"""The environmental chatbot: answers grounded in one specific decision.

The chatbot does not decide anything and does not hold opinions about the environment. It reads
the decision state for one analysis and reports what is in it. Where an explainability provider is
configured it phrases the answer; where one is not, the deterministic answer is returned instead —
so every question below is answerable with no LLM configured at all.

Context isolation is the property that matters most here. Answers are keyed by `analysis_id`, and
an id the store does not hold is refused rather than answered from whatever was analysed last.
Explaining River B with River A's evidence is the single worst failure this component can have,
because it is invisible: the prose reads perfectly and every number in it is wrong.
"""

import logging
import re
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from schemas import ChatResponse, EnvironmentalDecision

logger = logging.getLogger("ecosentinel.ai.chat")

#: How many recent analyses stay answerable. Bounded so a long-running server cannot grow forever.
MAX_TRACKED_ANALYSES = 32


class DecisionStore:
    """Recent decisions, keyed by analysis id. Thread-safe, bounded, LRU."""

    def __init__(self, capacity: int = MAX_TRACKED_ANALYSES):
        self.capacity = capacity
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, Tuple[str, EnvironmentalDecision]]" = OrderedDict()

    def remember(self, analysis_id: str, location: str, decision: EnvironmentalDecision) -> None:
        with self._lock:
            self._entries[analysis_id] = (location, decision)
            self._entries.move_to_end(analysis_id)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)

    def get(self, analysis_id: str) -> Optional[Tuple[str, EnvironmentalDecision]]:
        with self._lock:
            entry = self._entries.get(analysis_id)
            if entry is not None:
                self._entries.move_to_end(analysis_id)
            return entry

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


store = DecisionStore()


# --------------------------------------------------------------------------- deterministic answers


def _reasons_answer(decision: EnvironmentalDecision, limit: int = 5) -> Tuple[str, List[str]]:
    reasons = decision.reasons[:limit]
    if not reasons:
        return (
            "No evidence-supported reasons were identified for this location. "
            + (decision.data_gaps[0] if decision.data_gaps else ""),
            [],
        )
    # State the real count rather than implying the requested one was met.
    lines = [f"{len(reasons)} evidence-supported reason{'s' if len(reasons) != 1 else ''} identified."]
    for reason in reasons:
        sources = f" Source: {', '.join(reason.sources)}." if reason.sources else ""
        lines.append(
            f"{reason.rank}. {reason.title} — {reason.detail}{sources} "
            f"Confidence: {reason.confidence:.0%}. Evidence: {', '.join(reason.evidence_ids)}."
        )
    return "\n".join(lines), [eid for r in reasons for eid in r.evidence_ids]


def _primary_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    primary = decision.primary_problem
    if primary is None:
        gap = decision.data_gaps[0] if decision.data_gaps else ""
        return f"No primary concern was identified: the evidence is not sufficient. {gap}", []
    return (
        f"{primary.title} was selected as the primary concern. It had the highest deterministic "
        f"priority ({primary.priority:.3f}), computed as severity × confidence × evidence strength "
        f"× persistence, from {len(primary.evidence_ids)} evidence item(s) at "
        f"{primary.confidence:.0%} confidence. Causal status: {primary.causal_status.replace('_', ' ')}.",
        list(primary.evidence_ids),
    )


def _evidence_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    if not decision.evidence:
        return "No evidence was collected for this analysis.", []
    lines = [f"{len(decision.evidence)} evidence item(s) were collected:"]
    for item in decision.evidence:
        note = " (context only, not a measurement)" if item.domain == "geographic" else ""
        demo = " [demo data]" if item.is_mock else ""
        lines.append(f"- [{item.evidence_id}] {item.label}: {item.detail} — {item.source}{note}{demo}")
    return "\n".join(lines), [item.evidence_id for item in decision.evidence]


def _contradiction_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    if not decision.conflicts:
        return "No contradictory evidence was found for this analysis.", []
    lines = ["Contradictory evidence:"] + [f"- {c.detail}" for c in decision.conflicts]
    return "\n".join(lines), [eid for c in decision.conflicts for eid in c.evidence_ids]


def _direction_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    if decision.overall_direction == "insufficient_history":
        return (
            "No trend could be determined. Only the air readings have a historical baseline; the "
            "water and waste providers return a single point in time, so whether this location is "
            "improving or deteriorating cannot be established from the available evidence.",
            [],
        )
    if decision.overall_direction == "mixed":
        detail = decision.conflicts[0].detail if decision.conflicts else ""
        return f"The signals point in both directions, so the overall trend is mixed. {detail}", []
    directional = [e.evidence_id for e in decision.evidence if e.direction != "unknown"]
    return (
        f"The measured trend is {decision.overall_direction}, based on the signals that have a "
        f"historical baseline to compare against.",
        directional,
    )


def _garbage_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    detections = [e for e in decision.evidence if e.kind == "detection"]
    if not detections:
        return "No visual detections were reported for this analysis.", []
    lines = ["Visually detected material:"]
    for item in detections:
        lines.append(f"- {item.label}: {item.detail} — detected by {item.source}")
    lines.append(
        "Positions come from the detector that reported them; the dashboard overlays only the "
        "coordinates it actually returned."
    )
    return "\n".join(lines), [item.evidence_id for item in detections]


def _recovery_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    plan = decision.recovery
    if plan is None or not plan.available:
        return (plan.summary if plan else "No recovery plan is available."), []
    lines = [plan.summary, ""]
    for action in plan.actions:
        lines.append(f"{action.rank}. {action.title} ({action.timeline_range})")
    return "\n".join(lines), [eid for a in plan.actions for eid in a.evidence_ids]


def _timeline_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    plan = decision.recovery
    if plan is None:
        return "No timeline is available for this analysis.", []
    # plan.summary already opens with the "not a guaranteed prediction" caveat; don't repeat it.
    horizons = sorted({a.timeline_range for a in plan.actions})
    tail = f" Actions span {', '.join(horizons)}." if horizons else ""
    return f"{plan.summary}{tail}", []


def _gaps_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    if not decision.data_gaps:
        return "No data gaps were recorded for this analysis.", []
    lines = ["Missing information:"] + [f"- {gap}" for gap in decision.data_gaps]
    if decision.investigation_plan:
        lines.append("")
        lines.append("Recommended next steps:")
        for action in decision.investigation_plan[:5]:
            lines.append(f"- {action.title} — {action.rationale} (source: {action.provider})")
    return "\n".join(lines), []


def _trace_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    lines = ["Decision trace:"]
    for step in decision.decision_trace:
        lines.append(f"{step.step}. [{step.stage}] {step.detail}")
    return "\n".join(lines), [eid for s in decision.decision_trace for eid in s.evidence_ids]


def _industrial_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    context = [e for e in decision.evidence if e.domain == "geographic"]
    if not context:
        return "No mapped geographic features were recorded for this location.", []
    lines = [f"- {item.detail}" for item in context]
    lines.append(
        "These are contextual only. The available evidence does not establish that any mapped "
        "feature caused the observed readings; mapped features describe what is present, not what "
        "is emitting."
    )
    return "\n".join(lines), [item.evidence_id for item in context]


#: Question intent -> deterministic answer. Matched on keywords, so the chatbot works with no LLM.
def _investigation_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    """What to collect next. Distinct from `_recovery_answer`, which is what to DO about a
    confirmed problem — "what should I verify" is a question about evidence, not remediation."""
    plan = decision.investigation_plan
    if not plan:
        gaps = "; ".join(decision.data_gaps[:2])
        return (
            "No further collection is recommended: the reporting domains answered and the "
            "evidence was sufficient to decide."
            + (f" Remaining gaps: {gaps}" if gaps else ""),
            [],
        )
    lines = [
        f"{len(plan)} verification step{'s' if len(plan) != 1 else ''} recommended, "
        "most important first:"
    ]
    for index, action in enumerate(plan, start=1):
        lines.append(
            f"{index}. {action.title} — {action.rationale} "
            f"Missing: {action.missing_data}. Source: {action.provider}."
        )
    if decision.conflicts:
        lines.append(
            "This matters here because the evidence disagrees: " + decision.conflicts[0].detail
        )
    return "\n".join(lines), list(decision.supporting_evidence)


def _sources_answer(decision: EnvironmentalDecision) -> Tuple[str, List[str]]:
    """The knowledge passages that grounded this decision, cited by chunk id.

    Returns what was actually retrieved for THIS analysis, not a fresh search — "show me the
    source" is a request to see the working, and a different set of passages would not be it.
    """
    knowledge = getattr(decision, "knowledge", None)
    results = list(getattr(knowledge, "results", None) or [])
    if not results:
        message = getattr(knowledge, "message", None)
        return (
            "No knowledge passages were retrieved for this analysis."
            + (f" {message}" if message else ""),
            [],
        )
    query = getattr(knowledge, "query", "") or ""
    lines = [
        f"{len(results)} passage(s) were retrieved to ground this explanation"
        + (f', for the query "{query[:120]}"' if query else "")
        + ":"
    ]
    for item in results:
        lines.append(
            f"- [{item.chunk_id}] {item.document_title} — {item.section} "
            f"(relevance {item.score:.2f}, from {item.source_file or 'unknown file'})"
        )
    lines.append(
        "These explain what the measurements mean. They carry no severity and did not affect "
        "the risk score."
    )
    return "\n".join(lines), []


INTENTS: List[Tuple[str, Any]] = [
    (r"\b(source|sources|citation|citations|retrieved|knowledge base|passage)\b", _sources_answer),
    (r"\b(verify|verification|investigat|next step|what should i check|confirm)\b", _investigation_answer),
    (r"\b(trace|steps?|how did you decide)\b", _trace_answer),
    (r"\b(industrial|factory|factories|nearby.*(area|site))\b", _industrial_answer),
    (r"\b(garbage|trash|waste|litter|plastic).*(where|location|locate)|where.*(garbage|trash|waste|litter)\b", _garbage_answer),
    (r"\b(timeline|how long|when will|recover by)\b", _timeline_answer),
    (r"\b(recover|recovery|fix|clean ?up|remediat|what should we do|action)\b", _recovery_answer),
    (r"\b(missing|data gap|gaps?|what (information|data))\b", _gaps_answer),
    (r"\b(contradict|conflict|against|disagree)\b", _contradiction_answer),
    (r"\b(reasons?|why is|why are|deteriorat|improv|getting worse)\b", _reasons_answer),
    (r"\b(evidence|support|proof|data)\b", _evidence_answer),
    (r"\b(primary|main|biggest|choose|chose|select)\b", _primary_answer),
    (r"\b(direction|trend|improving|worsening)\b", _direction_answer),
]


def deterministic_answer(decision: EnvironmentalDecision, question: str) -> Tuple[str, List[str]]:
    """Answer from the decision state alone. Always available, never needs a provider."""
    normalised = question.lower()
    for pattern, handler in INTENTS:
        if re.search(pattern, normalised):
            return handler(decision)

    # Unrecognised question: summarise rather than guess at intent.
    primary, ids = _primary_answer(decision)
    return (
        f"{decision.explanation}\n\n{primary}\n\nAsk about the evidence, the reasons, "
        "contradictions, missing data, recovery actions, the timeline, or the decision trace.",
        ids,
    )


def answer(analysis_id: str, question: str) -> Optional[ChatResponse]:
    """Answer a question about one analysis, or None when that analysis is not held.

    Returning None rather than answering from another analysis is deliberate: a confident answer
    about the wrong river is worse than no answer.
    """
    entry = store.get(analysis_id)
    if entry is None:
        return None
    location, decision = entry

    text, evidence_ids = deterministic_answer(decision, question)

    # An explainability provider may rephrase the deterministic answer. It receives the decision
    # context and the question, and cannot alter anything it is given.
    from services.ai import explainability

    provider = explainability.resolve_provider()
    if provider is not None:
        prose = explainability.explain(decision, location, question=question)
        if prose:
            logger.info("chat_answered analysis_id=%s provider=%s", analysis_id, provider.name)
            return ChatResponse(
                analysis_id=analysis_id, question=question, answer=prose,
                evidence_ids=evidence_ids, source=provider.name, llm_enhanced=True,
            )

    logger.info("chat_answered analysis_id=%s provider=deterministic", analysis_id)
    return ChatResponse(
        analysis_id=analysis_id, question=question, answer=text,
        evidence_ids=evidence_ids, source="deterministic", llm_enhanced=False,
    )
