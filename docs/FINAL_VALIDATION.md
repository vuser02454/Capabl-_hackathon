# Final Validation

Every result below was produced by running the system on **2026-09-19**, not by inspection.

---

## 1. Test suites

| Suite | Command | Result |
| --- | --- | --- |
| Backend unit/integration | `.venv/bin/python -m pytest backend/tests -q` | **408 passed**, 0 failed |
| Frontend typecheck | `npx tsc --noEmit` | **exit 0** |
| Frontend tests | `npx vitest run` | **38 passed** (3 files) |
| Frontend production build | `npm run build` | **succeeded** — 2,941 modules, 331 kB gzip |
| Demo scenarios | `backend/scripts/demo_scenarios.py` | **5/5 passed** |
| Live smoke test | `backend/scripts/smoke_test.py` | **37 passed**, 0 failed |

Backend tests went 333 → 362 → **408**. The first round added 29 (semantic separation ×17, waste
confidence gates ×6, Grad-CAM ×6); the optimization round added 46 more (RAG ×27, tools ×19).
Smoke checks went 27 → **37**.

### Retrieval and tool checks (optimization round)

| Check | Result |
| --- | --- |
| Knowledge corpus indexed | 6 documents / 37 chunks, `tfidf-sparse-lexical` |
| Retrieval returns the right passage, cited | `water_quality_standards#turbidity` @ 0.62 |
| Retrieval declines an off-topic query | returns nothing rather than citing |
| Analysis retrieves grounding knowledge | 3 passages, all citable |
| Tool registry exposes the expected tools | 9 registered |
| Every tool advertises a JSON Schema | pass |
| Risk tool computes deterministically | 0.74 HIGH, matches `core/risk.py` |
| Unknown tool / invalid arguments | `UNKNOWN_TOOL` / `INVALID_ARGUMENTS`, HTTP 200 |

**Retrieval quality, measured on 12 queries:** all 8 on-topic queries returned the expected
passage as the top hit; all 4 off-topic queries (`capital of France`, `best pizza in Naples`,
`bake bread`, `tell me a joke`) correctly returned nothing.

## 2. Smoke-test coverage (§21)

| # | Requirement | Check | Result |
| --- | --- | --- | --- |
| 1 | Backend startup | `/api/health` → 200, v1.1.0 | PASS |
| 2 | Frontend startup | `tsc` + `vite build` | PASS |
| 3 | Water analysis | `POST /api/water/analyze-image` | PASS |
| 4 | Waste analysis | `POST /api/waste/segregate` | PASS |
| 5 | LangGraph execution | `POST /api/analyze/graph`, 4 agent runs | PASS |
| 6 | Deterministic risk | decision trace, 10 steps | PASS |
| 7 | Explanation generation | provider reported (`groq`), fallback path tested | PASS |
| 8 | Missing sensor | degraded reading → warnings, analysis continues | PASS |
| 9 | Missing vision | `not_run` / `unavailable` with a reason | PASS |
| 10 | Low-confidence waste | → `needs_review` / `uncertain`, candidate kept | PASS |
| 11 | Non-waste detection | `NEVER_WASTE_CLASSES`, segregation withheld | PASS |
| 12 | Invalid image | `400 INVALID_IMAGE` | PASS |
| 13 | Demo mode | `isMock: true` propagates; `mode: demo` | PASS |
| 14 | API endpoints | 12 endpoints probed | PASS |
| 15 | Frontend/backend integration | typed contract, build clean | PASS |

## 3. Endpoints verified live

| Endpoint | Status |
| --- | --- |
| `GET /api/health` · `/api/agents/status` · `/api/locations` · `/api/ai/status` | 200 |
| `GET /api/waste/pipeline-status` · `/api/water/dataset-status` · `/api/environment/{loc}` | 200 |
| `POST /api/analyze` · `/api/analyze/graph` | 200 |
| `POST /api/location/reverse` · `/api/location/search` · `/api/location/context` | 200 |
| `POST /api/water/analyze-image` · `/api/water/scan-frame` · `/api/water/match-frame` | 200 |
| `POST /api/waste/analyze` · `/api/waste/segregate` (+`?explain=true`) · `/api/waste/debug` | 200 |

**No endpoint was renamed or removed.** `?explain=true` is additive and defaults to off.

## 4. Fixes verified by before/after measurement

### C1 — Non-pollution objects counted as water pollution *(critical)*

Image: `water_datasets/TUD-GV/images/exp55_221.jpg`

| | Before | After |
| --- | --- | --- |
| Detections | person ×2, kite ×4 | person ×2, kite ×4 *(unchanged — nothing is hidden)* |
| Counted as pollution | **6** | **0** |
| `visual_score` | 0.30 | 0.00 |
| Water risk | 0.55 → **0.63** | **0.55** (no escalation) |
| Finding emitted | "Visible pollution in water" | *none* |
| `scan-frame` agreement | **0 vs 6 — contradictory** | **0 vs 0 — agree** |

Litter is still counted — verified separately: `plastic_bottle.jpg` → `bottle` classified
`visible_surface_litter`, risk 0.55 → 0.56, finding emitted. `vase` (COCO's usual misread of a
bottle) stays `unclassified_object` and is not counted, which is the conservative direction.

### C2 — Waste confidence gate bypass *(high)*

`runs/debug_waste/original/person_and_aerosol_can.jpg`, detection 2:

| | Before | After |
| --- | --- | --- |
| Detection confidence | 0.395 | 0.395 |
| Classification confidence | 0.5673 *(below 0.60)* | 0.5673 |
| Status | **`confirmed`** | **`needs_review`** |
| Segregation | **`biodegradable`** | **`uncertain`** |
| Message | "…the classifier did not confirm a label" *(while confirmed)* | "…below the 60% threshold… No segregation is asserted." |

Confident cases are unchanged: detection 1 (det 0.937 / cls 0.887) stays `confirmed`.

**An intermediate version was rejected.** Handing the label to the classifier when the detector
was weak asserted `ewaste` at 85% for a photograph of paper — routing paper to hazardous handling
with a confident-looking number. The held-out data says the classifier loses these disagreements
6–22, so the final behaviour keeps the detector's class as a **candidate** and asserts nothing.
Both branches are covered by tests.

### C3 — Paper described as non-degrading *(medium)*

`paper_waste` is `biodegradable` but its `handling: recyclable` note read *"**Non-degrading** but
widely recoverable"* — so one card said biodegradable and non-degrading simultaneously. Paper now
has its own `fibre_recyclable` handling key: *"Degrades naturally, and recoverable as fibre while
it is still dry and clean."* Config-only change.

### C4 — XAI did not exist *(medium)*

A repo-wide search for `gradcam|grad_cam|integrated_grad|occlusion|saliency|heatmap|xai` returned
**zero matches**. Now: real Grad-CAM at `features[-1]`, verified as

- **faithful** — explained class/confidence equal `classify()` output exactly (0.8974 both);
- **class-conditional** — different target → different map and confidence (0.8974 vs 0.0069);
- **honest on failure** — `available: false` + reason + **no image**;
- **off by default** — absent unless `?explain=true`.

Visually inspected: on `metal_can.jpg` the attribution concentrates on the **metal lid and rim**,
the genuinely discriminative feature.

## 5. Error handling verified

| Input | Behaviour |
| --- | --- |
| Text file named `.jpg` | `400 INVALID_IMAGE` |
| Truncated JPEG | `200` — sensor analysis completes, vision degrades with a stated reason |
| Missing file field | `422 VALIDATION_ERROR` |
| `analyze` with no location | `422` |
| Classifier unavailable | `uncertain` + "no trained classifier", never a guess |
| Detector finds nothing | "found no objects it recognises… not the same as 'no waste is present'" |
| LLM unavailable | deterministic template; decision unchanged |
| Overpass slow | capped at 10 s, degrades to `unavailable` |

## 6. Security

- `backend/.env` was read for **variable names only**. No value was printed or modified.
- `/api/ai/status` asserted free of key-shaped tokens (`sk-`, `AIza`, `gsk_`, `api_key`).
- Pre-existing test `test_status_never_leaks_a_key` still passes.
- Roboflow and Overpass error paths raise `type(exc).__name__` only — never a URL or key.
- No secret was added, moved, logged or committed.

## 7. Honesty checks

Asserted by automated test, not by review:

- Vision evidence never contains `contamination detected`, `chemically contaminated`,
  `unsafe to drink`, `not potable`, `dissolved oxygen` or `toxic`, and must contain `surface`.
- Scenario B asserts no output contains `water is clean`, `safe to drink`, `no pollution` or
  `potable`.
- Smoke test asserts the full analysis contains no unsupported chemical-contamination claim.
- `IMG-DET-00N` ids still index the real box positions after litter filtering
  (`["IMG-DET-002"]` for a person/bottle/person frame — the bottle keeps index 2).

## 8. Performance

| Operation | Time |
| --- | --- |
| Full `/api/analyze` (3 agents parallel + LLM) | ~2.5 s |
| `/api/water/analyze-image` (YOLO + match) | ~1–2 s |
| `/api/waste/segregate` | ~1 s |
| `+?explain=true` | +~0.3 s per detected object |

Models are loaded **once per process** and cached behind a lock (`LocalYoloDetector._cache`,
`WasteClassifier._cache`). Heavy imports (`torch`, `ultralytics`) are lazy, so a missing optional
dependency degrades rather than breaking import. No LLM or LangGraph call sits on the live-frame
path — `scan-frame` is detection only.

## 9. Not fixed, deliberately

| Item | Why |
| --- | --- |
| `visual_score` calibration | Blocked on B1 (no clean-water negatives). Retained as an explicit provisional demo signal, documented. |
| Water detector training | TUD-GV split ready; blocked on B1. Shipping a stated limitation beats an unvalidated model. |
| `plastic_bottle.jpg` → 0 detections | Genuine detector recall gap, not a defect. Documented as a demo-input choice. |
| FloW usage | Redistribution rights unresolved (B3). |
| 1.1 MB frontend bundle | Cosmetic; no demo impact. |
