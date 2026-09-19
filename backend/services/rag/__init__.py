"""Retrieval-Augmented Generation over EcoSentinel's own verifiable knowledge.

    knowledge/*.md              corpus — knowledge already encoded in this codebase
        │
        ▼  loader.py            stage 1 — load documents + front matter (title, domain, source)
        ▼  chunker.py           stage 2 — heading-aligned chunks, stable `document#section` ids
        ▼  embeddings.py        stage 3 — TF-IDF sparse lexical vectors (numpy only)
        ▼  store.py             stage 4/5 — in-memory vector store, cosine top-k, relevance floor
        ▼  retriever.py         stage 6 — deterministic query construction from structured evidence
        ▼                       grounded context, cited by chunk id, shown in the UI

The corpus is deliberately restricted to knowledge this project can stand behind: thresholds it
already encodes, metrics it already measured, policies it already documented. Every document
names the repository file it came from, so every citation resolves to something a reader can open.
No external publication is quoted and nothing was fetched from the web — a citation nobody can
check is worse than none, because it makes an unverified claim look verified.

Retrieved knowledge is CONTEXT, not evidence. It never enters the evidence list, never carries
severity, and cannot move a risk score — the same rule geographic context follows.
"""

from services.rag.retriever import (  # noqa: F401
    build_query,
    format_context,
    retrieve_for_evidence,
    search_knowledge,
)
from services.rag.store import DEFAULT_TOP_K, MIN_SCORE, RetrievalResult, get_store  # noqa: F401


def status() -> dict:
    """Corpus health for GET /api/ai/status. Never raises."""
    try:
        return get_store().status()
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "documents": 0,
            "chunks": 0,
            "embedding": "tfidf-sparse-lexical",
            "detail": f"Knowledge corpus could not be loaded ({type(exc).__name__}).",
        }
