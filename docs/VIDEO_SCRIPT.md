# Video Script — 75 seconds

**Written for: whoever records and edits the submission video.**

Rubric: 200 of 500 marks. Length 60–80 s (40) · Hook (40) · A/V quality (40) · Storytelling (80).
Target runtime **75 s** — inside the window with room for a breath, not scraping the 60 s floor.

Everything claimed below is verified. Nothing needs softening in the edit.

---

## The spine

One idea, carried the whole way through:

> Every environmental AI detects things. Ours knows the difference between what it **saw**, what
> it **inferred**, and what it has **not established**.

Do not try to show the whole system. A 75-second video that explains three agents, a graph, a
retriever and a tool layer explains nothing. Show **one bug, one fix, one principle** — the
people-and-kites story — and let the architecture appear behind it.

---

## Shot list

| # | Time | Visual | Voiceover |
| --- | --- | --- | --- |
| 1 | 0:00–0:08 | **Cold open, no logo.** Full-screen river photo with six detection boxes. Two labelled `person`, four `kite`. Then a red counter slams up: **"6 pollution objects · risk +8"** | "This is what our system used to say about this river." |
| 2 | 0:08–0:16 | Boxes stay. Labels zoom: `person`, `kite`. Red counter glitches, resets to **0**. | "Two people. Four kites. Not one piece of litter — and it raised the pollution score anyway." |
| 3 | 0:16–0:24 | Title card over the dimmed photo: **EcoSentinel AI** — *Evidence-driven environmental intelligence* | "Most environmental AI is confidently wrong in exactly this way. We built the system that catches it." |
| 4 | 0:24–0:34 | Dashboard. Three agents fire **in parallel** (visible simultaneity). Evidence Fusion panel draws its connector lines. Risk lands: **79 / 100 HIGH**. | "Air, water and waste run as independent agents. Their evidence converges — and a deterministic engine computes the risk. Not a language model. Python." |
| 5 | 0:34–0:44 | Water upload. Panel resolves: **Visible litter 0 · of 6 objects detected** → then **"Also detected — not counted as pollution"** → then **"Not established: chemical contamination"** | "Now it separates what the detector saw from what that actually means. Six objects. Zero litter. And it says so." |
| 6 | 0:44–0:54 | **Scenario C.** Split screen: litter boxes on the left, all-green sensor readings on the right. Conflict banner slides in. | "Here's the hard case. Vision sees litter. The sensors are clean. A naive system picks one and asserts it." |
| 7 | 0:54–1:03 | Zoom the conflict card: **OBSERVED** / **NOT ESTABLISHED** / **CONFLICT** / **RECOMMENDED**. | "EcoSentinel reports the disagreement — visible litter observed, chemical contamination *not* established, verification recommended." |
| 8 | 1:03–1:11 | Waste photo → Grad-CAM heatmap blooms on the can's **lid and rim**. Caption: *real gradients, 7×7, MobileNetV3* | "Every classification shows the model's own gradients. When it can't, it says 'unavailable' instead of drawing something reassuring." |
| 9 | 1:11–1:15 | Hard cut to black. White text, one line at a time: **408 tests · 37 live checks · 0 fabricated claims** | "Honest by construction." |

**Total: 75 s.**

---

## The hook (40 marks) — why shot 1 works

It opens on the system being **wrong**. No logo, no problem-statement montage, no "environmental
monitoring is fragmented" voiceover over stock drone footage. A judge who has watched forty demos
has never seen one open by admitting a bug.

It also does the work: by second 8 the viewer already understands the entire thesis — detection is
easy, interpretation is where systems lie — without anyone having stated it.

**Do not** put a logo before shot 1. **Do not** fade in. Cut straight to the river.

---

## Recording notes

**Capture**
- Record at 1920×1080, 60 fps if your screen recorder allows, then deliver 1080p.
- Zoom the browser to **125%** before recording. Dashboard text is dense; at 100% it is unreadable after compression.
- Hide bookmarks, close other tabs, use a clean profile. A visible tab bar reads as a prototype.
- Run the backend and frontend and **complete one analysis before recording**, so models are
  warm. A cold `torch` import costs several seconds you do not have.

**Audio** — this is 40 marks and the cheapest to win
- Record voiceover **separately** from screen capture. Never live-narrate a demo.
- Use any half-decent mic, 15 cm away, off-axis. Phone earbuds beat a laptop mic.
- Record in a soft room — a bed, a sofa, clothes on a rail. Bare walls sound like a corridor.
- Do one noise-reduction pass and one light compressor pass. Nothing more.
- Speak **slower than feels natural**. The script is ~150 words for 75 s, which is a calm pace.

**Edit**
- Cut on the beat of each sentence. No crossfades between shots — hard cuts throughout.
- Music: instrumental, low, ducked to about -18 dB under the voice. Drop it entirely at shot 9.
- Captions burned in. Many judges watch muted first.
- Colour: leave it. The dark UI already grades itself.

---

## Exact demo state to prepare

| Shot | Preparation |
| --- | --- |
| 1–2, 5 | `water_datasets/TUD-GV/images/exp55_221.jpg` — the people-and-kites frame |
| 4 | `/api/analyze` on **Delhi**, demo mode — reliably HIGH with all three agents reporting |
| 6–7 | `python backend/scripts/demo_scenarios.py --scenario C`, or stage it in the UI |
| 8 | `runs/debug_waste/original/metal_can.jpg` with **Explain (Grad-CAM)** ticked |

**Avoid `plastic_bottle.jpg`** — the detector returns zero detections on it. Real limitation,
wrong moment.

---

## What the voiceover must not say

Taken from `HACKATHON_PRESENTATION_NOTES.md`; these are the claims that would make the video
unsupportable if a judge checked.

- Not "detects water contamination" → **"detects visible surface litter"**.
- Not "93% accurate" as a system figure → that is the classifier on clean crops.
- Not "trained on water litter" → the water detector is **COCO-pretrained**.
- Not "real-time monitoring" over demo data → it is seeded and labelled `isMock`.
- Not "explainable AI" about the LLM layer → the LLM explains a **decision**; Grad-CAM explains a
  **model**. Only the second is XAI.

---

## If you have 20 extra seconds (90 s cut)

Insert between shots 8 and 9:

> Retrieved-knowledge panel expanding, chunk id and source file visible.
> *"Explanations are grounded in our own documented standards — every citation resolves to a file
> you can open. Ask it something outside that corpus and it returns nothing rather than inventing
> a source."*

Worth it only if the 75-second cut already breathes. Length is scored; padding is not.
