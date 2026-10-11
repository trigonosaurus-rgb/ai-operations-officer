"""Write the API contract to frontend/lib/api/openapi.json (no server needed).

The frontend generates its TypeScript types from this file (`npm run gen:api`),
so backend models are the single source of truth for both sides.

Run (from backend/):  uv run python -m scripts.export_openapi
"""

import json

from app.config import REPO_ROOT
from app.main import app

OUT = REPO_ROOT / "frontend" / "lib" / "api" / "openapi.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
