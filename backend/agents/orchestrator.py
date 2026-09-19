"""Runs specialist agents independently, then hands their reports to the Coordinator.

    LocationContext -> [Air | Water | Waste] -> typed reports -> Coordinator -> Decision

Every specialist receives the same LocationContext. The Coordinator receives only
the specialist reports and a short location label — never coordinates or providers.
Each agent runs under a timeout; a failing specialist does not abort the analysis.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any, List, Optional

from agents.air_agent import AirQualityAgent
from agents.base import Agent, AgentTrace
from agents.coordinator_agent import CoordinatorAgent, CoordinatorInput
from agents.registry import registry
from agents.waste_agent import UploadedImage, WasteAgentInput, WasteDetectionAgent
from agents.water_agent import WaterQualityAgent
from config import settings
from core.errors import AnalysisFailedError, EcoSentinelError
from schemas import AgentRun, AnalysisResult, LocationContext, WasteImageAnalysis
from services.location_service import location_label
from services.openaq_service import get_air_provider
from services.waste_detection_service import get_waste_detector
from services.water_sensor_service import get_water_provider

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")


def build_agents(demo_mode: bool):
    """Construct one instance of every agent, wired to the right provider for this mode.

    Shared by AnalysisOrchestrator (below) and the LangGraph orchestrator
    (agents/langgraph_orchestrator.py) so provider selection lives in exactly one place.
    """
    air = AirQualityAgent(get_air_provider(demo_mode))
    water = WaterQualityAgent(get_water_provider(demo_mode))
    waste = WasteDetectionAgent(get_waste_detector(demo_mode))
    coordinator = CoordinatorAgent()
    return air, water, waste, coordinator


class AnalysisOrchestrator:
    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode
        self.air, self.water, self.waste, self.coordinator = build_agents(demo_mode)

    @property
    def providers(self) -> dict:
        return {
            "air": self.air.provider.name,
            "water": self.water.provider.name,
            "waste": self.waste.detector.name,
            "coordinator": "Cross-signal reasoning engine",
        }

    def analyze(self, location: LocationContext) -> AnalysisResult:
        label = location_label(location)
        started = datetime.now(timezone.utc)
        runs: List[AgentRun] = []

        air = self._run(self.air, location, runs)
        water = self._run(self.water, location, runs)
        waste = self._run(self.waste, WasteAgentInput(location=location), runs)
        coordinator = self._coordinate(label, air, water, waste, runs)

        return AnalysisResult(
            analysis_id=uuid.uuid4().hex[:12],
            location=label,
            mode="demo" if self.demo_mode else "live",
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            air=air,
            water=water,
            waste=waste,
            coordinator=coordinator,
            runs=runs,
            location_context=location,
        )

    def analyze_waste_image(
        self, location: LocationContext, image: Optional[UploadedImage], reassess: bool
    ) -> WasteImageAnalysis:
        runs: List[AgentRun] = []
        waste = self._run(self.waste, WasteAgentInput(location=location, image=image), runs)
        if waste is None:
            raise AnalysisFailedError(runs[-1].error or "Waste detection failed.")

        coordinator = None
        if reassess:
            air = self._run(self.air, location, runs)
            water = self._run(self.water, location, runs)
            coordinator = self._coordinate(location_label(location), air, water, waste, runs)
        return WasteImageAnalysis(waste=waste, coordinator=coordinator, runs=runs)

    # ------------------------------------------------------------ internals

    def _coordinate(self, location_name: str, air, water, waste, runs: List[AgentRun]):
        payload = CoordinatorInput(location=location_name, air=air, water=water, waste=waste)
        result = self._run(self.coordinator, payload, runs)
        if result is None:
            raise AnalysisFailedError(runs[-1].error or "Coordinator could not complete the assessment.")
        return result

    def _run(self, agent: Agent, payload: Any, runs: List[AgentRun]):
        trace = AgentTrace()
        started = time.perf_counter()
        status, error, result = "complete", None, None
        try:
            result = _executor.submit(agent.run, payload, trace).result(timeout=settings.agent_timeout_seconds)
        except FutureTimeout:
            status, error = "timeout", f"{agent.name} timed out after {settings.agent_timeout_seconds:.0f}s."
        except EcoSentinelError as exc:
            status, error = "failed", exc.message
        except Exception as exc:  # never let one agent crash the pipeline
            status, error = "failed", f"{agent.name} failed unexpectedly: {exc}"

        duration_ms = int((time.perf_counter() - started) * 1000)
        if error:
            trace.log(error)
        runs.append(AgentRun(agent=agent.agent_id, name=agent.name, status=status,  # type: ignore[arg-type]
                             duration_ms=duration_ms, steps=trace.steps, error=error))
        registry.record(agent.agent_id, status, duration_ms, self.providers[agent.agent_id])
        return result
