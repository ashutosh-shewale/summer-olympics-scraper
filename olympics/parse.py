"""HTML -> data. Pure functions with no network or database access, so they are easy to test offline.

Robustness strategy: instead of positional lookups like "the 7th table on the page" (which break
whenever an editor adds a table), every value is located by a *semantic anchor* that Wikipedia
templates render the same way on every Games page:

* infobox rows are found by their label text ("Location", "Nations", "Athletes", "Events");
* nations and sports come from the standard navboxes ("Nations at the 1968 Summer Olympics", ...),
  whose links all follow the ``<Thing>_at_the_<year>_Summer_Olympics`` URL convention;
* the medal table is the ``wikitable`` whose header row reads Rank / Gold / Silver / Bronze.
"""

import re
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from .config import MEDAL_TABLE_DEPTH, WIKI_BASE
from .models import GamesLink, GamesRecord, MedalRow

# Wikipedia emits both absolute ("https://en.wikipedia.org/wiki/...") and relative ("/wiki/...") hrefs.
_WIKI_PATH = r"^(?:https?://en\.wikipedia\.org)?/wiki/"
_GAMES_HREF = re.compile(_WIKI_PATH + r"(\d{4})_Summer_Olympics$")
_FOOTNOTE = re.compile(r"\[[^\]]*\]")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.)])")
_EVENTS = re.compile(r"([\d,]+)\s+in\s+([\d,]+)\s+sports")
_MEN_WOMEN = re.compile(r"([\d,]+)\s+men,\s*([\d,]+)\s+women")
# Leading count, optionally written as a sum, e.g. "204+2 (including 2 IOA teams)".
_LEADING_SUM = re.compile(r"^\s*(\d[\d,]*(?:\s*\+\s*\d[\d,]*)*)")


class ParseError(ValueError):
    """Raised when a page lacks a section the record cannot do without."""


def parse_games_index(html: str, first_year: int, last_year: int) -> list[GamesLink]:
    """Return one link per Summer Games held between ``first_year`` and ``last_year``, by year."""
    soup = BeautifulSoup(html, "html.parser")
    years = {
        int(_GAMES_HREF.match(anchor["href"]).group(1))
        for anchor in soup.find_all("a", href=_GAMES_HREF)
    }
    return [
        GamesLink(year, f"{WIKI_BASE}/wiki/{year}_Summer_Olympics")
        for year in sorted(years)
        if first_year <= year <= last_year
    ]


def parse_games_page(html: str, link: GamesLink) -> GamesRecord:
    """Extract a full :class:`GamesRecord` from one Games article."""
    soup = BeautifulSoup(html, "html.parser")
    infobox = _infobox_fields(soup)
    host_city, host_country = _split_location(_require(infobox, "Location"))
    events, sports_count = _parse_events(_require(infobox, "Events"))
    athletes_text = _require(infobox, "Athletes")
    men, women = _parse_men_women(athletes_text)
    games_href = _per_games_href(link.year)

    return GamesRecord(
        year=link.year,
        url=link.url,
        name=_clean_text(soup.find("h1")),
        host_city=host_city,
        host_country=host_country,
        nations_count=_leading_count(_require(infobox, "Nations")),
        athletes=_leading_count(athletes_text),
        athletes_men=men,
        athletes_women=women,
        events=events,
        sports_count=sports_count,
        nations=_navbox_entries(soup, rf"(National_Olympic_Committees|Nations)_at_the_{link.year}_", games_href),
        sports=_navbox_entries(soup, rf"Events_at_the_{link.year}_", games_href),
        medal_table=_parse_medal_table(soup, games_href),
    )


# --- infobox -----------------------------------------------------------------------------------


def _infobox_fields(soup: BeautifulSoup) -> dict[str, str]:
    """Map each infobox label (e.g. "Athletes") to its cleaned value text."""
    infobox = soup.find("table", class_="infobox")
    if infobox is None:
        raise ParseError("page has no infobox")
    fields = {}
    for row in infobox.find_all("tr"):
        label = row.find("th", class_="infobox-label")
        value = row.find("td", class_="infobox-data")
        if label and value:
            fields[_clean_text(label)] = _clean_text(value)
    return fields


def _require(fields: dict[str, str], label: str) -> str:
    """Fetch a mandatory infobox field, failing with a message that names what is missing."""
    try:
        return fields[label]
    except KeyError:
        raise ParseError(f"infobox has no '{label}' row") from None


def _split_location(location: str) -> tuple[str, str]:
    """Split "Mexico City, Mexico" into ("Mexico City", "Mexico")."""
    city, _, country = location.partition(",")
    return city.strip(), country.strip()


def _parse_events(text: str) -> tuple[int, int]:
    """Parse "172 in 18 sports (24 disciplines)" into (events, sports)."""
    match = _EVENTS.search(text)
    if match is None:
        raise ParseError(f"unrecognised Events value: {text!r}")
    return _to_int(match.group(1)), _to_int(match.group(2))


def _parse_men_women(text: str) -> tuple[int | None, int | None]:
    """Parse the "(4,735 men, 781 women)" breakdown; optional because not every page gives it."""
    match = _MEN_WOMEN.search(text)
    if match is None:
        return None, None
    return _to_int(match.group(1)), _to_int(match.group(2))


def _leading_count(text: str) -> int:
    """Read the number a field starts with, summing forms like "204+2"."""
    match = _LEADING_SUM.match(text)
    if match is None:
        raise ParseError(f"expected a leading number in {text!r}")
    return sum(_to_int(part) for part in match.group(1).split("+"))


# --- navboxes ----------------------------------------------------------------------------------


def _per_games_href(year: int) -> re.Pattern[str]:
    """Match links like ``/wiki/Kenya_at_the_1968_Summer_Olympics`` and capture ``Kenya``.

    ``[^/:]`` excludes namespaced links such as the navbox's own ``Template:`` edit links.
    """
    return re.compile(_WIKI_PATH + rf"([^/:]+)_at_the_{year}_Summer_Olympics$")


def _navbox_entries(soup: BeautifulSoup, label_pattern: str, games_href: re.Pattern[str]) -> list[str]:
    """Return the distinct entries linked from the navbox whose label matches ``label_pattern``."""
    label = re.compile(rf"^(30px_)?{label_pattern}")
    navbox = next(
        (box for box in soup.select("div.navbox[aria-labelledby]") if label.search(box["aria-labelledby"])),
        None,
    )
    if navbox is None:
        raise ParseError(f"no navbox labelled like {label_pattern!r}")
    entries = (_name_from_href(anchor["href"], games_href) for anchor in navbox.find_all("a", href=games_href))
    return list(dict.fromkeys(entries))  # de-duplicate, keep page order


def _name_from_href(href: str, games_href: re.Pattern[str]) -> str:
    """Use the canonical article slug ("Soviet_Union") rather than display text ("URS"/"USSR").

    Display text varies between sections of the same page; the slug does not, which lets the
    nations list and the medal table be joined on the same name.
    """
    return unquote(games_href.match(href).group(1)).replace("_", " ")


# --- medal table -------------------------------------------------------------------------------


def _parse_medal_table(soup: BeautifulSoup, games_href: re.Pattern[str]) -> list[MedalRow]:
    """Return the top rows of the medal table, carrying tied ranks across merged cells."""
    table = _find_medal_table(soup)
    rows: list[MedalRow] = []
    rank = 0
    for tr in table.find_all("tr")[1:]:
        nation_link = tr.find("a", href=games_href)
        if nation_link is None:  # e.g. the "Totals" footer row
            continue
        numbers = [_to_int(_clean_text(td)) for td in tr.find_all("td")]
        # Tied nations share one rank cell via rowspan, so later tied rows have only 4 numbers.
        if len(numbers) == 5:
            rank, *numbers = numbers
        gold, silver, bronze, total = numbers
        nation_cell = nation_link.find_parent(["th", "td"])
        rows.append(
            MedalRow(
                rank=rank,
                nation=_name_from_href(nation_link["href"], games_href),
                gold=gold,
                silver=silver,
                bronze=bronze,
                total=total,
                is_host="*" in nation_cell.get_text(),  # Wikipedia marks the host nation with *
            )
        )
        if len(rows) == MEDAL_TABLE_DEPTH:
            break
    return rows


def _find_medal_table(soup: BeautifulSoup) -> Tag:
    """Locate the medal table by its header row rather than by position on the page."""
    for table in soup.find_all("table", class_="wikitable"):
        header = table.find("tr").get_text(" ", strip=True)
        if all(column in header for column in ("Rank", "Gold", "Silver", "Bronze")):
            return table
    raise ParseError("no medal table found")


# --- text helpers ------------------------------------------------------------------------------


def _clean_text(tag: Tag) -> str:
    """Visible text without footnote markers like "[1]" and with tidy spacing."""
    text = _FOOTNOTE.sub("", tag.get_text(" ", strip=True))
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return " ".join(text.split())


def _to_int(text: str) -> int:
    """Parse "5,516" -> 5516."""
    return int(text.replace(",", "").strip())
