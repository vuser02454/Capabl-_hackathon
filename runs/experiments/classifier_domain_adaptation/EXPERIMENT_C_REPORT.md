# Experiment C — Classifier Domain Adaptation

Offline experiment. No production code, weights, thresholds, API or frontend were modified. The
production classifier `runs/classification/best.pt` is untouched (sha256 4fc5e9e4e80ef8be…,
mtime unchanged). TACO TEST was never trained on, never tuned against, and contributed zero crops.

## Baseline

The current classifier, measured through the production `classify()` path on four fixed sets:

| set | n | top-1 | macro-F1 | coverage ≥0.60 | acc when asserted |
|---|---:|---:|---:|---:|---:|
| garbage_Dataset val | 466 | 88.2% | 0.8842 | 88.0% | 92.4% |
| TACO val GT crops | 237 | 31.2% | 0.4353 | 36.7% | 40.2% |
| **TACO test GT crops** | 141 | **24.1%** | 0.3447 | 41.1% | 32.8% |
| TACO test detector crops | 82 | 34.2% | 0.4781 | 37.8% | 48.4% |

This reproduces the previously reported 88.2% / 24.1% / 34.2% exactly, which validates the harness
both checkpoints run through.

### What the audit found first

`mobilenet_v3_small`, 8 classes, 224px. Preprocessing is already letterbox (`letterbox_v2`) and
training augmentation already simulates detector box error (`RandomBoxJitter`, `boxjitter_v2`). The
geometric half of the domain gap had therefore already been fixed. What remained was **content**:
`garbage_Dataset` is centred, well-lit, single-object product photography; a detector crop is a
small, cluttered, partially-occluded fragment of an outdoor scene.

So Experiment C changes the training data distribution and nothing else. Same architecture, same
image size, same optimiser, same LR, same batch size, same seed, same augmentation, same training
script — invoked with a different `--dataset`.

## Dataset construction

TACO TRAIN and VAL boxes cut into detector-style crops in five variants:

| variant | crops | what it teaches |
|---|---:|---|
| tight | 1,220 | the object with no context |
| expanded (pad 0.18) | 1,361 | generous context, background included |
| prodpad (pad 0.06) | 1,289 | exactly what production `_crop()` produces |
| off-centre (shift ±0.18) | 1,308 | a box the detector placed badly |
| detector-style | 1,055 | a real production box matched to a human box at IoU ≥ 0.5 |
| **total** | **6,233** | |

Mixed with 15,366 `garbage_Dataset` images (symlinked, so the originals remain the source of
truth). Four classes only — `metal_cans`, `paper_waste`, `plastic_bags`, `plastic_bottles`.

Counted and excluded, never merged into a neighbouring class: 10 TACO boxes in `ewaste` (2) and
`food_waste` (8). Real human labels, too few to shift a distribution.

**Stated limitation:** `leaf_waste` and `wood_waste` have no TACO box data at all, so they remain
pure `garbage_Dataset` and receive no domain adaptation. They also have zero support in the TACO
test set, so this experiment says nothing about them either way.

## Dataset integrity

| check | result |
|---|---|
| TACO TEST stems appearing in training data | **0** |
| TACO TEST image SHA-256 ∩ train/val source images | **0** |
| Cross-split duplicates excluded from train | 111 (by SHA-256, existing script logic) |
| Crops with short side < 32px | 0 |
| Crops with short side < 64px | 1,691 (27.1%) |
| Median short side | 121px |
| Train / val samples | 19,264 / 2,215 |

Class balance after mixing (train): `food_waste` 10,050, `plastic_bags` 2,655, `paper_waste` 1,825,
`metal_cans` 1,505, `plastic_bottles` 1,314, `leaf_waste` 1,151, `wood_waste` 585, `ewaste` 179.
The existing `WeightedRandomSampler` balances per class, as in the baseline run.

## Training configuration

```
script      training/train_waste_classifier.py   (unmodified)
dataset     runs/experiments/classifier_domain_adaptation/dataset
out         runs/experiments/classifier_domain_adaptation/run_c
arch        mobilenet_v3_small (ImageNet init)   image_size 224
epochs 10   batch 48   lr 3e-4 (AdamW, wd 1e-4)   seed 1337   patience 3   device mps
augment     boxjitter_v2      preprocess letterbox_v2
selection   macro-F1 on the COMBINED validation set (garbage val + TACO val crops)
```

Identical to the baseline run except `--dataset` and `--out`.

Early stopping fired at epoch 9; **best is epoch 6, combined-val macro-F1 0.8414**. Duration 1,151s.

Model selection used the combined validation set, so it balances both objectives rather than
optimising TACO alone. TACO TEST played no part in selection.

## Baseline vs Experiment C

| Metric | Current Classifier | Experiment C |
|---|---:|---:|
| TACO GT top-1 | 24.1% | **69.5%** |
| TACO detector-crop top-1 | 34.2% | **70.7%** |
| Macro precision | 0.5545 | **0.7050** |
| Macro recall | 0.2681 | **0.6366** |
| Macro F1 | 0.3447 | **0.6598** |
| Bottle accuracy | 25.8% | **67.7%** |
| Assertion coverage | 41.1% | **83.7%** |
| Accuracy when asserted | 32.8% | **77.1%** |

(Macro figures and coverage are on `taco_test_gt`.)

### The original distribution did not degrade

| set | baseline | Experiment C |
|---|---:|---:|
| garbage_Dataset val top-1 | 88.2% | **89.5%** |
| garbage_Dataset val macro-F1 | 0.8842 | **0.8952** |

No tradeoff was incurred. This was the outcome most at risk and it did not occur; had it, this
section would report the loss.

## TACO GT crop results, per class (n=141)

| class | support | baseline P / R / F1 | Experiment C P / R / F1 |
|---|---:|---|---|
| plastic_bags | 61 | 0.529 / 0.148 / 0.231 | **0.688 / 0.869 / 0.768** |
| plastic_bottles | 31 | 0.727 / 0.258 / 0.381 | **0.750 / 0.677 / 0.712** |
| paper_waste | 28 | 0.462 / 0.429 / 0.444 | **0.632 / 0.429 / 0.511** |
| metal_cans | 21 | 0.500 / 0.238 / 0.323 | **0.750 / 0.571 / 0.649** |

`ewaste`, `food_waste`, `leaf_waste`, `wood_waste`: zero support in this set.

## Plastic bottle results

| | baseline | Experiment C |
|---|---:|---:|
| GT crops | 31 | 31 |
| Correct | 8 | **21** |
| Accuracy | 25.8% | **67.7%** |

Confusion transitions, measured:

```
baseline  plastic_bottles -> ewaste 8, metal_cans 4, paper_waste 4, plastic_bags 4,
                             wood_waste 2, leaf_waste 1,  CORRECT 8
Exp C     plastic_bottles -> plastic_bags 7, metal_cans 2, paper_waste 1,  CORRECT 21
```

The `-> ewaste` failure mode (8 of 31, the single largest) is **eliminated entirely**, as are
`-> wood_waste` and `-> leaf_waste`. The residual error is `-> plastic_bags` (7), a confusion
between two plastics rather than a confusion between a bottle and an electronic device.

## Confidence behaviour

| | baseline | Experiment C |
|---|---:|---:|
| Coverage ≥0.60 | 41.1% | 83.7% |
| Accuracy when asserted | 32.8% | 77.1% |
| **False assertion rate** (wrong confident claims / all crops) | 27.7% | **19.2%** |

The threshold was not changed. Coverage doubled *and* the false assertion rate fell, so the extra
coverage is not bought by asserting more junk.

Reliability on `taco_test_gt` — accuracy within each confidence bin:

| confidence | baseline n / acc | Experiment C n / acc |
|---|---|---|
| 0.4–0.5 | 29 / 0.207 | 9 / 0.333 |
| 0.5–0.6 | 27 / 0.296 | 8 / 0.375 |
| 0.6–0.7 | 14 / 0.214 | 9 / 0.333 |
| 0.7–0.8 | 19 / 0.316 | 17 / **0.706** |
| 0.8–0.9 | 13 / 0.385 | 27 / **0.852** |
| 0.9–1.0 | 12 / 0.417 | 65 / **0.815** |

The baseline is badly miscalibrated: at 0.9–1.0 confidence it is right 41.7% of the time — that is
the "confidently wrong" behaviour that motivated this work. Experiment C's high-confidence bins run
0.71–0.85. Still optimistic (0.9+ should be ~0.9), but the curve now rises with confidence instead
of staying flat.

## Confusion matrix — Experiment C, taco_test_gt

```
truth \ pred      metal_cans  paper_waste  plastic_bags  plastic_bottles  wood_waste
metal_cans (21)           12            2             5                1           1
paper_waste (28)           2           12            12                2           -
plastic_bags (61)          -            4            53                4           -
plastic_bottles (31)       2            1             7               21           -
```

Dominant residual error: `paper_waste -> plastic_bags` (12 of 28). `paper_waste` is the one class
whose recall did not move (0.429 both), and it is where the next gain is.

## Answers

1. **Did domain adaptation improve TACO GT-crop accuracy?** Yes — 24.1% → 69.5%, a 2.9x
   improvement on 141 crops never trained on.
2. **Did it improve detector-crop accuracy?** Yes — 34.2% → 70.7% on identical crops from the same
   detector at the same threshold.
3. **Did plastic-bottle recognition improve?** Yes — 8/31 → 21/31 (25.8% → 67.7%). The
   `-> ewaste` failure mode is gone.
4. **Did confidence reliability improve?** Yes. Coverage 41.1% → 83.7%, accuracy when asserted
   32.8% → 77.1%, false assertion rate 27.7% → 19.2%, with no threshold change. Calibration is
   still optimistic at the top but no longer flat.
5. **Does a major domain gap remain?** Yes, but much smaller: 89.5% in-domain vs 69.5% on TACO
   crops — a 20-point gap, down from 64 points.
6. **Is Experiment C good enough to consider integration?** **Yes — it is worth considering, and
   that is a decision to take deliberately, not automatically.** It improves every measured axis
   including the original distribution, with no measured regression. Before promotion:
   - `leaf_waste` and `wood_waste` received no adaptation and have no TACO test support. Their
     behaviour on real crops is unmeasured, not verified.
   - `paper_waste` recall did not improve (0.429) and it leaks heavily into `plastic_bags`.
   - Calibration is better but still optimistic at 0.9+.
   - The end-to-end pipeline figure has not been recomputed with this checkpoint; localisation
     recall (~53%) remains the other multiplier.

## Projected end-to-end effect (not measured — stated as arithmetic)

Experiment A localised 89 of 166 objects with 76 reaching the classifier. At the baseline's 32.9%
crop accuracy that yielded 15.1% end-to-end. At Experiment C's 70.7% on the same detector crops,
the same 76 crops would give roughly 54/166 ≈ **32%** end-to-end. That is a projection from two
measured quantities, not an executed pipeline run, and should be confirmed by running the
end-to-end harness with this checkpoint.
