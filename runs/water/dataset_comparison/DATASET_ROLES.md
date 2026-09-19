# Water datasets — role assignment

Roles follow from each dataset's **label contract**, not from its size. A dataset is assigned to
training only where its supervision is consistent with what the model is being asked to predict.

Roles: **A** detector training · **B** specialist detector · **C** classifier data ·
**D** evaluation-only · **E** hard-negative · **F** domain adaptation · **G** not used.

## Assignment

| Dataset | Primary role | Secondary role | Explicitly NOT | Reason from evidence |
| --- | --- | --- | --- | --- |
| **TUD-GV** | **A — detector training** (generic floating-litter) | F — domain adaptation for fixed overhead cameras | Not C (no material field); not E | The only self-consistent contract: anthropogenic + floating, natural material systematically excluded. Zero real annotation defects. Explicit session ids make a leakage-safe split straightforward |
| **FloW-Img** | **B — specialist bottle detector** | D — bottle-recall evaluation | **Not A** for a generic-litter detector | Bottle-only supervision. Its frames are dense *negative* supervision for every non-bottle litter type (C2), so mixing it into generic training actively teaches bags as background |
| **IWHR** | **D — evaluation-only**, localisation recall | F — domain adaptation for wide surveillance views | **Not A** without relabelling; **not E** | Largest set (23,689 boxes) but the most contradictory contract: natural material as positive (C1), litter on dry rock as positive (C4), inconsistent omission (C5). Two capture modes with a 17x object-size gap |

**No dataset is assigned role C (classifier data)** — none has a material, subtype or attribute
field, so no material classifier can be trained from any of them.

**No dataset is assigned role E (hard negatives)** — all three have zero empty frames, so none
supplies negative examples at all.

**No dataset is assigned role G** — each has a defensible use; none is worthless.

## Why IWHR is not the training set despite being the largest

This is the counter-intuitive call, so the reasoning is set out explicitly.

IWHR has 23,689 boxes — more than FloW and TUD-GV combined (11,429). Size argues for using it as
the training set. The contract argues against, on three independent grounds:

1. **C1**: its `image` group (442 frames) annotates natural leaf/algae mats as positives. Training
   on it teaches a detector to fire on algae, which the Water Agent would then count as pollution
   density.
2. **C4**: 73.5% of IWHR is litter on **dry rock**. A detector trained on it does not measure
   *floating* litter.
3. **C5**: unboxed regions in its surveillance frames are unreliable negatives.

Used as **evaluation-only for localisation recall**, none of these bite: recall asks "did the model
find the annotated object", and IWHR's annotated objects are real objects whatever their
category. Precision must **not** be reported on IWHR because of C5.

## Role-consistent uses, stated positively

| Question to answer | Dataset to use | Metric that is valid |
| --- | --- | --- |
| Does the detector find floating anthropogenic litter? | TUD-GV held-out sessions | Precision **and** recall |
| Does it find bottles specifically? | FloW-Img | Recall (precision valid only against bottle GT) |
| Does it generalise to wide surveillance views? | IWHR surveillance groups | **Recall only** |
| Does it fire on clean water? | **None available** | — requires new data |
| Does it distinguish plastic from organic? | **None available** | — not trainable from these |

## Outstanding data requirements

1. **Clean-water negative frames.** Mandatory before any false-positive claim. Not obtainable by
   merging (C6). EcoSentinel already has a measured clean-water weakness in its reference matcher,
   so this is a known, repeating gap.
2. **Material labels**, if any material claim is ever wanted. Requires new annotation, not new
   datasets of this kind.
3. **Natural-vs-anthropogenic separation in IWHR**, if IWHR is ever to be promoted to role A.
   Requires human relabelling of 23,689 boxes.
4. **Licence resolution** for IWHR and TUD-GV before anything trained on them is deployed or
   published. FloW declares CC BY 4.0 (by a re-uploader, not the original authors).
