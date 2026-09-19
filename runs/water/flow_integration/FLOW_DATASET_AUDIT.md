# Flow-Img.v2i.yolov8 (Roboflow export) — dataset audit

Audit only. Nothing was trained, converted, merged or modified; the IWHR dataset and all
production code are untouched. This covers **only** the export present at
`water_datasets/Flow-Img.v2i.yolov8`.

## 0. Provenance caveat — the ZIP is not on disk

`Flow-Img.v2i.yolov8.zip` could not be found anywhere under the user's home directory. Only the
extracted tree exists. **Unlike the IWHR audit, the extraction could not be verified against an
archive**, so no checksum of the delivered artifact is recorded here and nothing certifies that the
tree matches what Roboflow produced. Everything below describes the files as they currently sit on
disk.

## 1. Archive structure

```
Flow-Img.v2i.yolov8/
├── README.dataset.txt
├── README.roboflow.txt
├── data.yaml
└── train/
    ├── images/     1,200 .jpg
    └── labels/     1,200 .txt
```

83 MB on disk (80.1 MB of JPEG). No `valid/`, no `test/`, no `ImageSets`, no source video, no
per-frame metadata.

## 2-3. Image and label counts

| | |
| --- | --- |
| Images | **1,200** (all JPEG, all RGB) |
| Label files | **1,200** |
| Pairing | 1:1, **0 missing images, 0 missing labels, 0 orphans** |

Matches `README.roboflow.txt`, which states "The dataset includes 1200 images."

## 4. Class names from data.yaml

```yaml
nc: 1
names: ['bottle']
```

## 5. Class distribution

| Class id | Name | Objects | Images containing it |
| --- | --- | --- | --- |
| 0 | `bottle` | **3,248** | 1,200 (100%) |

Single class. No label line in any of the 1,200 files carries a class id other than `0`.

## 6. Bounding-box count

**3,248** boxes. Objects per image: min 1, median 2, mean 2.71, p90 5, p99 11, **max 16**.
**No image has zero objects** — the export contains no negative/background frames.

## 7. Image dimensions

**All 1,200 images are exactly 640x640**, JPEG, RGB. No other size occurs, and no EXIF block
survives (0 EXIF entries; only JFIF density headers).

## 8. Bounding-box dimensions

Measured in the 640x640 delivered frame:

| | min | median | max |
| --- | --- | --- | --- |
| Box width (px) | 3.0 | **20.0** | 188.5 |
| Box height (px) | 3.5 | **19.5** | 213.5 |

| Relative area | p1 | p10 | median | p90 | max |
| --- | --- | --- | --- | --- | --- |
| Fraction of frame | 0.0085% | 0.021% | **0.095%** | 0.686% | 7.381% |

Median box aspect ratio 0.986 — near-square boxes, consistent with upright floating bottles seen
from near water level.

**This is a small-object dataset**: 3,049 of 3,248 boxes (**93.87%**) occupy under 1% of the frame,
1,682 under 0.1%, and 1,039 under 0.05%.

## 9-14. Label validity

Every label file was parsed as a trainer would read it. **Zero defects of every kind checked:**

| Check | Count |
| --- | --- |
| Malformed lines (field count / non-numeric) | **0** |
| Unknown class ids | **0** |
| Coordinates outside [0,1] | **0** |
| Zero or negative width/height | **0** |
| Boxes extending past the frame edge | **0** |
| Empty label files | **0** |
| Duplicate annotations within a file | **0** |
| Missing images | **0** |
| Missing labels | **0** |
| Unreadable images | **0** |

`invalid_labels.csv` is present and **empty apart from its header**. This is a mechanically clean
export — cleaner than IWHR, which carried 105 defects.

## 15-16. Duplicates

| | Pairs | Unique images | Groups | Largest group |
| --- | --- | --- | --- | --- |
| **Exact (SHA-256)** | — | **0** | **0** | — |
| Near-duplicate, Hamming ≤ 0 | 9 | 18 (1.5%) | 9 | 2 |
| Hamming ≤ 2 | 73 | 108 (9.0%) | 45 | 6 |
| Hamming ≤ 5 | 369 | 351 (29.2%) | 96 | 36 |
| Hamming ≤ 8 | 1,054 | 583 (48.6%) | 99 | 136 |

No byte-identical image appears twice. Near-duplication is real but **materially lower than IWHR**
(9.0% of images involved at Hamming ≤ 2, against IWHR's 26.1%) — consistent with a curated subset
sampled from video rather than dense consecutive frames.

`FLOW_DUPLICATES.csv` records 1,054 rows. **Rows are pairs, not images** — 1,054 pairs involve 583
distinct images in 99 groups.

## 17. Train / validation / test structure

**Broken as shipped.** `data.yaml` declares three splits; only one exists:

| Declared in `data.yaml` | Directory present |
| --- | --- |
| `train: ../train/images` | **yes** (1,200 images) |
| `val: ../valid/images` | **NO** |
| `test: ../test/images` | **NO** |

All 1,200 images are in `train/`. A training run pointed at this `data.yaml` **would fail on
validation**, because `../valid/images` does not exist. There is no split to preserve and one would
have to be created — which, given the near-duplicate structure, must not be done per-frame.

## 18. Source / video / frame information

No video files, no frame indices, no capture timestamps, no sequence metadata. The **only**
provenance surviving is in the filenames:

```
000001_jpg.rf.f119a0829dda943a21a13948be335c7c
└─ original stem   └─ Roboflow content hash
```

Original stems are zero-padded 6-digit sequential numbers **`000001`-`001200`, contiguous with zero
gaps**. That ordering is consistent with frames extracted from video, but the export preserves no
clip boundaries, so **capture sessions cannot be recovered** — unlike IWHR, where the original
filenames identified eleven sessions and made a leakage-safe split possible.

This is a significant limitation: any split of this export must fall back on near-duplicate
clustering alone, with no session-level grouping to reinforce it.

## 19. License information

| Source | Statement |
| --- | --- |
| `data.yaml` | `license: CC BY 4.0` |
| `README.dataset.txt` | `License: CC BY 4.0` |
| `README.dataset.txt` | "Provided by a Roboflow user" |

**CC BY 4.0 is declared, which is materially better than IWHR (no license at all).** The caveat is
that this is the *re-uploader's* declared license on a Roboflow Universe project, not a license
document from the original dataset authors. Attribution is "a Roboflow user" — no named author, no
citation, no DOI. Whether the re-uploader had the right to relicense the underlying data is not
established by anything in this export.

## 20. README metadata

`README.roboflow.txt`, verbatim on the points that matter:

- Exported via roboflow.com on **July 14, 2025 at 12:55 PM GMT**
- Version: **Flow-Img - v2 2025-01-21 3:00pm**
- Workspace `small-objects-5irpk`, project `flow-img`, version 2
- "The dataset includes 1200 images. Flow-Img are annotated in YOLOv8 format."

## 21. Has this export modified the images?

**Yes — confirmed by the export's own declaration and verified against the files.**

| Declared pre-processing | Verified |
| --- | --- |
| Auto-orientation of pixel data (EXIF-orientation stripping) | EXIF blocks absent from every sampled image |
| **Resize to 640x640 (Stretch)** | All 1,200 images are exactly 640x640 |

Declared augmentation: **"No image augmentation techniques were applied."** Consistent with the
1,200 images / 1,200 originals 1:1 mapping and contiguous stem numbering — an augmented export
would normally carry multiple variants per source stem.

**"Stretch" means the resize did not preserve aspect ratio.** The scenes are plainly landscape
video frames (wide canal views), so unless the source was already square — which would be unusual
for this content — **the delivered images are geometrically distorted relative to the originals**.
The exact original dimensions cannot be recovered from this export, so the magnitude of that
distortion is unverifiable here; the fact of it follows from the word "Stretch".

This matters for any comparison with IWHR, whose frames are native 1920x1080 and undistorted, and
for any use against EcoSentinel's inference path, which feeds native frames to the detector.

## 22. Is this derived from the original FloW dataset?

**Almost certainly yes, and it is a partial re-upload rather than the original distribution.**
Evidence, separated from inference:

**Observed in the files:**
- Roboflow project is literally named `flow-img`, version 2, in workspace `small-objects-5irpk`.
- Single class `bottle` — verified against all 3,248 annotations.
- Original stems are contiguous 6-digit sequential `000001`-`001200`.
- Imagery is a camera at near-water level on an urban inland waterway, Chinese urban architecture
  and signage in frame.

**Inference from that evidence:** FloW-Img is the published image subset of the FloW floating-waste
benchmark, captured from an unmanned surface vehicle on Chinese inland waters, annotated with a
single `bottle` class. Every observable property of this export matches it. The count does **not**:
this export holds 1,200 images, whereas the published FloW-Img subset is larger, so this is best
treated as a **subset re-upload of unknown selection criteria**.

**Not established:** which FloW release it came from, whether the 1,200 are the first 1,200 of the
original or a filtered selection, whether annotations were altered after import, and whether the
re-uploader had redistribution rights. None of that is recoverable from the export.

## 23. What the class semantically represents — read from the annotations, not the name

The class name was not taken on trust. 19 frames spanning the numbering range and the full
object-count range (1 to 16 objects) were rendered with their boxes and inspected
(`previews/`, `FLOW_CONTACT_SHEET.jpg`).

**The name is accurate.** Boxes land on plastic drink bottles and similar rigid containers
**floating on the water surface** — in the close-up frames the bottle is unambiguous (a PET Pepsi
bottle, tightly boxed, floating against bank vegetation). Across the sampled frames:

- Every inspected box is on a floating manufactured container, not on shoreline litter and not on
  natural debris.
- Leaves, algae, surface scum and other natural matter visible in the same frames are **not**
  annotated. The annotation is selective, not "anything on the surface".
- No box was observed on a person, boat, building or bank object, all of which appear in frame.

So, on the evidence of the annotations themselves, `bottle` denotes **floating rigid drink
containers**, a material-and-object-specific class. This is a genuinely different semantic contract
from IWHR's `floater`, which the IWHR forensic report established is a single generic class with no
material field. **No mapping between the two is proposed here** — that is the next task.

Caveat proportionate to the evidence: 19 of 1,200 frames were inspected visually. The consistency
across that sample is strong, but it is a sample, and at a median box size of 20x19 px most objects
in this dataset are too small to adjudicate by eye at all.
