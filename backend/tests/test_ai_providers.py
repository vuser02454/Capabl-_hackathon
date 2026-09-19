"""The two AI provider roles, and the boundaries between them.

Gemini performs functional work whose output becomes evidence. OpenRouter and Groq receive a
finished decision and put it into words. Those are different jobs with different guarantees, and
most of what is worth testing is that neither can do the other's:

  - an explainability provider cannot change a score, a problem, a priority or the evidence
  - a functional provider cannot be substituted by an explainability one
  - a malformed functional response contributes nothing rather than something half-understood
  - every role degrades to the deterministic path, never to a crash
  - the chatbot answers from one analysis and refuses to answer from another

No test here reaches the network: every provider is stubbed.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import pytest

from core import recovery as recovery_core
from schemas import FunctionalAnalysis
from services.ai import chat as chat_service
from services.ai import explainability, functional
from tests.test_decision_engine import air_report, run_engine, waste_report, water_report


class _PatchedSettings:
    """Settings is a frozen dataclass; wrap it to override attributes for a test."""

    def __init__(self, base, **overrides):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_overrides", overrides)

    def __getattr__(self, name):
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)


def configure(monkeypatch, module, **overrides) -> None:
    monkeypatch.setattr(module, "settings", _PatchedSettings(module.settings, **overrides))


@pytest.fixture(autouse=True)
def _clear_chat_store():
    chat_service.store.clear()
    yield
    chat_service.store.clear()


# --------------------------------------------------------------------------- role separation


def test_explainability_providers_are_not_accepted_for_functional_work(monkeypatch):
    """The roles carry different guarantees; silently swapping them is the failure to prevent."""
    for provider in ("openrouter", "groq"):
        configure(monkeypatch, functional, functional_ai_provider=provider, gemini_api_key="k")
        assert functional.resolve_provider() is None
        assert functional.status()["available"] is False


def test_gemini_is_the_functional_provider(monkeypatch):
    configure(monkeypatch, functional, functional_ai_provider="gemini", gemini_api_key="k",
              gemini_model="gemini-2.5-flash")
    provider = functional.resolve_provider()
    assert provider is not None and provider.name == "gemini"
    assert provider.model == "gemini-2.5-flash"


@pytest.mark.parametrize("provider_name,expected", [("openrouter", "openrouter"), ("groq", "groq")])
def test_both_explainability_providers_resolve(monkeypatch, provider_name, expected):
    configure(monkeypatch, explainability, explainability_ai_provider=provider_name,
              openrouter_api_key="k", groq_api_key="k")
    provider = explainability.resolve_provider()
    assert provider is not None and provider.name == expected


def test_no_silent_failover_between_explainability_providers(monkeypatch):
    """Answering via a provider the operator did not configure is its own dishonesty."""
    configure(monkeypatch, explainability, explainability_ai_provider="openrouter",
              openrouter_api_key=None, groq_api_key="groq-key-is-set")
    assert explainability.resolve_provider() is None


def test_an_unknown_provider_is_refused_not_guessed(monkeypatch):
    configure(monkeypatch, explainability, explainability_ai_provider="mystery-model")
    assert explainability.resolve_provider() is None
    configure(monkeypatch, functional, functional_ai_provider="mystery-model")
    assert functional.resolve_provider() is None


# --------------------------------------------------------------------------- decision integrity


class StubExplainer:
    """An explainability provider that actively contradicts the decision it is given."""

    name = "stub"

    def __init__(self, reply: str = "I think the main problem is air pollution and the risk is LOW."):
        self.reply = reply
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


def test_an_explanation_cannot_change_the_decision(monkeypatch):
    """The core guarantee: prose lands in its own field and reaches no number."""
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    before = decision.model_dump()

    monkeypatch.setattr(explainability, "resolve_provider", lambda: StubExplainer())
    prose = explainability.explain(decision, "Test location")

    assert "air pollution" in prose  # the model really did disagree
    # ...and nothing moved.
    assert decision.model_dump() == before
    assert decision.primary_problem.title != "air pollution"


def test_every_protected_field_survives_an_explanation(monkeypatch):
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    snapshot = {
        "risk_level": decision.risk_level,
        "risk_score": decision.risk_score,
        "confidence": decision.confidence,
        "primary": decision.primary_problem.problem_id,
        "priority": decision.primary_problem.priority,
        "evidence": [e.evidence_id for e in decision.evidence],
        "sufficient": decision.sufficient_evidence,
    }

    monkeypatch.setattr(explainability, "resolve_provider", lambda: StubExplainer("Risk is LOW. Score 0.01."))
    explainability.explain(decision, "Test location")

    assert decision.risk_level == snapshot["risk_level"]
    assert decision.risk_score == snapshot["risk_score"]
    assert decision.confidence == snapshot["confidence"]
    assert decision.primary_problem.problem_id == snapshot["primary"]
    assert decision.primary_problem.priority == snapshot["priority"]
    assert [e.evidence_id for e in decision.evidence] == snapshot["evidence"]
    assert decision.sufficient_evidence == snapshot["sufficient"]


def test_the_context_handed_to_a_provider_is_read_only_and_carries_no_secrets(monkeypatch):
    decision = run_engine(air=air_report(), water=water_report())
    stub = StubExplainer()
    monkeypatch.setattr(explainability, "resolve_provider", lambda: stub)
    explainability.explain(decision, "Bengaluru")

    _system, user = stub.calls[0]
    lowered = user.lower()
    for forbidden in ("api_key", "apikey", "authorization", "bearer", "latitude", "longitude", "token"):
        assert forbidden not in lowered, forbidden


def test_the_system_prompt_forbids_deciding_and_padding(monkeypatch):
    prompt = explainability.SYSTEM_PROMPT.lower()
    assert "you decide nothing" in prompt
    assert "caused" in prompt
    assert "if three reasons are given, give three" in prompt


# --------------------------------------------------------------------------- functional AI


class StubGemini(functional.GeminiFunctionalAI):
    def __init__(self, result):
        super().__init__("key", "gemini-2.5-flash", 30.0)
        self._result = result

    def _client(self):
        raise AssertionError("the stub should not build a real client")

    def analyze(self, task, payload):  # type: ignore[override]
        if isinstance(self._result, Exception):
            return FunctionalAnalysis(status="unavailable", provider="gemini", message=str(self._result))
        return self._result


def test_functional_output_enters_as_evidence_not_as_a_verdict():
    """A functional observation is one signal among several, with no authority over the score."""
    analysis = FunctionalAnalysis(
        available=True, status="ok", provider="gemini", model="gemini-2.5-flash",
        observations=[{"type": "visible_waste", "description": "Plastic-like objects on the surface", "confidence": 0.91}],
        uncertainties=["An image cannot establish chemical contamination"],
    )
    # The schema has no field through which a functional provider could set a risk or severity.
    assert not {"risk_level", "risk_score", "severity", "priority"} & set(FunctionalAnalysis.model_fields)
    assert analysis.observations[0].confidence == 0.91


def test_an_unconfigured_functional_provider_degrades_quietly(monkeypatch):
    configure(monkeypatch, functional, functional_ai_provider="none")
    result = functional.analyze("interpret this", "{}")
    assert result.status == "not_configured"
    assert result.available is False
    assert result.observations == []


def test_a_missing_gemini_key_degrades_quietly(monkeypatch):
    configure(monkeypatch, functional, functional_ai_provider="gemini", gemini_api_key=None)
    result = functional.analyze("interpret this", "{}")
    assert result.status == "not_configured" and result.available is False


def test_a_provider_failure_never_raises_into_the_pipeline(monkeypatch):
    monkeypatch.setattr(functional, "resolve_provider", lambda: StubGemini(RuntimeError("model exploded")))
    result = functional.analyze("interpret this", "{}")
    assert result.status == "unavailable" and result.available is False


def test_the_functional_prompt_forbids_scoring_and_causality():
    prompt = functional.SYSTEM_PROMPT.lower()
    assert "never estimate a risk level" in prompt
    assert "never claim one thing caused another" in prompt
    assert "inventing an observation to fill the list is not" in prompt


# --------------------------------------------------------------------------- reasons & recovery


def test_reasons_are_never_padded_to_a_target_count():
    """Asked for five, a model returns five. Deriving them first means three stays three."""
    decision = run_engine(air=air_report(), water=water_report(turbidity=1.0, level="LOW", score=0.1))
    reasons = recovery_core.top_reasons(decision, limit=5)
    assert len(reasons) <= 5
    assert all(reason.evidence_ids for reason in reasons)


def test_every_reason_cites_the_evidence_behind_it():
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    known = {item.evidence_id for item in decision.evidence}
    for reason in recovery_core.top_reasons(decision):
        assert reason.evidence_ids
        assert set(reason.evidence_ids) <= known


def test_mapped_geography_is_never_a_reason_on_its_own():
    """Context can corroborate a reason; it can never be one."""
    from tests.test_decision_engine import geo_context

    decision = run_engine(air=air_report(), waste=waste_report(), geo=geo_context())
    for reason in recovery_core.top_reasons(decision):
        assert reason.domain != "geographic"
        assert not any(eid.startswith("geographic.") for eid in reason.evidence_ids)


def test_no_problem_means_no_invented_recovery_advice():
    decision = run_engine(
        air=air_report(pm25=5.0, level="LOW", score=0.1),
        water=water_report(turbidity=1.0, level="LOW", score=0.1),
        risk=("LOW", 0.1, 0.9),
    )
    plan = recovery_core.recovery_plan(decision)
    assert plan.available is False
    assert plan.actions == []


def test_recovery_actions_address_the_detected_problem():
    decision = run_engine(water=water_report(), waste=waste_report())
    plan = recovery_core.recovery_plan(decision)
    addressed = {action.addresses_problem for action in plan.actions}
    detected = {p.problem_id for p in [decision.primary_problem, *decision.secondary_problems] if p}
    assert addressed <= detected


def test_the_timeline_is_a_planning_horizon_never_a_prediction():
    decision = run_engine(air=air_report(), waste=waste_report())
    plan = recovery_core.recovery_plan(decision)
    assert plan.timeline_category in recovery_core.TIMELINE_BANDS
    assert plan.timeline_range in recovery_core.TIMELINE_BANDS.values()
    assert "not a guaranteed recovery prediction" in plan.summary
    # No specific day count anywhere: "the river will recover in 27 days" must be unreachable.
    assert "will recover" not in plan.summary.lower()


# --------------------------------------------------------------------------- chatbot


def _remember(decision, analysis_id="a1", location="River A"):
    chat_service.store.remember(analysis_id, location, decision)


def test_the_chatbot_answers_from_the_decision_with_no_llm_configured(monkeypatch):
    configure(monkeypatch, explainability, explainability_ai_provider="none")
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    decision = decision.model_copy(update={"reasons": recovery_core.top_reasons(decision)})
    _remember(decision)

    response = chat_service.answer("a1", "Give me the five strongest reasons")
    assert response is not None
    assert response.source == "deterministic" and response.llm_enhanced is False
    assert "evidence-supported reason" in response.answer


def test_the_chatbot_states_the_real_count_when_five_were_requested(monkeypatch):
    configure(monkeypatch, explainability, explainability_ai_provider="none")
    decision = run_engine(air=air_report(), water=water_report(turbidity=1.0, level="LOW", score=0.1))
    decision = decision.model_copy(update={"reasons": recovery_core.top_reasons(decision)})
    _remember(decision)

    answer = chat_service.answer("a1", "Give me the five strongest reasons").answer
    count = len(decision.reasons)
    assert f"{count} evidence-supported reason" in answer


def test_switching_analyses_never_leaks_the_previous_context(monkeypatch):
    """Explaining River B with River A's evidence reads perfectly and is entirely wrong."""
    configure(monkeypatch, explainability, explainability_ai_provider="none")
    river_a = run_engine(air=air_report(pm25=95.0), waste=waste_report(total=30, plastic=25))
    river_b = run_engine(water=water_report(turbidity=12.0), waste=waste_report(total=3, plastic=1, level="LOW", score=0.1))
    chat_service.store.remember("river-a", "River A", river_a)
    chat_service.store.remember("river-b", "River B", river_b)

    answer_b = chat_service.answer("river-b", "What evidence supports this?").answer
    assert "air.pm25" not in answer_b
    assert any(eid in answer_b for eid in [e.evidence_id for e in river_b.evidence])


def test_an_unknown_analysis_is_refused_not_answered_from_another():
    decision = run_engine(air=air_report(), water=water_report())
    _remember(decision, "known")
    assert chat_service.answer("unknown-id", "why?") is None


def test_the_store_is_bounded():
    decision = run_engine(air=air_report(), water=water_report())
    for index in range(chat_service.MAX_TRACKED_ANALYSES + 5):
        chat_service.store.remember(f"id-{index}", "Somewhere", decision)
    assert chat_service.store.get("id-0") is None
    assert chat_service.store.get(f"id-{chat_service.MAX_TRACKED_ANALYSES + 4}") is not None


@pytest.mark.parametrize(
    "question",
    [
        "Why is this river deteriorating?",
        "What are the biggest problems?",
        "Where is the garbage?",
        "What evidence supports this?",
        "What should we do first?",
        "How long could recovery take?",
        "What information is missing?",
        "Why did EcoSentinel choose this as the primary problem?",
        "Could the nearby industrial area be contributing?",
        "Show me the decision trace.",
    ],
)
def test_every_supported_question_gets_a_grounded_answer(monkeypatch, question):
    configure(monkeypatch, explainability, explainability_ai_provider="none")
    from tests.test_decision_engine import geo_context

    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report(), geo=geo_context())
    decision = decision.model_copy(
        update={"reasons": recovery_core.top_reasons(decision), "recovery": recovery_core.recovery_plan(decision)}
    )
    _remember(decision)

    response = chat_service.answer("a1", question)
    assert response is not None and response.answer.strip()
    assert response.analysis_id == "a1"


def test_the_industrial_answer_refuses_to_attribute_cause(monkeypatch):
    configure(monkeypatch, explainability, explainability_ai_provider="none")
    from tests.test_decision_engine import geo_context

    decision = run_engine(air=air_report(), waste=waste_report(), geo=geo_context())
    _remember(decision)

    answer = chat_service.answer("a1", "Could the nearby industrial area be contributing?").answer
    assert "does not establish" in answer
    assert "contextual only" in answer.lower()


def test_an_explainability_outage_falls_back_to_the_deterministic_answer(monkeypatch):
    class Failing:
        name = "groq"

        def complete(self, system, user):
            raise explainability.ExplainabilityUnavailable("Could not reach groq.")

    configure(monkeypatch, explainability, explainability_ai_provider="groq", groq_api_key="k")
    monkeypatch.setattr(explainability, "resolve_provider", lambda: Failing())
    decision = run_engine(air=air_report(), water=water_report())
    _remember(decision)

    response = chat_service.answer("a1", "What evidence supports this?")
    assert response is not None
    assert response.source == "deterministic" and response.llm_enhanced is False


# --------------------------------------------------------------------------- status endpoint


def test_status_never_leaks_a_key(monkeypatch):
    secret = "sk-super-secret-value-9876543210"
    configure(monkeypatch, functional, functional_ai_provider="gemini", gemini_api_key=secret)
    configure(monkeypatch, explainability, explainability_ai_provider="groq", groq_api_key=secret)

    blob = repr(functional.status()) + repr(explainability.status())
    assert secret not in blob
    # Not even a fragment long enough to be useful.
    assert secret[:12] not in blob


def test_status_reports_the_two_roles_separately(monkeypatch):
    configure(monkeypatch, functional, functional_ai_provider="gemini", gemini_api_key="k")
    configure(monkeypatch, explainability, explainability_ai_provider="groq", groq_api_key="k")

    assert functional.status()["provider"] == "gemini"
    assert explainability.status()["provider"] == "groq"
    assert functional.status()["configured"] is True
    assert explainability.status()["configured"] is True


def test_status_explains_why_a_role_is_unavailable(monkeypatch):
    configure(monkeypatch, explainability, explainability_ai_provider="openrouter", openrouter_api_key=None)
    status = explainability.status()
    assert status["available"] is False
    assert "OPENROUTER_API_KEY" in (status["detail"] or "")


# --------------------------------------------------------------------------- graph integration


def test_a_demo_run_carries_reasons_and_a_recovery_plan():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    decision = result.decision
    assert decision.reasons and all(r.evidence_ids for r in decision.reasons)
    assert decision.recovery is not None and decision.recovery.available
    # No provider configured in tests, so prose is absent and the deterministic text stands.
    assert decision.llm_explanation is None
    assert decision.explanation


def test_an_analysis_becomes_answerable_by_its_own_id():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    response = chat_service.answer(result.analysis_id, "What evidence supports this?")
    assert response is not None and response.analysis_id == result.analysis_id
