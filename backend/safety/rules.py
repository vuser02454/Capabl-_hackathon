"""Deterministic safety-report analysis: extraction, scoring and classification.

Everything a number depends on lives here, and none of it calls a language model. The LLM in this
system writes prose — summaries, reasoning, recommendations — and never decides a risk level or
counts anything. Two reasons:

RELIABILITY. A safety officer reading HIGH needs the same answer for the same report every time.
An LLM asked to classify will drift between runs and across providers, and the failure is silent.

AUDITABILITY. When this says HIGH it can name the signal and the phrase in the report that matched
it. "The model felt it was high" is not something anyone can act on or appeal.

IMPORTANT: these thresholds are APPLICATION-LEVEL DEMO RULES. They are not OSHA, ISO 45001, or any
regulatory classification, and nothing here should be presented as a compliance determination.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")

#: (canonical hazard, regex). Word-boundary anchored so "oil" does not fire on "boiler" and
#: "fall" does not fire on "fallen leaves". Ordered most-specific-first only for readability;
#: every pattern is evaluated, because one report routinely contains several hazards.
HAZARD_PATTERNS: List[Tuple[str, str]] = [
    ("Oil spill",             r"\boil\b(?!\s*(?:filter|change))|\bhydraulic fluid\b|\blubricant (?:leak|spill)\b"),
    ("Chemical exposure",     r"\bchemical\b|\bsolvent\b|\bcorrosive\b|\bacid\b|\bcaustic\b|\btoxic\b|\bfumes?\b|\bvapou?rs?\b"),
    ("Electrical hazard",     r"\belectric(?:al|ity)?\b|\bexposed wir(?:e|ing)\b|\bshock\b|\bshort circuit\b|\blive (?:wire|panel|conductor)\b|\bearth(?:ing)? fault\b"),
    ("Fire / ignition",       r"\bfire\b|\bsmoke\b|\bignition\b|\bflame\b|\bburn(?:ing|t)?\b|\bsparks?\b|\bexplosion\b"),
    ("Slip / trip / fall",    r"\bslip(?:ped|pery|ping)?\b|\btrip(?:ped|ping)?\b|\bfell\b|\bfall(?:en|ing)?\b|\bstumbl\w+"),
    ("Machine guarding",      r"\bguard(?:ing)? (?:missing|removed|open|defeat\w*)\b|\bunguarded\b|\binterlock\b|\bpinch point\b|\bentangle\w+"),
    ("Equipment failure",     r"\bmalfunction\w*|\bbreakdown\b|\bfailed\b|\bfailure\b|\bdefective\b|\bfaulty\b|\bseiz(?:ed|ure)\b"),
    ("Overheating",           r"\boverheat\w*|\bexcessive (?:heat|temperature)\b|\bsmell(?:ing|ed)? of burning\b"),
    ("Missing PPE",           r"\bppe\b|\bhard hat\b|\bhelmet\b|\bsafety glasses\b|\bgoggles\b|\bgloves?\b|\bhigh[- ]vis\w*|\bhearing protection\b|\brespirator\b|\bsafety (?:boots|shoes)\b"),
    ("Blocked egress",        r"\b(?:emergency )?exit\b|\bfire (?:door|escape)\b|\begress\b|\bevacuation route\b|\bwalkway blocked\b"),
    ("Working at height",     r"\bladder\b|\bscaffold\w*|\bheight\b|\bharness\b|\bfall arrest\b|\bmezzanine\b|\bedge protection\b"),
    ("Manual handling",       r"\blift(?:ing|ed)\b|\bmanual handling\b|\bcarry(?:ing)?\b|\bstrain(?:ed)?\b|\bback injury\b"),
    ("Vehicle / forklift",    r"\bforklift\b|\bpallet (?:truck|jack)\b|\bvehicle\b|\breversing\b|\btruck\b|\bloading dock\b"),
    ("Housekeeping",          r"\bhousekeep\w*|\bclutter\w*|\bdebris\b|\buntidy\b|\bobstruct\w*|\bstacked\b|\bspill\b"),
    ("Wet surface",           r"\bwet floor\b|\bwater on the floor\b|\bcondensation\b|\bpuddle\b|\bdamp\b"),
    ("Confined space",        r"\bconfined space\b|\btank entry\b|\bvessel entry\b|\bmanhole\b"),
    ("Noise exposure",        r"\bnoise\b|\bdecibel\b|\bloud\b"),
]

#: Controls whose ABSENCE is itself a risk factor. Detected as "<control> missing", not as a hazard.
CONTROL_PATTERNS: List[Tuple[str, str]] = [
    ("Warning signage",   r"\bsign(?:age|s)?\b|\bwarning (?:cone|sign|barrier)\b|\bcones?\b"),
    ("Barrier / barricade", r"\bbarrier\b|\bbarricade\b|\bcordon\w*|\btape[d]? off\b"),
    ("Lockout / tagout",  r"\blockout\b|\btagout\b|\bloto\b|\bisolat(?:ed|ion)\b"),
    ("Permit to work",    r"\bpermit\b|\bwork authorisation\b|\bwork authorization\b"),
    ("Machine guard",     r"\bguard\b"),
    ("PPE",               r"\bppe\b|\bgloves?\b|\bhelmet\b|\bgoggles\b|\bharness\b"),
]

#: Negation within this many characters before/after a control mention marks it absent.
_ABSENT = r"(?:no|not|without|missing|absent|lack(?:ing|ed)?|failed to|were ?n[o']t|was ?n[o']t|had ?n[o']t|never)"

INCIDENT_TYPES: List[Tuple[str, str]] = [
    ("Injury",        r"\binjur\w+|\bwound\w*|\bfracture\w*|\blaceration\b|\bburn(?:ed|s)?\b|\bcut\b|\bbruis\w+|\bhospital\w*|\bfirst aid\b|\bmedical treatment\b"),
    ("Near miss",     r"\bnear[- ]miss\b|\bnearly\b|\balmost\b|\bcould have\b|\bnarrowly\b|\bavoided\b"),
    ("Unsafe condition", r"\bunsafe condition\b|\bhazard(?:ous)? condition\b|\bdefect\w*|\bnot functioning\b"),
    ("Unsafe act",    r"\bunsafe act\b|\bbypass\w*|\bshortcut\b|\bdid not follow\b|\bignored\b|\bfailed to follow\b"),
    ("Property damage", r"\bdamage[d]?\b|\bbroken\b|\bdent\w*|\bwrite[- ]off\b"),
    ("Observation",   r"\bobserv\w+|\bnoticed\b|\breported that\b|\bwalkthrough\b|\binspection\b|\baudit\b"),
]

#: Signals that force HIGH regardless of accumulated score. Each is a condition where a
#: MEDIUM label would understate something a safety officer must see today.
CRITICAL_SIGNALS: List[Tuple[str, str]] = [
    ("Serious injury reported",  r"\bhospital\w*|\bambulance\b|\bfracture\w*|\bunconscious\b|\bamputat\w+|\bsevere\b|\bmajor injury\b|\blost time\b"),
    ("Fire or explosion",        r"\bfire\b|\bexplosion\b|\bignition\b|\bflames?\b"),
    ("Electrical contact",       r"\belectric(?:al)? shock\b|\bshocked\b|\blive (?:wire|conductor|panel)\b|\bexposed (?:wire|conductor)s?\b|\barc flash\b"),
    ("Chemical exposure to person", r"\b(?:inhaled|ingested|splash\w*|exposed to)\b[^.]{0,40}\b(?:chemical|acid|solvent|fumes?|vapou?rs?|caustic)\b"),
    ("Confined space entry",     r"\bconfined space\b"),
    ("Fall from height",         r"\bfell from\b|\bfall from height\b|\bfell off (?:the )?(?:ladder|scaffold|platform|mezzanine)\b"),
]

INJURY_RE = re.compile(r"\binjur\w+|\bhurt\b|\bwound\w*|\bfracture\w*|\blaceration\b|\bcut (?:his|her|their|the)\b|\bbruis\w+|\bhospital\w*|\bfirst aid\b", re.I)
NO_INJURY_RE = re.compile(r"\bno (?:one |body |personnel )?(?:was |were )?(?:injur\w+|hurt|harmed)\b|\bnot injured\b|\bno injur\w+\b|\bwithout injury\b|\bunharmed\b", re.I)

ENV_PATTERNS: List[Tuple[str, str]] = [
    ("Poor lighting",   r"\b(?:poor|low|inadequate|dim|no) light\w*"),
    ("Wet conditions",  r"\bwet\b|\brain\w*|\bdamp\b|\bpuddle\b|\bcondensation\b"),
    ("High temperature", r"\bhot\b|\bheat\b|\bhigh temperature\b|\bhumid\w*"),
    ("Restricted space", r"\bconfined\b|\bcramped\b|\bnarrow\b|\brestricted (?:space|access)\b"),
    ("Night shift",     r"\bnight shift\b|\bnight[- ]time\b|\bgraveyard shift\b"),
]

#: Weighted contributions. Tuned so a single serious hazard with a missing control clears HIGH,
#: and a lone housekeeping observation stays LOW. The weights are a demo convention, not science.
HAZARD_WEIGHT = {
    "Chemical exposure": 26, "Electrical hazard": 26, "Fire / ignition": 28,
    "Confined space": 26, "Working at height": 22, "Machine guarding": 22,
    "Equipment failure": 16, "Overheating": 16, "Vehicle / forklift": 14,
    "Oil spill": 14, "Slip / trip / fall": 14, "Blocked egress": 18,
    "Missing PPE": 12, "Manual handling": 10, "Wet surface": 10,
    "Noise exposure": 8, "Housekeeping": 6,
}
MISSING_CONTROL_WEIGHT = 12
INJURY_WEIGHT = 22
NEAR_MISS_WEIGHT = 8
REPEAT_WEIGHT = 10          # applied by the risk agent when history shows the same hazard+location

HIGH_THRESHOLD = 60
MEDIUM_THRESHOLD = 30


def _find(text: str, patterns: List[Tuple[str, str]]) -> List[str]:
    out: List[str] = []
    for name, pattern in patterns:
        if re.search(pattern, text, re.I):
            out.append(name)
    return out


def _evidence(text: str, pattern: str, window: int = 60) -> Optional[str]:
    """The phrase that matched, so a classification can cite the report rather than assert."""
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    start = max(0, match.start() - window // 2)
    end = min(len(text), match.end() + window // 2)
    snippet = text[start:end].strip().replace("\n", " ")
    return f"…{snippet}…" if (start > 0 or end < len(text)) else snippet


def detect_missing_controls(text: str) -> List[str]:
    """Controls the report says were absent. Absence is the risk factor, not the control."""
    missing: List[str] = []
    for name, pattern in CONTROL_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            before = text[max(0, match.start() - 45):match.start()]
            after = text[match.end():match.end() + 25]
            if re.search(_ABSENT + r"[^.]{0,40}$", before, re.I) or re.search(
                r"^[^.]{0,25}\b(?:missing|absent|not (?:in place|available|provided|used|worn))\b", after, re.I
            ):
                missing.append(f"{name} missing")
                break
    return missing


def detect_injury(text: str) -> Optional[bool]:
    """True / False / None. None means the report does not say — never guessed."""
    if NO_INJURY_RE.search(text):
        return False
    if INJURY_RE.search(text):
        return True
    return None


def extract(text: str) -> Dict[str, Any]:
    """Structured facts grounded in the report. Absent information stays absent."""
    text = (text or "").strip()
    hazards = _find(text, HAZARD_PATTERNS)
    missing_controls = detect_missing_controls(text)
    incident_types = _find(text, INCIDENT_TYPES)
    injury = detect_injury(text)
    if injury is False and "Injury" in incident_types:
        # "The worker was not injured" matches the injury vocabulary on the word alone. An
        # explicit denial outranks the keyword, or every near miss is filed as an injury.
        incident_types.remove("Injury")
        if "Near miss" not in incident_types:
            incident_types.insert(0, "Near miss")
    env = _find(text, ENV_PATTERNS)
    critical = [(name, _evidence(text, pattern)) for name, pattern in CRITICAL_SIGNALS
                if re.search(pattern, text, re.I)]

    risk_factors = hazards + missing_controls + env
    return {
        "hazards": hazards,
        "missing_controls": missing_controls,
        "risk_factors": risk_factors,
        "incident_type": incident_types[0] if incident_types else "Unknown",
        "incident_types": incident_types,
        "injury_present": injury,
        "ppe_issue": ("Missing PPE" in hazards) or any("PPE" in c for c in missing_controls),
        "environmental_condition": env[0] if env else None,
        "severity_indicators": [name for name, _ in critical],
        "critical_signals": [{"signal": n, "evidence": e} for n, e in critical],
        "evidence": {h: _evidence(text, p) for h, p in HAZARD_PATTERNS if h in hazards},
    }


def score(facts: Dict[str, Any], repeat_hits: int = 0) -> Tuple[int, List[Dict[str, Any]]]:
    """`(0..100, contributions)`. Every point is attributable to a named, cited signal."""
    total = 0
    contributions: List[Dict[str, Any]] = []

    for hazard in facts.get("hazards", []):
        weight = HAZARD_WEIGHT.get(hazard, 8)
        total += weight
        contributions.append({"factor": hazard, "points": weight, "kind": "hazard",
                              "evidence": (facts.get("evidence") or {}).get(hazard)})

    for control in facts.get("missing_controls", []):
        total += MISSING_CONTROL_WEIGHT
        contributions.append({"factor": control, "points": MISSING_CONTROL_WEIGHT,
                              "kind": "missing_control", "evidence": None})

    if facts.get("injury_present") is True:
        total += INJURY_WEIGHT
        contributions.append({"factor": "Injury reported", "points": INJURY_WEIGHT,
                              "kind": "outcome", "evidence": None})
    elif "Near miss" in facts.get("incident_types", []):
        total += NEAR_MISS_WEIGHT
        contributions.append({"factor": "Near miss", "points": NEAR_MISS_WEIGHT,
                              "kind": "outcome", "evidence": None})

    if repeat_hits > 0:
        points = min(REPEAT_WEIGHT * repeat_hits, 20)
        total += points
        contributions.append({"factor": f"Recurring condition ({repeat_hits} similar prior reports)",
                              "points": points, "kind": "recurrence", "evidence": None})

    return min(total, 100), contributions


def classify(points: int, facts: Dict[str, Any]) -> Tuple[str, List[str]]:
    """`(level, override_reasons)`. Critical signals force HIGH whatever the score says."""
    critical = facts.get("critical_signals") or []
    if critical:
        return "HIGH", [c["signal"] for c in critical]
    if points >= HIGH_THRESHOLD:
        return "HIGH", []
    if points >= MEDIUM_THRESHOLD:
        return "MEDIUM", []
    return "LOW", []


def confidence(text: str, facts: Dict[str, Any]) -> float:
    """How much the report actually supports the classification — not how sure the model feels.

    Driven by observable coverage: a two-line report naming nothing specific yields a low number,
    and that low number is the useful signal ("go read this one yourself").
    """
    words = len((text or "").split())
    value = 0.35
    if facts.get("hazards"):
        value += min(0.25, 0.10 * len(facts["hazards"]))
    if facts.get("incident_types"):
        value += 0.10
    if facts.get("injury_present") is not None:
        value += 0.10
    if facts.get("missing_controls"):
        value += 0.08
    if words >= 25:
        value += 0.07
    if words >= 60:
        value += 0.05
    if not facts.get("hazards"):
        value -= 0.15
    return round(max(0.15, min(0.97, value)), 2)
