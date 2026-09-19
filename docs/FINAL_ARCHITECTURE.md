# EcoSentinel AI — Final Architecture

Multi-agent environmental monitoring, evidence reasoning and risk assessment.

---

## 1. The problem

Environmental monitoring is fragmented. Air quality comes from one network, water quality from
another, waste from nobody in particular. Each is read alone, so nothing reconciles them — and
when two signals disagree, the disagreement is usually averaged away rather than reported.

That averaging is where overclaiming starts. A photograph of litter in a river becomes "the river
is contaminated". A clean-looking photograph becomes "the water is fine". Neither follows.

EcoSentinel treats each signal as **evidence with provenance**, reasons over the whole set, and
keeps three claims apart that are routinely conflated:

| | Meaning | Example |
| --- | --- | --- |
| **OBSERVED** | A model or sensor measured this | Turbidity 14 NTU; 3 litter objects in frame |
| **INFERRED** | Derived from observations | Water-quality concern, MODERATE |
| **NOT ESTABLISHED** | Nothing here supports this claim | Chemical contamination |

## 2. System flow

```
                              USER / LOCATION
                                     │
                          ┌──────────▼──────────┐
                          │ Geographic Context  │   Nominatim + Overpass (OSM)
                          │ CONTEXT ONLY        │   severity 0, confidence 0
                          └──────────┬──────────┘
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
        AIR AGENT              WATER AGENT            WASTE AGENT
     OpenAQ v3 / demo    sensors + vision + match   detector + classifier
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     ▼
                          STRUCTURED EVIDENCE
                  EnvironmentalEvidence[] — one flat, typed list
                                     │
                                     ▼
                           LANGGRAPH STATEGRAPH
        normalize → detect_problems → cross_signal → conflicts → sufficiency
                                     │
                     ┌───────────────┴───────────────┐
              insufficient                      sufficient
                     │                               │
           investigation_needed ──────────► decision_synthesis
                                                     │
                                     DETERMINISTIC RISK ENGINE
                                        core/risk.py — the score
                                                     │
                                          frame_investigation
                                                     │
                                            explain_decision
                                   Groq / OpenRouter — WORDS ONLY
                                                     │
                                                 FRONTEND
```

## 3. The rule that shapes everything

> **Vision and sensors produce evidence. The deterministic engine produces the number. The LLM
> produces the sentence. An LLM never sets a score.**

This is enforced structurally, not by convention:

- `backend/config.py` defines two **non-interchangeable** LLM roles. `FUNCTIONAL_AI_PROVIDER`
  output is validated against a Pydantic schema and enters as evidence, where the deterministic
  engine weighs it like any other signal. `EXPLAINABILITY_AI_PROVIDER` receives an
  **already-final** decision and can only put it into words.
- `backend/tests/conftest.py` carries a static test asserting `coordinator_agent.py` never imports
  `services`, `http`, `urllib`, `requests` or `httpx`. The Coordinator physically cannot reach a
  network or a model.
- With both providers set to `none` the entire pipeline still runs and every explanation falls
  back to deterministic template text.

## 4. The LangGraph graph

`backend/agents/langgraph_orchestrator.py` — a real `StateGraph`, not a wrapper over sequential
calls:

| Node | Does |
| --- | --- |
| `resolve_location` | Name or coordinates → one normalised `LocationContext` |
| `triage_environment` | Which specialists are worth running |
| `run_air` / `run_water` / `run_waste` | **Parallel fan-out**, each under its own timeout |
| `context_enrichment` | OSM features, in parallel with the specialists |
| `coordinate` | Fan-in; cross-signal risk from typed reports only |
| `normalize_evidence` | Three domains → one `EnvironmentalEvidence[]` |
| `detect_problems` | Evidence → the problems it supports |
| `cross_signal_reasoning` | Relationships between domains |
| `evaluate_conflicts` | Evidence pointing opposite ways, surfaced not averaged |
| `knowledge_retrieval` | Retrieves corpus passages for THIS analysis's evidence (see §9) |
| `check_data_sufficiency` | **Conditional edge** — enough to decide? |
| `investigation_needed` | Taken when evidence is insufficient |
| `decision_synthesis` | Deterministic risk, priority, investigation plan |
| `frame_investigation` | Per-detection reasoning over a clicked frame |
| `explain_decision` | LLM narration of a finished decision |

Concurrency is real: `runs` uses an `Annotated[List, operator.add]` reducer so the three parallel
branches each contribute without overwriting one another. `_run_node` wraps every specialist in
`asyncio.wait_for`, so a failure becomes a structured `AgentRun(status="failed")` and the graph
continues with the remaining evidence.

## 5. Agents

### Air Agent — `backend/agents/air_agent.py`
OpenAQ v3 nearby-station search, WHO 2021 guidelines, weighted PM2.5 / PM10 / NO₂ / O₃. Carries
the **only genuine trend signal in the system**: a 24-hour PM2.5 baseline. Every other domain
returns a single point in time, so their direction stays `unknown` rather than a fabricated
"stable". India NAQI is computed but explicitly labelled an estimate, since it is applied to
single readings rather than a 24-hour average.

### Water Agent — `backend/agents/water_agent.py`
Three **strictly separate** signals, which is the whole point of the design:

| Signal | Source | Can establish | Can never establish |
| --- | --- | --- | --- |
| Measurements | IoT → station → dataset → demo | pH, turbidity, temperature, TDS | what the surface looks like |
| `visual_pollution` | YOLO over a photo | visible surface litter | any chemistry |
| `dataset_match` | colour-histogram match | that a photo *looks like* labelled references | anything measured |

The visual signal is **escalation-only**:

```python
combined = clamp(quality_score + water_visual_weight * visual_score)
```

Not a weighted average — deliberately. Averaging would let a clean-looking photo pull down a risk
that measured chemistry had established. A river can be visually clear and still fail on pH.
**Visible pollution corroborates harm; its absence is not evidence of safety.**

`dataset_match` deliberately does **not** touch the score: measured leave-one-clip-out, the
matcher misreads clean water as contaminated most of the time, so letting it move a sensor-backed
number would corrupt it. It is carried as caveated evidence for a human.

### Waste Agent — `backend/services/waste/waste_pipeline.py`
Two stages that fail differently and are reported separately — the detector says *where*, the
classifier says *what*:

```
image → YOLO (TACO waste_detector.pt) → dedup (IoU 0.7) → crop (+6% pad, min 24px)
      → MobileNetV3-Small, 8 classes → confidence gate (0.60) → segregation → Grad-CAM
```

Four refusals are built in:
1. Below 0.60 → `uncertain` / `needs_review`, top guess kept as `candidate` only.
2. Crop under 24 px → `uncertain`; too few pixels to do anything but guess.
3. `NEVER_WASTE_CLASSES` — the classifier has 8 waste classes and no way to answer "not waste";
   its softmax must sum to 1 across them. Measured on TACO it called a `dog` wood_waste at 84%.
   Confidence cannot catch this, because the model was never given the option of abstaining.
4. Detector authority requires the detector to clear the same 0.60 bar before a label is
   *asserted*. Below it the label is a candidate and segregation is withheld.

`environmental_note` has its own field: "plastic bags are persistent" is a configured policy
statement from `training/config/waste_categories.json`, not something the network predicted.

## 6. Explainable AI

**Waste — Grad-CAM** (`backend/services/waste/waste_xai.py`). The same MobileNetV3 instance that
produced the prediction, hooked at `features[-1]` (576 channels, 7×7), backpropagating the
predicted **logit** — not the softmax, whose denominator couples every class. Opt-in via
`POST /api/waste/segregate?explain=true`.

Two properties are asserted by test: the explained class and confidence **equal** what `classify`
reported (otherwise the heatmap explains a different computation), and the map **changes with the
target class** (a saliency map that does not is an edge detector, not an explanation).

When gradients cannot be computed the response says `available: false` with a reason and **no
image**. There is deliberately no fallback picture.

**Water — frame investigation** (`backend/core/investigation.py`): per-detection reasoning where
each `IMG-DET-00N` evidence id resolves to the box the model actually drew.

## 7. Geographic context is not evidence

OSM features enter at `severity=0.0, confidence=0.0`. A mapped factory is a polygon a contributor
drew — it is not an emission, and it must never raise a risk score. It exists so reasoning can say
"industrial activity is mapped nearby" *alongside* a measurement, never as a cause.

## 8. Layering

```
main.py            HTTP, validation, error mapping
agents/            orchestration + the three specialists + coordinator
core/              risk, evidence, decision, investigation, recovery   ← no service imports
services/          providers, models, external APIs
schemas.py         the API contract
```

`core/` never imports `services/`. The semantic taxonomy
(`is_pollution_class` / `is_never_waste` / `semantic_category_for`) lives in `core/investigation.py`
and is imported by everything that needs it — there is exactly one, because there were once
effectively two, and the same river photo got two different answers from two endpoints.


## 9. Retrieval-Augmented Generation

`backend/services/rag/` — a real pipeline, one module per stage:

```
backend/knowledge/*.md      corpus — knowledge already encoded in this codebase
    │
    ▼ loader.py             load documents + front matter (title, domain, source file)
    ▼ chunker.py            heading-aligned chunks, stable `document#section` ids
    ▼ embeddings.py         TF-IDF sparse lexical vectors, numpy only
    ▼ store.py              in-memory vector store, cosine top-k, relevance floor
    ▼ retriever.py          deterministic query construction from structured evidence
    ▼                       grounded context, cited by chunk id, rendered in the UI
```

**The corpus is deliberately restricted** to knowledge this project can stand behind: thresholds
it already encodes (`water_agent.py` PARAMETERS, `air_agent.py` POLLUTANTS), policies it already
documents (`waste_categories.json`, `core/recovery.py`), and metrics it already measured
(`runs/evaluation/`). Every document names the repository file it came from, so every citation
resolves to something a reader can open. Nothing was fetched from the web. A citation nobody can
check is worse than none, because it makes an unverified claim look verified.

**Why TF-IDF rather than a neural embedder.** The demo must not be able to fail, the corpus is
seven short technical documents in a fixed vocabulary (the regime where lexical retrieval is
strongest), retrieval is deterministic so the on-screen panel is reproducible, and every score
decomposes into terms a reader can argue with. The API names the technique
(`tfidf-sparse-lexical`) rather than implying a semantic model is running.

**Two honesty properties, both enforced in `store.py` and both tested:**

1. **Relevance floor** (cosine 0.08) — a weak chunk is not returned at all.
2. **Query coverage gate** (50%) — if fewer than half a query's tokens exist in the corpus
   vocabulary, the query is refused outright. A score floor alone was not enough: *"best pizza in
   Naples"* matched the waste confidence-thresholds section at 0.14 on the word *"best"* (the
   corpus says "rather than a best guess") and was returned as a cited source.

**Retrieved knowledge is CONTEXT, not evidence.** It never enters the evidence list, carries no
severity, and cannot move a risk score — the same rule geographic context follows. It is attached
to the decision *after* `synthesize()` has run, so there is no code path by which a retrieved
passage can influence a number. The explanation prompt receives the passages as clearly-separated
reference material with an instruction to cite by chunk id and not to exceed them.

## 10. Tool layer

`backend/services/tools/` — nine typed, validated, individually callable operations.

**The boundary this layer exists to enforce:**

> A model may decide **which** tool to call and **with what arguments**.
> A tool decides **what the answer is**.

| Tool | Category | Wraps |
| --- | --- | --- |
| `get_air_quality_data` | air | `AirQualityAgent` + OpenAQ provider |
| `get_water_sensor_data` | water | `WaterQualityAgent` + sensor resolver |
| `analyze_water_image` | water | `water_vision_service.build_report` |
| `analyze_waste_image` | waste | `waste_pipeline.analyze_waste` (+ Grad-CAM) |
| `get_waste_segregation_guidance` | waste | `waste_categories.json` + `core/recovery.py` |
| `get_location_context` | location | Nominatim + Overpass |
| `search_environmental_knowledge` | knowledge | the RAG retriever |
| `calculate_environmental_risk` | decision | **`core/risk.py`** |
| `generate_investigation_plan` | decision | the full LangGraph run |

Every tool is a thin wrapper over an implementation that already existed and is already tested —
a tool layer that re-implements the pipeline is a second pipeline that can disagree with the
first.

`calculate_environmental_risk` is the clearest statement of the rule: it runs the same module the
decision engine runs and returns its number. A model asked to "estimate the risk" would produce
something plausible with no provenance, and nothing downstream could tell the difference.

Each tool carries a Pydantic input and output model, validates before executing, and returns a
structured `ToolResult`. Three failure modes are kept distinct because they need different
responses: `UNKNOWN_TOOL` (routing bug), `INVALID_ARGUMENTS` (caller bug), `TOOL_FAILED` (genuine
unavailability). Internal exception text never reaches the caller.

Exposed at `GET /api/tools` (JSON Schema per tool, the OpenAI/Anthropic function-calling shape)
and `POST /api/tools/{name}/invoke`, which always returns 200 with a structured result — a caller
running several tools needs to see which failed and why, not a transport error that loses the
detail.
