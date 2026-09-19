# IWHR_AI_Lable_Floater_V1 — final forensic verification

Independent re-derivation of every headline figure from the artifacts and the files themselves,
not from the prior reports. Where a number could be produced two ways, it was: raw object counts
were recounted straight from the XML text rather than through the audit's parser, and split
membership was read from the derived dataset's `provenance.csv` rather than from the converter's
own report.

**Nothing was trained, modified or downloaded.** No production code, no model weights, no change to
the derived YOLO dataset, no FloW/TUD-GV access.

## Summary

| Metric | Result | Status |
| --- | --- | --- |
| Archive integrity (both ZIPs) | `unzip -t` clean; SHA-256 recorded | PASS |
| Raw images / annotations | 3,000 / 3,000, stems fully paired | PASS |
| Raw objects (independent recount of `<bndbox>`) | **23,692** — matches audit | PASS |
| Distinct class values in schema | **1** (`floater`), 23,692/23,692 | PASS |
| Exact duplicate images (SHA-256) | **0** | PASS |
| Exact duplicates across packages | **0** | PASS |
| Near-duplicate **pairs** (dHash ≤ 8) | 3,996 | INFO |
| Near-duplicate **unique images** (≤ 2) | **782** (26.1% of 3,000) | INFO |
| Near-duplicate **groups** (≤ 2) | **304** components, largest 21 | INFO |
| Identical-perceptual-hash groups (≤ 0) | 53 groups, 124 images | INFO |
| Cross-split duplicates at isolation threshold (≤ 2) | **0** | PASS |
| Cross-split near-duplicates, any distance | 6 pairs / 7 images, **all val↔test** | ACCEPTABLE |
| Train involved in any cross-split pair | **No** | PASS |
| Identical images (SHA-256) in >1 split | **0** | PASS |
| Invalid annotations | 105 of 23,692 = **0.443%** | PASS |
| Images fully excluded from derived set | **0** | PASS |
| Converted images | 3,000 / 3,000 expected | PASS |
| Converted boxes | 23,689 / 23,689 expected | PASS |
| Empty label files | **0** | PASS |
| Malformed label lines | **0** | PASS |
| Coordinate violations (outside [0,1], w/h ≤ 0, box past frame) | **0** | PASS |
| Missing labels / orphan labels | **0 / 0** | PASS |
| `data.yaml` | `nc: 1`, `names: {0: floater}` | PASS |
| Provenance rows | 3,000, one per original, stems unique | PASS |
| Dangling symlinks | **0** | PASS |
| Provenance SHA-256 verified against disk | 10/10 sampled | PASS |
| License | **Absent from both archives** | **BLOCKER (deployment)** |

## 1. Duplicates

**The 3,996 rows in `IWHR_DUPLICATES.csv` are pairs, not images.** Confirmed: 3,996 unique
unordered pairs, 0 rows repeating a pair, 0 self-pairs. Counting rows as images would overstate
duplication by roughly 5x.

Resolved into groups (connected components of the near-duplicate graph):

| Hamming | Pairs | Unique images | Groups | Largest group |
| --- | --- | --- | --- | --- |
| ≤ 0 (visually identical) | 103 | 124 (4.1%) | **53** | 6 |
| ≤ 2 (isolation threshold used) | 820 | **782** (26.1%) | **304** | 21 |
| ≤ 5 | 2,247 | 1,954 (65.1%) | 566 | 28 |
| ≤ 8 | 3,996 | 2,543 (84.8%) | 402 | 112 |

- **Exact duplicates: 0.** No two images share a SHA-256, within or across packages. The
  `type` column contains only `near_duplicate_dhash` rows — there are no exact-duplicate rows
  because there are no exact duplicates.
- **Near-duplicates: present and substantial**, as expected of sampled video frames.
- **Cross-split: 6 pairs involving 7 images.** All six are **val ↔ test**, at distances 7 and 8 —
  above the distance-2 threshold the split was built to isolate. Six of the seven images are `val`
  frames paired against a single `test` frame (`package1/0153.jpg`).
- **Zero cross-split pairs involve `train`.**

**Could duplicate handling cause leakage?** No, in the direction that matters. Leakage inflates a
score when a training frame has a near-copy in an evaluation split; **that count is 0 at every
distance measured**. The 6 residual pairs are between two evaluation splits, which cannot inflate a
model's apparent performance — it only means val and test are not fully independent of each other.
Worth stating when both are reported; not a remediation item.

## 2. Invalid annotations

| | |
| --- | --- |
| Original annotation objects | **23,692** (independently recounted) |
| Invalid / defective | **105** |
| Percentage invalid | **0.443%** |
| Distinct images affected | **69** (66 clipping, 3 zero-area) |
| Objects carried into the derived set | **23,689 (99.987%)** |

| Reason | Count | Images | Action | Effect on derived dataset |
| --- | --- | --- | --- | --- |
| `box_outside_image_bounds` | 102 | 66 | Clipped to frame | Boxes **retained**, coordinates adjusted by exactly 1 px |
| `zero_area_box` | 3 | 3 | Rejected | 3 boxes **dropped** |

Every one of the 102 overruns is exactly 1 pixel (measured min = max = 1 px) — a 1-indexed
annotation tool writing an inclusive `xmax`/`ymax`. Clipping is the documented VOC semantic and is
lossless in substance.

**Did invalid annotations affect the derived dataset?** Only the 3 rejected boxes, and no image lost
its annotation entirely:

| Image | Split | Raw boxes | Written | Still annotated |
| --- | --- | --- | --- | --- |
| `0622.jpg` | val | 34 | 33 | yes |
| `1769.jpg` | train | 13 | 12 | yes |
| `1821.jpg` | train | 7 | 6 | yes |

**Images completely excluded: 0.** All 3,000 appear in the derived dataset.

## 3. YOLO conversion

| Check | Expected | Found | Status |
| --- | --- | --- | --- |
| Images | 3,000 | **3,000** | PASS |
| Boxes | 23,689 | **23,689** | PASS |
| Classes (`nc`) | 1 | **1** | PASS |
| Class names | `floater` | `{0: floater}` | PASS |
| Label lines with class id ≠ 0 | 0 | 0 | PASS |
| Missing labels | 0 | 0 | PASS |
| Orphan labels | 0 | 0 | PASS |
| Empty label files | 0 | 0 | PASS |
| Malformed lines (field count / non-numeric) | 0 | 0 | PASS |
| Coordinates outside [0,1] | 0 | 0 | PASS |
| Non-positive width/height | 0 | 0 | PASS |
| Box extending past frame edge | 0 | 0 | PASS |

Re-checked directly against the label files, independently of `IWHR_YOLO_VALIDATION.json` (which
reports the same figures and `verdict: PASS`, 0 failures).

## 4. Split integrity

| Split | Images | % | Objects | Source groups |
| --- | --- | --- | --- | --- |
| train | **2,204** | 73.5% | **15,075** | `rubbish`, `fishing-1/2/3/4` |
| val | **550** | 18.3% | **7,107** | `image`, `2022-07-20` |
| test | **246** | 8.2% | **1,507** | `_bare_numeric`, `2022-08-18`, `2022-06-18`, `5-11_mix_data` |
| **total** | **3,000** | 100% | **23,689** | 11 groups, none split |

Leakage checks: 0 identical images across splits, 0 stem overlap, 0 cross-split near-duplicates at
distance ≤ 2, 6 at distance 7-8 (val↔test only, train uninvolved). No source group is divided
across splits.

Object density differs sharply by split — 6.8 objects/image in train against 12.9 in val — because
the split boundary follows capture mode. Recorded, not corrected; correcting it would require
splitting a source group.

## 5. Provenance

Every derived file is traceable in both directions:

- `provenance.csv` holds **3,000 rows**, one per original image, with `yolo_stem`, `split`,
  `component`, `source_group`, `package`, `original_image`, `original_annotation`,
  `internal_filename`, `sha256`, `objects`, `width`, `height`.
- All 3,000 `original_image` paths resolve to a real file; all 3,000 `original_annotation` paths
  resolve. **0 missing.**
- **0 dangling symlinks** across all three splits.
- Every one of the 3,000 originals appears **exactly once**; every `yolo_stem` is unique
  (`package`-qualified, since stems repeat across packages).
- Sampled 10 rows: the recorded SHA-256 matches the file on disk **and** the derived symlink
  resolves to that exact original — **10/10 verified**.
- Reverse traceability holds: all 3,996 image paths in `IWHR_DUPLICATES.csv` resolve to a
  provenance row.

`raw/` is symlinked and was re-verified against the archives after all work: 8 random files per
package re-hashed against the ZIP, **16/16 identical, 0 changed.**

## 6. Final dataset identity

Determined from the **annotation schema**, not from object appearance. The complete tag vocabulary
across all 3,000 files was enumerated:

- `<name>`: **one distinct value, `floater`**, on all 23,692 objects.
- `<pose>`: `Unspecified` on all 23,692.
- `<difficult>`: `0` on all 23,692 — no hard/easy division.
- `<truncated>`: `0` on 19,863, `1` on 3,829 — a geometry flag, not a material one.
- **XML attributes anywhere: none.** No material, polymer, category or subclass field exists.
- `<segmented>`: `0` — no masks. (77 files omit the optional `path`/`source`/`segmented` tags
  entirely; `<filename>` is present on all 3,000, so source-group derivation is unaffected —
  all 3,000 frames grouped, 0 unattributable to a filename.)

There is no field in this dataset from which a material class could be read. Any material label
would have to be invented.

> **IWHR provides generic floating-object detection evidence rather than reliable
> material-specific waste classification.**

The visual observations recorded in `IWHR_VISUAL_AUDIT.md` — that the single class is applied to
litter on dry rock in some groups and to natural leaf/algae mats in others — are **not** used here
to assign material classes, and must not be. They serve only as an additional caution: the class is
not merely non-material, it is not even consistently *floating*. Both facts point the same way, and
the schema alone is sufficient to settle it.

## 7. Outstanding items (unchanged by this verification)

1. **License absent from both archives** — blocks deployment/publication of anything trained on it.
   Not a data-integrity defect.
2. **Train/val-test domain gap** — median object area 23,079 px (train) vs ~1,400 px in three
   evaluation groups. Forced by the leakage-safe split; requires per-group reporting rather than a
   single mAP.
3. **No negative images** — every frame has ≥1 object, so false-positive rate on clean water cannot
   be measured from this dataset.

None of these is a preparation error, and none is fixable by re-running the conversion.

---

# READY_FOR_DATASET_COMPARISON

Every mechanical property of the preparation verifies: counts reconcile from raw XML through to
label files (23,692 raw → 105 defects → 23,689 written, 3,000 images in and out, 0 excluded), the
conversion is clean on every structural check, provenance is complete and bidirectional in a
10/10 sample, `raw/` is byte-identical to the archives after all work, and no training frame shares
a near-duplicate with any evaluation frame.

The three outstanding items above are **properties of the source data, already documented, and
none of them blocks a taxonomy comparison** — which is the next step and is exactly where the
license question and the semantics of `floater` should be resolved against FloW-Img and TUD-GV.

This verdict covers dataset preparation only. No model was trained, so no model performance
contributed to it. The earlier `DATASET_REQUIRES_CLEANUP` verdict in
`IWHR_READINESS_REPORT.md` is **not** contradicted: it refers to readiness for *training*, which
still requires the taxonomy decision and the license answer. This report addresses readiness for
*dataset comparison*, which the verified preparation supports.
