---
title: Recovery Actions and Planning Timelines
domain: cross_signal
source: backend/core/recovery.py
---

# Recovery Actions and Planning Timelines

Source: `backend/core/recovery.py`.

## Timeline bands

Timelines are **categories, not predictions**. "Immediate (0-7 days)" is a planning horizon.
"The river will recover in 27 days" is a fabrication, and nothing in this system can produce one.

| Band | Horizon |
| --- | --- |
| immediate | 0-7 days |
| short_term | 1-4 weeks |
| medium_term | 1-3 months |
| long_term | 3-12+ months |

## Recommended actions by problem category

Each action is a response to the detected problem rather than generic environmental advice.

### Waste
1. Remove accumulated waste from the affected area — *immediate*
2. Identify the waste entry points feeding the accumulation — *short_term*
3. Re-survey the area across multiple time windows to confirm whether it returns — *short_term*

### Water
1. Re-sample water quality upstream and downstream of the analysis point — *immediate*
2. Check the reporting sensors and fill the missing parameters — *short_term*
3. Establish repeat measurements to distinguish a spike from a trend — *medium_term*

### Air
1. Confirm the reading against a second nearby monitoring station — *immediate*
2. Identify local emission activity during the hours the readings peaked — *short_term*
3. Track the pollutant against its baseline over several days — *medium_term*

## Three rules, each pinned by tests

1. **Never pad.** Reasons are returned as they exist, up to five. Three reasons means three, and
   the caller says so.
2. **Every reason cites evidence.** Each carries the evidence ids behind it, so the chain from
   claim to measurement to source stays walkable.
3. **Timelines are categories, not predictions.**

Geographic context carries no severity, so it can corroborate a reason but never be one.
