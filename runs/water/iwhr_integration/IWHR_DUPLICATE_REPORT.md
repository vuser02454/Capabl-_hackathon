# IWHR — duplicate and leakage audit

Phase 5. Mandatory, and it changed the split design.

Method: SHA-256 over image bytes for exact duplicates; a 64-bit dHash (difference hash) for
visual near-duplicates, compared over all 4,498,500 image pairs. **Filenames were never used as
the duplicate test** — they could not be, because the packages renumber every frame to
`0001.jpg`-`3000.jpg` and discard the original name from the path.

## Exact duplicates

| Check | Result |
| --- | --- |
| Exact duplicate images (SHA-256) | **0** |
| Exact duplicates across package1/package2 | **0** |
| Same image under different filenames | **0** |

No byte-identical file appears twice. The packages do not overlap at the byte level.

A **redundant extraction** was found outside the dataset proper:
`water_datasets/27376851/IWHR_AI_Lable_Floater_V1-package2 2/` — 3,000 files, same relative names,
10/10 sampled byte-identical to `package2`. A macOS double-unzip artifact. **Recorded and excluded
from every count; not deleted.**

## Near-duplicates — the dataset is video frames

| dHash Hamming distance | Pairs | Crossing source groups | Crossing packages |
| --- | --- | --- | --- |
| 0 (visually identical) | 103 | 4 | 0 |
| ≤ 2 | 820 | 63 | 21 |
| ≤ 5 | 2,247 | 297 | 101 |
| ≤ 8 | 3,996 | 598 | 216 |

53 groups of frames share an *identical* 64-bit perceptual hash while having different bytes —
consecutive frames of a near-static water surface, re-encoded. `0168.jpg`, `0169.jpg`, `0171.jpg`
are one such group.

**This is not a defect.** It is what a frame-sampled surveillance dataset looks like. It is a
defect only if the split ignores it.

## Source sequences

The original filenames inside the XML (`<filename>`, `<path>`) survive the renumbering and identify
eleven capture sessions:

| Source group | Images | Packages | Filename shape |
| --- | --- | --- | --- |
| `rubbish` | 1,509 | 1 + 2 | `rubbish-1208.jpg` |
| `image` | 442 | 1 | `image-00105.jpg` |
| `fishing-1` | 366 | 1 + 2 | `fishing-1,712.jpg` |
| `fishing-4` | 187 | 2 | `fishing-4,955.jpg` |
| `_bare_numeric` | 163 | 1 | `01703.jpg` — **provenance unknown** |
| `fishing-3` | 136 | 1 + 2 | `fishing-3,208.jpg` |
| `2022-07-20` | 108 | 1 | `2022-07-20-4873.jpg` |
| `2022-08-18` | 70 | 1 | `2022-08-18-236.jpg` |
| `5-11_mix_data` | 12 | 1 | `5-11_mix_data_4317.jpg` |
| `fishing-2` | 6 | 1 | `fishing-2,901.jpg` |
| `2022-06-18` | 1 | 1 | `2022-06-18-0020.jpg` |

163 frames carry a bare number and cannot be attributed to a session. They are grouped together
and kept in one split — their independence cannot be demonstrated, and the cost of guessing wrong
is leakage.

> **`2022-08-18` frames carry a burned-in overlay reading `2022年07月28日`.** The filename date and
> the on-screen date disagree. Neither was trusted over the other; the group is defined by the
> filename because that is what groups the files consistently.

## What this forced in the split

A per-frame random split — which is exactly what the dataset's own `split_train_val.py` does,
unseeded — would put 820 near-identical pairs on opposite sides of the train/val boundary. The
resulting validation score would measure memorisation.

The split unit is therefore a **connected component** of:

```
(frames sharing a source session)  UNION  (frames within dHash distance 2)
```

Components are assigned whole. Merging at distance 2 yields **6 components**:

| Component size | Contents | Assigned |
| --- | --- | --- |
| 2,204 | `rubbish` + `fishing-1/2/3/4`, chained by near-duplicates | train |
| 442 | `image` | val |
| 163 | `_bare_numeric` | test |
| 108 | `2022-07-20` | val |
| 71 | `2022-08-18` + `2022-06-18` | test |
| 12 | `5-11_mix_data` | test |

**The largest component is 73.5% of the dataset**, so a 70/20/10 split is not reachable. The
achieved split is 73.5 / 18.3 / 8.2. This is a property of the data, not a tuning choice: the five
litter sessions are chained into one blob by cross-session near-duplicates, and breaking that blob
would mean deliberately leaking.

Residual near-duplicate pairs still spanning two splits, at distances *above* the isolation
threshold: **6 pairs total** (4 at distance 7, 2 at distance 8). At that distance the frames are
"similar scene", not "same frame". Recorded in `IWHR_CONVERSION_REPORT.json` rather than hidden.

Verified independently after conversion: **0 images with the same SHA-256 appear in more than one
split**, and no stem appears in two splits (`IWHR_YOLO_VALIDATION.json`).

## Full record

`IWHR_DUPLICATES.csv` — 3,996 rows, each with the Hamming distance, both image paths, both source
groups and whether the pair crosses a group or a package boundary.
