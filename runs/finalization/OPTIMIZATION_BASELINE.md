# EcoSentinel AI — Optimization Baseline

**Date:** 2026-09-19 · Read-only audit. **No code was changed to produce this document.**
Prior audit: `FINALIZATION_BASELINE.md` · Prior outcome: `FINAL_STATUS.md`

---

## 0. HEADLINE FINDING — two rubric premises are false

The optimization brief states as verified fact:

> - RAG infrastructure exists
> - tool calling infrastructure exists

**Neither exists.** Verified by exhaustive search, not by impression:

| Search | Scope | Result |
| --- | --- | --- |
| `tool_call\|tools=\|@tool\|bind_tools\|StructuredTool\|ToolNode` | all of `backend/` | **0 matches** |
| `embedding\|vector.?store\|faiss\|chromadb\|\bretriever\b\|\bRAG\b` | `backend/`, excluding tests | **0 matches** |
| RAG dependencies (`faiss`, `chromadb`, `sentence-transformers`, `scikit-learn`, `rank_bm25`) | installed venv | **none installed** |

The only `top_k` in the codebase is `water_dataset_match_service.py` — a **colour-histogram
appearance matcher over images**. It is nearest-neighbour image matching, not document retrieval.
Presenting it as RAG would be precisely what the brief forbids ("DO NOT call a direct LLM prompt
'RAG'").

`services/ai/chat.py` is grounded — but in **decision state held in memory**, keyed by
`analysis_id`. There is no corpus, no chunking, no embedding, no retrieval. It is state lookup.

### Rubric consequence

| Rubric line | Marks | Current |
| --- | --- | --- |
| RAG quality | 20 | **0** |
| Tool design / tool calling | 25 | **0** |
| **Combined** | **45 of 100 technical** | **0** |

**45 of the 100 technical marks are currently unscoreable.** This is the single highest-value
finding in this audit and it reframes the remaining priorities.

---

## 1. Current functionality (verified, unchanged)

| Component | State | Evidence |
| --- | --- | --- |
| Backend | Starts clean, 12 endpoints 200 | smoke test 27/27 |
| Frontend | typecheck exit 0, build succeeds | 38 tests |
| LangGraph | Real `StateGraph`, 15 nodes, parallel fan-out, conditional edge | `langgraph_orchestrator.py` |
| Risk engine | Deterministic, structurally isolated from LLMs | static import test |
| Air agent | WHO 2021 + NAQI estimate, OpenAQ v3 | untouched |
| Water agent | Semantic taxonomy fixed; COCO detector remains | 17 regression tests |
| Waste pipeline | Gates corrected, 4 refusals | 6 gate tests |
| Grad-CAM | Real, faithful, class-conditional | 6 XAI tests |
| Demo scenarios | 5/5 offline | `demo_scenarios.py` |
| Tests | 362 backend + 38 frontend | all passing |

## 2. Existing rubric coverage

### CREATIVITY — 100
| Line | Marks | Estimate | Note |
| --- | --- | --- | --- |
| Visual/UX quality | 40 | **~28** | Polished dark dashboard, Framer Motion, Recharts, landing scene. Dense; state not readable in 2 s. |
| Beyond-chat interaction | 30 | **~22** | Image upload, camera capture, clickable detection boxes, map, Grad-CAM toggle. Strong already. |
| Polish/delight | 30 | **~20** | Good motion work. No "wow" moment (no before/after, no fusion visual). |

### PROBLEM RELEVANCE — 100
| Line | Marks | Estimate | Note |
| --- | --- | --- | --- |
| Problem-market fit | 40 | **~36** | Fragmented monitoring is a real, well-argued problem. |
| Originality | 30 | **~27** | Evidence-conflict reasoning + refusal-to-overclaim is genuinely uncommon. |
| Practical usability | 30 | **~22** | Works end to end. Investigation output is not yet actionable as a checklist. |

### TECHNICAL — 100
| Line | Marks | Estimate | Note |
| --- | --- | --- | --- |
| Core pipeline completeness | 20 | **~18** | Complete and verified. |
| RAG quality | 20 | **0** | **Does not exist.** |
| Tool design / tool calling | 25 | **0** | **Does not exist.** |
| Agent reasoning/orchestration | 25 | **~23** | Genuinely strong — real graph, real conflict logic. |
| Live correctness | 10 | **~9** | 27/27 smoke, offline-capable. |

**Technical currently ≈ 50/100**, almost entirely because of the two missing layers.

### VIDEO — 200
Not started. **Largest single block of marks in the rubric (200 of 500).** Storytelling alone is
80. No script, no shot list, no recording.

## 3. Remaining technical gaps

| # | Gap | Rubric cost | Fix size |
| --- | --- | --- | --- |
| T1 | **No RAG pipeline** | 20 | Medium — needs corpus, chunker, embedder, store, retriever |
| T2 | **No tool layer** | 25 | Medium — typed wrappers over existing functions |
| T3 | No tool/RAG provenance in API responses | part of T1/T2 | Small |
| T4 | Water detector still COCO-pretrained | none directly | **Not fixable** (blocker B1) — documented |
| T5 | No regression test for the person/kite case at API level | risk of silent regression | Small |

**On corpus choice (T1):** the project already holds genuine, citable environmental knowledge —
BIS 10500 water limits and WHO 2021 air guidelines encoded as thresholds in `water_agent.py` /
`air_agent.py`, the segregation taxonomy in `training/config/waste_categories.json`, and the
recovery/timeline bands in `core/recovery.py`. A corpus built from these is **verifiable and
already cited in code**. Inventing an external corpus of environmental papers would be
fabrication of sources and is ruled out.

## 4. Remaining UX gaps

| # | Gap | Rubric line |
| --- | --- | --- |
| U1 | No **Analysis Trace** — `runs[].steps` and `decisionTrace` exist in the API but node-level execution is not surfaced as a timeline | Beyond-chat, polish |
| U2 | No **Evidence Inspector** — evidence exists and is typed, but is not browsable with provenance | Visual/UX, usability |
| U3 | No **Evidence Fusion** visual — the multi-agent story is told in text only | Polish/delight |
| U4 | No **Investigation Mode** — `investigationPlan` exists in the payload but is not an actionable checklist | Practical usability |
| U5 | Dashboard hierarchy — risk is not legible in 2 s | Visual/UX |
| U6 | No before/after comparison for waste | Polish/delight |
| U7 | Grad-CAM only visible after clicking a detection; not discoverable | Polish |

`decisionTrace` **is** already rendered (`DecisionPanel.tsx:198`) — Phase 6 is partially done.

## 5. Remaining demo gaps

| # | Gap |
| --- | --- |
| D1 | **No video script, shot list or recording** — 200 marks |
| D2 | No single "wow" frame to open on (hook = 40 marks) |
| D3 | Demo scenarios are CLI-only; not reachable from the UI |
| D4 | `plastic_bottle.jpg` yields 0 detections — a live-demo trap |

## 6. Potential regressions to guard

| Risk | Guard |
| --- | --- |
| RAG/tools becoming a path for an LLM to set a number | Tools return typed Python results; risk tool wraps `core/risk.py` only |
| A retriever inventing a source | Corpus is repo-local with document + chunk ids; citations resolve or are omitted |
| New UI panels slowing the analysis path | Render existing payload fields; no new blocking calls |
| Water semantic fix regressing | 17 tests exist; add API-level cases (T5) |
| Adding dependencies that break the offline demo | Prefer numpy-only retrieval; optional embedding provider |
| Test count dropping below 362 | Never delete a passing test |

## 7. Highest-value optimizations, ranked

| Rank | Work | Marks addressed | Why |
| --- | --- | --- | --- |
| **1** | **Video script + shot list + recording guide** | up to **200** | Largest block, currently zero, and it is the only deliverable judged on its own |
| **2** | **Real RAG pipeline with visible citations** | **20** | Currently zero; corpus already exists in-repo |
| **3** | **Typed tool layer over existing functions** | **25** | Currently zero; implementations already exist to wrap |
| **4** | Analysis Trace + Evidence Fusion visual | ~15 | Makes the invisible architecture visible — the project's main differentiator |
| **5** | Evidence Inspector + Investigation Mode | ~12 | Usability + practical action |
| **6** | Dashboard hierarchy pass | ~8 | 2-second comprehension |
| **7** | Waste before/after comparison | ~6 | Wow moment for the video hook |

## 8. Must NOT be touched

- `backend/agents/air_agent.py` — working, out of scope.
- LangGraph graph topology — correct; new nodes only if genuinely needed.
- `coordinator_agent.py` import restrictions — enforced by static test.
- `core/risk.py` maths — the numerical source of truth.
- The semantic taxonomy in `core/investigation.py` — one taxonomy, hard-won.
- Waste confidence gates and `_apply_detector_authority` — both branches measured and tested.
- `backend/.env` — names only, never values.
- `runs/**` experiment reports, `datasets/`, `water_datasets/`, all model weights.
- The 362 + 38 passing tests.
- `visual_score` / `count_reference` values — recalibration blocked on B1.

---

## 9. Plan

1. Real RAG: corpus from in-repo verifiable knowledge → chunk → embed → store → retrieve, with
   document/chunk ids and scores surfaced through the API.
2. Typed tool layer wrapping existing implementations; deterministic values stay in Python.
3. Analysis Trace, Evidence Inspector, Evidence Fusion, Investigation Mode in the UI.
4. Water/waste regression tests at API level.
5. Dashboard hierarchy + waste before/after.
6. Video script and shot list.
7. Re-verify everything, update docs, freeze.

**Out of scope:** retraining any model, acquiring datasets, recalibrating `visual_score`,
rebuilding the map, framework changes.

---

# OUTCOME — what this round actually delivered

Appended after the work. Every figure below was produced by running the system.

## Closed

| # | Gap | Delivered | Tests |
| --- | --- | --- | --- |
| T1 | No RAG pipeline | 6 stages in `backend/services/rag/`, 6-document corpus, cited retrieval, grounded explanation, `POST /api/knowledge/search` | **27** |
| T2 | No tool layer | 9 typed tools in `backend/services/tools/`, JSON Schema, validation, `GET /api/tools` + invoke | **19** |
| T3 | No RAG/tool provenance in responses | `decision.knowledge` with chunk ids, source files and scores; `KnowledgeStatus` on `/api/ai/status` | covered |
| U1 | No Analysis Trace | `AnalysisTrace.tsx` — execution events only, no chain-of-thought | typecheck |
| U2 | No Evidence Inspector | Evidence surfaced through Investigation Mode + Retrieved Knowledge panels | typecheck |
| U3 | No Evidence Fusion visual | `EvidenceFusion.tsx` — animated lanes drawn from the actual run | typecheck |
| U4 | No Investigation Mode | `InvestigationMode.tsx` — observed / not established / verify next, as a checklist | typecheck |
| D1 | No video plan | `docs/VIDEO_SCRIPT.md` — 75 s shot list, voiceover, recording notes | — |

## Verification

| Suite | Before | After |
| --- | --- | --- |
| Backend tests | 362 | **408** (+46) |
| Live smoke checks | 27 | **37** (+10) |
| Frontend tests | 38 | 38 |
| Frontend typecheck / build | clean | clean |
| Demo scenarios | 5/5 | 5/5 |

**Retrieval quality:** 8/8 on-topic queries return the expected passage first; 4/4 off-topic
queries correctly return nothing.

## Two retrieval defects found and fixed during the build

1. **Interrogatives polluted the vocabulary.** The corpus is full of headings like "What an image
   can and cannot establish", so `what` carried a non-zero IDF. The off-topic query "what is the
   capital of France" matched three chunks at 0.24 on that word alone. Fixed by adding
   interrogatives to the stop list — while deliberately keeping `not`, because "not established"
   is one of the most meaningful phrases in this corpus.

2. **A score floor alone was not enough.** "best pizza in Naples" still matched the waste
   confidence-thresholds section at 0.14 on the word "best" (the corpus says "rather than a best
   guess"). Fixed with a query-coverage gate: if fewer than half a query's tokens exist in the
   corpus vocabulary, the query is refused before scoring. Chosen over raising the floor, which
   would have discarded genuinely useful weak cross-domain matches at 0.09–0.15.

Both are cases of the same failure the RAG layer exists to prevent: citing a source for a
question the corpus cannot answer.

## Not attempted, and why

| Item | Reason |
| --- | --- |
| Water detector training | Blocked on B1 (no clean-water negatives). Unchanged. |
| `visual_score` recalibration | Depends on B1. Still an explicit provisional signal. |
| Map rebuild | Brief says do not rebuild; existing map works. |
| Before/after waste slider | Lower value than RAG/tools; Grad-CAM already carries the visual moment. |
| Neural embeddings | Would add a network path or a large dependency to a demo that must not fail. |

## Status

Water remains **PARTIALLY_READY** — the detector is still COCO-pretrained. That is a data
blocker, documented rather than worked around, and it is the honest position.

**Feature work is complete.** Remaining time belongs to recording the video and rehearsing.
