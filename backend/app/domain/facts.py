"""Loads the company fact sheet (data/company/facts.yaml)."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings

Facts = dict[str, Any]


def load_facts(path: Path) -> Facts:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def get_facts() -> Facts:
    return load_facts(get_settings().facts_path)
