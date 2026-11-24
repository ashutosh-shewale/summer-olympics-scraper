"""SQLite storage that doubles as a work queue for concurrent scrapers.

Each Games row moves through ``pending -> in_progress -> done | failed``. Workers claim rows with
a single atomic UPDATE, so any number of threads or processes can share the queue without two of
them scraping the same page. (Reading a row and flagging it in a separate step would leave a window
in which two workers could pick the same row.)
"""

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .models import GamesLink, GamesRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    year            INTEGER PRIMARY KEY,
    url             TEXT    NOT NULL,
    name            TEXT,
    host_city       TEXT,
    host_country    TEXT,
    nations_count   INTEGER,
    athletes        INTEGER,
    athletes_men    INTEGER,
    athletes_women  INTEGER,
    events          INTEGER,
    sports_count    INTEGER,
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'done', 'failed')),
    error           TEXT,
    updated_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS participating_nations (
    year    INTEGER NOT NULL REFERENCES games(year) ON DELETE CASCADE,
    nation  TEXT    NOT NULL,
    PRIMARY KEY (year, nation)
);
CREATE TABLE IF NOT EXISTS sports (
    year    INTEGER NOT NULL REFERENCES games(year) ON DELETE CASCADE,
    sport   TEXT    NOT NULL,
    PRIMARY KEY (year, sport)
);
CREATE TABLE IF NOT EXISTS medal_table (
    year     INTEGER NOT NULL REFERENCES games(year) ON DELETE CASCADE,
    rank     INTEGER NOT NULL,
    nation   TEXT    NOT NULL,
    gold     INTEGER NOT NULL,
    silver   INTEGER NOT NULL,
    bronze   INTEGER NOT NULL,
    total    INTEGER NOT NULL,
    is_host  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (year, nation)
);
"""

# One statement both finds and claims a row, so the claim is atomic: SQLite serialises writers,
# and a row already flipped to 'in_progress' no longer matches the subquery for the next worker.
_CLAIM_NEXT = """
UPDATE games
   SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP
 WHERE year = (SELECT year FROM games WHERE status = 'pending' ORDER BY year LIMIT 1)
RETURNING year, url
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection tuned for several concurrent writers, creating the schema if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout = busy timeout: a writer waits up to 30s for the lock instead of failing immediately.
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL lets readers proceed while a writer commits, so workers rarely block each other.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def replace_queue(conn: sqlite3.Connection, links: Iterable[GamesLink]) -> None:
    """Start a fresh dataset: drop previous results and enqueue ``links`` as pending."""
    with conn:
        conn.execute("DELETE FROM games")  # child rows go too, via ON DELETE CASCADE
        conn.executemany("INSERT INTO games (year, url) VALUES (?, ?)", ((l.year, l.url) for l in links))


def requeue_all(conn: sqlite3.Connection) -> None:
    """Mark every queued Games as pending again (used to repeat benchmark runs on the same set)."""
    with conn:
        conn.execute("UPDATE games SET status = 'pending', error = NULL, updated_at = CURRENT_TIMESTAMP")


def claim_next(conn: sqlite3.Connection) -> GamesLink | None:
    """Atomically take the next pending Games, or return None when the queue is drained."""
    with conn:
        row = conn.execute(_CLAIM_NEXT).fetchone()
    return GamesLink(row["year"], row["url"]) if row else None


def save_record(conn: sqlite3.Connection, record: GamesRecord) -> None:
    """Store a parsed Games page and mark it done, all in one transaction."""
    with conn:
        conn.execute(
            """
            UPDATE games
               SET name = ?, host_city = ?, host_country = ?, nations_count = ?, athletes = ?,
                   athletes_men = ?, athletes_women = ?, events = ?, sports_count = ?,
                   status = 'done', error = NULL, updated_at = CURRENT_TIMESTAMP
             WHERE year = ?
            """,
            (
                record.name, record.host_city, record.host_country, record.nations_count,
                record.athletes, record.athletes_men, record.athletes_women, record.events,
                record.sports_count, record.year,
            ),
        )
        # Replace child rows so re-scraping a year never leaves stale entries behind.
        for table in ("participating_nations", "sports", "medal_table"):
            conn.execute(f"DELETE FROM {table} WHERE year = ?", (record.year,))
        conn.executemany(
            "INSERT INTO participating_nations (year, nation) VALUES (?, ?)",
            ((record.year, nation) for nation in record.nations),
        )
        conn.executemany(
            "INSERT INTO sports (year, sport) VALUES (?, ?)",
            ((record.year, sport) for sport in record.sports),
        )
        conn.executemany(
            """
            INSERT INTO medal_table (year, rank, nation, gold, silver, bronze, total, is_host)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (record.year, m.rank, m.nation, m.gold, m.silver, m.bronze, m.total, int(m.is_host))
                for m in record.medal_table
            ),
        )


def mark_failed(conn: sqlite3.Connection, year: int, error: str) -> None:
    """Record why a page could not be scraped, so one bad page never stops the run."""
    with conn:
        conn.execute(
            "UPDATE games SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP WHERE year = ?",
            (error, year),
        )


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Number of Games in each queue state, e.g. {'done': 14}."""
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM games GROUP BY status")
    return {row["status"]: row["n"] for row in rows}


def failures(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """(year, error) for every Games that failed to scrape."""
    rows = conn.execute("SELECT year, error FROM games WHERE status = 'failed' ORDER BY year")
    return [(row["year"], row["error"]) for row in rows]
