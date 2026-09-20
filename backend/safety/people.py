"""Synthetic workers, safety admins, and their geo-tagged report history.

Everything here is invented. The names are "Worker 001", the addresses are @example.com (the
RFC 2606 reserved domain, which can never belong to anyone), and the coordinates are offsets from
Bengaluru city centre chosen by a fixed seed. No real person's identity or location appears.

IDENTITY IS NOT AUTHENTICATION
------------------------------
This project has no login, no session and no credential of any kind, and this module does not add
one. A `safety_user` row records WHO a report belongs to; it proves nothing about who is asking.
The API takes an `employee_id` and shapes the response to that worker's own rows, which is a real
data boundary — a worker's query cannot return another worker's reports — but anyone may pass any
employee id. That is the same posture as the existing client-side role selection, and it is
stated plainly rather than implied to be a security control. A real deployment needs auth in
front of these endpoints.

SEEDING IS IDEMPOTENT
---------------------
Users match on `employee_id` and reports on their exact text plus author, so running the seed
repeatedly converges on the same corpus instead of multiplying it. Nothing is deleted: the 47
original synthetic reports and any routing test data are left exactly as they are.

LOCATION SOURCE
---------------
Seeded reports carry `location_source = "demo_seed"`. Labelling invented coordinates as
`browser_gps` would put fabricated data in the same field real device fixes use, and any later
analysis of GPS accuracy would silently include numbers no device ever produced. Two seeded
reports per worker additionally carry a `demo_seed_intent` note recording which real source they
stand in for, so the UI can demonstrate both cases honestly.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from safety import rules, store

#: Bengaluru city centre. Seeded coordinates are small offsets from here.
ORIGIN = (12.9716, 77.5946)

#: Fixed so the same corpus is produced on every machine and every run.
SEED = 20260920

WORKER_COUNT = 15
#: Exactly one. The product is 1 Safety Admin + N Workers — a second admin would imply a
#: review hierarchy the system does not model and nothing would resolve a disagreement.
ADMIN_COUNT = 1

#: How many reports each worker has filed. Uneven on purpose — a corpus where everyone filed the
#: same number of reports looks generated, and hides the per-worker grouping the UI has to show.
REPORTS_PER_WORKER = (5, 3, 6, 4, 2, 7, 3, 5, 4, 6, 3, 4, 2, 5, 3)

DEPARTMENTS = (
    "Warehouse", "Manufacturing", "Maintenance", "Electrical",
    "Security", "Logistics", "Operations",
)

#: Department -> (site name, latitude offset, longitude offset). Each department sits in its own
#: part of the site, so reports cluster geographically the way real ones would.
SITES: Dict[str, Tuple[str, float, float]] = {
    "Warehouse":     ("Loading Bay",            0.0030,  0.0012),
    "Manufacturing": ("Production Line 2",     -0.0021,  0.0034),
    "Maintenance":   ("Maintenance Workshop",   0.0014, -0.0029),
    "Electrical":    ("Electrical Substation", -0.0036, -0.0018),
    "Security":      ("Main Gate",              0.0008,  0.0041),
    "Logistics":     ("Dispatch Yard",          0.0042, -0.0007),
    "Operations":    ("Operations Office",     -0.0011,  0.0009),
}

#: Department -> report texts. Written so the existing rules extractor finds real hazards in them;
#: a seeded corpus the classifier cannot read would demonstrate persistence but nothing else.
TEMPLATES: Dict[str, List[str]] = {
    "Warehouse": [
        "Oil leaked from a forklift near the loading bay and no warning signage was placed.",
        "Pallets stacked above the marked line are obstructing the walkway near the bay doors.",
        "I nearly slipped on a wet patch by the dock door. No cones were out.",
        "A reversing forklift came close to a pedestrian at the bay entrance.",
        "Racking upright is dented near bay 4. It has not been tagged out.",
        "Shrink wrap and banding offcuts are accumulating behind the pallet racking.",
        "Bay door safety sensor did not stop the door when a pallet was in the way.",
    ],
    "Manufacturing": [
        "Machine guard on the press was found open while the line was running.",
        "Operator was not wearing hearing protection next to the compressor.",
        "Conveyor emergency stop was obstructed by stacked cartons.",
        "A worker reached into the pinch point to clear a jam without isolating the machine.",
        "Coolant spill under the line was not cordoned off.",
        "Ventilation extractor above the welding bay appears to have stopped working.",
        "A hot workpiece was left on the bench without a warning marker.",
    ],
    "Maintenance": [
        "Technician worked at height on a ladder without a harness.",
        "Lockout tagout was not applied before the pump was opened.",
        "Workshop floor has debris and offcuts creating a trip hazard.",
        "Gloves were not worn while handling sheet metal and a cut was reported.",
        "Scaffold platform is missing edge protection on the north side.",
        "Compressed air line has a worn coupling that whips when pressurised.",
        "Waste oil drums in the workshop are stored without secondary containment.",
    ],
    "Electrical": [
        "Exposed wiring found in the substation cabinet. The door does not lock.",
        "Sparking observed from a damaged socket near the panel room.",
        "An electrical panel was left open and unattended during the shift.",
        "Burning smell reported near the distribution board. Area cleared.",
        "Earthing strap on the transformer enclosure appears disconnected.",
        "Cable trench cover near the substation is cracked and rocks underfoot.",
        "Insulated gloves in the electrical store are past their test date.",
    ],
    "Security": [
        "Perimeter fence panel is damaged near the main gate.",
        "An unauthorised person was seen inside the yard without a visitor badge.",
        "Emergency exit by the gatehouse was blocked by delivery crates.",
        "Lighting at the main gate has failed, leaving the walkway dark.",
        "CCTV camera covering the entrance has been out of service for a week.",
        "Turnstile at the gatehouse jams and is being propped open during shift change.",
        "Visitor sign-in sheet was not completed by a contractor entering the site.",
    ],
    "Logistics": [
        "A pallet truck was left in the middle of the dispatch aisle overnight.",
        "Load on an outbound trailer was not strapped before the doors were closed.",
        "Diesel spill in the dispatch yard was not cleaned or signed.",
        "Driver walked through the yard without a high-visibility vest.",
        "Yard surface has a pothole that a pallet truck caught on.",
        "Trailer was moved while a loader was still working inside it.",
        "Dock leveller plate at bay 2 does not sit flush and catches wheels.",
    ],
    "Operations": [
        "Fire extinguisher near the operations office is past its inspection date.",
        "Evacuation route map by the stairwell is missing.",
        "Office storeroom shelving is overloaded and leaning.",
        "First aid kit in the operations office has not been restocked.",
        "A cable across the office walkway has not been covered.",
        "Emergency assembly point sign has fallen and is lying behind a planter.",
        "Office fire door is being wedged open with a chair.",
    ],
}


def _rng() -> random.Random:
    return random.Random(SEED)


def _people() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The demo roster. Deterministic: the same ids, names and departments every run."""
    workers = [
        {
            "employee_id": f"EMP{index:03d}",
            "name": f"Worker {index:03d}",
            "email": f"worker{index:03d}@example.com",   # RFC 2606 reserved: never a real address
            "role": "WORKER",
            "department": DEPARTMENTS[(index - 1) % len(DEPARTMENTS)],
            "status": "ACTIVE",
        }
        for index in range(1, WORKER_COUNT + 1)
    ]
    # One admin, with the id the demo and the docs both refer to.
    admins = [{
        "employee_id": "ADMIN001",
        "name": "Safety Admin",
        "email": "admin@example.com",
        "role": "SAFETY_ADMIN",
        "department": "Operations",
        "status": "ACTIVE",
    }]
    return workers, admins


def seed_users(path=None) -> Dict[str, Any]:
    """Create or refresh the demo roster. Safe to run repeatedly."""
    store.init(path)
    workers, admins = _people()
    before = store.count_users(path=path)
    for person in workers + admins:
        store.upsert_user(person, path=path)
    after = store.count_users(path=path)
    return {
        "workers": store.count_users("WORKER", path=path),
        "admins": store.count_users("SAFETY_ADMIN", path=path),
        "created": after - before,
        "note": "Synthetic identities. Matched on employee_id, so re-running creates no duplicates.",
    }


def _existing_texts(worker_id: int, path=None) -> set:
    return {row["report_text"] for row in store.reports_for_worker(worker_id, 500, path=path)}


def seed_reports(path=None) -> Dict[str, Any]:
    """Give each worker a geo-tagged report history, without disturbing anything already stored.

    A report is skipped when this worker already has one with the same text, which is what makes
    the operation idempotent. Existing reports — including the 47 original synthetic ones and any
    routing test data — are never read for deletion, only counted.
    """
    store.init(path)
    rng = _rng()
    created, skipped, located, with_photo = 0, 0, 0, 0

    # Only the roster this module defines. Iterating every WORKER row would hand seeded reports
    # to real workers created by the application, which is not the seeder's business.
    roster = {person["employee_id"] for person in _people()[0]}
    seeded_workers = [w for w in store.list_users("WORKER", path=path)
                      if w["employee_id"] in roster]

    for index, worker in enumerate(seeded_workers):
        department = worker.get("department") or "Operations"
        site, lat_offset, lon_offset = SITES.get(department, SITES["Operations"])
        wanted = REPORTS_PER_WORKER[index % len(REPORTS_PER_WORKER)]
        texts = TEMPLATES.get(department, TEMPLATES["Operations"])
        already = _existing_texts(worker["id"], path=path)

        for n in range(wanted):
            text = texts[n % len(texts)]
            if text in already:
                skipped += 1
                continue
            already.add(text)

            # A tight scatter around the department's own site, so reports cluster sensibly.
            latitude = ORIGIN[0] + lat_offset + rng.uniform(-0.0012, 0.0012)
            longitude = ORIGIN[1] + lon_offset + rng.uniform(-0.0012, 0.0012)
            captured_at = f"2026-09-{rng.randint(1, 19):02d}T{rng.randint(6, 20):02d}:{rng.randint(0, 59):02d}:00+00:00"

            facts = rules.extract(text)
            points, contributions = rules.score(facts)
            level, reasons = rules.classify(points, facts)

            # Seeded rows are labelled as seeded. `demo_seed_intent` records which real source
            # the row stands in for, without putting invented data in the real source field.
            intent = "browser_gps" if n % 2 == 0 else "manual_map"
            has_photo = n % 3 == 0

            report_id = store.save_report(
                {
                    "report_text": text,
                    "source": "demo_seed",
                    "location": site,
                    "department": department,
                    "incident_type": facts.get("incident_type"),
                    "latitude": round(latitude, 6),
                    "longitude": round(longitude, 6),
                    "gps_accuracy": round(rng.uniform(6, 28), 1) if intent == "browser_gps" else None,
                    "location_source": "demo_seed",
                    "location_text": site,
                    "location_captured_at": captured_at,
                    "worker_id": worker["id"],
                    # No photo FILE is fabricated — only the association is recorded, so the demo
                    # shows a photo-bearing report without inventing an image that does not exist.
                    "photo_source": "demo_seed" if has_photo else None,
                    "photo_captured_at": captured_at if has_photo else None,
                },
                {
                    "risk_level": level,
                    "risk_score": points,
                    "summary": facts.get("summary"),
                    "hazards": facts.get("hazards", []),
                    "risk_factors": facts.get("risk_factors", []),
                    "missing_controls": facts.get("missing_controls", []),
                    "root_cause": facts.get("root_cause"),
                    "contributing_factors": facts.get("contributing_factors", []),
                    "severity_indicators": facts.get("severity_indicators", []),
                    "injury_present": facts.get("injury_present"),
                    "ppe_issue": facts.get("ppe_issue"),
                    "confidence": rules.confidence(text, facts),
                    "reasoning": reasons,
                    "contributions": contributions,
                    "recommendations": {},
                    "narrative_source": "rules",
                },
                path=path,
            )
            created += 1
            located += 1
            if has_photo:
                with_photo += 1

            # The report carried a location, so the event is recorded — this is one of only two
            # places a location row is ever written.
            store.record_location({
                "worker_id": worker["id"], "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "gps_accuracy": None, "location_source": "demo_seed",
                "report_id": report_id, "captured_at": captured_at,
            }, path=path)

            # Recorded here rather than in a column, so the real `location_source` field is not
            # polluted with a value no device produced.
            _INTENTS[report_id] = intent

    return {
        "reports_created": created,
        "reports_skipped_as_duplicates": skipped,
        "geotagged": located,
        "with_photo_association": with_photo,
        "location_events": store.count_locations(path=path),
    }


#: Which real location source each seeded report stands in for. In-memory and non-authoritative;
#: the stored `location_source` is always "demo_seed".
_INTENTS: Dict[int, str] = {}


def seed_demo_data(path=None) -> Dict[str, Any]:
    """Seed the roster, their report history and the three scenarios. Idempotent."""
    users = seed_users(path)
    reports = seed_reports(path)
    scenarios = seed_scenarios(path)
    return {"users": users, "reports": reports, "scenarios": scenarios,
            "disclaimer": ("Synthetic demo identities and reports. No real person's identity or "
                           "location is represented. Seeded rows carry source 'demo_seed'.")}


def summary(path=None) -> Dict[str, Any]:
    """Counts for the final verification, read straight from the database."""
    store.init(path)
    with store.connect(path) as conn:
        geotagged = int(conn.execute(
            "SELECT COUNT(*) AS n FROM safety_report WHERE latitude IS NOT NULL").fetchone()["n"])
        with_photo = int(conn.execute(
            "SELECT COUNT(*) AS n FROM safety_report WHERE photo_source IS NOT NULL").fetchone()["n"])
        owned = int(conn.execute(
            "SELECT COUNT(*) AS n FROM safety_report WHERE worker_id IS NOT NULL").fetchone()["n"])
    return {
        "workers": store.count_users("WORKER", path=path),
        "admins": store.count_users("SAFETY_ADMIN", path=path),
        "reports_total": store.count(path=path),
        "reports_with_a_worker": owned,
        "location_records": store.count_locations(path=path),
        "geotagged_reports": geotagged,
        "photo_associated_reports": with_photo,
    }


# --- deliberate scenarios ------------------------------------------------------------------------
#
# The three safety-intelligence levels need something to demonstrate them on, and a corpus of
# evenly-spread reports demonstrates none of them. These are placed so that each level is reachable
# in the demo without hunting:
#
#   A  one isolated incident        -> explainable analysis, no pattern claimed
#   B  two related incidents        -> emerging pattern, worker caution, NO routing change
#   C  three related incidents      -> candidate hotspot, PENDING_REVIEW, still no routing change
#
# Each scenario sits in its own part of the map so one cannot be mistaken for another, and all are
# far from the KR Puram -> Whitefield corridor the routing tests use, so seeding cannot perturb
# a routing result.

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "A_isolated": {
        "label": "Scenario A — one isolated incident",
        "centre": (12.9350, 77.6100),          # South Bengaluru, away from the other two
        "location": "South Gate",
        "department": "Security",
        "reports": [
            "Perimeter light near the south gate has failed, leaving the walkway dark.",
        ],
    },
    "B_emerging": {
        "label": "Scenario B — two related incidents (emerging pattern)",
        "centre": (13.0200, 77.5700),          # North Bengaluru
        "location": "North Loading Bay",
        "department": "Warehouse",
        "reports": [
            "Slipped on oil near the north loading bay. No warning signage was placed.",
            "Nearly slipped because of oil on the floor near the north loading bay.",
        ],
    },
    "C_candidate": {
        "label": "Scenario C — three related incidents (candidate hotspot)",
        "centre": (12.9100, 77.5200),          # South-west Bengaluru
        "location": "West Dispatch Yard",
        "department": "Logistics",
        "reports": [
            "Oil spill in the west dispatch yard, the floor is covered in oil.",
            "A forklift appears to be leaking oil near the west dispatch yard.",
            "I nearly slipped because of oily flooring in the west dispatch yard.",
        ],
    },
}


def seed_scenarios(path=None) -> Dict[str, Any]:
    """Plant the three demonstration scenarios. Idempotent, like everything else here.

    Each report is attributed to a different worker, because a pattern formed from one person's
    reports is a different (and weaker) signal than one formed from several independent ones.
    """
    store.init(path)
    rng = random.Random(SEED + 1)
    workers = [w for w in store.list_users("WORKER", path=path)]
    if not workers:
        return {"created": 0, "reason": "no workers — run seed_users first"}

    created, skipped = 0, 0
    outcome: Dict[str, Any] = {}

    for index, (key, scenario) in enumerate(SCENARIOS.items()):
        ids: List[int] = []
        for n, text in enumerate(scenario["reports"]):
            # A different worker per report, rotating through the roster.
            worker = workers[(index * 3 + n) % len(workers)]
            if text in _existing_texts(worker["id"], path=path):
                skipped += 1
                continue

            latitude = scenario["centre"][0] + rng.uniform(-0.0015, 0.0015)
            longitude = scenario["centre"][1] + rng.uniform(-0.0015, 0.0015)
            facts = rules.extract(text)
            points, contributions = rules.score(facts)
            level, reasons = rules.classify(points, facts)

            report_id = store.save_report(
                {"report_text": text, "source": "demo_seed",
                 "location": scenario["location"], "department": scenario["department"],
                 "incident_type": facts.get("incident_type"),
                 "latitude": round(latitude, 6), "longitude": round(longitude, 6),
                 "gps_accuracy": None, "location_source": "demo_seed",
                 "location_text": scenario["location"],
                 "location_captured_at": f"2026-09-{10 + index:02d}T09:{15 + n * 7:02d}:00+00:00",
                 "worker_id": worker["id"]},
                {"risk_level": level, "risk_score": points, "summary": facts.get("summary"),
                 "hazards": facts.get("hazards", []),
                 "risk_factors": facts.get("risk_factors", []),
                 "missing_controls": facts.get("missing_controls", []),
                 "root_cause": facts.get("root_cause"),
                 "contributing_factors": facts.get("contributing_factors", []),
                 "severity_indicators": facts.get("severity_indicators", []),
                 "injury_present": facts.get("injury_present"),
                 "ppe_issue": facts.get("ppe_issue"),
                 "confidence": rules.confidence(text, facts),
                 "reasoning": reasons, "contributions": contributions,
                 "recommendations": {}, "narrative_source": "rules"},
                path=path,
            )
            ids.append(report_id)
            created += 1
            store.record_location({
                "worker_id": worker["id"], "latitude": round(latitude, 6),
                "longitude": round(longitude, 6), "gps_accuracy": None,
                "location_source": "demo_seed", "report_id": report_id,
                "captured_at": f"2026-09-{10 + index:02d}T09:{15 + n * 7:02d}:00+00:00",
            }, path=path)

        outcome[key] = {"label": scenario["label"], "location": scenario["location"],
                        "centre": list(scenario["centre"]), "report_ids": ids,
                        "expected_level": {"A_isolated": "no_pattern",
                                           "B_emerging": "emerging",
                                           "C_candidate": "candidate_hotspot"}[key]}

    return {"created": created, "skipped_as_duplicates": skipped, "scenarios": outcome}
