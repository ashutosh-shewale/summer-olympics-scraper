"""Work-queue behaviour, including the concurrency guarantee the scraper relies on."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from olympics import db
from olympics.models import GamesLink, GamesRecord, MedalRow


def _links(count: int) -> list[GamesLink]:
    return [GamesLink(1900 + i, f"https://example.org/{i}") for i in range(count)]


def _record(year: int) -> GamesRecord:
    return GamesRecord(
        year=year, url=f"https://example.org/{year}", name=f"{year} Summer Olympics",
        host_city="City", host_country="Country", nations_count=2, athletes=100,
        athletes_men=60, athletes_women=40, events=10, sports_count=3,
        nations=["A", "B"], sports=["Rowing"],
        medal_table=[MedalRow(1, "A", 5, 3, 1, 9, is_host=True)],
    )


def test_claims_follow_year_order_and_stop_when_drained(conn):
    db.replace_queue(conn, _links(2))
    assert db.claim_next(conn).year == 1900
    assert db.claim_next(conn).year == 1901
    assert db.claim_next(conn) is None
    assert db.status_counts(conn) == {"in_progress": 2}


def test_concurrent_workers_never_claim_the_same_row(db_path):
    """Read-then-flag claiming would let two workers pick up the same Games; this must not."""
    with closing(db.connect(db_path)) as conn:
        db.replace_queue(conn, _links(200))

    def drain() -> list[int]:
        with closing(db.connect(db_path)) as conn:
            claimed = []
            while (link := db.claim_next(conn)) is not None:
                claimed.append(link.year)
            return claimed

    with ThreadPoolExecutor(max_workers=8) as pool:
        per_worker = list(pool.map(lambda _: drain(), range(8)))

    all_claims = [year for claims in per_worker for year in claims]
    assert len(all_claims) == 200
    assert len(set(all_claims)) == 200


def test_save_record_marks_done_and_replaces_child_rows(conn):
    db.replace_queue(conn, _links(1))
    db.claim_next(conn)
    db.save_record(conn, _record(1900))
    db.save_record(conn, _record(1900))  # re-saving must not duplicate child rows

    assert db.status_counts(conn) == {"done": 1}
    assert conn.execute("SELECT COUNT(*) FROM participating_nations").fetchone()[0] == 2
    assert conn.execute("SELECT is_host FROM medal_table").fetchone()[0] == 1


def test_failures_are_recorded_with_their_error(conn):
    db.replace_queue(conn, _links(1))
    db.claim_next(conn)
    db.mark_failed(conn, 1900, "HTTPError: 503")
    assert db.failures(conn) == [(1900, "HTTPError: 503")]


def test_replace_queue_discards_previous_results(conn):
    db.replace_queue(conn, _links(1))
    db.claim_next(conn)
    db.save_record(conn, _record(1900))
    db.replace_queue(conn, [GamesLink(2000, "https://example.org/2000")])

    assert db.status_counts(conn) == {"pending": 1}
    assert conn.execute("SELECT COUNT(*) FROM medal_table").fetchone()[0] == 0  # cascaded


def test_requeue_all_resets_every_row_to_pending(conn):
    db.replace_queue(conn, _links(3))
    while db.claim_next(conn):
        pass
    db.requeue_all(conn)
    assert db.status_counts(conn) == {"pending": 3}
