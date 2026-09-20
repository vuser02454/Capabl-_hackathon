"""LangGraph workflow wiring the safety agents together.

    START -> parse -> risk -> store -> patterns -> hotspots -> incident_domain
          -> (emergency_router)
               |-- specialized_response   (MEDICAL / FIRE / VIOLENCE_SECURITY /
               |                           ELECTRICAL / CHEMICAL / WILDLIFE)
               \-- advise                 (everything else)
          -> explainable_advisor -> END

`emergency_router` is a conditional edge rather than a node: it makes no state change, it only
chooses which branch runs. Both branches converge on `explainable_advisor`, so every report gets
the same historical-evidence treatment whether or not it was routed to a specialised responder.

Each node owns exactly one step and writes only its own slice of the state, so a hand-off is a real
boundary rather than four calls inside one function. The order matters and encodes two dependencies
that are easy to get wrong:

`store` runs BEFORE `patterns`, so the report being analysed is part of the corpus it is compared
against — otherwise the very first report of a recurring problem reports "no pattern" and the
system misses the thing it exists to catch.

`risk` runs BEFORE `store` and reads history, so recurrence can raise the score of the report that
completes a pattern.

The graph is compiled once at import. LangGraph is already a project dependency, used by the
environmental orchestrator, so this follows the existing convention.
"""

from __future__ import annotations

import logging
import operator
from typing import Any, Dict, List, Optional

# `Annotated`/`TypedDict` must be resolvable at MODULE scope: LangGraph calls get_type_hints() on
# the state schema, and on Python 3.9 that cannot see names bound inside a function.
from typing_extensions import Annotated, TypedDict

from safety import authority as authority_lookup
from safety import domains, geo, history, store
from safety.agents import (
    PatternDetectionAgent,
    ReportParserAgent,
    RiskAnalysisAgent,
    SafetyAdvisorAgent,
)

logger = logging.getLogger(__name__)


class SafetyState(TypedDict, total=False):
    """What flows between nodes. Every key is written by exactly one node."""

    report_text: str
    source: str
    persist: bool
    #: The fix the worker explicitly confirmed, or None. Flows through the graph so `store`
    #: writes it with the report and the history node can use it without a second query.
    latitude: Optional[float]
    longitude: Optional[float]
    gps_accuracy: Optional[float]
    location_source: str
    location_text: Optional[str]
    #: When the device took the fix. Must be declared here: LangGraph drops state keys its schema
    #: does not name, so an undeclared field silently arrives as None at the node that stores it.
    location_captured_at: Optional[str]
    facts: Dict[str, Any]
    analysis: Dict[str, Any]
    patterns: Dict[str, Any]
    advice: Dict[str, Any]
    hotspots: List[Dict[str, Any]]
    domain: Dict[str, Any]
    authority: Dict[str, Any]
    specialized: Dict[str, Any]
    history: Dict[str, Any]
    explanation: Dict[str, Any]
    report_id: Optional[int]
    #: Each node appends its own entry; the reducer preserves hand-off order.
    trace: Annotated[List[Dict[str, Any]], operator.add]


parser_agent = ReportParserAgent()
risk_agent = RiskAnalysisAgent()
pattern_agent = PatternDetectionAgent()
advisor_agent = SafetyAdvisorAgent()


def _parse_node(state: SafetyState) -> Dict[str, Any]:
    facts = parser_agent.run(state["report_text"], state.get("source", "user"))
    return {"facts": facts, "trace": [parser_agent.trace(facts)]}


def _risk_node(state: SafetyState) -> Dict[str, Any]:
    corpus = store.all_analyses()
    analysis = risk_agent.run(state["report_text"], state["facts"], corpus)
    return {"analysis": analysis, "trace": [risk_agent.trace(analysis)]}


def _store_node(state: SafetyState) -> Dict[str, Any]:
    """Persist before pattern detection, so this report counts toward its own comparison."""
    if not state.get("persist", True):
        return {"report_id": None,
                "trace": [{"agent": "Store", "status": "skipped",
                           "detail": "Preview mode — analysis not persisted", "payload": {}}]}
    facts, analysis = state["facts"], state["analysis"]
    report_id = store.save_report(
        {
            "report_text": state["report_text"],
            "source": state.get("source", "user"),
            "location": facts.get("location"),
            "department": facts.get("department"),
            "equipment": facts.get("equipment"),
            "incident_type": facts.get("incident_type"),
            "latitude": state.get("latitude"),
            "longitude": state.get("longitude"),
            "gps_accuracy": state.get("gps_accuracy"),
            "location_source": state.get("location_source") or "unknown",
            "location_text": state.get("location_text"),
            "location_captured_at": state.get("location_captured_at"),
        },
        {
            "risk_level": analysis["risk_level"],
            "risk_score": analysis["risk_score"],
            "summary": facts.get("summary"),
            "hazards": facts.get("hazards", []),
            "risk_factors": facts.get("risk_factors", []),
            "missing_controls": facts.get("missing_controls", []),
            "root_cause": facts.get("root_cause"),
            "contributing_factors": facts.get("contributing_factors", []),
            "severity_indicators": facts.get("severity_indicators", []),
            "injury_present": facts.get("injury_present"),
            "ppe_issue": facts.get("ppe_issue"),
            "confidence": analysis.get("confidence", 0),
            "reasoning": analysis.get("reasoning", []),
            "contributions": analysis.get("contributions", []),
            "recommendations": {},
            "narrative_source": analysis.get("narrative_source", "rules"),
        },
    )
    return {"report_id": report_id,
            "trace": [{"agent": "Store", "status": "ok",
                       "detail": f"Saved as report #{report_id}",
                       "payload": {"report_id": report_id}}]}


def _pattern_node(state: SafetyState) -> Dict[str, Any]:
    corpus = store.all_analyses()
    patterns = pattern_agent.run(corpus, interpret=True)
    return {"patterns": patterns, "trace": [pattern_agent.trace(patterns)]}


def _hotspot_node(state: SafetyState) -> Dict[str, Any]:
    """Geographic clustering over stored reports. Entirely deterministic — no LLM involved.

    Runs after `patterns` (which is aspatial) and before `advise`, so the advisor can cite a
    recurring LOCATION as well as a recurring hazard. Detection only ever creates or refreshes a
    PENDING_REVIEW candidate; publishing is a human action.
    """
    corpus = store.all_analyses()
    candidates = geo.detect_hotspots(corpus)
    ids = [store.upsert_hotspot(c) for c in candidates]
    detail = (f"{len(candidates)} candidate hotspot(s) · "
              f"{geo.HOTSPOT_MIN_REPORTS}+ related reports within {geo.HOTSPOT_RADIUS_METERS} m")
    return {"hotspots": candidates,
            "trace": [{"agent": "Geographic Hotspot Agent", "status": "ok", "detail": detail,
                       "payload": {"rule": geo.rule_description(), "hotspot_ids": ids,
                                   "candidates": [{"primary_hazard": c["primary_hazard"],
                                                   "report_count": c["report_count"],
                                                   "max_spread_meters": c["max_spread_meters"]}
                                                  for c in candidates[:3]]}}]}


def _domain_node(state: SafetyState) -> Dict[str, Any]:
    """Classify which kind of incident this is. Deterministic, and carries its own evidence."""
    result = domains.classify(state["report_text"])
    detail = f"{result['label']}"
    if result.get("matched_text"):
        detail += f" — matched {result['matched_text']!r}"
    return {"domain": result,
            "trace": [{"agent": "Incident Domain Agent", "status": "ok", "detail": detail,
                       "payload": {"domain": result["domain"],
                                   "authority_type": result["authority_type"],
                                   "evidence": result.get("evidence"),
                                   "also_matched": [m["domain"] for m in result["also_matched"]]}}]}


def _emergency_router(state: SafetyState) -> str:
    """Conditional edge: specialised branch for emergency domains, ordinary advisor otherwise.

    Makes no state change — LangGraph calls this only to choose the next node. Keeping it edge-only
    means the routing decision cannot quietly alter the analysis on its way past.
    """
    domain = (state.get("domain") or {}).get("domain")
    return "specialized_response" if domain in domains.EMERGENCY_DOMAINS else "advise"


def _specialized_node(state: SafetyState) -> Dict[str, Any]:
    """Emergency-domain response: look up the relevant authority and state what a human should do.

    The lookup can fail and that is fine — `authority.lookup` returns its failure as data, the
    analysis continues, and the UI says "Authority lookup unavailable" instead of inventing a
    contact. This node never contacts anyone.
    """
    domain = state.get("domain") or {}
    latitude, longitude = state.get("latitude"), state.get("longitude")

    if latitude is None or longitude is None:
        found = {"available": False, "authority_type": domain.get("authority_type"),
                 "results": [],
                 "reason": "No coordinates on this report, so no nearby authority can be located.",
                 "source": None}
    else:
        found = authority_lookup.lookup(float(latitude), float(longitude), domain.get("authority_type"))

    nearest = (found.get("results") or [None])[0]
    recommendation = (
        f"Safety Admin should assess the situation and consider contacting the appropriate "
        f"{(found.get('label') or 'emergency').lower()} authority."
    )
    detail = f"{domain.get('label', 'Emergency')} — "
    detail += (f"nearest {found.get('label', 'authority')}: {nearest['name']}"
               if nearest else (found.get("reason") or "no authority located"))

    return {
        "authority": found,
        "specialized": {
            "domain": domain.get("domain"),
            "label": domain.get("label"),
            "authority": found,
            "nearest": nearest,
            "recommendation": recommendation,
            # Stated on every specialised response so the branch cannot read as an instruction.
            "disclaimer": ("This is a screening recommendation for a human safety officer. "
                           "The system does not contact any authority and does not declare an "
                           "emergency."),
        },
        "trace": [{"agent": "Specialized Response Agent", "status": "ok", "detail": detail,
                   "payload": {"domain": domain.get("domain"),
                               "authority_type": found.get("authority_type"),
                               "available": found.get("available"),
                               "result_count": len(found.get("results") or []),
                               "source": found.get("source")}}],
    }


def _advise_node(state: SafetyState) -> Dict[str, Any]:
    advice = advisor_agent.run(state["facts"], state["analysis"], state.get("patterns", {}))
    return {"advice": advice, "trace": [advisor_agent.trace(advice)]}


def _explainable_node(state: SafetyState) -> Dict[str, Any]:
    """Attach the area's incident history and an assessment built only from it.

    Runs for every report, emergency-routed or not, so the explanation is uniform. With no
    coordinates there is no geographic history to report, and the node says exactly that rather
    than falling back to a non-geographic summary that would read as if it were one.
    """
    latitude, longitude = state.get("latitude"), state.get("longitude")
    facts = state.get("facts") or {}
    current = {"domain": (state.get("domain") or {}).get("domain"),
               "hazards": facts.get("hazards") or []}

    if latitude is None or longitude is None:
        block = {"radius_meters": geo.HOTSPOT_RADIUS_METERS, "report_count": 0,
                 "risk_breakdown": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
                 "recurring_hazards": [], "all_hazards": [], "incident_types": [],
                 "serious_incidents": [], "serious_incident_count": 0,
                 "first_report_at": None, "latest_report_at": None, "report_ids": [],
                 "previous_recommendations": [], "unavailable_reason":
                     "This report has no coordinates, so no geographic incident history applies."}
        explanation = {"statement": block["unavailable_reason"], "findings": [],
                       "serious_history": [], "evidence_report_ids": [], "basis": "stored reports"}
    else:
        corpus = store.all_analyses()
        exclude = [state["report_id"]] if state.get("report_id") else []
        block = history.summarise(corpus, float(latitude), float(longitude),
                                  geo.HOTSPOT_RADIUS_METERS, exclude_ids=exclude)
        explanation = history.assessment(block, current)

    detail = (f"{block['report_count']} previous report(s) within "
              f"{block['radius_meters']} m · {block['serious_incident_count']} serious")
    return {"history": block, "explanation": explanation,
            "trace": [{"agent": "Explainable Advisor", "status": "ok", "detail": detail,
                       "payload": {"report_count": block["report_count"],
                                   "serious_incident_count": block["serious_incident_count"],
                                   "evidence_report_ids": explanation["evidence_report_ids"][:10],
                                   "basis": "stored reports"}}]}


def _build():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(SafetyState)
    graph.add_node("parse", _parse_node)
    graph.add_node("risk", _risk_node)
    graph.add_node("store", _store_node)
    graph.add_node("patterns", _pattern_node)
    graph.add_node("hotspots", _hotspot_node)
    graph.add_node("incident_domain", _domain_node)
    graph.add_node("specialized_response", _specialized_node)
    graph.add_node("advise", _advise_node)
    graph.add_node("explainable_advisor", _explainable_node)

    graph.add_edge(START, "parse")
    graph.add_edge("parse", "risk")
    graph.add_edge("risk", "store")
    graph.add_edge("store", "patterns")
    graph.add_edge("patterns", "hotspots")
    graph.add_edge("hotspots", "incident_domain")

    # The emergency router. Both destinations converge on the explainable advisor, so a
    # specialised response is an ADDITION to the normal explanation, never a replacement for it.
    graph.add_conditional_edges(
        "incident_domain",
        _emergency_router,
        {"specialized_response": "specialized_response", "advise": "advise"},
    )
    graph.add_edge("specialized_response", "explainable_advisor")
    graph.add_edge("advise", "explainable_advisor")
    graph.add_edge("explainable_advisor", END)
    return graph.compile()


_COMPILED = None


def compiled():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _build()
    return _COMPILED


def analyze_report(
    report_text: str,
    source: str = "user",
    persist: bool = True,
    location: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one report through the full workflow. Raises ValueError on empty input.

    `location` carries the fix the worker confirmed — latitude, longitude, gps_accuracy,
    location_source, location_text. It is optional at every level: without it the report is still
    analysed, but there is no geographic history and no authority lookup, and both say so.
    """
    if not (report_text or "").strip():
        raise ValueError("Report text is empty.")
    fix = location or {}
    result = compiled().invoke({
        "report_text": report_text, "source": source, "persist": persist, "trace": [],
        "latitude": fix.get("latitude"), "longitude": fix.get("longitude"),
        "gps_accuracy": fix.get("gps_accuracy"),
        "location_source": fix.get("location_source") or "unknown",
        "location_text": fix.get("location_text"),
        "location_captured_at": fix.get("location_captured_at"),
    })
    return {
        "report_id": result.get("report_id"),
        "facts": result.get("facts", {}),
        "analysis": result.get("analysis", {}),
        "patterns": result.get("patterns", {}),
        "advice": result.get("advice", {}),
        "hotspots": result.get("hotspots", []),
        "domain": result.get("domain", {}),
        "authority": result.get("authority", {}),
        "specialized": result.get("specialized", {}),
        "history": result.get("history", {}),
        "explanation": result.get("explanation", {}),
        "trace": result.get("trace", []),
    }


def workflow_nodes() -> List[Dict[str, str]]:
    """The graph's shape, for the UI to render without hardcoding it in TypeScript."""
    return [
        {"id": "parse", "agent": ReportParserAgent.name, "role": "Extract structured facts from free text"},
        {"id": "risk", "agent": RiskAnalysisAgent.name, "role": "Classify LOW / MEDIUM / HIGH with cited evidence"},
        {"id": "store", "agent": "Store", "role": "Persist so the report joins the comparison corpus"},
        {"id": "patterns", "agent": PatternDetectionAgent.name, "role": "Aggregate recurring hazards and locations"},
        {"id": "hotspots", "agent": "Geographic Hotspot Agent",
         "role": f"Cluster related reports within {geo.HOTSPOT_RADIUS_METERS} m"},
        {"id": "incident_domain", "agent": "Incident Domain Agent",
         "role": "Classify the incident domain and pick the response branch"},
        {"id": "specialized_response", "agent": "Specialized Response Agent",
         "role": "Emergency domains only — look up the relevant authority"},
        {"id": "advise", "agent": SafetyAdvisorAgent.name,
         "role": "Recommend prioritised, specific actions"},
        {"id": "explainable_advisor", "agent": "Explainable Advisor",
         "role": f"Cite incident history within {geo.HOTSPOT_RADIUS_METERS} m as evidence"},
    ]
