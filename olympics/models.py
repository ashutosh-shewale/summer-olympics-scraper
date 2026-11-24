"""Plain data containers passed between the parser, the database layer and the analysis."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GamesLink:
    """A Games edition discovered on the index page: the unit of work in the scrape queue."""

    year: int
    url: str


@dataclass(frozen=True)
class MedalRow:
    """One nation's line in a Games medal table."""

    rank: int
    nation: str
    gold: int
    silver: int
    bronze: int
    total: int
    is_host: bool = False


@dataclass
class GamesRecord:
    """Everything extracted from a single Games page."""

    year: int
    url: str
    name: str
    host_city: str
    host_country: str
    nations_count: int
    athletes: int
    athletes_men: int | None
    athletes_women: int | None
    events: int
    sports_count: int
    nations: list[str] = field(default_factory=list)
    sports: list[str] = field(default_factory=list)
    medal_table: list[MedalRow] = field(default_factory=list)
