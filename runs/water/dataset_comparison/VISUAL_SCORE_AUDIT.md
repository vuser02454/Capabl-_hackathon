# `visual_score` — implementation audit

**Nothing was changed.** This documents the formula as it stands, every call site, and what a
detector swap would do to it.

## 1. Current formula

`backend/services/water_vision_service.py:370-382`

```python
def score_detections(detections, count_reference) -> float:
    if count_reference <= 0:
        return 0.0
    return round_half_up(clamp(len(detections) / count_reference))
```

**A normalised object count. Nothing else.** No confidence weighting, no per-class severity, no box
area, no image size. The docstring is explicit that this is deliberate: "No per-class severity
weighting is applied, because the dataset's class list is model-defined and we do not assume any
class is worse than another."

| Parameter | Default | Source |
| --- | --- | --- |
| `count_reference` | **20.0** | `ECOSENTINEL_WATER_VISUAL_COUNT_REFERENCE`, `config.py:107` |
| `water_visual_weight` | **0.25** | `ECOSENTINEL_WATER_VISUAL_WEIGHT`, `config.py:105` |
| `yolo_confidence_threshold` | 0.25 | `YOLO_CONFIDENCE_THRESHOLD`, `config.py:97` |

The parallel constant in the waste agent is `COUNT_REFERENCE = 24.0` (`waste_agent.py:18`) — the two
visual signals are scored the same way but **not with the same reference**.

## 2. Every call site

### Producer — one

| Location | Role |
| --- | --- |
| `water_vision_service.py:425` | `score = score_detections(output.detections, reference)` inside `build_report`. **The only place `visual_score` is computed.** |
| `water_vision_service.py:397` | `reference = settings.water_visual_count_reference if count_reference is None else count_reference` |
| `water_vision_service.py:434-435` | Written to `WaterVisionReport.visual_score`, and `visual_level = risk_level_for(score)` |

### Callers of `build_report` — four production paths

| Location | Path | Does `visual_score` reach the risk score? |
| --- | --- | --- |
| `agents/water_agent.py:194` | Water Agent with an image | **YES — this is the only path that moves risk** |
| `agents/water_agent.py:227` | Water Agent, no image | No — produces a `not_run` report |
| `agents/langgraph_orchestrator.py:418` | Frame investigation, standalone when the water specialist failed | No — investigation output only |
| `main.py:552` | `POST /api/water/scan-frame` | No — verdict only |
| `services/waste/waste_pipeline.py:144` | Waste segregation | No — the waste pipeline ignores `visual_score` |

### Consumer — the risk blend

`agents/water_agent.py:195-201`

```python
if vision_report.status == "ok" and vision_report.visual_score is not None:
    weight = clamp(settings.water_visual_weight)
    score  = round_half_up(clamp(quality_score + weight * vision_report.visual_score))
    blended = score != quality_score
```

and `water_agent.py:214-218` records the `water.visual_pollution` finding with
`impact = water_visual_weight * visual_score`.

**Escalation only.** The term is additive and non-negative, so vision can raise the water score but
never lower it — by design: "Visible pollution is corroborating evidence of harm; its absence is not
evidence of safety."

## 3. How it influences final Water risk

```
sensor/dataset parameters → quality_score
                              │
visual_score = len(dets)/20 ──┤  × water_visual_weight (0.25)
                              ▼
        score = clamp(quality_score + 0.25 × visual_score)
                              ▼
        risk_level_for(score)  →  LOW / MODERATE(≥0.40) / HIGH(≥0.70)
                              ▼
        WaterAgentResult → CoordinatorInput → core/risk.py → overall risk
```

Concretely, with the shipped defaults:

| Detections in frame | `visual_score` | Contribution to water score |
| --- | --- | --- |
| 1 | 0.05 | +0.0125 |
| 2 | 0.10 | +0.0250 |
| 5 | 0.25 | +0.0625 |
| 8 | 0.40 | +0.1000 |
| 10 | 0.50 | +0.1250 |
| 14 | 0.70 | +0.1750 |
| **20 or more** | **1.00 (clamped)** | **+0.2500 (maximum)** |

`visual_level` is a separate, **directly user-visible** band computed from `visual_score` alone
(`risk_level_for`, `core/risk.py:20-25`, thresholds 0.40 / 0.70):

- `visual_level = MODERATE` requires **8 detections** in one frame.
- `visual_level = HIGH` requires **14 detections** in one frame.

## 4. The assumed detection distribution

`count_reference = 20` encodes an assumption: **20 objects in one frame is maximum visual pollution
density.** Nothing in the codebase derives that number from data — it is a convention, chosen to
mirror the waste agent's 24.

Measured **ground-truth annotation density** in the three audited datasets:

| Dataset | Median | Mean | p90 | p99 | Max |
| --- | --- | --- | --- | --- | --- |
| IWHR | 6 | 7.90 | 16 | 32 | **43** |
| FloW-Img | 2 | 2.71 | 5 | 11 | 16 |
| TUD-GV | 5 | 5.45 | 9 | 11 | 14 |

A reference of 20 is therefore plausible for IWHR-like density, generous for TUD-GV (whose **maximum
observed density of 14 is exactly the HIGH threshold** — a TUD-GV-trained detector could reach HIGH
only on the single densest frame in its training distribution), and far too high for a bottle-only
detector.

## 5. Dependency on detector class and count

**Count: total.** `score_detections` receives `output.detections` — **every** detection the model
returned above `yolo_confidence_threshold`, with no class filter.

**Class: none, on this path.** `is_pollution_class` is **not** applied before scoring. Verified call
sites: `main.py:557` (`/api/water/scan-frame`) and `core/investigation.py:175, 253, 356, 401`
(frame investigation). **None of those is in the Water Agent blend path.**

Consequences with the COCO model currently configured (`YOLO26_MODEL_PATH=models/yolov8n.pt`):

- A `person`, `boat` or `car` on the bank contributes to `visual_score` exactly as a bottle does.
- A single-class litter detector would make every detection pollution-relevant, silently removing
  that flaw — **a behaviour change to state, not a free win.**

Verified against the live code, this class-name dependency is sharper than it looks:

| Class name | `is_pollution_class` |
| --- | --- |
| `floater` | **False** |
| `litter` | True |
| `bottle` | True |
| `floating_litter` | True |

A detector emitting `floater` would score identically in the Water Agent (no filter) but become
**invisible** to the frame-investigation path, which filters on `is_pollution_class` for actions,
escalation risks and narrative. **The two paths would disagree about whether anything was found.**

## 6. Consequences of changing detectors

Because the score is a raw count over a fixed reference, **swapping detectors changes the water risk
distribution even with identical weights, thresholds and configuration.**

Using each dataset's ground-truth density as a proxy for what a detector trained on it would tend to
emit:

| Detector trained on | % frames reaching `visual_level` MODERATE (≥8 det) | % reaching HIGH (≥14 det) | % saturating (≥20 det) | Median contribution |
| --- | --- | --- | --- | --- |
| IWHR-like | **36.4%** | **15.8%** | 6.3% | +0.0750 |
| TUD-GV-like | 22.5% | 0.2% | 0.0% | +0.0625 |
| FloW bottle-only | **4.2%** | 0.2% | 0.0% | +0.0250 |

**An IWHR-style detector would flag MODERATE visual pollution 8.7x more often than a bottle-only
detector on the same reference**, with no configuration change and nothing in the logs to indicate
why.

**These are annotation densities, not detector outputs.** A detector does not emit ground truth: it
misses objects (lowering counts) and produces false positives (raising them). Ground-truth density
is the distribution a detector is trained toward, so it is the best available proxy and it bounds
the honest range — but it is a proxy, and the recalibration below must use real detector output.

Two further dependencies:

- **Confidence threshold.** `visual_score` counts detections above `yolo_confidence_threshold`
  (0.25). Lowering it raises counts and therefore risk, with no change to the formula.
- **Duplicate boxes.** The waste pipeline de-duplicates class-agnostically at 0.7 IoU because YOLO
  runs NMS per class and one object can survive twice. **The water path has no such de-duplication**,
  so a multi-class detector can double-count a single object into `visual_score`.

## 7. What evidence is needed to recalibrate

`count_reference` must be **derived from measured detector output**, not chosen. Required, in order:

1. **A chosen detector and fixed configuration** — weights, confidence threshold, decoder. The
   figure is meaningless without them.
2. **Detector-output density on held-out frames**, not annotation density: run the chosen detector
   over a held-out split and record detections per frame. The TUD-GV split manifest provides a
   leakage-safe held-out set for this.
3. **A defensible definition of "maximum density"**, stated explicitly — e.g. the p95 of observed
   detector output on real deployment-like frames. It is a policy choice and should be recorded as
   one.
4. **Clean-water frames** (see `NEGATIVE_DATA_REQUIREMENTS.md`). Without them the false-positive
   contribution to the count is unknown, and `visual_score` counts false positives exactly as it
   counts real litter. **This is the binding constraint: no honest reference can be set while the
   false-positive rate is unmeasured.**
5. **A decision on de-duplication**, matching the waste pipeline's 0.7 IoU class-agnostic merge, or
   an explicit statement that the single-class detector makes it unnecessary.
6. **A decision on whether `is_pollution_class` should apply** to the blend path, so the two paths
   stop disagreeing.

Until 1-4 exist, the current default of 20 should be treated as **an unvalidated convention that
happens to suit IWHR-like density** — not as a calibrated threshold. Changing it without that
evidence would replace one unvalidated number with another.
