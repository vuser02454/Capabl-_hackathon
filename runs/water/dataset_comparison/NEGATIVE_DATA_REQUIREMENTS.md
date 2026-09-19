# Clean-water negative data — requirements specification

**No dataset was downloaded.** This specifies what a valid negative set must contain, so that a
candidate can be judged before it is acquired.

## Why this is a blocker and not a refinement

All three audited datasets have **zero images containing no annotated object**:

| Dataset | Images | Images with no objects |
| --- | --- | --- |
| IWHR | 3,000 | **0** |
| FloW-Img | 1,200 | **0** |
| TUD-GV | 1,501 | **0** |

A detector trained and evaluated only on these can report recall but **cannot support any claim
about false positives**. Three specific consequences:

1. **`visual_score` counts false positives identically to real litter** (`len(detections)/20`). An
   uncalibrated false-positive rate propagates straight into the water risk score, and escalates it
   — the blend is additive and can only raise the score.
2. **TUD-GV's own imagery makes this worse.** Its visual audit recorded persistent specular glare
   and wind ripple that resemble small pale litter, and it contains no clean frames to calibrate
   against.
3. **EcoSentinel already has a measured clean-water blind spot.** The reference-dataset matcher has
   only **~15-33% recall on clean `Baja` frames**, because only 4 of 29 source clips are clean
   water. Adding a detector with an unmeasured false-positive rate would repeat that failure in a
   second subsystem.

**This cannot be solved by merging the three datasets.** Negatives must be acquired.

## Mandatory content requirements

| # | Requirement | Why | Acceptance test |
| --- | --- | --- | --- |
| N1 | **Real water scenes**, photographic | Synthetic or rendered water does not reproduce the glare and ripple statistics that cause false positives | No rendered, composited or generated imagery |
| N2 | **No target floating litter present** — verified, not assumed | A single unnoticed bottle turns a negative into a mislabelled positive | Human verification pass per image, recorded per image, not sampled |
| N3 | **Varied specular reflections** — sky, cloud, bank, structures | Reflections are a leading false-positive source | ≥20% of frames carry visible specular reflection |
| N4 | **Vegetation** — floating, emergent and overhanging | Duckweed, algae and leaves are the hardest true negatives; IWHR labels these as *positives*, so they are the sharpest disambiguation case | ≥20% of frames contain surface or overhanging vegetation |
| N5 | **Waves and surface texture** — still, rippled, wind-driven, wake | Ripple crests read as small pale objects | ≥3 distinct surface states represented |
| N6 | **Shadows** — bank, bridge, vegetation, structure | Shadow edges produce high-contrast blobs | ≥15% of frames contain a cast shadow crossing water |
| N7 | **Glare** — direct sun, backlight, low-angle | The highest-severity false-positive case | ≥10% of frames carry visible glare or blown highlights |
| N8 | **Turbidity range** — clear, green, brown, algal | Object-water contrast varies with turbidity | ≥3 turbidity bands, each ≥15% of frames |
| N9 | **Different viewpoints** — overhead, oblique, water-level, shore-based | A negative set from one viewpoint only calibrates one viewpoint | ≥3 distinct camera geometries; **no single viewpoint >50%** |
| N10 | **Different lighting** — overcast, direct sun, golden hour, deep shade | Illumination changes the false-positive rate | ≥3 lighting conditions, each ≥15% |
| N11 | **No leakage from the positive datasets** | A negative frame that is a near-duplicate of a training positive is not an independent test | See below |

## Requirements that follow from EcoSentinel specifically

| # | Requirement | Why |
| --- | --- | --- |
| N12 | **Natural organic matter present and unannotated** | C1: IWHR treats algae and water plants as `floater` **by documented policy**; TUD-GV treats them as background. Negatives containing organic matter are the only way to measure which behaviour a trained model actually learned |
| N13 | **Non-litter objects present** — boats, people, birds, moorings, bank furniture | The blend path applies **no** `is_pollution_class` filter, so any detection raises risk. Whether the detector fires on a moored boat is a risk-scoring question, not a cosmetic one |
| N14 | **Frames from the same installations as the positives, at times with no litter** | The strongest negatives share background with the positives so the model cannot separate them on scene identity alone. For TUD-GV these would be pre- or post-release frames from the same `exp` sessions |
| N15 | **Deployment-representative frames**, if a target deployment is known | A reference calibrated on European canals may not transfer to the deployment water body |

## Leakage exclusion protocol (N11)

Reuse the methodology already applied three times in this project:

1. **SHA-256** over image bytes against all 5,701 audited positives → reject any exact match.
2. **64-bit dHash**, reject any candidate within **Hamming ≤ 2** of any positive image.
3. **Report residual pairs** at distances 3-8 rather than silently accepting them, as the IWHR and
   TUD-GV splits both do.
4. **Session/source-level exclusion** where session metadata exists: if a negative comes from a
   TUD-GV `exp` session, it must sit in the **same split** as that session, never across.

**Do not use "no annotation" as the negative criterion.** N2 requires *verified absence*. All three
audited datasets have undocumented negative definitions, and an unannotated region in any of them
may mean out-of-scope or annotator omission rather than absence — that distinction is the core
finding of `LABEL_CONTRACTS.md`.

## Minimum viable size

A false-positive rate is a proportion, so the requirement is precision on the estimate, not a round
number.

| Purpose | Frames | Rationale |
| --- | --- | --- |
| **Calibration floor** | **≥300** verified-clean frames | At a true FP rate of 5%, 300 frames give roughly ±2.5% at 95% confidence — enough to distinguish 5% from 15% |
| **Per-condition analysis** | **≥600** | Reporting FP rate per viewpoint, turbidity and lighting band needs ≥50 frames per cell |
| **Recalibrating `count_reference`** | **≥300**, deployment-representative | `VISUAL_SCORE_AUDIT.md` §7 item 4 |

Fewer than ~300 verified-clean frames supports a qualitative statement ("it fires on glare") but not
a rate.

## What the negative set will and will not establish

**Will:** the false-positive rate per frame and per condition; whether the detector fires on
vegetation, glare, ripple, boats and people; the evidence needed to set `count_reference` honestly;
a regression baseline for future detector swaps.

**Will not:** anything about recall — that needs positives. Anything about **chemical
contamination** — clean-*looking* water is not clean water, and no image establishes water
chemistry. A frame with no visible litter is evidence of *no visible litter*, nothing more, and the
Water Agent's separation of `measurements` from `visual_pollution` must continue to enforce that.

## Acceptance checklist

A candidate negative dataset is acceptable when **all** hold:

- [ ] N1-N11 satisfied, each with the stated acceptance test measured and recorded
- [ ] N12-N13 satisfied (EcoSentinel-specific disambiguation cases present)
- [ ] ≥300 frames verified clean **by human review, recorded per image**
- [ ] Zero exact and zero Hamming ≤ 2 matches against all 5,701 audited positive images
- [ ] Residual near-duplicates at distance 3-8 counted and reported
- [ ] Licence verified from an authoritative record, as in `LICENSE_PROVENANCE_REPORT.md`
- [ ] Provenance recorded: source, authors, capture conditions, date
