"""The retrieval pipeline, stage by stage, and the honesty properties that matter.

A retriever's worst failure is not missing a passage — it is confidently citing one for a
question the corpus cannot answer, because the citation makes an unverified claim look checked.
Several tests here exist only to hold that line.
"""

import pytest

from services.rag import build_query, format_context, get_store, search_knowledge
from services.rag.chunker import chunk_document, chunk_documents
from services.rag.embeddings import TfidfEmbedder, tokenize
from services.rag.loader import load_documents


# --------------------------------------------------------------------------- stage 1: loading


def test_corpus_loads():
    documents = load_documents()
    assert documents, "the knowledge corpus must load"
    assert len(documents) >= 5


def test_every_document_declares_a_resolvable_source():
    """A citation nobody can open is worse than no citation."""
    for document in load_documents():
        assert document.source, f"{document.document_id} declares no source file"
        assert not document.warnings, f"{document.document_id}: {document.warnings}"


def test_documents_carry_a_domain():
    valid = {"air", "water", "waste", "cross_signal"}
    for document in load_documents():
        assert document.domain in valid, f"{document.document_id} has domain {document.domain!r}"


# --------------------------------------------------------------------------- stage 2: chunking


def test_chunks_are_heading_aligned_and_carry_their_section():
    for document in load_documents():
        for chunk in chunk_document(document):
            assert chunk.section, "every chunk must know which section it came from"
            # The heading travels with the body, including for a split section.
            assert chunk.text.startswith(chunk.section)


def test_chunk_ids_are_unique_and_resolvable():
    chunks = chunk_documents(load_documents())
    ids = [chunk.chunk_id for chunk in chunks]
    assert len(ids) == len(set(ids)), "chunk ids must be unique or a citation is ambiguous"
    for chunk in chunks:
        document_id, _, slug = chunk.chunk_id.partition("#")
        assert document_id == chunk.document_id
        assert slug, "a chunk id must name a section"


# --------------------------------------------------------------------------- stage 3: embedding


def test_tokenizer_keeps_technical_terms_whole():
    """Splitting these would lose the exact vocabulary this corpus is about."""
    assert "pm2.5" in tokenize("PM2.5 exceeded the guideline")
    assert "visible_surface_litter" in tokenize("classified as visible_surface_litter")
    assert "non-degrading" in tokenize("plastic is non-degrading")


def test_negation_survives_tokenization():
    """'not established' is one of the most important phrases in this corpus."""
    assert "not" in tokenize("chemical contamination is not established")


def test_interrogatives_are_stopped():
    """'what' is a frequent corpus heading term and matched off-topic queries on its own."""
    assert tokenize("what is the capital of France") == ["capital", "france"]


def test_vectors_are_l2_normalised():
    embedder = TfidfEmbedder.fit(["turbidity exceeds the limit", "pm2.5 exceeds the guideline"])
    import numpy as np

    vector = embedder.embed("turbidity limit")
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-5)


def test_unknown_terms_produce_a_zero_vector():
    embedder = TfidfEmbedder.fit(["turbidity exceeds the limit"])
    import numpy as np

    assert float(np.linalg.norm(embedder.embed("zzzz qqqq"))) == 0.0


# --------------------------------------------------------------------------- stage 4/5: store


def test_index_is_built():
    status = get_store().status()
    assert status["available"]
    assert status["documents"] >= 5
    assert status["chunks"] >= 20
    # The technique is named plainly rather than implying a semantic model is running.
    assert status["embedding"] == "tfidf-sparse-lexical"


@pytest.mark.parametrize(
    "query, domain, expected_chunk",
    [
        ("turbidity BIS permissible limit", "water", "water_quality_standards#turbidity"),
        ("PM2.5 WHO guideline", "air", "air_quality_standards#pollutants-and-who-2021-guidelines"),
        ("plastic bags persistent handling", "waste", "waste_segregation#handling-notes"),
        (
            "can an image prove chemical contamination",
            None,
            "evidence_semantics#what-an-image-can-and-cannot-establish",
        ),
        ("recovery timeline planning horizon", None, "recovery_and_timelines#recovery-actions-and-planning-timelines"),
    ],
)
def test_on_topic_queries_retrieve_the_right_passage(query, domain, expected_chunk):
    results = search_knowledge(query, top_k=3, domain=domain)
    assert results, f"{query!r} retrieved nothing"
    assert results[0].chunk_id == expected_chunk, f"{query!r} -> {results[0].chunk_id}"


@pytest.mark.parametrize(
    "query",
    [
        "what is the capital of France",
        "best pizza in Naples",
        "how do I bake bread",
        "tell me a joke",
    ],
)
def test_off_topic_queries_retrieve_nothing(query):
    """The corpus must decline rather than cite a source for a question it cannot answer.

    'best pizza in Naples' once matched the waste confidence-thresholds section at 0.14, on the
    word 'best' — the corpus says 'rather than a best guess'.
    """
    assert search_knowledge(query, top_k=5) == []


def test_results_are_ranked_and_scored():
    results = search_knowledge("turbidity BIS permissible limit", top_k=3, domain="water")
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True), "results must be ranked"
    assert all(0.0 < s <= 1.0 for s in scores)


def test_top_k_is_respected():
    assert len(search_knowledge("waste segregation handling category", top_k=2)) <= 2


def test_every_result_carries_full_provenance():
    for result in search_knowledge("turbidity BIS permissible limit", domain="water"):
        assert result.chunk_id and result.document_id and result.section
        assert result.source, "a result without a source file cannot be cited"
        assert result.text.strip()


# --------------------------------------------------------------------------- stage 6: query


def test_query_is_built_from_elevated_evidence():
    from schemas import EnvironmentalEvidence

    evidence = [
        EnvironmentalEvidence(
            evidence_id="water.turbidity", domain="water", kind="measurement",
            label="Turbidity", detail="", severity=0.8, status="elevated",
        ),
        EnvironmentalEvidence(
            evidence_id="water.ph", domain="water", kind="measurement",
            label="pH", detail="", severity=0.05, status="normal",
        ),
    ]
    query = build_query(evidence, "water")
    assert "Turbidity" in query
    # Normal evidence is real but is not what the user needs explaining.
    assert "pH" not in query


def test_query_focuses_on_the_primary_domain():
    """A query about everything is a query about nothing.

    Concatenating every domain's labels made a Delhi air analysis retrieve the WATER temperature
    section as its top hit.
    """
    from schemas import EnvironmentalEvidence

    def item(domain, label):
        return EnvironmentalEvidence(
            evidence_id=f"{domain}.{label}", domain=domain, kind="measurement",
            label=label, detail="", severity=0.9, status="critical",
        )

    query = build_query([item("air", "PM2.5"), item("water", "Turbidity")], "air")
    assert "PM2.5" in query
    assert "Turbidity" not in query
    # Other domains still contribute their name, so cross-signal knowledge stays reachable.
    assert "water" in query


def test_geographic_context_never_shapes_a_query():
    """Context is not evidence, so it must not steer retrieval either."""
    from schemas import EnvironmentalEvidence

    evidence = [
        EnvironmentalEvidence(
            evidence_id="geographic.industrial", domain="geographic", kind="context",
            label="Mapped industrial feature", detail="", severity=0.0,
        )
    ]
    assert build_query(evidence, None) == ""


def test_context_block_labels_every_passage_with_its_citation():
    results = search_knowledge("turbidity BIS permissible limit", domain="water")
    context = format_context(results)
    for result in results:
        assert result.chunk_id in context, "a passage must arrive with its citation attached"
