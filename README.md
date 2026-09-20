# EcoSentinel — C3 Safety Intelligence

[![Backend Tests](https://img.shields.io/badge/Backend%20Tests-780%20passed-brightgreen.svg)](#quick-start)
[![Frontend Tests](https://img.shields.io/badge/Frontend%20Tests-184%20passed-brightgreen.svg)](#quick-start)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x%20clean-blue.svg)](#quick-start)
[![Framework](https://img.shields.io/badge/Orchestrator-LangGraph-orange.svg)](#the-agent-workflow)
[![Maps](https://img.shields.io/badge/Maps-OpenStreetMap%20%7C%20Leaflet-green.svg)](#worker-routing--dijkstra-and-conditional-safety)

An incident-precursor detection system for workplace safety. Workers report hazards from their
phones with a photo and a confirmed GPS fix; a LangGraph agent workflow extracts the facts,
classifies the risk, finds geographic clusters, routes emergencies to the relevant authority and
explains every conclusion from stored evidence. A human safety officer decides what, if anything,
workers are told.

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
cd backend && python -m pytest -q          # 780 tests passed
cd frontend && npm run test                # 184 tests passed
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

Routing supports journeys up to **20 km** apart. Overpass is slow and unevenly loaded, and its
cost scales with the area, so the fetch budget scales with the distance asked for — from 30 s for
a city block to 75 s for a cross-city walk — and falls through a list of mirrors before giving up.

Measured against the live API:

| Separation | Graph | Route | Fetch |
| --- | --- | --- | --- |
| 1.4 km | 2,672 nodes | 2.0 km | ~4 s |
| 18.5 km | 63,749 nodes | 23.5 km | ~22 s |

A single fixed budget could not serve both ends of that range, and overrunning it is not a loud
failure — it silently produces the direct-line estimate described below.

### When map data cannot be loaded

If every mirror fails the backend returns a **direct-line estimate** rather than nothing — and
labels it as one. The response carries `geometrySource: "estimated"`, the algorithm string says
the points were generated locally, and the UI replaces the node count with *"N generated points —
not map data"* plus a warning that the line does not follow roads.

> This matters because it went wrong once. An earlier change cut the Overpass timeout to 12 s,
> below what a real query costs, so every request fell through to the estimate — and the estimate
> was rendered as *"Dijkstra over 95 OpenStreetMap nodes"*. A straight line across a street grid
> was presented as a mapped route. Route length gives it away: a real route here measures **1.48x**
> its straight-line distance, a fabricated one **1.00x**. Tests now pin the timeout, the mirror
> list, and the rule that generated geometry is never described as OpenStreetMap.

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
safety_user ──┬── worker_location       (explicit events only, never a trail)
              ├── worker_route_event    (one per explicit route request; stores both geometries)
              ├── safety_report ────────┬── report_analysis (extracted facts & cited evidence)
              │                         └── pattern_analysis (recurring hazard detection)
              │                                  │
              │                                  └── safety_hotspot ── safety_announcement
              │                                             ├── admin_action           (what a human did)
              │                                             └── recommendation_feedback (advice utility)
              │
              ├── safety_notification   (messages, hazard alerts & peer comms)
              └── notification_read     (per-worker read receipts for broadcasts)
```

SQLite via the standard library, no ORM. Migrations are additive `ALTER TABLE` statements, so an
existing database is upgraded in place and never rebuilt.

## API

**Worker** — `POST /api/worker/reports` · `POST /api/worker/reports/{id}/photo` ·
`GET /api/worker/me` · `GET /api/worker/reports` · `GET /api/worker/reports/{id}` ·
`GET /api/worker/location-history` · `POST /api/worker/locations` ·
`GET /api/worker/routes` · `GET /api/worker/routes/{id}` · `GET /api/worker/cautions` ·
`POST /api/worker/verify-location` · `GET /api/worker/alerts` · `GET /api/worker/map` ·
`POST /api/worker/route` · `GET /api/worker/notifications` ·
`POST /api/worker/notifications/{id}/read` · `POST /api/worker/notifications/read-all` ·
`GET /api/worker/directory` · `POST /api/worker/notifications/send`

**Admin** — `GET /api/admin/dashboard` · `/map` · `/reports` · `/reports/{id}` ·
`/reports/{id}/photo` · `/hotspots` · `/hotspots/{id}` · `POST /hotspots/{id}/{action}` ·
`POST /hotspots/flag` · `/announcements` · `/actions` · `/feedback` · `/workers` ·
`/workers/{employee_id}/reports` · `/workers/{employee_id}/routes` · `/routes` ·
`/routes/{id}` · `/alerts/{id}/affected-workers` · `/alerts/{id}/rerouted-workers` ·
`/notifications` · `POST /notifications/{id}/read` · `POST /notifications/read-all` ·
`POST /notifications/send` · `POST /seed-demo-data`

**Assistant** — `POST /api/safety/chat`

**Analysis** — `POST /api/reports/analyze` · `/batch-analyze` · `GET /api/analytics/overview` ·
`/analytics/patterns` · `GET /api/agents/workflow` · `/agents/status` · `GET /api/health`

Full schemas at <http://127.0.0.1:8000/docs>.

## Screens

| Route | Description |
| --- | --- |
| `/` | Interactive landing story (photographed 50-frame day-night sequence) → choose Worker / Safety Admin |
| `/safety` | C3 Safety Command: active hazard overview, high-level metrics, and quick triage actions |
| `/notifications` | Notification & Communication Centre: alerts, safety messages, peer messaging, broadcast management |
| `/worker/report` | Describe the hazard, take a live photo, confirm a location |
| `/worker/my-reports` | The worker's own history, each report on the map |
| `/worker/map` | Published alerts, destination search, routing with safe detour intelligence |
| `/worker/alerts` | Published alerts as a list |
| `/worker/my-routes` | The worker's own recorded routes and why any changed |
| `/admin/dashboard` | Counts, domain breakdown, review queue |
| `/admin/map` | Reports, candidates, investigations, published alerts on OpenStreetMap |
| `/admin/hotspots` | Review queue: evidence, history, authority, actions, publish |
| `/admin/reports` | Every report with its photo and provenance |
| `/admin/announcements` | What workers can currently see |
| `/admin/worker-routes` | Route Intelligence: recorded decisions, original vs selected route |
| `/analyze` | Live Incident Simulator: interactive LangGraph workflow trace and evidence extraction |
| `/patterns` | Pattern & Hotspot Intelligence: recurring hazard families, department breakdown, spatial clustering |

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
- A photograph does **not** prove chemical toxicity or structural failure, and the system never says it does.
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

## Notifications and Colleague Messaging

Worker ↔ Admin and Worker ↔ Colleague, unified in the `safety_notification` and `notification_read` tables.

- **Automated Incident Triage**: Filing a report immediately raises an admin notification carrying
  the report id, risk level, extracted hazards, coordinates, GPS accuracy, and location source. This
  is clickable through to the incident details. A failure to notify never aborts or rolls back the report.
- **Admin Broadcasts & Targeting**: Safety admins can broadcast announcements to all workers or target
  specific employee IDs. A worker's payload is a strict privacy subset: no sender identity, no report ID,
  no raw GPS accuracy, and no internal extracted risk factors.
- **Worker-to-Safety Messaging**: Workers can compose direct inquiries or hazard warnings to the
  safety team (`POST /api/worker/notifications/send`).
- **Worker-to-Worker (Peer) Messaging**: Workers can also notify named colleagues about emergent hazards
  in their work area. A safe directory endpoint (`GET /api/worker/directory`) lists addressable colleagues
  showing only `employee_id`, `name`, and `department` — never locations, report histories, or status.
- **Deliberate Narrow Attribution**: Messages sent explicitly by a person reveal their sender handle so
  they can be evaluated, answered, or reported for misuse. Conversely, the automated `REPORT_SUBMITTED`
  notification is strictly unattributed and delivered only to the safety team, preserving reporting privacy.
- **Per-Reader Read Receipts**: Read states for broadcast messages live in `notification_read` per employee,
  ensuring one worker reading an alert does not clear it for other recipients.

> **A notification is a message, not a hazard.** Only a published safety alert affects routing.
> The send panel says so, and a test asserts an announcement leaves a route byte-identical.

## System Resilience & Error Boundary

Workplace safety systems must fail visibly, gracefully, and informatively:

- **Top-Level ErrorBoundary**: The React application root is wrapped with an outer `<ErrorBoundary>`
  outside all context providers. If an unhandled exception or stale module resolution crash occurs during
  initialization, the application displays an informative error card rather than an unhelpful blank screen.
- **Actionable Diagnostics**: The error screen displays the error message, an expandable component stack
  trace, and targeted remediation advice (such as stale dev-server module cache detection).
- **Graceful Network & Sensor Degradation**: When geolocation permissions are denied, OpenStreetMap Overpass
  is slow/rate-limited, or optional LLM keys are absent, the system degrades to deterministic local fallbacks
  without blocking worker workflows.

## Repository Structure

```text
.
├── backend/                              # FastAPI backend service
│   ├── main.py                           # App entry point; mounts safety, worker, admin & chat routers
│   ├── config.py                         # Environment configuration & settings
│   ├── schemas.py                        # Pydantic data schemas
│   ├── safety/                           # C3 Safety Intelligence Core
│   │   ├── rules.py                      # Deterministic hazard/control regexes, weights & thresholds
│   │   ├── agents.py                     # Parser, Risk Analysis, Pattern Detection & Advisor agents
│   │   ├── graph.py                      # LangGraph StateGraph workflow with emergency conditional routing
│   │   ├── domains.py                    # Incident domain classification & serious-incident markers
│   │   ├── geo.py                        # Haversine distance, hazard families, single-link clustering
│   │   ├── history.py                    # 1 km historical evidence aggregation & audit trails
│   │   ├── authority.py                  # Real-time OpenStreetMap Overpass emergency authority lookup
│   │   ├── routing.py                    # RoadGraph, Dijkstra, Yen k-shortest safe detour routing
│   │   ├── people.py                     # Synthetic workers/admins & idempotent seed generator
│   │   ├── store.py                      # 12-table SQLite schema, additive migrations & persistence
│   │   ├── api.py                        # Analysis, analytics, and workflow inspection routes
│   │   ├── roles_api.py                  # Worker & Admin APIs with strict SQL privacy boundaries
│   │   ├── chat_tools.py                 # Grounded, read-only tools for safety assistant (no SQL injection)
│   │   └── llm.py                        # Optional Groq narrative synthesizer (zero-hallucination guard)
│   └── tests/                            # Pytest test suite (780 tests across 37 test files)
│       ├── test_safety_agents.py         # Parsing, risk calculation & evidence citation
│       ├── test_safety_geo.py            # 1 km clustering, hotspot review & privacy boundaries
│       ├── test_safety_intelligence.py   # Domain routing, OSM authority lookup & actions
│       ├── test_routing.py               # Dijkstra, Yen k-shortest & conditional detour avoidance
│       ├── test_route_history_and_chat.py# Worker route tracking & grounded tool assistant
│       ├── test_notifications.py         # Worker/admin notifications, messaging & read receipts
│       └── test_worker_persistence.py    # Identity boundaries, location events & reporting
└── frontend/                             # React 19 + TypeScript + Vite application
    ├── src/
    │   ├── pages/                        # Worker, Admin, Notification & Safety views
    │   │   ├── WorkerPages.tsx           # Incident reporting, hazard alerts & live map routing
    │   │   ├── MyReportsPage.tsx         # Worker personal report history & geotag inspection
    │   │   ├── MyRoutesPage.tsx          # Worker recorded routes, hazard detours & trip logs
    │   │   ├── AdminPages.tsx            # Safety command dashboard, report audit & review queue
    │   │   ├── AdminMapPage.tsx          # Incident map with candidate clusters & published zones
    │   │   ├── WorkerRoutesPage.tsx      # Route Intelligence: original vs safe detour inspection
    │   │   ├── NotificationsPage.tsx     # Bidirectional alerts, peer messaging & directory
    │   │   ├── SafetyDashboardPage.tsx   # C3 Safety Command: hazard triage & status
    │   │   ├── AnalyzeReportPage.tsx     # Interactive LangGraph workflow simulator & trace
    │   │   └── PatternIntelligencePage.tsx# Recurring hazard families & spatial cluster analysis
    │   ├── components/
    │   │   ├── layout/                   # AppLayout, Sidebar, TopBar, ErrorBoundary
    │   │   ├── safety/                   # SafetyMap (Leaflet/OSM), LocationPicker, SafetyChat,
    │   │   │                             # LivePhotoCapture, RoutePanel, IncidentIntelligence
    │   │   └── dashboard/                # LocationBar, LocationSelector, MetricCard
    │   ├── hooks/                        # useBrowserLocation, usePlaceSearch, useLiveLocation
    │   ├── services/                     # Typed API client & session managers
    │   └── context/                      # Role, Navigation, Settings, Toast & Analysis contexts
    ├── vitest.config.ts                  # Vitest + jsdom test configuration (184 passing tests)
    └── vite.config.ts
```

## Local Development & Setup

### 1. Prerequisites
- Python 3.9+ (with virtual environment support)
- Node.js 18+ and `npm`

### 2. Backend Setup
```bash
# create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# install backend dependencies
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt

# configure environment variables
cp backend/.env.example backend/.env

# start backend server
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive OpenAPI / Swagger documentation is accessible at `http://127.0.0.1:8000/docs`.

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5174` in your browser. The Vite dev server proxies `/api` calls directly to the backend on port 8000.

### 4. Running the Complete Test Suites
Both suites run completely offline without external network access or API credentials:

```bash
# backend test suite (780 passed tests across 37 test files)
cd backend && pytest -q

# frontend test suite (184 passed tests across 18 test files)
cd frontend && npm run test

# TypeScript type check
cd frontend && npm run typecheck
```
