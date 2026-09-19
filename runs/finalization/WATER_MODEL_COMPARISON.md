# Water detector A/B — COCO YOLOv8n vs TUD-GV litter detector

**Date:** 2026-09-19 · Both models run through the same decoder, same threshold (0.25), same
images. **No detection below was drawn, edited or added by hand.**

---

## 1. Models

| | CURRENT (production) | CANDIDATE |
| --- | --- | --- |
| Weights | `backend/models/yolov8n.pt` | `runs/water/litter_detector/weights/best.pt` |
| Architecture | YOLOv8n | YOLOv8n |
| Training | COCO, 80 general classes | Fine-tuned on TUD-GV, **1 class: `litter`** |
| Data | — | 1,057 train / 298 val / 146 test, session-level leakage-safe split |
| Role | General object detector | **PROVISIONAL WATER LITTER DETECTOR** |
| Promoted | Yes (current default) | **No** |

The candidate is trained by `training/water/train_water_detector.py` from the audited
`TUDGV_SPLIT_MANIFEST.json`. The source dataset is untouched: the split is materialised as
symlinks.

## 2. The exact contaminated image

`image copy 3.png` — a canal surface packed with plastic bottles and debris.

| | Detections | Classes |
| --- | --- | --- |
| **CURRENT** | **0** | — |
| **CANDIDATE** | **9 litter** | confidence 0.27 – **0.81** |

At the production threshold the current model reports **nothing** on an image roughly half
covered in bottles. Its only sub-threshold hypotheses are `bird` (0.089) and `kite` (0.015); it
never proposes `bottle` at any threshold. See `WATER_CURRENT_FAILURE.md`.

## 3. All candidate images

| Image | Content | CURRENT | CANDIDATE |
| --- | --- | --- | --- |
| `image copy 3.png` | Canal packed with bottles | **0** | **9 litter** (max 0.81) |
| `image copy 4.png` | Industrial canal + shoreline litter | 1 × `person` | **6 litter** (max 0.89) |
| `image copy 2.png` | Polluted waterway | `person` ×3, `cow` ×2, `horse`, `bear` | **13 litter** (max 0.92) |
| `image.png` | Degraded river / restored river | 2 × `person` | **12 litter** (max 0.71) |

The current model's output on `image copy 2.png` is worth reading twice: seven detections, of
which two are cows, one a horse and one a bear, on a photograph of a polluted waterway. Those are
correctly categorised `non_pollution_object` by the semantic layer and contribute nothing to the
risk — but they are the entirety of what the detector had to say about that scene.

## 4. False positives — the part that matters

**The candidate has a measured false-positive problem on clean water, and it must not be promoted
without saying so.**

`image.png` is a two-panel composite: a degraded river on the left, a **pristine restored river**
on the right — clear water, greenery, wildflowers, no litter of any kind. Cropping the panels:

| Crop | Expected | CANDIDATE |
| --- | --- | --- |
| `image.png` LEFT (degraded, litter present) | detections | 9 |
| **`image.png` RIGHT (restored, visibly clean)** | **none** | **6 detections, up to 0.84** |
| `image copy 3.png` LEFT (bottles) | detections | 14 |
| `image copy 3.png` RIGHT (algae, no discrete litter) | none | **0** ✓ |

Six confident detections on a photograph containing no litter. The model has most likely learned
"small high-contrast object against water and vegetation" and is firing on flowers, rocks and
foliage.

This is **exactly what blocker B1 predicted**. TUD-GV contains **zero** verified-clean-water
frames, so the model was never shown what an absence of litter looks like, and its
false-positive rate has never been measurable. It still is not — one two-panel image is an
illustration, not a measurement.

### In-domain behaviour is correct

| Check | Result |
| --- | --- |
| TUD-GV held-out test frame `exp121_105.jpg` | ground truth 3 boxes → **3 detected** |
| Validation (298 images, 1,347 boxes) | P 0.887 · R 0.840 · **mAP50 0.936** · mAP50-95 0.668 |

Within the canal-surface domain it was trained on, the candidate is accurate. Outside it, it
over-fires.

## 5. Which failure is worse

Both models fail; they fail in opposite directions.

| | CURRENT | CANDIDATE |
| --- | --- | --- |
| Failure mode | **False negative** — misses all litter | **False positive** — reports litter on clean water |
| On the demo image | "No detectable visual litter" on a canal of bottles | 9 litter objects, correctly |
| On clean water | Correct (finds nothing) | **Wrong** (6 detections) |
| Consequence | Silent false reassurance | A verification the user did not need |

The system already refuses to say water is clean, and already routes visible litter to
*"observed — chemical contamination not established — verify next"*. A false positive therefore
surfaces as a recommendation to check; a false negative surfaces as nothing at all, on the exact
case the product exists to catch.

## 6. Recommendation

**Make the candidate available; do not silently make it the default.** It is a configuration
change, not a code change — the Water Vision provider is already env-driven:

```bash
# in backend/.env — opt in to the provisional litter detector
YOLO26_MODEL_PATH=../runs/water/litter_detector/weights/best.pt
```

Whichever is configured, **Water stays `PARTIALLY_READY`**:

- With COCO: it cannot see litter at all.
- With the candidate: it sees litter well in-domain, and over-fires on clean water by an
  unmeasured amount.

Neither is a validated production water-pollution detector, and the candidate must not be
described as one. Closing that gap needs clean-water negatives (blocker B1) — acquisition, not
training.

## 7. What was NOT done

- No detection was drawn, edited, added or removed by hand.
- The source dataset was not modified; the split is symlinks from the audited manifest.
- The production model was not overwritten.
- No threshold was lowered to improve any result.
- No additional dataset was downloaded.
