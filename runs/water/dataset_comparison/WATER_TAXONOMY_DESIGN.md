# Water Vision — taxonomy and label-contract design

Design only. **Nothing was trained, merged, converted or deployed; no production code was
modified.** Companion documents: `LABEL_CONTRACTS.md`, `LABEL_CONTRADICTIONS.md`,
`DATASET_ROLES.md`.

---

## 1. Dataset contracts

| Dataset | Images / boxes | Class | Positive | Negative | Scope |
| --- | --- | --- | --- | --- | --- |
| IWHR | 3,000 / 23,689 | `floater` | Salient object **on or beside** water — manufactured **and** natural, including litter on **dry rock** | **UNKNOWN**, inconsistent | Broadest |
| FloW-Img | 1,200 / 3,248 | `bottle` | Rigid floating drink container | **UNKNOWN** — non-bottle litter is *out of scope*, not asserted negative | Narrowest |
| TUD-GV | 1,501 / 8,181 | `litter` | Any **anthropogenic** object **floating** on the surface | **UNKNOWN**, but natural material consistently excluded | Middle |

**No dataset ships annotation guidelines.** Every negative definition above is inferred from
observed behaviour on a sample. This single fact governs the whole design: absence of a box is not
evidence of absence in any of the three.

**All three have zero empty frames**, so none can measure a false-positive rate on clean water.

---

## 2. Semantic overlap

| Concept | IWHR | FloW | TUD-GV |
| --- | --- | --- | --- |
| floater (generic) | **SUPPORTED** | NOT_SUPPORTED | PARTIALLY_SUPPORTED |
| bottle | PARTIALLY_SUPPORTED | **SUPPORTED** | PARTIALLY_SUPPORTED |
| litter (anthropogenic floating) | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | **SUPPORTED** |
| natural material | **SUPPORTED** (as positive) | NOT_SUPPORTED | **NOT_SUPPORTED** (excluded) |
| plastic | NOT_SUPPORTED | NOT_SUPPORTED | NOT_SUPPORTED |
| bag | PARTIALLY_SUPPORTED | NOT_SUPPORTED | PARTIALLY_SUPPORTED |
| container | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED |
| foam | PARTIALLY_SUPPORTED | NOT_SUPPORTED | PARTIALLY_SUPPORTED |
| other anthropogenic litter | PARTIALLY_SUPPORTED | NOT_SUPPORTED | **SUPPORTED** |

The `plastic` row is empty of support in all three columns. **Material is not trainable from this
data.**

*PARTIALLY_SUPPORTED* means the object is inside the positive set but **not separable** from it.

---

## 3. Contradictions

| ID | Contradiction | Severity | Remedy |
| --- | --- | --- | --- |
| C1 | Natural material: IWHR positive / TUD-GV background | **UNSAFE** | SEPARATE_MODEL or RELABELLING |
| C2 | Non-bottle litter: TUD-GV positive / FloW background | **UNSAFE** | MASKING or SEPARATE_MODEL |
| C3 | Bottle named three ways | **SAFE** (single-class) | RELABELLING only if multi-class |
| C4 | Litter on dry rock: IWHR positive | **UNSAFE** | RELABELLING or SEPARATE_MODEL |
| C5 | IWHR annotation omission | **UNSAFE** as negatives | MASKING for evaluation |
| C6 | No negative frames anywhere | **UNSAFE** for FP claims | REQUIRES_MORE_DATA |
| C7 | FloW aspect distortion (640x640 stretch) | REQUIRES_MASKING of shape stats | Exclude from shape priors |

**C2 is the one most likely to be underestimated**: FloW frames look like clean litter supervision
and are silently dense *negative* supervision for bags, foam and wrappers.

---

## 4. Dataset roles

| Dataset | Role | Not |
| --- | --- | --- |
| **TUD-GV** | **A — detector training** (generic floating litter) | not C, not E |
| **FloW-Img** | **B — specialist bottle detector**, D — bottle recall | **not A** for generic litter |
| **IWHR** | **D — evaluation-only (recall)**, F — domain adaptation | **not A** without relabelling |

No dataset serves role C (no material field) or role E (no empty frames). None is unused.

---

## 5. Architecture options

Evidence and trade-offs. No subjective ranking is given.

### Option A — one unified YOLO detector over all three

| Dimension | Assessment |
| --- | --- |
| Label consistency | **Fails.** C1, C2 and C4 put opposed gradients on identical visual content |
| False-positive risk | **High.** Inherits IWHR's natural-material and dry-rock positives — fires on algae and bank litter |
| False-negative risk | Moderate. FloW's background-supervised bags suppress bag recall |
| Dataset compatibility | **Lowest.** Requires C1, C2, C4 all resolved first |
| Inference cost | **Lowest** — one model, one pass (~19 ms measured for yolov8n on M5/MPS) |
| Maintainability | High — one artifact, one `data.yaml` |
| Explainability | **Poor.** A single class merging three contracts cannot be described honestly |
| LangGraph | Simplest wiring; the honesty problem moves downstream into the narrative |
| Live feed | Best latency |

### Option B — generic floating-object detector + material/object classifier

| Dimension | Assessment |
| --- | --- |
| Label consistency | Detector stage consistent; **classifier stage is untrainable** — no material field in any dataset |
| False-positive risk | Moderate at detector; classifier would have to abstain constantly |
| False-negative risk | Moderate |
| Dataset compatibility | **Blocked.** Requires material labels that do not exist |
| Inference cost | Detector + N crops — the waste pipeline measures this as the dominant cost |
| Maintainability | Two artifacts, one preprocessing contract shared — the waste pipeline already shows this drifting is expensive |
| Explainability | Good *if* the classifier can abstain |
| LangGraph | Fits the existing evidence model well |
| Live feed | Poorer — per-crop classification per frame |
| **Precedent** | The waste pipeline measured exactly this: detector localisation rose 5.7x but end-to-end correctness only 2.7x, because the classifier **refused 41 of 57 correctly localised crops**. The bottleneck moved from detection to classification rather than disappearing |

### Option C — two-stage: floating-object/litter detector → object classifier

Structurally similar to B; differs in that stage 1 is trained on TUD-GV's *anthropogenic floating*
contract rather than a generic salient-object contract.

| Dimension | Assessment |
| --- | --- |
| Label consistency | **Best available for stage 1** — TUD-GV alone is self-consistent |
| False-positive risk | Lower than A: natural material is excluded by TUD-GV's contract |
| False-negative risk | **Higher on unseen domains.** TUD-GV is one fixed overhead viewpoint, no sky, no boats, no people |
| Dataset compatibility | Stage 1 trainable today; **stage 2 remains untrainable** (no material labels) |
| Inference cost | As B when stage 2 exists; as A while it does not |
| Maintainability | Good — stage 2 can be added later without retraining stage 1 |
| Explainability | **Best.** "Floating litter detected" is exactly what TUD-GV's contract supports |
| LangGraph | Clean: stage 1 output is already the evidence shape |
| Live feed | Good while stage 2 is absent |

### Option D — separate specialist detectors + evidence fusion

| Dimension | Assessment |
| --- | --- |
| Label consistency | **Highest.** Each model trained only on its own contract; no contradiction ever arises |
| False-positive risk | **Compounded** — three models, three independent FP sources, none measurable (C6) |
| False-negative risk | Lowest per-specialist |
| Dataset compatibility | **Total** — uses all three as-is, requires no relabelling |
| Inference cost | **Highest** — 3x detector passes (~60 ms vs ~20 ms) |
| Maintainability | **Lowest** — three weights, three thresholds, three drift surfaces |
| Explainability | Good per model; **fusion rules become the hard part** to justify |
| LangGraph | Requires new conflict rules for disagreeing specialists — the graph already has `evaluate_conflicts`, which is the right home |
| Live feed | Poorest latency |
| **Precedent** | The waste A/B found detector and classifier disagreed 42 times on 107 objects, with the detector right 22 and the classifier 6. Fusion rules matter more than either model |

### What the evidence does and does not settle

- **A is not available today** without resolving C1, C2 and C4 — that is relabelling work, not a
  configuration choice.
- **B and C both stall at stage 2** for the same reason: no material labels exist anywhere.
- **C's stage 1 is the only stage trainable from existing data without relabelling.**
- **D is the only option that uses all three datasets as-is**, at triple inference cost and with
  fusion rules that would themselves need evidence to justify.

---

## 6. Recommended structure, from the evidence

**Stage 1 of Option C, trained on TUD-GV alone, with FloW as a role-B specialist held in reserve.**

The reasoning is entirely contract-driven:

1. TUD-GV is the **only** dataset whose contract matches what EcoSentinel wants to claim —
   *visible anthropogenic floating litter*.
2. It is mechanically the cleanest (0 real defects) and has explicit session ids for a leakage-safe
   split.
3. IWHR and FloW stay in evaluation and specialist roles, so no contradiction enters training.
4. Stage 2 is **deferred, not designed away**. It cannot be built until material labels exist.

The honest limitation: TUD-GV is one fixed overhead viewpoint with no sky, buildings, boats or
people. A detector trained on it alone will be **narrow**, and IWHR's surveillance groups are the
right instrument for measuring how narrow — as recall-only evaluation (C5).

---

## 7. What must NOT be merged

1. **IWHR's natural-material boxes with TUD-GV** (C1) — opposed supervision.
2. **FloW frames into generic-litter training** (C2) — silently supervises bags as background.
3. **IWHR's dry-rock litter into a floating-litter detector** (C4) — a detector that fires on
   shoreline litter is not measuring floating density, which is what `visual_score` assumes.
4. **Class names into a multi-class head** (C3) — `bottle`/`litter`/`floater` are not mutually
   exclusive categories; they are three contracts over overlapping object sets.
5. **FloW shape statistics with the other two** (C7) — stretch-resized geometry.
6. **Any unboxed region, from any of the three, used as a negative** — no dataset documents its
   negatives, and none has empty frames.

---

## 8. Proposed intermediate evidence schema

**Design only — no production schema was modified.** `backend/schemas.py` is untouched.

```jsonc
{
  "object_type":        "floating_object",   // what the MODEL emitted, verbatim
  "semantic_category":  "anthropogenic_litter",
  "detector_class_raw": "litter",            // the weights' own class string, never rewritten
  "confidence":          0.74,
  "bbox":               [x1, y1, x2, y2],
  "frame_width":         1920,
  "frame_height":        1080,
  "source_dataset":     "TUD-GV",            // contract this model was trained under
  "model":              "water-litter-v1",   // derived from the weights file, never asserted
  "evidence_type":      "vision",
  "material_confidence": null,               // ALWAYS null until material labels exist
  "material_claim":      null,
  "requires_review":     false,
  "contract_note":      "anthropogenic floating litter; natural material excluded by training contract"
}
```

### Rules the schema encodes

- **`semantic_category` is constrained** to the vocabulary in §9 and may never be set to a material.
- **`material_confidence` and `material_claim` are permanently `null`** under every architecture
  trainable from current data. They exist so that a future material stage has somewhere to write,
  and so that their emptiness is *visible* rather than implied.
- **`detector_class_raw` is kept verbatim and separately** from `semantic_category`. This is not
  redundancy — see the integration hazard below.
- **`source_dataset` travels with every detection**, so a claim can always be traced to the
  contract that licenses it.
- **`requires_review`** carries forward the waste pipeline's discipline: below-threshold results are
  `uncertain`, not a best guess.

### A verified integration hazard this schema exists to prevent

`core/investigation.py::is_pollution_class` matches class names against substring hints. Tested
directly against the live code:

| Class name | `is_pollution_class` |
| --- | --- |
| `floater` | **False** |
| `litter` | True |
| `bottle` | True |
| `floating_litter` | True |

**A detector emitting IWHR's raw class name `floater` would be invisible to the entire
frame-investigation path** — `build_actions`, `build_escalation_risks` and the narrative all filter
on `is_pollution_class`, so the system would report "No supported visible pollution objects were
detected" while the model had detected objects. Keeping `detector_class_raw` separate from
`semantic_category`, and mapping explicitly between them, is what prevents a weights change from
silently switching off downstream reasoning.

Note also that the Water Agent's `score_detections` counts **every** detection with no
pollution filter (`water_vision_service.py:370`), while the frame-investigation path filters. The
two paths disagree today, and any new detector inherits that disagreement.

---

## 9. Water Agent semantics — six concepts that must not collapse

| Concept | Establishable by vision? | By which evidence |
| --- | --- | --- |
| `VISIBLE_FLOATING_OBJECT` | **Yes** | Detector trained on any of the three contracts |
| `VISIBLE_ANTHROPOGENIC_LITTER` | **Yes** | Detector trained on TUD-GV's contract only |
| `VISIBLE_BOTTLE` | **Yes** | FloW specialist only |
| `VISIBLE_NATURAL_MATERIAL` | **No** | No dataset labels it *as* natural; IWHR merges it into `floater` |
| `VISIBLE_SURFACE_ANOMALY` | Partially | Would include glare and ripple — **no dataset separates these from litter**, and TUD-GV's glare visually resembles pale litter |
| `CHEMICAL_CONTAMINATION` | **NEVER** | Requires sensor or laboratory evidence. No vision model, on any of these datasets, can establish it |

The existing Water Agent already enforces the last row structurally: `measurements` come from
sensors, `visual_pollution` from vision, and the agent "never lets it populate those fields". **That
separation must survive any detector change.**

Floating debris is not chemical contamination. A frame full of litter and a frame of chemically
contaminated clear water are, to a detector, the same and opposite respectively.

---

## 10. LangGraph integration design

**Design only — `langgraph_orchestrator.py` was not modified.**

```
Water image
  → detector (injected; build_report(detector, ...))
  → structured evidence records  (§8 schema, one per detection)
  → EVIDENCE VALIDATION      reject malformed/out-of-frame boxes; never repair
  → OBJECT-LEVEL REASONING   count, density, size distribution — deterministic
  → normalize_evidence       existing node; severity/confidence from the specialist
  → cross_signal_reasoning   existing node
  → evaluate_conflicts       existing node; new rule for specialist disagreement
  → check_data_sufficiency   existing conditional edge
  → deterministic risk engine (core/risk.py — unchanged)
  → explain_decision         existing node
```

### Rules

1. **LangGraph never invents a detection.** Nodes may count, group, filter and withhold; they may
   not add a box. The existing graph already honours this — the Coordinator sees typed reports
   only.
2. **No node overrides raw model evidence without an explicit, named evidence rule.** Any
   suppression must record *which rule* fired, in the decision trace, so it is auditable rather
   than merely applied.
3. **Vision escalates only.** The current blend is
   `score = clamp(quality_score + water_visual_weight * visual_score)` with
   `water_visual_weight` defaulting to **0.25** — verified in `water_agent.py:199-200` and
   `config.py:105`. Visible litter is corroborating evidence of harm; **its absence is not evidence
   of safety**, so the term must never be able to reduce a sensor-derived score.
4. **Vision may never write `ph`, `turbidity`, `temperature` or `tds`.**
5. **`source_dataset` and the contract note travel into the explanation**, so a narrative can say
   what the model was trained to see — and, by omission, what it was not.

### The scoring hazard a detector swap introduces

`visual_score = clamp(len(detections) / water_visual_count_reference)` with the reference
defaulting to **20** (`config.py:107`). Object density differs sharply across these datasets —
TUD-GV median 5 per frame and max 14; IWHR median 6 and max 43. **Changing detectors changes the
water risk distribution even with identical weights and thresholds.** Any detector swap must
re-derive `water_visual_count_reference` against the new model's density, and that re-derivation
must be measured, not guessed.

---

## 11. Training requirements still outstanding

| # | Requirement | Blocks | Obtainable by merging? |
| --- | --- | --- | --- |
| 1 | **Clean-water negative frames** | Any false-positive claim | **No** — C6 |
| 2 | **Material labels** | Stage 2 of Options B and C; any `plastic`/`bag`/`foam` claim | **No** — no dataset has the field |
| 3 | **Natural-vs-anthropogenic separation in IWHR** | Promoting IWHR to role A | No — needs human relabelling of 23,689 boxes |
| 4 | **Floating-vs-grounded separation in IWHR** | Using IWHR's 73.5% dry-rock majority | No — the distinction is only in the imagery |
| 5 | **Licence resolution: IWHR and TUD-GV** | Deployment or publication of anything trained on them | No |
| 6 | **Session-level split for TUD-GV** | Training on it at all | No — but it is straightforward (30 explicit sessions) |
| 7 | **Re-derived `water_visual_count_reference`** | Any detector swap | No — must be measured |
| 8 | **Viewpoint diversity** | Generalisation beyond one fixed overhead camera | Partially — IWHR/FloW as role-F domain adaptation |

Items 1 and 2 are the hard blockers. Neither is solvable by any combination of the three datasets.

---

# DATASET_DESIGN_READY

The design is determined and evidence-backed: **TUD-GV trains stage 1 of a generic
anthropogenic-floating-litter detector; FloW serves as a role-B bottle specialist; IWHR serves as
recall-only evaluation and domain-adaptation reference. Nothing is merged.** The six
must-not-merge rules in §7 follow directly from the seven contradictions, and the evidence schema
in §8 prevents the verified `is_pollution_class('floater') == False` failure from reaching
production.

This is *design* readiness, not *training* readiness. Before a model is trained, items 5, 6 and 7
must be closed; before any false-positive or material claim is made, items 1 and 2 must be closed,
and neither can be closed by merging what is already held.

The honest summary of the whole exercise: **three datasets, three incompatible contracts, and the
smallest of them is the only one that can safely train the thing EcoSentinel actually wants to
claim.**

Nothing was trained, merged, converted or deployed. No production code was modified.
