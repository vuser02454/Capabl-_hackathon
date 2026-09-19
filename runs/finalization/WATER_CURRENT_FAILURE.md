# Water Agent — current failure, reproduced

**Date:** 2026-09-19 · Reproduced against the running stack (backend :8000, frontend :5173).
**Nothing was changed to produce this document.**

---

## 1. The question

> Why does the current system detect a bird but miss the visible litter?

Answered below with measurements, not inference.

## 2. Reproduction

Every candidate water image in the repository, through the live
`POST /api/water/analyze-image` at the production confidence threshold (0.25):

| Image | Content | Objects | Litter | Detections |
| --- | --- | --- | --- | --- |
| `image copy 3.png` | **Canal surface packed with plastic bottles and debris** | **0** | **0** | *(none)* |
| `image.png` | Degraded river + restored river, birds in sky | 2 | 0 | person 0.66, person 0.48 |
| `image copy 2.png` | Polluted waterway | 7 | 0 | person ×3, cow ×2, horse, bear |
| `image copy 4.png` | Industrial canal, shoreline litter | 1 | 0 | person 0.36 |
| `image copy.png` | Water scene | 1 | 0 | clock 0.25 |

**Not one litter detection across five images, three of which are visibly full of litter.**

`image copy 3.png` is the strongest case: roughly half the frame is plastic bottles in a canal,
and the detector returns **nothing at all**.

## 3. The bird, isolated

Sweeping the confidence threshold on `image copy 3.png` (414×740, BGR, YOLOv8n, `models/yolov8n.pt`):

| Threshold | Detections | Classes |
| --- | --- | --- |
| **0.25 (production)** | **0** | — |
| 0.10 | 0 | — |
| 0.05 | 2 | **bird** 0.089, **bird** 0.051 |
| 0.01 | 11 | **bird ×9**, **kite ×2** |

**At no threshold does the model propose `bottle`** — even though `bottle` is one of COCO's 80
classes and the image is full of them.

This is the reported "Bird — 40%" behaviour in its pure form: the model's only response to a
surface of floating litter is a weak `bird` hypothesis. The bird is not a false positive to be
filtered. **It is the model's best available guess for "small irregular object on textured
natural background", because it has no better one.**

## 4. Root cause — domain mismatch, not threshold and not taxonomy

The detector in production is **COCO-pretrained YOLOv8n** (`YOLO26_MODEL_PATH=models/yolov8n.pt`),
a general-purpose 80-class object detector. It was never trained on floating litter.

COCO's `bottle` class is learned from bottles that are **upright, isolated, unoccluded, close to
camera, indoors or on tables**. Floating litter is the opposite on every axis:

| COCO `bottle` prior | Floating litter in `image copy 3.png` |
| --- | --- |
| Upright, canonical pose | Arbitrary rotation, lying flat on water |
| Isolated, clear boundaries | Densely packed, mutually occluding |
| Fully visible | Partially submerged, half the object missing |
| Large in frame | Tens of pixels across |
| Indoor / tabletop context | Outdoor water surface, specular highlights, foam |

The activations never reach the `bottle` head with any confidence. What survives is a diffuse
"small blob on natural texture" response, and among COCO's 80 classes the nearest prior for that
is `bird`.

### What this rules out

| Hypothesis | Verdict |
| --- | --- |
| Confidence threshold too high | **Ruled out.** At 0.01 there are still zero bottles — only birds and kites. |
| Semantic taxonomy filtering litter out | **Ruled out.** The taxonomy never sees a litter class; the detector does not emit one. |
| RGB/BGR channel swap | **Ruled out.** Decoder returns BGR, as Ultralytics expects (fixed previously and tested). |
| Preprocessing / image size | **Ruled out.** Same path as every other image; the detector runs and returns cleanly. |
| A prompt or LLM problem | **Ruled out.** No language model participates in detection. |

### What it confirms

This is a **model/dataset/domain problem**, exactly as framed. The only fix that addresses it is
a detector trained on floating litter. Nothing in prompting, thresholding, filtering or UI
wording can make a model report a class it has no representation for.

## 5. What the system currently gets RIGHT

Worth stating, because it constrains the fix: the semantic layer is behaving correctly
throughout. Every non-litter detection above is categorised `non_pollution_object` or
`unclassified_object`, contributes **0** to the pollution count, and leaves water risk at the
sensor-only 0.55. No bird, person, cow or clock inflates a pollution score.

So the failure is **one-sided**: the system does not report false pollution. It fails to report
**true** pollution — a false-negative problem, not a false-positive one.

That is the safer direction to fail in, and it is still a failure.

## 6. Consequence for the claim the product makes

With this detector the Water Agent can honestly say:

> "No detectable visual litter" — meaning *this model found none*.

It **cannot** say:

> "No visible litter is present."

On `image copy 3.png` those two statements differ completely, and the second would be false.

## 7. Next step

Train a provisional single-class `litter` detector on the audited TUD-GV split
(`TUDGV_SPLIT_MANIFEST.json`, session-level, leakage-safe: 1,057 / 298 / 146 images) and A/B it
against the current model on the exact image above.

Promotion is conditional on evaluation, not on producing more boxes. See
`WATER_MODEL_COMPARISON.md`.
