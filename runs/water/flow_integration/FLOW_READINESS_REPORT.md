# Flow-Img.v2i.yolov8 — readiness report

Audit only. No training, no conversion, no merge, no change to IWHR or production code.
Full detail: `FLOW_DATASET_AUDIT.md`. Machine-readable: `FLOW_DATASET_STATS.json`.

## Summary

| Metric | Result | Status |
| --- | --- | --- |
| Delivered ZIP present on disk | **No** — only the extracted tree | CANNOT VERIFY |
| Images | **1,200** JPEG, all RGB | PASS |
| Label files | **1,200**, 1:1 with images | PASS |
| Annotations (boxes) | **3,248** | PASS |
| Classes | **1** — `bottle` (`nc: 1`) | PASS |
| Objects per class | `bottle`: 3,248 across 1,200 images | PASS |
| Invalid labels (all 9 checks) | **0** | PASS |
| Missing images / missing labels | **0 / 0** | PASS |
| Empty labels | **0** | PASS |
| Coordinates outside [0,1] | **0** | PASS |
| Zero/negative width or height | **0** | PASS |
| Image dimensions | 640x640, uniform | INFO |
| Median box size | **20.0 x 19.5 px** (0.095% of frame) | INFO |
| Tiny objects (<1% of frame) | **3,049 / 3,248 = 93.87%** | CONCERN |
| Exact duplicate images | **0** | PASS |
| Near-duplicate images (Hamming ≤ 2) | 73 pairs / **108 images (9.0%)** / 45 groups | ACCEPTABLE |
| Split structure | **train only; `valid/` and `test/` declared but absent** | **DEFECT** |
| Source / video / frame metadata | **None recoverable** — no session boundaries | CONCERN |
| License | **CC BY 4.0 declared** (by re-uploader, not original authors) | ACCEPTABLE |
| Images modified by export | **Yes** — auto-orient + **resize 640x640 "Stretch"** | CONCERN |
| Augmentation | **None** (declared and consistent with the files) | PASS |
| Derived from original FloW | **Almost certainly — partial subset re-upload** | INFO |

## Requested figures

- **Exact image count:** 1,200
- **Exact annotation count:** 3,248 bounding boxes across 1,200 label files
- **Exact class list:** `['bottle']` (`nc: 1`) — one class, no other class id present in any file
- **Objects per class:** `bottle` = 3,248 (100%)
- **Invalid annotation count:** **0** (`invalid_labels.csv` is header-only)
- **Duplicate count:** 0 exact; near-duplicates 108 images / 45 groups at Hamming ≤ 2, rising to
  583 images / 99 groups at Hamming ≤ 8. *The 1,054 rows in `FLOW_DUPLICATES.csv` are pairs, not
  images.*
- **Split structure:** single `train/` split holding all 1,200 images. `data.yaml` points `val` and
  `test` at `../valid/images` and `../test/images`, **neither of which exists.**
- **License status:** CC BY 4.0, declared in both `data.yaml` and `README.dataset.txt`, attributed
  only to "a Roboflow user". No named author, citation or DOI; the re-uploader's right to
  relicense the underlying FloW data is not established by anything in this export.

## Is this export suitable for comparison against IWHR?

**Yes for taxonomy and statistical comparison. No as a drop-in training or evaluation partner in
its current form.**

**What makes it suitable:**
- The annotations are mechanically flawless — 0 defects across every check, against IWHR's 105.
- The class semantics were verified by reading the annotations, not the name: boxes fall on
  floating rigid drink containers, and natural debris in the same frames is deliberately left
  unannotated. That is a **material-and-object-specific** contract, and it contrasts sharply with
  IWHR's generic single `floater` class. This contrast is precisely what the comparison needs.
- A license is at least declared, which IWHR lacks entirely.
- Both datasets are Chinese inland waterways with floating-object annotations, so the comparison is
  meaningful rather than apples-to-oranges.

**What blocks it from being more than that, without remediation:**

1. **No usable split.** `data.yaml` is broken: two of three declared split directories do not
   exist. A split must be created before any evaluation, and it cannot be per-frame — 9% of images
   have a near-duplicate at Hamming ≤ 2.
2. **No session metadata to split on.** IWHR's original filenames identified eleven capture
   sessions and made a leakage-safe grouping possible. This export preserves only a contiguous
   frame index, so a split here can rely on near-duplicate clustering alone — a weaker guarantee.
3. **The images are geometrically distorted.** "Resize to 640x640 (Stretch)" is non-aspect-preserving
   on landscape video frames. Any geometric statistic compared against IWHR's native 1920x1080
   frames — box aspect ratio above all — is comparing a stretched frame against an unstretched one.
   Relative-area comparisons survive this; aspect-ratio comparisons do not.
4. **Severe object-size mismatch with IWHR.** Median relative box area is **0.095%** here against
   **0.847%** in IWHR — roughly 9x smaller. 93.9% of FloW boxes are tiny (<1% of frame) against
   53.9% in IWHR. The two datasets do not describe the same detection difficulty, and any merged
   training or cross-evaluation would be dominated by this gap rather than by taxonomy.
5. **No negative images.** Every frame contains at least one object, so — exactly as with IWHR —
   this export cannot measure a false-positive rate on clean water.
6. **Provenance is partly unverifiable.** The ZIP is absent, so the extraction cannot be checked
   against a delivered artifact, and the relationship to the original FloW release (which release,
   which 1,200 of its images, whether annotations were altered) is not recoverable.

## Recommended next step

Proceed to the **taxonomy comparison** against IWHR and TUD-GV, which is what this export is
genuinely ready for. Carry these four facts into it: `bottle` is material-specific while `floater`
is not; FloW objects are ~9x smaller in relative terms; FloW frames are aspect-distorted and IWHR
frames are not; and FloW has a declared license while IWHR has none.

Do **not** build a split, convert, merge or train on this until that comparison settles what a
unified water taxonomy should be — a `bottle`-vs-`floater` reconciliation is a semantic decision,
not a file operation.

---

# SUITABLE_FOR_COMPARISON — NOT_READY_FOR_TRAINING

Suitable for comparison: counts reconcile exactly, annotations are defect-free, class semantics are
verified from the annotations themselves, and a license is declared.

Not ready for training or evaluation: the declared train/val/test structure is broken, no session
metadata exists to support a leakage-safe split, and the images are aspect-distorted by the export.

This verdict rests on dataset evidence only. No model was trained, nothing was converted, and
nothing was merged with IWHR.
