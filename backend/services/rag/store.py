"""Stage 4 and 5 — vector store and retriever.

An in-memory vector store over the chunked corpus, with cosine top-k retrieval.

The corpus is seven documents and a few dozen chunks. A persistent vector database here would be
infrastructure carrying no weight: the whole matrix is a few hundred kilobytes, it rebuilds in
milliseconds, and an external store would add a service that can be down during a demo. The
interface is the one a vector database exposes, so swapping in a real one later is a contained
change — but nothing about this corpus justifies one today.

RETRIEVAL HONESTY
-----------------
Two rules, both enforced here rather than left to the caller:

1. **A score below `MIN_SCORE` is not returned.** A retriever that always returns its best
   k chunks will cite something for any query, including one the corpus cannot answer. Returning
   nothing is a valid and useful answer.
2. **Scores are reported, never hidden.** The UI shows them, so a weak match is visibly weak
   instead of arriving with the same authority as a strong one.
"""

import logging
import threading
from dataclasses import dataclass
from typing import List, Optional, Sequence

from services.rag.chunker import Chunk, chunk_documents
from services.rag.embeddings import TfidfEmbedder
from services.rag.loader import Document, corpus_fingerprint, load_documents

logger = logging.getLogger("ecosentinel.rag.store")

#: Cosine similarity below which a chunk is not considered relevant at all. Set by inspection of
#: real queries against this corpus: on-topic queries score well above it, and off-topic queries
#: ("what is the capital of France") fall below it and correctly return nothing.
MIN_SCORE = 0.08

#: Default number of chunks returned. Small on purpose — retrieved context is shown to a user and
#: injected into an explanation prompt, and ten half-relevant passages is not better than three
#: good ones.
DEFAULT_TOP_K = 3

#: Multiplier applied to a chunk whose domain matches the query's. Retrieval stays global — an
#: air query can still surface a cross-signal chunk — but same-domain knowledge is preferred when
#: scores are close.
DOMAIN_BOOST = 1.15

#: Minimum fraction of a query's tokens that must exist in the corpus vocabulary before the query
#: is answered at all.
#:
#: A per-chunk score floor alone is not enough, because a long off-topic query can graze a single
#: common corpus word and clear it. "best pizza in Naples" matched the waste confidence-thresholds
#: section at 0.14 on the word "best" — the corpus says "rather than a best guess" — and was
#: returned as a cited source. One word in three is not a question this corpus can answer.
#:
#: Checking coverage at the query level rather than raising the score floor keeps genuinely weak
#: but on-topic secondary matches (0.09-0.15) retrievable, which is where much of the useful
#: cross-domain knowledge sits.
MIN_QUERY_COVERAGE = 0.5


@dataclass(frozen=True)
class RetrievalResult:
    """One retrieved chunk with everything needed to cite it."""

    chunk_id: str
    document_id: str
    document_title: str
    section: str
    domain: str
    #: The repository file this knowledge came from. None means the citation cannot be resolved.
    source: Optional[str]
    text: str
    score: float
    #: True when DOMAIN_BOOST was applied, so a ranking can be explained.
    domain_matched: bool


class KnowledgeStore:
    """Chunks plus their vectors, with cosine top-k search."""

    def __init__(self, documents: Sequence[Document]):
        self.documents = list(documents)
        self.chunks: List[Chunk] = chunk_documents(self.documents)
        self.embedder = TfidfEmbedder.fit([chunk.text for chunk in self.chunks])
        self.matrix = self.embedder.embed_all([chunk.text for chunk in self.chunks])
        logger.info(
            "rag_index_built documents=%s chunks=%s vocabulary=%s",
            len(self.documents), len(self.chunks), self.embedder.dimensions,
        )

    @property
    def available(self) -> bool:
        return bool(self.chunks)

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        domain: Optional[str] = None,
        min_score: float = MIN_SCORE,
    ) -> List[RetrievalResult]:
        """Top-k chunks above `min_score`, most relevant first. May return an empty list."""
        if not self.chunks or not query.strip():
            return []

        import numpy as np

        from services.rag.embeddings import tokenize

        # Coverage gate, before any scoring. A query mostly made of words the corpus has never
        # seen is a question this corpus cannot answer, however well one stray term happens to
        # match. See MIN_QUERY_COVERAGE.
        tokens = tokenize(query)
        if not tokens:
            return []
        known = sum(1 for token in tokens if token in self.embedder.vocabulary)
        if known / len(tokens) < MIN_QUERY_COVERAGE:
            logger.info(
                "rag_query_out_of_domain query=%r coverage=%.2f", query[:80], known / len(tokens)
            )
            return []

        vector = self.embedder.embed(query)
        if not float(np.linalg.norm(vector)):
            # No query term is in the corpus vocabulary, so there is nothing to match against.
            return []

        # Both sides are L2-normalised, so the dot product IS the cosine similarity.
        scores = self.matrix @ vector

        if domain:
            boost = np.array(
                [DOMAIN_BOOST if chunk.domain == domain else 1.0 for chunk in self.chunks],
                dtype="float32",
            )
            scores = scores * boost

        order = np.argsort(-scores)[: max(1, top_k)]
        results: List[RetrievalResult] = []
        for index in order:
            score = float(scores[int(index)])
            if score < min_score:
                continue
            chunk = self.chunks[int(index)]
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    section=chunk.section,
                    domain=chunk.domain,
                    source=chunk.source,
                    text=chunk.text,
                    score=round(score, 4),
                    domain_matched=bool(domain and chunk.domain == domain),
                )
            )
        return results

    def status(self) -> dict:
        return {
            "available": self.available,
            "documents": len(self.documents),
            "chunks": len(self.chunks),
            "vocabulary": self.embedder.dimensions,
            "embedding": "tfidf-sparse-lexical",
            "top_k": DEFAULT_TOP_K,
            "min_score": MIN_SCORE,
            "document_ids": [document.document_id for document in self.documents],
        }


_lock = threading.Lock()
_store: Optional[KnowledgeStore] = None
_fingerprint: Optional[str] = None


def get_store(force_rebuild: bool = False) -> KnowledgeStore:
    """The process-wide store, rebuilt only when the corpus on disk has changed.

    Built once and cached: fitting the vectoriser on every request would put avoidable work on the
    analysis path for a corpus that changes only when someone edits a file.
    """
    global _store, _fingerprint
    with _lock:
        fingerprint = corpus_fingerprint()
        if _store is None or force_rebuild or fingerprint != _fingerprint:
            _store = KnowledgeStore(load_documents())
            _fingerprint = fingerprint
        return _store
