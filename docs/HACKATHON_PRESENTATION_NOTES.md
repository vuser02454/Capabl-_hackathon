# Presentation Notes

Written for whoever is presenting. Claims here are all defensible against `runs/` and the code.

---

## The one-sentence pitch

> EcoSentinel combines air, water and waste signals into a single evidence-driven decision — and
> it knows the difference between what it observed, what it inferred, and what it has not
> established.

## Why this is not "three AI models in a dashboard"

Anyone can wire three models to three cards. The architecture that matters is what happens
**after** the models speak:

```
MULTI-MODAL EVIDENCE  +  MULTI-AGENT ANALYSIS  +  LANGGRAPH EVIDENCE REASONING
                      +  DETERMINISTIC RISK ENGINE  +  EXPLAINABLE DECISION
```

The load-bearing claim: **an LLM never sets a number.** Vision and sensors produce evidence, a
deterministic engine produces the score, and the LLM only puts the finished decision into words.

That is enforced structurally, which is the part worth saying:

- Two **non-interchangeable** LLM roles in config — one whose output is schema-validated and
  enters as evidence, one that receives an already-final decision.
- A **static test** asserts the Coordinator never imports `services`, `http`, `urllib`, `requests`
  or `httpx`. It physically cannot reach a model or a network.
- With both LLM providers off, the whole pipeline still runs and explanations fall back to
  deterministic text.

## The demo moment: evidence conflict

This is the slide to slow down on.

> Vision sees litter. Sensors show normal chemistry.
>
> A naive system picks one and asserts it. EcoSentinel reports:
>
> **OBSERVED** — visible floating litter, 88% confidence
> **NOT ESTABLISHED** — chemical contamination
> **CONFLICT** — measurements are within guideline limits while visual detections are elevated;
> neither alone settles the question
> **RECOMMENDED** — additional water-quality verification

And the converse, which matters just as much:

> No visible litter + abnormal sensor readings → *sensor-based water-quality concern*.
> **Never "the water is clean."** Absence of visible litter is not evidence of safety.

That asymmetry is in the code, not the pitch: the visual signal is **escalation-only**
(`combined = clamp(quality + weight × visual)`), deliberately not an average, so a clean-looking
photo can never pull down a risk that measured chemistry established.

## A bug worth presenting

Judges respond to engineering honesty better than to a flawless story. This one is concrete:

> Our water detector is COCO-pretrained. On a river photo it found six objects: two people and
> four kites. All six counted as "visible pollution" and pushed water risk from 0.55 to 0.63.
> Worse, two of our own endpoints disagreed — `scan-frame` said zero pollution objects on the same
> image, because it filtered by a taxonomy the risk path never called.
>
> We now have one taxonomy in `core/investigation.py`, used everywhere. Raw detector class and
> semantic interpretation are separate fields, so the detector still reports what it saw and the
> system decides what that means. The endpoints agree, and there is a test for each case.

It shows the failure, the root cause (a duplicated taxonomy), the fix, and the regression guard.

## Grad-CAM — real attribution

Same MobileNetV3 instance that made the prediction, hooked at `features[-1]`, backpropagating the
predicted **logit** (not the softmax — its denominator couples every class).

Two properties are **asserted by test**:
1. The explained class and confidence equal what `classify` reported — otherwise the heatmap
   explains a different computation.
2. The map changes with the target class — a saliency map that does not is an edge detector.

When gradients cannot be computed: `available: false`, a reason, and **no image**. There is
deliberately no fallback picture.

## Numbers you can defend

| Claim | Figure | Source |
| --- | --- | --- |
| Waste classifier macro F1 | **91.1%** (accuracy 93.4%, 1,200 held-out images) | `runs/evaluation/classification_report.json` |
| Detector localisation, held-out TACO | **53.3%** vs 9.3% for COCO | `runs/waste_detection/AB_TEST_REPORT.md` |
| Detector-vs-classifier disagreements | detector right 22, classifier 6 (of 42) | same |
| RGB/BGR bug cost | 46% of detections (62 → 114) | same |
| Backend tests | **408 passing** | `pytest backend/tests` |
| Smoke checks | **37 passing** | `backend/scripts/smoke_test.py` |
| Retrieval accuracy | 8/8 on-topic correct, 4/4 off-topic declined | `test_rag.py` |
| Tools | 9 typed, JSON Schema, validated | `GET /api/tools` |
| TUD-GV split | 1,057 / 298 / 146, zero leakage | `TUDGV_SPLIT_MANIFEST.json` |
| Licences | IWHR Apache 2.0, TUD-GV CC BY 4.0 — verified via Figshare/Zenodo APIs | `LICENSE_PROVENANCE_REPORT.md` |

## DO NOT CLAIM

Read this list before going on stage.

1. **Do not claim the system detects chemical contamination from an image.** It cannot. It detects
   visible surface litter.
2. **Do not present 93.4% as pipeline accuracy.** That is the *classifier* on cropped
   single-object images. End-to-end on held-out TACO is **7.5%**.
3. **Do not hide the 7.5%.** If asked, explain it: TACO is small litter in the wild, and the
   dominant error is the classifier *abstaining* (41 of 107), not being wrong. The system
   abstains far more often than it errs — by design.
4. **Do not claim a trained water-litter detector.** The water model is COCO-pretrained YOLOv8n.
   TUD-GV is prepared but **nothing has been trained on it**.
5. **Do not claim `visual_score` is calibrated.** `count_reference = 20` is a convention. Up to
   8.7× swing between detector families.
6. **Do not claim false-positive rates on clean water.** No clean-water negative set exists
   (blocker B1). This is unmeasured.
7. **Do not present demo data as measurements.** It is seeded and marked `isMock` everywhere.
8. **Do not claim reports reach an authority.** They are logged locally; forwarding happens only
   when a destination is configured, and the API says plainly when nothing was transmitted.
9. **Do not claim FloW is licensed for use.** Rights are unresolved and it is not used.
10. **Do not call Grad-CAM pixel-level.** It is 7×7, upsampled.

## RAG and tools — how to describe them

**RAG.** Six stages, one module each: loader → chunker → TF-IDF embeddings → vector store →
retriever → grounded generation. The corpus is this project's own documented standards and
measured results, and every document names the repository file it came from, so **every citation
resolves to a file a judge can open**. Two honesty gates: a relevance floor, and a query-coverage
gate that refuses a query when most of its words are outside the corpus vocabulary. Ask it about
pizza and it returns nothing rather than a citation it cannot support.

Say **"sparse lexical embeddings"**, not "semantic embeddings". It is TF-IDF, chosen because the
demo must not be able to fail, the retrieval is deterministic and therefore reproducible on
screen, and every score decomposes into terms you can argue with. The API names the technique in
its own response.

**Tools.** Nine typed tools, each with a Pydantic input/output model, validation before execution
and distinct error codes. The line worth saying out loud:

> A model may decide which tool to call and with what arguments. The tool decides what the answer
> is.

`calculate_environmental_risk` runs `core/risk.py` — the same module the decision engine runs. A
model asked to estimate a risk would return something plausible with no provenance, and nothing
downstream could tell the difference.

## Likely questions

**"Why LangGraph and not just function calls?"**
Real parallel fan-out for the three specialists with per-node timeout isolation, an additive state
reducer so parallel branches do not overwrite each other, and a **conditional edge** on data
sufficiency that routes to an investigation plan instead of deciding. A failed specialist becomes
a typed `AgentRun(status="failed")` and the graph continues on the remaining evidence.

**"How do you stop the LLM hallucinating a risk score?"**
It never receives the inputs to one. It gets a finished decision object. And the Coordinator that
computes the score cannot import an HTTP client — there is a test for that.

**"Your water detector isn't trained on water. Isn't that fatal?"**
It is the biggest gap, and it is documented. It means low recall on real floating litter. What it
no longer means is *false* pollution: non-litter classes are excluded from the score, both
endpoints agree, and the panel shows litter and non-litter counts separately. We have a
leakage-safe TUD-GV split ready; we did not train because the honest blocker is missing
clean-water negatives, and we would rather ship a stated limitation than an unvalidated model.

**"Is that really RAG, or just a lookup?"**
It is the full pipeline — documents are loaded, chunked on headings, embedded into vectors,
stored, retrieved by cosine top-k, and injected into the explanation prompt as cited context,
with the citation rendered in the UI. What it is *not* is a neural embedder, and the response
says so rather than implying one. For seven technical documents in a fixed vocabulary, lexical
retrieval measurably wins — 8 of 8 on-topic queries return the right passage first.

**"Couldn't the LLM just make up the risk score?"**
It never receives the inputs to one, and the Coordinator that computes it cannot import an HTTP
client — there is a static test for that. The tool layer makes the same guarantee explicit: the
risk tool runs Python and returns its number.

**"What happens if your APIs are down?"**
The demo does not depend on them. Demo mode is seeded fixtures; both LLM roles can be `none` and
every explanation falls back to deterministic text.

## Closing line

> The hard part of environmental AI is not detecting things. It is being honest about what a
> detection means. EcoSentinel separates observation from inference from verification-required —
> and when its signals disagree, it says so instead of averaging them into a confident number.
