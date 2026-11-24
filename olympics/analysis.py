"""Statistics over the scraped data. Aggregation happens in SQL; functions return data, not text."""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class GamesSummary:
    """Headline numbers for one Games, ordered by year in every list this module returns."""

    year: int
    host_city: str
    host_country: str
    nations: int
    athletes: int
    women_share: float | None  # percentage of athletes who were women
    events: int
    sports: int


@dataclass(frozen=True)
class DatasetOverview:
    """Headline answers about the whole dataset."""

    years: list[int]
    most_frequent_top3: list[tuple[str, int]]  # every nation tied for the most top-3 finishes
    average_athletes: float


@dataclass(frozen=True)
class HostResult:
    """How a host nation finished in its own medal table (only hosts that reached the top 10)."""

    year: int
    nation: str
    rank: int
    total_medals: int


def games_summaries(conn: sqlite3.Connection) -> list[GamesSummary]:
    """One summary per successfully scraped Games."""
    rows = conn.execute(
        """
        SELECT year, host_city, host_country, nations_count, athletes, events, sports_count,
               ROUND(100.0 * athletes_women / athletes, 1) AS women_share
          FROM games
         WHERE status = 'done'
         ORDER BY year
        """
    )
    return [
        GamesSummary(
            year=r["year"], host_city=r["host_city"], host_country=r["host_country"],
            nations=r["nations_count"], athletes=r["athletes"], women_share=r["women_share"],
            events=r["events"], sports=r["sports_count"],
        )
        for r in rows
    ]


def dataset_overview(conn: sqlite3.Connection) -> DatasetOverview:
    """Years in the dataset, the nation(s) most often in the top 3, and the mean athlete count."""
    years = [row[0] for row in conn.execute("SELECT year FROM games WHERE status = 'done' ORDER BY year")]
    average = conn.execute("SELECT AVG(athletes) FROM games WHERE status = 'done'").fetchone()[0]
    appearances = top3_appearances(conn)
    best = appearances[0][1] if appearances else 0
    # Report ties rather than silently picking one nation.
    leaders = [(nation, count) for nation, count in appearances if count == best]
    return DatasetOverview(years=years, most_frequent_top3=leaders, average_athletes=average or 0.0)


def top3_appearances(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple[str, int]]:
    """Nations ranked by how many Games they finished in the medal-table top 3."""
    rows = conn.execute(
        """
        SELECT nation, COUNT(*) AS finishes
          FROM medal_table
         WHERE rank <= 3
         GROUP BY nation
         ORDER BY finishes DESC, nation
         LIMIT ?
        """,
        (limit if limit is not None else -1,),  # SQLite treats LIMIT -1 as "no limit"
    )
    return [(row["nation"], row["finishes"]) for row in rows]


def medal_table_leaders(conn: sqlite3.Connection) -> list[tuple[int, str, int]]:
    """(year, nation, golds) for the nation that topped each Games' medal table."""
    rows = conn.execute("SELECT year, nation, gold FROM medal_table WHERE rank = 1 ORDER BY year")
    return [(row["year"], row["nation"], row["gold"]) for row in rows]


def host_results(conn: sqlite3.Connection) -> list[HostResult]:
    """Host nations that finished in their own Games' top 10, to illustrate home advantage."""
    rows = conn.execute(
        "SELECT year, nation, rank, total FROM medal_table WHERE is_host = 1 ORDER BY year"
    )
    return [HostResult(row["year"], row["nation"], row["rank"], row["total"]) for row in rows]


def percent_change(first: float, last: float) -> float:
    """Relative growth from ``first`` to ``last``, in percent."""
    return 100.0 * (last - first) / first
