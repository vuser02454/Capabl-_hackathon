---
title: Model Capabilities, Measured Metrics and Known Limits
domain: cross_signal
source: runs/evaluation/classification_report.json, runs/waste_detection/AB_TEST_REPORT.md
---

# Model Capabilities, Measured Metrics and Known Limits

All figures are measured and held in `runs/`. None are estimated.

## Waste classifier — MobileNetV3-Small, 8 classes

Source: `runs/evaluation/classification_report.json`, 1,200 held-out validation images.

- Accuracy **93.4%**, macro precision 90.6%, macro recall 92.4%, **macro F1 91.1%**.
- Best class: leaf_waste F1 0.994. Worst: plastic_bottles F1 0.842.
- **plastic_bottles recall is 73.9%** — roughly one bottle in four is missed. Precision is 98%,
  so it under-reports rather than over-reports.
- Training distribution is severely imbalanced: 10,050 food_waste against 179 ewaste, a 56:1
  ratio. Macro F1 is the honest headline for exactly this reason.

## Waste detector — TACO-trained YOLOv8n

Source: `runs/waste_detection/AB_TEST_REPORT.md`, held-out TACO test split (59 images, 107 objects).

| Model | Localisation | End-to-end correct |
| --- | --- | --- |
| COCO yolov8n | 9.3% | 2.8% |
| TACO waste_detector | 53.3% | 7.5% |

End-to-end correctness is **7.5%**. TACO is small litter photographed in the wild and is among
the hardest benchmarks in this domain. The dominant error is **the classifier declining to
answer** (41 of 107) — the confidence gate working as designed. The system abstains far more
often than it errs.

Where detector and classifier disagree (42 cases), the detector is right 22 times and the
classifier 6. That measurement is why detector authority exists.

## Water vision — COCO-pretrained YOLOv8n

**The water detector is not trained on water litter.** It is a COCO model detecting 80 everyday
classes. Consequences:

- It will **under-detect** real floating litter.
- Non-litter COCO classes (person, boat, kite) are excluded from the pollution count by the
  semantic taxonomy, so they no longer inflate the risk score.
- No water-litter detector has been trained. A leakage-safe TUD-GV split exists but training is
  blocked on the absence of clean-water negatives.

## visual_score is an unvalidated convention

`visual_score = count(litter detections) / count_reference`, with `count_reference = 20`. No
confidence weighting, no per-class severity, no box area. The reference is a **convention, not a
calibration**: measured ground-truth density differs by up to **8.7x** between detector families,
so swapping detectors changes how often visible pollution is reported with no configuration
change. It is retained as an explicit provisional signal capped at +0.25 escalation.

## Grad-CAM attribution

Computed at `features[-1]` of MobileNetV3-Small — 576 channels at **7x7**, upsampled for display.
It is **regional, not pixel-level**. The explained class and confidence equal what the classifier
reported, and the map changes with the target class; both properties are asserted by test. When
gradients cannot be computed the response says so and carries **no image**.

## Open blockers

- **B1** — No clean-water negative set exists. The false-positive rate on clean water is
  **unmeasured**, and clean water is the most common real-world input.
- **B2** — `count_reference = 20` is unvalidated, and depends on B1.
- **B3** — FloW-Img redistribution rights are unresolved; the dataset is not used.
