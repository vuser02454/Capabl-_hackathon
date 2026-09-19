# Water datasets — label contradictions

Every case where combining two datasets would give a model conflicting supervision for the same
visual content. Severity is assigned per case, with the remedy that follows from the evidence.

Severity vocabulary: **SAFE** · **UNSAFE** · **REQUIRES_MASKING** · **REQUIRES_RELABELLING** ·
**REQUIRES_SEPARATE_MODEL**.

## Semantic overlap matrix

Does each dataset's annotation contract **support** a claim about this concept?

| Concept | IWHR (`floater`) | FloW-Img (`bottle`) | TUD-GV (`litter`) |
| --- | --- | --- | --- |
| floater (generic salient object on/near water) | **SUPPORTED** | NOT_SUPPORTED | PARTIALLY_SUPPORTED |
| bottle | PARTIALLY_SUPPORTED | **SUPPORTED** | PARTIALLY_SUPPORTED |
| litter (anthropogenic, floating) | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | **SUPPORTED** |
| natural material | **SUPPORTED** (annotated as `floater`) | NOT_SUPPORTED | **NOT_SUPPORTED** (deliberately excluded) |
| plastic | NOT_SUPPORTED | NOT_SUPPORTED | NOT_SUPPORTED |
| bag | PARTIALLY_SUPPORTED | NOT_SUPPORTED | PARTIALLY_SUPPORTED |
| container | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED |
| foam | PARTIALLY_SUPPORTED | NOT_SUPPORTED | PARTIALLY_SUPPORTED |
| other anthropogenic litter | PARTIALLY_SUPPORTED | NOT_SUPPORTED | **SUPPORTED** |

**Reading the cells.** *SUPPORTED* means the contract lets you assert this concept from a label.
*PARTIALLY_SUPPORTED* means objects of this kind are inside the positive set but **not separable**
from it — TUD-GV boxes bottles, but its label cannot tell you a box is a bottle. *NOT_SUPPORTED*
splits into two very different situations, distinguished in the notes below: out-of-scope
(FloW/bag) versus actively excluded (TUD-GV/natural material).

**No cell in the `plastic` row is supported.** No dataset has a material field. Material is not
recoverable from any combination of these three.

## Contradictions

### C1 — Natural floating material: positive in IWHR, background in TUD-GV

| | |
| --- | --- |
| IWHR | Yellow leaf/algae mats on a canal are boxed as `floater` (the `image` group, 442 frames, is largely this) |
| TUD-GV | Organic surface matter is systematically left unboxed |
| Conflict | Identical visual content, opposite supervision |
| Severity | **UNSAFE** |

Merging these into one positive class trains the model on both "algae mat = object" and "algae mat
= background". The gradient contribution is not merely noisy, it is **opposed**, and the two
datasets are large enough (442 vs 1,501 frames) for neither to be drowned out.

**Remedy: REQUIRES_SEPARATE_MODEL, or REQUIRES_RELABELLING of IWHR's natural-material boxes.**
Relabelling means a human separating natural from anthropogenic across IWHR's 23,689 boxes — the
information to do so automatically does not exist in the annotation.

### C2 — Non-bottle litter: positive in TUD-GV, background in FloW

| | |
| --- | --- |
| FloW | A floating bag beside an annotated bottle receives no box |
| TUD-GV | The same bag is boxed as `litter` |
| Conflict | Identical visual content, opposite supervision |
| Severity | **UNSAFE** for a generic-litter detector; **SAFE** for a bottle-only detector |

This is the sharpest contradiction in the set because it is **asymmetric and silent**: FloW's
frames look like clean supervision for a litter detector and are in fact dense negative supervision
for every non-bottle litter type.

**Remedy: REQUIRES_MASKING or REQUIRES_SEPARATE_MODEL.** Masking means treating FloW frames as
*ignore regions* outside bottle boxes, not as background — supported by Ultralytics only through
dataset-level exclusion, not per-region ignore, so in practice this means not mixing FloW into
generic-litter training at all.

### C3 — Bottles: `bottle` in FloW, `litter` in TUD-GV, `floater` in IWHR

| | |
| --- | --- |
| Conflict | Same object, three class names |
| Severity | **SAFE** under a single-class detector; **REQUIRES_RELABELLING** under a multi-class one |

This is the *least* dangerous contradiction and the most likely to be mistaken for the worst. If
the detector has one class, all three agree a bottle is a positive, and the differing names collapse
harmlessly. It only bites if someone builds a 3-class detector from the union of class names, which
would train `bottle` and `litter` as mutually exclusive on identical pixels.

### C4 — Litter on dry rock: positive in IWHR, out of frame-scope in TUD-GV

| | |
| --- | --- |
| IWHR | `rubbish` and `fishing-*` — 2,204 frames, 73.5% of the dataset — box litter resting on **dry rock and sand** |
| TUD-GV | The bank appears in most frames and is never annotated |
| FloW | Bank visible, never annotated |
| Severity | **UNSAFE** for a *floating*-object detector |

A model trained on the union learns that litter on dry ground is a positive, then meets TUD-GV and
FloW frames where bank litter would be background. More importantly for EcoSentinel: a detector
that fires on shoreline litter is **not** measuring floating-litter density, which is what the Water
Agent's `visual_score` treats it as.

**Remedy: REQUIRES_RELABELLING or REQUIRES_SEPARATE_MODEL.** IWHR's own annotation cannot
distinguish floating from grounded — the distinction exists only in the imagery.

### C5 — Annotation omission in IWHR's surveillance frames

| | |
| --- | --- |
| IWHR | Visually similar debris patches inconsistently boxed within a single frame |
| Severity | **UNSAFE as negative supervision; ACCEPTABLE as positive supervision** |

Unboxed regions in these frames are not reliable negatives. Recall measured on them reads
pessimistically, and an unmatched detection there is not necessarily a false positive.

**Remedy: REQUIRES_MASKING** if used for evaluation — or restrict IWHR evaluation to reporting
localisation recall only, never precision.

### C6 — No dataset has negative frames

| | |
| --- | --- |
| All three | Zero images with zero objects |
| Severity | **UNSAFE for any false-positive claim** |

No combination of these datasets can measure the false-positive rate on clean water. TUD-GV makes
this worse rather than better: its glare and ripple visually resemble small pale litter, and it
contains no clean frames to calibrate that against.

**Remedy: REQUIRES_MORE_DATA.** Clean-water frames must be sourced separately. This cannot be
solved by merging.

### C7 — FloW's geometry is not comparable

| | |
| --- | --- |
| FloW | 640x640 **stretch**-resized from landscape source; aspect ratio not preserved |
| IWHR / TUD-GV | Native 1920x1080, unmodified |
| Severity | **REQUIRES_MASKING** (of the statistic, not the data) |

Relative-area comparisons survive the resize. **Box aspect-ratio comparisons do not**, and neither
does any shape prior learned from FloW. Mixing FloW into training with the others teaches a
distorted shape distribution for the same physical objects.

## Summary

| ID | Contradiction | Severity | Remedy |
| --- | --- | --- | --- |
| C1 | Natural material: IWHR positive / TUD-GV background | **UNSAFE** | SEPARATE_MODEL or RELABELLING |
| C2 | Non-bottle litter: TUD-GV positive / FloW background | **UNSAFE** | MASKING or SEPARATE_MODEL |
| C3 | Bottle named three ways | **SAFE** single-class | RELABELLING only if multi-class |
| C4 | Litter on dry rock: IWHR positive | **UNSAFE** | RELABELLING or SEPARATE_MODEL |
| C5 | IWHR annotation omission | **UNSAFE** as negatives | MASKING for evaluation |
| C6 | No negative frames anywhere | **UNSAFE** for FP claims | REQUIRES_MORE_DATA |
| C7 | FloW aspect distortion | **REQUIRES_MASKING** of shape stats | Exclude from shape priors |

**Four of seven are UNSAFE, and two of those (C1, C4) originate in IWHR alone.** The single
contradiction most likely to be underestimated is **C2**, because FloW's frames look like clean
supervision and are silently the opposite.
