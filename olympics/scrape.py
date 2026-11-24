"""Orchestration: build the work queue, then drain it with one or many workers.

Every worker runs the same loop: claim a Games from the database, fetch its page, parse it and
save the result. Concurrency therefore needs no coordination beyond the database itself, and the
same loop runs unchanged on a single thread, on a thread pool or on a process pool.
"""

import logging
import random
import sqlite3
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Literal

import requests

from . import db
from .config import FIRST_YEAR, INDEX_URL, LAST_YEAR
from .fetch import fetch_html, make_session
from .models import GamesLink
from .parse import ParseError, parse_games_index, parse_games_page

Mode = Literal["sequential", "threads", "processes"]
MODES: tuple[Mode, ...] = ("sequential", "threads", "processes")

log = logging.getLogger(__name__)


def discover_games(sample: int | None = None, seed: int | None = None) -> list[GamesLink]:
    """Fetch the index page and return the Games to scrape, optionally a random sample of them."""
    links = parse_games_index(fetch_html(make_session(), INDEX_URL), FIRST_YEAR, LAST_YEAR)
    if sample is not None:
        links = sorted(random.Random(seed).sample(links, sample), key=lambda link: link.year)
    return links


def prepare_queue(db_path: Path, links: list[GamesLink]) -> None:
    """Reset the database so that exactly ``links`` are waiting to be scraped."""
    with closing(db.connect(db_path)) as conn:
        db.replace_queue(conn, links)


def run_workers(db_path: Path, mode: Mode, workers: int) -> None:
    """Drain the queue using ``workers`` concurrent workers of the given kind, then return.

    Returning only after every worker has exited answers "how do we know no worker is still
    running?" without polling the database.
    """
    if mode == "sequential":
        worker_loop(db_path)
        return
    executor_class: type[Executor] = ThreadPoolExecutor if mode == "threads" else ProcessPoolExecutor
    with executor_class(max_workers=workers) as pool:
        futures = [pool.submit(worker_loop, db_path) for _ in range(workers)]
        for future in futures:
            future.result()  # re-raise anything unexpected that escaped a worker


def worker_loop(db_path: Path) -> int:
    """Claim and scrape Games until none are pending; return how many this worker handled.

    Each worker owns its own SQLite connection and HTTP session: neither object is safe to share
    across threads, and neither can be sent to another process.
    """
    session = make_session()
    handled = 0
    with closing(db.connect(db_path)) as conn:
        while (link := db.claim_next(conn)) is not None:
            _scrape_one(conn, session, link)
            handled += 1
    return handled


def _scrape_one(conn: sqlite3.Connection, session: requests.Session, link: GamesLink) -> None:
    """Fetch, parse and store one Games; on an expected failure record it and keep going."""
    try:
        record = parse_games_page(fetch_html(session, link.url), link)
    except (requests.RequestException, ParseError) as exc:
        log.warning("failed to scrape %s: %s", link.url, exc)
        db.mark_failed(conn, link.year, f"{type(exc).__name__}: {exc}")
    else:
        db.save_record(conn, record)
        log.info("scraped %s", record.name)
