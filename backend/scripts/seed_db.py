"""Rebuild the operational database for today.

Usage (from backend/):  uv run python -m scripts.seed_db
"""

from app.config import get_settings
from app.data.seed import build_database, company_today
from app.domain.facts import get_facts


def main() -> None:
    settings = get_settings()
    facts = get_facts()
    today = company_today(facts)
    counts = build_database(settings.db_path, facts, today)
    print(f"Seeded {settings.db_path} for {today}:")
    for table, n in counts.items():
        print(f"  {table:<12} {n:>6} rows")


if __name__ == "__main__":
    main()
