# Direct multi-class YOLO vs. localise-then-classify — data availability and architecture

Audit only. Nothing was trained, converted, merged or modified. All counts are read from label
files on disk and cross-checked against the existing audits
(`runs/waste_detection_dataset_report.json`, `training/config/taco_taxonomy_mapping.json`,
`runs/water/flow_integration/FLOW_DATASET_AUDIT.md`,
`runs/water/tudgv_integration/TUDGV_READINESS_REPORT.md`). No label was invented or inferred.

## 0. Correction to the premise

The comparison as posed does not describe what is deployed.

```
stated CURRENT : TACO single-class litter detector -> localisation -> 8-class material classifier
actual CURRENT : TACO SIX-class material detector  -> its own class IS the label (detector authority)
                 -> classifier runs, and is overruled whenever the two disagree
```

Runtime check: `YOLO('backend/models/waste_detector.pt').names` =
`{0: ewaste, 1: food_waste, 2: metal_cans, 3: paper_waste, 4: plastic_bags, 5: plastic_bottles}`,
`task='detect'`. `_apply_detector_authority` (`backend/services/waste/waste_pipeline.py:289`) sets
`classification = detector_class` with `label_source="detector"` whenever the detector clears the
assertion bar.

**The article's architecture is already in production.** It was A/B tested against the COCO
alternative in `runs/waste_detection/AB_TEST_REPORT.md` and adopted. The question is therefore not
"should we try a direct multi-class detector" but "should we keep the one we have, or move to the
architecture the question mistakenly attributes to us".

A single-class litter detector does exist in this repo — `runs/water/litter_detector`, trained on
`runs/water/tudgv_yolo` (`nc: 1, names: [litter]`) — but it belongs to the Water Agent and has
never been in the waste path.

## 1. Data availability per class

Bounding-box annotations only. `images` counts distinct images containing at least one box of that
class, so the column sums exceed the dataset's 988 images: one image may carry several classes.

| class | dataset | images | boxes | train/val/test (boxes) | usable? |
| --- | --- | ---: | ---: | --- | --- |
| plastic_bags | `datasets/taco_yolo` | 519 | **845** | 640 / 134 / 71 | **Yes** |
| plastic_bottles | `datasets/taco_yolo` | 263 | **335** | 242 / 61 / 32 | **Yes** |
| paper_waste | `datasets/taco_yolo` | 249 | **351** | 261 / 55 / 35 | **Yes** |
| metal_cans | `datasets/taco_yolo` | 179 | **273** | 205 / 40 / 28 | **Marginal** — smallest of the four |
| ewaste | `datasets/taco_yolo` | 2 | **2** | 2 / 0 / 0 | **No** — no val, no test, cannot be learned or measured |
| food_waste | `datasets/taco_yolo` | 7 | **8** | 8 / 0 / 0 | **No** — no val, no test |
| leaf_waste | — | 0 | **0** | 0 / 0 / 0 | **No** — no box data exists |
| wood_waste | — | 0 | **0** | 0 / 0 / 0 | **No** — no box data exists |
| | **TACO total** | **988** | **1,814** | 1,358 / 290 / 166 | 4 of 8 classes |

Matches `runs/waste_detection_dataset_report.json` exactly. Split is by image id, and the report
records `cross_split_duplicate_groups: 0`.

### Datasets that cannot supply detection labels for these classes

| dataset | content | images | boxes | why not |
| --- | --- | ---: | ---: | --- |
| `garbage_Dataset` | **classification only** — class folders, no label files of any kind | 14,046 train / 1,200 val | **0** | Image-level labels. Turning them into boxes means inventing coordinates. Covers all 8 classes, which is exactly why the temptation exists. |
| `water_datasets/Flow-Img.v2i.yolov8` | `nc: 1, names: ['bottle']` | 1,200 | 3,248 | Label says `bottle`, not `plastic_bottles` — glass is not excluded by the annotation. **Train split only**, no val/test. River-surface domain; 93.87% of boxes occupy under 1% of the frame (median 0.095%). Remapping `bottle` -> `plastic_bottles` would be inventing a material claim the annotator did not make. |
| `runs/water/tudgv_yolo` | `nc: 1, names: [litter]` | 1,501 | 8,181 | Asserts litter, not material. Usable for a class-agnostic localiser; carries no per-class signal. |
| `datasets/water/IWHR_..._yolo` | `nc: 1, names: [floater]` | 3,000 | 23,689 | Same — generic, and water-surface specific. |
| TACO unmapped categories | 36 categories left out of the mapping | — | **2,970** | Deliberately excluded, never merged (`Cigarette` 667, `Unlabeled litter` 517, `Other plastic` 273 …). Folding them in would teach a class to mean "small litter". |

## 2. Is there enough data for a direct 8-class detector?

**No.** A direct 8-class detector cannot be trained from what exists.

- **4 of 8 classes** have workable box data (845 / 351 / 335 / 273 boxes).
- **2 classes** have token amounts with **zero validation and zero test boxes** — `ewaste` (2) and
  `food_waste` (8). They can be neither learned nor measured. The existing training manifest
  already records this: *"ewaste (2 train boxes) and food_waste (8, both with 0 validation boxes)
  cannot be learned from this dataset."*
- **2 classes** have **no box data at all** — `leaf_waste`, `wood_waste`. The only images that
  exist for them are classification folders (1,215 and 644 images), which cannot become detection
  labels without fabricating coordinates.

Training "8 classes" on this would produce a 4-class detector wearing an 8-class label — which is
precisely the current situation, where the model reports 6 classes and two of them are vestigial.

For scale: 1,814 boxes total across 4 real classes is roughly two orders of magnitude below what a
multi-class detector normally needs. The measured consequence is already on record —
mAP50 **0.341**, precision **0.406**, recall **0.373**; per-class localisation on the held-out
test split: `plastic_bags` 53.8%, `plastic_bottles` 58.3%, `paper_waste` 52.9%, `metal_cans` 42.9%.

## 3. Would a direct detector fix the three observed failures?

| failure | would a direct multi-class detector fix it? | evidence |
| --- | --- | --- |
| person -> `plastic_bags` | **No — it is the cause** | The box on the person came *from* our direct multi-class detector: `paper_waste` 0.436 at IoU **0.7179** with COCO `person` 0.705 (`runs/debug_waste/coord_audit/`). A waste-only vocabulary has no token for "person" and no way to abstain. `AB_TEST_REPORT.md` §8 recorded the consequence when this architecture was adopted: *"NEVER_WASTE_CLASSES matches on the detector's class name. The TACO detector emits only waste class names, so that gate becomes inert."* |
| shelf/background -> `paper_waste` | **No — it is the cause** | Raw detector output, `paper_waste` 0.283 over 41% of the frame, before any classification. Precision 0.406 at 1,814 boxes over 6 classes. Adding two more classes on zero data lowers this. |
| actual bottle missed | **Partly, and it already did** | Localisation on the held-out split rose 9.3% -> **53.3%** (5.7x) when this detector replaced COCO. The remaining miss is recall at ~55%, which is a **data** problem, not an architecture one. |

Two of the three failures are *produced by* the architecture being proposed. The third was already
improved by it, and the remaining gap needs more boxes, not a different topology.

## 4. The asymmetry that should drive the decision

```
detection labels (boxes)      : 4 of 8 classes,  1,814 boxes,  988 images
classification labels (images): 8 of 8 classes, 15,246 images
```

Our data is shaped for classification and starved for detection. The article's architecture demands
per-class box data — the one thing we have least of, and have none of for two classes. The opposite
architecture (class-agnostic localisation, then material classification) demands box data for a
*single* generic class, where we hold **33,371 boxes** across `litter`, `floater` and `bottle`
annotations, and material labels from images, where we hold 15,246.

Supporting measurement, same YOLOv8n, same trainer: single-class `litter` on TUD-GV reaches
mAP50 **0.941** / precision 0.906 / recall 0.862, against **0.346** for 6-class TACO.

**That comparison is not apples-to-apples and must not be quoted as one.** TUD-GV is video frames
from one water-surface domain with 34.78% near-duplication at Hamming <= 2; the split is
session-level, which mitigates leakage but does not remove the domain narrowness. It shows what
collapsing the class dimension does to a localisation problem; it does not predict 0.94 on street
litter.

### The honest counter-evidence

Localise-then-classify was already measured end to end and **lost**: classifier authority scored
8/107 correct on the held-out split against detector authority's 32/107 (`AB_TEST_REPORT.md` §7).
The reason is a domain gap, not a topology flaw — the classifier scores macro-F1 0.911 on
`garbage_Dataset`'s clean product-style photographs and collapses on small outdoor TACO crops. Its
0.911 does not transfer.

So: neither architecture is currently supported by adequate data, and the binding constraint is
data, not topology.

## 5. Recommendation

1. **Do not adopt the article's approach.** It is what already runs, two of the three failures come
   from it, and it requires the per-class box data we most lack.
2. **Do not train a direct 8-class detector.** Half the classes cannot be trained or measured.
   `leaf_waste` and `wood_waste` have no boxes at all; `ewaste` and `food_waste` have no validation
   data.
3. **Keep `waste_detector.pt` as the baseline.** It is the measured best localiser available and
   the A/B report is the record.
4. **Treat this as a data question.** The decision that unblocks everything is which to acquire:
   per-class boxes for 8 classes (enables the current architecture to work properly), or a
   class-agnostic litter localiser on our 33,371 generic boxes plus a classifier retrained on
   detector-style crops rather than product photos (enables the alternative). The second reuses far
   more of what we already hold.
5. **Two datasets need a provenance decision before either path**, and neither should be silently
   remapped: Flow-Img's `bottle` is not `plastic_bottles`, and it has no val/test split.

Nothing here should be read as a result. No model was trained and no threshold was changed.
