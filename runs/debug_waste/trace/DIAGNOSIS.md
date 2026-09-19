# Waste Agent false positives — traced production path

Reproduce: `python backend/scripts/trace_waste_inference.py <image>`
Artefacts: `runs/debug_waste/trace/<stem>/{A_raw_detector_vs_coco.png, crop_*.png, trace.json}`

## 1. The production path, as it actually runs

```
RealWasteDetection.tsx:60          api.segregateWaste(file, …)
apiClient.ts:151                   POST /api/waste/segregate  (multipart, field "file")
main.py:629  segregate_waste       validate_image -> run_in_threadpool(analyze_waste)
waste_pipeline.py:117 analyze_waste
  water_vision_service.py:310        get_waste_pipeline_detector()
                                       -> LocalYoloDetector(backend/models/waste_detector.pt, conf=0.25)
  water_vision_service.py:148        LocalYoloDetector.detect -> _decode_image (BGR ndarray) -> YOLO.predict
  waste_pipeline.py:61               _deduplicate  (class-agnostic NMS, IoU 0.7)
  waste_pipeline.py:97               _crop         (pad 6%, MIN_CROP_PIXELS 24, NO max-size gate)
  waste_classifier.py:181            WasteClassifier.classify (MobileNetV3, 8 classes, threshold 0.60)
  waste_pipeline.py:204              is_never_waste(detection.class_name)   <-- INERT, see §3
  waste_pipeline.py:289              _apply_detector_authority              <-- detector class wins
  waste_classifier.py:169            segregation_for -> training/config/waste_categories.json
RealWasteDetection.tsx:160-172     box drawn from detection.bbox / result.imageWidth|Height
RealWasteDetection.tsx:174         box LABEL = detection.detectedObject  (raw detector class, verbatim)
```

The frontend performs **no** relabeling. The string on the box is the detector's own class name.

## 2. Which model produced `plastic_bags` / `paper_waste`

Runtime metadata, printed from the production accessor:

```
settings.waste_detector_model_path = 'models/waste_detector.pt'
resolved                           = backend/models/waste_detector.pt
detector.model (UI label)          = waste_detector
model.task                         = detect
model.names (6)                    = {0: ewaste, 1: food_waste, 2: metal_cans,
                                      3: paper_waste, 4: plastic_bags, 5: plastic_bottles}
trained from                       = backend/models/yolov8n.pt
trained on                         = datasets/taco_yolo/data.yaml
train metrics                      = precision 0.406  recall 0.373  mAP50 0.341  mAP50-95 0.222
classifier weights                 = runs/classification/best.pt  (8 classes, threshold 0.60)
```

`plastic_bags` and `paper_waste` are **detector class names**, not classifier output and not a
taxonomy remap. They reach the UI through `record["detected_object"]`, which is the literal YOLO
class, and again through `_apply_detector_authority` setting `classification = detector_class`
with `label_source="detector"`.

The intended architecture (class-agnostic YOLO localisation -> material classifier) is **not** what
runs. The localiser is itself a 6-class material detector, so stage 1 already emits a material
label and stage 2 is reduced to a tie-break.

## 3. Why nothing rejects a person-shaped box

`waste_pipeline.py:204` is the only validity gate on a localisation:

```python
if record.get("classification") and is_never_waste(detection.class_name):
```

`is_never_waste` matches `detection.class_name` against `NEVER_WASTE_CLASSES`
(`core/investigation.py:76`), a list of **COCO** names — person, dog, car, bench…

`waste_detector.pt` can only ever emit one of its six waste class names. The set intersection with
`NEVER_WASTE_CLASSES` is empty, so **the gate cannot fire in production**. This was predicted in
`runs/waste_detection/AB_TEST_REPORT.md` §8 ("the gate becomes inert under model B — a person would
simply not be detected rather than being flagged"). The second half of that assumption is false:
the detector does fire on people.

There is also no maximum-box-area gate anywhere — `MIN_CROP_PIXELS = 24` is the only geometry
constraint, and it has no upper bound.

## 4. Evidence — reproduction (`runs/debug_waste/trace/exif_probe/`)

Raw detector output, before any classification:

| # | class | conf | xyxy | crop | % of frame | never_waste gate |
|---|---|---|---|---|---|---|
| 1 | metal_cans | 0.962 | [149.7, 192.1, 420.8, 311.6] | 271x120 | 10.5% | **False** |
| 2 | paper_waste | 0.436 | [1.7, 0.0, 286.7, 164.6] | 285x165 | 15.3% | **False** |
| 3 | paper_waste | 0.283 | [201.0, 194.1, 640.0, 480.0] | 439x286 | **40.9%** | **False** |

COCO yolov8n on the same pixels, as an independent read of what is there:

| # | class | conf | xyxy |
|---|---|---|---|
| C1 | **person** | 0.705 | [0.3, 0.2, 378.8, 154.8] |
| C2 | **person** | 0.407 | [533.5, 1.4, 639.7, 477.5] |

Overlap:

```
waste #2 'paper_waste' (0.436)  vs  person (0.705)   IoU = 0.718   person 75% inside the waste box
waste #3 'paper_waste' (0.283)  vs  person (0.407)   IoU = 0.206   person 60% inside the waste box
waste #1 'metal_cans' (0.962)   -> the bottle, mis-named (it is a bottle, not a can)
```

Final pipeline output — what the UI renders:

```
WASTE-DET-002 bbox=[1.7, 0.0, 286.7, 164.6]   <- 72% IoU with a person
  detected_object = 'paper_waste'   det_conf = 0.436
  classification  = 'paper_waste'   clf_conf = 0.6408
  segregation = biodegradable   status = CONFIRMED
WASTE-DET-003 bbox=[201.0, 194.1, 640.0, 480.0]   <- 41% of the frame, background
  detected_object = 'paper_waste'   det_conf = 0.283
  classification  = 'paper_waste'   clf_conf = 0.7306
  segregation = biodegradable   status = CONFIRMED
summary: non_waste_objects = 0        <- the system does not know it saw two people
```

Classifier run alone on a controlled person crop confirms it cannot save the pipeline:

```
coco_1_person  378x154 -> paper_waste  top3 = [paper_waste 0.621, food_waste 0.177, wood_waste 0.048]
```

0.621 is above the 0.60 threshold, so both stages independently assert `paper_waste` on a person.
The confidence gate is not the missing check; **a localisation-validity check is.**

Controlled detector runs (crop -> detector, `runs/debug_waste/trace/person_and_aerosol_can/`):

```
FULL IMAGE        -> metal_cans 0.938 (10% of frame), paper_waste 0.384 (39% of frame)
PERSON crop       -> no detections
BOTTLE crop       -> plastic_bottles 0.877 (95% of crop), metal_cans 0.293
BACKGROUND crop   -> no detections
```

The bottle **is** detectable — `plastic_bottles` at 0.877 when it fills the crop. At full-frame
scale the same object is named `metal_cans` and the surrounding scene generates large low-confidence
`paper_waste` boxes. The failure is scale- and context-dependent, consistent with mAP50 0.341 on an
outdoor-litter training set being applied to an indoor scene.

## 5. Second, independent defect: EXIF orientation

`_decode_image` (`water_vision_service.py:261`) and `analyze_waste`'s own
`Image.open(...).convert("RGB")` both skip `ImageOps.exif_transpose`. There is no `exif` reference
anywhere in `backend/`, `frontend/src/` or `training/`.

Measured on a phone-style JPEG (landscape buffer + `Orientation=6`):

```
backend _decode_image shape (H,W,C) = (480, 640, 3)  -> API reports imageWidth=640 imageHeight=480
browser <img src=blob:> renders                       -> 480 x 640  (portrait; EXIF applied)
ImageOps.exif_transpose                               -> 480 x 640
```

`RealWasteDetection.tsx:167-170` positions each box as `x1 / result.imageWidth` of the **rendered**
element. When the two disagree, every box is placed and scaled wrongly against the photo the user
is looking at — and a box at `x2 = 640` becomes a full-width overlay. The detector is also running
on a sideways scene, which is out of distribution on its own.

This does not apply to an image with no EXIF orientation tag (or orientation 1). It applies to
essentially every photo taken on a phone in portrait.

## 6. What is NOT happening

- The classifier is **not** being run as a detector. Every box originates in
  `LocalYoloDetector.detect` from `box.xyxy`; `_crop` only reads boxes.
- No synthetic or derived boxes are generated anywhere in the waste path.
- The frontend does not relabel, remap or invent boxes.
- The taxonomy (`training/config/waste_categories.json`) only maps class -> category/handling; it
  never changes which class was predicted.

---

# Changes made

Nothing was retrained. No existing threshold was changed (`detection_confidence` 0.25 and
`classification_confidence` 0.60 in `training/config/waste_categories.json` are untouched). The
risk engine, RAG/LangGraph and the UI were not modified.

## 1. EXIF orientation — `water_vision_service.py`

New `exif_upright()`, applied in `_decode_image` and in `waste_pipeline.analyze_waste`'s own decode
(the crops must come from the frame the boxes were drawn on) and in `waste_debug.py`'s saved
original. A missing or malformed tag leaves the image untouched.

`_decode_image` is shared with the Water Agent, so its inputs change too: it now also runs upright.

## 2. Localisation gate — new `services/waste/waste_localisation.py`

```
DETECTION -> verify_localisation -> crop -> material classification -> final label
```

Runs **before** the crop, so the classifier is never asked about a region that is not a waste
object. Two independent checks:

- **`degenerate_box`** — a box spanning >= 92% of the frame on both axes is a region, not an
  object. From the TACO label distribution (1814 boxes): p99.5 width 0.904, p99.5 height 0.837,
  and exactly 1 box (0.06%) clears 0.92 on both axes. Deliberately **not** a size ceiling: 1.9% of
  real annotated litter covers more than 40% of its frame and the largest covers 94%, so refusing
  large boxes would discard the close-up shots this feature exists for.
- **`non_waste_object`** — one yolov8n pass per upload (~20 ms, `AB_TEST_REPORT.md` §9) supplies a
  second opinion. A waste box overlapping a `NEVER_WASTE_CLASSES` object at IoU >= 0.40, or with
  >= 70% containment either way, at >= 0.40 confidence, is refused. This restores what
  `is_never_waste` was for, using the only model that has a name for "person".

Skipped when the detector has already named something that cannot be waste — the existing
post-classification `is_never_waste` path is better there, because it keeps the classifier's guess
visible as a candidate. COCO-detector behaviour is therefore unchanged.

A refused box is still reported with its real coordinates and confidence; only the segregation
claim is withheld, and the message names the measurement that refused it.

New response fields: `detection.localisation_rejected` and `summary.localisations_rejected`.
`summary.non_waste_objects` now also counts gate refusals, so it stops reading 0 on a frame full
of people.

## 3. Verified

`backend/tests/test_waste_localisation.py` — 16 tests covering the geometry bar, the veto,
containment vs IoU, the confidence floor on a veto, the classifier not being called on a refused
region, refusals still being reported and counted, a valid localisation still reaching the
classifier, the EXIF transpose, and a malformed EXIF block not failing the decode.

Full suite: 442 passed.

End to end on the reproduction:

| Input | Reported frame | Result |
|---|---|---|
| upright original | 480x640 | bottle + one uncertain box; no false assertion |
| sideways, no EXIF tag | 640x480 | person box **REFUSED[non_waste_object]**, counted in `non_waste_objects` |
| phone portrait (EXIF=6) | **480x640** (was 640x480) | one box, both `paper_waste` false positives gone |

## 4. Known remaining gap

On the sideways frame a `paper_waste` box covering 41% of the frame over desk/background is still
asserted. It is not degenerate (69% x 60% span) and COCO recognises nothing there, so neither check
applies. This is the detector's own false positive — mAP50 0.341, trained on outdoor litter — and
it is a detection-quality problem, not a gate problem. Tightening either bar to catch it would
start refusing real close-ups. Recorded here rather than papered over.
