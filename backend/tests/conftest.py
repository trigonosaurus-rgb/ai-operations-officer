"""Shared fixtures.

The tests never call an LLM, never download the embedding model and never touch
`var/`: the database is seeded into a temp dir for a fixed date, settings ignore the
local `.env`, and the agent and document index are replaced with fakes where needed.
"""

from datetime import date
from pathlib import Path

import pytest

from app.agent.tools.database import OperationalDB
from app.config import REPO_ROOT, Settings
from app.data.seed import build_database
from app.domain.facts import Facts, load_facts

# A Wednesday. Pinning "today" makes every date-dependent assertion reproducible.
TODAY = date(2026, 10, 7)


@pytest.fixture(scope="session")
def facts() -> Facts:
    return load_facts(REPO_ROOT / "data" / "company" / "facts.yaml")


@pytest.fixture(scope="session")
def db_path(tmp_path_factory: pytest.TempPathFactory, facts: Facts) -> Path:
    """One seeded database shared by all read-only tests (building takes ~1 s)."""
    path = tmp_path_factory.mktemp("var") / "logistics.db"
    build_database(path, facts, TODAY)
    return path


@pytest.fixture
def db(db_path: Path) -> OperationalDB:
    return OperationalDB(db_path, row_limit=50)


@pytest.fixture
def settings(db_path: Path) -> Settings:
    # _env_file=None: a developer's .env (API key, rate limits…) must not change test results.
    return Settings(_env_file=None, var_dir=db_path.parent, rate_limit_enabled=False)
