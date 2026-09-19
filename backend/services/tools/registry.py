"""Tool registry: typed, validated, individually callable operations.

WHAT A TOOL IS HERE
-------------------
A named Python operation with a Pydantic input model, a Pydantic output model, and a real
implementation. Every tool validates its input before running and returns a structured result or
a structured error — never a free-form string, and never a partial success that reads like a
success.

WHY THE BOUNDARY MATTERS MORE THAN THE PLUMBING
-----------------------------------------------
The rule this registry exists to enforce is that **a language model never computes a value the
system can compute itself**. The division:

    a model may decide WHICH tool to call and with WHAT arguments
    a tool decides WHAT THE ANSWER IS

So `calculate_environmental_risk` runs `core/risk.py`, the same code the deterministic engine
runs, and returns its number. A model asked to "estimate the risk" would produce a plausible
number with no provenance, and nothing downstream could tell the difference. `get_water_sensor_data`
returns what a provider reported. `search_environmental_knowledge` returns corpus passages with
their chunk ids. In each case the model's contribution is routing, and the answer's provenance is
a Python call.

Every tool is a thin wrapper over an implementation that already existed and is already tested.
That is deliberate: a tool layer that re-implements the pipeline is a second pipeline that can
disagree with the first.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("ecosentinel.tools")


class ToolError(Exception):
    """A tool could not complete. Carries a code so callers can branch without parsing prose."""

    def __init__(self, message: str, code: str = "TOOL_FAILED"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class Tool:
    """One callable operation."""

    name: str
    #: What the tool does and, just as importantly, what it does not. This text is what a model
    #: routes on, so a vague description is a routing bug waiting to happen.
    description: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    handler: Callable[[BaseModel], BaseModel]
    #: Grouping for the UI and the docs. air | water | waste | location | knowledge | decision
    category: str = "general"
    #: True when the tool only reads. A caller can offer read-only tools freely and gate the rest.
    read_only: bool = True

    def json_schema(self) -> Dict[str, Any]:
        """OpenAI/Anthropic-style function schema, so the tool is genuinely model-callable."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        }


@dataclass
class ToolResult:
    """The outcome of one invocation, successful or not.

    Failures are returned rather than raised so a caller running several tools gets a complete
    picture instead of stopping at the first problem.
    """

    tool: str
    ok: bool
    duration_ms: int
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    #: Echoed back so a result can be matched to the call that produced it.
    arguments: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """The set of tools this system exposes."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return sorted(self._tools.values(), key=lambda t: (t.category, t.name))

    def schemas(self) -> List[Dict[str, Any]]:
        return [tool.json_schema() for tool in self.all()]

    def invoke(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> ToolResult:
        """Validate, run, and return a structured result. Never raises.

        Three failure modes are distinguished, because they need different responses: an unknown
        tool (routing bug), invalid arguments (caller bug), and a failing implementation
        (genuine unavailability). Collapsing them into one error loses the distinction exactly
        when it is needed.
        """
        arguments = arguments or {}
        started = time.perf_counter()

        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool=name, ok=False, duration_ms=0, arguments=arguments,
                error=f"No tool named '{name}'. Available: {', '.join(sorted(self._tools))}.",
                error_code="UNKNOWN_TOOL",
            )

        try:
            payload = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            field_name = ".".join(str(part) for part in first.get("loc", [])) or "input"
            return ToolResult(
                tool=name, ok=False, duration_ms=0, arguments=arguments,
                error=f"Invalid argument '{field_name}': {first.get('msg', 'bad input')}",
                error_code="INVALID_ARGUMENTS",
            )

        try:
            output = tool.handler(payload)
        except ToolError as exc:
            duration = int((time.perf_counter() - started) * 1000)
            logger.info("tool_failed name=%s code=%s", name, exc.code)
            return ToolResult(
                tool=name, ok=False, duration_ms=duration, arguments=arguments,
                error=exc.message, error_code=exc.code,
            )
        except Exception as exc:  # noqa: BLE001 - a tool fault must not take down its caller
            duration = int((time.perf_counter() - started) * 1000)
            logger.warning("tool_error name=%s", name, exc_info=True)
            return ToolResult(
                tool=name, ok=False, duration_ms=duration, arguments=arguments,
                error=f"{name} failed unexpectedly ({type(exc).__name__}).",
                error_code="TOOL_FAILED",
            )

        duration = int((time.perf_counter() - started) * 1000)
        logger.info("tool_invoked name=%s duration_ms=%s", name, duration)
        return ToolResult(
            tool=name, ok=True, duration_ms=duration, arguments=arguments,
            output=output.model_dump(by_alias=True, mode="json"),
        )


registry = ToolRegistry()
