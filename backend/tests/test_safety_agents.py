"""C3 Safety Intelligence: extraction, classification, aggregation and the API contract.

No test here touches the network. The LLM is monkeypatched off throughout, which is the point —
every property under test must hold from the deterministic path alone, because that is the path
that runs when the provider is down. If a test needed Groq to pass, the guarantee would be fiction.
"""

import pytest
from fastapi.testclient import TestClient

from safety import llm, rules, service, store
from safety.agents import (
    PatternDetectionAgent,
    ReportParserAgent,
    RiskAnalysisAgent,
    SafetyAdvisorAgent,
)

DEMO = (
    "At approximately 10:30 AM, a worker nearly slipped in the loading bay after oil leaked from "
    "a forklift. No warning signage was placed around the affected area. The worker was not injured."
)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Every assertion must hold without a language model."""
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """An isolated database per test; never the developer's real corpus."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init()
    return tmp_path / "test.db"


# --- extraction -------------------------------------------------------------------------------

def test_extracts_hazards_controls_and_location_from_the_demo_report():
    facts = ReportParserAgent().run(DEMO)
    assert "Oil spill" in facts["hazards"]
    assert "Slip / trip / fall" in facts["hazards"]
    assert "Warning signage missing" in facts["missing_controls"]
    assert facts["location"] == "Loading Bay"
    assert facts["equipment"] == "forklift"


def test_explicit_denial_of_injury_outranks_the_injury_keyword():
    # "was not injured" contains "injur" — the denial has to win, or every near miss files as one.
    facts = ReportParserAgent().run(DEMO)
    assert facts["injury_present"] is False
    assert facts["incident_type"] == "Near miss"


def test_unstated_information_is_null_never_guessed():
    facts = ReportParserAgent().run("A cone was left in the aisle.")
    assert facts["injury_present"] is None
    assert facts["location"] is None
    assert facts["department"] is None


def test_empty_report_is_rejected():
    with pytest.raises(ValueError):
        ReportParserAgent().run("   ")


# --- classification ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", rules.RISK_LEVELS)
def test_risk_levels_are_exactly_the_three_allowed(level):
    assert level in ("LOW", "MEDIUM", "HIGH")


def test_classification_is_restricted_to_the_controlled_vocabulary():
    for text in [DEMO, "Minor housekeeping issue noted.", "Fire in the boiler room.", ""]:
        facts = rules.extract(text)
        score, _ = rules.score(facts)
        level, _ = rules.classify(score, facts)
        assert level in rules.RISK_LEVELS


def test_demo_report_classifies_high_with_a_supporting_score():
    facts = ReportParserAgent().run(DEMO)
    analysis = RiskAnalysisAgent().run(DEMO, facts, history=[])
    assert analysis["risk_level"] == "HIGH"
    assert 0 <= analysis["risk_score"] <= 100
    assert analysis["risk_score"] >= rules.HIGH_THRESHOLD


def test_a_minor_observation_stays_low():
    text = "Housekeeping: some cardboard left near the wall in the canteen."
    facts = ReportParserAgent().run(text)
    analysis = RiskAnalysisAgent().run(text, facts, history=[])
    assert analysis["risk_level"] == "LOW"


def test_a_critical_signal_forces_high_regardless_of_score():
    # A short report scoring below the HIGH threshold on weights alone must still escalate.
    text = "An electrician received an electrical shock at the panel."
    facts = ReportParserAgent().run(text)
    analysis = RiskAnalysisAgent().run(text, facts, history=[])
    assert analysis["risk_level"] == "HIGH"
    assert analysis["rule_basis"]["forced_high"] is True


def test_every_scored_point_is_attributable_to_a_named_factor():
    facts = ReportParserAgent().run(DEMO)
    analysis = RiskAnalysisAgent().run(DEMO, facts, history=[])
    assert analysis["contributions"]
    assert sum(c["points"] for c in analysis["contributions"]) >= analysis["risk_score"]
    assert all(c["factor"] and isinstance(c["points"], int) for c in analysis["contributions"])


def test_recurrence_at_the_same_location_raises_the_score():
    facts = ReportParserAgent().run(DEMO)
    history = [{"location": "Loading Bay", "hazards": ["Oil spill"]} for _ in range(3)]
    alone = RiskAnalysisAgent().run(DEMO, facts, history=[])
    repeated = RiskAnalysisAgent().run(DEMO, facts, history=history)
    assert repeated["repeat_hits"] == 3
    assert repeated["risk_score"] >= alone["risk_score"]


def test_reasoning_is_produced_without_an_llm():
    facts = ReportParserAgent().run(DEMO)
    analysis = RiskAnalysisAgent().run(DEMO, facts, history=[])
    assert analysis["reasoning"]
    assert analysis["narrative_source"] == "rules"


# --- pattern aggregation ----------------------------------------------------------------------

def _corpus():
    return [
        {"location": "Loading Bay", "department": "Logistics", "incident_type": "Near miss",
         "hazards": ["Oil spill"], "risk_factors": ["Oil spill"], "root_cause": "Forklift leak",
         "risk_level": "HIGH", "risk_score": 70},
        {"location": "Loading Bay", "department": "Logistics", "incident_type": "Observation",
         "hazards": ["Oil spill"], "risk_factors": ["Oil spill"], "root_cause": "Forklift leak",
         "risk_level": "HIGH", "risk_score": 65},
        {"location": "Loading Bay", "department": "Logistics", "incident_type": "Observation",
         "hazards": ["Oil spill"], "risk_factors": ["Oil spill"], "root_cause": "Forklift leak",
         "risk_level": "MEDIUM", "risk_score": 40},
        {"location": "Warehouse", "department": "Warehouse", "incident_type": "Observation",
         "hazards": ["Housekeeping"], "risk_factors": ["Housekeeping"], "root_cause": None,
         "risk_level": "LOW", "risk_score": 10},
    ]


def test_aggregation_counts_hazards_and_locations():
    patterns = PatternDetectionAgent().run(_corpus(), interpret=False)
    assert patterns["report_count"] == 4
    assert patterns["risk_distribution"] == {"LOW": 1, "MEDIUM": 1, "HIGH": 2}
    assert patterns["top_hazards"][0]["name"] == "Oil spill"
    assert patterns["top_hazards"][0]["count"] == 3


def test_a_hazard_recurring_at_one_location_becomes_an_emerging_pattern():
    patterns = PatternDetectionAgent().run(_corpus(), interpret=False)
    titles = [p["pattern"] for p in patterns["emerging_patterns"]]
    assert any("Oil spill" in t and "Loading Bay" in t for t in titles)


def test_locations_rank_by_severity_not_volume():
    patterns = PatternDetectionAgent().run(_corpus(), interpret=False)
    assert patterns["high_risk_locations"][0]["location"] == "Loading Bay"
    assert patterns["high_risk_locations"][0]["high_risk_count"] == 2


def test_an_empty_corpus_does_not_crash():
    patterns = PatternDetectionAgent().run([], interpret=False)
    assert patterns["report_count"] == 0
    assert patterns["emerging_patterns"] == []


# --- advisor ----------------------------------------------------------------------------------

def test_advisor_produces_specific_actions_without_an_llm():
    facts = ReportParserAgent().run(DEMO)
    analysis = RiskAnalysisAgent().run(DEMO, facts, history=[])
    advice = SafetyAdvisorAgent().run(facts, analysis, PatternDetectionAgent().run(_corpus(), interpret=False))
    assert advice["recommended_actions"]
    # "Improve safety" is the failure mode: an action must name the place it applies to.
    assert any("Loading Bay" in action for action in advice["recommended_actions"])


def test_high_risk_always_requires_human_review():
    facts = ReportParserAgent().run(DEMO)
    analysis = RiskAnalysisAgent().run(DEMO, facts, history=[])
    advice = SafetyAdvisorAgent().run(facts, analysis, {})
    assert analysis["risk_level"] == "HIGH"
    assert advice["human_review_required"] is True


# --- persistence and the API --------------------------------------------------------------------

def test_reports_round_trip_through_sqlite(db):
    facts = ReportParserAgent().run(DEMO)
    analysis = RiskAnalysisAgent().run(DEMO, facts, history=[])
    report_id = store.save_report(
        {"report_text": DEMO, "source": "synthetic", "location": facts["location"]},
        {"risk_level": analysis["risk_level"], "risk_score": analysis["risk_score"],
         "hazards": facts["hazards"], "confidence": analysis["confidence"]},
    )
    fetched = store.get_report(report_id)
    assert fetched["report"]["source"] == "synthetic"
    assert fetched["analysis"]["risk_level"] == "HIGH"
    # JSON-shaped columns come back as lists, not strings.
    assert isinstance(fetched["analysis"]["hazards"], list)


def test_synthetic_corpus_is_labelled_synthetic(db):
    outcome = service.seed_synthetic(force=True)
    assert outcome["processed"] > 20
    assert all(row["source"] == "synthetic" for row in store.all_analyses())


def _client():
    import main

    return TestClient(main.app)


def test_health_endpoint_reports_status():
    response = _client().get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "disclaimer" in body


def test_analyze_endpoint_returns_the_full_contract():
    response = _client().post("/api/reports/analyze",
                              json={"report_text": DEMO, "persist": False})
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["riskLevel"] in rules.RISK_LEVELS
    assert body["extraction"]["hazards"]
    assert body["recommendations"]["recommendedActions"]
    assert body["trace"], "the agent trace is what demonstrates the hand-offs"
    assert "disclaimer" in body


@pytest.mark.parametrize("payload", [{"report_text": ""}, {"report_text": "   "}, {}])
def test_analyze_rejects_empty_or_missing_text(payload):
    response = _client().post("/api/reports/analyze", json=payload)
    assert response.status_code == 422


def test_unknown_report_id_is_404():
    assert _client().get("/api/reports/99999999").status_code == 404
