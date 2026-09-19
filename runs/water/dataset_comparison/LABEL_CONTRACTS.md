# Water datasets — label contracts

What each dataset's annotation actually promises, stated separately from what its class is *called*.
Derived from the three completed audits and from inspecting rendered annotations; no dataset ships
annotation guidelines, which is itself the central finding.

## The documentation problem, stated first

**None of the three datasets ships an annotation guideline, codebook, README describing labelling
policy, or any statement of what annotators were told to box.**

| Dataset | Documentation present on disk |
| --- | --- |
| IWHR | None. No LICENSE, README, citation or DOI. `<source><database>` reads `Unknown` in all 3,000 XML files |
| FloW-Img | `README.roboflow.txt` and `README.dataset.txt` — these describe **export pre-processing and license only**, not annotation policy |
| TUD-GV | None. `classes.txt` (6 bytes) and a `.DS_Store` are the only non-data files |

Every "negative definition" below is therefore **inferred from observed annotation behaviour on a
sample**, not read from documentation. That distinction is carried explicitly through this document
because it determines whether absence of a box can be treated as evidence of absence — and it
cannot.

## Contracts

| Dataset | Positive definition | Negative definition | Intentionally unannotated | Semantic scope |
| --- | --- | --- | --- | --- |
| **IWHR** (`floater`, 23,689 boxes / 3,000 images) | An object judged salient **on or beside the water**, including manufactured litter **and** natural organic mats, and including litter resting on **dry rock and sand** | **UNKNOWN.** No documented policy. Observed: many visually similar debris patches in turbid wide shots are left unboxed while neighbouring ones are boxed | **Unknown / inconsistent.** In surveillance frames, diffuse debris is boxed in some places and not others. No rule recoverable | **Broadest of the three.** Not restricted to floating, not restricted to anthropogenic, no material distinction. Effectively *visually salient object in a water scene* |
| **FloW-Img** (`bottle`, 3,248 boxes / 1,200 images) | A **rigid floating drink container** (bottle) on the water surface | **UNKNOWN, and specifically not "everything else".** Other floating litter is *out of annotation scope*, which is not the same as being asserted non-litter | **Non-bottle floating litter** (bags, wrappers, foam), natural debris, boats, banks, people. Observed consistently across the sample | **Narrowest.** A single material-and-object-specific class. Bottle-only supervision |
| **TUD-GV** (`litter`, 8,181 boxes / 1,501 images) | **Any anthropogenic object floating on the water surface** — bags, bottles, rigid containers, foam, wrappers — all under one label | **UNKNOWN,** but the most internally consistent of the three. Observed: organic surface matter in annotated frames is left unboxed systematically, not sporadically | **Natural surface material** (organic matter, vegetation). Also anything on the bank — the bank appears in most frames and is never annotated | **Middle.** Generic across *materials*, specific about *anthropogenic* and *floating*. No material subdivision |

## Why "unannotated" is not "negative" here

This is not a theoretical caution; each dataset breaks the equivalence in a different way.

**FloW-Img — out of scope, not negative.** A plastic bag floats in a FloW frame with no box. Training
a *generic litter* detector on that frame supervises the bag as background. The annotation never
claimed the bag was not litter; it claimed the frame's **bottles** were enumerated. Using FloW as
negative evidence for non-bottle litter asserts something the contract does not support.

**IWHR — omission, not scope.** In the surveillance groups, debris patches of similar appearance are
inconsistently boxed within the same frame. Here an empty region is closer to *annotation omission*
than to a scope boundary, and neither reading is documented. IWHR's unboxed regions are the least
trustworthy negatives of the three.

**TUD-GV — the only defensible negative, and only for one category.** Organic material is left
unboxed consistently across sessions, which supports treating *natural surface matter* as a
deliberate exclusion. It does **not** support treating every unboxed pixel as litter-free: glare and
ripple resemble small pale litter, and the dataset has no clean-water frames to calibrate against.

**All three: no negative images at all.** Every frame in all three datasets contains at least one
annotated object (IWHR 0 empty, FloW 0 empty, TUD-GV 0 empty). **None of the three can measure a
false-positive rate on clean water.** That gap is shared, and it is the same gap EcoSentinel's
existing reference matcher already has (15-33% recall on clean `Baja` frames).

## Contract-level consequences

1. **The three positives are not nested.** `bottle` ⊄ `litter` ⊄ `floater` as *supervision*, even
   though the object sets look nested: FloW supervises a bag as background where TUD-GV supervises
   it as positive. Set-theoretic reasoning about the class names does not transfer to the labels.
2. **Only TUD-GV's contract is self-consistent enough to define a negative**, and only for natural
   material.
3. **No dataset supports a material claim.** None has a material, polymer or subtype field. A
   material-specific output cannot be trained from any of them, individually or together.
4. **Cross-dataset evaluation is contract-mismatched by construction.** A model evaluated on FloW
   is scored against bottle-only ground truth; every correct non-bottle litter detection counts as
   a false positive.
