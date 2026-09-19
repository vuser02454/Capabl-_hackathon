# Water Detector — Final Model Report

**Date:** 2026-09-19 · Companion to `WATER_CURRENT_FAILURE.md` and `WATER_MODEL_COMPARISON.md`.

---

## 1. Decision

**The provisional TUD-GV litter detector is NOT promoted to default.** It is trained, evaluated,
retained and documented, and can be enabled with one configuration line. Water remains
**PARTIALLY_READY** under either model.

## 2. Why not promoted

Both models fail, in opposite directions, and neither failure is measured well enough to call the
matter settled.

| | CURRENT (COCO yolov8n) | CANDIDATE (TUD-GV litter) |
| --- | --- | --- |
| Litter on `image copy 3.png` | **0 detections** | **9 detections**, max 0.81 |
| Validation (TUD-GV, 298 img) | n/a — different vocabulary | P 0.887 · R 0.840 · **mAP50 0.936** |
| TUD-GV test frame `exp121_105` | — | 3 ground truth → **3 detected** |
| **Visibly clean restored river** | correct (finds nothing) | **6 false positives, up to 0.84** |
| Failure mode | false negative — misses everything | false positive — sees litter that is not there |

The candidate is decisively better at the job. It also over-fires on clean water by an amount
nobody can currently quantify, because **TUD-GV contains zero verified-clean-water frames**
(blocker B1). Promoting a detector whose false-positive rate is unmeasured, on the single most
common real-world input, is not a decision this evaluation supports.

## 3. Model card — PROVISIONAL WATER LITTER DETECTOR

| Field | Value |
| --- | --- |
| Weights | `runs/water/litter_detector/weights/best.pt` |
| Architecture | YOLOv8n |
| Pretrained from | `yolov8n.pt` (COCO) |
| Classes | 1 — `litter` |
| Dataset | TUD-GV (CC BY 4.0, Zenodo DOI `10.5281/zenodo.13730228`) |
| Split | Session-level, from `TUDGV_SPLIT_MANIFEST.json` — **not** a random frame split |
| Train / Val / Test | 1,057 / 298 / 146 images · 6,330 / 1,347 / 504 boxes |
| Image size | 640 |
| Batch | 16 · Optimizer AdamW (auto), lr 0.002 · Seed 0 · Device MPS |
| Source dataset | **Unmodified** — split materialised as symlinks |
| Production weights | **Not overwritten** |

### Why the split is session-level

TUD-GV frames are subsampled video. 34.78% of images have a near-duplicate at dHash ≤ 2, and
98.3% of those pairs are intra-session. A random frame split would place a frame and its
near-twin either side of the boundary and report a test score that is largely memorisation. The
manifest groups by connected components of (session ∪ near-duplicate); this training script only
reads it and never invents a split.

## 4. Limitations — none of these are closed

1. **No clean-water negatives (B1).** False-positive rate on clean water is **unmeasured**.
   Demonstrated qualitatively: 6 detections on a photograph with no litter in it.
2. **Single class.** `litter` only — no distinction between bottle, bag and debris.
3. **One domain.** Canal surfaces at a fixed vantage. Generalisation to rivers, lakes, coastline
   and other camera geometries is unmeasured.
4. **Out-of-domain over-firing.** Likely triggered by small high-contrast objects against water
   and vegetation — flowers, rocks, foliage.
5. **Not a validated production detector**, and must not be described as one.

## 5. What would close the gap

Acquisition, not training: **≥300 verified-clean water frames** meeting
`NEGATIVE_DATA_REQUIREMENTS.md` N1–N13, with zero Hamming ≤ 2 matches against the 5,701 audited
positives. With those, the false-positive rate becomes measurable, `count_reference` (blocker B2)
becomes calibratable, and the promotion question becomes answerable on evidence.

## 6. Enabling it

```bash
# backend/.env
YOLO26_MODEL_PATH=../runs/water/litter_detector/weights/best.pt
```

No code change — the Water Vision provider is already env-driven, and the semantic layer,
evidence normaliser and risk engine are unchanged. The detector emits `litter`, which
`is_pollution_class` already maps to `visible_surface_litter`.

**If enabled, the claim must change with it.** "Visible litter detected" becomes supportable;
"no litter present" and any clean-water assurance do not.

## 7. Training status

Training was still in progress when this was written (8 of 60 epochs, best validation mAP50
**0.943**, improving). All figures above use the best checkpoint at that point. Final held-out
TEST metrics are written to `runs/water/litter_detector/test_metrics.json` on completion. The
conclusion is not expected to change: strong in-domain, over-fires on clean water, not promotable
without B1.
