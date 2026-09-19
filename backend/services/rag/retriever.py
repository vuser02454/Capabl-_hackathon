"""Stage 6 — query construction and grounded context assembly.

The bridge between structured evidence and the corpus. It answers: *given what this analysis
actually found, which knowledge is relevant to it?*

QUERY CONSTRUCTION IS DETERMINISTIC
-----------------------------------
The query is built from the evidence the agents produced — labels, statuses, domains — not by
asking a language model what to search for. Two reasons:

1. An LLM-generated query is a second place for the system to drift off what it measured. If the
   evidence says turbidity, the query says turbidity.
2. It is reproducible. The same analysis retrieves the same knowledge, which is what makes the
   retrieval panel in the UI trustworthy rather than decorative.

WHAT RETRIEVED KNOWLEDGE IS ALLOWED TO DO
-----------------------------------------
It grounds an explanation. It is **context, not evidence**: it never enters the evidence list,
never carries severity, and cannot move a risk score. A retrieved passage about turbidity limits
explains what a turbidity reading means; it is not itself a reading. This is the same rule
geographic context already follows, for the same reason.
"""

import logging
from typing import List, Optional, Sequence

from services.rag.store import DEFAULT_TOP_K, RetrievalResult, get_store

logger = logging.getLogger("ecosentinel.rag.retriever")

#: Evidence at or above this severity shapes the query. Below it, a signal is real but not what
#: the user needs explaining.
QUERY_SEVERITY = 0.4

#: Hard cap on query length. A query built from twenty evidence labels matches everything weakly.
MAX_QUERY_TERMS = 24


def build_query(evidence: Sequence, primary_domain: Optional[str] = None) -> str:
    """Structured evidence -> one retrieval query string.

    FOCUSED ON THE PRIMARY DOMAIN, deliberately. Concatenating every elevated label across all
    three domains was tried first and retrieves badly: a Delhi analysis with an air primary
    problem produced a 14-term query spanning PM2.5, turbidity, temperature and litter density,
    and its top hit was the WATER document's temperature section. A query about everything is a
    query about nothing — each term dilutes the others, and the shortest chunk containing any one
    of them wins.

    So the primary domain's elevated evidence forms the query, with the other domains contributing
    only their names. Cross-domain knowledge is still reachable: the store searches the whole
    corpus and the domain boost is a multiplier, not a filter.
    """
    def _terms_for(items: Sequence) -> List[str]:
        collected: List[str] = []
        for item in items:
            label = getattr(item, "label", "") or ""
            if label:
                collected.append(label)
            # A detection carries its meaning in the label; a measurement carries it in the
            # status ("critical" / "elevated"), which is the vocabulary the corpus discusses.
            status = getattr(item, "status", "")
            if status in {"elevated", "critical"}:
                collected.append(status)
        return collected

    elevated = [
        item
        for item in evidence
        if getattr(item, "severity", 0.0) >= QUERY_SEVERITY
        and getattr(item, "domain", "") != "geographic"
    ]
    if not elevated:
        return ""

    focused = [item for item in elevated if getattr(item, "domain", "") == primary_domain]
    # Fall back to everything only when the primary domain contributed nothing elevated.
    terms = _terms_for(focused or elevated)

    if primary_domain:
        terms.append(primary_domain)
    # Other domains contribute their name only, so a cross-signal passage stays reachable without
    # their measurement labels competing with the primary domain's.
    others = sorted({getattr(item, "domain", "") for item in elevated} - {primary_domain, ""})
    terms.extend(others)

    return " ".join(terms[:MAX_QUERY_TERMS]).strip()


def retrieve_for_evidence(
    evidence: Sequence,
    primary_domain: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
) -> "tuple[str, List[RetrievalResult]]":
    """Evidence -> (query, retrieved chunks). Never raises.

    Returns an empty list rather than a weak match when nothing clears the relevance floor, and
    an empty list when retrieval itself fails — an analysis must not depend on its own footnotes.
    """
    query = build_query(evidence, primary_domain)
    if not query:
        return "", []

    try:
        results = get_store().search(query, top_k=top_k, domain=primary_domain)
    except Exception:  # noqa: BLE001 - retrieval is enrichment; it cannot fail an analysis
        logger.warning("rag_retrieval_failed", exc_info=True)
        return query, []

    logger.info(
        "rag_retrieved query=%r domain=%s results=%s top_score=%s",
        query[:80], primary_domain, len(results), results[0].score if results else None,
    )
    return query, results


def search_knowledge(
    query: str, top_k: int = DEFAULT_TOP_K, domain: Optional[str] = None
) -> List[RetrievalResult]:
    """Free-text search, for the knowledge tool and the chat endpoint. Never raises."""
    try:
        return get_store().search(query, top_k=top_k, domain=domain)
    except Exception:  # noqa: BLE001
        logger.warning("rag_search_failed", exc_info=True)
        return []


def format_context(results: Sequence[RetrievalResult], max_chars: int = 2000) -> str:
    """Retrieved chunks -> a context block for an explanation prompt.

    Each passage is labelled with its citation, so a model quoting it can be checked against the
    source, and a model inventing beyond it is visibly doing so.
    """
    if not results:
        return ""
    blocks: List[str] = []
    budget = max_chars
    for result in results:
        header = f"[{result.chunk_id}] {result.document_title} — {result.section}"
        body = result.text.strip()
        block = f"{header}\n{body}"
        if len(block) > budget:
            block = block[: max(0, budget)].rstrip() + "…"
        if not block.strip():
            break
        blocks.append(block)
        budget -= len(block)
        if budget <= 0:
            break
    return "\n\n".join(blocks)
