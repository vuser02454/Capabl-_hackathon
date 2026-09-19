"""EcoSentinel agents: three independent specialists and one coordinator."""

from agents.air_agent import AirQualityAgent
from agents.coordinator_agent import CoordinatorAgent, CoordinatorInput
from agents.orchestrator import AnalysisOrchestrator
from agents.waste_agent import UploadedImage, WasteAgentInput, WasteDetectionAgent
from agents.water_agent import WaterQualityAgent

__all__ = [
    "AirQualityAgent",
    "WaterQualityAgent",
    "WasteDetectionAgent",
    "WasteAgentInput",
    "UploadedImage",
    "CoordinatorAgent",
    "CoordinatorInput",
    "AnalysisOrchestrator",
]
