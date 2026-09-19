"""Coordinator Agent.

Input:      AirAgentResult, WaterAgentResult, WasteAgentResult (any may be missing)
Processing: cross-signal reasoning -> risk aggregation -> priority identification
Output:     CoordinatorResult (overall risk, reasons, recommended actions)

The coordinator never touches raw provider data — only specialist reports.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from agents.base import Agent, AgentTrace
from core.errors import AnalysisFailedError
from core.risk import clamp, format_number, join_and, risk_level_for, round_half_up
from schemas import (
    AirAgentResult,
    ContributingFactor,
    CoordinatorResult,
    Recommendation,
    SignalContribution,
    WasteAgentResult,
    WaterAgentResult,
)

SpecialistResult = Union[AirAgentResult, WaterAgentResult, WasteAgentResult]

WEIGHTS: Dict[str, float] = {"air": 0.38, "water": 0.27, "waste": 0.35}
CORRELATION_BOOST = 0.03  # per additional HIGH specialist signal
MISSING_CONFIDENCE_PENALTY = 0.1
MAX_FACTORS = 3

AGENT_NAMES = {"air": "air", "water": "water", "waste": "waste"}
HIGH_PHRASE = {"air": "air pollution", "water": "water-quality degradation", "waste": "litter density"}
MODERATE_PHRASE = {
    "air": "air quality shows moderate deterioration",
    "water": "water-quality indicators show moderate degradation",
    "waste": "litter levels are moderately elevated",
}
LOW_PHRASE = {
    "air": "air quality remains within acceptable limits",
    "water": "water-quality indicators remain within acceptable limits",
    "waste": "litter levels remain low",
}


@dataclass(frozen=True)
class CoordinatorInput:
    location: str
    air: Optional[AirAgentResult] = None
    water: Optional[WaterAgentResult] = None
    waste: Optional[WasteAgentResult] = None


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


class CoordinatorAgent(Agent[CoordinatorInput, CoordinatorResult]):
    agent_id = "coordinator"
    name = "Coordinator Agent"

    def run(self, payload: CoordinatorInput, trace: AgentTrace) -> CoordinatorResult:
        reports: List[Tuple[str, SpecialistResult]] = [
            (agent_id, report)
            for agent_id, report in (("air", payload.air), ("water", payload.water), ("waste", payload.waste))
            if report is not None
        ]
        if not reports:
            raise AnalysisFailedError("Coordinator received no specialist reports to assess.")
        missing = [a for a in ("air", "water", "waste") if a not in {r[0] for r in reports}]
        trace.log(f"Received reports from {len(reports)} specialist agent{'s' if len(reports) != 1 else ''}")

        # --- risk aggregation
        weight_total = sum(WEIGHTS[a] for a, _ in reports)
        contributions = [
            SignalContribution(
                agent=agent_id,  # type: ignore[arg-type]
                risk_level=report.risk_level,
                risk_score=report.risk_score,
                weight=round_half_up(WEIGHTS[agent_id] / weight_total, 3),
                contribution=round_half_up(WEIGHTS[agent_id] / weight_total * report.risk_score, 3),
            )
            for agent_id, report in reports
        ]
        contributions.sort(key=lambda c: c.contribution, reverse=True)
        base_score = sum(WEIGHTS[a] / weight_total * r.risk_score for a, r in reports)

        trace.log("Performing cross-signal reasoning...")
        levels = {agent_id: report.risk_level for agent_id, report in reports}
        highs = [a for a in ("air", "water", "waste") if levels.get(a) == "HIGH"]
        moderates = [a for a in ("air", "water", "waste") if levels.get(a) == "MODERATE"]
        lows = [a for a in ("air", "water", "waste") if levels.get(a) == "LOW"]

        adjustment = CORRELATION_BOOST * (len(highs) - 1) if len(highs) >= 2 else 0.0
        overall = round_half_up(clamp(base_score + adjustment))
        overall_level = risk_level_for(overall)

        insights = self._insights(payload, highs, adjustment, missing)
        confidence = sum(WEIGHTS[a] / weight_total * r.confidence for a, r in reports)
        confidence = round_half_up(clamp(confidence - MISSING_CONFIDENCE_PENALTY * len(missing)))
        trace.log(f"Risk aggregation · {overall * 100:.0f}% overall ({overall_level})")

        factors: List[ContributingFactor] = []
        report_map = dict(reports)
        for c in contributions:
            report = report_map[c.agent]
            if report.findings and report.risk_level != "LOW":
                top = report.findings[0]
                factors.append(ContributingFactor(agent=c.agent, label=top.label, detail=top.detail))
        factors = factors[:MAX_FACTORS]

        recommendations = self._recommendations(payload, overall, overall_level)
        trace.log(f"Identified {len(recommendations)} prioritized actions")
        limitations = self._data_limitations(payload, missing)
        trace.log("Final environmental risk generated")

        dominant = highs or ([contributions[0].agent] if moderates else [])
        return CoordinatorResult(
            location=payload.location,
            overall_risk_level=overall_level,
            overall_score=overall,
            confidence=confidence,
            reasoning=self._reasoning(overall_level, highs, moderates, lows, missing),
            cross_signal_insights=insights,
            contributing_factors=factors,
            contributions=contributions,
            cross_signal_adjustment=round_half_up(adjustment, 3),
            dominant_agents=dominant,  # type: ignore[arg-type]
            inputs_received=[a for a, _ in reports],  # type: ignore[misc]
            missing_inputs=missing,  # type: ignore[arg-type]
            recommendations=recommendations,
            data_limitations=limitations,
            timestamp=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------ reasoning

    @staticmethod
    def _reasoning(level: str, highs: List[str], moderates: List[str], lows: List[str], missing: List[str]) -> str:
        elevated = len(highs) + len(moderates)
        if level == "HIGH":
            opening = (
                "Multiple environmental indicators show elevated risk."
                if elevated >= 2
                else "A single dominant indicator is driving elevated environmental risk."
            )
        elif level == "MODERATE":
            opening = "Environmental indicators show moderate overall risk."
        else:
            opening = "Environmental indicators are largely within acceptable ranges."

        if highs:
            verb = "are the dominant risk factors" if len(highs) > 1 else "is the dominant risk factor"
            tail = [MODERATE_PHRASE[a] for a in moderates] or [LOW_PHRASE[a] for a in lows]
            body = f"{_capitalise(join_and(HIGH_PHRASE[a] for a in highs))} {verb}"
            body += f", while {join_and(tail)}." if tail else "."
        elif moderates:
            verb = "are the main concerns" if len(moderates) > 1 else "is the main concern"
            tail = [LOW_PHRASE[a] for a in lows]
            body = f"{_capitalise(join_and(HIGH_PHRASE[a] for a in moderates))} {verb}"
            body += f", while {join_and(tail)}." if tail else "."
        else:
            body = "No specialist agent reported indicators above guideline thresholds."

        text = f"{opening} {body}"
        if missing:
            text += f" The {join_and(missing)} assessment is unavailable, so confidence is reduced."
        return text

    @staticmethod
    def _insights(payload: CoordinatorInput, highs: List[str], adjustment: float, missing: List[str]) -> List[str]:
        insights: List[str] = []
        if adjustment > 0:
            insights.append(
                f"Correlated high-risk signals from the {join_and(highs)} agents add "
                f"{adjustment * 100:.0f} points to the aggregate score."
            )
        air, water, waste = payload.air, payload.water, payload.waste
        if waste and water and waste.risk_level != "LOW" and water.turbidity is not None and water.turbidity > 5:
            insights.append(
                "Litter density alongside elevated turbidity suggests surface runoff may be "
                "carrying waste into the nearby water body."
            )
        if air and waste and air.risk_level == "HIGH" and waste.counts.plastic >= 8:
            insights.append(
                "High PM2.5 near a plastic-heavy litter zone warrants a check for open waste burning."
            )
        if water and water.sensor_status == "degraded":
            insights.append("Water assessment relies on partial sensor data; one or more probes are not reporting.")
        if missing:
            insights.append(
                f"No report received from the {join_and(missing)} agent; its weight was redistributed."
            )
        return insights

    @staticmethod
    def _data_limitations(payload: CoordinatorInput, missing: List[str]) -> List[str]:
        """Freshness/mock/missing-agent caveats, derived only from the typed specialist reports.

        Deterministic and side-effect free (no I/O, no new imports) — every claim here traces
        back to a field the specialist agent already reported, never an inference or invention.
        """
        limitations: List[str] = []
        air, water, waste = payload.air, payload.water, payload.waste

        if air is not None:
            if air.is_mock:
                limitations.append("Air-quality data is simulated demo data, not a live reading.")
            elif air.data_age_minutes is not None and air.data_age_minutes > 15:
                limitations.append(f"Air-quality readings are {air.data_age_minutes} minutes old.")

        if water is not None:
            if water.is_mock:
                limitations.append("Water-quality data is simulated demo data, not a live reading.")
            elif water.data_age_minutes is not None and water.data_age_minutes > 15:
                limitations.append(f"Water readings are {water.data_age_minutes} minutes old.")
            if water.sensor_status == "degraded":
                limitations.append(f"{water.sensor_name} is reporting partial data; some parameters are missing.")

        if waste is not None:
            if waste.input_type == "upload":
                limitations.append(
                    "Waste analysis is image-based and reflects a single uploaded photo, not continuous monitoring."
                )
            elif waste.is_mock:
                limitations.append("Waste detection is simulated demo data, not a live camera feed.")

        for agent_id in missing:
            limitations.append(f"No {agent_id} assessment is available; treat the overall risk with reduced confidence.")
        return limitations

    @staticmethod
    def _recommendations(payload: CoordinatorInput, overall: float, overall_level: str) -> List[Recommendation]:
        candidates: List[Tuple[float, dict]] = []
        air, water, waste = payload.air, payload.water, payload.waste

        if waste and waste.risk_level != "LOW":
            candidates.append((waste.risk_score * 1.0, dict(
                id="inspect-waste", title="Inspect waste accumulation zone", agent="waste",
                explanation=(f"{waste.total_objects} objects detected at {waste.source_name}, "
                             f"{waste.counts.plastic} of them plastic. Dispatch a sanitation crew and trace the source."),
                action_label="Dispatch crew")))

        if water and water.sensor_status == "degraded":
            candidates.append((max(water.risk_score, 0.5) * 0.95, dict(
                id="restore-sensor", title="Restore water sensor telemetry", agent="water",
                explanation=f"{water.sensor_name} is reporting partial data. Inspect probes and connectivity on {water.sensor_id}.",
                action_label="Open ticket")))
        elif water and water.risk_level != "LOW":
            turbidity = (f"Turbidity at {format_number(water.turbidity)} NTU exceeds the 5 NTU permissible limit"
                         if water.turbidity is not None and water.turbidity > 5
                         else "Water indicators are drifting from safe ranges")
            candidates.append((water.risk_score * 0.95, dict(
                id="investigate-water", title="Investigate nearby water source", agent="water",
                explanation=f"{turbidity} at {water.sensor_name}. Collect a grab sample for lab validation.",
                action_label="Schedule sampling")))

        if overall_level != "LOW":
            candidates.append((overall * 0.7, dict(
                id="increase-monitoring", title="Increase environmental monitoring frequency", agent="all",
                explanation="Raise sampling cadence from 60 to 15 minutes across all agents for the next 24 hours to confirm the trend.",
                action_label="Update cadence")))

        if air and air.risk_level == "HIGH":
            pm = (f"PM2.5 at {format_number(air.pm25)} µg/m³ is {air.pm25 / 15:.1f}× the WHO guideline"
                  if air.pm25 is not None else "Air pollution is at a high-risk level")
            candidates.append((air.risk_score * 0.65, dict(
                id="air-advisory", title="Issue air-quality health advisory", agent="air",
                explanation=f"{pm}. Notify sensitive groups near {air.station_name} and review traffic controls.",
                action_label="Draft advisory")))
        elif air and air.risk_level == "MODERATE":
            candidates.append((air.risk_score * 0.6, dict(
                id="air-watch", title="Monitor air-quality trend", agent="air",
                explanation=f"Air quality at {air.station_name} is moderate. Watch for sustained increases over the next 12 hours.",
                action_label="Set alert")))

        if not candidates:
            candidates.append((0.1, dict(
                id="routine", title="Maintain routine monitoring", agent="all",
                explanation="All indicators are within acceptable limits. Continue the standard sampling schedule.",
                action_label="Acknowledge")))

        candidates.sort(key=lambda item: item[0], reverse=True)
        recommendations = []
        for index, (urgency_score, data) in enumerate(candidates):
            urgency = "Immediate" if index == 0 and urgency_score >= 0.6 else "Within 24h" if urgency_score >= 0.45 else "Routine"
            recommendations.append(Recommendation(priority=index + 1, urgency=urgency, **data))
        return recommendations
