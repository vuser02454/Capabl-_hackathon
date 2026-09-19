# Existing Water Agent architecture — what IWHR would plug into

Phase 0 of the IWHR integration audit. Read before designing any integration, because the
answers below constrain what a floating-object detector can and cannot change.

Nothing in this document was modified. It is a survey of the code as it stands.

## 1. How water images enter the system

Three entry points, all `POST`, all going through the same decoder and detector:

| Endpoint | `backend/main.py` | Purpose |
| --- | --- | --- |
| `/api/water/analyze-image` | 351 | Full Water Agent run with a photo attached |
| `/api/water/scan-frame` | 537 | Detector-only verdict, polled by the live camera |
| `/api/water/match-frame` | 575 | Reference-dataset appearance match only (no detector) |

The Water Agent accepts `WaterAgentInput(location, image: Optional[WaterImage])`. A plain
`LocationContext` still works, so both orchestrators call it unchanged — **the image path is
optional and additive**. `/api/analyze` never supplies an image, so a LangGraph run carries no
vision signal at all unless the caller used the image endpoint.

## 2. Decoding and preprocessing

One decoder: `water_vision_service._decode_image`, shared by the water and waste image paths.

It returns an HxWxC ndarray handed straight to `model.predict(image, conf=...)`. There is **no
resize, letterbox, normalisation or aspect-ratio handling in our code** — Ultralytics does its own
letterboxing internally. This is the opposite of the waste classifier, which owns its preprocessing
(`training/waste_preprocess.py`).

**Channel order was a real bug here.** `_decode_image` returned RGB while Ultralytics treats a bare
ndarray as BGR; every frame had red and blue swapped. It does not raise, it just detects less — a
TACO-trained detector lost 46% of its detections. Already fixed, but it is the reason any new
detector must be evaluated through this decoder rather than on files read separately.

Frame dimensions are taken from the decoded array (`image.shape`), never from what the model
reports.

## 3. What the Water Agent treats as evidence

Three strictly separated signals. The separation is the design, and a detector change touches
only the second one:

```
measurements / ph / turbidity / temperature / tds  <- sensors, monitoring stations, dataset
visual_pollution                                   <- what the detector could SEE
dataset_match                                      <- which labelled reference frames it LOOKS LIKE
```

`agents/water_agent.py` docstring states it directly: a vision model cannot measure pH, turbidity,
dissolved oxygen or chemistry, and the agent never lets it populate those fields. **A floating-object
detector is therefore incapable of improving the chemical half of the water report, by construction.**

## 4. How the visual signal reaches the score

`water_agent.py:189-217`. Vision **escalates only**:

```
score = clamp(quality_score + water_visual_weight * visual_score)
```

- `water_visual_weight` (`ECOSENTINEL_WATER_VISUAL_WEIGHT`, default **0.25**) is the maximum
  escalation at maximum visual density.
- Visible pollution is corroborating evidence of harm; **its absence is not evidence of safety**,
  so the term can never reduce a sensor-derived score.
- When vision does not run, the combined score *is* the water-quality score.
- The pre-blend `water_quality_score` is surfaced **only when the blend actually moved the number**,
  so the escalation stays auditable.

`visual_score` itself (`water_vision_service.score_detections`, line 370):

```
visual_score = clamp(len(detections) / water_visual_count_reference)    # default reference 20
```

A plain normalised object count. No per-class severity weighting, deliberately — the class list is
model-defined and no class is assumed worse than another.

> **Finding worth carrying into the integration.** `score_detections` counts **every** detection,
> not only pollution-relevant ones. `is_pollution_class` is applied in `/api/water/scan-frame`
> (`main.py:557`) but **not** in the Water Agent blend path. With the COCO detector currently
> served, a `person` or `boat` in the frame therefore contributes to `visual_score` exactly as a
> bottle does. A single-class `floater` detector would make every detection genuinely
> pollution-relevant and this discrepancy would disappear — but that is a behaviour change to
> record, not a silent side benefit.

## 5. Confidence

Confidence is **not** derived from the detector. `water_agent.py:253`:

```
confidence = clamp(base - MISSING_PENALTY * missing)
```

It reflects how many expected water parameters were actually reported. Per-detection confidence
lives on `VisionDetection.confidence` and the frame-level threshold on
`WaterVisionReport.confidence_threshold` (`YOLO_CONFIDENCE_THRESHOLD`, default 0.25), but neither
feeds the agent's `confidence` field.

## 6. Interface to LangGraph and the risk engine

```
WaterSensorProvider + WaterVisionDetector
  -> WaterQualityAgent.run()
  -> WaterAgentResult (typed Pydantic)
  -> run_water node (asyncio.to_thread, own timeout)
  -> CoordinatorInput  { location, air, water, waste }
  -> deterministic core/risk.py
```

The Coordinator sees only the typed report and a location label — never coordinates, providers or
raw imagery. `WaterVisionReport` travels inside `WaterAgentResult` for the frontend, but the fields
the risk engine consumes are `risk_level`, `score`, `confidence`, `measurements`, `findings`.

The detector is **injected**: `WaterQualityAgent(provider, vision=...)` and
`build_report(detector, ...)` take the detector as a parameter. This is the same injection point the
waste detector A/B used (`analyze_waste(detector=...)`), so **an IWHR detector can be evaluated
against production code without changing a line of it.**

## 7. Which method is in use — all three, for different questions

| Method | Where | Question answered |
| --- | --- | --- |
| **Detection** (YOLO) | `water_vision_service.py` | What objects are visible in this frame? |
| **Reference-image similarity** | `water_dataset_match_service.py` | Which labelled frames does this photo resemble? |
| Classification | — | Not used on the water path (the 8-class classifier is waste-only) |

The similarity matcher is **not** a model: 2x2 spatial HSV colour histograms plus a 64-bit dHash,
indexed in `backend/data/water_dataset_index.npz`. Calibrated and documented as weak — ~71% exact
class accuracy, and only **~15-33% recall on clean water**, because only 4 of 29 source clips are
clean. It never moves the risk score.

## 8. Water datasets already present

| Dataset | Location | Type | Role |
| --- | --- | --- | --- |
| Alta / Media / Baja reference frames | `datasets/` | Labelled **classification** frames (6,515) | Appearance matching only; **no bounding boxes** |
| Water potability dataset | `backend/data/` | Tabular | Historical/ML assessment fallback |
| IWHR (this audit) | `water_datasets/27376851/` | **Detection**, Pascal VOC | Not integrated |

**There is no existing water *detection* dataset.** The Alta/Media/Baja frames carry a
contamination *level* per frame and no boxes, so no water detector has ever been trained in this
project. IWHR would be the first.

## 9. Reusable YOLO training and inference pipeline — yes, do not duplicate

An end-to-end detection pipeline already exists from the waste work and generalises:

| Reusable | Path | Notes |
| --- | --- | --- |
| Dataset quality report | `training/validate_dataset.py` | Duplicate groups, imbalance, unusable files. Written for **classification** folders — needs a detection-aware variant, not a rewrite |
| VOC/COCO -> YOLO conversion | `training/convert_taco_to_yolo.py` | COCO JSON input; IWHR is **Pascal VOC XML**, so the reader differs. Its discipline — unmapped categories excluded *and counted*, split by image id, leakage check, JSON report — is the pattern to follow |
| Detector training | `training/train_waste_detector.py` | Ultralytics, seeded, writes `training_manifest.json`. Reusable as-is with a different `data.yaml` |
| A/B harness | `training/ab_test_detectors.py` | Compares two detectors **through the production call path**. Written around `analyze_waste`; the water equivalent is `build_report(detector, ...)` |
| Serving | `water_vision_service.LocalYoloDetector` | Already provider-agnostic: point `YOLO26_MODEL_PATH` at any Ultralytics weights |

The upstream detector repos shipped inside IWHR (`detectors/yolov5-7.0.zip`, `ultralytics-main.zip`,
`YOLOv6`, `yolov7`, `yolov9`, `CenterNet2`, `faster-rcnn`, `retinanet`, `ssd.pytorch` — 76 MB of
zipped third-party source) are **not needed**: EcoSentinel already depends on Ultralytics. They were
left unextracted.

## 10. Constraints any IWHR integration inherits

1. Detection is injected, so it can be A/B tested without touching production. Do that first.
2. Vision **escalates only**, capped at `water_visual_weight` (0.25).
3. Vision cannot touch pH, turbidity, temperature or TDS.
4. `visual_score` is a raw count over a reference of 20 — swapping in a detector that finds far more
   objects per frame **changes the score distribution even with identical weights**. IWHR images
   average many floaters per frame (one sampled annotation carries 25 objects), so this is a live
   risk, not a hypothetical.
5. Floating debris is visual evidence only. The project already refuses to read it as chemical
   contamination, and that refusal must survive.
