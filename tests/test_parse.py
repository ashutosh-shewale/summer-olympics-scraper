"""Parser tests against real Wikipedia pages saved as fixtures (no network needed)."""

import pytest

from olympics.models import GamesLink
from olympics.parse import ParseError, parse_games_index, parse_games_page
from tests.conftest import load_fixture


@pytest.fixture(scope="module")
def games_1968():
    link = GamesLink(1968, "https://en.wikipedia.org/wiki/1968_Summer_Olympics")
    return parse_games_page(load_fixture("1968"), link)


@pytest.fixture(scope="module")
def games_2012():
    link = GamesLink(2012, "https://en.wikipedia.org/wiki/2012_Summer_Olympics")
    return parse_games_page(load_fixture("2012"), link)


def test_index_lists_every_summer_games_from_1968_to_2020():
    links = parse_games_index(load_fixture("index"), 1968, 2020)
    assert [link.year for link in links] == list(range(1968, 2021, 4))
    assert links[0].url == "https://en.wikipedia.org/wiki/1968_Summer_Olympics"


def test_infobox_fields(games_1968):
    assert games_1968.name == "1968 Summer Olympics"
    assert (games_1968.host_city, games_1968.host_country) == ("Mexico City", "Mexico")
    assert games_1968.nations_count == 112
    assert games_1968.athletes == 5516
    assert (games_1968.athletes_men, games_1968.athletes_women) == (4735, 781)
    assert (games_1968.events, games_1968.sports_count) == (172, 18)


def test_nations_list_matches_official_count(games_1968):
    assert len(games_1968.nations) == games_1968.nations_count
    assert "Kenya" in games_1968.nations


def test_sports_come_from_events_navbox(games_1968):
    assert {"Athletics", "Swimming", "Boxing"} <= set(games_1968.sports)
    assert not any(":" in sport for sport in games_1968.sports)  # no Template:/Category: links


def test_medal_table_top_rows(games_1968):
    top = games_1968.medal_table
    assert len(top) == 10
    assert (top[0].rank, top[0].nation, top[0].gold, top[0].total) == (1, "United States", 45, 107)
    assert top[1].nation == "Soviet Union"


def test_nation_count_written_as_a_sum(games_2012):
    # The 2012 infobox reads "204+2 (including 2 IOA teams)".
    assert games_2012.nations_count == 206


def test_host_nation_flagged_in_medal_table(games_2012):
    hosts = [row.nation for row in games_2012.medal_table if row.is_host]
    assert hosts == ["Great Britain"]


def test_page_without_infobox_raises_parse_error():
    with pytest.raises(ParseError, match="infobox"):
        parse_games_page("<html><h1>Not a Games page</h1></html>", GamesLink(1968, "x"))
