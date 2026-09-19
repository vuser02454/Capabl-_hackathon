"""Deterministic answers to the questions users actually ask.

"Why is this deteriorating?", "what should we do?", "how long will it take?" — these look like
questions for a language model, and that is exactly the trap. A model asked for five reasons will
produce five, whether or not five exist; asked for a timeline it will produce a number. So the
substance is derived here, from evidence the system actually holds, and the explainability layer
only puts it into words.

Three rules, each pinned by tests:

1. **Never pad.** `top_reasons` returns as many evidence-supported reasons as exist, up to five.
   Three reasons means three, and the caller says so.
2. **Every reason cites evidence.** Each carries the evidence ids behind it, so the chain from
   claim to measurement to source stays walkable.
3. **Timelines are categories, not predictions.** "Immediate (0-7 days)" is a planning horizon.
   "The river will recover in 27 days" is a fabrication, and nothing here can produce one.
"""

from typing import List, Sequence

from schemas import (
    DeteriorationReason,
    EnvironmentalDecision,
    EnvironmentalEvidence,
    RecoveryAction,
    RecoveryPlan,
)

MAX_REASONS = 5

#: Planning horizons. Deliberately coarse — the evidence supports a category, never a date.
TIMELINE_BANDS = {
    "immediate": "0-7 days",
    "short_term": "1-4 weeks",
    "medium_term": "1-3 months",
    "long_term": "3-12+ months",
}

#: Problem category -> the actions that follow from it, most direct first. Each is a response to
#: the detected problem rather than generic environmental advice.
CATEGORY_ACTIONS = {
    "waste": [
        ("Remove accumulated waste from the affected area", "immediate"),
        ("Identify the waste entry points feeding the accumulation", "short_term"),
        ("Re-survey the area across multiple time windows to confirm whether it returns", "short_term"),
    ],
    "water": [
        ("Re-sample water quality upstream and downstream of the analysis point", "immediate"),
        ("Check the reporting sensors and fill the missing parameters", "short_term"),
        ("Establish repeat measurements to distinguish a spike from a trend", "medium_term"),
    ],
    "air": [
        ("Confirm the reading against a second nearby monitoring station", "immediate"),
        ("Identify local emission activity during the hours the readings peaked", "short_term"),
        ("Track the pollutant against its baseline over several days", "medium_term"),
    ],
}


def top_reasons(decision: EnvironmentalDecision, limit: int = MAX_REASONS) -> List[DeteriorationReason]:
    """The strongest evidence-supported reasons, ranked, never padded to a target count.

    Ordering follows the same deterministic priority the decision engine used, so the reasons a
    user reads are the reasons the system actually acted on — not a re-ranking invented for prose.
    """
    by_id = {item.evidence_id: item for item in decision.evidence}
    reasons: List[DeteriorationReason] = []

    problems = [p for p in (decision.primary_problem, *decision.secondary_problems) if p is not None]
    for problem in problems:
        supporting = [by_id[eid] for eid in problem.evidence_ids if eid in by_id]
        # Context carries no severity, so it can corroborate a reason but never be one.
        supporting = [item for item in supporting if item.domain != "geographic"]
        if not supporting:
            continue
        lead = max(supporting, key=lambda item: item.severity)
        reasons.append(
            DeteriorationReason(
                rank=len(reasons) + 1,
                title=problem.title,
                detail=lead.detail,
                evidence_ids=[item.evidence_id for item in supporting],
                sources=sorted({item.source for item in supporting if item.source}),
                confidence=problem.confidence,
                domain=problem.category if problem.category != "cross_signal" else "unknown",  # type: ignore[arg-type]
            )
        )
        if len(reasons) >= limit:
            return reasons

    # Individually elevated signals that no problem claimed — still real, still evidence-backed.
    claimed = {eid for reason in reasons for eid in reason.evidence_ids}
    spare = sorted(
        (
            item
            for item in decision.evidence
            if item.evidence_id not in claimed and item.severity > 0 and item.domain != "geographic"
        ),
        key=lambda item: item.severity,
        reverse=True,
    )
    for item in spare:
        if len(reasons) >= limit:
            break
        reasons.append(
            DeteriorationReason(
                rank=len(reasons) + 1,
                title=item.label,
                detail=item.detail,
                evidence_ids=[item.evidence_id],
                sources=[item.source] if item.source else [],
                confidence=item.confidence,
                domain=item.domain,  # type: ignore[arg-type]
            )
        )
    return reasons


def recovery_timeline(decision: EnvironmentalDecision) -> str:
    """A planning horizon for the first meaningful action, as a category.

    Driven by severity and evidence quality, not by a model's intuition about rivers.
    """
    if decision.primary_problem is None:
        return "short_term"
    severity = decision.primary_problem.severity
    if severity == "HIGH":
        return "immediate"
    if severity == "MODERATE":
        return "short_term"
    return "medium_term"


def recovery_plan(decision: EnvironmentalDecision) -> RecoveryPlan:
    """Actions that follow from the detected problem, plus the horizons they sit in.

    Actions come from the problem categories actually detected. With no problem detected there is
    nothing to recover from, and the plan says so rather than offering generic advice.
    """
    problems = [p for p in (decision.primary_problem, *decision.secondary_problems) if p is not None]
    if not problems:
        return RecoveryPlan(
            available=False,
            timeline_category="short_term",
            timeline_range=TIMELINE_BANDS["short_term"],
            summary=(
                "No evidence-supported problem was detected, so there is no recovery action to "
                "recommend. The investigation plan lists what would confirm that."
            ),
        )

    actions: List[RecoveryAction] = []
    seen: set = set()
    for problem in problems:
        for title, horizon in CATEGORY_ACTIONS.get(problem.category, []):
            if title in seen:
                continue
            seen.add(title)
            actions.append(
                RecoveryAction(
                    rank=len(actions) + 1,
                    title=title,
                    addresses_problem=problem.problem_id,
                    evidence_ids=list(problem.evidence_ids),
                    timeline_category=horizon,
                    timeline_range=TIMELINE_BANDS[horizon],
                )
            )

    # Monitoring is always warranted where no baseline exists, because a single snapshot cannot
    # show whether an action worked.
    if decision.overall_direction == "insufficient_history":
        actions.append(
            RecoveryAction(
                rank=len(actions) + 1,
                title="Monitor the area across multiple time windows to establish a baseline",
                addresses_problem=problems[0].problem_id,
                evidence_ids=[],
                timeline_category="medium_term",
                timeline_range=TIMELINE_BANDS["medium_term"],
            )
        )

    category = recovery_timeline(decision)
    return RecoveryPlan(
        available=True,
        actions=actions[:MAX_REASONS],
        timeline_category=category,
        timeline_range=TIMELINE_BANDS[category],
        summary=(
            f"Estimated planning timeline, not a guaranteed recovery prediction. The first actions "
            f"for {problems[0].title.lower()} sit in the {TIMELINE_BANDS[category]} horizon; sustained "
            "improvement requires repeat measurement over a longer period."
        ),
    )


def visible_waste_locations(evidence: Sequence[EnvironmentalEvidence]) -> List[str]:
    """Evidence ids for anything visually detected, for a "where is the garbage?" answer.

    Only returns what a detector actually reported. Bounding boxes come from the detector
    (YOLO, or the functional AI when it supplies them) and are never invented here.
    """
    return [item.evidence_id for item in evidence if item.kind == "detection"]
