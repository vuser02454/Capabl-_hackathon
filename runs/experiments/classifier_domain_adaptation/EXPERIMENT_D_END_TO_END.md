# Experiment D — end-to-end validation of the Experiment C classifier

Offline evaluation. Nothing was trained. No production code, weights, thresholds, API or frontend
was modified. The production classifier is byte-identical (sha256 `4fc5e9e4e80ef8be…`, mtime
unchanged) and so is `backend/models/waste_detector.pt`. TACO TEST was not used for training.

## 1. Checkpoint verification

```
C_CHECKPOINT = runs/experiments/classifier_domain_adaptation/run_c/best.pt
               6,224,169 bytes   sha256 7e2865aeac0cccac…
```

| property | production | Experiment C | identical? |
|---|---|---|---|
| arch | `mobilenet_v3_small` | `mobilenet_v3_small` | yes |
| image_size | 224 | 224 | yes |
| classes (order-sensitive) | 8-class list | 8-class list | yes |
| `preprocess` field | `None` | `letterbox_v2` | see note |
| state_dict | — | — | **differs**, confirming C is a genuinely different model |

Note on preprocessing: both checkpoints are *served* through the same `letterbox_v2` eval
transform. The field differs only because the production checkpoint predates preprocessing
versioning and records nothing — which is what raises the "unverified preprocessing" warning at
load. C declares it, so that warning disappears. Applied preprocessing is identical.

## Architecture

```
IMAGE
 ↓ production detector   backend/models/waste_detector.pt   conf 0.25
 ↓ localisation gate     services/waste/waste_localisation.py   (unmodified)
 ↓ _crop()               services/waste/waste_pipeline.py       (unmodified)
 ↓ CLASSIFIER            <-- the only variable
 ↓ confidence gate       0.60, unchanged
 ↓ final material assertion
```

Detections and gate decisions are computed **once** and reused by both arms, so the two
classifiers are handed byte-identical crops. Localised / accepted / classified are 89 / 83 / 76 in
both arms — identical by construction, not by coincidence.

Fixed held-out set: 98 TACO test images, 166 human GT boxes. Match IoU 0.5.

## 2-3. Full comparison

| Metric | Current Production | Experiment C |
|---|---:|---:|
| Localized | 89 | 89 |
| Gate accepted | 83 | 83 |
| Classified | 76 | 76 |
| Correct material | 25 | **53** |
| End-to-end accuracy | 15.1% | **31.9%** |
| Assertion coverage | 16.3% | **36.8%** |
| Accuracy when asserted | 51.9% | **77.1%** |
| False assertion rate | 7.8% | 8.4% |
| Bottle end-to-end | 18.8% | **25.0%** |
| Paper end-to-end | 22.9% | 22.9% |

End-to-end more than doubles: **25 → 53 objects correct out of 166**. This lands within half a
point of the ~32% projected arithmetically in the Experiment C report, which is a useful
consistency check on that projection.

## 4. Per-class analysis

| class | GT | localized | accepted | classified | correct (prod) | correct (C) | e2e prod | e2e C |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| plastic_bags | 71 | 41 | 38 | 34 | 8 | **29** | 11.3% | **40.8%** |
| plastic_bottles | 32 | 15 | 13 | 13 | 6 | **8** | 18.8% | **25.0%** |
| paper_waste | 35 | 20 | 20 | 19 | 8 | 8 | 22.9% | **22.9%** |
| metal_cans | 28 | 13 | 12 | 10 | 3 | **8** | 10.7% | **28.6%** |

No class regressed. `paper_waste` is flat; the other three improve, `plastic_bags` most (3.6x).

## 5. Confidence analysis (threshold unchanged at 0.60)

| | Current Production | Experiment C |
|---|---:|---:|
| Assertions | 27 | 61 |
| Correct assertions | 14 | **47** |
| Incorrect assertions | 13 | 14 |
| Assertion coverage | 16.3% | **36.8%** |
| Accuracy when asserted | 51.9% | **77.1%** |
| False assertion rate | 7.8% | 8.4% |

Coverage rises 2.3x while the absolute number of *incorrect* assertions barely moves (13 → 14).
Nearly all the extra coverage is correct. The false assertion rate ticks up 0.6 points because the
denominator is all 166 GT objects and C simply makes many more claims.

Confidence bins on the end-to-end crops (n, accuracy):

| bin | Current Production | Experiment C |
|---|---|---|
| 0.5–0.6 | 14 / 0.214 | 10 / 0.400 |
| 0.6–0.7 | 5 / 0.400 | 10 / 0.700 |
| 0.7–0.8 | 6 / 0.500 | 3 / 0.333 |
| 0.8–0.9 | 8 / 0.625 | 12 / 0.583 |
| 0.9–1.0 | 8 / **0.500** | 36 / **0.889** |

The top bin is the one that matters: production is right half the time at ≥0.9 confidence, C is
right 89% of the time, and C puts 36 of 76 crops there rather than 8. The mid bins are noisy at
n=3–12 and should not be over-read.

## 6. Gate analysis

| | value |
|---|---:|
| Raw detections | 187 |
| Gate accepted | 176 |
| Gate rejected | 11 |
| Non-waste rejections | 11 |
| Degenerate-box rejections | 0 |
| True detections wrongly rejected | 6 |

Identical to the Experiment A evaluation, as expected: the classifier sits downstream of the gate
and cannot influence it. Consistency confirmed.

## 7. Bottle failure analysis

13 bottle crops reach the classifier (15 localised, 2 lost to the gate).

```
Current  plastic_bottles -> plastic_bottles 6, ewaste 3, food_waste 1, wood_waste 1,
                            leaf_waste 1, paper_waste 1
Exp C    plastic_bottles -> plastic_bottles 8, plastic_bags 4, paper_waste 1
```

Measured, not inferred: every cross-material failure mode (`ewaste`, `food_waste`, `wood_waste`,
`leaf_waste` — 6 of 13) is gone. The residual error is `-> plastic_bags` (4), a plastic/plastic
confusion. End-to-end 6/32 → 8/32.

The binding constraint on bottles is now **localisation**: only 15 of 32 bottles are found at all,
so 17 are lost before the classifier is consulted. Classifier accuracy on the crops it does see is
8/13 = 61.5%.

## 8. Paper-waste analysis

19 paper crops reach the classifier. End-to-end is unchanged at 8/35, but the error *composition*
changed completely:

```
Current  paper_waste -> paper_waste 8, wood_waste 5, plastic_bags 3, leaf_waste 1,
                        ewaste 1, metal_cans 1
Exp C    paper_waste -> plastic_bags 9, paper_waste 8, leaf_waste 1, metal_cans 1
```

The `-> wood_waste` mode (5) is eliminated; `-> plastic_bags` grows from 3 to 9 and is now the
single largest confusion in the whole matrix. Net effect on correctness: zero.

Stated as measurement only — the cause is not established here. What can be said is that
`plastic_bags` is the largest class in the adapted training data (2,655 train samples against
`paper_waste`'s 1,825), and that `plastic_bags` recall rose to 0.869 in Experiment C. Whether the
`paper -> bags` leak is a consequence of that is a hypothesis this experiment does not test.

## 9. Promotion check

1. **Does C materially improve end-to-end accuracy?** **Yes.** 15.1% → 31.9%, 25 → 53 of 166
   objects, on identical detections and crops. Not a marginal or noise-level difference.
2. **Does C improve confidence reliability?** **Yes.** Accuracy when asserted 51.9% → 77.1%;
   coverage 16.3% → 36.8% with incorrect assertions rising only 13 → 14; the ≥0.9 bin goes
   0.500 → 0.889. Threshold unchanged.
3. **Does C improve bottle recognition?** **Yes**, modestly end-to-end (18.8% → 25.0%) and
   substantially on crops it sees (6/13 → 8/13). All cross-material bottle failures eliminated.
4. **Does C introduce regressions on paper/bags/metal?** **No regression in accuracy.** `bags`
   11.3% → 40.8%, `metal` 10.7% → 28.6%, `paper` flat at 22.9%. The one thing worth watching is
   the new `paper -> plastic_bags` concentration (9 of 19) and the 0.6-point rise in false
   assertion rate.
5. **Is the remaining bottleneck now localisation rather than classification?** **Yes, it has
   flipped.** Of 166 objects, 77 are never localised and 6 more are lost to the gate — 83 objects,
   50% of the set, never reach the classifier. Of the 76 that do, C gets 53 right (69.7%). The
   ceiling with a perfect classifier and this detector is 83/166 = 50%; the ceiling with a perfect
   detector and C's crop accuracy is roughly 70%. Localisation is now the larger term.
6. **Is C strong enough to enter a staging / manual-review integration?** **On this evidence, yes —
   as a staged, reviewed change, not an automatic swap.** Every measured axis improves or holds,
   the original distribution improved (89.5% vs 88.2%), and confident claims became far more
   trustworthy. What is still unverified before it goes anywhere near users:
   - `leaf_waste` and `wood_waste` received no domain adaptation and have **zero support** in this
     test set. Their real-crop behaviour is unmeasured. C predicts `leaf_waste` once here, wrongly.
   - `paper_waste` is flat and now leaks into `plastic_bags`.
   - 31.9% end-to-end is a large improvement over 15.1% and still far from deployable accuracy.
   - n=166 with per-class counts of 13–38 crops; these are small samples.

**No promotion is made by this experiment.** That is a decision for a human, and the honest summary
is: C is clearly better than the incumbent on every axis measured, and still not good enough for
unreviewed automatic segregation claims.
