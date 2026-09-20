# EcoSentinel — C3 Safety Intelligence

An incident-precursor detection system for workplace safety. Workers report hazards from their
phones with a photo and a confirmed GPS fix; a LangGraph agent workflow extracts the facts,
classifies the risk, finds geographic clusters, routes emergencies to the relevant authority and
explains every conclusion from stored evidence. A human safety officer decides what, if anything,
workers are told.

The product was pivoted from an earlier environmental-monitoring system (air / water / waste).
Those agents still run and their routes still work — they are documented from
[Repository Layout](#repository-layout) onward and are no longer the primary product.

## The one rule everything else follows

**Rules decide, the LLM describes.** Every number — risk score, risk level, cluster membership,
route distance — is produced by deterministic code. Groq is used for summaries and phrasing, and
the system is fully functional with the LLM switched off; the classification is byte-identical
either way. A model that occasionally invents a risk level would be worse than no model.

Three consequences you can check in the code:

- **No detection publishes anything.** A cluster of related reports becomes a `PENDING_REVIEW`
  *candidate*. Only a human pressing "Publish Alert" makes it visible to workers.
- **Nothing is invented.** Authority names and phone numbers come from OpenStreetMap or are
  reported as absent. Incident history cites the report ids it counted.
- **Absence is stated, not implied.** "Authority lookup unavailable", "no route avoids the
  published alert", "no previous reports within 1 km" are all real answers the system gives.

## Quick start

```bash
# backend  (http://127.0.0.1:8000, docs at /docs)
cd backend && source ../.venv/bin/activate && python -m uvicorn main:app --port 8000 --reload

# frontend (http://localhost:5174)
cd frontend && npm run dev

# seed 10 synthetic workers, 3 admins and 45 geo-tagged reports (idempotent)
curl -X POST http://127.0.0.1:8000/api/admin/seed-demo-data
```

Open <http://localhost:5174>, let the landing animation play, then choose **Worker** or
**Safety Admin**.

```bash
# verify
cd backend && python -m pytest -q          # 683 tests
cd frontend && npx vitest run              # 113 tests
cd frontend && npm run typecheck           # clean
```

## The agent workflow

```text
START
  ↓
parse                Report Parser Agent       free text → structured facts (regex, deterministic)
  ↓
risk                 Risk Analysis Agent       LOW / MEDIUM / HIGH, weighted, with cited evidence
  ↓
store                                          persist BEFORE comparison, so a report counts
  ↓                                            toward its own pattern
patterns             Pattern Detection Agent   recurring hazards, locations, departments
  ↓
hotspots             Geographic Hotspot Agent  3+ related reports within 1 km → candidate
  ↓
incident_domain      Incident Domain Agent     MEDICAL / FIRE / VIOLENCE_SECURITY / ELECTRICAL /
  ↓                                            CHEMICAL / WILDLIFE / EQUIPMENT / GENERAL_SAFETY /
  │                                            ENVIRONMENTAL / OTHER
  ├──[emergency_router — a LangGraph conditional edge]
  │
  ├── specialized_response   emergency domains only: nearest relevant authority from OpenStreetMap
  └── advise                 everything else: prioritised, specific recommendations
  ↓
explainable_advisor  Explainable Advisor       incident history within 1 km, cited by report id
  ↓
END
```

`store` runs **before** `patterns` on purpose: otherwise the very first report of a recurring
problem reports "no pattern" and the system misses the thing it exists to catch.

## Hotspot detection — the exact rule

```python
HOTSPOT_MIN_REPORTS   = 3        # safety/geo.py
HOTSPOT_RADIUS_METERS = 1000     # 1 km, configurable
```

Proximity alone is not enough. Two reports are **related** when they are within the radius **and**
their hazard families intersect — an oil spill, a forklift oil leak and a slip on oily flooring
cluster; an oil spill, a broken light and a noise complaint do not. Clustering is single-link
union-find over the related-and-near graph using haversine distance, sorted by report id so the
output is deterministic.

> This is an application-level demo threshold, **not a regulatory standard**. The API says so in
> every response that carries it, and the UI displays it.

## Worker routing — Dijkstra, and conditional safety

Dijkstra runs in `safety/routing.py` over a road graph this backend builds from OpenStreetMap way
geometry fetched through Overpass. **No external routing service is called** — OSM supplies the
roads, not the route.

The safety rule is **conditional**, which is the part most easily got wrong:

```text
dijkstra(start, destination)  →  shortest route
        ↓
  does it come within ROUTE_SAFETY_RADIUS_METERS (500 m) of a PUBLISHED alert?
        ↓                                  ↓
       NO                                 YES
        ↓                                  ↓
  return it unchanged.              generate alternatives by distance (Yen's k-shortest),
  Nothing else is computed.         return the first that is clear.
                                    If none is clear, say so — never call it safe.
```

Three radii mean three different things and are deliberately separate:

| Constant | Value | Question |
| --- | --- | --- |
| `HOTSPOT_RADIUS_METERS` | 1000 m | How far apart related *reports* may be and still cluster |
| `alert.radius_meters` | admin-set | The area an admin drew when publishing |
| `ROUTE_SAFETY_RADIUS_METERS` | 500 m | How close a *route* may come before it is rejected |

**Only PUBLISHED alerts affect routing.** A candidate hotspot is an unreviewed hypothesis a worker
never sees; a route bending around one would leak its existence through the shape of the path.
A test asserts a 1 km candidate sitting directly on a route changes nothing.

## Roles and the privacy boundary

| | Worker | Safety Admin |
| --- | --- | --- |
| Submit a report, photo, GPS | ✅ | |
| Their **own** report history | ✅ | |
| Published safety alerts | ✅ | ✅ |
| Another worker's reports | ❌ | ✅ (for follow-up) |
| Candidate hotspots, review notes, AI reasoning | ❌ | ✅ |
| Their own route history | ✅ | ✅ (all workers) |
| Worker location history | own only | ❌ (not needed to act on a report) |

The boundary is enforced **server-side in SQL**, not by filtering in the client: worker endpoints
simply never select the columns a worker may not see.

> **There is no authentication.** This is a demo. `employee_id` is a handle, not a credential, and
> role selection lives in `localStorage`. The *data* boundary is real — a worker's query cannot
> return another worker's rows — but anyone may pass any id. A real deployment needs auth in front
> of `/api/admin/*` and `/api/worker/*`.

## Route history

Every explicit `POST /api/worker/route` records one `worker_route_event`. **This is not tracking**
— there is no `watchPosition`, no polling and no background writer; the calculation the worker
asked for *is* the event.

The route **geometry** is stored, both the shortest route and the one served. A route recomputed
later from start + destination would reflect today's map and today's alerts, which is exactly what
historical evidence must not do — so an admin proving "this worker was rerouted" sees the rejected
route beside the served one, as they were at the time.

Each event is classified deterministically (no model):

| | |
| --- | --- |
| `NORMAL_ROUTE` | no published alert within the route safety radius |
| `MODERATE_HAZARD_PASSED` | the route runs past a published alert; no high-severity detour |
| `HIGH_HAZARD_DETOUR` | a HIGH-severity alert rejected the shortest route; an alternative was taken |
| `NO_SAFE_ALTERNATIVE` | affected, and nothing clear was found within `MAX_ROUTE_DETOUR_RATIO` (1.6) |

> **Route history begins when recording was introduced.** Nothing before it exists, and the API
> and UI both say so. Absence from an affected-workers list is not evidence that nobody passed
> through.

## Safety assistant

A chatbot grounded in this project's database, at `POST /api/safety/chat`.

```
question → deterministic intent match → controlled read-only tool → evidence → LLM phrasing
```

The model never writes SQL and never sees the database. It picks from a fixed table of functions
in `safety/chat_tools.py`, is handed what they returned, and is asked to phrase it. Three rules
are structural rather than prompted:

- **It cannot invent.** No tool result means "I don't have enough recorded data to answer that",
  and no model is called at all. Every answer ships with `deterministicAnswer` — the same facts
  composed with no model — so the phrasing can be checked against them.
- **It cannot act.** Every tool is a read. Publishing, dismissing, resolving, changing a severity
  or contacting an authority is refused before any query runs.
- **It cannot cross the worker boundary.** A worker's tools take the caller's employee id from the
  session, never from the question, so naming another worker returns your own records or nothing.

Mounted separately from the environmental `/api/chat`, which is grounded in one `analysisId` and
has a different contract.

## Location and photo provenance

Location is optional at every step and is requested only on an explicit press. A denial is a
supported path, not an error: the worker can search for a place or tap the map instead, and the
report is never blocked.

`location_source` records which it was — `browser_gps`, `text_search`, `manual_map`, `unknown`, or
`demo_seed` for seeded rows. Seeded coordinates are **never** labelled `browser_gps`, so invented
numbers cannot contaminate an analysis of real GPS accuracy.

**EXIF is deliberately ignored.** The authoritative geotag is the fix the worker confirmed in the
app. Browsers often strip EXIF from a canvas capture, and an embedded position can be stale or
absent — relying on it would put hazards in the wrong place.

Location is stored only when the worker explicitly asks for it or files a report carrying one.
There is no scheduler, no polling endpoint and no background writer; a test asserts only two
location-writing routes exist.

## Database

```text
safety_user ──┬── worker_location   (explicit events only, never a trail)
              ├── worker_route_event (one per explicit route request; stores both geometries)
              └── safety_report ──── report_analysis
                        │                photo file on disk, path in the row
                        └── safety_hotspot ── safety_announcement
                                   ├── admin_action           (what a human did)
                                   └── recommendation_feedback (was the advice useful)
```

SQLite via the standard library, no ORM. Migrations are additive `ALTER TABLE` statements, so an
existing database is upgraded in place and never rebuilt.

## API

**Worker** — `POST /api/worker/reports` · `POST /api/worker/reports/{id}/photo` ·
`GET /api/worker/me` · `GET /api/worker/reports` · `GET /api/worker/reports/{id}` ·
`GET /api/worker/location-history` · `POST /api/worker/locations` ·
`GET /api/worker/routes` · `GET /api/worker/routes/{id}` · `GET /api/worker/cautions` ·
`POST /api/worker/verify-location` ·
`GET /api/worker/alerts` · `GET /api/worker/map` · `POST /api/worker/route`

**Admin** — `GET /api/admin/dashboard` · `/map` · `/reports` · `/reports/{id}` ·
`/reports/{id}/photo` · `/hotspots` · `/hotspots/{id}` · `POST /hotspots/{id}/{action}` ·
`POST /hotspots/flag` · `/announcements` · `/actions` · `/feedback` · `/workers` ·
`/workers/{employee_id}/reports` · `/workers/{employee_id}/routes` · `/routes` ·
`/routes/{id}` · `/alerts/{id}/affected-workers` · `/alerts/{id}/rerouted-workers` ·
`POST /seed-demo-data`

**Assistant** — `POST /api/safety/chat`

**Analysis** — `POST /api/reports/analyze` · `/batch-analyze` · `GET /api/analytics/overview` ·
`/analytics/patterns` · `GET /api/agents/workflow` · `/agents/status` · `GET /api/health`

Full schemas at <http://127.0.0.1:8000/docs>.

## Screens

| Route | |
| --- | --- |
| `/` | Landing animation, then **Continue as** Worker / Safety Admin |
| `/worker/report` | Describe the hazard, take a live photo, confirm a location |
| `/worker/my-reports` | The worker's own history, each report on the map |
| `/worker/map` | Published alerts, destination search, routing |
| `/worker/alerts` | Published alerts as a list |
| `/admin/dashboard` | Counts, domain breakdown, review queue |
| `/admin/map` | Reports, candidates, investigations, published alerts |
| `/admin/hotspots` | Review queue: evidence, history, authority, actions, publish |
| `/admin/reports` | Every report with its photo and provenance |
| `/admin/announcements` | What workers can currently see |
| `/admin/worker-routes` | Route Intelligence: recorded decisions, original vs selected route |
| `/worker/my-routes` | The worker's own recorded routes and why any changed |

## Demo data

`POST /api/admin/seed-demo-data` creates 10 workers and 3 safety admins across seven departments,
with 45 geo-tagged reports between them. Deterministic (fixed seed) and **idempotent** — users
match on `employee_id`, reports on text plus author, so re-running creates nothing and deletes
nothing.

All identities are synthetic. Names are `Worker 001`, addresses use `@example.com` (RFC 2606,
which can never belong to anyone), and coordinates are offsets from Bengaluru city centre. No real
person's identity or location is represented.

## What this system does not claim

- It does **not** replace a qualified safety professional. Every analysis carries that disclaimer.
- A photograph does **not** prove chemical contamination, and the system never says it does.
- AI risk classifications are **screening**, not official safety determinations.
- The 1 km / 3-report rule and the 100 m route radius are **application thresholds**, not
  regulatory standards.
- The system **contacts nobody**. "Contacted Police" is a log entry a human writes after the fact.
- A pattern in reports is evidence about *reporting*, not a measurement of the world — the
  explainable assessment says this in as many words.

## Deployment

Repository: <https://github.com/vuser02454/Capabl-_hackathon>

### Environment variables

**Backend** (Render dashboard — never in the repo):

| Variable | Purpose |
| --- | --- |
| `ECOSENTINEL_DB_PATH` | SQLite file. On Render: `/var/data/safety.db` |
| `ECOSENTINEL_REPORTS_PATH` | Uploaded photos. On Render: `/var/data/report_photos` |
| `ECOSENTINEL_ROUTE_CACHE_DIR` | Cached OSM road graphs. On Render: `/var/data/route_graph_cache` |
| `ECOSENTINEL_CORS_ORIGINS` | The Vercel origin, comma separated. Defaults to `*` |
| `ECOSENTINEL_NOMINATIM_USER_AGENT` | Identifies the deployment to OpenStreetMap, as their policy requires |
| `GROQ_API_KEY` | **Optional.** Risk classification is deterministic without it; Groq only phrases summaries |

**Frontend** (Vercel):

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | The backend origin, no trailing slash. Blank locally, where Vite's dev proxy handles it |

> `VITE_*` variables are compiled into a bundle every visitor downloads. **Never put a key there** —
> no Groq key, no Gemini key, no database credential. A frontend test fails the build if one appears.

### Render (backend)

[`render.yaml`](render.yaml) defines the service: `uvicorn main:app --host 0.0.0.0 --port $PORT`,
health check at `/health`.

> **A persistent disk is required, not optional.** This service keeps its SQLite database and
> worker-uploaded photos on the local filesystem, and Render's ordinary filesystem is ephemeral.
> **Without a disk mounted at `/var/data`, every deploy and every restart silently discards all
> reports, users, route history and photos.** The blueprint declares a 1 GB disk and points the
> three path variables into it; a paid plan is needed for one. Do not treat this storage as
> durable on a free instance.

### Vercel (frontend)

[`vercel.json`](vercel.json) builds `frontend/` and rewrites unmatched paths to `index.html`, so a
cold load of `/worker/map` or `/admin/dashboard` does not 404. Set `VITE_API_BASE_URL` to the
Render URL, then add that Vercel origin to `ECOSENTINEL_CORS_ORIGINS` on the backend — both sides
have to know about each other.

### Production authentication

> **There is none.** `employee_id` is a handle, not a credential, and role selection lives in
> `localStorage`. The *data* boundaries are real and enforced in SQL — a worker's query cannot
> return another worker's rows — but anyone may pass any id. **A real deployment must put
> authentication in front of `/api/admin/*` and `/api/worker/*`.**

## Notifications

Worker → Admin and Admin → Worker, in one `safety_notification` table.

Filing a report raises an admin notification carrying the report id, risk level, extracted
hazards, coordinates, GPS accuracy and location source — enough to act on, and clickable through
to the incident. A failure to notify never costs the report.

Admins can broadcast to every worker or target named employee ids. A worker's payload is a strict
subset: no sender, no report id, no GPS accuracy, no extracted risk factors. Broadcast read state
lives in `notification_read` per reader, so one worker opening an announcement does not mark it
read for the other fourteen.

> **A notification is a message, not a hazard.** Only a published safety alert affects routing.
> The send panel says so, and a test asserts an announcement leaves a route byte-identical.

---

# Retained environmental subsystem

Everything below documents the earlier air / water / waste product. Those agents still run, their
routes still respond, and the documentation is kept because the code is kept. It is no longer the
primary product.

The `docs/` set was written for that system and still describes it accurately — read it for the
environmental agents, not for Safety Intelligence:

| Document | Read it for |
| --- | --- |
| [docs/FINAL_ARCHITECTURE.md](docs/FINAL_ARCHITECTURE.md) | The environmental system end to end |
| [docs/MODEL_LIMITATIONS.md](docs/MODEL_LIMITATIONS.md) | Measured metrics and every known weakness |
| [docs/DATASET_PROVENANCE.md](docs/DATASET_PROVENANCE.md) | Licences, splits, attribution, open blockers |
| [docs/FINAL_VALIDATION.md](docs/FINAL_VALIDATION.md) | What was tested, before/after per fix |
| [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) | The environmental demo scenarios |
| [docs/CHATBOT_ARCHITECTURE.md](docs/CHATBOT_ARCHITECTURE.md) | Chat routing, tool authority, grounding |

```bash
# the environmental subsystem's own checks
.venv/bin/python backend/scripts/demo_scenarios.py   # reasoning scenarios, offline
.venv/bin/python backend/scripts/smoke_test.py       # live-server checks
```

## Repository Layout

```text
.
├── README.md
├── requirements.txt              # -> backend/requirements.txt
├── index.html / styles.css / script.js   # legacy static prototype
├── inference_waste.py            # CLI for the two-stage waste pipeline (image / video / webcam)
├── shared/
│   ├── locations.json
│   └── water_sensors.json
├── training/                     # waste model pipeline (see training/README.md)
│   ├── validate_dataset.py           # dataset quality report: duplicates, imbalance, unusable files
│   ├── waste_preprocess.py           # the single definition of image -> tensor, shared with serving
│   ├── train_waste_classifier.py     # stage 2: 8-class waste classifier
│   ├── evaluate_classifier.py        # held-out metrics, macro-F1 selected
│   ├── inspect_taco.py               # TACO category survey before any mapping is written
│   ├── convert_taco_to_yolo.py       # TACO COCO annotations -> YOLO, unmapped classes excluded
│   ├── download_taco_images.py
│   ├── train_waste_detector.py       # stage 1: TACO-trained detector (trained, not deployed)
│   ├── ab_test_detectors.py          # COCO vs TACO through the production call path
│   ├── ab_test_extras.py             # false-positive probe, latency
│   ├── ab_test_visuals.py            # annotated correct / missed / wrong crops
│   └── config/
│       ├── waste_categories.json         # segregation mapping + thresholds (data, not code)
│       └── taco_taxonomy_mapping.json    # TACO category -> project class
├── runs/                         # training + evaluation artefacts (the evidence, kept)
│   ├── classification/               # served classifier weights + training manifest
│   ├── classification_letterbox{,_v2}/   # retrained, measured worse, kept as the reason not to deploy
│   ├── evaluation/                   # held-out classification report
│   └── waste_detection/
│       ├── AB_TEST_REPORT.md             # COCO vs TACO detector, full method and numbers
│       ├── taco_yolov8n/                 # detector training run
│       └── ab_test/                      # annotated visual evidence per error bucket
├── datasets/                     # water reference frames (Alta/Media/Baja) + taco_yolo/
├── garbage_Dataset/              # waste classification images (train/val, not in git)
├── TACO-master/                  # upstream TACO annotations + downloader
├── frontend/                     # React + TypeScript + Vite dashboard
│   ├── src/
│   │   ├── pages/                # Worker, Admin and Safety pages (plus retained environmental)
│   │   │   ├── WorkerPages.tsx        # report, alerts, map (with destination routing)
│   │   │   ├── MyReportsPage.tsx      # the worker's own report history
│   │   │   ├── AdminPages.tsx         # dashboard, reports, hotspot review, announcements
│   │   │   └── AdminMapPage.tsx       # reports, candidates and published alerts on OSM
│   │   ├── components/           # agents, architecture, charts, coordinator, map, ui...
│   │   │   ├── safety/                # SafetyMap (Leaflet/OSM), LocationPicker,
│   │   │   │                          # LivePhotoCapture, RoutePanel, IncidentIntelligence
│   │   │   ├── dashboard/            # LocationBar, LocationSelector, DataProvenance
│   │   │   └── coordinator/          # CoordinatorPanel, DecisionPanel (decision + trace)
│   │   ├── hooks/                 # useBrowserLocation (one-shot GPS), usePlaceSearch, useLiveLocation
│   │   ├── services/              # API client, analysis engine, providers, history
│   │   ├── context/               # Analysis / Navigation / Settings / Toast contexts
│   │   └── lib/                   # formatting, risk scoring, routing helpers
│   ├── vitest.config.ts           # jsdom test env for the location hooks
│   └── vite.config.ts
└── backend/                      # FastAPI service
    ├── main.py                   # app entry point; mounts the safety, worker and admin routers
    ├── safety/                    # C3 Safety Intelligence — the primary product
    │   ├── rules.py                   # hazard/control regexes, weights, thresholds (deterministic)
    │   ├── agents.py                  # Parser, Risk, Pattern, Advisor agents
    │   ├── graph.py                   # the LangGraph workflow incl. the emergency conditional edge
    │   ├── domains.py                 # incident-domain routing + serious-incident markers
    │   ├── geo.py                     # haversine, hazard families, 1 km / 3-report clustering
    │   ├── history.py                 # incident history within 1 km + explainable assessment
    │   ├── authority.py               # nearest police/fire/medical from OpenStreetMap Overpass
    │   ├── routing.py                 # RoadGraph, Dijkstra, Yen k-shortest, conditional safety
    │   ├── people.py                  # synthetic workers/admins + idempotent seeding
    │   ├── store.py                   # SQLite schema, additive migrations, all persistence
    │   ├── api.py                     # analysis + analytics routes
    │   ├── roles_api.py               # /api/worker/* and /api/admin/* (the privacy boundary)
    │   ├── llm.py                     # optional Groq narration; everything works without it
    │   ├── service.py                 # corpus operations and seeding
    │   └── synthetic.py               # the 47 original synthetic reports
    ├── config.py                 # environment-driven settings (backend/.env)
    ├── schemas.py                 # Pydantic request/response models
    ├── models/                    # detector weights: yolov8n.pt (served), waste_detector.pt (not served)
    ├── agents/                    # air, water, waste, coordinator agents + both orchestrators
    │   ├── orchestrator.py            # original ThreadPoolExecutor-based orchestrator
    │   ├── langgraph_orchestrator.py   # LangGraph StateGraph orchestrator (default for /api/analyze)
    │   └── llm_reasoning.py            # optional Coordinator LLM narrative (off by default)
    ├── core/                      # errors, geo math, risk scoring, deterministic rng
    │   ├── risk.py                    # shared risk primitives (unchanged scale of record)
    │   ├── evidence.py                # specialist reports -> normalized evidence
    │   ├── decision.py                # problems, cross-signal, conflicts, priority, synthesis
    │   ├── investigation.py           # investigation planning + NEVER_WASTE_CLASSES exclusions
    │   └── recovery.py                # derived recovery timelines
    ├── data/                      # location profiles, history generation, example datasets
    ├── services/                  # OpenAQ, geocoding, Overpass, water sensor registry, waste detection
    │   ├── waste/                     # the two-stage waste pipeline
    │   │   ├── waste_classifier.py        # stage 2: crop -> class -> segregation
    │   │   ├── waste_pipeline.py          # analyze_waste(image) -> structured JSON
    │   │   └── waste_debug.py             # per-stage dump behind /api/waste/debug
    │   ├── ai/                        # functional (Gemini) + explainability providers, chatbot
    │   ├── water_vision_service.py    # the shared YOLO detector and its decoder
    │   ├── geocoding_service.py       # Nominatim, both directions, throttled + cached
    │   ├── openaq_service.py          # OpenAQ v3 stations and readings
    │   ├── overpass_service.py        # nearby water bodies + geographic context features
    │   └── location_service.py        # one LocationContext per analysis; geographic context resolver
    ├── data/safety.db             # SQLite store (gitignored; recreated on first run)
    ├── scripts/                   # check_openaq.py connectivity check
    └── tests/                     # pytest suite, 683 tests
        ├── test_safety_agents.py          # extraction, scoring, classification
        ├── test_safety_geo.py             # the 1 km rule, review flow, privacy boundary
        ├── test_safety_intelligence.py    # domain routing, authority lookup, history, actions
        ├── test_routing.py                # Dijkstra, Yen, conditional safety routing
        └── test_worker_persistence.py     # identity, location events, report history
```

## Backend API

The FastAPI backend exposes:

```text
GET  /api/health
GET  /api/agents/status
GET  /api/locations
POST /api/location/reverse
POST /api/location/search
POST /api/location/context
GET  /api/environment/{location}
POST /api/environment
POST /api/analyze
POST /api/analyze/graph
POST /api/waste/analyze
GET  /api/waste/pipeline-status
POST /api/waste/segregate
POST /api/waste/debug
POST /api/water/analyze-image
POST /api/water/match-frame
POST /api/water/scan-frame
POST /api/water/nearby-bodies
GET  /api/water/dataset-status
GET  /api/ai/status
POST /api/chat
POST /api/reports/contamination
POST /api/sensors/water/{sensor_id}/readings
```

- `/api/analyze` and `/api/waste/analyze` run the full agent pipeline (air, water, waste, coordinator) for a resolved location, in demo mode or against live providers. `/api/analyze` runs through the LangGraph orchestrator by default (see below).
- `/api/analyze/graph` is a development/testing endpoint that always runs the LangGraph orchestrator, regardless of the `ECOSENTINEL_LANGGRAPH_ORCHESTRATION` toggle. It is not required by the frontend.
- `/api/location/reverse` resolves coordinates to a place name via OpenStreetMap Nominatim, cached server-side; coordinates are only ever sent in POST bodies, never query strings or logs. `/api/location/search` is the same service in the other direction — a free-text place name to coordinates, so any place can be analysed rather than only the presets in `shared/locations.json`.
- `/api/location/context` returns the OpenStreetMap features **mapped** near a point — industrial land, waste facilities, waterways and major roads — from Overpass. Context only: a mapped factory is a polygon a contributor drew, not an emission and not evidence that anything is polluting. It never fails the caller; an unreachable, rate-limited or disabled Overpass returns `available: false` with a reason.
- `/api/water/nearby-bodies` lists water bodies near a point from OpenStreetMap via the Overpass API (see below). Geography only — it names the lake, it says nothing about its quality.
- `/api/waste/segregate` runs the two-stage waste pipeline on an uploaded image — YOLO detection, then the trained classifier on each crop — and returns per-object segregation with an explicit `uncertain` bucket. `/api/waste/pipeline-status` reports which stages are actually available and which weights are loaded, so "no classifier" is never confused with "no waste found". `/api/waste/debug` dumps each stage's intermediate output for one image. See [Waste Detection and Segregation](#waste-detection-and-segregation).
- `/api/water/analyze-image` runs the Water Agent with a photo attached, adding the visual-pollution and reference-match blocks to its report. `/api/water/match-frame` does the reference match alone — the fast path the live camera polls every couple of seconds, alongside `/api/water/scan-frame` for the detector-only verdict.
- `/api/reports/contamination` records a citizen report of apparently contaminated water. It is the one endpoint that **persists precise coordinates**, and only ever runs after an explicit confirmation in the UI. It forwards the report onwards only when `ECOSENTINEL_AUTHORITY_WEBHOOK_URL` is configured; with no destination it returns `status: "recorded"` and says plainly that nothing was transmitted.
- `/api/sensors/water/{sensor_id}/readings` is a push endpoint for ESP32 boards or an MQTT bridge, gated behind a bearer-style sensor token.

Interactive API docs are available at `http://127.0.0.1:8000/docs` once the backend is running.

## Data Providers

Each specialist agent is backed by a provider that can run in **demo mode** (deterministic mock data, no network access or API keys) or **live mode**:

| Agent | Service | Live data source |
| --- | --- | --- |
| Air Quality | `services/openaq_service.py` | [OpenAQ](https://explore.openaq.org) v3 API (requires a free API key) |
| Water Quality | `services/water_sensor_service.py` | Registered sensors in `shared/water_sensors.json`, with Firebase Realtime Database or MQTT ingest, falling back to a historical dataset |
| Waste Detection | `services/waste_detection_service.py` | Structured for a future YOLO-based image detector; currently mock analysis. The **agent** is unchanged — the trained waste models live on the separate `/api/waste/segregate` path, not in the risk pipeline |
| Waste segregation | `services/waste/` | `backend/models/yolov8n.pt` (detection) + `runs/classification/best.pt` (8-class classifier). See [Waste Detection and Segregation](#waste-detection-and-segregation) |
| Vision detector | `services/water_vision_service.py` | Local Ultralytics weights at `YOLO26_MODEL_PATH`, or Roboflow hosted inference; shared by the water and waste image paths |
| Geocoding | `services/geocoding_service.py` | OpenStreetMap Nominatim — reverse (coordinates → place) and forward (place → coordinates) |
| Geographic context | `services/overpass_service.py` | OpenStreetMap Overpass — mapped industrial / waste / waterway / road features near a point. Context only; never a measurement, never scored. |

Provider selection is controlled per-agent via environment variables (`ECOSENTINEL_AIR_PROVIDER`, `ECOSENTINEL_WATER_PROVIDER`, `ECOSENTINEL_WASTE_PROVIDER`), each defaulting to `auto`: use live data when configured, otherwise fall back to demo data.

## Orchestration (LangGraph)

`POST /api/analyze` is orchestrated by an explicit **LangGraph `StateGraph`** (`backend/agents/langgraph_orchestrator.py`) rather than hand-written sequencing. It sits *above* the existing agents and providers — it does not replace them, and it never turns provider data into free-form LLM text:

```text
Provider → Specialist Agent → Typed Pydantic Report → Coordinator → Deterministic Decision
```

**Graph nodes and edges:**

```text
START → resolve_location → triage_environment
      → { run_air | run_water | run_waste | context_enrichment }     (concurrent investigators)
      → coordinate                                                    (deterministic risk)
      → normalize_evidence → detect_problems → cross_signal_reasoning
      → evaluate_conflicts → check_data_sufficiency
      → [conditional]  decision_synthesis | investigation_needed
      → explain_decision → END
```

The graph is the decision workflow, not just a scheduler: it decides which investigations a
location warrants, what the evidence supports, whether that evidence settles the question, and
what to collect when it does not. See [Decision Engine](#decision-engine).

- **`resolve_location`** — builds the single `LocationContext` every other node uses (`services/location_service.py`, reused unchanged).
- **`run_air` / `run_water` / `run_waste`** — each wraps the existing `AirQualityAgent` / `WaterQualityAgent` / `WasteDetectionAgent` (`agents/air_agent.py`, `water_agent.py`, `waste_agent.py`) in `asyncio.to_thread(...)` under its own `asyncio.wait_for(..., timeout=ECOSENTINEL_AGENT_TIMEOUT)`. Because none of the three depends on the others' output, LangGraph runs them **concurrently** in the same superstep — a slow air-quality lookup no longer delays the water or waste readings.
- **`triage_environment`** — decides which investigations this location warrants. Deterministic availability rules only: a domain is skipped when its provider cannot answer, never because a model judged it irrelevant. Skipping a measurement on a guess is how a real exceedance goes unreported.
- **`context_enrichment`** — asks Overpass what OpenStreetMap has *mapped* near the point, and writes the result to the analysis response only. It joins the same parallel wave as the specialists rather than sitting between location resolution and them: no specialist consumes it, so making them queue behind a donated third-party service would add latency for nothing. Demo Mode skips it entirely rather than querying a shared service for a fabricated location.
- **`coordinate`** — builds a `CoordinatorInput` from whichever specialist reports actually succeeded (never raw provider data, never coordinates) and runs the existing deterministic `CoordinatorAgent` (`agents/coordinator_agent.py`, `core/risk.py` — unchanged scoring formulas, unchanged `WEIGHTS`/thresholds).

- **`normalize_evidence` → `detect_problems` → `cross_signal_reasoning` → `evaluate_conflicts` → `check_data_sufficiency` → `decision_synthesis` → `explain_decision`** — the decision stages, described under [Decision Engine](#decision-engine). They run *after* `coordinate` deliberately: the engine consumes the deterministic risk score as one input rather than computing a rival one.

**Why `context_enrichment` is bounded by its own timeout.** The `coordinate` fan-in waits on *every* incoming edge, including this one — so an unbounded enrichment node stalls the whole assessment. Against a rate-limited Overpass this was measured at **over 120 seconds**, well past the frontend's own 30-second limit, and the dashboard surfaced it as a request timeout with no result at all. `ECOSENTINEL_OVERPASS_CONTEXT_TIMEOUT` (default 10 s) caps it: enrichment is optional, the assessment is not, so enrichment is what gets dropped. Regression: `tests/test_geographic_context.py::test_a_stalled_overpass_cannot_stall_the_analysis`.

**Failure handling** — a specialist failure or timeout never aborts the graph:

| Scenario | Result |
| --- | --- |
| All three specialists succeed | Coordinator receives all three reports; full assessment. |
| One specialist fails/times out | That agent's slot is `null`; its `AgentRun.status` is `"failed"` or `"timeout"` with a message; the Coordinator reasons over the rest and lists the missing agent in `missingInputs` and `dataLimitations`. |
| Two specialists fail | Coordinator still produces a full assessment from the one remaining report. |
| All three fail | No measurement is fabricated. The API still returns `200` with `coordinator.insufficientData = true`, `overallScore = 0`, `confidence = 0`, and a `"Retry the analysis"` recommendation — never an HTTP error for a data problem. |
| Overpass is down, rate-limited, disabled or slow | `geographicContext.available = false` carries the reason. Risk scores are **byte-identical** to a run where Overpass was never consulted — asserted by `test_enrichment_failure_does_not_change_the_risk_score`. |

**What the Coordinator does and does not do:**

- It only reasons over the typed `AirAgentResult` / `WaterAgentResult` / `WasteAgentResult` objects and a location *label* — never latitude/longitude, API keys, provider credentials, internal service URLs, or the geographic context (enforced by `backend/tests/test_orchestrator_location.py::test_coordinator_consumes_only_specialist_reports`, which statically asserts `coordinator_agent.py` never imports `services`, `httpx`, `requests`, `urllib`, or `http`).
- **Risk scoring stays deterministic.** `overallRiskLevel`, `overallScore`, `confidence`, and `contributions` are always computed by `core/risk.py` / `coordinator_agent.py` — no LLM is in that path, so the same inputs always produce the same score.
- **Cross-signal reasoning** (e.g. "elevated PM2.5 alongside high litter density near a water body") uses hedged language — *"may indicate"*, *"is consistent with"*, *"insufficient evidence to determine causality"* — and never claims one signal caused another.
- **`dataLimitations`** is populated deterministically from fields the specialist reports already carry (`isMock`, `dataAgeMinutes`, `sensorStatus`, `inputType`) — e.g. *"Water readings are 45 minutes old."*, *"Waste analysis is image-based."* No LLM is required for this.

**Optional LLM narrative** (`agents/llm_reasoning.py`) — off by default (`LLM_PROVIDER=none`). If set to `gemini`, `openai`, or `groq` (with the matching optional LangChain package installed and an API key configured), the Coordinator asks that model for a short *additional* narrative (`coordinator.llmNarrative`) explaining the already-computed result — it never sets or overrides the score. The system prompt explicitly tells the model to treat every specialist field as **untrusted data, not instructions**, to guard against prompt injection through station names, filenames, or warning text. Any failure (missing package, missing key, timeout, model error) is caught and silently ignored — the deterministic result is used as-is, so demo mode never needs this and never calls out to a model.

**Observability** — every graph run logs (to the standard `ecosentinel.langgraph` logger, no secrets): `graph_execution_started/completed`, `location_resolved`, and `agent_started/completed/failed` for each of the four agents, each tagged with a per-request `request_id` and duration. Coordinates, API keys, and sensor tokens are never logged.

**Rollback switch** — set `ECOSENTINEL_LANGGRAPH_ORCHESTRATION=false` to route `/api/analyze` back through the original sequential `AnalysisOrchestrator` (`agents/orchestrator.py`); `POST /api/analyze/graph` always uses the LangGraph path for development/testing regardless of this flag. Both orchestrators call the exact same `build_agents(demo_mode)` factory, so provider selection and demo-mode numbers are identical either way (see `backend/tests/test_langgraph_orchestrator.py::test_demo_mode_scores_match_pre_langgraph_orchestrator`).

**Example `/api/analyze` response (trimmed):**

```json
{
  "location": "Bengaluru",
  "mode": "demo",
  "air": { "riskLevel": "HIGH", "pm25": 92.3, "aqi": 210, "dataSource": "Demo dataset (OpenAQ-compatible)" },
  "water": { "riskLevel": "LOW", "ph": 7.2, "turbidity": 3.1, "sensorStatus": "online" },
  "waste": { "riskLevel": "HIGH", "totalObjects": 17, "counts": { "plastic": 11, "paper": 3, "other": 3 } },
  "coordinator": {
    "overallRiskLevel": "HIGH",
    "overallScore": 0.81,
    "confidence": 0.89,
    "reasoning": "Air pollution and litter density are the dominant risk factors, while water-quality indicators remain within acceptable limits.",
    "crossSignalInsights": [
      "High PM2.5 near a plastic-heavy litter zone warrants a check for open waste burning."
    ],
    "recommendations": [
      { "title": "Inspect waste accumulation zone", "urgency": "Immediate", "agent": "waste" },
      { "title": "Issue air-quality health advisory", "urgency": "Within 24h", "agent": "air" }
    ],
    "dataLimitations": ["Air-quality data is simulated demo data, not a live reading."],
    "insufficientData": false,
    "llmEnhanced": false
  },
  "runs": [
    { "agent": "air", "status": "complete", "durationMs": 4 },
    { "agent": "water", "status": "complete", "durationMs": 2 },
    { "agent": "waste", "status": "complete", "durationMs": 3 },
    { "agent": "coordinator", "status": "complete", "durationMs": 1 }
  ]
}
```

## Decision Engine

The graph does not stop at "here are three reports and a score". It asks what environmental
problem the evidence points to, which signals corroborate it, what contradicts it, how confident
that makes the system, and what is worth collecting next.

```text
evidence → problems → cross-signal → conflicts → priority → decision → investigation plan
```

Two separations do most of the work, and the tests enforce both.

**Risk is not the problem.** `HIGH` risk does not mean "water pollution". Risk (from the
deterministic Coordinator) is *how much concern*; the problem classification is *what the evidence
points toward*. They are computed separately and reported separately — the engine reads the
Coordinator's score and never derives a competing one.

**An LLM never decides anything.** The whole chain above is deterministic
(`backend/core/evidence.py`, `backend/core/decision.py`). When `EXPLAINABILITY_AI_PROVIDER` is
configured, the `explain_decision` node adds `llmExplanation` — prose about a finished decision. It
cannot change the score, the confidence, the priorities or the evidence, and every failure leaves
the decision untouched. The deterministic `explanation` is always present. Verified against live
providers: the decision fingerprint is identical with the explainability layer on and off.

### Evidence

Every specialist report is normalised into one representation, so later stages never need to know
that air measures µg/m³ against a WHO guideline while waste counts objects in a frame. Severity is
carried over from the specialists' own `sub_score`, not recomputed, so `core/risk.py` stays the
single scale of record. Mapped OpenStreetMap features enter as evidence with **severity 0 and
confidence 0** — context can be cited, never scored.

### Problem priority — the exact formula

```text
priority = severity_score × confidence × evidence_strength × persistence
```

| Term | Range | Meaning |
| --- | --- | --- |
| `severity_score` | 0–1 | the specialist's own deterministic score |
| `confidence` | 0–1 | the specialist's own confidence |
| `evidence_strength` | 0.5 / 0.75 / 1.0 | 1, 2, or 3+ independent supporting evidence items |
| `persistence` | 0.75 / 1.0 | 1.0 when a real baseline comparison supports it, 0.75 otherwise |

It is a product, so weakness anywhere pulls the result down: a severe problem nobody is confident
about ranks below a moderate one confirmed from several angles. No LLM contributes to this number.

The **primary concern is always a domain problem**, never the `cross_signal` meta-problem —
"multiple interacting risks" tells an operator that several things are wrong without saying where
to start. The co-occurrence is still reported, as a cross-signal finding.

### What the engine refuses to say

> **Trends.** Only the air agent has a real historical baseline (a 24-hour PM2.5 comparison). The
> water and waste providers return a single point in time, so `overallDirection` reports
> `insufficient_history` rather than `stable`. Reporting "stable" would assert a trend nobody
> measured. The mechanism is in place: once a provider supplies history, direction and the
> persistence factor both start working without further changes.

> **Causes.** Cross-signal findings carry `causality: "not_established"`, fixed in the schema so
> no caller can set it otherwise. Mapped industry beside elevated readings is reported as
> *"mapped features describe what is present, not what is emitting; the available evidence does
> not establish that this feature caused the readings."*

> **Certainty it does not have.** With fewer than two reporting domains nothing can be
> cross-checked, so the engine declines to name a primary concern and routes through
> `investigation_needed` instead — a conditional edge, not a fallback.

### Explainability

Every decision carries a `decisionTrace`: an ordered chain from evidence, through the problems it
supported, the cross-signal findings and conflicts, the Coordinator's risk score, to the decision
and *why that problem outranked the others*. A test asserts every evidence id cited in the trace
exists in the evidence list, so the chain can always be audited rather than merely read.

The dashboard's **Environmental Decision** panel renders this chain behind *"Why this decision?"*,
with three views: decision trace, evidence (supporting items highlighted), and investigation plan.
Contradictory evidence is given the same prominence as supporting evidence.

### Investigation planning

When evidence is thin the engine says what is missing, why it matters, and which provider can
supply it — for example *"Capture repeat observations across multiple time windows"*, because a
single snapshot cannot distinguish a persistent problem from a transient spike.

## AI Architecture

Three LLM providers, **two roles that are not interchangeable**. Presenting them as a single
"choose your AI" list would be the wrong mental model: it implies they do the same job, and a user
swapping one for another would silently change what the system is allowed to decide.

```text
                    LangGraph decision workflow
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
      FUNCTIONAL AI                   EXPLAINABLE AI
         Gemini                     OpenRouter / Groq
              │                               │
    performs AI work                 explains a finished
    output → evidence                decision to the user
              │                               │
              ▼                               ▼
   deterministic engine weighs it    cannot change anything
```

### Functional AI — Gemini

Runs *before* a decision exists and contributes to it, so it is held to the stricter contract:

- **Structured or nothing.** Output is validated against `FunctionalAnalysis`. A malformed
  response becomes `status="invalid_response"` and contributes no evidence — it never reaches the
  decision half-parsed and never raises into the analysis.
- **Observation, not verdict.** Results enter as evidence alongside sensor readings, where the
  deterministic engine weighs them. The schema has no field through which a functional provider
  could set a risk level, severity or priority.
- **It does not replace a detector.** YOLO remains the object detector for waste and water
  imagery — it is trained for that and returns real bounding boxes. Gemini interprets; it does not
  localise, and bounding boxes are never invented.
- `uncertainties` is part of the contract, because what a vision model *cannot* tell you is often
  the useful part: an image can show floating plastic but can never establish chemical contamination.

### Explainable AI — OpenRouter / Groq

Runs *after* the decision is complete and immutable. A provider returns a string; that string is
stored in its own field. **There is no code path from a response to a number.**

If a model replies *"actually I think the main problem is air pollution"*, the decision does not
change — the claim simply appears in prose beside a decision saying otherwise. A visible,
auditable disagreement rather than a silent override. Asserted by
`test_an_explanation_cannot_change_the_decision` and `test_every_protected_field_survives_an_explanation`.

Both are reached over their OpenAI-compatible `/chat/completions` endpoints using the stdlib,
matching how `openaq_service.py` and `overpass_service.py` talk to their APIs — two more
dependency trees would be a lot of machinery for one POST returning text.

**No automatic failover.** The configured provider is used; if it is unreachable the deterministic
explanation stands. Silently answering via a different model than the operator chose is its own
kind of dishonesty.

**Two things only a real call revealed**, both worth knowing before configuring Groq:

- **Groq rejects `urllib`.** Its Cloudflare edge answers stdlib requests with `error code: 1010`
  whatever `User-Agent` they carry, while accepting `requests` — which is why this one service
  uses `requests` where the rest of the backend uses the stdlib. The block page surfaced as a
  `403`, which reads exactly like an auth failure until the response body is printed.
- **`llama-3.3-70b-versatile` is not available** on current Groq accounts. The default is now
  `openai/gpt-oss-120b`; list what a key can actually reach with
  `GET https://api.groq.com/openai/v1/models`. Provider error messages are passed through verbatim,
  so "the model does not exist" no longer arrives as a bare status code.

### Decision Engine — LangGraph

Controls the investigation and decision workflow. See [Decision Engine](#decision-engine).

### Deterministic Risk Engine

Risk scores, problem priorities and evidence sufficiency are always computed deterministically
(`core/risk.py`, `core/decision.py`). No LLM is in that path, in either role.

### Reasons, recovery and timelines are derived, not written

"Why is this deteriorating?", "what should we do?", "how long?" look like questions for a language
model, and that is the trap: a model asked for five reasons produces five whether or not five
exist. The substance is derived in `core/recovery.py` from evidence the system actually holds, and
the explainability layer only phrases it.

- **Reasons are never padded.** Three evidence-supported reasons means three, and the answer says
  *"3 evidence-supported reasons identified"*. Each cites the evidence ids behind it.
- **Recovery actions follow the detected problem**, not generic environmental advice. No problem
  detected means no actions offered.
- **Timelines are planning horizons** — `Immediate 0-7 days`, `Short term 1-4 weeks`,
  `Medium term 1-3 months`, `Long term 3-12+ months` — labelled *"estimated planning timeline, not
  a guaranteed recovery prediction"*. "The river will recover in 27 days" is unreachable by
  construction.

### Chatbot — grounded in one analysis

`POST /api/chat` answers questions about a **specific** `analysisId`. Every answer reads from that
analysis's decision state, and an unknown id is **refused rather than answered** from whichever
analysis ran most recently. Explaining River B with River A's evidence reads perfectly and is
entirely wrong, which makes it the worst failure this component could have.

The chatbot works with **no LLM configured at all** — every question has a deterministic answer
derived from the decision; an explainability provider only rephrases it.

### Status and secrets

`GET /api/ai/status` reports both roles separately — provider, whether configured, whether
available, and the model — and never returns a key, a fragment of one, or anything from which one
could be derived. Keys live in `backend/.env` only; there is no `VITE_GEMINI_API_KEY`,
`VITE_GROQ_API_KEY` or `VITE_OPENROUTER_API_KEY`, and a frontend test fails the build if one
appears.

## Local Run

### Backend

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

# optional: enable live providers
cp backend/.env.example backend/.env
# then edit backend/.env — e.g. set OPENAQ_API_KEY

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: http://127.0.0.1:8000/docs

Run the backend test suite — full success, each specialist failing individually, multiple/all specialists failing, timeout isolation, Nominatim and Overpass parsing/caching/throttling, geographic-context degradation, and that `/api/analyze` stays API-compatible. Entirely offline: `tests/conftest.py` points both OSM services at unroutable addresses, disables Overpass, blanks the OpenAQ key, and every client is stubbed.

```bash
python3 -m pip install -r backend/requirements-dev.txt
pytest backend/tests
```

To exercise the LangGraph path directly instead of through the API, run it in a Python shell from `backend/`:

```python
import asyncio
from agents.langgraph_orchestrator import LangGraphOrchestrator

result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
print(result.coordinator.overall_risk_level, result.coordinator.overall_score)
```

### Waste models (optional)

The training scripts and the served classifier need dependencies that are **not** in
`requirements.txt` — torch is large, and nothing in the API requires it. Without them the
classifier reports `unavailable` and every other route keeps working:

```bash
python3 -m pip install torch torchvision ultralytics
```

`ultralytics` is needed for the detection stage and for `training/train_waste_detector.py`; torch
and torchvision alone are enough to train and evaluate the classifier. See
[Waste Detection and Segregation](#waste-detection-and-segregation).

### Frontend (React dashboard)

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — the Vite dev server proxies `/api` requests to the backend on port 8000.

Other frontend scripts: `npm run build` (typecheck + production build), `npm run preview`, `npm run typecheck`.

Run the frontend test suite (vitest + jsdom — browser geolocation success and every failure mode, permission-prompt discipline, debounced Nominatim search, and the guard that no shipped source file reads a `VITE_*` credential or names a provider host):

```bash
npm test
```

**Seeing it work end to end.** With the backend running and Demo Mode switched off in Settings, the dashboard asks for location on load, resolves it through Nominatim, and analyses those coordinates. Deny the permission and the manual search takes over — type three or more characters into the location dropdown to search OpenStreetMap. The `DataProvenance` panel underneath the overview cards shows which providers actually answered.

### Legacy static prototype (optional)

The original static dashboard at the repository root can still be served directly:

```bash
python3 -m http.server 8080
```

Then open http://127.0.0.1:8080/index.html. It talks to the same backend API but predates the React rewrite and is not actively maintained.

## Environment Configuration

Backend settings are read from environment variables (see `backend/.env.example` for the full list), including:

- `ECOSENTINEL_AIR_PROVIDER`, `OPENAQ_API_KEY`, `ECOSENTINEL_OPENAQ_RADIUS_M`, `ECOSENTINEL_OPENAQ_MAX_AGE_HOURS`
- `ECOSENTINEL_WATER_PROVIDER`, `ECOSENTINEL_WATER_REGISTRY_PATH`, `FIREBASE_DB_URL`, `ECOSENTINEL_SENSOR_INGEST_TOKEN`
- `ECOSENTINEL_NOMINATIM_USER_AGENT`, `NOMINATIM_EMAIL`, `ECOSENTINEL_GEOCODE_CACHE_DISTANCE_M`
- `ECOSENTINEL_DEMO_MODE`, `ECOSENTINEL_CORS_ORIGINS`, `ECOSENTINEL_AGENT_TIMEOUT`
- `ECOSENTINEL_LANGGRAPH_ORCHESTRATION` (default `true`) — routes `/api/analyze` through the LangGraph orchestrator; set `false` to use the original sequential orchestrator instead
- `FUNCTIONAL_AI_PROVIDER` (`none` default | `gemini`), `GEMINI_API_KEY`, `GEMINI_MODEL` — functional AI; its validated output enters as evidence and can never set a score. See [AI Architecture](#ai-architecture)
- `EXPLAINABILITY_AI_PROVIDER` (`none` default | `openrouter` | `groq`), `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `GROQ_API_KEY`, `GROQ_MODEL` — explainable AI; explains a finished decision and can change nothing about it. No automatic failover between the two
- `LLM_TIMEOUT_SECONDS` (default `30`) — shared ceiling for both AI roles
- `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` — the legacy single-provider Coordinator narrative, superseded by the two roles above and still honoured for existing deployments
- `ECOSENTINEL_WATER_VISION_PROVIDER` (`auto` | `local` | `roboflow`), `YOLO26_MODEL_PATH`, `YOLO_CONFIDENCE_THRESHOLD` (default `0.25`), `ROBOFLOW_API_KEY`, `ROBOFLOW_MODEL_ID` — the YOLO detector shared by the water and waste image paths. The model name reported by the API is derived from the weights file actually loaded, never asserted, so an operator can see which weights produced a detection. Relative paths resolve against `backend/`, not the process working directory. Pointing this at `models/waste_detector.pt` switches on the TACO detector — read [Waste Detection and Segregation](#waste-detection-and-segregation) first, including what it does to the non-waste gate
- `ECOSENTINEL_WATER_DATASET_IMAGES_PATH` (default `datasets/`), `ECOSENTINEL_WATER_DATASET_MATCH_THRESHOLD`, `ECOSENTINEL_WATER_DATASET_TOP_K`, `ECOSENTINEL_WATER_DATASET_FLAG_LEVELS` — reference-dataset appearance matching (see below)
- `ECOSENTINEL_AUTHORITY_WEBHOOK_URL`, `ECOSENTINEL_AUTHORITY_WEBHOOK_TOKEN`, `ECOSENTINEL_AUTHORITY_NAME`, `ECOSENTINEL_REPORTS_PATH` — where citizen contamination reports are stored and, optionally, forwarded
- `ECOSENTINEL_OVERPASS_ENABLED`, `ECOSENTINEL_OVERPASS_BASE_URL`, `ECOSENTINEL_OVERPASS_RADIUS_M`, `ECOSENTINEL_OVERPASS_TIMEOUT_SECONDS` — nearby water body lookup **and** geographic context via Overpass (no API key); one shared budget for both
- `ECOSENTINEL_OVERPASS_CONTEXT_TIMEOUT` (default `10`) — hard ceiling on the LangGraph `context_enrichment` node. Keep it comfortably below the frontend's 30-second analysis timeout; set `ECOSENTINEL_OVERPASS_ENABLED=false` to skip the lookup entirely and shave it off every run

`backend/.env` is git-ignored; copy `backend/.env.example` and fill in only the values you need. No API key, `LLM_PROVIDER`, database, or external account is required to run the full pipeline in demo mode.

## Waste Detection and Segregation

A separate path from the risk pipeline, reached through `POST /api/waste/segregate`. Two stages,
two models, two different questions:

```text
image → YOLO detection → crop each box → waste classifier → segregation category
        (where is it)                     (what is it)      (biodegradable?)
```

They are kept apart deliberately. Merging them would mean either a classifier inventing boxes or a
detector asserting categories it was never trained on. The Waste **Agent** in the risk pipeline is
untouched by all of this and still runs mock analysis — these models are not wired into scoring.

Full method, dataset findings and every measurement: [`training/README.md`](training/README.md).

### What is trained, and what is actually served

| Stage | Trained | Served |
| --- | --- | --- |
| Classification (8 classes) | `runs/classification/best.pt` — macro-F1 **0.911**, accuracy 0.934 on 1,200 held-out images | **Yes** |
| Detection (bounding boxes) | `backend/models/waste_detector.pt` — TACO, 40 epochs, mAP50 **0.346** | **No** — COCO `yolov8n.pt` is still configured |

Classes: `ewaste`, `food_waste`, `leaf_waste`, `metal_cans`, `paper_waste`, `plastic_bags`,
`plastic_bottles`, `wood_waste`. The taxonomy follows the data that exists, not a tidy list — it
has `ewaste`, which the Kaggle segregation class list does not, and no generic `waste` class.

The segregation mapping and both confidence thresholds live in
`training/config/waste_categories.json` — data, not code, because what counts as recyclable varies
by municipality and a hard-coded mapping quietly exports one region's rules everywhere.

### An offline metric only describes the pipeline it was measured through

The classifier scored macro-F1 0.911 validating on `Resize(258)` + `CenterCrop(224)`. On the roughly
square dataset photos that keeps nearly everything. Serving feeds it **detector crops**, which are
not square — a bottle crop is typically 2.6x taller than wide, so `CenterCrop` kept about a fifth of
the object, usually just the label, and discarded the shape that identifies a bottle.

Measured on 145 real bottle crops, changing nothing but the transform:

| Transform | Classified `plastic_bottles` |
| --- | --- |
| `Resize` + `CenterCrop` (what was served) | 36% |
| `Resize` to square, ignoring aspect ratio | 56% |
| Letterbox — preserve aspect, pad the short side | **87%** |

0.911 was a true number about a transform nobody served, and no metric in the project moved while
it was wrong. `training/waste_preprocess.py` is now the single definition of image → tensor,
imported by training, evaluation **and** the backend classifier; every checkpoint records its
`preprocess` version and `/api/waste/pipeline-status` reports a mismatch rather than letting it
surface as unexplained misclassification.

**Retraining to match made the model worse**, twice, on 392 held-out detector crops: 79.3% top-1
served versus 72.2% and 72.7% retrained, almost all of the gap in `ewaste`. The served combination
is therefore deliberately *not* a matched one, `status()` says so rather than implying it was
verified, and the rejected runs are kept in `runs/classification_letterbox{,_v2}/` because they are
the evidence for not deploying them.

### The TACO detector was trained, measured, and not deployed

TACO's COCO annotations were converted to YOLO (988 images, 1,814 boxes, 2,970 unmapped annotations
excluded and counted rather than merged into the nearest class) and a detector trained from
`yolov8n.pt`. It was then A/B tested against the served COCO model **through the production call
path** — `analyze_waste(detector=...)` as the only variable, with dedup, cropping, preprocessing and
both gates identical.

On 107 held-out objects:

| Model | Localisation | End-to-end correct |
| --- | --- | --- |
| COCO `yolov8n` (**served**) | 9.3% | 2.8% |
| TACO `waste_detector` | **53.3%** | 7.5% |

Localisation improves 5.7x; end-to-end correctness only 2.7x, because the classifier then refuses
41 of the 57 crops the detector correctly localises. The bottleneck moves from detection to
classification rather than disappearing. `NEVER_WASTE_CLASSES` also matches on the detector's class
name, so it goes **inert** under a detector that emits only waste labels — a real change in safety
behaviour, not a neutral one. Neither model was deployed and neither was retrained; the full report,
including per-class results, the false-positive probe and latency, is
[`runs/waste_detection/AB_TEST_REPORT.md`](runs/waste_detection/AB_TEST_REPORT.md).

The largest win available needs no new data: the two models disagree 42 times, the detector is right
22 of those and the classifier 6, and the pipeline currently resolves every one in the classifier's
favour.

**A production bug surfaced before the comparison was valid.** `_decode_image` returned RGB while
Ultralytics treats a bare ndarray as BGR, so every frame had its red and blue channels swapped. It
does not raise — it just detects less: the waste detector lost 46% of its detections (114 → 62), the
COCO model barely noticed (30 → 28), and the fault therefore looked like a weak new model rather
than a pipeline fault. Fixed in `water_vision_service.py`; the Water Agent shares that decoder and
was affected too.

### What the pipeline refuses to say

The classifier has eight waste classes and a softmax that must distribute 1.0 across them whatever
it is shown. On real TACO images it called a dog `wood_waste` at 84% and a car `food_waste` at 64% —
both above threshold, so raising the threshold cannot fix it. It was never given the option of
abstaining, so the refusals are structural:

| Situation | Result |
| --- | --- |
| Classification ≥ threshold (default 0.60) | `confirmed`, segregation asserted |
| Classification < threshold | `needs_review`, `segregation: uncertain`, top class exposed as `candidate` only |
| Crop smaller than 24px | `uncertain` — too few pixels to do anything but guess |
| Detector class cannot be waste (`person`, `car`, `dog`) | `uncertain`; the guess is kept as `candidate` only |
| No trained classifier | `unavailable` — a **missing model**, not "nothing found" |

That last row matters: "no classifier" and "no waste" produce identical object counts and mean
opposite things, so they are never collapsed.

`summary` reports more than a count for the same reason. YOLO runs NMS per class, so one bottle
survives twice — as `bottle` 0.66 and `vase` 0.39 over nearly identical pixels — and would be
reported as two objects. Merging is class-agnostic at 0.7 IoU, `duplicate_boxes_merged` says how
many boxes were folded in, absorbed class names travel with the survivor as `also_detected_as`, and
`uncertain` is counted separately rather than folded into either category.

### Reproduce

```bash
python training/validate_dataset.py --dataset garbage_Dataset --out runs/dataset_report.json
python training/train_waste_classifier.py --epochs 10 --batch-size 48 --workers 4
python training/evaluate_classifier.py --weights runs/classification/best.pt

# the two-stage pipeline from the command line
python inference_waste.py --status
python inference_waste.py --source path/to/image.jpg
python inference_waste.py --source path/to/video.mp4 --stride 15
python inference_waste.py --source 0                    # webcam
```

Seeds are fixed (`--seed`, default 1337) and every run writes a `training_manifest.json` with the
arguments, class list, device, library versions, dataset statistics and full epoch history.

Two dataset problems the validator found are handled rather than papered over: **111 duplicate image
groups across train and val** (excluded from training, validation left exactly as shipped so the
held-out set is not quietly reshaped) and **56:1 class imbalance** (`food_waste` 10,066 vs `ewaste`
180 — weighted sampler, and the best checkpoint selected on macro F1, because on this distribution
accuracy rewards ignoring the rare classes). Nothing is deleted; 7 unusable images are skipped and
recorded.

To train a real waste **detector** you need boxes. `garbage_Dataset` has none — it is an
image-classification dataset and nothing else — which is why the detection stage came from TACO
instead.

## Reference-Dataset Matching and Contamination Reports

A water photo — uploaded, or sampled from the live camera preview every two seconds — is compared
against the labelled reference frames in `datasets/<ClassName>/*.jpg` (`Alta` / `Media` / `Baja`,
mapped to HIGH / MODERATE / LOW). Two tiers, reported separately:

| Tier | Method | What a hit means |
| --- | --- | --- |
| Similarity | 2×2 spatial HSV colour histogram, compared by histogram intersection; the 5 nearest frames vote | The photo **resembles** frames labelled with that class |
| Near-duplicate | 64-bit difference hash, accepted only when that same frame is also a strong colour match | The photo is essentially a frame the dataset already contains — a replayed sample |

Build the index ahead of time with `python backend/scripts/build_dataset_index.py` (≈12 s for 6,515
frames, 0.3 MB on disk); otherwise the API builds it lazily in a background thread on first use and
reports `status: "indexing"` with progress until it is ready.

### How reliable is it — measured, not assumed

Reproduce with `python backend/scripts/calibrate_dataset_match.py --samples 900 --bands`. Every query
excludes **all frames from its own video clip**, which is the honest stand-in for "water this matcher
has never seen":

| Metric | Result |
| --- | --- |
| Exact class accuracy | ~71% |
| Contaminated-or-not accuracy | ~84% |
| Recall on `Alta` (visibly contaminated) | ~91% |
| Recall on `Baja` (clean) | **~15–33%** |
| Non-water images (app screenshots) | best similarity ≤ 0.27, well under the 0.62 threshold |

That clean-water number is the important one: **50–100% of genuinely clean frames are matched to a
contaminated class, and this does not improve at higher similarity.** The cause is the dataset, not
the threshold — only 4 of the 29 source clips are clean water, and a colour histogram keys on scene
appearance far more than on turbidity. Fixing it properly needs more clean-water clips, or a model
trained on turbidity rather than appearance.

Three consequences are encoded deliberately:

1. The flag says "**resembles** reference frames labelled contaminated", never "this water is
   contaminated", and carries its reliability caveat everywhere it is shown.
2. The match **never moves the risk score**. Risk stays sensor-backed
   (`backend/tests/test_water_dataset_match.py::test_dataset_match_never_moves_the_risk_score`).
3. Nothing is reported automatically. A flag offers to read the device location — which is requested
   only on a button press, and leaves the device only on an explicit per-report confirmation showing
   exactly what will be sent. The caveat is embedded in the report body so a recipient cannot mistake
   it for a lab result.

## Location Detection

An analysis needs a point. There are three ways to supply one, and the dashboard never blurs which was used.

| Source | How | `SelectedLocation.source` |
| --- | --- | --- |
| Browser geolocation | One-shot `navigator.geolocation.getCurrentPosition`, reverse-geocoded by the backend | `browser` |
| Manual search | Debounced free-text query → `POST /api/location/search` → Nominatim | `manual` |
| Preset monitoring area | The bundled areas in `shared/locations.json` | `preset` |

**One-shot, not `watchPosition`.** An environmental analysis is a snapshot of a point, not a journey. `useBrowserLocation` calls `getCurrentPosition` exactly once; continuous tracking would hold a GPS fix open, cost battery, and invite a stream of re-analyses nobody asked for. (`useLiveLocation` *does* watch — a contamination report is taken while the reporter walks around a water body. Different job, different hook.)

**The permission dialog opens at most once on our initiative.** The automatic attempt fires only when no location is set, and a denial is remembered for the session so it never re-prompts. An explicit "Use My Location" click always retries, because the user may have changed the browser permission in the meantime. A single hook instance lives in `AnalysisContext`, so however many controls offer the button, there is one prompt.

**The first analysis waits for the location.** The geolocation attempt resolves before the dashboard's initial run, so the first result describes the place the user is actually at. Getting this wrong is subtle and was caught only by running the app: the dashboard auto-ran against the default preset, then received the fix, leaving a result for one place while the location bar displayed another.

**Every failure names the fallback**, rather than just reporting a problem:

| Failure | What the user sees |
| --- | --- |
| Permission denied | *Location permission was denied. Search for a location manually.* |
| Position unavailable | *Unable to determine your current location. Search manually instead.* |
| Timeout | *Locating timed out. Search for a location manually.* |
| Browser unsupported / insecure context | *This browser cannot read your location here. Search for a location manually.* |
| Nominatim unreachable during search | *Location search is temporarily unavailable. Please try again.* |
| Reverse geocode fails after a good fix | The fix is kept and labelled with its coordinates — a missing name never discards a valid location. |

Geolocation requires a secure context: `https`, or `localhost` in development.

### Provenance: what the dashboard claims about its own numbers

The `DataProvenance` panel lists a source **only when it actually supplied data for the run on screen**, and states what kind of data it is. "OpenAQ", "a historical dataset" and "demo fixtures" are three different claims, and rendering them identically would be lying by omission.

| Status | Meaning |
| --- | --- |
| Current observation | A live provider reading, recent enough that the *provider* calls it current |
| Latest available observation (n h old) | A real reading, past the freshness window — labelled with its age |
| Historical / ML assessment | Dataset-derived, **not** a reading from this place right now |
| Demo data | Fixtures, labelled as such |
| Context only | Geography (Nominatim, Overpass) — never a measurement |

Freshness is the provider's own verdict (`AirQualityReading.freshness`), never inferred by the UI. The water potability dataset is always shown as *Historical / ML assessment*: it has no coordinates for the analysed location and is never presented as a live sensor reading.

## OpenStreetMap Integrations (Nominatim + Overpass)

Two OSM services, both keyless, both **geographic context only** — neither carries a single
water-quality measurement, and nothing from either can move a risk score.

| Service | Endpoint | Answers |
| --- | --- | --- |
| Nominatim reverse | `POST /api/location/reverse` | "What is the address at these coordinates?" |
| Nominatim search | `POST /api/location/search` | "Where is *Bellandur Lake*?" → coordinates, with `isWater` set for water features |
| Overpass | `POST /api/water/nearby-bodies` | "Which water bodies are near this point, and how far?" |
| Overpass | `POST /api/location/context` | "What industrial land, waste facilities, waterways and major roads are *mapped* near this point?" |

### Why Overpass, when reverse geocoding already returns a `waterFeature`

Reverse geocoding only mentions water when the queried point happens to *sit on* it. A photo taken
from a bank is a few metres inland, so it usually comes back with a road name. Overpass answers the
question a contamination report actually needs, and the result is folded into the report:

```
Coordinates   : 12.93450, 77.67450
Nearest mapped water body : Bellandur Lake (Lake, ~1423 m away, OSM relation/19751547)
```

**One detail worth keeping.** Urban water is mapped as a dense mesh of unnamed drain and stream
segments, so the named lake sits far down the distance ordering — around Bellandur it is the **39th**
result. `nearestNamed` is therefore chosen from the *full* result set, never from the list after the
caller's `limit` truncates it; otherwise a point a few hundred metres from a famous lake silently
reports "no named water body". Covered by
`test_nearest_named_is_chosen_before_the_limit_truncates`.

### Mapped features are context, never a cause

The geographic context feature exists to answer "what is around here?", not "is this place polluted?".
OpenStreetMap reports what contributors have **mapped**: presence tells you nothing about whether a
site is operating, compliant, or emitting anything, and absence tells you nothing either, because OSM
coverage is uneven. So this data supports wording like:

> Industrial activity is mapped near the analysis location.

and, alongside an actual reading from a measuring provider:

> Elevated particulate observations alongside nearby mapped industrial features warrant further investigation.

It must never be used to say *this factory is causing the pollution*. Structurally, it cannot: the
enrichment result never enters `CoordinatorInput`, so no mapped feature can move a score. Two tests
pin that down — `test_context_enrichment_never_reaches_the_coordinator` asserts the Coordinator's
input carries only `location`, `air`, `water`, `waste`; `test_enrichment_failure_does_not_change_the_risk_score`
asserts scores are identical with Overpass working and with Overpass down.

### Being a good citizen of donated infrastructure

Neither service needs an API key, and both are donated. Both clients therefore:

- send an identifying `User-Agent` (`ECOSENTINEL_NOMINATIM_USER_AGENT`)
- serialise requests and enforce a minimum one-second interval
- cache by position (Nominatim 100 m, Overpass 250 m) and by normalised query string
- cap the Overpass radius, result count, and send an explicit server-side `[timeout:]`
- degrade to `status: "unavailable"` with a reason on rate-limit or outage, never an exception

Both Overpass services share **one** `OverpassThrottle` instance, handed to them by their factories.
Overpass rate-limits the client, not the code path, so two services each keeping a private
one-per-second budget would spend two slots per second between them. Sharing keeps the process to a
single outstanding request (`test_both_overpass_services_share_one_request_budget`).

Each context category is truncated **independently**, so a dense mesh of mapped drains cannot crowd
out the one mapped landfill — the feature an analyst actually wants to see.

> **Expect rate limiting.** Overpass is free, shared and unauthenticated. Under load it *stalls*
> before it rejects, which is exactly why the enrichment node is bounded. For sustained use, point
> `ECOSENTINEL_OVERPASS_BASE_URL` at your own instance.

The test suite never contacts either service — `tests/conftest.py` points both at unroutable
addresses and the clients are stubbed.

## Demo Mode

Demo data stays labelled through the decision engine too: `decision.dataStatus` reports `demo`
(or `mixed` when only some providers are live), and the dashboard's decision panel shows a **Demo
data** chip. A simulated reading is never presented as a measurement of a real place.

With no API keys configured, every provider falls back to realistic deterministic mock data, so the full dashboard — agent runs, risk scoring, coordinator recommendations, waste image analysis — works out of the box with no external accounts or hardware. This includes the LangGraph orchestrator: `ECOSENTINEL_DEMO_MODE=true` (or `demoMode: true` in the request body) needs no OpenAQ key, Firebase project, MQTT broker, YOLO weights, or `LLM_PROVIDER` — the graph produces the same deterministic scores every run.
