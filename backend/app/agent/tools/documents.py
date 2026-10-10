"""`search_documents` tool: hybrid retrieval over the policy PDFs.

Ingestion (once, cached in var/index):
    PDF ─► page text (headers/footers stripped) ─► ~400-token chunks ─► bge-small embeddings

Query time:
    question ─┬─► vector search (meaning)   ─┐
              └─► BM25 keyword search (terms)┴─► reciprocal rank fusion ─► top-k chunks

Vector search finds paraphrases ("late truck" ≈ "arrives after the grace period");
BM25 nails exact tokens the embedding model blurs ("UN3480", "HPL-OPS-002", "5.6").
"""

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml
from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.llms import MockLLM
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from llama_index.retrievers.bm25 import BM25Retriever
from pypdf import PdfReader

from app.agent.events import Citation
from app.config import Settings

log = logging.getLogger(__name__)

CHUNK_SIZE = 400
CHUNK_OVERLAP = 60
INDEX_VERSION = "1"  # bump when ingestion logic changes to force a rebuild


@dataclass
class SearchResult:
    """Tool output. `str()` is what the LLM sees; `citations` feed the UI."""

    query: str
    citations: list[Citation]

    def __str__(self) -> str:
        if not self.citations:
            return "No relevant passages found in the company documents."
        blocks = [
            f"[{c.n}] {c.title} ({c.doc_id}), page {c.page}:\n{c.snippet}" for c in self.citations
        ]
        return "\n\n".join(blocks)

    def to_ui(self) -> dict:
        return {"query": self.query, "citations": [c.model_dump() for c in self.citations]}


def load_manifest(path: Path) -> dict[str, dict]:
    docs = yaml.safe_load(path.read_text(encoding="utf-8"))["documents"]
    return {d["slug"]: d for d in docs}


def _strip_boilerplate(pages: list[str]) -> list[str]:
    """Drops lines that repeat on every page (running headers/footers)."""
    if len(pages) < 2:
        return pages

    def norm(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip())

    counts = Counter(norm(line) for page in pages for line in set(page.splitlines()))
    boilerplate = {line for line, n in counts.items() if n >= len(pages) and line}
    return ["\n".join(ln for ln in p.splitlines() if norm(ln) not in boilerplate) for p in pages]


def _load_documents(docs_dir: Path, manifest: dict[str, dict]) -> list[Document]:
    documents = []
    for slug, meta in manifest.items():
        reader = PdfReader(docs_dir / f"{slug}.pdf")
        pages = _strip_boilerplate([p.extract_text() or "" for p in reader.pages])
        for page_no, text in enumerate(pages, start=1):
            documents.append(
                Document(
                    text=text,
                    metadata={
                        "slug": slug,
                        "doc_id": meta["doc_id"],
                        "title": meta["title"],
                        "page": page_no,
                    },
                    # The title helps the embedding ("Hazmat Policy" chunk ≈ hazmat question);
                    # ids and page numbers are just noise for semantic similarity.
                    excluded_embed_metadata_keys=["slug", "doc_id", "page"],
                    excluded_llm_metadata_keys=["slug", "doc_id", "page"],
                )
            )
    return documents


def _fingerprint(settings: Settings, manifest: dict[str, dict]) -> str:
    h = hashlib.sha256(
        f"{INDEX_VERSION}|{settings.embed_model}|{CHUNK_SIZE}|{CHUNK_OVERLAP}".encode()
    )
    for slug in sorted(manifest):
        h.update((settings.docs_dir / f"{slug}.pdf").read_bytes())
    return h.hexdigest()[:16]


class DocumentIndex:
    def __init__(self, nodes: list[TextNode], index: VectorStoreIndex, top_k: int):
        self.nodes = nodes
        vector = index.as_retriever(similarity_top_k=top_k)
        bm25 = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=top_k)
        self.retriever = QueryFusionRetriever(
            [vector, bm25],
            mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=top_k,
            num_queries=1,  # no LLM query rewriting: keeps search fast and deterministic
            use_async=False,
            llm=MockLLM(),  # never called with num_queries=1, avoids resolving a default LLM
        )

    @classmethod
    def load_or_build(cls, settings: Settings) -> "DocumentIndex":
        manifest = load_manifest(settings.manifest_path)
        embed = FastEmbedEmbedding(
            model_name=settings.embed_model, cache_dir=str(settings.models_dir)
        )
        index_dir = settings.index_dir
        fingerprint = _fingerprint(settings, manifest)
        stamp = index_dir / "fingerprint.json"

        if stamp.exists() and json.loads(stamp.read_text())["fingerprint"] == fingerprint:
            log.info("Loading document index from %s", index_dir)
            storage = StorageContext.from_defaults(persist_dir=str(index_dir))
            index = load_index_from_storage(storage, embed_model=embed)
            nodes = list(index.docstore.docs.values())
        else:
            log.info("Building document index (sources changed or no cache)")
            documents = _load_documents(settings.docs_dir, manifest)
            splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
            nodes = splitter.get_nodes_from_documents(documents)
            index = VectorStoreIndex(nodes, embed_model=embed)
            index.storage_context.persist(persist_dir=str(index_dir))
            stamp.write_text(json.dumps({"fingerprint": fingerprint, "chunks": len(nodes)}))
        log.info("Document index ready: %d chunks from %d documents", len(nodes), len(manifest))
        return cls(nodes, index, settings.retrieval_top_k)

    def search(self, query: str) -> list[NodeWithScore]:
        return self.retriever.retrieve(query)
