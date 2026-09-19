---
title: Waste Classes, Segregation Categories and Handling
domain: waste
source: training/config/waste_categories.json
---

# Waste Classes, Segregation Categories and Handling

Source: `training/config/waste_categories.json`. The mapping is held as data, not code, so it can
be corrected for a locality without touching the pipeline — what counts as recyclable varies by
municipality, and a hard-coded mapping would quietly export one region's rules everywhere.

`category` is the ML-facing segregation label. `handling` is an **application-level policy
heuristic** and is deliberately separate: the model predicts what an object is, it does not know
how a given council processes it.

## The eight classes

| Class | Segregation category | Handling |
| --- | --- | --- |
| food_waste | biodegradable | organic |
| leaf_waste | biodegradable | organic |
| wood_waste | biodegradable | organic |
| paper_waste | biodegradable | fibre_recyclable |
| plastic_bottles | non_biodegradable | recyclable |
| metal_cans | non_biodegradable | recyclable |
| plastic_bags | non_biodegradable | persistent |
| ewaste | non_biodegradable | hazardous |

## Handling notes

- **organic** — Breaks down naturally; compostable in most systems.
- **fibre_recyclable** — Degrades naturally, and recoverable as fibre while it is still dry and
  clean.
- **recyclable** — Non-degrading but widely recoverable through recycling streams.
- **persistent** — Non-degrading and poorly recovered; fragments rather than breaking down.
- **hazardous** — Contains components requiring specialist handling; should not enter general
  waste.

Notes are keyed by `handling`, not by material. Paper has its own `fibre_recyclable` key because
the shared `recyclable` note reads "non-degrading", which is correct for plastic and metal and
wrong for paper — paper would otherwise be described as biodegradable and non-degrading on the
same card.

## Confidence thresholds

- `detection_confidence`: 0.25 — below this the detector does not report a box at all.
- `classification_confidence`: 0.60 — below this the pipeline reports `uncertain` rather than a
  best guess.

The 0.60 bar is also the **assertion bar** for the detector's own class. A detector label is only
asserted as a confirmed segregation category when the detector clears 0.60; below that the label
is carried as a candidate and no segregation is claimed.

## What the pipeline refuses to do

- Report a detection the detector did not make.
- Assert a segregation category below the configured threshold.
- Claim the classifier is available when no trained weights exist.
- Let the environmental interpretation masquerade as a model output.
