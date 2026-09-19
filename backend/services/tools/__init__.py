"""Typed, validated tools over EcoSentinel's existing capabilities.

    registry.py        the Tool/ToolResult contract, validation and error handling
    environmental.py   the nine tools, each wrapping an already-tested implementation

THE RULE THIS LAYER ENFORCES
----------------------------
A language model may decide WHICH tool to call and WITH WHAT ARGUMENTS.
A tool decides WHAT THE ANSWER IS.

So a risk figure comes from `calculate_environmental_risk`, which runs `core/risk.py`; a sensor
reading comes from `get_water_sensor_data`, which runs a provider; a citation comes from
`search_environmental_knowledge`, which runs the retriever. A model that produced any of these
itself would produce something plausible with no provenance, and nothing downstream could tell
the difference.

Importing this package registers every tool.
"""

from services.tools import environmental  # noqa: F401 - import registers the tools
from services.tools.registry import Tool, ToolError, ToolResult, registry  # noqa: F401


def list_tools():
    return registry.all()


def schemas():
    """Model-callable function schemas for every registered tool."""
    return registry.schemas()


def invoke(name: str, arguments=None) -> ToolResult:
    return registry.invoke(name, arguments)
