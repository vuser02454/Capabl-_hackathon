"""EXPERIMENT: can a local Qwen2-VL-2B localise EcoSentinel waste well enough to be useful?

Describing an image is not the question — the production detector's weakness is *where*, not
*what*, so this measures boxes. An answer that names a bottle but cannot say where it is adds
nothing YOLO does not already have.

Device note, measured rather than assumed: MPS float32 is the only configuration that is both
fast and correct on this machine. float16 returns a refusal string and bfloat16 loops
("a bottle with a label and a label and a label"), so the 2x speedup they offer buys nothing.

    CPU  fp32   26.5 s   correct
    MPS  fp32   12.0 s   correct      <- used here
    MPS  bf16    6.9 s   degenerate
    MPS  fp16    7.0 s   garbage

Touches nothing in production: no import from this file exists anywhere in the app, the YOLO
checkpoint is read-only, and `/api/waste/segregate` is not involved.

    python backend/scripts/test_qwen_local.py
"""

from __future__ import annotations

import json
import re
import resource
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

MODEL_ID = "Qwen/Qwen2-VL-2B-Instruct"
OUT_DIR = REPO_ROOT / "runs" / "experiments" / "qwen_local"

#: Downscale before inference. A 1080x1920 frame costs 2,720 vision tokens and 80 s; 640 px costs
#: 328 tokens and a third of the time, with no measured loss in description quality.
MAX_EDGE = 640

WASTE_CLASSES = ["plastic_bottles", "plastic_bags", "paper_waste", "metal_cans", "food_waste", "ewaste"]

#: Visual appearances only. A photograph cannot establish chemistry, so the vocabulary is written
#: so that every term stays an observation: "oil_like_surface" is something you can see,
#: "petroleum contamination" is a lab result and is not offered as an option.
WATER_INDICATORS = [
    "floating_waste", "visible_plastic", "oil_like_surface", "foam",
    "algal_bloom_appearance", "visible_debris", "turbidity_or_cloudiness",
]

WASTE_PROMPT = (
    "Find every discarded waste object in this photograph and give its bounding box.\n\n"
    f"Allowed classes: {', '.join(WASTE_CLASSES)}\n\n"
    "Furniture, walls, curtains, shelves, tables, appliances and decorations are NOT waste — "
    "do not box them. If an object looks like waste but fits no class, use \"unknown\". "
    "Give each object its own box; never merge several objects into one.\n\n"
    "Boxes are [x1, y1, x2, y2] normalized 0-1000, origin at the top-left.\n"
    'Return ONLY JSON: {"objects": [{"class": "plastic_bottles", "bbox": [x1,y1,x2,y2], '
    '"description": "..."}]}\n'
    'If there is no waste, return {"objects": []}.'
)

WATER_PROMPT = (
    "Report only what is VISIBLE in this water photograph. You are describing appearance, not "
    "measuring chemistry.\n\n"
    f"Allowed visual indicators: {', '.join(WATER_INDICATORS)}\n\n"
    "Rules you must follow:\n"
    "- \"oil_like_surface\" means an iridescent sheen is visible. Do NOT claim petroleum "
    "contamination; that needs a laboratory.\n"
    "- \"turbidity_or_cloudiness\" means the water looks cloudy. Do NOT state an NTU value; that "
    "needs a sensor.\n"
    "- Never invent measurements, concentrations, GPS coordinates or sensor readings.\n"
    "- If the water simply looks clean, say so and return an empty list.\n\n"
    "Boxes are [x1, y1, x2, y2] normalized 0-1000, origin at the top-left.\n"
    'Return ONLY JSON: {"objects": [{"class": "floating_waste", "bbox": [x1,y1,x2,y2], '
    '"description": "..."}]}'
)


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 3)


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@dataclass
class ImageResult:
    image_id: str
    path: str
    original_size: Tuple[int, int]
    inference_size: Tuple[int, int]
    latency_s: float
    raw_response: str
    objects: List[Dict[str, Any]] = field(default_factory=list)
    malformed: List[Dict[str, Any]] = field(default_factory=list)
    parse_ok: bool = False
    parse_error: Optional[str] = None


def _strip_fence(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return (fenced.group(1) if fenced else text).strip()


def parse_and_validate(
    text: str, width: int, height: int, allowed: List[str]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """`(objects, malformed, parse_error)`.

    A box that fails validation is recorded with its reason and `bbox: None`, never clamped into
    looking plausible — the whole question is whether the coordinates can be trusted.
    """
    if not text.strip():
        return [], [], "empty response"
    try:
        payload = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        return [], [], f"not valid JSON: {exc}"
    if not isinstance(payload, dict) or not isinstance(payload.get("objects"), list):
        return [], [], "no 'objects' list in response"

    allowed_set = set(allowed)
    objects: List[Dict[str, Any]] = []
    malformed: List[Dict[str, Any]] = []

    for index, item in enumerate(payload["objects"]):
        if not isinstance(item, dict):
            malformed.append({"index": index, "reason": "not an object"})
            continue
        name = str(item.get("class") or "").strip()
        canonical = name if name in allowed_set else "unknown"
        raw_box = item.get("bbox")
        bbox: Optional[List[float]] = None
        reason: Optional[str] = None

        if not isinstance(raw_box, (list, tuple)) or len(raw_box) != 4:
            reason = "bbox missing or not four numbers"
        else:
            try:
                x1, y1, x2, y2 = (float(v) for v in raw_box)
            except (TypeError, ValueError):
                reason = "bbox contained a non-numeric value"
            else:
                if not all(0 <= v <= 1000 for v in (x1, y1, x2, y2)):
                    reason = "bbox outside the 0-1000 range"
                else:
                    px = [x1 / 1000 * width, y1 / 1000 * height, x2 / 1000 * width, y2 / 1000 * height]
                    if not (0 <= px[0] < px[2] <= width and 0 <= px[1] < px[3] <= height):
                        reason = "bbox degenerate after conversion"
                    else:
                        bbox = [round(v, 1) for v in px]

        record = {
            "class": canonical,
            "bbox": bbox,
            # Qwen emits prose, not a calibrated score. Never invented.
            "confidence": None,
            "description": (str(item.get("description") or "").strip() or None),
        }
        if reason:
            record["bbox_error"] = reason
            malformed.append({"index": index, "class": canonical, "reason": reason, "raw": str(raw_box)[:80]})
        objects.append(record)

    return objects, malformed, None


def run(model, processor, device: str, path: Path, prompt: str, allowed: List[str]) -> ImageResult:
    from qwen_vl_utils import process_vision_info

    with Image.open(path) as handle:
        source = handle.convert("RGB")
    original = source.size
    image = source.copy()
    image.thumbnail((MAX_EDGE, MAX_EDGE))

    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    images, videos = process_vision_info(messages)
    inputs = processor(text=[text], images=images, videos=videos, padding=True, return_tensors="pt").to(device)

    started = time.time()
    with torch.inference_mode():
        generated = model.generate(**inputs, max_new_tokens=512, do_sample=False)
    latency = time.time() - started

    trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, generated)]
    answer = processor.batch_decode(trimmed, skip_special_tokens=True)[0].strip()

    # Boxes are validated against the size the model actually saw, not the original frame.
    objects, malformed, error = parse_and_validate(answer, image.size[0], image.size[1], allowed)
    return ImageResult(
        image_id=path.stem,
        path=str(path),
        original_size=original,
        inference_size=image.size,
        latency_s=round(latency, 2),
        raw_response=answer,
        objects=objects,
        malformed=malformed,
        parse_ok=error is None,
        parse_error=error,
    )


def main() -> int:
    scratch = Path(
        "/private/tmp/claude-501/-Users-vvijwal01gmail-com-agenticAI/"
        "1f297bf6-9c74-43fe-b859-26a35e0daf0b/scratchpad"
    )
    waste_images = [
        scratch / "scale_test/bottle_C_close.jpg",
        scratch / "bottles_scene.png",
        scratch / "product_test/coke_can_indoor.png",
        scratch / "bottle_frame.png",
        REPO_ROOT / "runs/debug_waste/original/plastic_bag.jpg",
        REPO_ROOT / "runs/debug_waste/original/paper.jpg",
    ]
    water_images = sorted((REPO_ROOT / "datasets" / "Alta").glob("*.jpg"))[:2]

    device = pick_device()
    print(f"  device: {device}   dtype: float32   model: {MODEL_ID}")

    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

    started = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        MODEL_ID, dtype=torch.float32, low_cpu_mem_usage=True
    ).to(device).eval()
    load_s = time.time() - started
    print(f"  load: {load_s:.1f}s   RSS {peak_rss_gb():.2f} GB\n")

    results: List[Dict[str, Any]] = []
    for kind, paths, prompt, allowed in (
        ("waste", waste_images, WASTE_PROMPT, WASTE_CLASSES),
        ("water", water_images, WATER_PROMPT, WATER_INDICATORS),
    ):
        for path in paths:
            if not path.is_file():
                print(f"  SKIP {path.name} (missing)")
                continue
            outcome = run(model, processor, device, path, prompt, allowed)
            good = [o for o in outcome.objects if o["bbox"]]
            print(
                f"  [{kind}] {outcome.image_id:<24} {outcome.latency_s:>6.1f}s  "
                f"objects={len(outcome.objects):<2} usable_boxes={len(good):<2} "
                f"malformed={len(outcome.malformed):<2} parse_ok={outcome.parse_ok}"
            )
            for obj in outcome.objects[:4]:
                print(f"       {obj['class']:<24} bbox={obj['bbox']}  {(obj['description'] or '')[:60]}")
            if not outcome.parse_ok:
                print(f"       parse_error: {outcome.parse_error} | raw: {outcome.raw_response[:120]!r}")
            record = outcome.__dict__.copy()
            record["kind"] = kind
            results.append(record)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": "qwen_local",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "device": device,
        "dtype": "float32",
        "max_edge_px": MAX_EDGE,
        "load_seconds": round(load_s, 1),
        "peak_rss_gb": round(peak_rss_gb(), 2),
        "torch": torch.__version__,
        "python": sys.version.split()[0],
        "results": results,
    }
    (OUT_DIR / "qwen_local_results.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\n  wrote {OUT_DIR / 'qwen_local_results.json'}")
    print(f"  peak RSS: {peak_rss_gb():.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
