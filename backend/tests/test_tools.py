"""The tool layer: typed contracts, validation, error handling, and the boundary it enforces.

The boundary is the point of this layer. A model may choose WHICH tool to call; the tool decides
WHAT THE ANSWER IS. Several tests below exist only to hold that line — particularly that the risk
tool runs the same deterministic module the decision engine runs, rather than anything that could
be substituted by a plausible-looking guess.
"""

import base64
from pathlib import Path

import pytest

from services import tools
from services.tools.registry import ToolRegistry

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- contracts


def test_every_tool_is_fully_specified():
    registered = tools.list_tools()
    assert registered, "no tools registered"
    for tool in registered:
        assert tool.name and tool.name.islower()
        # The description is what a model routes on, so a thin one is a routing bug in waiting.
        assert len(tool.description) > 80, f"{tool.name} has a thin description"
        assert tool.input_model is not None and tool.output_model is not None
        assert callable(tool.handler)
        assert tool.category


def test_schemas_are_model_callable():
    for schema in tools.schemas():
        assert set(schema) >= {"name", "description", "parameters"}
        assert schema["parameters"]["type"] == "object"


def test_tool_names_are_unique():
    names = [tool.name for tool in tools.list_tools()]
    assert len(names) == len(set(names))


def test_duplicate_registration_is_refused():
    registry = ToolRegistry()
    existing = tools.list_tools()[0]
    registry.register(existing)
    with pytest.raises(ValueError):
        registry.register(existing)


# --------------------------------------------------------------------------- error handling


def test_unknown_tool_is_reported_not_raised():
    result = tools.invoke("no_such_tool")
    assert result.ok is False
    assert result.error_code == "UNKNOWN_TOOL"
    # The message lists what IS available, so a caller can correct itself.
    assert "analyze_waste_image" in result.error


def test_invalid_arguments_are_rejected_before_the_handler_runs():
    result = tools.invoke("calculate_environmental_risk", {"airScore": 5})
    assert result.ok is False
    assert result.error_code == "INVALID_ARGUMENTS"
    assert result.duration_ms == 0, "validation must fail before any work happens"


def test_missing_required_argument_is_rejected():
    assert tools.invoke("get_waste_segregation_guidance", {}).error_code == "INVALID_ARGUMENTS"


def test_an_unknown_location_is_a_typed_error():
    result = tools.invoke("get_air_quality_data", {"location": "Xyzzyville"})
    assert result.ok is False
    assert result.error_code == "UNKNOWN_LOCATION"


def test_a_corrupt_image_is_a_typed_error():
    result = tools.invoke("analyze_water_image", {"imageBase64": "not!!base64"})
    assert result.ok is False
    assert result.error_code in {"INVALID_ARGUMENTS", "INVALID_IMAGE"}


def test_a_failing_handler_does_not_escape():
    """A tool fault must become a result, never an exception in the caller."""
    from pydantic import BaseModel

    from services.tools.registry import Tool

    class Empty(BaseModel):
        pass

    def explode(_payload):
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(Tool(
        name="explodes", description="x" * 90, input_model=Empty,
        output_model=Empty, handler=explode,
    ))
    result = registry.invoke("explodes", {})
    assert result.ok is False
    assert result.error_code == "TOOL_FAILED"
    assert "boom" not in (result.error or ""), "internal detail must not leak to the caller"


# --------------------------------------------------------------------------- the boundary


def test_risk_tool_matches_the_deterministic_engine():
    """The whole point: the number comes from core/risk.py, not from anything approximate."""
    from core.risk import risk_level_for, round_half_up

    result = tools.invoke(
        "calculate_environmental_risk", {"airScore": 0.94, "waterScore": 0.55, "wasteScore": 0.74}
    )
    assert result.ok
    expected = round_half_up((0.94 + 0.55 + 0.74) / 3)
    assert result.output["riskScore"] == expected
    assert result.output["riskLevel"] == risk_level_for(expected)


def test_risk_tool_excludes_domains_that_did_not_report():
    """Missing data is not evidence of safety, so it must not be averaged in as zero."""
    result = tools.invoke("calculate_environmental_risk", {"airScore": 0.9})
    assert result.ok
    assert result.output["riskScore"] == 0.9
    assert list(result.output["contributing"]) == ["air"]


def test_risk_tool_requires_at_least_one_score():
    assert tools.invoke("calculate_environmental_risk", {}).ok is False


def test_risk_tool_describes_its_own_arithmetic_accurately():
    result = tools.invoke("calculate_environmental_risk", {"airScore": 0.5})
    method = result.output["method"].lower()
    # It is an unweighted mean; calling it weighted would misdescribe it in its own output.
    assert "unweighted" in method
    assert "weighted mean" not in method.replace("unweighted mean", "")


# --------------------------------------------------------------------------- semantics


def test_water_vision_tool_states_what_it_cannot_establish():
    """The disclaimer must be present on EVERY response, including when vision did not run.

    The suite runs with `YOLO26_MODEL_PATH=""` on purpose (see conftest) so it never loads torch,
    so this asserts the contract rather than a detection count. The live detector behaviour —
    that the people-and-kites frame yields zero litter — is covered by `smoke_test.py`, which
    runs against a server with real weights.
    """
    image = REPO / "water_datasets" / "TUD-GV" / "images" / "exp55_221.jpg"
    if not image.is_file():
        pytest.skip("no sample water image")
    result = tools.invoke(
        "analyze_water_image", {"imageBase64": base64.b64encode(image.read_bytes()).decode()}
    )
    assert result.ok, "an unavailable detector is still a successful tool call"

    establishes = result.output["establishes"].lower()
    assert "cannot establish" in establishes
    assert "ph" in establishes and "potability" in establishes
    assert "not evidence that water is clean" in establishes

    # Whatever the detector did or did not do, litter can never exceed the objects found.
    assert result.output["pollutionObjects"] <= result.output["totalObjects"]


def test_segregation_tool_returns_configured_policy_not_a_prediction():
    result = tools.invoke("get_waste_segregation_guidance", {"material": "paper_waste"})
    assert result.ok
    assert result.output["known"] is True
    assert result.output["category"] == "biodegradable"
    # Paper must not inherit the shared "non-degrading" recyclable note.
    assert "non-degrading" not in (result.output["environmentalNote"] or "").lower()


def test_segregation_tool_refuses_an_unknown_material():
    result = tools.invoke("get_waste_segregation_guidance", {"material": "unobtainium"})
    assert result.ok, "an unknown material is a valid answer, not a failure"
    assert result.output["known"] is False
    assert result.output["category"] is None
    assert "not one of the configured waste classes" in result.output["message"]


def test_knowledge_tool_declines_rather_than_inventing_a_source():
    result = tools.invoke(
        "search_environmental_knowledge", {"query": "what is the capital of France"}
    )
    assert result.ok
    assert result.output["results"] == []
    message = result.output["message"].lower()
    assert "does not cover this question" in message
    # And it tells the caller what NOT to do with that emptiness.
    assert "general knowledge" in message


def test_knowledge_tool_results_are_citable():
    result = tools.invoke(
        "search_environmental_knowledge", {"query": "turbidity BIS permissible limit", "topK": 2}
    )
    assert result.ok and result.output["results"]
    for item in result.output["results"]:
        assert item["chunkId"] and item["sourceFile"] and item["content"]
