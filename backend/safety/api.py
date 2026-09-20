"""Safety Intelligence API — the C3 incident-precursor endpoints.

Mounted as its own router so the pivot adds surface rather than editing the environmental routes.
Responses are plain dicts with camelCase keys, matching the convention the existing `ApiModel`
schemas already produce for the frontend.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from safety import graph, llm, service, store, synthetic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["safety"])

DISCLAIMER = (
    "This system is an AI-assisted safety screening and decision-support tool. It does not replace "
    "qualified safety professionals, workplace procedures, or regulatory requirements."
)
SYNTHETIC_NOTICE = (
    "The demo corpus consists of synthetic reports written for this demonstration. It does not "
    "represent real-world incident frequencies."
)

MAX_REPORT_CHARS = 8000


class AnalyzeRequest(BaseModel):
    report_text: str = Field(min_length=1, max_length=MAX_REPORT_CHARS)
    source: str = "user"
    persist: bool = True


class BatchRequest(BaseModel):
    reports: Optional[List[Dict[str, Any]]] = None
    use_synthetic: bool = True
    force: bool = False


def _camel_key(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part.title() for part in rest)


def _camel(value: Any) -> Any:
    """snake_case -> camelCase, RECURSIVELY.

    One level is not enough: the aggregate payloads are lists of dicts (`high_risk_locations`
    carries `high_risk_count`), and a shallow conversion leaves those keys snake_case so the UI
    renders an empty slot where the number should be.
    """
    if isinstance(value, dict):
        return {_camel_key(k): _camel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camel(item) for item in value]
    return value


def _shape_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    facts, analysis, advice = result["facts"], result["analysis"], result["advice"]
    return {
        "reportId": result.get("report_id"),
        "report": {
            "reportText": None,  # echoed by the caller; not duplicated here
            "source": facts.get("source"),
            "location": facts.get("location"),
            "department": facts.get("department"),
            "equipment": facts.get("equipment"),
            "incidentType": facts.get("incident_type"),
        },
        "extraction": {
            "summary": facts.get("summary"),
            "hazards": facts.get("hazards", []),
            "riskFactors": facts.get("risk_factors", []),
            "missingControls": facts.get("missing_controls", []),
            "rootCause": facts.get("root_cause"),
            "contributingFactors": facts.get("contributing_factors", []),
            "severityIndicators": facts.get("severity_indicators", []),
            "injuryPresent": facts.get("injury_present"),
            "ppeIssue": facts.get("ppe_issue"),
            "environmentalCondition": facts.get("environmental_condition"),
            "confidence": facts.get("confidence"),
            "narrativeSource": facts.get("narrative_source"),
        },
        "analysis": {
            "riskLevel": analysis.get("risk_level"),
            "riskScore": analysis.get("risk_score"),
            "confidence": analysis.get("confidence"),
            "reasoning": analysis.get("reasoning", []),
            "criticalFactors": analysis.get("critical_factors", []),
            "contributions": [_camel(c) for c in analysis.get("contributions", [])],
            "repeatHits": analysis.get("repeat_hits", 0),
            "narrativeSource": analysis.get("narrative_source"),
            "ruleBasis": _camel(analysis.get("rule_basis", {})),
        },
        "recommendations": {
            "priority": advice.get("priority"),
            "recommendedActions": advice.get("recommended_actions", []),
            "preventiveActions": advice.get("preventive_actions", []),
            "reasoning": advice.get("reasoning"),
            "humanReviewRequired": advice.get("human_review_required"),
            "narrativeSource": advice.get("narrative_source"),
        },
        "trace": result.get("trace", []),
        "disclaimer": DISCLAIMER,
    }


@router.get("/health")
async def health() -> Dict[str, Any]:
    store.init()
    return {
        "status": "ok",
        "service": "EcoSentinel Safety Intelligence",
        "reportsStored": store.count(),
        "llmAvailable": llm.available(),
        "llmModel": llm.model_name(),
        "syntheticAvailable": synthetic.count(),
        "disclaimer": DISCLAIMER,
    }


@router.post("/reports/analyze")
async def analyze(request: AnalyzeRequest) -> Dict[str, Any]:
    """Run one report through the four-agent workflow."""
    text = request.report_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Report text cannot be empty.")
    try:
        result = await run_in_threadpool(graph.analyze_report, text, request.source, request.persist)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface a usable error, never a stack trace
        logger.exception("safety_analyze_failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(exc).__name__}") from exc

    shaped = _shape_analysis(result)
    shaped["report"]["reportText"] = text
    return shaped


@router.post("/reports/batch-analyze")
async def batch_analyze(request: BatchRequest) -> Dict[str, Any]:
    """Seed or analyse a corpus. Deterministic and offline — no LLM calls."""
    try:
        if request.use_synthetic and not request.reports:
            outcome = await run_in_threadpool(service.seed_synthetic, request.force)
        else:
            outcome = await run_in_threadpool(service.batch_analyze, request.reports or [])
    except Exception as exc:  # noqa: BLE001
        logger.exception("safety_batch_failed")
        raise HTTPException(status_code=500, detail=f"Batch analysis failed: {type(exc).__name__}") from exc
    outcome["syntheticNotice"] = SYNTHETIC_NOTICE
    return outcome


@router.get("/reports")
async def list_reports(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    store.init()
    rows = await run_in_threadpool(store.list_reports, limit)
    return {"count": len(rows), "reports": [_camel(r) for r in rows],
            "syntheticNotice": SYNTHETIC_NOTICE}


@router.get("/reports/{report_id}")
async def get_report(report_id: int) -> Dict[str, Any]:
    store.init()
    record = await run_in_threadpool(store.get_report, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} was not found.")
    advice = await run_in_threadpool(service.advise_for, report_id)
    return {
        "report": _camel(record["report"]),
        "analysis": _camel(record["analysis"]) if record["analysis"] else None,
        "recommendations": _camel(advice) if advice else None,
        "disclaimer": DISCLAIMER,
    }


@router.get("/analytics/overview")
async def overview() -> Dict[str, Any]:
    data = await run_in_threadpool(service.overview)
    return {
        "totalReports": data["total_reports"],
        "syntheticReports": data["synthetic_reports"],
        "userReports": data["user_reports"],
        "riskDistribution": data["risk_distribution"],
        "topHazards": _camel(data["top_hazards"]),
        "topRiskFactors": _camel(data["top_risk_factors"]),
        "highRiskLocations": _camel(data["high_risk_locations"]),
        "topDepartments": _camel(data["top_departments"]),
        "recurringCauses": _camel(data["recurring_causes"]),
        "incidentTypes": _camel(data["incident_types"]),
        "emergingPatterns": _camel(data["emerging_patterns"]),
        "trendSummary": data["trend_summary"],
        "recentReports": [_camel(r) for r in data["recent_reports"]],
        "llmAvailable": data["llm_available"],
        "llmModel": data["llm_model"],
        "syntheticNotice": SYNTHETIC_NOTICE,
        "disclaimer": DISCLAIMER,
    }


@router.get("/analytics/patterns")
async def patterns(interpret: bool = Query(True)) -> Dict[str, Any]:
    data = await run_in_threadpool(service.patterns, interpret)
    return {
        "reportCount": data["report_count"],
        "riskDistribution": data["risk_distribution"],
        "topHazards": _camel(data["top_hazards"]),
        "topRiskFactors": _camel(data["top_risk_factors"]),
        "highRiskLocations": _camel(data["high_risk_locations"]),
        "topDepartments": _camel(data["top_departments"]),
        "recurringCauses": _camel(data["recurring_causes"]),
        "incidentTypes": _camel(data["incident_types"]),
        "emergingPatterns": _camel(data["emerging_patterns"]),
        "trendSummary": data["trend_summary"],
        "narrativeSource": data["narrative_source"],
        "syntheticNotice": SYNTHETIC_NOTICE,
    }


@router.get("/agents/workflow")
async def workflow() -> Dict[str, Any]:
    """The graph's shape, so the UI renders the real node list rather than a hardcoded copy."""
    return {"nodes": graph.workflow_nodes(), "llmAvailable": llm.available(),
            "llmModel": llm.model_name()}
