# IWHR_AI_Lable_Floater_V1 — dataset structure audit

Phases 3, 4 and 6. Every number here was produced by `training/water/audit_iwhr.py` and
`training/water/analyze_iwhr.py` reading the actual files. Nothing was assumed from the
dataset's name, and nothing in `raw/` was modified.

## Structure

Both packages are Pascal VOC, identically shaped, and disjoint:

```
IWHR_AI_Lable_Floater_V1-package1/     0001-1500     Annotations/*.xml  JPEGImages/*.jpg
IWHR_AI_Lable_Floater_V1-package2/     1501-3000     Annotations/*.xml  JPEGImages/*.jpg
```

| | package1 | package2 | total |
| --- | --- | --- | --- |
| Images (.jpg) | 1,500 | 1,500 | **3,000** |
| Annotations (.xml) | 1,500 | 1,500 | **3,000** |
| Stem pairing complete | yes | yes | yes |
| Objects | 13,490 | 10,199 | **23,689** |

No missing image, no missing annotation, no unpaired stem, no empty annotation file. There is
**no `ImageSets/`, no split file, no license and no README** anywhere in either archive.

**The packages are not a split.** Six of the eleven capture sessions have frames in *both*
packages (`rubbish`, `fishing-1`, `fishing-3` most heavily). package1/package2 is a delivery
convenience — a 1 GB file size boundary — and must not be treated as train/test.

## Formats

| Property | Value |
| --- | --- |
| Annotation format | Pascal VOC XML, one file per image |
| Image format | JPEG, RGB, 3-channel |
| Bounding box | `<bndbox>` absolute pixels, `xmin/ymin/xmax/ymax`, **1-indexed** (see Phase 4) |
| Segmentation | **None.** `<segmented>0</segmented>` on every file; no masks, no polygons |
| Per-object flags | `truncated` (3,829 set), `difficult` (**0** set), `pose` (always `Unspecified`) |
| Declared `<size>` | Matches real pixels on all 3,000 images |
| `<source><database>` | `Unknown` on every file |

`<path>` carries the annotator's original Windows path (`D:\dataset\images\rubbish-1208.jpg`) and
`<filename>` the original filename. **These are the only provenance in the dataset** and they are
what makes a leakage-safe split possible — see the duplicate report.

## Image dimensions

| Dimensions | Images | Note |
| --- | --- | --- |
| 1920x1080 | 2,934 | 97.8% |
| 3840x2160 | 54 | 4K, same 16:9 |
| 880x1920 | 9 | **portrait** |
| 1080x1920 | 2 | **portrait** |
| 1920x880 | 1 | letterboxed |

Twelve portrait frames (0.4%) sit against 2,988 landscape. Not enough to matter for training,
enough to break any code that assumes 16:9.

## Taxonomy (Phase 6)

**One class. The dataset is a single-class floating-object detector, and it must stay one.**

| IWHR class | Objects | Images | EcoSentinel mapping | Mapping status |
| --- | --- | --- | --- | --- |
| `floater` | 23,689 | 3,000 (100%) | — | **NOT_APPLICABLE** |

There is no second class anywhere in the 3,000 files. `difficult` is never set, so there is not
even an implicit hard/easy division.

### Why the mapping is NOT_APPLICABLE rather than PARTIAL

`floater` is **not a material class** and cannot be mapped to any EcoSentinel waste class. Visual
inspection of every source group (Phase 7) shows the single label covers at least three
semantically different things:

| What is labelled `floater` | Where | Is it litter? |
| --- | --- | --- |
| Plastic bottles, cans, packaging **on dry rock and sand** | `rubbish`, `fishing-*` | Yes — but not floating |
| Natural leaf / algae / scum mats on the water surface | `image`, `2022-*` | **No — organic, not waste** |
| Small indistinct debris patches on turbid water | surveillance groups | Unresolvable at that scale |

Mapping `floater -> plastic_bottles` would be wrong for the majority of annotated objects.
Mapping it to a generic waste class would assert that floating leaf litter is anthropogenic waste.
**The honest mapping is no mapping**: IWHR detects *objects on or beside water*, and any material
claim has to come from a second stage, exactly as the waste pipeline already separates detection
from classification.

This also means IWHR cannot answer "is this water contaminated". It localises visible objects.
Floating debris is not chemical contamination, and the existing Water Agent already refuses to
conflate the two.

## Annotation validation (Phase 4)

3,000 annotations, 23,692 raw objects, **105 problems in 3 images-worth of defects**:

| Problem | Count | Action | Justification |
| --- | --- | --- | --- |
| `box_outside_image_bounds` | 102 | **Clipped to frame** | Every overrun is **exactly 1 pixel** (`xmax`=1921 on a 1920-wide frame, `ymax`=1081 on 1080). Measured, not assumed: min overrun 1px, max overrun 1px, across all 102. This is a 1-indexed annotation tool writing an inclusive `xmax`. Clipping is the documented VOC semantic and is mathematically safe |
| `zero_area_box` | 3 | **Rejected** | A box with `xmin==xmax` or `ymin==ymax` encloses no pixels. There is no safe repair — any fix would invent an extent the annotator did not record |
| missing image | 0 | — | |
| missing annotation | 0 | — | |
| malformed XML | 0 | — | |
| negative coordinate | 0 | — | |
| inverted box (`xmax<xmin`) | 0 | — | |
| box entirely outside image | 0 | — | |
| duplicate annotation (same class+box in one file) | 0 | — | |
| duplicate image reference | 0 | — | |
| unknown class | 0 | — | single class |
| empty annotation file | 0 | — | every image has ≥1 object |
| impossible dimensions | 0 | — | |

Full per-object records: `invalid_annotations.csv` (105 rows, each with the original value and the
action taken).

**Net: 23,689 of 23,692 objects (99.987%) are usable.** Three were rejected, none were invented,
and nothing was silently repaired.

## Provided material

| Item | Status |
| --- | --- |
| `code to split and transform the dataset/voc_label.py` | VOC -> YOLO converter. Read, **not used** — see below |
| `code to split and transform the dataset/split_train_val.py` | **Must not be used.** `random.sample` over the XML list, unseeded, splitting individual frames. On a dataset with 820 near-duplicate pairs this puts near-copies of training frames into validation |
| `detectors/*.zip` (9 archives, 76 MB) | Upstream detector source (yolov5/6/7/9, ultralytics, CenterNet2, faster-rcnn, retinanet, ssd). Left unextracted — EcoSentinel already depends on Ultralytics |
| License | **Not present in either archive.** No LICENSE, README, citation or terms file |
| Source information | Only `<path>D:\dataset\images\...` and burned-in Chinese timestamp overlays. `<source><database>` is `Unknown` |
