"""Agent contract shared by all EcoSentinel agents."""

from abc import ABC, abstractmethod
from typing import Generic, List, TypeVar

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


class AgentTrace:
    """Human-readable execution log surfaced in the UI's Agent Activity panel."""

    def __init__(self) -> None:
        self.steps: List[str] = []

    def log(self, message: str) -> None:
        self.steps.append(message)


class Agent(ABC, Generic[TInput, TOutput]):
    agent_id: str
    name: str

    @abstractmethod
    def run(self, payload: TInput, trace: AgentTrace) -> TOutput:
        """Execute the agent on a structured input and return a structured result."""
