# TUD-GV — readiness report

Audit only. Nothing was trained, converted, merged or split; IWHR, FloW-Img and all production
code are untouched.

Detail: `TUDGV_DUPLICATE_REPORT.md`, `TUDGV_VISUAL_AUDIT.md`. Machine-readable:
`TUDGV_DATASET_STATS.json`. Defect log: `invalid_annotations.csv`.

## 1. Dataset identity

`TUD-GV`, at `water_datasets/TUD-GV/`, 810 MB. A flat YOLO-format floating-litter detection set:

```
TUD-GV/
├── classes.txt      6 bytes, literally "litter", no trailing newline
├── images/          1,501 .jpg
└── labels_txt/      1,501 .txt
```

No archive of the delivered dataset is on disk, so — as with FloW-Img — the tree could not be
verified against a source artifact. Directory mtimes (`images/` Jun 2024, `labels_txt/` May 2023)
suggest images and labels were assembled at different times.

## 2-5. Counts

| | |
| --- | --- |
| Images | **1,501** (all `.jpg`, all JPEG/RGB, all 1920x1080) |
| Label files | **1,501** |
| Annotations | **8,181** boxes |
| Classes | **1** — `litter` |
| Objects per class | `litter`: 8,181 |
| Images per class | `litter`: 1,501 (100%) |
| Images with no objects | **0** |

Objects per image: min 1, median 5, mean 5.45, p90 9, p99 11, max 14.

## 6. Annotation format

YOLO detection text, one file per image:

```
<class_id> <x_center> <y_center> <width> <height>
```

normalised to [0,1], written to 6 decimal places. Class ids come from `classes.txt` by line index;
only id `0` occurs.

## 7. Invalid annotations

**Zero real defects.** `invalid_annotations.csv` holds 50 rows, all of one kind:

| Problem | Rows | Assessment |
| --- | --- | --- |
| `box_extends_past_frame` | 50 | **Floating-point rounding, not a defect.** Maximum overrun across all 50 is **1e-6** — 0.0019 px on a 1920-px frame — arising because `cx + w/2` is recomputed from values stored to 6 decimals. Boxes kept unchanged |

All other checks returned zero: class ids outside `classes.txt`, coordinates outside [0,1],
zero/negative width or height, x1/y1 < 0 beyond rounding, x2/y2 > 1 beyond rounding, malformed
lines, non-numeric fields, duplicate annotations within a file, empty label files.

## 8. Missing and orphan files

| Check | Result |
| --- | --- |
| Missing images | **0** |
| Missing labels | **0** |
| Orphan labels | **0** |
| Every image has a label / every label has an image | **yes / yes** |
| Duplicate filename stems | **0** |
| Malformed filenames | **0** — all match `exp<N>_<frame>` or `exp<N>_pic<frame>` |
| Zero-byte images / labels | **0 / 0** |
| Unreadable or corrupt JPEGs | **0** (every image decoded and re-verified) |
| Stray non-image files in `images/` | **0** |

## 9-10. Duplicates

| | Pairs | Unique images | Groups | Largest |
| --- | --- | --- | --- | --- |
| **Exact (SHA-256)** | — | **0** | **0** | — |
| Near-duplicate ≤ 0 | 483 | 131 (8.73%) | 40 | 27 |
| Near-duplicate ≤ 2 | 3,234 | **522 (34.78%)** | 39 | 150 |
| Near-duplicate ≤ 5 | 13,238 | 968 (64.49%) | 66 | 505 |
| Near-duplicate ≤ 8 | 35,476 | 1,281 (85.34%) | 63 | 599 |

`TUDGV_DUPLICATES.csv` contains **35,476 rows, which are pairs** — involving 1,281 distinct images.
Rows are not images; the ratio here is about 28:1.

## 11. Split information

**No split exists.** There is no `train/`, `valid/`, `val/` or `test/` directory, no split text
file, no `data.yaml`. All 1,501 images sit in one flat `images/` directory. Nothing was created.

## 12. Sequence and video information

Explicit and usable — the strongest of the three datasets:

- **30 sessions**, `exp1`-`exp122`, identified directly in every filename.
- Two filename shapes: `exp<N>_pic<frame>` (912 images) and `exp<N>_<frame>` (589).
- Session sizes range from **151** (`exp27`) down to **3** (`exp3`, `exp82`).
- Frame indices within a session are **non-contiguous** (e.g. `exp50` holds 80 images across
  indices 1-912), so frames were subsampled from longer recordings.

No video files, timestamps or EXIF survive; the session id and frame index are the whole of it.

## 13. Leakage risk

**High under a random split, low under a session split.**

522 images (34.8%) have a near-duplicate at Hamming ≤ 2, and the largest such group holds 150
images — a random image-level split would place near-identical frames on both sides and measure
memorisation. But **98.3% of those pairs are intra-session**, so grouping by `exp` id isolates
almost all of them.

A future split should therefore be **source/session-level, not random image-level**. 30 sessions
with a long size tail give enough freedom to hit a target ratio — unlike IWHR, where near-duplicate
chaining forced a single component to 73.5% of the data. The residual 55 cross-session pairs at
≤ 2 should be measured and reported after any split is built. **No split was created.**

## 14. Object-size statistics

| | Value |
| --- | --- |
| Median box | **70 x 68 px** (4,543 px² on 1920x1080) |
| Median relative area | **0.219%** of frame |
| Relative area p1 / p10 / p90 / p99 / max | 0.049% / 0.118% / 0.660% / 1.893% / **4.979%** |
| Tiny (<1% of frame) | **7,849 / 8,181 = 95.94%** |
| Smallest / largest box | 17x30 px / 227x444 px |
| Median aspect ratio | 1.025 (near-square) |

The distribution is **tight**: no object exceeds 5% of the frame, so there is no close-up regime.

## 15. Visual-domain characteristics

Fixed **overhead camera looking down** at a turbid inland canal, with a timber-piled bank
revetment crossing most frames. No sky, horizon, buildings, boats or people in any inspected frame.
Daylight, both overcast and hard sun with cast shadows; persistent wind ripple and specular glare
that visually resembles small pale litter. One consistent viewpoint throughout — the `exp` naming
and controlled litter density suggest experimental releases rather than opportunistic capture
(an inference from structure, not from documentation).

## 16. License

**LICENSE_NOT_VERIFIED.**

No LICENSE file, no README, no citation, no DOI, no terms of any kind exist in
`water_datasets/TUD-GV/`. The only files present besides images and labels are `classes.txt`
(6 bytes) and a macOS `.DS_Store`. No license information was inferred or invented.

## 17. Provenance

| Field | Value |
| --- | --- |
| Dataset name | `TUD-GV` (directory name only) |
| Source | **Unknown** — no URL, archive or download record on disk |
| Authors | **Unknown** |
| Publication | **Unknown** |
| License | **LICENSE_NOT_VERIFIED** |
| Citation / DOI | **Absent** |
| EXIF | **Absent** from all sampled images (JFIF density headers only) |
| Provenance evidence available | Session ids and frame indices in filenames; directory mtimes (labels May 2023, images Jun 2024); the literal string `litter` in `classes.txt` |

The name plausibly denotes a TU Delft dataset, and the imagery is consistent with a European canal,
but **nothing on disk establishes that**, so it is recorded as unknown rather than asserted.

## 18. Dataset limitations

1. **No license and no provenance.** Same blocker as IWHR: unusable for anything published or
   deployed until resolved.
2. **No split**, and a random one would leak — 34.8% of images have a near-duplicate at ≤ 2.
3. **Single viewpoint.** One camera geometry, one water type, no sky, buildings, boats or people.
   A detector trained only here sees a very narrow world.
4. **No negative images.** Every frame has ≥1 object, so a false-positive rate on clean water
   cannot be measured — the same gap IWHR and FloW-Img both have, and the one EcoSentinel's
   existing reference matcher is already documented as weak on.
5. **Glare and ripple resemble the targets**, which makes the false-positive question more pressing
   here, not less — and the dataset cannot answer it.
6. **`litter` supports no material distinction**, so nothing downstream can claim one.

## 19. Comparison notes against IWHR

| | IWHR | **TUD-GV** |
| --- | --- | --- |
| Images / objects | 3,000 / 23,689 | 1,501 / 8,181 |
| Native frame | 1920x1080 | 1920x1080 (**directly comparable**) |
| Class | `floater`, 1 class | `litter`, 1 class |
| Class semantics | Generic; covers litter **on dry rock** and **natural leaf/algae mats** | Generic; **anthropogenic and floating only** — organic matter left unannotated |
| Annotation defects | 105 (0.443%) | **0 real** (50 rounding artifacts) |
| Near-dup images ≤ 2 | 782 (26.1%) | 522 (**34.8%**) |
| Session metadata | Recovered from XML `<filename>` | **Explicit in every filename** |
| Median relative box area | 0.847% | 0.219% |
| Max relative box area | 63.195% | 4.979% |
| Capture modes | **Two**, with a 17x size gap | **One**, uniform |
| License | None | **None** |

Both are single-class generic detectors, which makes them directly comparable at the taxonomy
level — but **their generic classes are not the same generic class**. IWHR's `floater` includes
natural organic mats and shoreline litter on dry rock; TUD-GV's `litter` is confined to
anthropogenic objects floating on water. TUD-GV's class is the narrower and cleaner of the two.

## 20. Comparison notes against FloW-Img

| | FloW-Img | **TUD-GV** |
| --- | --- | --- |
| Images / objects | 1,200 / 3,248 | 1,501 / 8,181 |
| Native frame | **640x640, stretch-resized** | 1920x1080, unmodified |
| Class | `bottle` — **material/object-specific** | `litter` — **generic** |
| Camera | Water-level, on a moving vessel | **Overhead, fixed** |
| Annotation defects | 0 | 0 real |
| Near-dup images ≤ 2 | 108 (9.0%) | 522 (34.8%) |
| Session metadata | **None** | **Explicit** |
| Median relative box area | 0.095% | 0.219% |
| License | **CC BY 4.0 declared** | **Not verified** |

The sharpest contrast in the whole three-dataset set is semantic: FloW annotates **bottles only**
and deliberately leaves other floating litter unannotated, while TUD-GV annotates **all
anthropogenic floating litter** including bottles. The two label sets are therefore not
interchangeable and are not in a simple subset relation either — FloW would mark a bag as
background where TUD-GV marks it as `litter`. Any future unified taxonomy has to resolve this
explicitly; it cannot be resolved by renaming classes.

FloW's stretch-resize also makes its shape statistics incomparable with TUD-GV's, though relative
areas remain comparable.

---

# SUITABLE_FOR_COMPARISON

TUD-GV is the mechanically cleanest of the three water datasets: 1,501 images and 1,501 labels in
perfect correspondence, 8,181 annotations with **zero real defects**, no missing or orphan files, no
corrupt or zero-byte files, uniform native 1920x1080 imagery with no export-side modification, and
**explicit session ids in every filename** — the best split metadata of the three.

Its two serious gaps — **no license or provenance whatsoever**, and **no split** with 34.8% of
images carrying a near-duplicate — are exactly the kind of thing a taxonomy comparison should take
as input rather than be blocked by. Neither prevents comparing what `litter` means against
`floater` and `bottle`, which is the next task.

It is **not** ready for training: a session-level split must be built first, and the license
question must be answered before anything trained on it is deployed or published.

This verdict rests on dataset evidence only. Nothing was trained, converted, split or merged.
