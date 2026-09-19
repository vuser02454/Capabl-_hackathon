# Final Runtime Verification

**Date:** 2026-09-19 · Against the running stack: backend `:8000`, frontend `:5173`.

---

## 1. Suites

| Suite | Result |
| --- | --- |
| Backend tests | **426 passed**, 0 failed |
| Frontend tests | **38 passed** |
| Frontend typecheck | exit 0 |
| Frontend production build | succeeded |
| Live smoke checks | **37 passed**, 0 failed |
| Demo scenarios | **5/5 passed** |

Backend tests: 408 → **426** (+18: chat agent ×15, demo intents ×3).

## 2. Water — reproduction and A/B

Detailed in `WATER_CURRENT_FAILURE.md` and `WATER_MODEL_COMPARISON.md`.

| Check | Result |
| --- | --- |
| Failure reproduced on the exact image | **Yes** — `image copy 3.png`, 0 detections at 0.25 |
| Bird behaviour isolated | **Yes** — only `bird` (0.089) / `kite` (0.015) below threshold; **never `bottle`** |
| Root cause | **Domain mismatch**, not threshold, taxonomy, decoder or prompt |
| Candidate trained | Yes — TUD-GV, session-level split, 1,057/298/146 |
| Candidate on the exact image | **9 litter detections**, max confidence 0.81 |
| Candidate validation | P 0.887 · R 0.840 · **mAP50 0.936** · mAP50-95 0.668 |
| False positives measured | **Yes — 6 detections on a visibly clean restored river** |
| Promoted to default | **No** — available by config, limitation documented |
| Non-pollution objects still transparent | Yes — reported, categorised, contribute 0 |

## 3. Chat — the §37 demo sequence, verified live

| Question | Intent | Tools | Result |
| --- | --- | --- | --- |
| "Why is the current water risk high?" | `analysis` | `get_current_analysis`, `get_retrieved_sources` | 3 evidence-supported reasons, 10 evidence items, 3 passages |
| "What should I verify next?" | `analysis` | same | Investigation plan, most important first, with what is missing and who supplies it |
| "Show me the source." | `analysis` | same | The 3 passages that grounded **this** decision, with chunk ids, relevance and source files |

Two defects were found and fixed while running this sequence: *"what should I verify next"* and
*"show me the source"* both fell through to a generic primary-concern summary, answering a
different question convincingly. Both now have their own intents, and three tests hold the line.

### Routing, verified live

| Message | Route | Tool | Outcome |
| --- | --- | --- | --- |
| "Search the knowledge base for what turbidity BIS permissible limit means" | `functional` | `search_environmental_knowledge` | Cited `water_quality_standards#turbidity`; answered **5 NTU** from the corpus |
| "Get the water sensor data for Mumbai" | `functional` | `get_water_sensor_data` | Mithi River · Kurla, pH 7.6, turbidity 19.0 NTU, HIGH |
| "What is eutrophication?" | `general` | — | Secondary LLM (Groq); no tools, no citations, labelled as general knowledge |

## 4. Architecture invariants

| Invariant | Held |
| --- | --- |
| Gemini is not a vision model | **Yes** — no image path reaches it; YOLO remains the only detector |
| Gemini does not calculate risk | **Yes** — `calculate_environmental_risk` runs `core/risk.py`; tested |
| Tools are authoritative | **Yes** — the explain prompt forbids changing any number; results returned unmodified |
| Only allow-listed tools execute | **Yes** — hallucinated names are refused before the registry; tested |
| Risk engine is deterministic | **Yes** — 423 → 426 tests including the static Coordinator import assertion |
| RAG retrieves, does not generate | **Yes** — retrieved passages attached after synthesis; cannot reach a score |
| Retrieval declines out-of-corpus questions | **Yes** — coverage gate; tested on 4 off-topic queries |

## 5. Not verified — stated plainly

**Browser end-to-end was NOT performed.** No browser automation is available in this environment
(no Playwright, Puppeteer, Selenium or driver installed, and no browser tool). The brief requires
it in §22, §43 and §47.

What was verified instead, and what that does and does not cover:

| Verified | Not verified |
| --- | --- |
| Backend serves every endpoint (37 live checks) | That the rendered page looks correct |
| Frontend dev server serves, and proxies `/api` to the backend (HTTP 200) | Click-through of the Water upload flow |
| Frontend typechecks and builds for production | Click-through of the chat panel |
| The exact JSON shape each component consumes | Visual layout, spacing, responsiveness |
| Every chat route, through the real API | Any browser console error |

The new UI components (`ChatPanel`, `EvidenceFusion`, `AnalysisTrace`,
`RetrievedKnowledgePanel`, `InvestigationMode`) compile and consume verified API shapes, but
**have not been seen rendered**. They should be opened in a browser before the demo.

## 6. Training status at time of writing

The provisional detector was still training when this was written: 7 of 60 epochs, best
validation mAP50 **0.943**. All A/B figures above use the best checkpoint at that point. Final
held-out TEST metrics land in `runs/water/litter_detector/test_metrics.json` when it completes;
the conclusion (strong in-domain, over-fires on clean water) is not expected to change, and the
document will need one update with the final numbers.
