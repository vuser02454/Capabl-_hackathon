---
title: Air Quality Pollutants, WHO Guidelines and NAQI
domain: air
source: backend/agents/air_agent.py (POLLUTANTS, NAQI_BREAKPOINTS)
---

# Air Quality Pollutants, WHO Guidelines and NAQI

Source: `backend/agents/air_agent.py`, `POLLUTANTS` and `NAQI_BREAKPOINTS`.

## Pollutants and WHO 2021 guidelines

Four pollutants are scored. `guideline` is the WHO 2021 24-hour guideline (O3 is the 8-hour
guideline). `reference` is the concentration treated as maximum risk when normalising.

| Pollutant | Weight | WHO 2021 guideline | Reference (max risk) |
| --- | --- | --- | --- |
| PM2.5 | 0.55 | 15 µg/m³ | 100 µg/m³ |
| PM10 | 0.25 | 45 µg/m³ | 180 µg/m³ |
| NO₂ | 0.12 | 25 µg/m³ | 80 µg/m³ |
| O₃ | 0.08 | 100 µg/m³ (8-hour) | 100 µg/m³ |

PM2.5 carries the largest weight, so it dominates the air risk score.

## India National AQI (NAQI)

NAQI sub-indices are computed for PM2.5 and PM10 by linear interpolation within breakpoint bands.

PM2.5 breakpoints (concentration low, high -> index low, high):
0–30 -> 0–50; 31–60 -> 51–100; 61–90 -> 101–200; 91–120 -> 201–300; 121–250 -> 301–400;
251–500 -> 401–500.

PM10 breakpoints:
0–50 -> 0–50; 51–100 -> 51–100; 101–250 -> 101–200; 251–350 -> 201–300; 351–430 -> 301–400;
431–1000 -> 401–500.

Categories: Good (<=50), Satisfactory (<=100), Moderate (<=200), Poor (<=300), Very Poor (<=400),
Severe (above).

**Important limitation.** Official NAQI is computed over a 24-hour average. This system applies
the breakpoints to single readings, so the reported figure is an **estimate**, not an official
AQI, and it is labelled as such in the response.

## Confidence and anomalies

- Reference-grade regulatory station: base confidence 0.95.
- Low-cost sensor network: base confidence 0.80.
- Each missing pollutant reduces confidence by 0.15; each pollutant filled from an older
  "latest available" reading reduces it by 0.05.
- An anomaly is flagged when a reading exceeds its 24-hour baseline by a ratio of 1.15.

The 24-hour PM2.5 baseline is the **only genuine historical comparison in the entire system**.
It is therefore the only source from which a direction of "deteriorating" may be claimed. Water
and waste return a single point in time, so their direction stays "unknown" rather than a
fabricated "stable".
