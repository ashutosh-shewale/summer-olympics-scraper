"""Analysis queries on a small hand-built dataset with known answers."""

import pytest

from olympics import analysis, db
from olympics.models import GamesLink, GamesRecord, MedalRow


def _games(year: int, athletes: int, women: int, podium: list[str], host: str | None = None) -> GamesRecord:
    medal_table = [
        MedalRow(rank, nation, 10 - rank, 5, 5, 20 - rank, is_host=(nation == host))
        for rank, nation in enumerate(podium, start=1)
    ]
    return GamesRecord(
        year=year, url=f"https://example.org/{year}", name=f"{year} Summer Olympics",
        host_city="City", host_country="Country", nations_count=len(podium) * 10,
        athletes=athletes, athletes_men=athletes - women, athletes_women=women,
        events=100, sports_count=20, medal_table=medal_table,
    )


@pytest.fixture
def seeded(conn):
    records = [
        _games(2000, 1000, 100, ["A", "B", "C"]),
        _games(2004, 2000, 500, ["B", "A", "D"], host="D"),
        _games(2008, 3000, 1500, ["A", "C", "B"]),
    ]
    db.replace_queue(conn, [GamesLink(r.year, r.url) for r in records])
    for record in records:
        db.claim_next(conn)
        db.save_record(conn, record)
    return conn


def test_dataset_overview(seeded):
    answers = analysis.dataset_overview(seeded)
    assert answers.years == [2000, 2004, 2008]
    # A and B both reached the top 3 three times: a tie is reported, not hidden.
    assert answers.most_frequent_top3 == [("A", 3), ("B", 3)]
    assert answers.average_athletes == pytest.approx(2000)


def test_top3_appearances_ordered_by_count(seeded):
    assert analysis.top3_appearances(seeded, limit=3) == [("A", 3), ("B", 3), ("C", 2)]


def test_women_share_and_leaders(seeded):
    shares = [s.women_share for s in analysis.games_summaries(seeded)]
    assert shares == [10.0, 25.0, 50.0]
    assert [nation for _, nation, _ in analysis.medal_table_leaders(seeded)] == ["A", "B", "A"]


def test_host_results(seeded):
    assert analysis.host_results(seeded) == [analysis.HostResult(2004, "D", 3, 17)]


def test_percent_change():
    assert analysis.percent_change(50, 75) == pytest.approx(50.0)
