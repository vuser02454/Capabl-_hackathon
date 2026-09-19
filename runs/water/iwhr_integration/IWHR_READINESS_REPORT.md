# IWHR_AI_Lable_Floater_V1 — readiness report

Phase 11. Dataset preparation and evidence only. **No model was trained, no weights were touched,
no production code was modified.**

## 1. Dataset source

`IWHR_AI_Lable_Floater_V1`, delivered as two ZIP archives plus a `detectors/` folder of upstream
detector source and a `code to split and transform the dataset/` folder. Held at
`water_datasets/27376851/`. IWHR is the China Institute of Water Resources and Hydropower Research;
the imagery is Chinese (Chinese-language packaging on the litter, Chinese timestamp overlays).
**No citation, DOI, README or license file is present in either archive** — the attribution above
is inferred from the dataset name and image content, not from a document.

## 2. Package sizes

| Package | Bytes | SHA-256 | Integrity |
| --- | --- | --- | --- |
| `IWHR_AI_Lable_Floater_V1-package1.zip` | 1,016,973,959 (970 MB) | `b96a3e9d…a3b716` | `unzip -t`: no errors |
| `IWHR_AI_Lable_Floater_V1-package2.zip` | 1,219,796,963 (1.1 GB) | `7af8f17c…4fe6ec` | `unzip -t`: no errors |
| **Total** | **2,236,770,922 (2.1 GB)** | | 3,003 entries each |

Full manifest: `IWHR_ARCHIVE_MANIFEST.json`.

## 3. Number of images

**3,000** (1,500 per package, no overlap, no exact duplicates).

## 4. Number of annotations

**3,000** annotation files, **23,692** raw objects, **23,689** usable (99.987%).

## 5. Annotation format

Pascal VOC XML, one file per image. Absolute-pixel `xmin/ymin/xmax/ymax`, **1-indexed**.
No segmentation masks (`<segmented>0</segmented>` everywhere). `truncated` set on 3,829 objects,
`difficult` never set.

## 6. Classes

**One: `floater`.** No second class exists anywhere in the 3,000 files.

## 7. Object counts

| Class | Objects | Images | Mean per image |
| --- | --- | --- | --- |
| `floater` | 23,689 | 3,000 (100%) | 7.9 |

Range 1-43 objects per image; median 6. **No image is empty**, so the dataset contains no negative
examples.

## 8. Image resolution statistics

| Dimensions | Images |
| --- | --- |
| 1920x1080 | 2,934 (97.8%) |
| 3840x2160 | 54 |
| 880x1920 (portrait) | 9 |
| 1080x1920 (portrait) | 2 |
| 1920x880 | 1 |

Declared `<size>` matches real pixels on all 3,000 images.

## 9. Invalid annotation count

**105 defects recorded** in `invalid_annotations.csv`:

| Problem | Count | Action |
| --- | --- | --- |
| Box exceeds frame by **exactly 1 px** | 102 | Clipped — 1-indexed `xmax`/`ymax`, documented VOC semantics, measured min and max overrun both 1 px |
| Zero-area box | 3 | **Rejected** — no safe repair exists |

Zero of: missing images, missing annotations, malformed XML, negative coordinates, inverted boxes,
boxes wholly outside the frame, duplicate annotations, duplicate image references, unknown classes,
empty annotation files, impossible dimensions.

## 10. Duplicate count

**0 exact duplicates** (SHA-256), including across packages. A redundant extracted copy of
package2 (`…-package2 2/`) was found, recorded and excluded from all counts; it was not deleted.

## 11. Near-duplicate count

| Hamming (64-bit dHash) | Pairs |
| --- | --- |
| 0 — visually identical | 103 |
| ≤ 2 | 820 |
| ≤ 5 | 2,247 |
| ≤ 8 | 3,996 |

53 groups of frames share an identical perceptual hash with different bytes. The dataset is
video frames.

## 12. Leakage findings

- The **packages are not a split**: six of eleven capture sessions have frames in both.
- A per-frame random split leaks heavily. The dataset's own `split_train_val.py` does exactly that,
  unseeded, and **must not be used**.
- Split units are connected components of (source session) ∪ (dHash distance ≤ 2), assigned whole.
- Post-conversion verification: **0 images with the same SHA-256 in more than one split**, 0 stem
  overlap. 6 residual pairs span splits at distance 7-8 ("similar scene", not same frame).

## 13. Train / validation / test structure

| Split | Images | % | Boxes | Source groups |
| --- | --- | --- | --- | --- |
| train | 2,204 | 73.5% | 15,075 | `rubbish`, `fishing-1/2/3/4` |
| val | 550 | 18.3% | 7,107 | `image`, `2022-07-20` |
| test | 246 | 8.2% | 1,507 | `_bare_numeric`, `2022-08-18`, `2022-06-18`, `5-11_mix_data` |

70/20/10 is **not reachable**: near-duplicates chain the five litter sessions into one component of
2,204 images (73.5%). Breaking it would mean deliberately leaking.

## 14. Class imbalance

**Not applicable — one class.** The imbalance that matters here is not between classes but between
capture modes: 2,204 close-up frames against 796 surveillance frames, and the split boundary falls
exactly along that line.

## 15. Tiny-object statistics

**12,761 of 23,689 boxes (53.87%) occupy under 1% of the frame.**

| | p1 | p10 | median | p90 | max |
| --- | --- | --- | --- | --- | --- |
| Box area, % of frame | 0.016% | 0.107% | 0.847% | 6.116% | 63.195% |

Median box: 157 x 118 px (17,675 px²). By group the median ranges from 46,827 px² (`fishing-3`,
train) down to 1,335 px² (`5-11_mix_data`, test) — a **17x gap between the training and test
distributions**. 30 boxes (0.13%) have a side of 8 px or less; 1 is 1x1 px.

## 16. Dataset quality concerns

1. **`floater` is semantically heterogeneous.** It labels anthropogenic litter, natural leaf/algae
   mats, and unresolvable debris patches with one name. In `rubbish` and `fishing-*` — 73.5% of the
   data — it labels litter resting on **dry rock and sand**, not floating at all.
2. **Train and val/test are different visual domains**, and the leakage-safe split cannot avoid it.
   Close-up handheld shoreline photography trains; wide fixed-camera surveillance validates.
3. **No negative images.** The dataset cannot measure a false-positive rate on clean water — which
   is precisely EcoSentinel's existing measured blind spot.
4. **A burned-in timestamp overlay** is present in one capture mode and absent in the other, and is
   a learnable shortcut that correlates with the split.
5. **Annotation completeness looks uneven** in turbid wide shots. Not quantified; it means recall on
   those frames may read pessimistically and unmatched detections are not automatically false.
6. **54% tiny objects** against an inference path that feeds full frames to YOLO at defaults.

## 17. License information

**None supplied.** No LICENSE, README, citation or terms file in either archive; `<source><database>`
reads `Unknown` in all 3,000 annotations. **Licensing must be resolved with the dataset provider
before any model trained on it is deployed or published.** This is a blocker for deployment, not
for the internal experiment.

## 18. Conversion status

**Converted successfully.** 3,000 images and all 23,689 usable boxes written, one class, no class
invented or renamed. Images are symlinks into `raw/`; `provenance.csv` records for every derived
file its origin, source group, component, split and SHA-256.

Phase 9 validation — `IWHR_YOLO_VALIDATION.json` — **PASS**, 0 failures:
every image has a label and every label an image, all class ids exist in `data.yaml`, all
coordinates within [0,1], all widths and heights positive, every box inside the frame, no symlink
dangling, no stem or image shared between splits.

## 19. YOLO dataset path

```
datasets/water/IWHR_AI_Lable_Floater_V1_yolo/
├── data.yaml                  # nc: 1, names: {0: floater}
├── provenance.csv             # 3,000 rows, full lineage per file
├── images/{train,val,test}/   # symlinks into raw/
└── labels/{train,val,test}/
```

## 20. Recommended next step

**Do not train on this yet, and when you do, do not train it as a waste detector.**

In order:

1. **Resolve the license** with the provider. Nothing trained on this should be deployed until that
   is answered.
2. **Decide what `floater` means for EcoSentinel** before training, not after. The honest reading is
   a single-class *visible-object-on-water* detector whose output is localisation only, with any
   material claim left to a second stage — the same detector/classifier separation the waste
   pipeline already enforces. Training it and *then* deciding how to describe it is how
   "floating leaf mat" becomes "plastic pollution" in a report.
3. **Baseline before training.** Run the existing COCO detector over `test` through
   `build_report(detector, ...)` — the same production call path the waste A/B used. That produces
   the comparison number for free and exercises the real decoder.
4. **Expect the domain gap.** Train (close-up litter) and val/test (wide surveillance) differ by 17x
   in median object size. A weak validation mAP will be ambiguous between "did not learn" and "did
   not transfer", so decide in advance which per-group numbers settle it.
5. **Do not merge with FloW-Img, TUD-GV or the waste dataset yet** — that is the next task, and it
   needs the taxonomy question in (2) answered first.

### Integration constraints already identified (from `EXISTING_WATER_ARCHITECTURE.md`)

- `visual_score = len(detections) / 20`, counting **every** detection. IWHR frames average 7.9
  objects and reach 43. Swapping detectors changes the water risk distribution **even with
  identical weights** — this needs measuring before any swap, not after.
- `is_pollution_class` is applied in `/api/water/scan-frame` but **not** in the Water Agent blend
  path. A single-class `floater` detector makes that filter a no-op, which is a behaviour change to
  state explicitly rather than a free win.
- Vision escalates only, capped at 0.25, and can never touch pH, turbidity or chemistry. Floating
  debris is not chemical contamination.

---

# DATASET_REQUIRES_CLEANUP

Not because the annotations are bad — they are unusually clean: 99.987% of objects are usable, the
only systematic defect is a 1-pixel off-by-one, and there are no exact duplicates, no missing files
and no malformed XML.

The cleanup required is **semantic and structural, and none of it can be fixed by editing labels**:

1. **The label does not mean one thing.** `floater` spans anthropogenic litter, natural organic
   mats, and litter on dry rock. Until EcoSentinel decides which of those it is detecting, a trained
   model's output cannot be described honestly — and this project's whole discipline is not
   describing outputs it cannot support.
2. **The split is domain-separated by necessity**, with a 17x object-size gap between train and
   test. That is a real evaluation hazard and it needs per-group reporting, not a single mAP.
3. **The license is unknown**, which blocks deployment regardless of model quality.

It is emphatically **not** `DATASET_UNSUITABLE`: 3,000 annotated frames of real water scenes with
23,689 boxes is the only water *detection* data this project has, and the existing water vision path
is a COCO model that has no concept of floating debris at all. It is worth using — after (1) is
answered.

This verdict rests on dataset evidence only. No model was trained, so no model performance
contributed to it.
