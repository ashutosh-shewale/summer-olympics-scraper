"""Command-line interface: ``python -m olympics {scrape,status,analyze,benchmark}``."""

import argparse
import logging
import time
from contextlib import closing
from pathlib import Path

from . import analysis, db
from .config import BENCHMARK_REPORT, DEFAULT_DB_PATH, IMAGES_DIR
from .scrape import MODES, discover_games, prepare_queue, run_workers


def main() -> None:
    """Parse arguments and dispatch to the chosen sub-command."""
    args = _build_parser().parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(threadName)s %(message)s", datefmt="%H:%M:%S")
    args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m olympics", description=__doc__)
    parser.set_defaults(log_level=logging.INFO)
    sub = parser.add_subparsers(required=True, metavar="command")

    scrape = sub.add_parser("scrape", help="discover the Games and populate the database")
    scrape.add_argument("--mode", choices=MODES, default="threads")
    scrape.add_argument("--workers", type=int, default=4, help="concurrent workers (ignored when sequential)")
    scrape.add_argument("--sample", type=int, help="scrape only N randomly chosen Games")
    scrape.add_argument("--seed", type=int, help="random seed for --sample, for reproducible picks")
    _add_db_argument(scrape, DEFAULT_DB_PATH)
    scrape.set_defaults(handler=_cmd_scrape)

    status = sub.add_parser("status", help="show how many Games are pending, done or failed")
    _add_db_argument(status, DEFAULT_DB_PATH)
    status.set_defaults(handler=_cmd_status)

    analyze = sub.add_parser("analyze", help="print the statistics and render the charts")
    analyze.add_argument("--no-charts", action="store_true", help="skip writing PNGs to docs/images")
    _add_db_argument(analyze, DEFAULT_DB_PATH)
    analyze.set_defaults(handler=_cmd_analyze)

    bench = sub.add_parser("benchmark", help="time sequential vs threaded vs multi-process scraping")
    bench.add_argument("--threads", type=int, nargs="*", default=[2, 4, 8], help="thread-pool sizes to try")
    bench.add_argument("--processes", type=int, nargs="*", default=[4], help="process-pool sizes to try")
    bench.add_argument("--repeats", type=int, default=3)
    # A separate database, so benchmarking never disturbs the dataset used for analysis.
    _add_db_argument(bench, DEFAULT_DB_PATH.with_name("benchmark.db"))
    # Per-page log lines would bury the timing output, so only warnings are shown.
    bench.set_defaults(handler=_cmd_benchmark, log_level=logging.WARNING)
    return parser


def _add_db_argument(parser: argparse.ArgumentParser, default: Path) -> None:
    parser.add_argument("--db", type=Path, default=default, help=f"SQLite file (default: {default.name})")


def _cmd_scrape(args: argparse.Namespace) -> None:
    links = discover_games(args.sample, args.seed)
    prepare_queue(args.db, links)
    print(f"Queued {len(links)} Games: {', '.join(str(link.year) for link in links)}")
    start = time.perf_counter()
    run_workers(args.db, args.mode, args.workers)
    print(f"Populated the database in {time.perf_counter() - start:.2f}s ({args.mode}, {args.workers} workers)")
    _cmd_status(args)


def _cmd_status(args: argparse.Namespace) -> None:
    with closing(db.connect(args.db)) as conn:
        counts = db.status_counts(conn)
        failed = db.failures(conn)
    print("Queue: " + (", ".join(f"{state}={n}" for state, n in sorted(counts.items())) or "empty"))
    for year, error in failed:
        print(f"  {year} failed: {error}")


def _cmd_analyze(args: argparse.Namespace) -> None:
    with closing(db.connect(args.db)) as conn:
        summaries = analysis.games_summaries(conn)
        if not summaries:
            raise SystemExit("No scraped Games in the database yet; run `python -m olympics scrape` first.")
        overview = analysis.dataset_overview(conn)
        top3 = analysis.top3_appearances(conn, limit=10)
        leaders = analysis.medal_table_leaders(conn)
        hosts = analysis.host_results(conn)

    _print_overview(overview)
    _print_trends(summaries)
    _print_medal_insights(top3, leaders, hosts)
    if not args.no_charts:
        from .charts import render_all  # imported lazily: matplotlib is slow to load

        for path in render_all(summaries, top3, leaders, IMAGES_DIR):
            print(f"Wrote {path}")


def _print_overview(overview: analysis.DatasetOverview) -> None:
    print("\n== Dataset overview ==")
    print("Years in the database:", ", ".join(map(str, overview.years)))
    leaders = ", ".join(f"{nation} ({count} times)" for nation, count in overview.most_frequent_top3)
    print("Most often in the medal-table top 3:", leaders)
    print(f"Average number of athletes: {overview.average_athletes:,.0f}")


def _print_trends(summaries: list[analysis.GamesSummary]) -> None:
    first, last = summaries[0], summaries[-1]
    print(f"\n== Trends {first.year} -> {last.year} ==")
    for label, a, b in (
        ("Athletes", first.athletes, last.athletes),
        ("Nations", first.nations, last.nations),
        ("Events", first.events, last.events),
    ):
        print(f"{label:<9} {a:>6,} -> {b:>6,}  ({analysis.percent_change(a, b):+.0f}%)")
    if first.women_share is not None and last.women_share is not None:
        print(f"Women     {first.women_share:>5}% -> {last.women_share:>5}% of athletes")
    lowest = min(summaries, key=lambda s: s.nations)
    print(f"Fewest nations: {lowest.nations} in {lowest.year} ({lowest.host_city})")


def _print_medal_insights(
    top3: list[tuple[str, int]], leaders: list[tuple[int, str, int]], hosts: list[analysis.HostResult]
) -> None:
    print("\n== Medal tables ==")
    print("Top-3 finishes:", ", ".join(f"{nation} {count}" for nation, count in top3))
    print("Medal-table winners:", ", ".join(f"{year} {nation}" for year, nation, _ in leaders))
    print("Host nations in their own top 10:", ", ".join(f"{h.year} {h.nation} (#{h.rank})" for h in hosts))


def _cmd_benchmark(args: argparse.Namespace) -> None:
    from .benchmark import run_benchmark, write_report

    results, pages = run_benchmark(args.db, args.threads, args.processes, args.repeats)
    write_report(results, pages, args.repeats, BENCHMARK_REPORT)
    print()
    for r in results:
        print(f"{r.config.label:<14} median {r.median:6.2f}s  speed-up {r.speedup_factor:4.2f}x  time saved {r.speedup_pct:+5.1f}%")
    print(f"Report written to {BENCHMARK_REPORT}")


# The guard matters on Windows/macOS: ProcessPoolExecutor starts workers by re-importing the
# main module, and without it each worker would try to run the CLI again.
if __name__ == "__main__":
    main()
