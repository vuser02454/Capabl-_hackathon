"""Five deterministic demo scenarios, run against the real agents and the real decision engine.

    python backend/scripts/demo_scenarios.py            # run all, print the reasoning
    python backend/scripts/demo_scenarios.py --scenario C
    python backend/scripts/demo_scenarios.py --quiet    # assertions only, for CI

WHY IN-PROCESS RATHER THAN OVER HTTP
------------------------------------
Scenarios B and C need specific sensor values — normal chemistry under visible litter, abnormal
chemistry under a clean-looking surface. Over HTTP those readings would have to come from a live
sensor or the token-gated ingest endpoint, neither of which is reproducible on a conference wifi
five minutes before a demo. So the providers are stubbed and everything downstream is the real
thing: the real `WaterQualityAgent`, the real thresholds, the real evidence normaliser, the real
conflict detection, the real deterministic risk engine.

WHAT IS SIMULATED
-----------------
Only the two inputs: the sensor reading and the detector output. Both are marked `is_mock=True`
and every scenario prints a DEMO / SIMULATED banner. No scenario fabricates a risk score, a
conflict or an explanation — those are computed. If a fix breaks the reasoning, these fail.

Each scenario asserts the thing it exists to demonstrate, so this doubles as a smoke test.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.base import AgentTrace  # noqa: E402
from agents.water_agent import WaterAgentInput, WaterImage, WaterQualityAgent  # noqa: E402
from core import decision as decision_core  # noqa: E402
from core import evidence as evidence_core  # noqa: E402
from schemas import VisionDetection, VisionDetectionBox  # noqa: E402
from services.location_service import resolve_location  # noqa: E402
from services.water_sensor_service import WaterSensorReading  # noqa: E402
from services.water_vision_service import VisionOutput  # noqa: E402

BANNER = "DEMO / SIMULATED INPUT — sensor reading and detector output are fixtures, not measurements."

# --------------------------------------------------------------------------- stubs


class StubSensor:
    """A fixed water reading. Always `is_mock=True`; nothing here may look like a measurement."""

    name = "Demo sensor fixture"
    network = "demo water sensors (fixture)"

    def __init__(self, ph, turbidity, temperature, label="Demo fixture sensor"):
        self.values = (ph, turbidity, temperature)
        self.label = label

    def get_latest(self, location):
        ph, turbidity, temperature = self.values
        return WaterSensorReading(
            sensor_id="DEMO-FIXTURE-01",
            sensor_name=self.label,
            status="online",
            ph=ph,
            turbidity=turbidity,
            temperature=temperature,
            observed_at=datetime.now(timezone.utc),
            provider="Demo scenario fixture",
            is_mock=True,
            source_type="demo",
            notes=("Simulated reading from a demo fixture — not a field measurement.",),
        )


class StubVision:
    """A fixed detector output. Class names are the raw ones a real detector would emit."""

    name = "Demo detector fixture"

    def __init__(self, classes):
        self.classes = classes
        self.model = "demo-detector-fixture"

    def is_configured(self):
        return True

    def detect(self, content, filename):
        detections = [
            VisionDetection(
                class_name=name,
                confidence=confidence,
                bbox=VisionDetectionBox(x1=10 * i, y1=10 * i, x2=10 * i + 40, y2=10 * i + 40),
            )
            for i, (name, confidence) in enumerate(self.classes, start=1)
        ]
        # semantic_category is deliberately NOT set here: the fixture reports raw classes exactly
        # as a detector does, and the system must do its own interpretation.
        return VisionOutput(
            model=self.model, detections=detections, image_width=640, image_height=480
        )


def run_water(sensor, vision, with_image=True):
    """The real Water Agent over stubbed inputs, plus the real evidence/decision pipeline."""
    location = resolve_location("Bengaluru", None)
    agent = WaterQualityAgent(sensor, vision=vision)
    trace = AgentTrace()
    payload = WaterAgentInput(
        location=location,
        image=WaterImage(content=b"demo-fixture-bytes", filename="demo.jpg") if with_image else None,
    )
    report = agent.run(payload, trace)

    evidence = evidence_core.normalize(None, report, None, None)
    # Severity stays the specialist's own deterministic verdict, exactly as the graph passes it
    # (see LangGraphOrchestrator._detect_problems_node) rather than a second opinion invented here.
    domain_risk = {"water": (report.risk_level, report.risk_score, report.confidence)}
    problems = decision_core.detect_problems(evidence, domain_risk)
    findings = decision_core.cross_signal_findings(evidence)
    conflicts = decision_core.evaluate_conflicts(evidence)
    return report, trace, evidence, problems, findings, conflicts


# --------------------------------------------------------------------------- reporting


def show(report, trace, evidence, conflicts, quiet):
    if quiet:
        return
    vision = report.visual_pollution
    print(f"  water risk        : {report.risk_score}  ({report.risk_level})")
    if report.water_quality_score is not None:
        print(f"  measured-only     : {report.water_quality_score}  (visual escalation applied)")
    if vision and vision.status == "ok":
        print(
            f"  detector          : {vision.total_objects} object(s), "
            f"{vision.pollution_objects} litter, {vision.non_pollution_objects} non-pollution"
        )
        for d in vision.detections:
            print(f"      - {d.class_name:<16} {d.confidence:.0%}   -> {d.semantic_category}")
    print("  OBSERVED          :")
    for item in evidence:
        if item.status in {"elevated", "critical"}:
            print(f"      - {item.label}: {item.detail}")
    print("  NOT ESTABLISHED   :")
    print("      - Chemical contamination (no chemistry was measured beyond the listed parameters)")
    if vision and vision.status == "ok" and vision.pollution_objects:
        print("      - That visible litter indicates any chemical change in the water")
    if conflicts:
        print("  CONFLICTS         :")
        for c in conflicts:
            print(f"      - {c.detail}")
    print("  NEEDS VERIFICATION:")
    for line in report.warnings[:3]:
        print(f"      - {line}")


# --------------------------------------------------------------------------- scenarios


def scenario_a(quiet):
    """A — VISIBLE WATER POLLUTION: litter in frame, chemistry also elevated."""
    report, trace, evidence, _problems, _findings, conflicts = run_water(
        StubSensor(ph=6.2, turbidity=14.0, temperature=29.0),
        StubVision([("plastic_bottle", 0.91), ("garbage", 0.87), ("plastic_bag", 0.78)]),
    )
    show(report, trace, evidence, conflicts, quiet)

    v = report.visual_pollution
    assert v.pollution_objects == 3, v.pollution_objects
    assert report.water_quality_score is not None, "visible litter must escalate the risk"
    assert report.risk_score > report.water_quality_score
    assert any(e.evidence_id.startswith("IMG-DET") for e in evidence), "each box must be evidence"
    return "visible litter raised the risk above the measured-only score"


def scenario_b(quiet):
    """B — SENSOR-BASED CONCERN: nothing visible, chemistry abnormal.

    The system must NOT say the water is clean. Absence of visible litter is not evidence of
    safety, and the measured exceedance stands on its own.
    """
    report, trace, evidence, _problems, _findings, conflicts = run_water(
        StubSensor(ph=5.1, turbidity=18.0, temperature=31.0),
        StubVision([]),  # detector ran and found nothing
    )
    show(report, trace, evidence, conflicts, quiet)

    assert report.visual_pollution.pollution_objects == 0
    assert report.risk_level in {"MODERATE", "HIGH"}, report.risk_level
    assert any(f.code.startswith("water.") for f in report.findings), "chemistry must still drive findings"
    # Nothing anywhere may call this water clean or safe.
    text = " ".join([report.risk_level, *(f.label for f in report.findings), *report.warnings]).lower()
    for phrase in ("water is clean", "safe to drink", "no pollution", "potable"):
        assert phrase not in text, f"must not claim {phrase!r}"
    return "sensor exceedance drove the risk with no visual evidence; no clean-water claim made"


def scenario_c(quiet):
    """C — CONFLICTING EVIDENCE: litter visible, chemistry within limits.

    The demo's central point. Visible pollution is reported, chemical contamination is NOT
    asserted, and the disagreement is surfaced rather than averaged away.
    """
    report, trace, evidence, _problems, _findings, conflicts = run_water(
        StubSensor(ph=7.1, turbidity=2.0, temperature=22.0),  # all within guidelines
        StubVision([("plastic_bottle", 0.88), ("garbage", 0.81)]),
    )
    show(report, trace, evidence, conflicts, quiet)

    assert report.visual_pollution.pollution_objects == 2
    # Measurements are normal, so no chemistry finding may exist.
    chemistry = [f for f in report.findings if f.code != "water.visual_pollution"]
    assert not chemistry, f"chemistry is within limits; no chemical finding expected: {chemistry}"
    # The conflict between normal measurements and elevated detections must be surfaced.
    assert any("measurement_vs_detection" in c.conflict_id for c in conflicts), (
        f"the measurement/detection disagreement must be reported: {conflicts}"
    )
    return "visible litter reported, chemical contamination NOT established, conflict surfaced"


def scenario_d(quiet):
    """D — WASTE CLASSIFICATION: detection -> classification -> gate -> segregation -> XAI."""
    from services.waste.waste_pipeline import analyze_waste

    image_path = BACKEND_DIR.parent / "runs" / "debug_waste" / "original" / "metal_can.jpg"
    if not image_path.is_file():
        print("  SKIPPED — no sample waste image at runs/debug_waste/original/metal_can.jpg")
        return "skipped (no sample image)"

    result = analyze_waste(image_path.read_bytes(), image_path.name, explain=True)
    if not quiet:
        print(f"  detector          : {result['model']}  ({result['status']})")
        for d in result["detections"]:
            label = d.get("classification") or f"CANDIDATE {d.get('candidate')}"
            print(
                f"      - {label:<18} det {d['detection_confidence']:.0%} "
                f"cls {d.get('classification_confidence') or 0:.0%} "
                f"-> {d['status']} / {d['segregation']}"
            )
            if d.get("environmental_note"):
                print(f"        note: {d['environmental_note']}")
            xai = d.get("xai") or {}
            print(
                f"        XAI : {xai.get('method')} available={xai.get('available')} "
                f"grid={xai.get('attribution_grid')} target={xai.get('target_class')}"
            )
        print(f"  summary           : {result['summary']}")

    assert result["status"] == "ok", result.get("message")
    assert result["detections"], "the sample image must produce at least one detection"
    for d in result["detections"]:
        # The gate: a confirmed label requires a confident model.
        if d["status"] == "confirmed":
            assert d["segregation"] in {"biodegradable", "non_biodegradable"}
        else:
            assert d["segregation"] == "uncertain"
        xai = d.get("xai") or {}
        # Either a real attribution, or an honest absence — never a substitute image.
        if not xai.get("available"):
            assert not xai.get("overlay_image"), "an unavailable XAI must carry no image"
    return "detection -> classification -> confidence gate -> segregation -> Grad-CAM"


def scenario_e(quiet):
    """E — MULTI-AGENT EVENT: air + water + waste through the full LangGraph pipeline."""
    import asyncio

    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Delhi", None))
    decision = result.decision
    if not quiet:
        print(f"  agents            : {[(r.agent, r.status) for r in result.runs]}")
        print(f"  overall risk      : {decision.risk_score} ({decision.risk_level})")
        print(f"  primary problem   : {decision.primary_problem.title if decision.primary_problem else None}")
        print(f"  evidence items    : {len(decision.evidence)}")
        print(f"  cross-signal      : {len(decision.cross_signal_findings)}")
        print(f"  conflicts         : {len(decision.conflicts)}")
        print(f"  explanation       : {decision.explanation[:160]}")
        print(f"  explained by      : {decision.explanation_provider or 'deterministic template'}")

    assert result.air and result.water and result.waste, "all three specialists must report"
    assert decision.evidence, "evidence must be normalised"
    assert decision.risk_score is not None
    assert decision.explanation, "an explanation must exist even with no LLM configured"
    assert decision.decision_trace, "the decision must be traceable"
    return "three agents -> evidence -> LangGraph reasoning -> deterministic risk -> explanation"


SCENARIOS = {
    "A": ("VISIBLE WATER POLLUTION", scenario_a),
    "B": ("SENSOR-BASED WATER CONCERN", scenario_b),
    "C": ("CONFLICTING EVIDENCE", scenario_c),
    "D": ("WASTE CLASSIFICATION", scenario_d),
    "E": ("MULTI-AGENT ENVIRONMENTAL EVENT", scenario_e),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="EcoSentinel demo scenarios")
    parser.add_argument("--scenario", help="run one scenario by letter (A-E)")
    parser.add_argument("--quiet", action="store_true", help="assertions only")
    args = parser.parse_args()

    selected = [args.scenario.upper()] if args.scenario else list(SCENARIOS)
    failures = []

    print("=" * 78)
    print("ECOSENTINEL AI — DEMO SCENARIOS")
    print(BANNER)
    print("=" * 78)

    for key in selected:
        if key not in SCENARIOS:
            print(f"Unknown scenario {key!r}. Choose from {', '.join(SCENARIOS)}.")
            return 2
        title, run = SCENARIOS[key]
        print(f"\nSCENARIO {key} — {title}")
        print("-" * 78)
        try:
            outcome = run(args.quiet)
            print(f"  PASS: {outcome}")
        except AssertionError as exc:
            failures.append((key, str(exc)))
            print(f"  FAIL: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append((key, f"{type(exc).__name__}: {exc}"))
            print(f"  ERROR: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 78)
    if failures:
        print(f"{len(failures)} scenario(s) FAILED: {', '.join(k for k, _ in failures)}")
        return 1
    print(f"All {len(selected)} scenario(s) passed.")
    print(BANNER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
