"""Synthetic safety reports for the demo corpus.

EVERY record carries `"source": "synthetic"` and is surfaced that way in the UI. These are written
prose, not sampled from any incident database, and they do NOT represent real-world incident
frequencies — the mix is chosen so pattern detection has something to find, which is the opposite
of a representative sample.

Three patterns are planted deliberately, because a pattern dashboard with nothing to discover
demonstrates nothing:

  1. Oil spills in the Loading Bay (forklift hydraulic leaks) — the flagship recurring pattern
  2. Missing PPE in the Maintenance Workshop — recurring behavioural issue
  3. Electrical faults in the Electrical Substation — low count, high severity

The remainder are spread across locations, departments and severities so the distribution is not
uniformly one thing.
"""

from __future__ import annotations

from typing import Any, Dict, List

#: (text, reported_at). Written as a safety officer would receive them: uneven length, some
#: vague, some precise — a corpus of uniformly well-written reports would flatter the extractor.
REPORTS: List[str] = [
    # --- Pattern 1: Loading Bay oil spills (forklift hydraulics) ------------------------------
    "At approximately 10:30 AM a worker nearly slipped in the Loading Bay after oil leaked from a "
    "forklift. No warning signage was placed around the affected area. The worker was not injured.",
    "Hydraulic fluid found pooling under the forklift in the Loading Bay during the morning "
    "walkthrough. The spill was not cordoned off and no cones were present. Logistics notified.",
    "Oil spill in Loading Bay again. Second time this week. Forklift 3 appears to be leaking from "
    "the mast cylinder. Area is slippery and no barrier was in place.",
    "Operator reported a slippery patch near the Loading Bay dock door. Oil residue visible. "
    "Housekeeping was called but signage was missing for over an hour.",
    "During night shift a pallet truck operator slipped on oil in the Loading Bay. He caught "
    "himself on the racking and was not injured. Lighting in that corner is poor.",
    "Forklift hydraulic leak reported in the Loading Bay. Maintenance attended. No signage was "
    "placed while the spill was being cleaned, and a delivery driver walked through the area.",

    # --- Pattern 2: Maintenance Workshop PPE ---------------------------------------------------
    "Technician observed operating the grinder in the Maintenance Workshop without safety glasses. "
    "He stated the goggles were fogging up. No injury occurred.",
    "Two maintenance staff were seen in the Maintenance Workshop without gloves while handling "
    "sheet metal. One sustained a minor cut to the hand and received first aid.",
    "During a walkthrough of the Maintenance Workshop, hearing protection was not being worn near "
    "the compressor despite the posted requirement.",
    "Maintenance Workshop: welding was taking place without a screen in position. A passing "
    "employee reported eye discomfort afterwards.",
    "PPE audit in the Maintenance Workshop found three technicians without safety boots. "
    "Supervisor was informed.",

    # --- Pattern 3: Electrical Substation (low count, high severity) ---------------------------
    "Exposed wiring found in the Electrical Substation near the distribution panel. The panel door "
    "was not locked and there was no lockout tag applied. Area was isolated immediately.",
    "An electrician received a minor electrical shock while working on the switchboard in the "
    "Electrical Substation. He was taken to hospital as a precaution. Lockout procedure had not "
    "been followed.",
    "Burning smell reported from the Electrical Substation. On inspection a cable termination was "
    "overheating. Supply was isolated. No fire occurred.",

    # --- Spread: varied hazards, locations, severities -----------------------------------------
    "A cardboard bale fell from the stack in the Warehouse when it was disturbed by a passing "
    "pallet truck. Nobody was in the aisle at the time.",
    "Emergency exit in the Packaging Hall was found blocked by stacked pallets. The route was "
    "cleared immediately and the supervisor briefed the shift.",
    "Chemical store: a container of solvent was left open on the bench. Fumes were noticeable on "
    "entry. Ventilation fan was not switched on.",
    "Operator strained his back lifting a 25 kg drum in the Chemical Store without assistance. "
    "He reported discomfort and was sent for first aid. No mechanical aid was available nearby.",
    "Conveyor guard on Production Line A was found removed. The line was running. It was stopped "
    "and the guard refitted before restart.",
    "Coolant leak on the press in Production Line B created a wet patch. A cone was placed and "
    "maintenance attended within the hour.",
    "Housekeeping issue in the Dispatch Yard — shrink wrap and strapping left across the walkway.",
    "The ladder in the Maintenance Workshop has a damaged stile. It was tagged out of service.",
    "A worker was observed standing on the top step of a stepladder in the Warehouse to reach a "
    "high shelf. He was asked to stop and use the correct access equipment.",
    "Reversing alarm on the forklift in the Dispatch Yard is not working. The vehicle was taken "
    "out of service pending repair.",
    "Near miss in the Car Park: a delivery vehicle reversed close to a pedestrian walking to the "
    "Canteen. No physical contact. Pedestrian route is not separated from the vehicle route.",
    "Cold Storage door seal is damaged, causing condensation and a wet floor at the entrance. "
    "Slip risk noted; a mat has been placed as a temporary measure.",
    "Boiler Room: pressure gauge reading outside the normal band. Engineering attended and "
    "adjusted. No release occurred.",
    "Paint Shop extraction fan was running intermittently. Solvent smell noticeable in the booth. "
    "Work was paused and the fan was serviced.",
    "A laboratory technician spilled a small quantity of acid on the bench during a transfer. "
    "Spill kit was used correctly. No skin contact and no injury.",
    "Assembly Floor: a pneumatic hose was left across the walkway creating a trip hazard. "
    "Rerouted immediately.",
    "Quality inspector noted that the eyewash station in the Laboratory has not been flush-tested "
    "this month.",
    "Overheating noted on the packaging machine motor in the Packaging Hall. Thermal cut-out "
    "operated as designed. Maintenance investigating.",
    "During a routine inspection, the fire extinguisher in the Dispatch Yard was found to be "
    "missing from its bracket.",
    "A pallet of finished goods in the Warehouse was stacked above the safe height marking.",
    "Facilities reported a broken floor tile in the Canteen causing an uneven surface.",
    "Roof Access hatch was found unlocked. Anyone could reach the roof edge, which has no "
    "permanent edge protection installed.",
    "A contractor began hot work in the Maintenance Workshop without a permit in place. Work was "
    "stopped and a permit was issued before resuming.",
    "Security noted that the barrier at the Dispatch Yard entrance is slow to lower, allowing "
    "vehicles to follow through.",
    "Minor oil mark observed on the floor of the Assembly Floor near the hoist. Cleaned promptly, "
    "source not identified.",
    "Production Line A operator reported that the emergency stop button is stiff and requires "
    "excessive force to activate.",
    "A cleaning trolley was left unattended in the corridor near the Packaging Hall fire door.",
    "Warehouse racking upright shows impact damage at floor level, likely from a pallet truck. "
    "Load has been removed from that bay pending inspection.",
    "Employee reported feeling unwell after working in the Boiler Room for an extended period. "
    "Temperature in the space was high. He was moved to a cool area and recovered.",
    "Compressed air line in the Maintenance Workshop has a worn hose showing reinforcement.",
    "Laboratory fume cupboard sash was left fully open overnight with reagents inside.",
    "A visitor was observed walking through the Assembly Floor without high-vis, escorted by a "
    "staff member who was also not wearing one.",
    "Cold Storage: emergency release handle on the inside of the door is obstructed by stored "
    "boxes. Cleared during the inspection.",
]


def records() -> List[Dict[str, Any]]:
    """The corpus, every entry explicitly labelled synthetic."""
    return [{"report_text": text, "source": "synthetic"} for text in REPORTS]


def count() -> int:
    return len(REPORTS)
