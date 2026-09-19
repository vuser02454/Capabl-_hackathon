"""LangGraph orchestration layer for EcoSentinel AI.

This module does NOT replace the specialist agents, the Coordinator, the data providers, or
the deterministic risk-scoring logic — it only replaces the manual sequencing that used to
live in agents/orchestrator.py with an explicit, typed LangGraph StateGraph:

    Location Input -> Location Resolution -> [Air | Water | Waste] (parallel) -> Coordinator

Every specialist node runs the SAME Agent classes used by agents/orchestrator.py
(agents/air_agent.py, water_agent.py, waste_agent.py) against the SAME providers
(services/openaq_service.py, water_sensor_service.py, waste_detection_service.py). The graph
only adds: real concurrency for the three specialist branches, per-node timeout isolation, and
graceful degradation when one or more specialists fail — it never turns a provider result into
free-form LLM text ("Provider -> Agent -> Typed Report -> Coordinator", never "Provider -> LLM").

The Coordinator only ever receives a location LABEL and the specialists' typed Pydantic
results — never raw coordinates, API keys, provider credentials, service URLs, or sensor
tokens (see CoordinatorInput in agents/coordinator_agent.py, and
test_coordinator_consumes_only_specialist_reports in backend/tests/conftest.py's suite, which
statically asserts coordinator_agent.py never imports services/http/urllib/requests/httpx).
"""

import asyncio
import logging
import operator
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from core import decision as decision_core
from core import evidence as evidence_core
from core import recovery as recovery_core

from agents.base import Agent, AgentTrace
from agents.coordinator_agent import CoordinatorAgent, CoordinatorInput
from agents.orchestrator import build_agents
from agents.registry import registry
from agents.waste_agent import WasteAgentInput
from agents.water_agent import WaterAgentInput, WaterImage
from config import settings
from core.errors import EcoSentinelError
from schemas import (
    AgentRun,
    AirAgentResult,
    AnalysisResult,
    CoordinatorResult,
    CrossSignalFinding,
    EnvironmentalDecision,
    EnvironmentalEvidence,
    EnvironmentalProblem,
    EvidenceConflict,
    GeographicContext,
    LocationContext,
    Recommendation,
    TriageDecision,
    WasteAgentResult,
    WaterAgentResult,
)
from services.location_service import location_label, resolve_geographic_context, resolve_location

logger = logging.getLogger("ecosentinel.langgraph")


class EnvironmentalState(TypedDict, total=False):
    """Graph state. Air/water/waste/coordinator are Optional because a failed or timed-out
    specialist must leave its slot empty rather than abort the graph (see `_run_node` below).
    `runs` uses an additive reducer so the three parallel specialist branches each contribute
    their own AgentRun without overwriting one another's updates.
    """

    request_id: str
    demo_mode: bool
    location_name: Optional[str]
    location_context: Optional[LocationContext]
    location: LocationContext
    geographic_context: Optional[GeographicContext]
    air: Optional[AirAgentResult]
    water: Optional[WaterAgentResult]
    waste: Optional[WasteAgentResult]
    coordinator: CoordinatorResult
    runs: Annotated[List[AgentRun], operator.add]
    # --- decision engine ---
    triage: TriageDecision
    evidence: List[EnvironmentalEvidence]
    problems: List[EnvironmentalProblem]
    cross_signal: List[CrossSignalFinding]
    conflicts: List[EvidenceConflict]
    sufficient: bool
    #: Knowledge retrieved for this analysis's evidence. Context for the explanation, never
    #: evidence: it carries no severity and cannot reach the risk score.
    knowledge: Optional[Any]
    decision: Optional[EnvironmentalDecision]
    # --- clicked-frame investigation ---
    #: The frame under investigation. When present the water specialist runs vision over it and
    #: each detection enters the SAME evidence pipeline as every other signal.
    frame_image: Optional[Any]
    frame_geotag: Optional[Any]
    investigation: Optional[Any]


async def _run_node(agent: Agent, payload: Any, providers: dict, request_id: str) -> "tuple[Optional[Any], AgentRun]":
    """Run one agent under its own timeout. Never raises — a failure becomes a structured
    AgentRun(status="failed"|"timeout") and a None result, so the graph keeps going.
    """
    trace = AgentTrace()
    started = time.perf_counter()
    status, error, result = "complete", None, None
    logger.info("agent_started agent=%s request_id=%s", agent.agent_id, request_id)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(agent.run, payload, trace), timeout=settings.agent_timeout_seconds
        )
    except asyncio.TimeoutError:
        status, error = "timeout", f"{agent.name} timed out after {settings.agent_timeout_seconds:.0f}s."
    except EcoSentinelError as exc:
        status, error = "failed", exc.message
    except Exception as exc:  # never let one agent crash the graph
        status, error = "failed", f"{agent.name} failed unexpectedly: {exc}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    if error:
        trace.log(error)
        logger.warning(
            "agent_failed agent=%s status=%s request_id=%s duration_ms=%s", agent.agent_id, status, request_id, duration_ms
        )
    else:
        logger.info("agent_completed agent=%s request_id=%s duration_ms=%s", agent.agent_id, request_id, duration_ms)

    run = AgentRun(
        agent=agent.agent_id, name=agent.name, status=status,  # type: ignore[arg-type]
        duration_ms=duration_ms, steps=trace.steps, error=error,
    )
    registry.record(agent.agent_id, status, duration_ms, providers.get(agent.agent_id, agent.name))
    return result, run


def _insufficient_data_result(label: str, note: str) -> CoordinatorResult:
    """Scenario D (see task spec): every specialist failed, or the Coordinator itself did.

    Never fabricates a measurement — overall_score/confidence are 0 and `insufficient_data`
    is set, so the frontend and API consumers can render this distinctly from a real LOW risk.
    """
    return CoordinatorResult(
        location=label,
        overall_risk_level="LOW",
        overall_score=0.0,
        confidence=0.0,
        reasoning=note,
        cross_signal_insights=[],
        contributing_factors=[],
        contributions=[],
        cross_signal_adjustment=0.0,
        dominant_agents=[],
        inputs_received=[],
        missing_inputs=["air", "water", "waste"],  # type: ignore[list-item]
        recommendations=[
            Recommendation(
                id="retry-analysis",
                priority=1,
                title="Retry the analysis",
                explanation="No specialist agent produced usable data. Retry once the air, water, "
                "and waste providers are reachable, or switch to Demo Mode.",
                agent="all",
                urgency="Immediate",
                action_label="Retry",
            )
        ],
        data_limitations=["No air, water, or waste data was available for this analysis."],
        insufficient_data=True,
        timestamp=datetime.now(timezone.utc),
    )


class LangGraphOrchestrator:
    """Builds and runs the EcoSentinel StateGraph for one demo/live mode.

    Mirrors AnalysisOrchestrator's constructor (agents/orchestrator.py) exactly — same
    `build_agents(demo_mode)` factory, same provider selection — so both orchestrators are
    interchangeable behind POST /api/analyze (see backend/main.py).
    """

    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode
        self.air, self.water, self.waste, self.coordinator = build_agents(demo_mode)
        self._graph = self._build_graph()

    @property
    def providers(self) -> dict:
        return {
            "air": self.air.provider.name,
            "water": self.water.provider.name,
            "waste": self.waste.detector.name,
            "coordinator": "Cross-signal reasoning engine"
            + (" + LLM narrative" if settings.llm_provider not in ("", "none") else ""),
        }

    # ------------------------------------------------------------ graph nodes

    async def _resolve_location_node(self, state: EnvironmentalState) -> dict:
        context = resolve_location(state.get("location_name"), state.get("location_context"))
        logger.info("location_resolved request_id=%s source=%s", state.get("request_id"), context.source)
        return {"location": context}

    async def _context_enrichment_node(self, state: EnvironmentalState) -> dict:
        """Optional OSM enrichment: what is MAPPED around the analysis point.

        Three properties make this safe to run inside the graph:
          - it never raises (resolve_geographic_context absorbs every failure into a structured
            `available=False`), so Overpass being down cannot fail an analysis;
          - it is bounded by its own timeout, so a slow provider cannot stall the analysis;
          - its output goes to the AnalysisResult only. It is NOT in CoordinatorInput, so a mapped
            factory can never move the risk score. Context describes the place; the score comes
            from measurements.

        The timeout is not belt-and-braces. The Coordinator fan-in waits on every incoming edge,
        including this one, so an unbounded enrichment node stalls the whole assessment — observed
        in practice as a >120 s hang against a busy Overpass, well past the frontend's own 30 s
        limit. Enrichment is optional; the assessment is not, so enrichment is what gets dropped.

        Demo Mode skips it entirely rather than querying a donated service for a fake location.
        """
        if self.demo_mode:
            return {
                "geographic_context": GeographicContext(
                    available=False,
                    status="skipped",
                    message="Demo Mode does not query OpenStreetMap for geographic context.",
                )
            }
        location = state["location"]
        timeout = settings.overpass_context_timeout_seconds
        try:
            context = await asyncio.wait_for(
                asyncio.to_thread(resolve_geographic_context, location.latitude, location.longitude),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # The worker thread is left to finish and be discarded — urllib offers no cancellation.
            # Its result would only have populated a descriptive panel, so losing it costs nothing.
            logger.warning(
                "context_enrichment_timeout request_id=%s after=%.0fs", state.get("request_id"), timeout
            )
            return {
                "geographic_context": GeographicContext(
                    available=False,
                    status="unavailable",
                    message="Geographic context timed out; the environmental assessment continued without it.",
                )
            }
        logger.info(
            "context_enrichment request_id=%s status=%s features=%s",
            state.get("request_id"), context.status, context.total_features,
        )
        return {"geographic_context": context}

    async def _triage_node(self, state: EnvironmentalState) -> dict:
        """Decide which investigations this location warrants.

        Deterministic availability rules only. An LLM never gets to declare a domain irrelevant:
        skipping a measurement because a model guessed nothing was there is exactly how a real
        exceedance goes unreported. Every configured domain is therefore investigated, and the
        rationale records why — triage narrows work only when a provider genuinely cannot answer.
        """
        domains: List[str] = ["air", "water", "waste"]
        skipped: List[str] = []
        rationale = [
            "All three specialist domains are investigated: a domain is skipped only when its "
            "provider is unavailable, never because a model judged it irrelevant.",
        ]
        if settings.overpass_enabled and not self.demo_mode:
            domains.append("geographic")
            rationale.append("Geographic context is available and adds mapped surroundings (context only).")
        else:
            skipped.append("geographic")
            rationale.append(
                "Geographic context skipped: "
                + ("Demo Mode does not query OpenStreetMap." if self.demo_mode else "Overpass is disabled.")
            )
        logger.info(
            "triage_completed request_id=%s domains=%s skipped=%s",
            state.get("request_id"), ",".join(domains), ",".join(skipped) or "-",
        )
        return {"triage": TriageDecision(domains=domains, skipped=skipped, rationale=rationale)}  # type: ignore[arg-type]

    async def _normalize_evidence_node(self, state: EnvironmentalState) -> dict:
        """Specialist reports -> one common evidence representation (core/evidence.py)."""
        evidence = evidence_core.normalize(
            state.get("air"), state.get("water"), state.get("waste"), state.get("geographic_context")
        )
        logger.info(
            "evidence_normalized request_id=%s count=%s elevated=%s",
            state.get("request_id"), len(evidence), len(evidence_core.elevated(evidence)),
        )
        return {"evidence": evidence}

    async def _detect_problems_node(self, state: EnvironmentalState) -> dict:
        """Evidence -> the problems it supports. Severity stays the specialists' own verdict."""
        domain_risk = {
            domain: (report.risk_level, report.risk_score, report.confidence)
            for domain, report in (
                ("air", state.get("air")), ("water", state.get("water")), ("waste", state.get("waste"))
            )
            if report is not None
        }
        problems = decision_core.detect_problems(state.get("evidence", []), domain_risk)
        logger.info(
            "problems_detected request_id=%s count=%s categories=%s",
            state.get("request_id"), len(problems), ",".join(p.category for p in problems) or "-",
        )
        return {"problems": problems}

    async def _cross_signal_node(self, state: EnvironmentalState) -> dict:
        """Co-occurring independent signals. Never a causal claim."""
        findings = decision_core.cross_signal_findings(state.get("evidence", []))
        logger.info(
            "cross_signal_analysis_completed request_id=%s findings=%s", state.get("request_id"), len(findings)
        )
        return {"cross_signal": findings}

    async def _conflicts_node(self, state: EnvironmentalState) -> dict:
        """Contradictory evidence, surfaced rather than averaged into one verdict."""
        conflicts = decision_core.evaluate_conflicts(state.get("evidence", []))
        logger.info(
            "conflict_analysis_completed request_id=%s conflicts=%s", state.get("request_id"), len(conflicts)
        )
        return {"conflicts": conflicts}

    async def _sufficiency_node(self, state: EnvironmentalState) -> dict:
        """Is there enough evidence to name a primary concern? Drives the conditional edge."""
        ranked = decision_core.prioritize(state.get("problems", []), state.get("evidence", []))
        reporting = [d for d in ("air", "water", "waste") if state.get(d) is not None]
        sufficient, _reasons = decision_core.check_sufficiency(ranked, reporting)
        logger.info(
            "data_sufficiency_checked request_id=%s sufficient=%s reporting=%s",
            state.get("request_id"), sufficient, ",".join(reporting) or "-",
        )
        return {"problems": ranked, "sufficient": sufficient}

    @staticmethod
    def _route_on_sufficiency(state: EnvironmentalState) -> str:
        """Conditional edge: a settled question goes straight to synthesis, an open one to planning."""
        return "decision_synthesis" if state.get("sufficient") else "investigation_needed"

    async def _investigation_needed_node(self, state: EnvironmentalState) -> dict:
        """Evidence is thin. The plan built during synthesis says what would resolve it."""
        logger.info("investigation_requested request_id=%s", state.get("request_id"))
        return {}

    async def _knowledge_retrieval_node(self, state: EnvironmentalState) -> dict:
        """Retrieve knowledge that explains THIS analysis's evidence.

        Runs after the evidence is settled and before synthesis, so the query is built from what
        the agents actually found. The query is constructed deterministically from evidence
        labels and statuses — not written by a language model — which is what makes the retrieval
        reproducible and therefore worth showing on screen.

        Retrieved passages are CONTEXT. They ground the explanation; they never enter the evidence
        list, carry no severity and cannot move the risk score. Retrieval failing is not an
        analysis failing: the node degrades to `unavailable` and everything downstream continues.
        """
        from schemas import KnowledgeRetrieval, RetrievedKnowledge
        from services import rag

        evidence = state.get("evidence", [])
        if not evidence:
            return {
                "knowledge": KnowledgeRetrieval(
                    status="not_run", message="No evidence was available to retrieve knowledge for."
                )
            }

        # The highest-severity domain is what the user most needs explained, so it biases
        # retrieval — without restricting it, since cross-signal knowledge is often the point.
        ranked = sorted(evidence, key=lambda item: getattr(item, "severity", 0.0), reverse=True)
        primary_domain = next(
            (item.domain for item in ranked if item.domain != "geographic"), None
        )

        try:
            query, results = await asyncio.to_thread(
                rag.retrieve_for_evidence, evidence, primary_domain
            )
            store_status = rag.status()
        except Exception as exc:  # noqa: BLE001 - enrichment must never fail an analysis
            logger.warning("knowledge_retrieval_failed request_id=%s", state.get("request_id"), exc_info=True)
            return {
                "knowledge": KnowledgeRetrieval(
                    status="unavailable",
                    message=f"Knowledge retrieval was unavailable ({type(exc).__name__}).",
                )
            }

        used_by = {"air": "Air Agent", "water": "Water Agent", "waste": "Waste Agent"}.get(
            primary_domain or "", "Decision Engine"
        )
        logger.info(
            "knowledge_retrieved request_id=%s domain=%s results=%s",
            state.get("request_id"), primary_domain, len(results),
        )
        return {
            "knowledge": KnowledgeRetrieval(
                status="ok" if store_status.get("available") else "unavailable",
                query=query,
                embedding=store_status.get("embedding", "tfidf-sparse-lexical"),
                documents_indexed=store_status.get("documents", 0),
                chunks_indexed=store_status.get("chunks", 0),
                min_score=store_status.get("min_score"),
                message=None if results else "No corpus passage cleared the relevance floor for this evidence.",
                results=[
                    RetrievedKnowledge(
                        chunk_id=result.chunk_id,
                        document_id=result.document_id,
                        document_title=result.document_title,
                        section=result.section,
                        domain=result.domain,
                        source_file=result.source,
                        content=result.text,
                        score=min(1.0, max(0.0, result.score)),
                        domain_matched=result.domain_matched,
                        used_by=used_by,
                    )
                    for result in results
                ],
            )
        }

    async def _decision_synthesis_node(self, state: EnvironmentalState) -> dict:
        """Assemble the decision. Risk comes from the Coordinator and is never recomputed here."""
        coordinator = state.get("coordinator")
        reporting = [d for d in ("air", "water", "waste") if state.get(d) is not None]
        reports = [state.get(d) for d in reporting]
        mocks = {bool(getattr(r, "is_mock", False)) for r in reports if r is not None}
        data_status = "none" if not mocks else "demo" if mocks == {True} else "live" if mocks == {False} else "mixed"

        decision = decision_core.synthesize(
            evidence=state.get("evidence", []),
            problems=state.get("problems", []),
            findings=state.get("cross_signal", []),
            conflicts=state.get("conflicts", []),
            # The deterministic Coordinator remains the risk authority.
            risk_level=coordinator.overall_risk_level if coordinator else "LOW",
            risk_score=coordinator.overall_score if coordinator else 0.0,
            confidence=coordinator.confidence if coordinator else 0.0,
            reporting_domains=reporting,
            triage=state.get("triage") or TriageDecision(),
            data_status=data_status,
        )
        # Reasons and recovery are DERIVED from the evidence, deterministically, before any
        # explainability provider is consulted. A model asked for five reasons produces five;
        # deriving them first means three reasons stays three.
        from schemas import KnowledgeRetrieval

        decision = decision.model_copy(
            update={
                "reasons": recovery_core.top_reasons(decision),
                "recovery": recovery_core.recovery_plan(decision),
                # Carried onto the decision for display and for the explanation prompt. It is
                # attached AFTER synthesis deliberately: `synthesize` never sees it, so there is
                # no path by which a retrieved passage can influence a score.
                "knowledge": state.get("knowledge") or KnowledgeRetrieval(),
            }
        )
        logger.info(
            "decision_synthesized request_id=%s primary=%s direction=%s sufficient=%s",
            state.get("request_id"),
            decision.primary_problem.problem_id if decision.primary_problem else "none",
            decision.overall_direction,
            decision.sufficient_evidence,
        )
        return {"decision": decision}

    async def _frame_investigation_node(self, state: EnvironmentalState) -> dict:
        """Present the finished decision as a WHERE / WHY / WHAT NEXT report for one frame.

        This node deliberately computes nothing the decision engine already owns. Risk, evidence,
        problems, priorities, confidence and data sufficiency all arrive from `decision`; the
        detections arrive from the water specialist's vision output. What this adds is the frame
        view of that same decision — the boxes, their position in the image, and the reasons and
        actions phrased around them.

        Skipped entirely when no frame is under investigation, so the ordinary dashboard analysis
        is unaffected.
        """
        frame = state.get("frame_image")
        if frame is None:
            return {}

        from core.investigation import build_investigation
        from schemas import WaterVisionReport

        water = state.get("water")
        vision = water.visual_pollution if water else None
        if vision is None:
            # The water specialist failed — typically because no sensor or dataset covers this
            # location — and took its vision stage down with it. Visual investigation does not
            # depend on a sensor, so the detector is run directly here rather than losing the
            # frame entirely. This runs a DETECTOR, not a second decision engine: evidence,
            # problems, priorities and sufficiency still come from `decision` below.
            from services.water_vision_service import build_report, get_water_vision_detector

            vision = await asyncio.to_thread(
                build_report, get_water_vision_detector(), frame.content, frame.filename
            )
            logger.info(
                "frame_vision_standalone request_id=%s status=%s",
                state.get("request_id"), vision.status,
            )
        investigation = build_investigation(
            vision=vision,
            water=water,
            geotag=state.get("frame_geotag"),
            decision=state.get("decision"),
        )
        logger.info(
            "frame_investigation_built request_id=%s detections=%s reasons=%s status=%s",
            state.get("request_id"), len(investigation.detections), len(investigation.reasons),
            investigation.detection_status,
        )
        return {"investigation": investigation}

    async def _explain_decision_node(self, state: EnvironmentalState) -> dict:
        """Optional LLM prose about an already-final decision.

        This is the EXPLAINABILITY role (OpenRouter or Groq), never the functional one. By the
        time it runs the decision is complete and immutable: the provider returns a string, that
        string lands in `llm_explanation`, and there is no path from a response to a number. A
        model insisting the real problem is something else changes nothing but its own paragraph.

        Any failure leaves the decision exactly as synthesized, because `explanation` is always
        present and deterministic.
        """
        decision = state.get("decision")
        if decision is None:
            return {}
        from services.ai import explainability

        provider = explainability.resolve_provider()
        if provider is None:
            return {}
        # The frame report goes with it, so WHERE / WHY / WHAT NEXT is explained against the boxes
        # the detector actually drew rather than in the abstract.
        prose = await asyncio.to_thread(
            explainability.explain,
            decision,
            location_label(state["location"]),
            None,
            state.get("investigation"),
        )
        if not prose:
            return {}
        logger.info(
            "explanation_generated request_id=%s provider=%s", state.get("request_id"), provider.name
        )
        update: dict = {
            "decision": decision.model_copy(
                update={
                    "llm_explanation": prose,
                    "llm_enhanced": True,
                    "explanation_provider": provider.name,
                }
            )
        }
        # The same prose belongs on the frame report, which is what the Water page actually shows.
        # Computing it and then dropping it before the UI is the difference between the layer
        # existing and the layer being visible.
        investigation = state.get("investigation")
        if investigation is not None:
            update["investigation"] = investigation.model_copy(
                update={"llm_reasoning": prose, "explanation_provider": provider.name}
            )
        return update

    def _specialist_node(self, agent: Agent, payload_fn: Callable[[EnvironmentalState], Any]):
        async def node(state: EnvironmentalState) -> dict:
            result, run = await _run_node(agent, payload_fn(state), self.providers, state.get("request_id", ""))
            return {agent.agent_id: result, "runs": [run]}

        return node

    async def _coordinate_node(self, state: EnvironmentalState) -> dict:
        request_id = state.get("request_id", "")
        label = location_label(state["location"])
        air, water, waste = state.get("air"), state.get("water"), state.get("waste")
        logger.info("coordinator_started request_id=%s", request_id)

        if air is None and water is None and waste is None:
            logger.warning("insufficient_data request_id=%s — every specialist agent failed", request_id)
            result = _insufficient_data_result(
                label,
                "Insufficient data: the air, water, and waste assessments are all unavailable. "
                "No environmental risk assessment could be produced from real or demo readings.",
            )
            run = AgentRun(
                agent="coordinator", name=self.coordinator.name, status="failed", duration_ms=0, steps=[],
                error="Coordinator received no specialist reports; every specialist failed or timed out.",
            )
            registry.record("coordinator", "failed", 0, self.providers["coordinator"])
        else:
            payload = CoordinatorInput(location=label, air=air, water=water, waste=waste)
            coord_result, run = await _run_node(self.coordinator, payload, self.providers, request_id)
            if coord_result is None:
                # Defensive fallback: the Coordinator itself failed/timed out despite having data.
                coord_result = _insufficient_data_result(
                    label,
                    "The Coordinator could not complete the cross-signal assessment even though "
                    "specialist data was available. " + (run.error or ""),
                )
            result = await self._maybe_enhance_with_llm(label, coord_result, air, water, waste, request_id)

        logger.info("coordinator_completed request_id=%s overall_risk=%s", request_id, result.overall_risk_level)
        return {"coordinator": result, "runs": [run]}

    @staticmethod
    async def _maybe_enhance_with_llm(
        label: str,
        coordinator: CoordinatorResult,
        air: Optional[AirAgentResult],
        water: Optional[WaterAgentResult],
        waste: Optional[WasteAgentResult],
        request_id: str,
    ) -> CoordinatorResult:
        if settings.llm_provider in ("", "none"):
            return coordinator
        try:
            from agents.llm_reasoning import generate_narrative

            narrative = await generate_narrative(label, coordinator, air, water, waste)
        except Exception:
            logger.warning("llm_narrative_error request_id=%s", request_id, exc_info=True)
            return coordinator
        if narrative is None:
            return coordinator
        logger.info("llm_narrative_applied request_id=%s", request_id)
        return coordinator.model_copy(
            update={
                "llm_narrative": narrative.summary,
                "llm_enhanced": True,
                "cross_signal_insights": [*coordinator.cross_signal_insights, *narrative.cross_signal_insights],
                "data_limitations": [*coordinator.data_limitations, *narrative.data_limitations],
            }
        )

    def _build_graph(self):
        """The decision workflow.

            START -> resolve_location -> triage_environment
                  -> { run_air | run_water | run_waste | context_enrichment }   (concurrent)
                  -> coordinate            (deterministic risk, unchanged)
                  -> normalize_evidence -> detect_problems -> cross_signal_reasoning
                  -> evaluate_conflicts -> check_data_sufficiency
                  -> [conditional] decision_synthesis | investigation_needed
                  -> explain_decision -> END

        The investigation stages run *after* the Coordinator deliberately: the decision engine
        consumes the deterministic risk score as one input rather than computing a rival one.
        """
        graph = StateGraph(EnvironmentalState)
        graph.add_node("resolve_location", self._resolve_location_node)
        graph.add_node("triage_environment", self._triage_node)
        graph.add_node("run_air", self._specialist_node(self.air, lambda s: s["location"]))
        graph.add_node(
            "run_water",
            self._specialist_node(
                self.water,
                # A frame, when one is being investigated; otherwise the plain location, exactly
                # as before. One water node serves both paths — there is no second pipeline.
                lambda s: WaterAgentInput(location=s["location"], image=s.get("frame_image"))
                if s.get("frame_image")
                else s["location"],
            ),
        )
        graph.add_node("run_waste", self._specialist_node(self.waste, lambda s: WasteAgentInput(location=s["location"])))
        graph.add_node("context_enrichment", self._context_enrichment_node)
        graph.add_node("coordinate", self._coordinate_node)
        graph.add_node("normalize_evidence", self._normalize_evidence_node)
        graph.add_node("detect_problems", self._detect_problems_node)
        graph.add_node("cross_signal_reasoning", self._cross_signal_node)
        graph.add_node("evaluate_conflicts", self._conflicts_node)
        graph.add_node("knowledge_retrieval", self._knowledge_retrieval_node)
        graph.add_node("check_data_sufficiency", self._sufficiency_node)
        graph.add_node("decision_synthesis", self._decision_synthesis_node)
        graph.add_node("investigation_needed", self._investigation_needed_node)
        graph.add_node("frame_investigation", self._frame_investigation_node)
        graph.add_node("explain_decision", self._explain_decision_node)

        graph.add_edge(START, "resolve_location")
        graph.add_edge("resolve_location", "triage_environment")

        # Fan-out: the investigators depend only on the resolved location, so LangGraph runs them
        # concurrently within the same superstep (async nodes with no edge between them).
        graph.add_edge("triage_environment", "run_air")
        graph.add_edge("triage_environment", "run_water")
        graph.add_edge("triage_environment", "run_waste")
        # Geographic enrichment joins the same wave rather than gating the specialists: none of
        # them consumes it, so making them wait on a donated third-party service buys nothing.
        graph.add_edge("triage_environment", "context_enrichment")

        # Fan-in: "coordinate" runs once all four incoming edges have completed, whether they
        # succeeded, failed, or timed out.
        graph.add_edge("run_air", "coordinate")
        graph.add_edge("run_water", "coordinate")
        graph.add_edge("run_waste", "coordinate")
        graph.add_edge("context_enrichment", "coordinate")

        # Investigation and reasoning, in order.
        graph.add_edge("coordinate", "normalize_evidence")
        graph.add_edge("normalize_evidence", "detect_problems")
        graph.add_edge("detect_problems", "cross_signal_reasoning")
        graph.add_edge("cross_signal_reasoning", "evaluate_conflicts")
        # Retrieval sits AFTER the evidence is settled and BEFORE the decision, so its query is
        # built from what the agents actually found rather than from the location alone.
        graph.add_edge("evaluate_conflicts", "knowledge_retrieval")
        graph.add_edge("knowledge_retrieval", "check_data_sufficiency")

        # The graph chooses its own next stage from the evidence it gathered.
        graph.add_conditional_edges(
            "check_data_sufficiency",
            self._route_on_sufficiency,
            {"decision_synthesis": "decision_synthesis", "investigation_needed": "investigation_needed"},
        )
        # Both routes converge: an under-evidenced analysis still produces a decision object, one
        # that says so and carries the investigation plan that would resolve it.
        graph.add_edge("investigation_needed", "decision_synthesis")
        # The frame view is built from the finished decision, then explained — so the explanation
        # layer sees the investigation too, and a no-frame run passes straight through.
        graph.add_edge("decision_synthesis", "frame_investigation")
        graph.add_edge("frame_investigation", "explain_decision")
        graph.add_edge("explain_decision", END)
        return graph.compile()

    # ------------------------------------------------------------ public API

    async def investigate_frame(
        self,
        location_name: Optional[str],
        location_context: Optional[LocationContext],
        image: WaterImage,
        geotag: Optional[Any] = None,
    ) -> AnalysisResult:
        """Run the SAME graph with a frame attached.

        There is no second decision engine and no second pipeline: the frame enters the water
        specialist, its detections become evidence, and the identical normalize -> detect ->
        cross-signal -> conflicts -> sufficiency -> synthesis path runs over them. The only extra
        stage is `frame_investigation`, which presents that finished decision as a frame report.
        """
        return await self._run(location_name, location_context, frame_image=image, frame_geotag=geotag)

    async def analyze(self, location_name: Optional[str], location_context: Optional[LocationContext]) -> AnalysisResult:
        """Run the full graph for one location. Raises EcoSentinelError only if the location
        itself cannot be resolved (same InvalidLocationError as the pre-LangGraph code path) —
        every downstream failure is absorbed into a structured AgentRun / CoordinatorResult
        instead of raising, so a specialist or Coordinator failure never surfaces as an HTTP 500.
        """
        return await self._run(location_name, location_context)

    async def _run(
        self,
        location_name: Optional[str],
        location_context: Optional[LocationContext],
        frame_image: Optional[Any] = None,
        frame_geotag: Optional[Any] = None,
    ) -> AnalysisResult:
        request_id = uuid.uuid4().hex[:12]
        started = datetime.now(timezone.utc)
        logger.info(
            "graph_execution_started request_id=%s demo_mode=%s frame=%s",
            request_id, self.demo_mode, frame_image is not None,
        )

        initial: EnvironmentalState = {
            "request_id": request_id,
            "demo_mode": self.demo_mode,
            "location_name": location_name,
            "location_context": location_context,
            "frame_image": frame_image,
            "frame_geotag": frame_geotag,
            "runs": [],
        }
        final_state: EnvironmentalState = await self._graph.ainvoke(initial)
        completed = datetime.now(timezone.utc)
        logger.info(
            "graph_execution_completed request_id=%s duration_ms=%s",
            request_id, int((completed - started).total_seconds() * 1000),
        )

        decision = final_state.get("decision")
        if decision is not None:
            # Keyed by analysis id so a later question is answered from THIS analysis, never from
            # whichever location happened to be analysed most recently.
            from services.ai.chat import store as decision_store

            decision_store.remember(request_id, location_label(final_state["location"]), decision)

        result = AnalysisResult(
            analysis_id=request_id,
            location=location_label(final_state["location"]),
            mode="demo" if self.demo_mode else "live",
            started_at=started,
            completed_at=completed,
            air=final_state.get("air"),
            water=final_state.get("water"),
            waste=final_state.get("waste"),
            coordinator=final_state["coordinator"],
            runs=final_state["runs"],
            location_context=final_state["location"],
            geographic_context=final_state.get("geographic_context"),
            decision=decision,
        )
        investigation = final_state.get("investigation")
        if investigation is not None:
            # Attached to the water report when there is one, and always to the analysis itself.
            # A frame investigation is valid on visual evidence alone: losing it because no sensor
            # covers this location would discard the very thing the user asked for.
            result = result.model_copy(update={"investigation": investigation})
            if result.water is not None:
                result = result.model_copy(
                    update={"water": result.water.model_copy(update={"investigation": investigation})}
                )
        return result
