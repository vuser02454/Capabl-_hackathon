# TUD-GV — duplicate and leakage audit

Phase 5. Same methodology as the IWHR forensic audit: SHA-256 over image bytes for exact
duplicates, a 64-bit dHash for visual near-duplicates over all 1,125,750 image pairs, and results
reported as **pairs, unique images and groups separately**.

## Pairs are not images

This distinction dominates the TUD-GV numbers more than either previous dataset:

| Hamming | **Pairs** | **Unique images** | **Groups** | Largest group |
| --- | --- | --- | --- | --- |
| 0 (visually identical) | 483 | **131** (8.73%) | **40** | 27 |
| ≤ 2 | 3,234 | **522** (34.78%) | **39** | 150 |
| ≤ 5 | 13,238 | 968 (64.49%) | 66 | 505 |
| ≤ 8 | 35,476 | 1,281 (85.34%) | 63 | 599 |

`TUDGV_DUPLICATES.csv` holds **35,476 rows. Those are pairs.** They involve 1,281 distinct images
in 63 groups. Reading the row count as an image count would overstate duplication by roughly 28x —
and would wrongly suggest the dataset is larger than its 1,501 images.

## Exact duplicates

| Check | Result |
| --- | --- |
| Exact duplicate images (SHA-256) | **0** |
| Images involved | **0** |

No byte-identical file appears twice.

## Repeated frames and sequence structure

483 pairs are **visually identical** (Hamming 0) while being byte-distinct, clustered into 40
groups — one of which contains **27 frames**. These are repeated or near-static frames from a
recording of a slow-moving water surface, re-encoded.

The decisive structural fact:

| Threshold | Pairs within one session | Pairs crossing sessions | % within |
| --- | --- | --- | --- |
| ≤ 0 | 481 | 2 | **99.6%** |
| ≤ 2 | 3,179 | 55 | **98.3%** |
| ≤ 5 | 11,538 | 1,700 | 87.2% |
| ≤ 8 | 24,021 | 11,455 | 67.7% |

**Near-duplication is overwhelmingly intra-session.** At the threshold that actually denotes "the
same frame" (≤ 2), 98.3% of duplicate pairs live inside a single `exp` session. Cross-session pairs
at distance 5-8 are better read as "same fixed camera, same scene" than as duplicate content — this
is one installation filmed repeatedly, so distant frames resemble each other by construction.

## Sequence and session evidence

Filenames carry an explicit session id, in two shapes:

| Shape | Images |
| --- | --- |
| `exp<N>_pic<frame>` | 912 |
| `exp<N>_<frame>` | 589 |

**30 sessions**, `exp1` through `exp122`, ranging from 3 images (`exp3`, `exp82`) to 151
(`exp27`). Frame indices inside a session are **non-contiguous** — e.g. `exp50` spans indices
1-912 with only 80 images present — so frames were subsampled from longer recordings rather than
taken consecutively. That is why the ≤ 0 group count (40) is far lower than the pair count (483):
repetition is concentrated in a few near-static stretches, not spread evenly.

## Leakage risk and what a future split must do

**A random image-level split would leak badly.** 522 images (34.8%) have a near-duplicate at
Hamming ≤ 2, and the largest such group holds 150 images; splitting those randomly would place
near-identical frames on both sides of the boundary and score memorisation.

**A source/session-level split is both necessary and sufficient here** — and TUD-GV is the best
equipped of the three datasets to take one:

- Session ids are explicit in every filename; nothing has to be inferred.
- 98.3% of ≤ 2 near-duplicate pairs are intra-session, so grouping by session isolates almost all
  of them outright.
- 30 sessions with a long size tail (151 down to 3) give real freedom to hit a target ratio, unlike
  IWHR where near-duplicate chaining forced one component to 73.5% of the data.

The residual concern is the 55 cross-session pairs at ≤ 2, which a session split would not isolate.
They should be measured after any split is built and reported, exactly as the 6 residual IWHR pairs
were — **but no split is created here.**

## Comparison with the other two water datasets

| At Hamming ≤ 2 | IWHR | FloW-Img | **TUD-GV** |
| --- | --- | --- | --- |
| Images involved | 782 (26.1%) | 108 (9.0%) | **522 (34.8%)** |
| Groups | 304 | 45 | **39** |
| Largest group | 21 | 6 | **150** |
| Session metadata | recovered from XML `<filename>` | **none** | **explicit in filename** |

TUD-GV has the **densest** near-duplication of the three and the **best** metadata for handling it.
FloW-Img is the opposite: least duplication, no session metadata at all.
