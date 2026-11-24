"""HTTP layer: a polite, resilient session for fetching Wikipedia pages."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import REQUEST_TIMEOUT_SECONDS, USER_AGENT


def make_session() -> requests.Session:
    """Create a session with a descriptive User-Agent and retry/backoff on transient errors.

    A Session reuses TCP/TLS connections, which matters when one worker fetches several pages.
    Sessions are not shared across threads, so every worker creates its own.
    """
    retry = Retry(
        total=3,
        backoff_factor=1.0,  # waits 0s, 2s, 4s between attempts
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_html(session: requests.Session, url: str) -> str:
    """GET a page and return its HTML, raising on HTTP errors so callers can record the failure."""
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text
