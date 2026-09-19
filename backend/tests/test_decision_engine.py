"""The LangGraph decision engine: evidence -> problems -> priority -> decision.

What these tests protect is mostly restraint. It is easy to build a system that always names a
primary concern, always reports a trend, and always sounds certain; the value here is that it
declines to do any of those things without evidence. So alongside the happy paths, these pin
down that the engine:

  - never emits a problem without a supporting evidence id
  - never claims causality, however suggestive the co-occurrence
  - never reports a trend for a signal that has no historical baseline
  - never lets an LLM, or mapped geography, touch a score
  - still produces a usable, honest decision when providers fail

Everything runs against fabricated reports — no network, no providers.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

import pytest

from core import decision as decision_core
from core import evidence as evidence_core
from schemas import (
    AirAgentResult,
    EnvironmentalEvidence,
    Finding,
    GeographicContext,
    GeographicFeature,
    Measurement,
    TriageDecision,
    WasteAgentResult,
    WasteCounts,
    WaterAgentResult,
)

NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------------- report builders


def air_report(pm25: float = 82.0, level: str = "HIGH", score: float = 0.8, anomalies=()) -> AirAgentResult:
    status = "critical" if pm25 >= 55 else "elevated" if pm25 > 15 else "normal"
    return AirAgentResult(
        location="Test", risk_level=level, risk_score=score, confidence=0.9, timestamp=NOW,
        data_source="OpenAQ v3", is_mock=False,
        measurements=[
            Measurement(key="pm25", label="PM2.5", value=pm25, unit="µg/m³", threshold=15,
                        threshold_label="WHO guideline", sub_score=min(1.0, pm25 / 100), status=status)
        ],
        findings=[Finding(code="air.pm25", label="PM2.5 above guideline", detail=f"{pm25} µg/m³", impact=0.5)],
        station_id="S1", station_name="Station 1", pm25=pm25, pm10=None, no2=None, o3=None,
        aqi=180, aqi_category="Poor", dominant_pollutant="pm25", anomalies=list(anomalies),
    )


def water_report(turbidity: Optional[float] = 11.2, level: str = "HIGH", score: float = 0.75) -> WaterAgentResult:
    status = "critical" if (turbidity or 0) >= 10 else "elevated" if (turbidity or 0) > 5 else "normal"
    measurements = [
        Measurement(key="turbidity", label="Turbidity", value=turbidity, unit="NTU", threshold=5,
                    threshold_label="BIS limit", sub_score=min(1.0, (turbidity or 0) / 15),
                    status=status if turbidity is not None else "missing")
    ]
    return WaterAgentResult(
        location="Test", risk_level=level, risk_score=score, confidence=0.85, timestamp=NOW,
        data_source="Test sensor", is_mock=False, measurements=measurements, findings=[],
        sensor_id="W1", sensor_name="Sensor 1", sensor_status="online",
        ph=7.0, turbidity=turbidity, temperature=22.0, source_type="live_iot",
    )


def waste_report(total: int = 14, plastic: int = 11, level: str = "HIGH", score: float = 0.88) -> WasteAgentResult:
    return WasteAgentResult(
        location="Test", risk_level=level, risk_score=score, confidence=0.8, timestamp=NOW,
        data_source="YOLO", is_mock=False, measurements=[], findings=[],
        source_id="C1", source_name="Camera 1", input_type="camera", model="yolov8n",
        total_objects=total,
        counts=WasteCounts(plastic=plastic, paper=max(0, total - plastic), other=0),
        density_index=total / 20, detections=[],
    )


def geo_context() -> GeographicContext:
    return GeographicContext(
        available=True, status="ok", radius_m=1500,
        industrial_features=[
            GeographicFeature(osm_id="way/1", name="Peenya Estate", category="industrial",
                              kind="industrial", label="Industrial area",
                              latitude=12.97, longitude=77.59, distance_km=0.4)
        ],
    )


def domain_risk(air=None, water=None, waste=None):
    return {
        domain: (r.risk_level, r.risk_score, r.confidence)
        for domain, r in (("air", air), ("water", water), ("waste", waste))
        if r is not None
    }


def run_engine(air=None, water=None, waste=None, geo=None, risk=("HIGH", 0.81, 0.89)):
    """The deterministic pipeline exactly as the graph runs it."""
    evidence = evidence_core.normalize(air, water, waste, geo)
    problems = decision_core.detect_problems(evidence, domain_risk(air, water, waste))
    findings = decision_core.cross_signal_findings(evidence)
    conflicts = decision_core.evaluate_conflicts(evidence)
    reporting = [d for d, r in (("air", air), ("water", water), ("waste", waste)) if r is not None]
    return decision_core.synthesize(
        evidence=evidence, problems=problems, findings=findings, conflicts=conflicts,
        risk_level=risk[0], risk_score=risk[1], confidence=risk[2],
        reporting_domains=reporting, triage=TriageDecision(domains=reporting), data_status="live",
    )


# --------------------------------------------------------------------------- evidence normalization


def test_every_domain_normalises_into_one_representation():
    evidence = evidence_core.normalize(air_report(), water_report(), waste_report(), geo_context())
    domains = {item.domain for item in evidence}
    assert domains == {"air", "water", "waste", "geographic"}
    assert {item.kind for item in evidence} >= {"measurement", "detection", "context"}


def test_severity_is_taken_from_the_specialist_not_recomputed():
    """The specialists' own sub_score stays the scale of record."""
    report = air_report(pm25=82.0)
    item = next(i for i in evidence_core.from_air(report) if i.evidence_id == "air.pm25")
    assert item.severity == pytest.approx(0.82, abs=0.01)


def test_mapped_geography_carries_no_severity_and_no_confidence():
    """Context can never raise a score — a drawn polygon is not an emission."""
    items = evidence_core.from_geographic(geo_context())
    assert items and all(i.severity == 0.0 and i.confidence == 0.0 for i in items)


def test_a_missing_measurement_becomes_evidence_of_a_gap():
    evidence = evidence_core.from_water(water_report(turbidity=None))
    gap = next(i for i in evidence if i.status == "missing")
    assert gap.severity == 0.0 and "not reported" in gap.detail


# --------------------------------------------------------------------------- problem detection


def test_air_evidence_produces_an_air_problem():
    decision = run_engine(air=air_report(), water=water_report(turbidity=1.0, level="LOW", score=0.1))
    categories = {p.category for p in [decision.primary_problem, *decision.secondary_problems] if p}
    assert "air" in categories


def test_no_problem_is_emitted_without_supporting_evidence():
    """A clean location must be able to report nothing, rather than inventing a concern."""
    decision = run_engine(
        air=air_report(pm25=5.0, level="LOW", score=0.1),
        water=water_report(turbidity=1.0, level="LOW", score=0.1),
        risk=("LOW", 0.12, 0.9),
    )
    assert decision.primary_problem is None
    assert decision.secondary_problems == []


def test_every_problem_traces_back_to_evidence():
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    problems = [decision.primary_problem, *decision.secondary_problems]
    assert problems and all(p.evidence_ids for p in problems if p)


def test_two_elevated_domains_raise_a_cross_signal_problem():
    evidence = evidence_core.normalize(air_report(), water_report(), None, None)
    problems = decision_core.detect_problems(evidence, domain_risk(air_report(), water_report()))
    cross = [p for p in problems if p.category == "cross_signal"]
    assert len(cross) == 1
    # A shared driver is a hypothesis, never an observation.
    assert cross[0].causal_status == "supported_hypothesis"


# --------------------------------------------------------------------------- cross-signal & causality


def test_cross_signal_findings_never_claim_causality():
    decision = run_engine(air=air_report(), waste=waste_report(), geo=geo_context())
    assert decision.cross_signal_findings
    for finding in decision.cross_signal_findings:
        assert finding.causality == "not_established"
        lowered = finding.detail.lower()
        assert "caused by" not in lowered
        assert "because of" not in lowered
        assert any(hedge in lowered for hedge in ("warrants", "does not establish", "not sufficient"))


def test_mapped_industry_beside_elevated_readings_is_named_never_blamed():
    decision = run_engine(air=air_report(), waste=waste_report(), geo=geo_context())
    finding = next(f for f in decision.cross_signal_findings if "industrial" in f.finding_id)
    assert "does not establish that this feature caused" in finding.detail


# --------------------------------------------------------------------------- direction


def test_no_baseline_means_no_trend_is_claimed():
    """Water and waste have no history; reporting "stable" would assert an unmeasured trend."""
    decision = run_engine(water=water_report(), waste=waste_report())
    assert decision.overall_direction == "insufficient_history"


def test_a_real_air_baseline_produces_a_deterioration_signal():
    decision = run_engine(
        air=air_report(anomalies=["PM2.5 is 2.1× its 24-hour baseline"]), waste=waste_report()
    )
    assert decision.overall_direction == "deteriorating"


def test_opposing_directions_report_mixed_never_a_single_verdict():
    evidence = [
        EnvironmentalEvidence(evidence_id="water.turbidity", domain="water", kind="measurement",
                              label="Turbidity", detail="improving", severity=0.5, confidence=0.8,
                              direction="improving"),
        EnvironmentalEvidence(evidence_id="waste.density", domain="waste", kind="detection",
                              label="Litter density", detail="worsening", severity=0.6, confidence=0.8,
                              direction="deteriorating"),
    ]
    assert decision_core.overall_direction(evidence) == "mixed"


def test_conflicting_directions_are_surfaced_as_a_conflict():
    evidence = [
        EnvironmentalEvidence(evidence_id="water.turbidity", domain="water", kind="measurement",
                              label="Turbidity", detail="down", severity=0.5, confidence=0.8,
                              direction="improving"),
        EnvironmentalEvidence(evidence_id="waste.density", domain="waste", kind="detection",
                              label="Litter density", detail="up", severity=0.6, confidence=0.8,
                              direction="deteriorating"),
    ]
    conflicts = decision_core.evaluate_conflicts(evidence)
    assert conflicts and "Mixed environmental signals" in conflicts[0].detail


# --------------------------------------------------------------------------- prioritization


def test_priority_is_the_documented_product():
    """priority = severity x confidence x evidence_strength x persistence."""
    evidence = evidence_core.normalize(air_report(), None, None, None)
    problems = decision_core.detect_problems(evidence, domain_risk(air=air_report()))
    problem = problems[0]
    expected = (
        problem.severity_score
        * problem.confidence
        * decision_core.evidence_strength(len(problem.evidence_ids))
        * decision_core.persistence_factor(problem, evidence)
    )
    assert decision_core.problem_priority(problem, evidence) == pytest.approx(expected, abs=0.001)


def test_evidence_strength_rewards_independent_corroboration():
    assert decision_core.evidence_strength(1) == 0.5
    assert decision_core.evidence_strength(2) == 0.75
    assert decision_core.evidence_strength(4) == 1.0
    assert decision_core.evidence_strength(0) == 0.0


def test_a_snapshot_is_discounted_against_a_confirmed_trend():
    baseline_evidence = evidence_core.normalize(
        air_report(anomalies=["PM2.5 is 2.1× its 24-hour baseline"]), None, None, None
    )
    snapshot_evidence = evidence_core.normalize(air_report(), None, None, None)
    with_trend = decision_core.detect_problems(baseline_evidence, domain_risk(air=air_report()))[0]
    without = decision_core.detect_problems(snapshot_evidence, domain_risk(air=air_report()))[0]
    assert decision_core.persistence_factor(with_trend, baseline_evidence) == 1.0
    assert decision_core.persistence_factor(without, snapshot_evidence) == 0.75


def test_the_highest_priority_problem_becomes_primary():
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    ranked = [decision.primary_problem, *decision.secondary_problems]
    priorities = [p.priority for p in ranked if p]
    assert priorities == sorted(priorities, reverse=True)


def test_a_confident_moderate_problem_outranks_an_unconfident_severe_one():
    severe_but_unsure = water_report(level="HIGH", score=0.9)
    severe_but_unsure = severe_but_unsure.model_copy(update={"confidence": 0.2})
    confident_moderate = air_report(pm25=40.0, level="MODERATE", score=0.5)
    decision = run_engine(air=confident_moderate, water=severe_but_unsure)
    assert decision.primary_problem is not None
    assert decision.primary_problem.category == "air"


# --------------------------------------------------------------------------- sufficiency & planning


def test_a_single_reporting_domain_is_insufficient_to_cross_check():
    decision = run_engine(air=air_report())
    assert decision.sufficient_evidence is False
    assert decision.primary_problem is None
    assert any("cross-check" in gap for gap in decision.data_gaps)


def test_insufficient_evidence_still_produces_an_investigation_plan():
    decision = run_engine(air=air_report())
    assert decision.investigation_plan
    action = decision.investigation_plan[0]
    assert action.missing_data and action.rationale and action.provider


def test_the_plan_names_what_is_missing_why_it_matters_and_who_supplies_it():
    decision = run_engine(air=air_report(), water=water_report(turbidity=None))
    for action in decision.investigation_plan:
        assert action.missing_data, action.action_id
        assert action.rationale, action.action_id
        assert action.provider, action.action_id


def test_missing_history_is_reported_as_a_gap_and_an_action():
    decision = run_engine(water=water_report(), waste=waste_report())
    assert any("historical baseline" in gap for gap in decision.data_gaps)
    assert any(a.action_id == "investigate.persistence" for a in decision.investigation_plan)


# --------------------------------------------------------------------------- failure handling


def test_one_agent_failing_still_yields_a_decision_from_the_rest():
    decision = run_engine(air=None, water=water_report(), waste=waste_report())
    assert decision.primary_problem is not None
    assert any("No air evidence" in gap for gap in decision.data_gaps)
    assert any(a.action_id == "investigate.air" for a in decision.investigation_plan)


def test_all_agents_failing_yields_insufficient_evidence_and_no_problem():
    decision = run_engine(risk=("LOW", 0.0, 0.0))
    assert decision.sufficient_evidence is False
    assert decision.primary_problem is None
    assert decision.evidence == []
    assert "not enough evidence" in decision.explanation.lower()


def test_the_engine_never_recomputes_risk():
    """Risk stays the Coordinator's verdict; the decision only classifies what it points to."""
    decision = run_engine(air=air_report(), water=water_report(), risk=("MODERATE", 0.55, 0.7))
    assert decision.risk_level == "MODERATE"
    assert decision.risk_score == 0.55
    assert decision.confidence == 0.7


def test_risk_level_and_problem_classification_stay_separate():
    decision = run_engine(air=air_report(), water=water_report(), risk=("HIGH", 0.9, 0.8))
    assert decision.risk_level == "HIGH"
    # HIGH risk does not itself name the problem — evidence does.
    assert decision.primary_problem is not None
    assert decision.primary_problem.title != "HIGH"


# --------------------------------------------------------------------------- explainability


def test_the_trace_runs_from_evidence_through_problem_to_decision():
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    stages = [step.stage for step in decision.decision_trace]
    assert "evidence" in stages and "problem" in stages and "risk" in stages
    assert stages[-1] == "decision"
    assert [s.step for s in decision.decision_trace] == list(range(1, len(decision.decision_trace) + 1))


def test_the_decision_step_states_why_the_primary_was_chosen():
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    final = decision.decision_trace[-1]
    assert "highest priority" in final.detail
    assert "severity x confidence x evidence strength x persistence" in final.detail


def test_every_trace_evidence_id_exists_in_the_evidence_list():
    """A trace that cites evidence which is not present cannot be audited."""
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report(), geo=geo_context())
    known = {item.evidence_id for item in decision.evidence}
    for step in decision.decision_trace:
        assert set(step.evidence_ids) <= known, step.detail


def test_a_deterministic_explanation_exists_without_any_llm():
    decision = run_engine(air=air_report(), water=water_report())
    assert decision.explanation
    assert decision.llm_explanation is None
    assert decision.llm_enhanced is False


# --------------------------------------------------------------------------- graph integration


def test_the_graph_exposes_the_decision_stages():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    graph = LangGraphOrchestrator(demo_mode=True)._graph.get_graph()
    nodes = set(graph.nodes)
    assert {
        "triage_environment", "normalize_evidence", "detect_problems", "cross_signal_reasoning",
        "evaluate_conflicts", "check_data_sufficiency", "decision_synthesis",
        "investigation_needed", "frame_investigation", "explain_decision",
    } <= nodes

    edges = {(e.source, e.target) for e in graph.edges}
    assert ("resolve_location", "triage_environment") in edges
    # The decision engine consumes the deterministic risk score rather than racing it.
    assert ("coordinate", "normalize_evidence") in edges
    # The frame view is built from the finished decision, then explained.
    assert ("decision_synthesis", "frame_investigation") in edges
    assert ("frame_investigation", "explain_decision") in edges


def test_the_sufficiency_router_picks_the_branch_from_the_evidence():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    route = LangGraphOrchestrator._route_on_sufficiency
    assert route({"sufficient": True}) == "decision_synthesis"
    assert route({"sufficient": False}) == "investigation_needed"
    assert route({}) == "investigation_needed"


def test_a_full_demo_run_produces_a_traceable_decision():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    decision = result.decision
    assert decision is not None
    assert decision.data_status == "demo"  # demo data stays labelled as demo
    assert decision.primary_problem is not None
    assert decision.decision_trace and decision.evidence
    # Risk still comes from the Coordinator, unchanged.
    assert decision.risk_level == result.coordinator.overall_risk_level
    assert decision.risk_score == result.coordinator.overall_score


def test_selecting_a_different_location_does_not_leak_the_previous_decision():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    orchestrator = LangGraphOrchestrator(demo_mode=True)
    first = asyncio.run(orchestrator.analyze("Bengaluru", None))
    second = asyncio.run(orchestrator.analyze("Delhi", None))
    assert first.decision is not second.decision
    assert first.location != second.location
    # Evidence is rebuilt per run, never carried across.
    assert all(e.evidence_id for e in second.decision.evidence)


def test_demo_mode_labels_its_data_and_skips_geographic_triage():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    triage = result.decision.triage
    assert "geographic" in triage.skipped
    assert any("Demo Mode" in reason for reason in triage.rationale)


def test_triage_never_drops_a_specialist_domain():
    """A domain is skipped only when its provider cannot answer — never on a model's judgement."""
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    assert {"air", "water", "waste"} <= set(result.decision.triage.domains)


def test_the_primary_concern_is_always_actionable_never_the_meta_problem():
    """"Multiple interacting risks" says several things are wrong without saying where to start."""
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    assert decision.primary_problem is not None
    assert decision.primary_problem.category != "cross_signal"
    assert all(p.category != "cross_signal" for p in decision.secondary_problems)
    # The co-occurrence itself is still reported, as a finding.
    assert any(f.finding_id == "cross.co_occurrence" for f in decision.cross_signal_findings)


def test_the_cross_signal_problem_still_appears_in_the_trace():
    decision = run_engine(air=air_report(), water=water_report(), waste=waste_report())
    assert any("Multiple interacting" in step.detail for step in decision.decision_trace)


def test_the_architecture_diagram_names_only_real_graph_nodes():
    """The frontend diagram is documentation, not decoration.

    ArchitectureFlow.tsx labels its nodes with the graph node they represent ("Graph node · X").
    If a stage is renamed or removed in the backend without updating the picture, the dashboard
    starts describing a system that does not exist — so every name it claims must resolve.
    """
    import re
    from pathlib import Path

    from agents.langgraph_orchestrator import LangGraphOrchestrator

    diagram = Path(__file__).resolve().parents[2] / "frontend/src/components/architecture/ArchitectureFlow.tsx"
    if not diagram.exists():  # frontend is optional for a backend-only checkout
        pytest.skip("frontend sources not present")

    claimed = set()
    for match in re.findall(r"Graph nodes? · ([^'\"]+)", diagram.read_text()):
        for name in re.split(r"[→,]", match):
            cleaned = name.strip()
            if cleaned:
                claimed.add(cleaned)

    real = set(LangGraphOrchestrator(demo_mode=True)._graph.get_graph().nodes)
    assert claimed, "the diagram no longer labels its nodes with graph node names"
    assert claimed <= real, f"diagram names nodes the graph does not have: {sorted(claimed - real)}"
