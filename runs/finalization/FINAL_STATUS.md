# EcoSentinel AI — Final Status

**Date:** 2026-09-19 · Baseline: `FINALIZATION_BASELINE.md` · Evidence: `docs/FINAL_VALIDATION.md`

---

## PROJECT STATUS

| Component | Status |
| --- | --- |
| **Backend** | **READY** — starts clean, 362 tests, 12 endpoints verified |
| **Frontend** | **READY** — typecheck exit 0, 38 tests, production build succeeds |
| **Air** | **READY** — untouched except integration verification, per §14 |
| **Water** | **PARTIALLY_READY** — critical semantics bug fixed; detector is still COCO-pretrained |
| **Waste** | **READY** — gates corrected, real Grad-CAM added |
| **LangGraph** | **READY** — genuine StateGraph, parallel fan-out, conditional edge |
| **Risk Engine** | **READY** — deterministic and structurally isolated from every LLM |
| **Chat** | **READY** — 3-route agent (Gemini + tools / secondary LLM / grounded), 18 tests |
| **RAG** | **READY** — 6-stage pipeline, cited retrieval, grounded explanation, 27 tests |
| **Tools** | **READY** — 9 typed tools, JSON Schema, validation, 19 tests |
| **Demo** | **READY** — 5 scenarios, offline-capable, all simulated data labelled |
| **Testing** | **PASS** — 426 backend + 38 frontend + 5 scenarios + 37 smoke, 0 failures |
| **Browser E2E** | **NOT VERIFIED** — no browser automation available in this environment |

**Water is PARTIALLY_READY for one reason only:** the detector is COCO-pretrained YOLOv8n, not a
trained water-litter model. It will under-detect real floating litter. It will no longer *invent*
pollution, which was the defect. This is a data blocker (B1), not a code defect, and it is
documented rather than worked around.

---

## 1. Fixed issues

### C1 — Non-pollution objects counted as water pollution *(CRITICAL)*
Two people and four kites in a river photo were scored as 0.30 visual pollution and escalated
water risk 0.55 → 0.63. Two endpoints disagreed on the same image: `scan-frame` reported 0
pollution objects while `analyze-image` reported 6 and raised the risk.

Root cause: `is_pollution_class` existed in `core/investigation.py` and was used by the
investigation and `scan-frame`, but the Water Agent's risk path never called it — effectively two
taxonomies.

Fixed by consolidating one taxonomy (`semantic_category_for` / `effective_semantic_category`) in
`core/investigation.py` and using it everywhere. Raw detector class and semantic interpretation
are now **separate fields**. Non-litter detections remain visible in the report and are excluded
from the score. Both endpoints now agree. 17 tests added.

### C2 — Waste confidence gate bypass *(HIGH)*
`_apply_detector_authority` set `status="confirmed"` from the existence of a category mapping
alone, never reading the detector's confidence. A person detected as `paper_waste` at 0.395, with
the classifier below threshold at 0.567, came back as a **confirmed biodegradable** object whose
own message said "the classifier did not confirm a label".

Fixed with an explicit assertion bar: the detector's class is still preferred (the measured 22-vs-6
win stands), but it is only *asserted* when the detector clears 0.60. Below that the label is a
candidate and segregation is withheld. 6 tests added.

### C3 — Paper described as non-degrading *(MEDIUM)*
`handling_notes` keyed by handling meant one note served plastic, metal and paper. Paper read
"biodegradable" and "non-degrading" simultaneously. Added a `fibre_recyclable` key. Config only.

### C4 — XAI did not exist *(MEDIUM)*
Zero matches repo-wide for any attribution method, despite XAI being in the stated architecture.
Added real Grad-CAM over MobileNetV3 `features[-1]`, opt-in, verified faithful and
class-conditional by test, with an honest `available: false` + no image on failure. 6 tests added.

### C6 — No runnable demo scenarios
Added `backend/scripts/demo_scenarios.py`: five scenarios over the real agents and real decision
engine with stubbed inputs only, each asserting the behaviour it demonstrates.

### Optimization round — RAG and tool layer *(added after the first finalization)*

The optimization brief stated both existed. **Neither did**: 0 matches repo-wide for
`@tool`/`bind_tools`/`ToolNode`, 0 for `embedding`/`vector_store`/`retriever`, and no RAG
dependency installed. That was 45 of 100 technical marks at zero.

**RAG** (`backend/services/rag/`): loader → chunker → TF-IDF embeddings → vector store →
retriever → grounded generation. Corpus is seven documents restating knowledge already encoded in
this codebase, each naming its source file. Two honesty gates — a cosine relevance floor and a
50% query-coverage gate — so an off-topic query returns nothing rather than a citation it cannot
support. Retrieved passages are attached to the decision *after* synthesis, so no passage can
reach a score. 27 tests.

**Tools** (`backend/services/tools/`): nine typed tools wrapping already-tested implementations,
each with Pydantic input/output models, validation before execution, and distinct error codes.
`calculate_environmental_risk` runs `core/risk.py` — the boundary being that a model chooses
which tool to call, and the tool decides what the answer is. 19 tests.

**UI**: Evidence Fusion (the architecture drawn from the run that happened), Analysis Trace
(execution events only — not chain-of-thought), Retrieved Knowledge panel (query, passages, chunk
ids, source files, relevance), Investigation Mode (observed / not established / verify next as a
working checklist).

### Water + chat round *(third pass)*

**Water root cause found and proven.** The production COCO detector returns **0 detections** at
threshold 0.25 on `image copy 3.png`, a canal packed with plastic bottles. Below threshold its
only hypotheses are `bird` (0.089) and `kite` (0.015) — it **never proposes `bottle` at any
threshold**, despite `bottle` being a COCO class. Domain mismatch, not a threshold, taxonomy,
decoder or prompt problem. Full reproduction: `WATER_CURRENT_FAILURE.md`.

**Provisional detector trained** on the audited TUD-GV session-level split (1,057/298/146, source
untouched, materialised as symlinks). Validation mAP50 **0.936**; **9 litter detections** on the
exact image the current model scored zero on. **But it fires 6 detections at up to 0.84 on a
visibly clean restored river** — blocker B1 made real. Not promoted to default; available by a
one-line config change, with the trade-off documented in `WATER_MODEL_COMPARISON.md`.

**Chat agent built** (`services/ai/chat_agent.py`): Gemini routes intent and names one tool from
a six-tool allow-list; the registry validates and executes; Gemini explains a result it may not
change; general questions go to the secondary LLM with no access to the user's data. Every layer
degrades — the whole suite runs with both providers off.

### Frontend honesty
`WaterVisionPanel` showed `objectCounts` verbatim — "person 2 / kite 4" under a pollution
heading. Rebuilt around **Observed — visible litter** / **Also detected — not counted as
pollution** / **Not established**, plus Grad-CAM display and an explain toggle. Two other call
sites that labelled the raw total as "pollution objects" were corrected.

---

## 2. Existing strengths (pre-existing, not built here)

- **LangGraph is a real reasoning graph** — 15 nodes, genuine parallel fan-out with an additive
  state reducer, per-node timeout isolation, a conditional edge on data sufficiency.
- **LLM/score separation is structural** — two non-interchangeable roles, plus a static test that
  the Coordinator cannot import an HTTP client.
- **Evidence model is genuinely good** — per-detection ids resolving to real boxes, provenance and
  `is_mock` on every item, geographic context pinned at severity 0.
- **Conflict detection already existed** and implements exactly the demo's central case.
- **Refusals throughout** — confidence gates, `NEVER_WASTE_CLASSES`, min crop size, IoU dedup with
  absorbed names preserved, dataset matcher barred from the score.
- **Dataset provenance research is excellent** — licences verified against Figshare/Zenodo APIs,
  leakage-safe split designed, blockers stated rather than glossed.
- **Error handling was already solid** — every failure path degrades with a stated reason.

---

## 3. Remaining limitations

1. **Water detector is COCO-pretrained** — will under-detect real floating litter. No water model
   trained (blocked on B1).
2. **`visual_score` is uncalibrated** — `count_reference = 20` is a convention; up to 8.7× swing
   between detector families. Retained as an explicit provisional demo signal, capped at +0.25.
3. **No clean-water negatives (B1)** — false-positive rate on clean water is **unmeasured**, and
   clean water is the most common real input.
4. **End-to-end TACO correctness is 7.5%** — TACO is very hard; the dominant error is the
   classifier *abstaining* (41 of 107), not being wrong.
5. **`plastic_bottles` recall 73.9%** — under-reports rather than over-reports.
6. **Training set imbalance 56:1** — macro F1 is the honest headline.
7. **Classifier preprocessing provenance unverified** — surfaced in `pipeline-status`, not hidden.
8. **`plastic_bottle.jpg` yields 0 detections** — genuine recall gap; avoid as a demo input.
9. **FloW rights unresolved (B3)** — not used.
10. **No ground truth for combined water risk** — never validated against an independent measure.

---

## 4. Verified metrics

| Metric | Value | Source |
| --- | --- | --- |
| Classifier accuracy / macro F1 | 93.4% / **91.1%** (1,200 held-out) | `runs/evaluation/classification_report.json` |
| Best / worst class F1 | leaf_waste 0.994 / plastic_bottles 0.842 | same |
| Detector localisation (held-out TACO) | **53.3%** vs COCO 9.3% | `runs/waste_detection/AB_TEST_REPORT.md` |
| End-to-end pipeline correctness | **7.5%** vs COCO 2.8% | same |
| Detector vs classifier disagreements | detector right 22, classifier 6 (of 42) | same |
| RGB/BGR bug cost | 46% of detections | same |
| TUD-GV split | 1,057 / 298 / 146, zero leakage | `TUDGV_SPLIT_MANIFEST.json` |
| Backend tests | **362** (was 333) | `pytest backend/tests` |
| Smoke checks | **27 passed, 0 failed** | `backend/scripts/smoke_test.py` |

---

## 5. Dataset provenance

| Dataset | Licence | Status |
| --- | --- | --- |
| IWHR (3,000 img / 23,692 boxes) | **Apache 2.0** — Figshare DOI `10.6084/m9.figshare.27376851.v1` | Verified; evaluation role only |
| TUD-GV (1,501 img / 8,181 boxes) | **CC BY 4.0** — Zenodo DOI `10.5281/zenodo.13730228` | Verified; attribution required |
| FloW-Img (1,200 local) | **UNRESOLVED** | Not used |
| garbage_Dataset | Classifier training | 111 leaked images excluded |
| TACO | Detector training + held-out eval | No new labels created |

Full detail: `docs/DATASET_PROVENANCE.md`.

---

## 6. Demo commands

```bash
# Terminal 1 — backend (MUST be run from inside backend/)
cd backend && ../.venv/bin/python -m uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev

# Verify before presenting (~1 minute total)
.venv/bin/python backend/scripts/demo_scenarios.py          # expect 5/5
.venv/bin/python backend/scripts/smoke_test.py              # expect 27 passed
.venv/bin/python -m pytest backend/tests -q                 # expect 362 passed
```

---

## 7. Known risks at demo time

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Backend launched from repo root → "no weights" | Medium | Documented; always `cd backend` first |
| Judge uploads a crowded/tiny-litter photo | Medium | Expect low recall; say so — abstention is by design |
| `plastic_bottle.jpg` used by accident | Low | Use `metal_can.jpg` / `plastic_bag.jpg` |
| Groq/OpenRouter down | Low | Deterministic fallback; decision unchanged |
| Overpass slow | Medium | Capped at 10 s, degrades cleanly |
| Judge asks about accuracy | **High** | Know the 91.1% vs 7.5% distinction cold |
| No internet | Low | Demo mode is fully offline |

---

## 8. What should NOT be claimed

1. Not "detects chemical contamination from an image" — it detects **visible surface litter**.
2. Not "93.4% accurate" as a pipeline figure — that is the classifier on clean crops.
3. Do not hide the **7.5%** end-to-end figure; explain the abstention split instead.
4. Not "a trained water-litter detector" — it is COCO-pretrained.
5. Not "calibrated visual scoring" — `count_reference` is a convention.
6. Not any false-positive rate on clean water — unmeasured (B1).
7. Not "real-time environmental measurements" in demo mode — seeded, marked `isMock`.
8. Not "reports reach authorities" — logged locally unless a destination is configured.
9. Not "FloW-licensed" — rights unresolved.
10. Not "pixel-level explainability" — Grad-CAM is 7×7, upsampled.

---

## 9. Recommended demo sequence (8–10 min)

1. **Problem** (45 s) — fragmented monitoring; signals read alone; disagreements averaged away.
2. **Architecture** (1 min) — `docs/FINAL_ARCHITECTURE.md` diagram. Land the one rule: *vision and
   sensors produce evidence, the deterministic engine produces the number, the LLM produces the
   sentence.* Mention it is enforced by a static test.
3. **Live multi-agent analysis** (1.5 min) — three agents in parallel → evidence → decision.
4. **Water upload** (3 min) — **the centrepiece.** Show visible-litter vs also-detected counts.
   Tell the person/kite story: the bug, the two endpoints disagreeing, the single taxonomy, the
   tests.
5. **Conflicting evidence** (1.5 min) — litter visible, chemistry normal → OBSERVED /
   NOT ESTABLISHED / CONFLICT / RECOMMENDED. Then the converse: no litter + bad chemistry never
   becomes "the water is clean".
6. **Waste + Grad-CAM** (1.5 min) — tick Explain, click a detection, show heat on the can's lid.
   Then the abstain case: candidate shown, segregation withheld.
7. **Honesty close** (45 s) — the limitations slide, unprompted. Blockers B1–B3 named.

> Closing line: *The hard part of environmental AI is not detecting things. It is being honest
> about what a detection means.*

---

## 10. Definition of done

- [x] backend starts · [x] frontend starts · [x] Air works · [x] Water works · [x] Waste works
- [x] LangGraph executes · [x] deterministic risk engine executes · [x] evidence is structured
- [x] conflicts handled · [x] uncertain evidence represented honestly · [x] waste gates work
- [x] no unsupported chemical-contamination claims · [x] demo scenarios work · [x] APIs work
- [x] smoke tests pass · [x] no secrets exposed · [x] documentation exists
- [x] final demo can be performed reliably

**Feature work is complete. Remaining time should go to rehearsal and validation only.**
