# Experiment A/B — production 6-class detector vs class-agnostic litter localizer

**FINAL.** Experiment B completed all 40 epochs. Every number below comes from the final
`best.pt` (epoch 38) on the same fixed held-out set as A.

No production code, weights, thresholds or config were modified. No retraining of B or the
classifier. No new split. All artifacts under `runs/experiments/`.

## 1. Training status

| | |
|---|---|
| Checkpoint | `runs/experiments/litter_localizer/checkpoints/best_final_epoch38.pt` (sha256 97635030bef22444…) |
| Loads | Yes — `task=detect`, `nc=1`, `names={0: litter}` |
| Training completed | **Yes** — `TRAINING COMPLETE` marker, `train_args.json` written 17:30:11Z |
| Epochs | **40/40**, 63.5 min wall |
| Best epoch | **38** — mAP50 0.5793, mAP50-95 0.3991, P 0.6773, R 0.5862 |
| Early stopping | Not triggered (patience 12; best at 38 of 40) |
| Train args | epochs 40, batch 16, imgsz 640, patience 12, seed 1337, device mps, pretrained `backend/models/yolov8n.pt` |
| Dataset | `runs/experiments/litter_localizer/dataset/data.yaml` |

Hyperparameters are identical to the production detector's run
(`runs/waste_detection/taco_yolov8n`), so the class dimension is the only variable.

## 2. Dataset

Single-class `litter`, every TACO material class id collapsed to 0. Images symlinked from
`datasets/taco_yolo`, so A and B evaluate on byte-identical files.

| split | images | boxes |
|---|---:|---:|
| train | 742 | 1,358 |
| val | 148 | 290 |
| test (**fixed held-out**) | **98** | **166** |

Leakage: stem overlap train&val / train&test / val&test = **0 / 0 / 0**; content-duplicate groups
**0**; split inherited verbatim, never re-split.

## 3-8. Results

All class-agnostic, same 98 images / 166 human boxes, conf 0.25, identical matching code, both arms
on CPU (A reproduced its MPS numbers exactly, so device is not a confound).

| Metric | A: Production Detector | B: Class-Agnostic Localizer |
|---|---:|---:|
| AP50 (class-agnostic) | 0.4387 | 0.4389 |
| AP50-95 (class-agnostic) | 0.2612 | 0.2937 |
| Recall @ IoU .30 | 59.0% | 56.6% |
| Precision @ IoU .30 | 0.5775 | 0.5714 |
| Recall @ IoU .50 | 53.6% | 51.8% |
| Precision @ IoU .50 | 0.5134 | 0.5200 |
| Non-waste FP rate | 35.8% | 33.0% |
| Person-region FPs | 6/25 | 3/25 |
| Classifier top-1 | 32.9% | 38.0% |
| Assertion coverage | 16.3% | 16.3% |
| Accuracy when asserted | 51.8% | 40.7% |
| End-to-end accuracy | 15.1% | 16.3% |
| Plastic bottle localization recall | 46.9% | 50.0% |
| Plastic bottle classification accuracy | 6/13 | 6/14 |

### Gate effect

| Metric | A | B |
|---|---:|---:|
| Raw detections | 187 | 175 |
| Accepted | 176 | 161 |
| Rejected | 11 | 14 |
| Non-waste-object rejections | 11 | 14 |
| Degenerate-box rejections | 0 | 0 |
| True detections wrongly rejected | 6 (6.3%) | 6 (6.6%) |

Only 18 COCO never-waste regions exist across the 98 held-out images, which caps what the gate can
catch here.

### End-to-end pipeline

image → localizer → gate → crop → classifier → 0.60 gate → assertion

| | A | B |
|---|---:|---:|
| Total GT objects | 166 | 166 |
| Localised | 89 | 86 |
| Accepted by gate | 83 | 80 |
| Classified | 76 | 71 |
| Correct material | 25 | **27** |
| **End-to-end accuracy** | **15.1%** | **16.3%** |
| Assertion coverage | 16.3% | 16.3% |
| Accuracy among assertions | 51.8% | 40.7% |

Per class (end-to-end):

| class | GT | A | B |
|---|---:|---:|---:|
| plastic_bags | 71 | 11.3% | 11.3% |
| paper_waste | 35 | 22.9% | **28.6%** |
| plastic_bottles | 32 | 18.8% | 18.8% |
| metal_cans | 28 | 10.7% | 10.7% |

`ewaste`, `food_waste`, `leaf_waste`, `wood_waste`: **0 GT objects in the held-out set**, not
evaluable.

### Plastic bottles (32 GT objects)

| | A | B |
|---|---:|---:|
| Localised (IoU ≥ .5) | 15 (46.9%) | **16 (50.0%)** |
| Gate-accepted | 13 | 14 |
| Classified | 13 | 14 |
| Top-1 correct | 6 | 6 |
| End-to-end | 18.8% | 18.8% |

Measured failure mode, not inferred: B's confusions are `plastic_bottles → ewaste` (5) against
`plastic_bottles → plastic_bottles` (6). On human GT crops the classifier scores 8/31 (25.8%) on
bottles. `plastic_bottles` is also the weakest class in the classifier's **own** domain — 63.3% on
`garbage_Dataset` val against 88.2% overall.

### Classifier

Existing `classify()`, `_crop()`, preprocessing and 0.60 gate. Not retrained.

Preserved unchanged from the earlier run: **human GT crops, n = 141, top-1 24.1%**, asserted 58
(41.1%), accuracy when asserted 32.8%.

Control: same weights on `garbage_Dataset` val score **88.2%** top-1 / 88.3% macro recall,
consistent with the claimed 0.911 macro-F1. The collapse on real crops is a domain gap, not a
harness fault.

### Rejected detections cannot reach the UI as waste

Live check against the running backend on the frame that produced the original person→`paper_waste`
failure (COCO person 0.705, waste box 0.436, IoU 0.7179):

```
WASTE-DET-002 paper_waste  localisationRejected=non_waste_object
                           classification=None  segregation=uncertain  status=needs_review
rejected records carrying a segregation claim : 0
rejected records with status=confirmed        : 0
```

`RealWasteDetection.tsx:75` filters `localisationRejected` out of the array driving both the photo
overlay (159) and the findings list (230); rejected records render only in the refusal section
(332).

## 9. Interpretation

1. **Localization?** Essentially tied. AP50 0.4389 vs 0.4387; AP50-95 **0.2937 vs 0.2612** (B
   better, tighter boxes); recall@.5 51.8% vs 53.6% (A better by 3 objects). B wins on box quality,
   A on raw recall.
2. **Non-waste false positives?** **Yes, B is better.** 33.0% vs 35.8% overall, and **3/25 vs 6/25
   person regions — half.** This reverses the interim epoch-9 reading (59.6%, 16/25), which was an
   undertraining artifact.
3. **Better crops?** Yes, modestly — classifier top-1 38.0% vs 32.9% on accepted crops.
4. **Better material classification?** No. The classifier is unchanged; only its input shifts.
5. **Better bottles?** Localization yes (50.0% vs 46.9%), end-to-end identical (18.8%), because the
   classifier loses the extra object it was handed.
6. **Better end-to-end?** Marginally — **16.3% vs 15.1%**, which is 27 vs 25 objects out of 166.
   Two objects is inside noise for n=166; this is not a meaningful win.
7. **Dominant bottleneck: CLASSIFICATION, decisively.**

   - *Localization:* real but secondary, and now essentially solved to parity. Perfect localization
     still caps end-to-end at the classifier's GT-crop accuracy of **24.1%**.
   - *Classification:* dominant. Handed **human** boxes the classifier is right 24.1% of the time.
     88.2% in-domain vs 24.1% on real crops is a domain gap, not a capacity limit.
   - *Gating/pipeline bug:* none. All rejections were `non_waste_object`, costing 6 true detections
     in each arm. Rejected records carry no segregation claim and are filtered from the UI.

   One regression worth naming: B's **accuracy when asserted falls to 40.7% from A's 51.8%**. B
   surfaces more crops past the 0.60 gate that the classifier then gets wrong, so B makes confident
   claims slightly less trustworthy even while raw end-to-end ticks up.

## 10. Recommendation

**Do not promote B to production on this evidence.** It earns a genuine safety win (person false
positives halved) and better box quality, but end-to-end moves 15.1% → 16.3% — two objects — and
assertion trustworthiness regresses. Neither architecture is usable at ~16% end-to-end.

The actionable finding is independent of A-vs-B: **the classifier scores 24.1% on perfect crops.**
Until that is addressed, no localizer choice matters. What it needs is training data drawn from
detector-style crops — small, off-centre, cluttered, motion-blurred, variably lit outdoor
fragments — rather than `garbage_Dataset`'s centred product photographs. `plastic_bottles` and the
`→ ewaste` / `→ wood_waste` confusions are where to start.

## 11. Pipeline integrity check

- [x] B checkpoint actually loaded (final, epoch 38)
- [x] B training complete (40/40, marker present)
- [x] All 98 test images processed
- [x] All 166 GT boxes included
- [x] Same test files as A (symlinks to the same inodes)
- [x] Same confidence threshold (0.25 detector, 0.60 classifier)
- [x] Same IoU matching methodology (shared code path)
- [x] Same non-waste COCO protocol (109 regions, conf ≥ 0.45)
- [x] Existing localisation gate used, unmodified
- [x] Existing classifier used, not retrained
- [x] Existing `_crop()` used
- [x] Existing classifier confidence threshold used
- [x] No production code modified
- [x] No production weights modified
- [x] No classifier retraining
- [x] No B retraining
- [x] No new random split
- [x] No test-set leakage (0/0/0 overlap, 0 duplicate groups)
- [x] All raw results saved (`predictions_final/`)
- [x] Final report generated

**19/19 verified. Experiment complete.**

Raw artifacts: `predictions_final/{ARMS_AB,FP_PROBE_AB,GATE_EFFECT_AB,END_TO_END_AB}.json` and
`raw_predictions_*.json`. Interim epoch-9 results retained in `predictions/` for comparison.
