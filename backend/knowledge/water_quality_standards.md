---
title: Water Quality Parameters and Thresholds
domain: water
source: backend/agents/water_agent.py (PARAMETERS)
---

# Water Quality Parameters and Thresholds

The Water Agent scores four parameters. Each carries a threshold, a weight in the combined
water-quality score, and the reference the threshold comes from.

Source: `backend/agents/water_agent.py`, `PARAMETERS`.

## pH

Acceptable range is **6.5 to 8.5** (BIS 10500). A reading below 6.5 is reported as acidic water
pH; above 8.5 as alkaline. The sub-score is the distance from neutral pH 7.0 divided by 1.5,
clamped to 0..1. Weight in the water score: 0.20. Readings outside 0–14 are rejected as
out-of-range rather than scored.

pH is a **measured chemical parameter**. It cannot be determined from a photograph.

## Turbidity

Threshold is **5 NTU** (BIS permissible limit). The sub-score is the reading divided by 21,
clamped to 0..1. Weight: 0.55 — the highest of the four, so turbidity dominates the water-quality
score. A finding reports the multiple of the permissible limit, for example "9 NTU · 1.8x BIS
permissible limit". Readings outside 0–4000 NTU are rejected.

Turbidity is a measure of suspended particles scattering light. High turbidity indicates cloudy
water; it does not by itself identify what the particles are.

## Temperature

Threshold is **26 °C**, reported as thermal stress. The sub-score is (value - 18) / 14, clamped.
Weight: 0.25. Elevated water temperature reduces dissolved oxygen. Readings outside -5 to 60 °C
are rejected.

## Total Dissolved Solids (TDS)

Threshold is **500 mg/L** (BIS acceptable limit). Sub-score is the reading divided by 1000,
clamped. Weight: 0.15. TDS is **optional**: it is only scored when the source actually reports it,
so a sensor without a TDS channel is not penalised for the gap.

## How the parameters combine

The water-quality score is the weighted mean of the sub-scores of the parameters that were
actually reported:

    quality_score = sum(weight * sub_score) / sum(weight of reported parameters)

A parameter that is missing or rejected is recorded as `status: missing` and excluded from both
sums. If no parameter is usable the agent raises rather than returning a score, because a score
derived from nothing is worse than an error.

## Risk bands

Source: `backend/core/risk.py`.

- **HIGH** at score >= 0.70
- **MODERATE** at score >= 0.40
- **LOW** below 0.40

## What measurement establishes, and what it does not

These four parameters establish what they measure and nothing further. In particular they do not
establish the presence of heavy metals, pathogens, BOD, COD or any specific chemical. A water
body can pass all four and still be unsafe for a use these parameters do not cover.
