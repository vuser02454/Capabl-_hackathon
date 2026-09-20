"""Incident domain classification — which kind of emergency, if any, a report describes.

This decides which specialised response branch the LangGraph workflow takes. It is deterministic
and regex-driven for the same reason the risk classifier is: a routing decision that sends a
report to the VIOLENCE_SECURITY branch has to be reproducible and inspectable, and an LLM that
occasionally routes an oil spill to MEDICAL would be worse than no routing at all.

Every classification carries the phrase that triggered it, so the admin can see WHY a report was
routed and overrule it. Domains are ranked by urgency rather than by match count: a report that
mentions both a fire and some housekeeping is a fire.

The routing decides which authority type is *relevant to look up*. It never decides that an
emergency is real, and never contacts anyone — a human does both.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: Domains in descending urgency. The first domain with a match wins, so ordering is the
#: priority rule: a report describing a fire during an assault is routed to the fire.
DOMAIN_ORDER = (
    "MEDICAL",
    "FIRE",
    "VIOLENCE_SECURITY",
    "ELECTRICAL",
    "CHEMICAL",
    "WILDLIFE",
    "EQUIPMENT",
    "GENERAL_SAFETY",
    "ENVIRONMENTAL",
    "OTHER",
)

#: Which authority is *relevant to look up* for a domain. Relevance is not a decision to contact.
DOMAIN_AUTHORITY = {
    "MEDICAL": "EMERGENCY_MEDICAL",
    "FIRE": "FIRE_STATION",
    "VIOLENCE_SECURITY": "POLICE",
    "ELECTRICAL": "ELECTRICAL_SERVICE",
    "CHEMICAL": "FIRE_STATION",       # hazmat response sits with the fire service in most regions
    "WILDLIFE": "WILDLIFE_AUTHORITY",
    "EQUIPMENT": None,
    "ENVIRONMENTAL": None,
    "GENERAL_SAFETY": None,
    "OTHER": None,
}

DOMAIN_LABEL = {
    "MEDICAL": "Medical emergency",
    "FIRE": "Fire",
    "VIOLENCE_SECURITY": "Security / violence",
    "ELECTRICAL": "Electrical",
    "CHEMICAL": "Chemical",
    "WILDLIFE": "Wildlife",
    "EQUIPMENT": "Equipment",
    "ENVIRONMENTAL": "Environmental",
    "GENERAL_SAFETY": "General safety",
    "OTHER": "Unclassified",
}

#: (domain, regex). Anchored on word boundaries; several may match one report.
DOMAIN_PATTERNS: List[Tuple[str, str]] = [
    ("MEDICAL", r"\bunconscious\b|\bnot breathing\b|\bcardiac\b|\bheart attack\b|\bseizure\b|"
                r"\bambulance\b|\bbleeding (?:heavily|badly|profusely)\b|\bsevere bleeding\b|"
                r"\bcollapsed\b|\bamputat\w+|\bcompound fracture\b|\bmedical emergency\b|"
                r"\brushed to hospital\b|\bcpr\b|\bresuscitat\w+"),

    ("FIRE", r"\bfire\b|\bsmoke\b|\bflames?\b|\bblaze\b|\bburning smell\b|\bsmell of burning\b|"
             r"\bexplosion\b|\bfire alarm\b|\bignition\b|\bcombust\w+"),

    ("VIOLENCE_SECURITY", r"\bassault\w*|\battack(?:ed|ing|er)?\b|\bfight(?:ing)?\b|\bpunch\w*|"
                          r"\bstabb\w+|\bweapon\b|\bknife\b|\bgun\b|\bfirearm\b|\bshot at\b|"
                          r"\bthreaten\w+|\bthreat\b|\bintruder\b|\btrespass\w+|\bbreak[- ]in\b|"
                          r"\brobbery\b|\btheft\b|\bstole\w*|\bvandal\w+|\bharass\w+|"
                          r"\bviolen\w+|\bsecurity (?:breach|incident)\b|\bunauthorised person\b|"
                          r"\bunauthorized person\b"),

    ("ELECTRICAL", r"\belectric(?:al)? shock\b|\bshocked\b|\bexposed wir(?:e|ing)\b|\blive wire\b|"
                   r"\blive (?:conductor|panel)\b|\bspark(?:s|ing|ed)\b|\barc flash\b|"
                   r"\bshort circuit\b|\belectrocut\w+|\bearth(?:ing)? fault\b|"
                   r"\bdamaged (?:cable|socket|switchboard|electrical)\b"),

    ("CHEMICAL", r"\bchemical\b|\bsolvent\b|\bcorrosive\b|\bacid\b|\bcaustic\b|\btoxic\b|"
                 r"\bfumes?\b|\bvapou?rs?\b|\bhazmat\b|\bgas leak\b|\bammonia\b|\bchlorine\b|"
                 r"\bsafety data sheet\b|\bmsds\b"),

    ("WILDLIFE", r"\banimal\b|\bwildlife\b|\bsnake\b|\bleopard\b|\btiger\b|\belephant\b|\bbear\b|"
                 r"\bboar\b|\bmonkey\b|\bdog pack\b|\bstray dogs?\b|\bswarm\b|\bbee(?:s|hive)\b|"
                 r"\bhornets?\b|\bpaw ?print\w*|\banimal tracks?\b|\bpug ?marks?\b|"
                 r"\bcarcass\b|\bmauled\b|\bbitten by\b|\bsnake ?bite\b"),

    ("EQUIPMENT", r"\bmalfunction\w*|\bbreakdown\b|\bdefective\b|\bfaulty\b|\bseiz(?:ed|ure)\b|"
                  r"\bequipment failure\b|\bmachine (?:failed|stopped|jammed)\b|\bguard (?:missing|removed)\b|"
                  r"\bunguarded\b|\bforklift\b|\bconveyor\b|\bcrane\b|\bhoist\b"),

    ("ENVIRONMENTAL", r"\bspill\w*|\bleak\w*|\bdischarge\b|\beffluent\b|\bcontaminat\w+|"
                      r"\bpollut\w+|\bwaste\b|\bdrain\w*|\bflood\w*"),

    ("GENERAL_SAFETY", r"\bslip(?:ped|pery|ping)?\b|\btrip(?:ped|ping)?\b|\bfell\b|\bfall(?:en|ing)?\b|"
                       r"\bppe\b|\bhelmet\b|\bharness\b|\bladder\b|\bscaffold\w*|\bhousekeep\w*|"
                       r"\bnear[- ]miss\b|\bunsafe\b|\bhazard\w*|\bblock(?:ed|ing|s)?\b|"
                       r"\bobstruct\w*|\bnoise\b|\blighting\b|\bwet floor\b|\bwalkway\b|"
                       r"\b(?:emergency )?exit\b|\bstack(?:ed|ing)\b|\bclutter\w*|\bdebris\b"),
]

#: Historical incidents that change how a current report should be read. These are matched against
#: STORED report text, never invented, and only ever reported alongside the report ids they came from.
SERIOUS_INCIDENT_PATTERNS: List[Tuple[str, str]] = [
    ("Fatality",             r"\bfatal\w*|\bdied\b|\bdeath\b|\bkilled\b|\bfatality\b|\bdeceased\b"),
    ("Serious injury",       r"\bhospitalis\w+|\bhospitaliz\w+|\bamputat\w+|\bfracture\w*|"
                             r"\bunconscious\b|\bsevere\b|\bcritical condition\b|\blost time\b"),
    ("Animal attack",        r"\bmauled\b|\battacked by\b|\banimal attack\b|\bbitten by\b|\bsnake ?bite\b"),
    ("Fire",                 r"\bfire\b|\bexplosion\b|\bblaze\b"),
    ("Electrical incident",  r"\belectrocut\w+|\belectric(?:al)? shock\b|\barc flash\b"),
    ("Chemical exposure",    r"\b(?:inhaled|ingested|splash\w*|exposed to)\b[^.]{0,40}"
                             r"\b(?:chemical|acid|solvent|fumes?|vapou?rs?|caustic)\b"),
    ("Major equipment failure", r"\bcollaps\w+|\bcatastrophic\b|\bmajor (?:failure|breakdown)\b|\bderail\w+"),
    ("Security incident",    r"\bassault\w*|\bstabb\w+|\brobbery\b|\bweapon\b|\bintruder\b"),
]

_COMPILED = [(domain, re.compile(pattern, re.I)) for domain, pattern in DOMAIN_PATTERNS]
_SERIOUS = [(label, re.compile(pattern, re.I)) for label, pattern in SERIOUS_INCIDENT_PATTERNS]


def _evidence(match: re.Match, text: str, window: int = 50) -> str:
    """The phrase that fired, with a little context — so a routing decision can be checked."""
    start = max(0, match.start() - window // 2)
    end = min(len(text), match.end() + window // 2)
    snippet = text[start:end].strip().replace("\n", " ")
    return f"…{snippet}…" if (start > 0 or end < len(text)) else snippet


def classify(text: str) -> Dict[str, Any]:
    """Route one report to a domain, with the evidence that decided it.

    Returns the winning domain plus every other domain that matched, because a report can
    legitimately belong to two and the admin should see the one that lost.
    """
    body = text or ""
    matches: Dict[str, Dict[str, Any]] = {}
    for domain, pattern in _COMPILED:
        found = pattern.search(body)
        if found:
            matches[domain] = {"domain": domain, "label": DOMAIN_LABEL[domain],
                               "matched_text": found.group(0), "evidence": _evidence(found, body)}

    # Urgency order, not match count: one mention of fire outranks five of housekeeping.
    primary = next((d for d in DOMAIN_ORDER if d in matches), "OTHER")
    secondary = [matches[d] for d in DOMAIN_ORDER if d in matches and d != primary]

    return {
        "domain": primary,
        "label": DOMAIN_LABEL[primary],
        "authority_type": DOMAIN_AUTHORITY.get(primary),
        "evidence": matches.get(primary, {}).get("evidence"),
        "matched_text": matches.get(primary, {}).get("matched_text"),
        "also_matched": secondary,
        "is_emergency_domain": primary in EMERGENCY_DOMAINS,
        "method": "rules",
    }


#: Domains that get a specialised response branch and an authority lookup. The rest are handled
#: by the ordinary advisor — inventing an "authority" for a housekeeping report would be noise.
EMERGENCY_DOMAINS = frozenset({"MEDICAL", "FIRE", "VIOLENCE_SECURITY", "ELECTRICAL", "CHEMICAL", "WILDLIFE"})


def serious_incident_markers(text: str) -> List[Dict[str, str]]:
    """Serious-incident labels present in one report's text, each with its triggering phrase.

    Used against HISTORICAL reports to answer "has something grave already happened here?".
    Returns an empty list rather than guessing when nothing matches.
    """
    body = text or ""
    out: List[Dict[str, str]] = []
    for label, pattern in _SERIOUS:
        found = pattern.search(body)
        if found:
            out.append({"label": label, "matched_text": found.group(0), "evidence": _evidence(found, body)})
    return out


def domain_catalogue() -> List[Dict[str, Optional[str]]]:
    """The routing table, for the UI to render without duplicating it in TypeScript."""
    return [
        {"domain": d, "label": DOMAIN_LABEL[d], "authority_type": DOMAIN_AUTHORITY.get(d),
         "specialised": d in EMERGENCY_DOMAINS}
        for d in DOMAIN_ORDER
    ]
