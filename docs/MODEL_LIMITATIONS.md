# Model Limitations

**Read this before demoing or presenting.** Everything here is measured or structural. Nothing is
softened, and the numbers come from `runs/`, not from estimation.

---

## 1. Waste classifier — MobileNetV3-Small, 8 classes

Held-out validation, 1,200 images (`runs/evaluation/classification_report.json`):

| Metric | Value |
| --- | --- |
| Accuracy | **93.4%** |
| Macro precision | 90.6% |
| Macro recall | 92.4% |
| **Macro F1** | **91.1%** |

> The report's own note: *"Accuracy alone is misleading on this distribution. Macro F1 and the
> per-class recall are what show whether the rare classes are recognised at all."*

| Class | Precision | Recall | F1 | Val support | Train support |
| --- | --- | --- | --- | --- | --- |
| leaf_waste | 0.997 | 0.990 | **0.994** | 394 | 1,151 |
| food_waste | 0.965 | 0.952 | 0.958 | 229 | **10,050** |
| metal_cans | 0.861 | 0.986 | 0.919 | 69 | 670 |
| ewaste | 0.893 | 0.926 | 0.909 | 54 | 179 |
| plastic_bags | 0.877 | 0.943 | 0.909 | 53 | 200 |
| paper_waste | 0.862 | 0.910 | 0.885 | 212 | 794 |
| wood_waste | 0.812 | 0.949 | 0.875 | 59 | 585 |
| **plastic_bottles** | 0.980 | **0.739** | **0.842** | 130 | 417 |

**Known weaknesses.**

- **`plastic_bottles` recall is 73.9%** — roughly one bottle in four is missed. Precision is high
  (98%), so when it *does* say bottle it is nearly always right. It under-reports rather than
  over-reports, which is the safer direction, but it is a real gap.
- **The training set is severely imbalanced**: 10,050 food_waste against 179 ewaste, a 56:1 ratio.
  Macro F1 is the honest headline for exactly this reason.
- **Preprocessing provenance is unverified.** The shipped weights do not record the preprocessing
  they were trained with, so the match with the served `letterbox_v2` transform cannot be
  confirmed either way. The transform was chosen by *measurement* on real detector crops, not by
  matching. `/api/waste/pipeline-status` reports this rather than staying silent.

## 2. Waste detector — TACO-trained YOLOv8n

Held-out TACO test split, 59 images / 107 objects (`runs/waste_detection/AB_TEST_REPORT.md`):

| Model | Localisation | Correctly named | End-to-end correct |
| --- | --- | --- | --- |
| COCO yolov8n | 9.3% | n/a¹ | **2.8%** |
| TACO waste_detector | **53.3%** | 29.9% | **7.5%** |

¹ COCO names are a different vocabulary (`cup`, `vase`, `bottle`) — neither right nor wrong about
`metal_cans`, so naming accuracy is undefined for that model.

### This is the most important limitation in the project

**End-to-end correctness on held-out TACO is 7.5%.** That number is real and must not be hidden.

Why it is so low, and why the system is still useful:

- TACO is small litter photographed in the wild — cigarette butts, wrappers, fragments at
  distance. It is among the hardest object-detection benchmarks in this domain.
- The dominant error bucket for the TACO detector is **D: the classifier was handed the crop and
  declined to answer** — 41 of 107. That is the confidence gate working as designed. The system
  is not wrong 92% of the time; it *abstains* far more often than it errs.
- On clear single-object photographs (the demo path) the pipeline performs far better — measured
  live on 6 sample images, 4 produced confirmed classifications at 0.85–0.96, one correctly
  abstained, one produced no detection.

**Do not present 7.5% as "accuracy", and do not present the 93.4% classifier figure as pipeline
accuracy either.** They measure different things on different data.

### A pipeline bug worth knowing about

`_decode_image` returned RGB while Ultralytics treats a bare ndarray as **BGR**. Every frame had
its red and blue channels swapped. It never raised — it just detected less:

| Model | RGB (buggy) | BGR (correct) |
| --- | --- | --- |
| TACO waste_detector | 62 | **114** |
| COCO yolov8n | 28 | 30 |

46% of the waste detector's detections, lost silently, looking exactly like a weak model. Fixed;
all figures above are post-fix. It affected the Water Agent too, which shares the decoder.

## 3. Water vision — the largest honest gap

**The production water detector is COCO-pretrained YOLOv8n. It is not trained on water litter.**

`YOLO26_MODEL_PATH=models/yolov8n.pt`. It detects COCO's 80 everyday classes. In a river photo it
finds `bottle` (useful), and also `person`, `boat` and `kite` (not litter).

Until this finalization round, **every** detection counted toward visual pollution. Measured on
`water_datasets/TUD-GV/images/exp55_221.jpg`: two people and four kites scored 0.30 visual
pollution and escalated water risk 0.55 → 0.63. Now the semantic taxonomy in
`core/investigation.py` separates them, and only `visible_surface_litter` reaches the score.

**What remains true even after the fix:**

- A COCO detector will still **miss** litter classes it was never trained on. Low recall on real
  floating waste is expected.
- `unclassified_object` (e.g. `kite`) is not counted — which is correct, but means the system is
  silent about objects it cannot place. Silence is not "clean".
- **No water detector has been trained.** TUD-GV is prepared with a leakage-safe split but
  training is blocked — see `DATASET_PROVENANCE.md` blockers B1–B3.

### `visual_score` is an unvalidated convention

```python
visual_score = count(litter detections) / count_reference    # count_reference = 20
```

No confidence weighting, no per-class severity, no box area. `count_reference = 20` is a
**convention, not a calibration**. Measured ground-truth density across detector families
(`runs/water/dataset_comparison/WATER_TRAINING_READINESS.md`):

| Detector family | % frames ≥ MODERATE | % ≥ HIGH | % saturating |
| --- | --- | --- | --- |
| IWHR-like | 36.4% | 15.8% | 6.3% |
| TUD-GV-like | 22.5% | 0.2% | 0.0% |
| FloW bottle-only | 4.2% | 0.2% | 0.0% |

Swapping detectors changes how often the system reports visible pollution by up to **8.7×**, with
no configuration change and nothing in the logs to explain it.

**It is retained as an explicit provisional demo signal**, capped at +0.25 escalation. It was not
recalibrated in this round because honest recalibration depends on blocker B1 (no clean-water
negatives exist, so the false-positive contribution to the count is unmeasurable). Filtering
changed *what* is counted; the denominator is still uncalibrated.

## 4. Reference-dataset matching

Colour-histogram appearance matching. Measured leave-one-clip-out, it **misreads clean water as
contaminated most of the time**. It is therefore reporting-only and deliberately cannot move a
risk score. Below the 0.62 similarity threshold it says "no confident match" and flags nothing.

## 5. Air

- India NAQI applied to single readings is an **estimate**, not an official 24-hour AQI. Labelled
  as such in the response.
- OpenAQ station coverage is uneven; the nearest station may be up to 25 km away, and that
  distance is reported.
- Missing pollutants may be filled from readings up to 96 h old, labelled `delayed`.

## 6. Structural limits

- **No ground truth for water risk.** The combined water score has never been validated against
  an independent measure, because no such labelled set exists in this project.
- **Single frame, no history.** Water and waste return one point in time, so direction stays
  `unknown` rather than a fabricated trend. Only air has a real baseline.
- **Demo mode is seeded synthetic data**, marked `isMock: true` throughout. It is not a
  measurement and the UI says so.
- **Grad-CAM is regional, not pixel-level.** Computed at 7×7 and upsampled; `attribution_grid` is
  reported so the overlay is never read as pixel precision.
- **Segregation categories are configuration, not prediction.** What counts as recyclable varies
  by municipality.
