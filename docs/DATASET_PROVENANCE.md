# Dataset Provenance

Licences were verified against **authoritative source records** (Figshare API, Zenodo API,
publisher pages), not against whatever shipped in the download. Where a re-uploader's declaration
conflicts with an upstream record, both are reported and the conflict is **left open** rather than
resolved by assumption.

Full working: `runs/water/dataset_comparison/LICENSE_PROVENANCE_REPORT.md`.

---

## 1. Water datasets

| Dataset | Images | Annotations | Licence | Status | Role |
| --- | --- | --- | --- | --- | --- |
| **IWHR** | 3,000 | 23,692 boxes | **Apache 2.0** (Figshare DOI `10.6084/m9.figshare.27376851.v1`) | Verified | Evaluation / generalisation only |
| **TUD-GV** | 1,501 | 8,181 boxes | **CC BY 4.0** (Zenodo DOI `10.5281/zenodo.13730228`) | Verified | Recommended primary training set |
| **FloW-Img** | 1,200 (local) | 3,248 bottle boxes | **UNRESOLVED — conflict** | Blocked | **Not for production training** |

### IWHR — Apache 2.0, verified
Qiao, Guangchao; Yang, Mingxiang; Wang, Hao (2024). *IWHR_AI_Lable_Floater_V1*. Figshare.

The local directory `water_datasets/27376851/` **is the Figshare article id**, which is how the
record was located. The Figshare record states 3,000 images; the audit counted 3,000. The paper
states 23,692 annotated instances; an independent recount of `<bndbox>` elements found 23,692.
Both match exactly, corroborating that the local copy is this dataset and is complete.

**Why it is not merged into training.** IWHR's semantics are *generic floaters* — it includes
water plants, algae and other natural floating accumulations. TUD-GV's class is *litter*,
meaning anthropogenic waste. Merging them would teach a "litter" detector that algae is litter,
and every downstream statement about visible pollution would inherit that error. Kept for
evaluation and generalisation testing instead.

### TUD-GV — CC BY 4.0, verified
Leakage-safe **session-level** split (`runs/water/dataset_comparison/TUDGV_SPLIT_MANIFEST.json`) —
frames from one recording session never straddle the split, so a near-duplicate frame cannot be in
both train and test:

| Split | Images | Boxes |
| --- | --- | --- |
| train | 1,057 | 6,330 |
| val | 298 | 1,347 |
| test | 146 | 504 |

Zero leakage at the audited threshold. **The manifest exists; no model has been trained on it.**

### FloW-Img — rights unresolved, not used
Upstream FloW is access-gated with no public licence. The local copy is a **partial re-upload**
(1,200 of 2,000 images) by an unnamed third party declaring CC BY 4.0, with the original authors
uncredited. A re-uploader cannot grant rights they do not hold.

**Not used in production training. Not merged with TUD-GV.** This blocks only the bottle-specialist
path; it does not block the recommended TUD-GV route.

## 2. Waste datasets

| Dataset | Use | Notes |
| --- | --- | --- |
| **garbage_Dataset** | Classifier training (8 classes) | 14,046 train / 1,200 val after cleaning |
| **TACO** | Detector training + held-out evaluation | Human annotations read from existing label files; **no new labels were created** |

### Classifier data hygiene
From `runs/dataset_report.json` and `runs/evaluation/classification_report.json`:

- **111 images excluded as leaked** from train (present in both splits).
- 8 unusable train images and 1 unusable val image excluded.
- Split verified leakage-clean after exclusion.

Class distribution is severely imbalanced — 10,050 food_waste against 179 ewaste (**56:1**).
This is why macro F1 (91.1%) is the reported headline rather than accuracy (93.4%).

### TACO evaluation splits
- `taco_test_heldout` — 59 images / 107 objects. Used for **neither** training nor checkpoint
  selection. **Any decision should rest on this set.**
- `taco_val_realworld_80` — 80 images / 135 objects, the first 80 of the TACO val split. That
  split was used for checkpoint selection while training the detector, so it is **biased in favour
  of the TACO model** and is reported as supporting evidence only.

`ewaste` and `food_waste` are excluded from *detector* evaluation: 2 and 8 training boxes, zero
validation boxes. There is nothing to measure.

## 3. Open blockers

These are **not solved**. They are recorded so nothing downstream pretends otherwise.
Source: `runs/water/dataset_comparison/WATER_TRAINING_READINESS.md`.

### B1 — No clean-water negative set exists
All three water datasets contain **zero** empty frames. Without negatives the false-positive rate
is unmeasurable, and `visual_score` counts a false positive identically to real litter while only
ever escalating risk.

Clean water is the **single most common real-world input**, and this project cannot state what a
trained detector would do to the risk score on it. Not solvable by merging — requires acquisition
of ≥300 verified-clean frames meeting `NEGATIVE_DATA_REQUIREMENTS.md` N1–N13, with zero
Hamming ≤ 2 matches against the 5,701 audited positives.

### B2 — `count_reference = 20` is an unvalidated convention
Depends on B1: a reference cannot be set honestly while the false-positive contribution to the
count is unknown. Up to **8.7×** swing between detector families. See `MODEL_LIMITATIONS.md` §3.

### B3 — FloW redistribution rights unresolved
Requires the dataset owner or legal review. Not inferable. Blocks the bottle specialist only.

## 4. Attribution

| Dataset | Required attribution |
| --- | --- |
| IWHR | Qiao, G.; Yang, M.; Wang, H. (2024), Figshare, DOI `10.6084/m9.figshare.27376851.v1`, Apache 2.0 |
| TUD-GV | Zenodo DOI `10.5281/zenodo.13730228`, CC BY 4.0 — **attribution required on any use** |
| TACO | TACO: Trash Annotations in Context (`TACO-master/`) |

## 5. What was NOT done in this round

No dataset was downloaded, merged, relicensed, deleted or re-annotated. No detector was trained
or retrained. The blockers above are documented, not closed.
