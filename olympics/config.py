"""Central configuration: what to scrape, where to store it, and how to behave on the network."""

from pathlib import Path

WIKI_BASE = "https://en.wikipedia.org"
INDEX_URL = f"{WIKI_BASE}/wiki/Summer_Olympic_Games"

# "The last 50 years": every Summer Games from 1968 to 2020.
FIRST_YEAR = 1968
LAST_YEAR = 2020

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "olympics.db"
IMAGES_DIR = PROJECT_ROOT / "docs" / "images"
BENCHMARK_REPORT = PROJECT_ROOT / "docs" / "benchmark.md"

# Wikimedia asks automated clients to identify themselves; generic library UAs may be throttled.
USER_AGENT = "OlympicsScraper/1.0 (educational data-analysis project; python-requests)"
REQUEST_TIMEOUT_SECONDS = 30

# How many rows of each Games' medal table to keep (Wikipedia pages show the top 10).
MEDAL_TABLE_DEPTH = 10
