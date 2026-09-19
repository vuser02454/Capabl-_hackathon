# EcoSentinel AI — Finalization Baseline

**Audit date:** 2026-09-19 · **Scope:** read-only inspection. **No code was changed to produce this document.**

This is the pre-change state of the repository, recorded so every later edit can be judged against
it. Everything below was verified by running the system, not by reading the README.

---

## 1. Verification method

| Check | Command | Result |
| --- | --- | --- |
| Backend test suite | `.venv/bin/python -m pytest backend/tests -q` | **333 passed**, 0 failed, 3.24 s |
| Backend startup | `uvicorn main:app` (port 8077) | **Starts clean**, no warnings in log |
| Frontend typecheck | `npx tsc --noEmit` | **Exit 0**, no errors |
| Frontend tests | `npx vitest run` | **38 passed** (3 files) |
| API surface | 12 endpoints probed live | **All HTTP 200** |
| Error paths | corrupt / truncated / missing image | **All degrade gracefully** |

The repository is **not a git repository** (`git status` → fatal). There is no version-control
safety net, so every change must be individually reversible and narrow.

---

## 2. What currently works

### 2.1 LangGraph — a genuine reasoning graph, not a wrapper

`backend/agents/langgraph_orchestrator.py` (732 lines) builds a real `StateGraph` with **15 nodes**:

```
START → resolve_location → triage_environment
                              ├→ run_air     ─┐
                              ├→ run_water   ─┤  (true parallel fan-out)
                              ├→ run_waste   ─┤
                              └→ context_enrichment ─┘
                                            → coordinate
                                            → normalize_evidence
                                            → detect_problems
                                            → cross_signal_reasoning
                                            → evaluate_conflicts
                                            → check_data_sufficiency
                                       ┌────── conditional edge ──────┐
                              investigation_needed          decision_synthesis
                                       └──────────→ decision_synthesis
                                            → frame_investigation
                                            → explain_decision → END
```

This already satisfies the intended architecture's node list. `runs` uses an
`Annotated[List, operator.add]` reducer so parallel branches do not overwrite each other, and
`_run_node` wraps every specialist in `asyncio.wait_for` so one failure becomes a structured
`AgentRun(status="failed")` instead of aborting the graph. **Do not rebuild this.**

### 2.2 Deterministic risk engine is genuinely the source of truth

The separation is enforced architecturally, not by convention:

- `backend/config.py` defines two **non-interchangeable** LLM roles — `FUNCTIONAL_AI_PROVIDER`
  (output validated against Pydantic, enters as evidence) and `EXPLAINABILITY_AI_PROVIDER`
  (receives an already-final decision).
- `backend/tests/conftest.py` carries a **static test asserting `coordinator_agent.py` never
  imports `services` / `http` / `urllib` / `requests` / `httpx`** — the Coordinator physically
  cannot reach a network or an LLM.
- Verified live: `/api/analyze` returned `riskScore: 0.79` with `explanationProvider: "groq"` and
  `llmEnhanced: true`. The LLM wrote prose; the number came from `core/risk.py`.

### 2.3 Evidence and conflict reasoning already exist

`core/evidence.py` normalises all three domains into one `EnvironmentalEvidence` list, with
per-detection IDs (`IMG-DET-001`) that resolve back to the actual bounding box. Geographic
context is carried at `severity=0.0, confidence=0.0` with an explicit comment that a mapped
factory is "a polygon a contributor drew: it is not an emission" — §15 is already satisfied.

`core/decision.py:evaluate_conflicts` already detects **exactly the Scenario C case**:

> "{Domain} measurements are within guideline limits while visual detections are elevated.
> Measurements and observations disagree; neither alone settles the question."

### 2.4 Waste pipeline

Two-stage detect→classify with real refusals: sub-threshold → `uncertain`/`needs_review`;
crops under 24 px → `uncertain`; IoU ≥ 0.7 deduplication with absorbed class names preserved;
`NEVER_WASTE_CLASSES` exclusion list preventing a confident `wood_waste` label on a dog.
Measured live on 6 images: 5/6 produced correct confirmed classifications at 0.85–0.96.

### 2.5 Air agent

193 lines, WHO 2021 guidelines, India NAQI breakpoints explicitly labelled as an estimate, real
OpenAQ v3 integration with a demo fallback. **Per §14 this is not to be rebuilt.** No defects found.

### 2.6 Error handling

| Input | Behaviour | Verdict |
| --- | --- | --- |
| Text file named `.jpg` | `400 INVALID_IMAGE` | correct |
| Truncated JPEG | `200` — sensor analysis completes, vision degrades to a warning | correct |
| Missing file field | `422 VALIDATION_ERROR` | correct |
| LLM unavailable | falls back to deterministic template | correct (`explanation` field) |

### 2.7 Dataset provenance research is already done and is high quality

`runs/water/dataset_comparison/` contains nine analysis documents including
`LICENSE_PROVENANCE_REPORT.md`, `VISUAL_SCORE_AUDIT.md`, `NEGATIVE_DATA_REQUIREMENTS.md` and
`WATER_TRAINING_READINESS.md`, which already state blockers B1/B2/B3 honestly. **This work does
not need repeating — it needs surfacing into `docs/`.**

---

## 3. Critical bugs found

### C1 — CRITICAL: the Water Agent counts non-pollution objects as water pollution

**This is the single most damaging defect for the demo.**

The production water detector is **COCO-pretrained YOLOv8n** (`YOLO26_MODEL_PATH=models/yolov8n.pt`),
which emits COCO classes: `person`, `kite`, `boat`, `car`. `score_detections()` in
`services/water_vision_service.py:378` counts **every** detection with no class filter:

```python
return round_half_up(clamp(len(detections) / count_reference))
```

Measured live on `water_datasets/TUD-GV/images/exp55_221.jpg`:

```
detections : person 0.482, kite 0.450, person 0.401, kite 0.325, kite 0.278, kite 0.262
objectCounts : {'person': 2, 'kite': 4}
visual_score : 0.30
finding      : "Visible pollution in water" (impact 0.075)
risk         : 0.55 (water quality) → 0.63 (after visual escalation)
```

**Two people and four kites were reported as visible water pollution and raised the risk score.**

The system already contradicts itself about this. `core/investigation.py` defines
`is_pollution_class()`, and `main.py:557` uses it — so on the *same image*:

| Endpoint | Answer |
| --- | --- |
| `POST /api/water/scan-frame` | `objectCount: 0`, `"No supported visible pollution objects in this frame."` |
| `POST /api/water/analyze-image` | `totalObjects: 6`, "Visible pollution in water", **risk +0.08** |

The frontend `WaterVisionPanel.tsx` renders `objectCounts` verbatim, so the dashboard displays
**"person 2 / kite 4"** beneath the heading "pollution objects".

**Fix:** reuse the existing `is_pollution_class()` in the water vision scoring path — do **not**
write a second taxonomy (§1: "do not create duplicate utilities"). Preserve the raw detector class
alongside a semantic category, per §6.

### C2 — HIGH: waste detector authority bypasses the confidence gates

`_apply_detector_authority()` (`services/waste/waste_pipeline.py:255`) sets
`status="confirmed"` based solely on whether a category mapping exists — it never consults the
detector's own confidence, and it overwrites a `needs_review` verdict. Measured live:

```json
{ "id": "WASTE-DET-002",
  "detectionConfidence": 0.395,          ← weak detection
  "classificationConfidence": 0.5673,    ← BELOW the 0.60 threshold
  "status": "confirmed",                 ← asserted anyway
  "labelSource": "detector",
  "message": "...because the classifier did not confirm a label." }
```

The record simultaneously says the classifier did **not** confirm a label and that the result is
**confirmed**. It was a person in the frame, labelled `paper_waste` → `biodegradable`. This
violates §10 ("never convert low-confidence predictions into confident labels"). Note
`waste_categories.json` already defines `detection_confidence: 0.25` — a threshold nothing reads.

### C3 — MEDIUM: paper waste carries a factually wrong environmental note

`_handling_note()` keys the note by `handling`, not by material. `paper_waste` is
`category: biodegradable, handling: recyclable`, and `handling_notes["recyclable"]` reads:

> "**Non-degrading** but widely recoverable through recycling streams."

So the UI shows paper waste as biodegradable *and* non-degrading in the same card. The note is
correct for plastic bottles and metal cans; it is wrong for paper. Config-only fix.

### C4 — MEDIUM: XAI does not exist

A repo-wide search for `gradcam|grad_cam|integrated_grad|occlusion|saliency|heatmap|xai` across
`backend/` and `frontend/src` returns **zero matches**. §9 and §11 both place XAI in the waste
pipeline. Nothing fabricates a heatmap today — the honest state is "absent", not "fake".

Feasibility is good: the classifier is **MobileNetV3-Small** and `classify()` already accepts a
`capture` dict returning the exact input tensor and full probability vector, so a genuine Grad-CAM
over `features[-1]` is a contained addition operating on real model gradients.

### C5 — LOW: detector recall gap on one demo image

`runs/debug_waste/original/plastic_bottle.jpg` → **0 detections** (5 of 6 other images work).
Not a crash; a recall limit of the TACO-trained detector. Matters only for demo input selection.

### C6 — Demo scenarios A–E do not exist as runnable fixtures

Demo mode itself is solid (`ECOSENTINEL_DEMO_MODE=true`, `isMock` flags propagate to every
report). But there is no scripted path that reproduces the five scenarios in §17, and in
particular no fixture that produces the **conflicting-evidence** case, which §24 identifies as
the key presentation moment.

### C7 — `docs/` does not exist

The 920-line README is thorough, but none of the six documents required by §23 exist, and the
substantial dataset-provenance analysis is buried in `runs/water/`.

---

## 4. Existing models

| Model | Path | Role | State |
| --- | --- | --- | --- |
| YOLOv8n (COCO) | `backend/models/yolov8n.pt` | Water vision | Generic COCO — **source of C1** |
| Waste detector (TACO) | `backend/models/waste_detector.pt` | Waste stage 1 | Working, configured |
| MobileNetV3-Small | `runs/classification/best.pt` | Waste stage 2, 8 classes | Working, thr 0.60 |
| Letterbox v1 / v2 | `runs/classification_letterbox*/best.pt` | Experimental | **Do not delete** |

Classifier preprocessing note, surfaced honestly by `status()`: the shipped weights do not record
their training preprocessing, so the match with the served `letterbox_v2` transform is
**unverified** — chosen by measurement on real crops, not by matching.

---

## 5. Things that must NOT be touched

- `backend/agents/air_agent.py` — working, §14.
- `backend/agents/langgraph_orchestrator.py` graph topology — already correct.
- `backend/agents/coordinator_agent.py` import restrictions — enforced by test.
- `backend/.env` — read for key *names* only; values never printed and never modified.
- `runs/classification_letterbox*`, `runs/waste_detection/taco_yolov8n/` — experimental models.
- `runs/water/**` and `runs/evaluation/**` — existing reports and metrics.
- `datasets/`, `water_datasets/`, `garbage_Dataset/`, `TACO-master/` — datasets.
- The 333 backend tests and 38 frontend tests — all must still pass after every change.
- `water_visual_weight` / `count_reference` **values** — recalibration is blocked on B1/B2
  (no clean-water negatives); they stay as documented provisional demo constants.

---

## 6. Planned changes, in priority order

| # | Change | Risk | Addresses |
| --- | --- | --- | --- |
| 1 | Semantic filter in water vision reusing `is_pollution_class`; raw class preserved | Low | C1 |
| 2 | Detector authority must respect confidence gates | Low | C2 |
| 3 | Correct the paper-waste handling note (config only) | None | C3 |
| 4 | Real Grad-CAM over MobileNetV3, degrading to "XAI unavailable" | Medium | C4 |
| 5 | Demo scenario fixtures + runner covering A–E | Low | C6 |
| 6 | Frontend: OBSERVED / INFERRED / NOT ESTABLISHED distinctions | Low | §16 |
| 7 | Smoke-test suite (§21) | None | — |
| 8 | `docs/` × 6 + `FINAL_STATUS.md` | None | C7 |

**Explicitly out of scope:** retraining any detector, acquiring datasets, recalibrating
`visual_score` numerically (blocked on B1), replacing the production waste detector, UI redesign.
