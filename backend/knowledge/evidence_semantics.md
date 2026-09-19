---
title: Evidence Semantics — Observation, Inference and What Is Not Established
domain: cross_signal
source: backend/core/investigation.py, backend/core/evidence.py
---

# Evidence Semantics

Source: `backend/core/investigation.py` and `backend/core/evidence.py`.

## Claim strength

Every reason carries a type saying how strongly the evidence backs it:

- **OBSERVED** — the detector located it in this frame, or a sensor measured it.
- **INFERRED** — follows from several observations in this frame.
- **HYPOTHESIS** — suggested by context; not established.
- **UNKNOWN** — a data gap, stated so it cannot be mistaken for a finding.

Reasons are capped at five and **never padded** to reach it.

## What an image can and cannot establish

An image is the most persuasive and least measurable evidence this system handles, so the wording
enforces the difference.

An image **can** support:
- visible floating litter
- visible surface debris
- visible waste accumulation
- observable surface condition

An image **cannot** establish:
- pH, dissolved oxygen, BOD, COD
- heavy metals or pathogens
- chemical identity or chemical contamination
- potability

Absence of visible litter is **not** evidence that water is clean. Visible pollution corroborates
harm; its absence corroborates nothing.

## Semantic categories for detections

The raw detector class is never overwritten. The interpretation is carried beside it:

- **visible_surface_litter** — the class indicates anthropogenic litter or debris.
- **non_pollution_object** — the detector's own class rules pollution out (person, boat, car).
- **unclassified_object** — a real detection this taxonomy makes no claim about.

Only `visible_surface_litter` may move a risk score. `unclassified_object` is not counted,
because counting an object the taxonomy cannot place would be inferring pollution from ignorance.

## Conflicts are surfaced, not averaged

Where a domain's measurements are within guideline limits while its detections are elevated, the
system reports the disagreement:

> Measurements are within guideline limits while visual detections are elevated. Measurements and
> observations disagree; neither alone settles the question.

Forcing a mixed picture into one direction is how a dashboard ends up saying "improving" while
half its indicators worsen.

## Geographic context is not evidence of pollution

Mapped OpenStreetMap features enter at severity 0.0 and confidence 0.0. A mapped factory is a
polygon a contributor drew: it is not an emission and must never raise a risk score. It exists so
reasoning can say "industrial activity is mapped nearby" alongside a measurement, never as a cause.
