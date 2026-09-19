# Water Vision — training readiness

Status of every item identified in `WATER_TAXONOMY_DESIGN.md` §11, after this round of
verification work. **Nothing was trained, merged, downloaded or modified.**

## What changed in this round

| Item | Before | After |
| --- | --- | --- |
| IWHR licence | Unknown | **RESOLVED — Apache 2.0** (Figshare DOI `10.6084/m9.figshare.27376851.v1`) |
| TUD-GV licence | Unknown | **RESOLVED — CC BY 4.0** (Zenodo DOI `10.5281/zenodo.13730228`) |
| FloW licence | CC BY 4.0 declared by re-uploader | **Still UNRESOLVED — conflict identified** |
| TUD-GV split | Not designed | **DESIGNED** — manifest only, 0 leakage at threshold |
| `visual_score` calibration | Flagged as a risk | **QUANTIFIED** — 8.7x swing measured between detector families |
| Clean-water negatives | Missing | **SPECIFIED** — still missing |
| IWHR annotation policy | Inferred visually | **DOCUMENTED by the source paper** — confirms C1 |

---

## BLOCKERS

Training must not begin until these are closed.

### B1 — Clean-water negative data does not exist

All three datasets have **zero** empty frames. Without negatives the false-positive rate is
unmeasurable, and `visual_score` counts false positives identically to real litter while only ever
escalating risk.

- **Why blocking:** it is not possible to state what a trained detector would do to the water risk
  score on clean water — which is the single most common real-world input.
- **Not solvable by merging.** Requires acquisition.
- **Closes when:** ≥300 verified-clean frames satisfying `NEGATIVE_DATA_REQUIREMENTS.md` N1-N13,
  with zero Hamming ≤ 2 matches against the 5,701 audited positives.

### B2 — `count_reference = 20` is an unvalidated convention

Measured ground-truth density (a proxy for detector output) under the shipped defaults:

| Detector family | % frames at MODERATE (≥8 det) | % at HIGH (≥14) | % saturating (≥20) |
| --- | --- | --- | --- |
| IWHR-like | **36.4%** | 15.8% | 6.3% |
| TUD-GV-like | 22.5% | 0.2% | 0.0% |
| FloW bottle-only | **4.2%** | 0.2% | 0.0% |

- **Why blocking:** deploying a TUD-GV-trained detector against a reference tuned for IWHR-like
  density silently changes how often the system reports visible pollution, by up to **8.7x**, with
  no configuration change and nothing in the logs to explain it.
- **Depends on B1** — a reference cannot be set honestly while the false-positive contribution to
  the count is unknown.
- **Closes when:** detector-output density is measured on the TUD-GV held-out split plus clean-water
  negatives, and "maximum density" is defined explicitly as a recorded policy choice.

### B3 — FloW-Img redistribution rights are unresolved

Upstream FloW is **access-gated with no public licence**; the local copy is a partial re-upload
(1,200 of 2,000 images) by an unnamed third party declaring CC BY 4.0, with the original authors
uncredited.

- **Why blocking for FloW only:** blocks the role-B bottle specialist. **Does not block the
  recommended TUD-GV training path.**
- **Not inferable.** Requires the dataset owner or legal review.
- **Closes when:** the rights position is confirmed by a competent party, or FloW is dropped.

---

## NON-BLOCKERS

Resolved, or manageable in-flight.

### NB1 — TUD-GV licence: CC BY 4.0 ✅

Verified from the Zenodo record. **Attribution is required** — Jia, Vallendar, de Vries, Kapelan,
Taormina (2024), DOI `10.5281/zenodo.13730228`, and the *Water Research* paper `10.1016/j.watres.2024.122405`.
An obligation to discharge, not a blocker.

### NB2 — IWHR licence: Apache 2.0 ✅

Verified from the Figshare record. Permissive, commercial use permitted.

**One distinction to preserve:** the **dataset** is Apache 2.0; the **paper** is CC BY-NC-ND. They
govern different artifacts. Whether Apache 2.0 reaches a model trained on the data is a legal
question, not a technical one, and is not answered here. IWHR's assigned role is evaluation-only,
so this is not on the training path regardless.

### NB3 — TUD-GV split: designed, leakage-free at threshold ✅

`TUDGV_SPLIT_MANIFEST.json` — **manifest only, no dataset created.**

| Split | Sessions | Images | % | Boxes | % | Boxes/image |
| --- | --- | --- | --- | --- | --- | --- |
| train | 16 | 1,057 | 70.4% | 6,330 | 77.4% | 5.99 |
| val | 9 | 298 | 19.9% | 1,347 | 16.5% | 4.52 |
| test | 5 | 146 | 9.7% | 504 | 6.2% | 3.45 |
| **total** | **30** | **1,501** | 100% | **8,181** | 100% | 5.45 |

All 1,501 images and 8,181 boxes accounted for. Single class `litter` throughout.

- **Split unit:** connected component of (`exp` session) ∪ (dHash ≤ 2). 30 sessions collapsed to
  **25 components** by 5 cross-session near-duplicate merges (`exp28`↔`exp29` at distance 0;
  `exp14`↔`exp24`, `exp23`↔`exp53`, `exp27`↔`exp29`, `exp82`↔`exp8` at distance 2).
- **Deterministic:** components ordered by (size desc, root id), assigned to the split furthest
  below target. No RNG, no seed.
- **Near-duplicate isolation: 0 cross-split pairs at Hamming ≤ 2** — complete isolation at the
  threshold. Residual at greater distances: 3 at d=4, 15 at d=5, 35 at d=6, 179 at d=7, 504 at d=8
  (736 total). At those distances frames are "same fixed installation, similar scene" rather than
  the same frame — expected, since TUD-GV is one camera setup throughout.

**Known imbalance, recorded not corrected:** box ratios (77.4/16.5/6.2) diverge from image ratios
(70.4/19.9/9.7) because object density varies by session — train averages 5.99 boxes/image against
test's 3.45. Correcting it would mean splitting a session, which would reintroduce leakage.
**Test is a relatively sparse split and metrics should be read with that in mind.**

### NB4 — IWHR annotation policy is documented, not merely inferred ✅

The source paper states: *"floating objects made up of water plants, algae or other litter
accumulations also need to be annotated."*

This **confirms contradiction C1** from the authoritative source. It strengthens rather than
weakens the design conclusion: IWHR's `floater` deliberately includes natural organic material, so
it cannot train a detector meant to report *anthropogenic* litter. Its evaluation-only role stands.

### NB5 — `is_pollution_class('floater') == False`

Verified against the live code. Mitigated by design: the proposed evidence schema keeps
`detector_class_raw` separate from `semantic_category`. Non-blocking **provided** the chosen
detector does not emit the literal string `floater` — the recommended TUD-GV path emits `litter`,
which passes the filter.

### NB6 — No de-duplication on the water path

The waste pipeline merges duplicate boxes class-agnostically at 0.7 IoU; the water path does not, so
a multi-class detector can double-count one object into `visual_score`. **Moot for a single-class
detector** — which is the recommended path. Becomes live again if a multi-class detector is ever
adopted.

---

## UNKNOWN

Cannot currently be determined; each needs evidence that does not exist yet.

### U1 — Whether TUD-GV generalises beyond its single viewpoint

One fixed overhead camera on one TU Delft canal, 10 days across February and April 2021, no sky, no
buildings, no boats, no people. How a detector trained there behaves on a shore-based oblique view
is **unmeasured**. IWHR's surveillance groups are the instrument for this (recall-only, per C5), but
the measurement has not been made.

### U2 — Whether Apache 2.0 reaches a model trained on IWHR

Legal, not technical. Not on the training path under the current role assignment.

### U3 — TUD-GV's negative annotation policy

The Zenodo record and search results do not state what annotators were told **not** to box. The
*Water Research* paper (`10.1016/j.watres.2024.122405`) may contain it; **it was not retrieved**. The
audit's observation that organic matter is systematically unannotated remains an inference from
imagery.

### U4 — Detector-output density, as opposed to annotation density

Every figure in B2 comes from ground-truth annotations. A real detector misses objects and invents
others. The true operating distribution is unknown until a detector is run — and running one
requires closing B1 first to interpret the result.

### U5 — Whether the two class-filter paths should be reconciled

The Water Agent blend applies no `is_pollution_class` filter; frame investigation does. Which is
correct is a product decision, not a technical one, and it has not been made.

---

## Readiness by path

| Path | Blocked by | Status |
| --- | --- | --- |
| **TUD-GV generic litter detector** (recommended) | B1, B2 | **Data ready, calibration not** — licence verified, split designed and leakage-free |
| FloW bottle specialist (role B) | B1, B2, **B3** | Blocked additionally on rights |
| IWHR as evaluation-only (role D) | — | **Ready.** Licence verified; recall-only use needs no calibration |
| IWHR as training data (role A) | C1 (documented), C4, C5 | **Not available** — needs human relabelling |
| Any material claim | No material labels in any dataset | **Not available** |
| Any false-positive claim | B1 | **Not available** |

---

# NOT_READY_FOR_TRAINING — 3 BLOCKERS OPEN

Two of the four training-readiness items in scope this round are **closed**: both licences that
could be resolved from authoritative records are resolved (IWHR Apache 2.0, TUD-GV CC BY 4.0), and
the TUD-GV session-level split is designed with **zero near-duplicate leakage at the isolation
threshold**.

The two remaining blockers are the ones that were always the hard ones, and neither is closable by
analysis:

- **B1** — clean-water negatives must be **acquired**. Specified in full; not obtainable from the
  data held.
- **B2** — `count_reference` must be **measured** against a real detector, and depends on B1.

**B3** blocks only the FloW specialist path, not the recommended one.

The recommended path — a single-class `litter` detector trained on the TUD-GV split — now has
verified licensing, a leakage-free split manifest, and a quantified understanding of what its
output would do to the water risk score. What it lacks is any means of knowing how often it would
fire on clean water. Training before B1 closes would produce a model whose most common real-world
behaviour is unmeasured, and whose detections escalate risk by construction.

Nothing was trained, merged, downloaded or deployed. No production code was modified.
