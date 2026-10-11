"""Build (or verify) the cached document index.

Usage (from backend/):  uv run python -m scripts.build_index
The API builds the index on startup when it is missing, so this is optional
locally; the Docker image runs it at build time to bake the index in.
"""

import logging

from app.agent.tools.documents import DocumentIndex
from app.config import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    index = DocumentIndex.load_or_build(get_settings())
    for hit in index.search("lithium battery carrier requirements")[:3]:
        meta = hit.node.metadata
        print(f"  {hit.score:.3f}  {meta['doc_id']} p.{meta['page']}")


if __name__ == "__main__":
    main()
