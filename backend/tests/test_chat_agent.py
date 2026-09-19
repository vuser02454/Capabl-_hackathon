"""The chat agent: routing, tool authority, grounding, and every degradation path.

The suite runs with both AI providers set to "none" (see conftest), which is deliberate: it
means every test here exercises the path a demo takes when a key is missing or an API is down.
The properties that matter most — that a hallucinated tool name never executes, that a tool
result is never rewritten, that an unknown analysis is refused — hold with no model at all.
"""

import pytest

from services.ai import chat_agent
from services.ai.chat import store


# --------------------------------------------------------------------------- routing


def test_routing_falls_back_to_analysis_without_gemini():
    """No router: prefer real evidence the user is looking at over general knowledge."""
    decision = chat_agent.route("Why is the current water risk high?")
    assert decision["intent"] == "analysis"
    assert decision["tool"] is None


def test_the_chat_allow_list_is_a_subset_of_the_registry():
    from services import tools as tool_layer

    registered = {tool.name for tool in tool_layer.list_tools()}
    assert set(chat_agent.CHAT_TOOLS) <= registered, "chat exposes a tool that does not exist"


def test_expensive_and_upload_only_tools_are_not_chat_callable():
    """A full multi-agent re-analysis must not be reachable from an ambiguous sentence."""
    assert "generate_investigation_plan" not in chat_agent.CHAT_TOOLS
    assert "analyze_water_image" not in chat_agent.CHAT_TOOLS
    assert "analyze_waste_image" not in chat_agent.CHAT_TOOLS


# --------------------------------------------------------------------------- tool authority


def test_a_tool_outside_the_allow_list_never_executes():
    """The safety property: a hallucinated name gets an error, not a call."""
    execution, output = chat_agent.execute_tool("delete_everything", {})
    assert execution.status == "failed"
    assert output is None
    assert "not available" in execution.error


def test_a_registered_but_non_chat_tool_is_still_refused():
    execution, output = chat_agent.execute_tool("generate_investigation_plan", {"location": "Delhi"})
    assert execution.status == "failed"
    assert output is None


def test_a_real_tool_executes_through_the_registry():
    execution, output = chat_agent.execute_tool(
        "calculate_environmental_risk", {"airScore": 0.94, "waterScore": 0.55, "wasteScore": 0.74}
    )
    assert execution.status == "ok"
    assert output is not None
    # The number is the deterministic engine's, unmodified.
    from core.risk import round_half_up

    assert output["riskScore"] == round_half_up((0.94 + 0.55 + 0.74) / 3)
    assert output["riskLevel"] == "HIGH"


def test_invalid_tool_arguments_are_reported_not_guessed():
    execution, output = chat_agent.execute_tool("calculate_environmental_risk", {"airScore": 5})
    assert execution.status == "failed"
    assert output is None
    assert execution.error


def test_tool_summaries_read_values_out_without_interpreting_them():
    _execution, output = chat_agent.execute_tool(
        "get_waste_segregation_guidance", {"material": "paper_waste"}
    )
    summary = chat_agent._summarize("get_waste_segregation_guidance", output)
    assert "biodegradable" in summary
    # A summary must not editorialise about severity.
    assert "dangerous" not in summary.lower() and "safe" not in summary.lower()


# --------------------------------------------------------------------------- citations


def test_citations_only_come_from_the_retriever():
    """A citation is built from real retriever output or it is not built at all."""
    _execution, output = chat_agent.execute_tool(
        "search_environmental_knowledge", {"query": "turbidity BIS permissible limit", "topK": 2}
    )
    citations = chat_agent._citations_from("search_environmental_knowledge", output)
    assert citations
    for citation in citations:
        assert citation["chunkId"] and citation["sourceFile"] and citation["content"]

    # No other tool may produce citations, whatever it returned.
    assert chat_agent._citations_from("get_water_sensor_data", {"results": [{"chunkId": "fake"}]}) == []


def test_an_off_topic_knowledge_query_yields_no_citations():
    _execution, output = chat_agent.execute_tool(
        "search_environmental_knowledge", {"query": "what is the capital of France"}
    )
    assert chat_agent._citations_from("search_environmental_knowledge", output) == []


# --------------------------------------------------------------------------- degradation


def test_an_unknown_analysis_is_refused_not_answered():
    """Answering about the wrong analysis reads perfectly and is entirely wrong."""
    store.clear()
    outcome = chat_agent.respond("no-such-analysis", "Why is the risk high?")
    assert outcome.intent == "analysis"
    assert "do not have that analysis" in outcome.answer.lower()
    assert outcome.evidence_ids == []


def test_general_questions_degrade_honestly_without_a_provider():
    """With no secondary LLM the agent says so rather than answering from nowhere."""
    answer = chat_agent.general_answer("What is eutrophication?")
    assert answer is None, "no provider is configured in the test suite"


def test_explanation_degrades_to_none_without_gemini():
    assert chat_agent.explain_result("why", "calculate_environmental_risk", {"riskScore": 0.5}) is None


# --------------------------------------------------------------------------- grounded answers


@pytest.fixture
def held_analysis():
    """A real decision in the store, built by the real engine."""
    import asyncio

    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Delhi", None))
    store.remember(result.analysis_id, result.location, result.decision)
    yield result
    store.clear()


def test_a_question_about_the_current_analysis_is_grounded_in_it(held_analysis):
    outcome = chat_agent.respond(held_analysis.analysis_id, "What evidence caused this decision?")
    assert outcome.intent == "analysis"
    assert outcome.answer
    # It reports the tool it used to read the analysis, so the UI can show provenance.
    assert any(e.tool == "get_current_analysis" for e in outcome.tool_executions)
    # Every cited evidence id must exist in the decision it claims to describe.
    held = {item.evidence_id for item in held_analysis.decision.evidence}
    for evidence_id in outcome.evidence_ids:
        assert evidence_id in held, f"{evidence_id} is not in this analysis"


def test_retrieved_sources_come_from_this_analysis(held_analysis):
    """'Show me the source' must resolve to what grounded THIS decision."""
    outcome = chat_agent.respond(held_analysis.analysis_id, "Show me the retrieved sources.")
    held = {item.chunk_id for item in (held_analysis.decision.knowledge.results or [])}
    for citation in outcome.citations:
        assert citation["chunkId"] in held


# --------------------------------------------------------------------------- demo intents


def test_verify_next_returns_the_investigation_plan(held_analysis):
    """'What should I verify next' is a question about EVIDENCE, not remediation.

    It previously fell through to the generic primary-concern summary, which answered a
    different question convincingly.
    """
    from services.ai.chat import deterministic_answer

    text, _ids = deterministic_answer(held_analysis.decision, "What should I verify next?")
    plan = held_analysis.decision.investigation_plan
    if plan:
        assert "verification step" in text
        assert plan[0].title in text
    else:
        assert "no further collection" in text.lower()


def test_show_me_the_source_returns_the_passages_that_grounded_this_decision(held_analysis):
    from services.ai.chat import deterministic_answer

    text, _ids = deterministic_answer(held_analysis.decision, "Show me the source.")
    results = held_analysis.decision.knowledge.results or []
    if results:
        # Every citation shown must be one this analysis actually retrieved.
        for item in results:
            assert item.chunk_id in text
        assert "did not affect the risk score" in text
    else:
        assert "no knowledge passages" in text.lower()


def test_source_and_verify_intents_do_not_shadow_each_other(held_analysis):
    """Both patterns sit above the broad `reasons`/`evidence` ones; neither may swallow the other."""
    from services.ai.chat import deterministic_answer

    source_text, _ = deterministic_answer(held_analysis.decision, "show me the retrieved sources")
    verify_text, _ = deterministic_answer(held_analysis.decision, "what should I verify next")
    assert source_text != verify_text
