# Detector A/B test — COCO YOLOv8n vs TACO waste_detector

Generated 2026-09-19T01:08:08.843507+00:00

**No deployment was made.** `backend/.env` still reads `YOLO26_MODEL_PATH=models/yolov8n.pt`, `/api/waste/pipeline-status` still reports `YOLOv8n` after the experiment, and neither weights file was modified or retrained. The B model was constructed in-process and never configured.

## 1. Production call path under test

The experiment calls the live code. `analyze_waste(detector=...)` is the only injection point used:

```
POST /api/waste/segregate (backend/main.py:494)
services.waste.waste_pipeline.analyze_waste
water_vision_service.build_report -> LocalYoloDetector.detect
_deduplicate (class-agnostic NMS, 0.7 IoU)
_crop (padding 0.06, min 24px)
WasteClassifier.classify -> waste_preprocess.eval_transform (letterbox_v2)
confidence gate (thresholds.classification_confidence)
is_never_waste gate
classifier.segregation_for (taxonomy)
```

analyze_waste is called with detector= as the only variable. Dedup, crop padding, preprocessing, the confidence gate, the non-waste gate and the taxonomy mapping are production code, identical for both models. Nothing was retrained and no weights or configuration were modified.

## 2. A production bug found before the comparison was valid

`_decode_image` returned **RGB**, but Ultralytics treats a bare ndarray as **BGR** (a file path is loaded with OpenCV). Every frame in production had its red and blue channels swapped. It does not raise — it just detects less.

| Model | detections as RGB (production) | as BGR (correct) |
| --- | --- | --- |
| TACO waste_detector | 62 | **114** |
| COCO yolov8n | 28 | 30 |

On the 59 held-out test images this cost the waste detector **46% of its detections**. The COCO model barely noticed, so the fault looked like a weak new model rather than a pipeline bug. Fixed in `backend/services/water_vision_service.py::_decode_image`; both models were then re-measured. Every table below is post-fix. The pre-fix run is kept at `ab_test_report_rgb_bug.json`.

This also affected the Water Agent, which shares the same decoder.

## 3. Datasets

| Dataset | Images | GT objects | metal_cans | paper_waste | plastic_bags | plastic_bottles |
| --- | --- | --- | --- | --- | --- | --- |
| `taco_test_heldout` | 59 | 107 | 14 | 17 | 52 | 24 |
| `taco_val_realworld_80` | 80 | 135 | 16 | 27 | 68 | 24 |

Both are TACO human annotations read from the existing label files. **No new labels were created.**

**`taco_val_realworld_80` is the 80-image / 135-box set from the earlier diagnosis.** It is the first 80 images of the TACO *val* split. That split was used for checkpoint selection while training the TACO detector, so **it is biased in favour of model B** and is reported as supporting evidence only. `taco_test_heldout` was used for neither training nor checkpoint selection and is the set any decision should rest on.

`ewaste` and `food_waste` are excluded from detector evaluation: 2 and 8 training boxes, zero validation boxes. There is nothing to measure.

## 4. Detector-only results

Identical settings for both models: confidence 0.25, IoU match 0.3, same images, same decoder.

| Dataset | Model | GT objects | Localised | Localisation % | Correctly named | Correct % |
| --- | --- | --- | --- | --- | --- | --- |
| `taco_test_heldout` | coco_yolov8n | 107 | 10 | **9.3%** | n/a¹ | n/a¹ |
| `taco_test_heldout` | taco_waste_detector | 107 | 57 | **53.3%** | 32 | 29.9% |
| `taco_val_realworld_80` | coco_yolov8n | 135 | 18 | **13.3%** | n/a¹ | n/a¹ |
| `taco_val_realworld_80` | taco_waste_detector | 135 | 75 | **55.6%** | 47 | 34.8% |

¹ COCO class names are a different vocabulary (`cup`, `vase`, `bottle`). They are neither right nor wrong about `metal_cans`, so naming accuracy is not defined for model A.

### Per class, held-out test split

| Class | GT | A localised | A % | B localised | B % |
| --- | --- | --- | --- | --- | --- |
| plastic_bags | 52 | 5 | 9.6% | 28 | **53.8%** |
| plastic_bottles | 24 | 2 | 8.3% | 14 | **58.3%** |
| paper_waste | 17 | 0 | 0.0% | 9 | **52.9%** |
| metal_cans | 14 | 3 | 21.4% | 6 | **42.9%** |

## 5. Complete pipeline results

| Dataset | Model | Localised | Pipeline correct | Pipeline correct % |
| --- | --- | --- | --- | --- |
| `taco_test_heldout` | coco_yolov8n | 9.3% | 3/107 | **2.8%** |
| `taco_test_heldout` | taco_waste_detector | 53.3% | 8/107 | **7.5%** |
| `taco_val_realworld_80` | coco_yolov8n | 13.3% | 5/135 | **3.7%** |
| `taco_val_realworld_80` | taco_waste_detector | 55.6% | 10/135 | **7.4%** |

Localisation improves 5.7x on the held-out split; end-to-end correctness improves 2.7x. The gap between those two numbers is the finding — see §7.

## 6. Error breakdown

| Dataset | Model | A missed | B det wrong class | C classifier wrong | D classifier uncertain | E correct |
| --- | --- | --- | --- | --- | --- | --- |
| `taco_test_heldout` | coco_yolov8n | 97 | 0 | 2 | 5 | 3 |
| `taco_test_heldout` | taco_waste_detector | 50 | 2 | 6 | 41 | 8 |
| `taco_val_realworld_80` | coco_yolov8n | 117 | 0 | 1 | 12 | 5 |
| `taco_val_realworld_80` | taco_waste_detector | 60 | 3 | 15 | 47 | 10 |

For model A the dominant bucket is **A: the detector never found the object**. For model B it shifts to **D: the classifier was handed the crop and declined to answer**. The bottleneck moves from detection to classification.

## 7. Detector vs classifier — authority strategies

| Dataset | Strategy | Correct | Wrong | Uncertain | Missed |
| --- | --- | --- | --- | --- | --- |
| `taco_test_heldout` | A — classifier authority (**current production**) | 8 | 8 | 41 | 50 |
| `taco_test_heldout` | B — detector authority | **32** | 25 | 0 | 50 |
| `taco_val_realworld_80` | A — classifier authority (**current production**) | 10 | 18 | 47 | 60 |
| `taco_val_realworld_80` | B — detector authority | **47** | 28 | 0 | 60 |

With the TACO detector, **detector authority is 4x more correct than classifier authority** on the held-out split (32 vs 8 of 107) and 4.7x on the val set (47 vs 10 of 135). Neither strategy was deployed.

### Where they disagree

| Dataset | Agree | Agree correct | Disagree | Detector right | Classifier right | Both wrong |
| --- | --- | --- | --- | --- | --- | --- |
| `taco_test_heldout` | 12 | 9 | 42 | **22** | 6 | 14 |
| `taco_val_realworld_80` | 24 | 15 | 48 | **30** | 4 | 14 |

On the held-out split they disagree 42 times. The detector is right 22 of those, the classifier 6. The current pipeline resolves every one of them in the classifier's favour.

## 8. False positives

No annotated non-waste image set exists in this project. These regions are labelled by the COCO detector itself at >=0.45 confidence, not by a human, which is a weaker basis than the TACO ground truth used elsewhere in this report.

**Unmatched detections** (detections overlapping no annotated object), held-out test split:

| Model | Detections | Matching no annotation |
| --- | --- | --- |
| coco_yolov8n | 26 | 16 |
| taco_waste_detector | 108 | 52 |

TACO produces more unmatched detections in absolute terms because it produces far more detections overall. TACO annotations are also known to be incomplete — an unmatched detection is not necessarily a false positive.

**Ordinary-object probe** (regions COCO labels as person, mouse, chair, cup, laptop, book, plant, TV, phone, table at >=0.45):

| Model | Overlapping detections | Waste class asserted | Withheld as needs_review |
| --- | --- | --- |  --- |
| coco_yolov8n | 15 | 4 | 11 |
| taco_waste_detector | 7 | 3 | 4 |

Neither model asserted a waste class over a **person, mouse, chair, TV, potted plant or phone**. The assertions were `cup`→metal_cans and `book`→paper_waste, which are materially defensible, plus `book`→**ewaste** in both, which is not. TACO produced 7 overlapping detections against COCO's 15, so it fires less often on ordinary objects.

**Caveat on the non-waste gate:** `NEVER_WASTE_CLASSES` matches on the detector's class name. The TACO detector emits only waste class names, so that gate becomes inert under model B — a person would simply not be detected rather than being flagged. That is a real change in safety behaviour, not a neutral one.

## 9. Performance

| Model | Preprocess ms | Inference ms | Postprocess ms | Total ms | Approx FPS | Size |
| --- | --- | --- | --- | --- | --- | --- |
| coco_yolov8n | 1.07 | 19.54 | 0.23 | 20.84 | 48.0 | 6.25 MB |
| taco_waste_detector | 1.06 | 18.51 | 0.25 | 19.82 | 50.5 | 5.94 MB |

Detector only. The classifier, LangGraph and every LLM provider are not invoked. Measured on 30 images after 3 warm-up images, Apple M5 / MPS. The two models are within 1 ms of each other, so latency is not a factor in this decision.

## 10. Visual evidence

```
runs/waste_detection/ab_test/
├── coco/{correct,missed,false_positive}/
├── taco/{correct,missed,false_positive}/
└── pipeline/{classifier_correct,classifier_wrong,uncertain}/
```

Each image is annotated with ground truth, detector class and confidence, IoU, classifier class and confidence, final result and error bucket — all read from the recorded results.

## 11. Summary

```
CURRENT COCO DETECTOR    (held-out test, 107 objects)
  Localization:                 9.3%
  Final pipeline correctness:   2.8%
TACO DETECTOR
  Localization:                 53.3%
  Final pipeline correctness:   7.5%
CLASSIFIER-AUTHORITY (TACO)     Correct: 8/107 = 7.5%
DETECTOR-AUTHORITY   (TACO)     Correct: 32/107 = 29.9%
FALSE POSITIVE (unmatched dets) COCO: 16/26   TACO: 52/108
LIVE INFERENCE                  COCO: 19.54 ms   TACO: 18.51 ms
```

### Where TACO improves the pipeline

- Localisation on the held-out split rises from 9.3% to 53.3% (5.7x). This was the stage the earlier diagnosis identified as the bottleneck.
- `paper_waste` goes from 0/17 localised to 9/17 — COCO has no concept for it at all.
- It fires less often on ordinary objects (7 overlapping detections vs 15).
- It is marginally faster and smaller.

### Where it regresses or fails to deliver

- End-to-end correctness rises only 2.8% → 7.5%, because the classifier now refuses 41 of the 57 crops the detector correctly localises (bucket D). **Most of the detector gain is discarded downstream.**
- `C_classifier_wrong` rises from 2 to 6 on the held-out split: more crops reaching the classifier means more chances to be wrong.
- The `NEVER_WASTE_CLASSES` safety gate becomes inert, since it matches on COCO class names.
- Both models still assert `book`→`ewaste`.

### Classes that remain weak

- `plastic_bags`: 28/52 localised, the largest class and barely over half.
- `paper_waste`: 9/17, and mAP50 0.208 at training time — the weakest trained class.
- `ewaste` and `food_waste`: **not evaluated and not trainable from this data** (2 and 8 training boxes, 0 validation boxes). The detector must not be described as covering six classes.

### Is more detection data needed

Yes. 50 of 107 held-out objects are still missed entirely, and two of the six taxonomy classes have no usable detection data at all. Separately, the largest single win available right now requires no new data: resolving the 42 detector/classifier disagreements in the detector's favour would take correctness from 8/107 to 32/107 on evidence already collected.

