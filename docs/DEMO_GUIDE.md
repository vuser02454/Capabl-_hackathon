# Demo Guide

Everything needed to run EcoSentinel end to end, plus the exact sequence to present.

---

## 1. Start the system

**Terminal 1 — backend**
```bash
cd backend
../.venv/bin/python -m uvicorn main:app --reload --port 8000
```
Wait for `Application startup complete`, then confirm:
```bash
curl -s http://127.0.0.1:8000/api/health
# {"status":"ok","service":"EcoSentinel AI","version":"1.1.0","demoMode":true,...}
```

**Terminal 2 — frontend**
```bash
cd frontend
npm run dev
```
Open the printed URL (default `http://localhost:5173`).

> The backend must be started **from inside `backend/`**. Relative weights paths
> (`models/waste_detector.pt`) resolve against the backend directory; launching from the repo root
> reads as "no model configured" rather than "wrong working directory".

## 2. Verify before presenting

Run both. They take under a minute together and will catch a broken demo before an audience does.

```bash
# 1. reasoning scenarios, in-process, no network needed
.venv/bin/python backend/scripts/demo_scenarios.py

# 2. live server checks (backend must be running)
.venv/bin/python backend/scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

Expected: `All 5 scenario(s) passed.` and `27 passed · 0 failed`.

Full test suites:
```bash
.venv/bin/python -m pytest backend/tests -q     # 362 passed
cd frontend && npx tsc --noEmit && npx vitest run  # exit 0, 38 passed
```

## 3. The five scenarios

Every scenario prints `DEMO / SIMULATED INPUT`. Only the two *inputs* (a sensor reading, a
detector output) are fixtures — the agents, thresholds, evidence normaliser, conflict detection
and risk engine are all production code. Nothing fabricates a score, a conflict or an explanation.

```bash
.venv/bin/python backend/scripts/demo_scenarios.py --scenario C   # one at a time
```

| | Scenario | Input | Demonstrates |
| --- | --- | --- | --- |
| **A** | Visible water pollution | litter in frame + elevated chemistry | Visual signal escalates the measured score; each box becomes its own evidence item |
| **B** | Sensor-based concern | **no** visible litter + abnormal chemistry | Risk driven by chemistry alone; **no clean-water claim** is made |
| **C** | Conflicting evidence | litter visible + chemistry **normal** | **The centrepiece** — litter reported, chemical contamination NOT established, conflict surfaced |
| **D** | Waste classification | a waste photograph | detection → classification → confidence gate → segregation → Grad-CAM |
| **E** | Multi-agent event | air + water + waste | Full LangGraph run → deterministic risk → explanation |

### Scenario C, the one to spend time on

```
water risk        : 0.17  (LOW)
detector          : 2 object(s), 2 litter, 0 non-pollution
      - plastic_bottle   88%   -> visible_surface_litter
      - garbage          81%   -> visible_surface_litter
  OBSERVED          :
      - Visible plastic bottle: ... Observed surface litter; it establishes
        nothing about the water's chemistry.
  NOT ESTABLISHED   :
      - Chemical contamination (no chemistry was measured beyond the listed parameters)
      - That visible litter indicates any chemical change in the water
  CONFLICTS         :
      - Water measurements are within guideline limits while visual detections are
        elevated. Measurements and observations disagree; neither alone settles the question.
```

Litter is visible. The chemistry is fine. A naive system says "contaminated" or "clean" —
EcoSentinel says **what it saw, what it did not establish, and that the two signals disagree.**

## 4. Live UI walkthrough (8–10 minutes)

**1 · Dashboard (1 min)** — pick a location. Air, water, waste and overall risk. Point at the
`DEMO` badge: simulated data is labelled everywhere it appears.

**2 · Run an analysis (1 min)** — watch the three agents run **in parallel**, then the decision
panel: risk score, category, evidence, conflicts, recommended action. Note the explanation
provider is named, so it is clear an LLM wrote the *sentence*, not the *number*.

**3 · Water — the key demo (3 min)** — upload a water photo. Show the vision panel:

- **Visible litter: N** — and beneath it, *of M objects detected*
- **Also detected — not counted as pollution** — the other objects, shown rather than hidden
- **Not established** — chemical contamination, pH, potability

> Say this out loud: *"The detector found six objects here. Two are people and four are kites.
> None of them are litter, so none of them move the water risk. Before we fixed this, all six
> counted as visible pollution and pushed the risk up by eight points."*

**4 · Waste with XAI (2 min)** — tick **Explain (Grad-CAM)**, upload a waste photo, click a
detection. The heatmap concentrates on the **metal lid and rim** of a can — the model's own
gradients, at `features[-1]`, 7×7. Say that it is regional, not pixel-level.

Then show a low-confidence case: the label appears as a **candidate**, segregation is withheld,
and the message names both models' guesses.

**5 · Conflicts (1 min)** — close on the conflict panel. Observation, inference and
verification-required are three different things, and the system keeps them apart.

## 5. Good and bad demo inputs

| Use | Avoid |
| --- | --- |
| `runs/debug_waste/original/metal_can.jpg` — confident, clean XAI | `runs/debug_waste/original/plastic_bottle.jpg` — detector returns **0 detections** |
| `runs/debug_waste/original/plastic_bag.jpg` — 96% confirmed | Crowded scenes with many tiny objects (TACO-like) — low recall |
| `runs/debug_waste/original/paper.jpg` — shows the abstain path honestly | |
| `water_datasets/TUD-GV/images/exp55_221.jpg` — shows the non-pollution filter | |

`plastic_bottle.jpg` is a genuine recall gap, not a crash. If you want to show a failure mode
deliberately, it is a good one — but do not stumble into it.

## 6. If something breaks mid-demo

| Symptom | Cause | Action |
| --- | --- | --- |
| Frontend shows a network error | backend not running / wrong port | restart from `backend/`; check `/api/health` |
| "No weights at models/…" | backend launched from repo root | restart from inside `backend/` |
| Analysis is slow | Overpass (OSM) is a free shared service | capped at 10 s; it degrades, it does not hang |
| Explanation is templated, not LLM prose | no LLM key, or provider down | **this is the designed fallback** — say so; the decision is unchanged |
| Vision "unavailable" | weights missing | sensor analysis still runs; the panel states the reason |

Every one of these degrades to a working system with a stated reason. Nothing silently invents a
result — which is worth saying out loud if it happens.

## 7. Offline

The demo does not depend on external APIs. `ECOSENTINEL_DEMO_MODE=true` (the default) uses seeded
fixtures for air, water and waste; `demo_scenarios.py` needs no network at all. Both LLM roles can
be set to `none` and every explanation falls back to deterministic text.
