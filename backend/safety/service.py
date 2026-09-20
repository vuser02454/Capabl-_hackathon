"""Corpus-level operations: seeding, batch analysis, and the dashboard aggregate.

Batch runs deliberately skip the LLM. Forty-eight reports times three prose calls is roughly two
minutes of latency and a few hundred thousand tokens to produce sentences nobody reads during a
seed — and the classification would be byte-identical, because the rules decide it either way. The
LLM is reserved for the single-report path, where a human is actually reading the output.

That choice is also what makes the demo robust: seeding never touches the network, so the corpus
and every pattern derived from it exist whether or not an API key works.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from safety import llm, store, synthetic
from safety.agents import (
    PatternDetectionAgent,
    ReportParserAgent,
    RiskAnalysisAgent,
    SafetyAdvisorAgent,
)

logger = logging.getLogger(__name__)

_parser = ReportParserAgent()
_risk = RiskAnalysisAgent()
_patterns = PatternDetectionAgent()
_advisor = SafetyAdvisorAgent()


def analyze_without_llm(report_text: str, source: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Parse + classify deterministically. Used for batch; identical classification to the graph."""
    available = llm.available
    try:
        llm.available = lambda: False  # type: ignore[assignment]
        facts = _parser.run(report_text, source)
        analysis = _risk.run(report_text, facts, history)
    finally:
        llm.available = available  # type: ignore[assignment]
    return {"facts": facts, "analysis": analysis}


def _persist(report_text: str, source: str, facts: Dict[str, Any], analysis: Dict[str, Any]) -> int:
    return store.save_report(
        {
            "report_text": report_text,
            "source": source,
            "location": facts.get("location"),
            "department": facts.get("department"),
            "equipment": facts.get("equipment"),
            "incident_type": facts.get("incident_type"),
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


def batch_analyze(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyse and persist a list of `{report_text, source}`. Deterministic, no network."""
    store.init()
    processed = 0
    failures: List[Dict[str, str]] = []
    for record in reports:
        text = (record.get("report_text") or "").strip()
        if not text:
            failures.append({"report_text": "", "error": "empty report text"})
            continue
        try:
            history = store.all_analyses()
            result = analyze_without_llm(text, record.get("source", "synthetic"), history)
            _persist(text, record.get("source", "synthetic"), result["facts"], result["analysis"])
            processed += 1
        except Exception as exc:  # noqa: BLE001 - one bad report must not abort the batch
            logger.warning("batch_report_failed error=%s", type(exc).__name__)
            failures.append({"report_text": text[:80], "error": type(exc).__name__})
    return {"processed": processed, "failed": len(failures), "failures": failures[:5],
            "total_in_store": store.count()}


def seed_synthetic(force: bool = False) -> Dict[str, Any]:
    """Load the synthetic corpus. No-op when data already exists unless `force`."""
    store.init()
    existing = store.count()
    if existing and not force:
        return {"seeded": False, "reason": "reports already present", "total_in_store": existing}
    if force:
        store.reset()
    outcome = batch_analyze(synthetic.records())
    outcome["seeded"] = True
    return outcome


def patterns(interpret: bool = True) -> Dict[str, Any]:
    store.init()
    return _patterns.run(store.all_analyses(), interpret=interpret)


def overview() -> Dict[str, Any]:
    """Everything the dashboard needs, in one call."""
    store.init()
    corpus = store.all_analyses()
    stats = _patterns.run(corpus, interpret=False)
    recent = store.list_reports(limit=8)
    synthetic_count = sum(1 for row in corpus if row.get("source") == "synthetic")
    return {
        "total_reports": len(corpus),
        "synthetic_reports": synthetic_count,
        "user_reports": len(corpus) - synthetic_count,
        "risk_distribution": stats["risk_distribution"],
        "top_hazards": stats["top_hazards"],
        "top_risk_factors": stats["top_risk_factors"],
        "high_risk_locations": stats["high_risk_locations"],
        "top_departments": stats["top_departments"],
        "recurring_causes": stats["recurring_causes"],
        "incident_types": stats["incident_types"],
        "emerging_patterns": stats["emerging_patterns"],
        "trend_summary": stats["trend_summary"],
        "recent_reports": recent,
        "llm_available": llm.available(),
        "llm_model": llm.model_name(),
    }


def advise_for(report_id: int) -> Optional[Dict[str, Any]]:
    """Regenerate advice for a stored report, in the context of the current corpus."""
    record = store.get_report(report_id)
    if not record or not record.get("analysis"):
        return None
    facts = {
        "hazards": record["analysis"].get("hazards", []),
        "missing_controls": record["analysis"].get("missing_controls", []),
        "location": record["report"].get("location"),
        "equipment": record["report"].get("equipment"),
        "injury_present": record["analysis"].get("injury_present"),
    }
    return _advisor.run(facts, record["analysis"], patterns(interpret=False))
