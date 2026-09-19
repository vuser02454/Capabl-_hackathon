"""Deterministic environmental decision logic.

This module is the reasoning the LangGraph decision engine runs. Every function here is pure and
deterministic: the same evidence always yields the same problems, the same priorities, and the
same decision. No LLM is involved at any point — `agents/llm_reasoning.py` may later add prose
*about* this output, but it can never change it.

The pipeline, in order:

    evidence -> detect_problems -> cross_signal_findings -> conflicts
             -> direction -> prioritize -> sufficiency -> investigation plan -> synthesis

Three rules hold throughout, and the tests pin all three:

1. **A problem needs evidence.** Nothing is ever emitted without at least one supporting
   evidence id, so every claim can be traced back to a measurement and its source.
2. **Co-occurrence is not causation.** Cross-signal findings say signals occur together and
   warrant investigation. They never say one caused another, and `causality` is fixed at
   `"not_established"` so no caller can set it otherwise.
3. **Risk is not recomputed.** The deterministic Coordinator remains the risk authority
   (`agents/coordinator_agent.py`, `core/risk.py`). This module reads its score and never
   derives a competing one — "how bad" and "what is it" are different questions.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from core.evidence import ELEVATED_SEVERITY, elevated, missing
from core.risk import clamp, risk_level_for, round_half_up
from schemas import (
    CrossSignalFinding,
    DecisionTraceStep,
    EnvironmentalDecision,
    EnvironmentalEvidence,
    EnvironmentalProblem,
    EvidenceConflict,
    InvestigationAction,
    TriageDecision,
)

DOMAIN_TITLES = {
    "air": "Air-quality concern",
    "water": "Water-quality concern",
    "waste": "Waste accumulation concern",
}
DOMAIN_PROVIDERS = {
    "air": "Air Quality Agent (OpenAQ)",
    "water": "Water Quality Agent (sensor / dataset)",
    "waste": "Waste Detection Agent (YOLO / demo)",
}

#: Below this confidence a detected problem does not settle the question on its own.
MIN_DECISION_CONFIDENCE = 0.5
#: Fewer reporting domains than this and nothing can be cross-checked.
MIN_REPORTING_DOMAINS = 2


# --------------------------------------------------------------------------- problem detection


def detect_problems(
    evidence: Sequence[EnvironmentalEvidence],
    domain_risk: Dict[str, Tuple[str, float, float]],
) -> List[EnvironmentalProblem]:
    """Evidence -> the problems it supports.

    `domain_risk` maps a domain to its specialist's own (risk_level, risk_score, confidence), so
    severity stays the specialist's deterministic verdict rather than a second opinion invented
    here.

    A domain yields a problem only when it has at least one piece of elevated evidence. A
    specialist reporting everything within guidelines is not a problem, and inventing one would
    make "no problems found" impossible to express.
    """
    problems: List[EnvironmentalProblem] = []

    for domain in ("air", "water", "waste"):
        supporting = elevated(evidence, domain)
        if not supporting or domain not in domain_risk:
            continue
        level, score, confidence = domain_risk[domain]
        problems.append(
            EnvironmentalProblem(
                problem_id=f"problem.{domain}",
                category=domain,  # type: ignore[arg-type]
                title=DOMAIN_TITLES[domain],
                description=_describe(domain, supporting),
                severity=level,  # type: ignore[arg-type]
                severity_score=score,
                confidence=confidence,
                evidence_ids=[item.evidence_id for item in supporting],
                # A threshold exceedance is the problem itself, directly observed.
                causal_status="observed",
            )
        )

    # A cross-domain problem is only meaningful when two independent domains are both elevated.
    elevated_domains = [p.category for p in problems]
    if len(elevated_domains) >= 2:
        supporting_ids = [eid for p in problems for eid in p.evidence_ids]
        severity_score = round_half_up(max(p.severity_score for p in problems))
        problems.append(
            EnvironmentalProblem(
                problem_id="problem.cross_signal",
                category="cross_signal",
                title="Multiple interacting environmental risks",
                description=(
                    f"Independent {' and '.join(elevated_domains)} signals are both elevated at this "
                    "location. They may share a driver, but the available evidence does not establish "
                    "that any one of them caused another."
                ),
                severity=risk_level_for(severity_score),  # type: ignore[arg-type]
                severity_score=severity_score,
                confidence=round_half_up(min(p.confidence for p in problems)),
                evidence_ids=supporting_ids,
                # Several signals agree; the shared cause remains a hypothesis.
                causal_status="supported_hypothesis",
            )
        )
    return problems


def _describe(domain: str, supporting: Sequence[EnvironmentalEvidence]) -> str:
    leads = ", ".join(item.label for item in supporting[:3])
    return f"Elevated {domain} indicators: {leads}."


# --------------------------------------------------------------------------- cross-signal


def cross_signal_findings(evidence: Sequence[EnvironmentalEvidence]) -> List[CrossSignalFinding]:
    """Independent signals that co-occur. Never a causal claim.

    The wording is deliberate and is asserted by the tests: "occur within the same geographic
    context", "warrants investigation", never "caused by".
    """
    findings: List[CrossSignalFinding] = []
    elevated_items = [item for item in evidence if item.severity >= ELEVATED_SEVERITY]
    domains = sorted({item.domain for item in elevated_items})

    if len(domains) >= 2:
        findings.append(
            CrossSignalFinding(
                finding_id="cross.co_occurrence",
                title="Multiple environmental signals co-occur",
                detail=(
                    f"Elevated {' and '.join(domains)} signals were observed at the same location. "
                    "This warrants further investigation; the available evidence is not sufficient "
                    "to establish that they share a cause."
                ),
                domains=domains,  # type: ignore[arg-type]
                evidence_ids=[item.evidence_id for item in elevated_items],
            )
        )

    # Mapped geography alongside a real measurement. Context is named, never blamed.
    context_items = [item for item in evidence if item.domain == "geographic"]
    if context_items and elevated_items:
        for context_item in context_items:
            if context_item.evidence_id not in ("geographic.industrial", "geographic.waste_facility"):
                continue
            findings.append(
                CrossSignalFinding(
                    finding_id=f"cross.{context_item.evidence_id}",
                    title=f"{context_item.label} mapped near elevated readings",
                    detail=(
                        f"{context_item.detail} Elevated "
                        f"{' and '.join(sorted({i.domain for i in elevated_items}))} readings were also "
                        "recorded here. Mapped features describe what is present, not what is emitting: "
                        "the available evidence does not establish that this feature caused the readings."
                    ),
                    domains=sorted({context_item.domain, *(i.domain for i in elevated_items)}),  # type: ignore[arg-type]
                    evidence_ids=[context_item.evidence_id, *(i.evidence_id for i in elevated_items)],
                )
            )
    return findings


# --------------------------------------------------------------------------- conflicts


def evaluate_conflicts(evidence: Sequence[EnvironmentalEvidence]) -> List[EvidenceConflict]:
    """Evidence pointing opposite ways, surfaced rather than averaged into a single verdict.

    Forcing a mixed picture into one direction is how a dashboard ends up saying "improving"
    while half its indicators worsen.
    """
    conflicts: List[EvidenceConflict] = []
    improving = [item for item in evidence if item.direction == "improving"]
    deteriorating = [item for item in evidence if item.direction == "deteriorating"]
    if improving and deteriorating:
        conflicts.append(
            EvidenceConflict(
                conflict_id="conflict.direction",
                detail=(
                    f"Mixed environmental signals: {', '.join(i.label for i in improving)} "
                    f"improving while {', '.join(d.label for d in deteriorating)} worsening."
                ),
                evidence_ids=[i.evidence_id for i in (*improving, *deteriorating)],
            )
        )

    # A domain whose measurements are within guidelines while its detections are elevated.
    for domain in ("air", "water", "waste"):
        items = [item for item in evidence if item.domain == domain]
        normal_measurements = [i for i in items if i.kind == "measurement" and i.status == "normal"]
        elevated_detections = [i for i in items if i.kind == "detection" and i.severity >= ELEVATED_SEVERITY]
        if normal_measurements and elevated_detections:
            conflicts.append(
                EvidenceConflict(
                    conflict_id=f"conflict.{domain}.measurement_vs_detection",
                    detail=(
                        f"{domain.capitalize()} measurements are within guideline limits while visual "
                        "detections are elevated. Measurements and observations disagree; neither "
                        "alone settles the question."
                    ),
                    evidence_ids=[i.evidence_id for i in (*normal_measurements, *elevated_detections)],
                )
            )
    return conflicts


# --------------------------------------------------------------------------- direction


def overall_direction(evidence: Sequence[EnvironmentalEvidence]) -> str:
    """Recovery vs deterioration, from measured baselines only.

    Returns `"insufficient_history"` whenever no evidence carries a measured direction — which is
    the common case today, because only the air agent has a historical baseline (a 24-hour PM2.5
    comparison). Reporting "stable" there would assert a trend nobody measured.
    """
    directions = {item.direction for item in evidence if item.direction != "unknown"}
    if not directions:
        return "insufficient_history"
    if "improving" in directions and "deteriorating" in directions:
        return "mixed"
    if "deteriorating" in directions:
        return "deteriorating"
    if "improving" in directions:
        return "improving"
    return "stable"


# --------------------------------------------------------------------------- prioritization


def evidence_strength(supporting_count: int) -> float:
    """Independent corroboration, normalised to 0..1.

    One signal is suggestive; several independent ones are much harder to explain away.
    1 -> 0.50, 2 -> 0.75, 3+ -> 1.00.
    """
    if supporting_count <= 0:
        return 0.0
    return min(1.0, 0.5 + 0.25 * (supporting_count - 1))


def persistence_factor(problem: EnvironmentalProblem, evidence: Sequence[EnvironmentalEvidence]) -> float:
    """Whether the problem is corroborated over time.

    1.0 when at least one supporting item carries a measured direction (i.e. a real baseline
    comparison exists); 0.75 otherwise. The discount is deliberate: a single snapshot genuinely
    is weaker evidence than a confirmed trend, and today only air readings can earn the full
    factor. It is a discount for unknown persistence, never a penalty invented per-domain.
    """
    by_id = {item.evidence_id: item for item in evidence}
    for evidence_id in problem.evidence_ids:
        item = by_id.get(evidence_id)
        if item is not None and item.direction != "unknown":
            return 1.0
    return 0.75


def problem_priority(problem: EnvironmentalProblem, evidence: Sequence[EnvironmentalEvidence]) -> float:
    """Deterministic ranking score.

        priority = severity_score x confidence x evidence_strength x persistence

    Each term is 0..1, so priority is 0..1 and the product punishes weakness anywhere: a severe
    problem nobody is confident about, or a confident one resting on a single snapshot, both rank
    below a moderate problem confirmed from several angles. No LLM contributes to this number.
    """
    return round_half_up(
        clamp(
            problem.severity_score
            * problem.confidence
            * evidence_strength(len(problem.evidence_ids))
            * persistence_factor(problem, evidence)
        ),
        3,
    )


def prioritize(
    problems: Sequence[EnvironmentalProblem], evidence: Sequence[EnvironmentalEvidence]
) -> List[EnvironmentalProblem]:
    """Problems ranked by `problem_priority`, highest first. Ties break on severity then category."""
    scored = [problem.model_copy(update={"priority": problem_priority(problem, evidence)}) for problem in problems]
    scored.sort(key=lambda p: (-p.priority, -p.severity_score, p.category))
    return scored


# --------------------------------------------------------------------------- sufficiency


def check_sufficiency(
    problems: Sequence[EnvironmentalProblem], reporting_domains: Sequence[str]
) -> Tuple[bool, List[str]]:
    """Is there enough evidence to settle the question? Returns (sufficient, reasons).

    Deterministic rules, in order:
      - no domain reported            -> insufficient
      - fewer than two domains        -> insufficient (nothing can be cross-checked)
      - a problem below MIN_DECISION_CONFIDENCE and nothing stronger -> insufficient
    """
    reasons: List[str] = []
    measuring = [d for d in reporting_domains if d in ("air", "water", "waste")]

    if not measuring:
        reasons.append("No specialist agent produced usable evidence.")
        return False, reasons
    if len(measuring) < MIN_REPORTING_DOMAINS:
        reasons.append(
            f"Only the {measuring[0]} domain reported; at least {MIN_REPORTING_DOMAINS} are needed "
            "to cross-check a finding."
        )
        return False, reasons
    if problems:
        best = max(p.confidence for p in problems)
        if best < MIN_DECISION_CONFIDENCE:
            reasons.append(
                f"Highest problem confidence is {best:.2f}, below the {MIN_DECISION_CONFIDENCE:.2f} "
                "threshold needed to identify a primary concern."
            )
            return False, reasons
    return True, reasons


# --------------------------------------------------------------------------- investigation plan


def plan_investigation(
    problems: Sequence[EnvironmentalProblem],
    evidence: Sequence[EnvironmentalEvidence],
    reporting_domains: Sequence[str],
    direction: str,
) -> List[InvestigationAction]:
    """What to collect next: what is missing, why it matters, and who can supply it."""
    actions: List[InvestigationAction] = []

    for domain in ("air", "water", "waste"):
        if domain in reporting_domains:
            continue
        actions.append(
            InvestigationAction(
                action_id=f"investigate.{domain}",
                title=f"Obtain {domain} evidence for this location",
                missing_data=f"No {domain} report was produced for this analysis.",
                rationale=(
                    f"With no {domain} evidence the assessment cannot be cross-checked, so any "
                    "finding rests on fewer independent signals than it should."
                ),
                provider=DOMAIN_PROVIDERS[domain],
                priority=1,
            )
        )

    for item in missing(evidence):
        actions.append(
            InvestigationAction(
                action_id=f"investigate.{item.evidence_id}",
                title=f"Collect {item.label}",
                missing_data=item.detail,
                rationale=(
                    f"{item.label} is part of the {item.domain} assessment but was not reported, so "
                    "that domain's score rests on the remaining parameters alone."
                ),
                provider=DOMAIN_PROVIDERS.get(item.domain, item.source or "provider"),
                priority=2,
            )
        )

    # Persistence is the gap that recurs, because only air has a historical baseline today.
    if problems and direction == "insufficient_history":
        actions.append(
            InvestigationAction(
                action_id="investigate.persistence",
                title="Capture repeat observations across multiple time windows",
                missing_data="No historical baseline exists for the water or waste signals.",
                rationale=(
                    "A single snapshot cannot distinguish a persistent problem from a transient "
                    "spike. Repeat observations would establish whether this is improving or "
                    "deteriorating, and would raise the persistence factor in problem priority."
                ),
                provider="Water Quality Agent / Waste Detection Agent",
                priority=2,
            )
        )

    for problem in problems:
        if problem.causal_status == "supported_hypothesis":
            actions.append(
                InvestigationAction(
                    action_id=f"investigate.{problem.problem_id}.causality",
                    title=f"Test whether the {problem.category.replace('_', '-')} signals share a driver",
                    missing_data="No evidence linking the co-occurring signals to a common source.",
                    rationale=(
                        "Signals co-occurring is not evidence that one caused another. Targeted "
                        "sampling would show whether a shared driver exists or the co-occurrence "
                        "is incidental."
                    ),
                    provider="Field sampling / multi-agent re-analysis",
                    priority=3,
                )
            )

    actions.sort(key=lambda a: a.priority)
    return actions


# --------------------------------------------------------------------------- synthesis


def build_trace(
    evidence: Sequence[EnvironmentalEvidence],
    problems: Sequence[EnvironmentalProblem],
    findings: Sequence[CrossSignalFinding],
    conflicts: Sequence[EvidenceConflict],
    primary: Optional[EnvironmentalProblem],
    risk_level: str,
    risk_score: float,
) -> List[DecisionTraceStep]:
    """The explainability chain: decision -> problem -> evidence -> measurement -> source.

    Written as an ordered narrative so a "why did you decide that?" question can be answered by
    replaying recorded steps rather than by re-deriving (or re-imagining) the reasoning.
    """
    steps: List[DecisionTraceStep] = []
    step = 1

    for domain in ("air", "water", "waste"):
        items = [i for i in evidence if i.domain == domain and i.severity >= ELEVATED_SEVERITY]
        if not items:
            continue
        steps.append(
            DecisionTraceStep(
                step=step,
                stage="evidence",
                detail=f"{domain.capitalize()} agent reported {len(items)} elevated signal(s): "
                + "; ".join(f"{i.label} ({i.detail})" for i in items[:3]),
                evidence_ids=[i.evidence_id for i in items],
            )
        )
        step += 1

    for problem in problems:
        steps.append(
            DecisionTraceStep(
                step=step,
                stage="problem",
                detail=(
                    f"{problem.title} detected from {len(problem.evidence_ids)} evidence item(s); "
                    f"severity {problem.severity} ({problem.severity_score:.2f}), confidence "
                    f"{problem.confidence:.2f}, priority {problem.priority:.3f}."
                ),
                evidence_ids=problem.evidence_ids,
            )
        )
        step += 1

    for finding in findings:
        steps.append(
            DecisionTraceStep(step=step, stage="cross_signal", detail=finding.detail, evidence_ids=finding.evidence_ids)
        )
        step += 1

    for conflict in conflicts:
        steps.append(
            DecisionTraceStep(step=step, stage="conflict", detail=conflict.detail, evidence_ids=conflict.evidence_ids)
        )
        step += 1

    steps.append(
        DecisionTraceStep(
            step=step,
            stage="risk",
            detail=(
                f"Deterministic Coordinator scored overall risk {risk_level} ({risk_score:.2f}). "
                "Risk level and problem classification are separate: risk is how much concern, the "
                "problem is what the evidence points to."
            ),
        )
    )
    step += 1

    if primary is not None:
        steps.append(
            DecisionTraceStep(
                step=step,
                stage="decision",
                detail=(
                    f"{primary.title} selected as the primary concern: it had the highest priority "
                    f"({primary.priority:.3f}) under severity x confidence x evidence strength x "
                    "persistence."
                ),
                evidence_ids=primary.evidence_ids,
            )
        )
    else:
        steps.append(
            DecisionTraceStep(
                step=step,
                stage="decision",
                detail="No primary concern was identified: the available evidence does not support one.",
            )
        )
    return steps


def _explanation(
    primary: Optional[EnvironmentalProblem],
    secondary: Sequence[EnvironmentalProblem],
    direction: str,
    conflicts: Sequence[EvidenceConflict],
    sufficient: bool,
    gaps: Sequence[str],
) -> str:
    """Deterministic prose. Always present, whether or not an LLM is configured."""
    if not sufficient or primary is None:
        text = (
            "There is not enough evidence to identify a primary environmental concern at this "
            "location."
        )
        if gaps:
            text += f" {gaps[0]}"
        return text

    text = (
        f"{primary.title} is the primary concern, supported by {len(primary.evidence_ids)} evidence "
        f"item(s) at {primary.confidence:.0%} confidence."
    )
    if secondary:
        text += f" Secondary concerns: {', '.join(p.title.lower() for p in secondary)}."
    if direction == "insufficient_history":
        text += " No historical baseline is available, so whether this is improving or deteriorating cannot be determined."
    elif direction == "mixed":
        text += " Signals point in both directions, so the overall trend is mixed."
    else:
        text += f" The measured trend is {direction}."
    if conflicts:
        text += f" {conflicts[0].detail}"
    if primary.causal_status != "observed":
        text += " No cause has been established."
    return text


def synthesize(
    evidence: Sequence[EnvironmentalEvidence],
    problems: Sequence[EnvironmentalProblem],
    findings: Sequence[CrossSignalFinding],
    conflicts: Sequence[EvidenceConflict],
    risk_level: str,
    risk_score: float,
    confidence: float,
    reporting_domains: Sequence[str],
    triage: TriageDecision,
    data_status: str,
    extra_gaps: Sequence[str] = (),
) -> EnvironmentalDecision:
    """Assemble the final decision from already-computed parts.

    `risk_level`/`risk_score`/`confidence` come straight from the deterministic Coordinator; this
    function never recomputes them.
    """
    ranked = prioritize(problems, evidence)
    direction = overall_direction(evidence)
    sufficient, reasons = check_sufficiency(ranked, reporting_domains)

    # The primary concern must be actionable, so it is always a domain problem. A cross-signal
    # problem is a statement *about* the others ("these co-occur") — naming it as the headline
    # would tell an operator that several things are wrong without saying where to start. It stays
    # in `problems` and in the trace, and its substance is reported as a cross-signal finding.
    domain_problems = [p for p in ranked if p.category != "cross_signal"]
    primary = domain_problems[0] if (domain_problems and sufficient) else None
    secondary = [p for p in domain_problems[1:]] if primary else []

    gaps = [*reasons, *extra_gaps]
    gaps.extend(
        f"No {domain} evidence was available for this analysis."
        for domain in ("air", "water", "waste")
        if domain not in reporting_domains
    )
    if direction == "insufficient_history" and ranked:
        gaps.append("No historical baseline exists for the water or waste signals, so no trend can be established.")

    plan = plan_investigation(ranked, evidence, reporting_domains, direction)
    trace = build_trace(evidence, ranked, findings, conflicts, primary, risk_level, risk_score)

    supporting = list(primary.evidence_ids) if primary else []
    contradictory = [eid for conflict in conflicts for eid in conflict.evidence_ids]

    return EnvironmentalDecision(
        primary_problem=primary,
        secondary_problems=secondary,
        overall_direction=direction,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        risk_score=risk_score,
        confidence=confidence,
        sufficient_evidence=sufficient,
        evidence=list(evidence),
        cross_signal_findings=list(findings),
        conflicts=list(conflicts),
        supporting_evidence=supporting,
        contradictory_evidence=contradictory,
        data_gaps=gaps,
        investigation_plan=plan,
        decision_trace=trace,
        triage=triage,
        explanation=_explanation(primary, secondary, direction, conflicts, sufficient, gaps),
        data_status=data_status,  # type: ignore[arg-type]
    )
