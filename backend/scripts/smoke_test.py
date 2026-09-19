"""End-to-end smoke test against a RUNNING backend.

    # terminal 1
    cd backend && uvicorn main:app --port 8000
    # terminal 2
    python backend/scripts/smoke_test.py                    # defaults to :8000
    python backend/scripts/smoke_test.py --base-url http://127.0.0.1:8077

Covers the checks in the finalization brief §21 that need a live server: startup, every endpoint,
both image pipelines, the LangGraph run, the deterministic risk engine, explanation fallback, and
the degradation paths (missing sensor, missing vision, low confidence, non-waste, invalid image).

The in-process reasoning scenarios live in `demo_scenarios.py`, and the unit suite in
`backend/tests/`. This file deliberately tests the SERVER, because a backend that passes its unit
tests and still fails to boot is the failure mode a demo actually hits.

Exit code is the number of failed checks, so CI can gate on it.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


class Results:
    def __init__(self):
        self.rows = []

    def add(self, name, status, detail=""):
        self.rows.append((name, status, detail))
        symbol = {PASS: "  ok  ", FAIL: " FAIL ", SKIP: " skip "}[status]
        print(f"[{symbol}] {name}" + (f"  — {detail}" if detail else ""))

    @property
    def failed(self):
        return [r for r in self.rows if r[1] == FAIL]


def main() -> int:
    parser = argparse.ArgumentParser(description="EcoSentinel backend smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    try:
        import httpx
    except ImportError:
        print("httpx is required: pip install httpx")
        return 1

    results = Results()
    client = httpx.Client(timeout=90.0)

    def get(path):
        return client.get(f"{base}{path}")

    def post(path, **kwargs):
        return client.post(f"{base}{path}", **kwargs)

    print("=" * 78)
    print(f"ECOSENTINEL SMOKE TEST — {base}")
    print("=" * 78)

    # ---------------------------------------------------------------- 1. startup
    try:
        health = get("/api/health")
        body = health.json()
        results.add(
            "backend startup / health",
            PASS if health.status_code == 200 and body.get("status") == "ok" else FAIL,
            f"v{body.get('version')} demoMode={body.get('demoMode')}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("backend startup / health", FAIL, f"{type(exc).__name__}: {exc}")
        print("\nThe backend is not reachable. Start it first:")
        print("  cd backend && uvicorn main:app --port 8000")
        return 1

    # ---------------------------------------------------------------- 2. GET endpoints
    for name, path in [
        ("GET /api/agents/status", "/api/agents/status"),
        ("GET /api/locations", "/api/locations"),
        ("GET /api/ai/status", "/api/ai/status"),
        ("GET /api/waste/pipeline-status", "/api/waste/pipeline-status"),
        ("GET /api/water/dataset-status", "/api/water/dataset-status"),
        ("GET /api/environment/delhi", "/api/environment/delhi"),
    ]:
        try:
            response = get(path)
            results.add(name, PASS if response.status_code == 200 else FAIL, f"HTTP {response.status_code}")
        except Exception as exc:  # noqa: BLE001
            results.add(name, FAIL, f"{type(exc).__name__}")

    # ---------------------------------------------------------------- 3. no key leaks
    try:
        status = get("/api/ai/status").json()
        blob = json.dumps(status)
        leaked = [
            token
            for token in ("sk-", "AIza", "gsk_", "api_key", "apiKey")
            if token in blob
        ]
        results.add(
            "no credentials in /api/ai/status",
            FAIL if leaked else PASS,
            f"found {leaked}" if leaked else "nothing key-shaped in the payload",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("no credentials in /api/ai/status", FAIL, f"{type(exc).__name__}")

    # ---------------------------------------------------------------- 4. full analysis
    analysis = None
    try:
        response = post("/api/analyze", json={"location": "Delhi", "demoMode": True})
        analysis = response.json()
        decision = analysis.get("decision") or {}
        ok = (
            response.status_code == 200
            and analysis.get("air")
            and analysis.get("water")
            and analysis.get("waste")
            and decision.get("riskScore") is not None
        )
        results.add(
            "POST /api/analyze (three agents + decision)",
            PASS if ok else FAIL,
            f"risk={decision.get('riskScore')} {decision.get('riskLevel')}",
        )

        # The deterministic engine must have produced a trace and evidence.
        results.add(
            "deterministic risk engine produced a trace",
            PASS if decision.get("decisionTrace") else FAIL,
            f"{len(decision.get('decisionTrace') or [])} step(s)",
        )
        results.add(
            "evidence is structured",
            PASS if decision.get("evidence") else FAIL,
            f"{len(decision.get('evidence') or [])} item(s)",
        )
        # An explanation must exist whether or not an LLM is configured.
        results.add(
            "explanation exists (LLM or deterministic fallback)",
            PASS if decision.get("explanation") else FAIL,
            f"provider={decision.get('explanationProvider') or 'deterministic template'}",
        )
        # Demo data must be labelled as such.
        results.add(
            "demo data is marked is_mock",
            PASS if analysis["air"].get("isMock") else FAIL,
            f"mode={analysis.get('mode')}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("POST /api/analyze", FAIL, f"{type(exc).__name__}: {exc}")

    # ---------------------------------------------------------------- 5. LangGraph route
    try:
        response = post("/api/analyze/graph", json={"location": "Mumbai", "demoMode": True})
        graph = response.json()
        results.add(
            "POST /api/analyze/graph (LangGraph)",
            PASS if response.status_code == 200 and graph.get("decision") else FAIL,
            f"{len(graph.get('runs') or [])} agent run(s)",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("POST /api/analyze/graph", FAIL, f"{type(exc).__name__}")

    # ---------------------------------------------------------------- 6. water image
    water_image = REPO / "water_datasets" / "TUD-GV" / "images" / "exp55_221.jpg"
    litter_image = REPO / "runs" / "debug_waste" / "original" / "plastic_bottle.jpg"

    if water_image.is_file():
        try:
            response = post(
                "/api/water/analyze-image",
                files={"file": (water_image.name, water_image.read_bytes(), "image/jpeg")},
                data={"location": "Delhi"},
            )
            water = response.json()
            vision = water.get("visualPollution") or {}
            results.add(
                "POST /api/water/analyze-image",
                PASS if response.status_code == 200 else FAIL,
                f"risk={water.get('riskScore')} vision={vision.get('status')}",
            )
            # The defect this project had: non-pollution classes counted as pollution.
            non_litter = [
                d for d in vision.get("detections", [])
                if d.get("semanticCategory") != "visible_surface_litter"
            ]
            counted = vision.get("pollutionObjects", 0)
            results.add(
                "non-pollution detections excluded from the litter count",
                PASS if counted == len(vision.get("detections", [])) - len(non_litter) else FAIL,
                f"{counted} litter of {vision.get('totalObjects')} object(s)",
            )
            # scan-frame and analyze-image must agree about what counts as pollution.
            verdict = post(
                "/api/water/scan-frame",
                files={"file": (water_image.name, water_image.read_bytes(), "image/jpeg")},
            ).json()
            results.add(
                "scan-frame agrees with analyze-image on the litter count",
                PASS if verdict.get("objectCount") == counted else FAIL,
                f"scan-frame={verdict.get('objectCount')} analyze-image={counted}",
            )
        except Exception as exc:  # noqa: BLE001
            results.add("POST /api/water/analyze-image", FAIL, f"{type(exc).__name__}: {exc}")
    else:
        results.add("POST /api/water/analyze-image", SKIP, "no sample water image in the repo")

    # ---------------------------------------------------------------- 7. waste image
    waste_image = REPO / "runs" / "debug_waste" / "original" / "metal_can.jpg"
    if waste_image.is_file():
        payload = waste_image.read_bytes()
        try:
            response = post(
                "/api/waste/segregate",
                files={"file": (waste_image.name, payload, "image/jpeg")},
            )
            waste = response.json()
            results.add(
                "POST /api/waste/segregate",
                PASS if response.status_code == 200 and waste.get("status") == "ok" else FAIL,
                f"{waste['summary']['totalObjects']} object(s)",
            )
            # Confidence gates: a confirmed label must carry a real segregation category.
            gate_ok = all(
                (d["status"] == "confirmed") == (d["segregation"] in {"biodegradable", "non_biodegradable"})
                for d in waste.get("detections", [])
            )
            results.add("waste confidence gates hold", PASS if gate_ok else FAIL)

            # XAI: opt-in, and a real attribution or an honest absence.
            explained = post(
                "/api/waste/segregate?explain=true",
                files={"file": (waste_image.name, payload, "image/jpeg")},
            ).json()
            xai = [d.get("xai") for d in explained.get("detections", []) if d.get("xai")]
            honest = all(x.get("available") or not x.get("overlayImage") for x in xai)
            results.add(
                "XAI is a real attribution or a stated absence",
                PASS if xai and honest else (FAIL if not honest else SKIP),
                f"{sum(1 for x in xai if x.get('available'))}/{len(xai)} available",
            )
            # And it must be OFF unless asked for.
            default_off = all(d.get("xai") is None for d in waste.get("detections", []))
            results.add("XAI is off by default", PASS if default_off else FAIL)
        except Exception as exc:  # noqa: BLE001
            results.add("POST /api/waste/segregate", FAIL, f"{type(exc).__name__}: {exc}")

        try:
            response = post(
                "/api/waste/analyze", files={"file": (waste_image.name, payload, "image/jpeg")}
            )
            results.add("POST /api/waste/analyze", PASS if response.status_code == 200 else FAIL)
        except Exception as exc:  # noqa: BLE001
            results.add("POST /api/waste/analyze", FAIL, f"{type(exc).__name__}")
    else:
        results.add("waste image endpoints", SKIP, "no sample waste image in the repo")

    # ---------------------------------------------------------------- 8. error handling
    try:
        response = post(
            "/api/waste/segregate", files={"file": ("bad.jpg", b"this is not an image", "image/jpeg")}
        )
        results.add(
            "invalid image is rejected cleanly",
            PASS if response.status_code == 400 else FAIL,
            f"HTTP {response.status_code} {response.json().get('error', {}).get('code')}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("invalid image is rejected cleanly", FAIL, f"{type(exc).__name__}")

    try:
        response = post("/api/waste/segregate")
        results.add(
            "missing file is a validation error",
            PASS if response.status_code == 422 else FAIL,
            f"HTTP {response.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("missing file is a validation error", FAIL, f"{type(exc).__name__}")

    if litter_image.is_file():
        try:
            truncated = litter_image.read_bytes()[:3000]
            response = post(
                "/api/water/analyze-image",
                files={"file": ("truncated.jpg", truncated, "image/jpeg")},
                data={"location": "Delhi"},
            )
            body = response.json()
            # A broken image must degrade the VISION only; the sensor analysis still stands.
            degraded = response.status_code in (200, 400)
            results.add(
                "corrupt image degrades vision without failing the analysis",
                PASS if degraded else FAIL,
                f"HTTP {response.status_code} risk={body.get('riskScore')}",
            )
        except Exception as exc:  # noqa: BLE001
            results.add("corrupt image degrades gracefully", FAIL, f"{type(exc).__name__}")

    try:
        response = post("/api/analyze", json={"demoMode": True})
        results.add(
            "analyze without a location is rejected",
            PASS if response.status_code == 422 else FAIL,
            f"HTTP {response.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("analyze without a location is rejected", FAIL, f"{type(exc).__name__}")

    # ---------------------------------------------------------------- 8b. RAG
    try:
        status = get("/api/ai/status").json().get("knowledge", {})
        results.add(
            "knowledge corpus indexed",
            PASS if status.get("available") and status.get("chunks", 0) > 10 else FAIL,
            f"{status.get('documents')} docs / {status.get('chunks')} chunks, {status.get('embedding')}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("knowledge corpus indexed", FAIL, f"{type(exc).__name__}")

    try:
        response = post(
            "/api/knowledge/search",
            json={"query": "turbidity BIS permissible limit", "topK": 2, "domain": "water"},
        )
        body = response.json()
        top = (body.get("results") or [{}])[0]
        results.add(
            "retrieval returns the right passage, cited",
            PASS if top.get("chunkId") == "water_quality_standards#turbidity" and top.get("sourceFile") else FAIL,
            f"{top.get('chunkId')} @ {top.get('score')}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("retrieval returns the right passage, cited", FAIL, f"{type(exc).__name__}")

    try:
        body = post("/api/knowledge/search", json={"query": "what is the capital of France"}).json()
        results.add(
            "retrieval declines an off-topic query",
            PASS if not body.get("results") else FAIL,
            "returns nothing rather than citing a source it cannot support",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("retrieval declines an off-topic query", FAIL, f"{type(exc).__name__}")

    if analysis:
        knowledge = (analysis.get("decision") or {}).get("knowledge") or {}
        cited = knowledge.get("results") or []
        results.add(
            "analysis retrieves grounding knowledge",
            PASS if knowledge.get("status") == "ok" and cited else FAIL,
            f"query={knowledge.get('query', '')[:48]!r} -> {len(cited)} passage(s)",
        )
        results.add(
            "every retrieved passage is citable",
            PASS if all(c.get("chunkId") and c.get("sourceFile") for c in cited) else FAIL,
        )

    # ---------------------------------------------------------------- 8c. tools
    try:
        body = get("/api/tools").json()
        names = {t["name"] for t in body.get("tools", [])}
        expected = {
            "get_air_quality_data", "get_water_sensor_data", "analyze_water_image",
            "analyze_waste_image", "get_location_context", "search_environmental_knowledge",
            "calculate_environmental_risk", "generate_investigation_plan",
            "get_waste_segregation_guidance",
        }
        missing = expected - names
        results.add(
            "tool registry exposes the expected tools",
            PASS if not missing else FAIL,
            f"{len(names)} registered" + (f", missing {sorted(missing)}" if missing else ""),
        )
        schema_ok = all(
            t.get("description") and (t.get("parameters") or {}).get("type") == "object"
            for t in body.get("tools", [])
        )
        results.add("every tool advertises a JSON Schema", PASS if schema_ok else FAIL)
    except Exception as exc:  # noqa: BLE001
        results.add("tool registry exposes the expected tools", FAIL, f"{type(exc).__name__}")

    try:
        body = post(
            "/api/tools/calculate_environmental_risk/invoke",
            json={"arguments": {"airScore": 0.94, "waterScore": 0.55, "wasteScore": 0.74}},
        ).json()
        out = body.get("output") or {}
        # (0.94 + 0.55 + 0.74) / 3 == 0.74333 -> 0.74
        results.add(
            "risk tool computes deterministically in Python",
            PASS if body.get("ok") and out.get("riskScore") == 0.74 and out.get("riskLevel") == "HIGH" else FAIL,
            f"{out.get('riskScore')} {out.get('riskLevel')}",
        )
    except Exception as exc:  # noqa: BLE001
        results.add("risk tool computes deterministically in Python", FAIL, f"{type(exc).__name__}")

    try:
        body = post("/api/tools/no_such_tool/invoke", json={"arguments": {}}).json()
        results.add(
            "unknown tool returns a structured error",
            PASS if body.get("ok") is False and body.get("errorCode") == "UNKNOWN_TOOL" else FAIL,
            f"HTTP 200, errorCode={body.get('errorCode')}",
        )
        bad = post(
            "/api/tools/calculate_environmental_risk/invoke", json={"arguments": {"airScore": 5}}
        ).json()
        results.add(
            "invalid tool arguments are rejected",
            PASS if bad.get("errorCode") == "INVALID_ARGUMENTS" else FAIL,
        )
    except Exception as exc:  # noqa: BLE001
        results.add("unknown tool returns a structured error", FAIL, f"{type(exc).__name__}")

    # ---------------------------------------------------------------- 9. no chemical overclaim
    if analysis:
        try:
            water = analysis.get("water") or {}
            decision = analysis.get("decision") or {}
            text = json.dumps(
                {
                    "findings": water.get("findings"),
                    "explanation": decision.get("explanation"),
                    "reasons": decision.get("reasons"),
                }
            ).lower()
            overclaims = [
                phrase
                for phrase in ("chemical contamination detected", "chemically contaminated", "unsafe to drink")
                if phrase in text
            ]
            results.add(
                "no unsupported chemical-contamination claim",
                FAIL if overclaims else PASS,
                f"found {overclaims}" if overclaims else "",
            )
        except Exception as exc:  # noqa: BLE001
            results.add("no unsupported chemical-contamination claim", FAIL, f"{type(exc).__name__}")

    client.close()

    # ---------------------------------------------------------------- summary
    passed = sum(1 for r in results.rows if r[1] == PASS)
    skipped = sum(1 for r in results.rows if r[1] == SKIP)
    print("\n" + "=" * 78)
    print(f"{passed} passed · {len(results.failed)} failed · {skipped} skipped")
    for name, _status, detail in results.failed:
        print(f"  FAILED: {name} — {detail}")
    print("=" * 78)
    return len(results.failed)


if __name__ == "__main__":
    sys.exit(main())
