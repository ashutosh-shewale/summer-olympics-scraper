"""Shared test helpers: offline HTML fixtures and a throwaway database."""

import gzip
from contextlib import closing
from pathlib import Path

import pytest

from olympics import db

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Return a saved Wikipedia page (stored gzipped to keep the repository small)."""
    return gzip.decompress((FIXTURES / f"{name}.html.gz").read_bytes()).decode("utf-8")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path):
    with closing(db.connect(db_path)) as connection:
        yield connection
