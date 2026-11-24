"""Render the trend charts embedded in the README (static PNGs, light surface)."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: charts are written to files, never shown in a window
import matplotlib.pyplot as plt
from matplotlib.axes import Axes

from .analysis import GamesSummary

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
# Categorical slots in fixed order; a nation keeps its colour in every chart.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BOYCOTT_YEARS = (1976, 1980, 1984)

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT_SECONDARY,
    "axes.titlecolor": TEXT_PRIMARY,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,  # grid lines sit behind the data, never across bars
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": TEXT_SECONDARY,
    "ytick.color": TEXT_SECONDARY,
    "font.size": 10,
})


def render_all(
    summaries: list[GamesSummary],
    top3: list[tuple[str, int]],
    leaders: list[tuple[int, str, int]],
    out_dir: Path,
) -> list[Path]:
    """Write every chart to ``out_dir`` and return the file paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return [
        _save(_growth(summaries), out_dir / "growth.png"),
        _save(_women_share(summaries), out_dir / "women_share.png"),
        _save(_top3(top3), out_dir / "top3_appearances.png"),
        _save(_leaders(leaders), out_dir / "medal_table_leaders.png"),
    ]


def _growth(summaries: list[GamesSummary]) -> plt.Figure:
    """Athletes, nations and events as small multiples (three scales, so never one dual axis)."""
    years = [s.year for s in summaries]
    panels = [
        ("Athletes", [s.athletes for s in summaries]),
        ("Participating nations", [s.nations for s in summaries]),
        ("Medal events", [s.events for s in summaries]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    for ax, (title, values) in zip(axes, panels):
        _year_line(ax, years, values)
        ax.set_title(title)
        _label_ends(ax, years, values)
    # The boycott dip is the story of the nations panel, so call it out where it happens.
    nations_ax = axes[1]
    nations_ax.axvspan(BOYCOTT_YEARS[0] - 1, BOYCOTT_YEARS[-1] + 1, color=GRID, alpha=0.6, linewidth=0, zorder=0)
    nations_ax.text(sum(BOYCOTT_YEARS) / len(BOYCOTT_YEARS), 12, "boycotts\n1976–84",
                    ha="center", va="bottom", color=TEXT_SECONDARY, fontsize=9)
    fig.suptitle("Summer Olympics 1968–2020: the Games roughly doubled", x=0.01, ha="left",
                 fontsize=13, fontweight="bold", color=TEXT_PRIMARY)
    fig.tight_layout()
    return fig


def _women_share(summaries: list[GamesSummary]) -> plt.Figure:
    """Share of athletes who were women, against the parity line."""
    points = [(s.year, s.women_share) for s in summaries if s.women_share is not None]
    years, shares = zip(*points)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.axhline(50, color=TEXT_SECONDARY, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(years[0], 50.8, "parity (50%)", color=TEXT_SECONDARY, fontsize=9)
    _year_line(ax, years, shares)
    _label_ends(ax, years, shares, fmt="{:.0f}%")
    ax.set_ylim(0, 55)
    ax.set_ylabel("% of athletes")
    ax.set_title("Women's share of Olympic athletes")
    fig.tight_layout()
    return fig


def _top3(top3: list[tuple[str, int]]) -> plt.Figure:
    """Horizontal bars: how many Games each nation finished in the medal-table top 3."""
    nations, counts = zip(*reversed(top3))  # reversed so the largest bar sits on top
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(nations) + 1.2))
    bars = ax.barh(nations, counts, color=SERIES[0], height=0.6)
    ax.bar_label(bars, padding=4, color=TEXT_PRIMARY)
    ax.grid(axis="y", visible=False)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.set_xlabel("Games finished in the top 3 of the medal table")
    ax.set_title("Who reaches the podium of the medal table?")
    fig.tight_layout()
    return fig


def _leaders(leaders: list[tuple[int, str, int]]) -> plt.Figure:
    """Gold medals won by each Games' medal-table winner, coloured by nation."""
    nations = list(dict.fromkeys(nation for _, nation, _ in leaders))  # first-appearance order
    colour = {nation: SERIES[i] for i, nation in enumerate(nations)}
    fig, ax = plt.subplots(figsize=(10, 4.2))
    # One bar call per nation gives one legend entry each; numeric x keeps bars chronological.
    for nation in nations:
        rows = [(x, gold) for x, (_, n, gold) in enumerate(leaders) if n == nation]
        bars = ax.bar([x for x, _ in rows], [g for _, g in rows], color=colour[nation], width=0.7, label=nation)
        ax.bar_label(bars, padding=2, color=TEXT_PRIMARY, fontsize=9)
    ax.set_xticks(range(len(leaders)), [str(year) for year, _, _ in leaders])
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("Gold medals")
    ax.set_title("Medal-table winner of each Games, by gold medals")
    ax.legend(frameon=False, loc="upper left", ncols=len(nations))
    ax.set_ylim(0, max(g for _, _, g in leaders) * 1.2)
    fig.tight_layout()
    return fig


def _year_line(ax: Axes, years, values) -> None:
    """A single-series time line with markers on every Games and the Olympic years as ticks."""
    ax.plot(years, values, color=SERIES[0], linewidth=2, marker="o", markersize=5)
    ax.set_xticks(years[::2])
    # Extra room on the right for the end label.
    ax.set_xlim(years[0] - 3, years[-1] + 9)
    ax.set_ylim(bottom=0)


def _label_ends(ax: Axes, years, values, fmt: str = "{:,}") -> None:
    """Direct-label only the first and last points: the 50-year change is the point.

    Both trends rise from the start, so the first label goes below the line and the last one
    to the right of the final marker, where neither can collide with the line.
    """
    ax.annotate(fmt.format(values[0]), xy=(years[0], values[0]), xytext=(4, -14),
                textcoords="offset points", ha="left", color=TEXT_PRIMARY, fontsize=9)
    ax.annotate(fmt.format(values[-1]), xy=(years[-1], values[-1]), xytext=(7, 0),
                textcoords="offset points", ha="left", va="center", color=TEXT_PRIMARY, fontsize=9)


def _save(fig: plt.Figure, path: Path) -> Path:
    """Write a figure at README-friendly resolution and free its memory."""
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
