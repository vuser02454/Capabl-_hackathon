"""Diagnostic mode for the waste pipeline: expose every intermediate stage.

The Waste Agent is producing wrong labels and the cause could be in any of five places. A final
label alone cannot distinguish them, because every failure looks identical from outside:

    A  the detector found the wrong thing (or nothing)
    B  the detector was right and the classifier was wrong
    C  the crop handed to the classifier was not the object
    D  preprocessing mangled the crop before the network saw it
    E  the class -> segregation mapping mislabelled a correct prediction

So this records the real values of one real run: the source image, what YOLO returned, the region
cut out of the image, **the exact tensor the network consumed**, the full probability vector, and
the taxonomy lookup applied to the winning class.

Two decisions matter for this to be worth anything:

`analyze_waste` is called normally and observed, rather than re-implemented here. A debug path that
reconstructs the pipeline can disagree with the pipeline, and then the diagnosis describes code
nobody runs.

The classifier input is written by inverting the normalisation on the captured tensor, not by
building a matching crop alongside. Case D is precisely the case where a separately-built
"equivalent" image would look right while the real one is wrong, so the real one is the only one
worth saving.

Nothing here is on the analysis path. It writes to `runs/debug_waste/` only when asked.
"""

import io
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ecosentinel.waste.debug")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEBUG_ROOT = REPO_ROOT / "runs" / "debug_waste"

#: Colours for the annotated image. Merged duplicates are drawn differently so a doubled box is
#: visible as a doubled box rather than read as two objects.
KEPT_COLOR = (45, 212, 191)
MERGED_COLOR = (250, 176, 64)


def _display_path(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise.

    Artefacts normally land in `runs/debug_waste/`, where a short path is what someone wants to
    read. A caller is free to write elsewhere, though, and a path outside the repo is not an error
    to raise — it is just a path that cannot be shortened.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_font(size: int = 15):
    from PIL import ImageFont

    for candidate in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _data_uri(image) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(_png_bytes(image)).decode("ascii")


def tensor_to_image(tensor):
    """Invert the normalisation to recover exactly what the network was shown.

    This is the classifier's literal input with the ImageNet standardisation undone — the letterbox
    padding, any resampling and any aspect distortion are all visible because they are all still in
    there. If this image does not look like the object, the fault is at or before preprocessing,
    and no amount of staring at the classifier's output will show that.
    """
    import sys

    from PIL import Image

    sys.path.insert(0, str(REPO_ROOT / "training"))
    import waste_preprocess

    array = tensor.detach().cpu()[0].clone()
    for channel, (mean, std) in enumerate(zip(waste_preprocess.MEAN, waste_preprocess.STD)):
        array[channel] = array[channel] * std + mean
    array = (array.clamp(0, 1) * 255).round().byte().permute(1, 2, 0).numpy()
    return Image.fromarray(array)


def annotate_detections(image, vision, merged_ids: Optional[set] = None):
    """Draw ONLY what YOLO returned — every raw box, before merging or classification.

    Deliberately free of classifier output. Case A has to be answerable by looking at this image
    alone, and a picture already carrying the final label cannot answer it.
    """
    from PIL import ImageDraw

    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    font = _load_font(max(13, canvas.size[0] // 60))
    merged_ids = merged_ids or set()

    for index, detection in enumerate(vision.detections, start=1):
        box = detection.bbox
        merged = id(detection) in merged_ids
        colour = MERGED_COLOR if merged else KEPT_COLOR
        draw.rectangle([box.x1, box.y1, box.x2, box.y2], outline=colour, width=3)
        label = f"{index}. {detection.class_name} {detection.confidence:.0%}"
        if merged:
            label += " (merged)"
        text_box = draw.textbbox((box.x1, max(0, box.y1 - 20)), label, font=font)
        draw.rectangle(text_box, fill=colour)
        draw.text((box.x1, max(0, box.y1 - 20)), label, fill=(6, 10, 14), font=font)
    return canvas


class WasteDebugRecorder:
    """Observer passed into `analyze_waste`. Collects the real intermediates, writes them out."""

    def __init__(self, stem: str, out_root: Path = DEBUG_ROOT, keep_images_in_memory: bool = True):
        self.stem = stem
        self.out_root = Path(out_root)
        self.keep = keep_images_in_memory
        self.records: List[Dict[str, Any]] = []
        self.original = None
        self.vision = None
        self._annotated = None

    # -- observer protocol -------------------------------------------------

    def on_image(self, image, vision) -> None:
        self.original = image
        self.vision = vision

    def on_detection(self, record, detection, bbox, crop, capture, classifier) -> None:
        """One detection, with every intermediate that produced its final label."""
        entry: Dict[str, Any] = {
            "id": record["id"],
            "detector": {
                "class": detection.class_name,
                "confidence": round(float(detection.confidence), 4),
                "bbox": [round(float(v), 1) for v in bbox],
            },
            "classifier": {
                # The raw argmax, BEFORE the confidence threshold and the non-waste gate. The
                # reported `classification` is None whenever either refused it, and a diagnosis
                # needs to see what the network actually said in order to place the blame.
                "class": None,
                "confidence": None,
            },
            "final_label": record.get("classification") or record.get("segregation"),
            "crop_path": None,
        }

        probabilities = capture.get("probabilities") if capture else None
        classes = capture.get("classes") if capture else None
        if probabilities and classes:
            top = max(range(len(probabilities)), key=lambda i: probabilities[i])
            entry["classifier"] = {
                "class": classes[top],
                "confidence": round(probabilities[top], 4),
            }
            # The runner-up matters: a correct class sitting second at 0.31 is a different problem
            # from the correct class being absent from the top five entirely.
            ranked = sorted(zip(classes, probabilities), key=lambda pair: pair[1], reverse=True)
            entry["classifier"]["top5"] = [
                {"class": name, "confidence": round(value, 4)} for name, value in ranked[:5]
            ]

        # What the pipeline reported, next to what the model said, so a gate is visible as a gate.
        entry["reported"] = {
            "classification": record.get("classification"),
            "classification_confidence": record.get("classification_confidence"),
            "candidate": record.get("candidate"),
            "segregation": record.get("segregation"),
            "status": record.get("status"),
            "label_source": record.get("label_source"),
            "message": record.get("message"),
        }

        # Stage 5: the class -> category lookup, shown as a lookup rather than folded into a label.
        predicted = (entry["classifier"] or {}).get("class")
        if predicted:
            mapping = classifier.segregation_for(predicted)
            entry["taxonomy"] = {
                "looked_up": predicted,
                "category": mapping.get("category"),
                "handling": mapping.get("handling"),
                "display": mapping.get("display"),
            }

        entry["_crop"] = crop
        entry["_input"] = None
        if capture and capture.get("tensor") is not None:
            try:
                entry["_input"] = tensor_to_image(capture["tensor"])
            except Exception:  # noqa: BLE001 - diagnostics must not break the run being diagnosed
                logger.warning("waste_debug_tensor_render_failed", exc_info=True)
        self.records.append(entry)

    # -- output ------------------------------------------------------------

    def write(self, original_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Write every artefact and return the manifest for this run."""
        originals = self.out_root / "original"
        annotated_dir = self.out_root / "detector_annotated"
        crops_dir = self.out_root / "classifier_crops"
        for directory in (originals, annotated_dir, crops_dir):
            directory.mkdir(parents=True, exist_ok=True)

        suffix = Path(filename).suffix or ".jpg"
        original_path = originals / f"{self.stem}{suffix}"
        original_path.write_bytes(original_bytes)

        merged_ids = self._merged_detection_ids()
        annotated_path = annotated_dir / f"{self.stem}.png"
        if self.original is not None and self.vision is not None:
            self._annotated = annotate_detections(self.original, self.vision, merged_ids)
            self._annotated.save(annotated_path)

        for entry in self.records:
            identifier = entry["id"]
            crop, model_input = entry.pop("_crop"), entry.pop("_input")
            if crop is not None:
                path = crops_dir / f"{self.stem}_{identifier}_crop.png"
                crop.save(path)
                # The region cut from the image, before preprocessing. Separating this from the
                # model input below is what distinguishes a bad crop (C) from bad preprocessing (D).
                entry["crop_path"] = _display_path(path)
                if self.keep:
                    entry["crop_image"] = _data_uri(crop)
            if model_input is not None:
                path = crops_dir / f"{self.stem}_{identifier}_model_input.png"
                model_input.save(path)
                entry["model_input_path"] = _display_path(path)
                if self.keep:
                    entry["model_input_image"] = _data_uri(model_input)

        manifest = {
            "stem": self.stem,
            "source_file": filename,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "original_path": _display_path(original_path),
            "detector_annotated_path": _display_path(annotated_path),
            "raw_detections": len(self.vision.detections) if self.vision else 0,
            "detections": self.records,
        }
        if self.keep:
            from PIL import Image

            manifest["original_image"] = _data_uri(Image.open(io.BytesIO(original_bytes)).convert("RGB"))
            if self._annotated is not None:
                manifest["detector_annotated_image"] = _data_uri(self._annotated)
        return manifest

    def _merged_detection_ids(self) -> set:
        """Which raw detections were absorbed as duplicates, so the drawing can mark them."""
        if self.vision is None:
            return set()
        kept_boxes = {tuple(entry["detector"]["bbox"]) for entry in self.records}
        return {
            id(detection)
            for detection in self.vision.detections
            if (round(float(detection.bbox.x1), 1), round(float(detection.bbox.y1), 1),
                round(float(detection.bbox.x2), 1), round(float(detection.bbox.y2), 1)) not in kept_boxes
        }


def debug_analyze(content: bytes, filename: str, stem: Optional[str] = None,
                  out_root: Path = DEBUG_ROOT, keep_images_in_memory: bool = True) -> Dict[str, Any]:
    """Run the real pipeline on one image and record every stage of it."""
    from services.waste import waste_pipeline

    stem = stem or Path(filename).stem or "image"
    recorder = WasteDebugRecorder(stem, out_root=out_root, keep_images_in_memory=keep_images_in_memory)
    result = waste_pipeline.analyze_waste(content, filename, observer=recorder)
    manifest = recorder.write(content, filename)
    manifest["pipeline_result"] = result
    return manifest


def write_results_index(manifests: List[Dict[str, Any]], out_root: Path = DEBUG_ROOT) -> Path:
    """Collect one or more runs into `results.json`, without the inline images."""
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    stripped = []
    for manifest in manifests:
        copy = {k: v for k, v in manifest.items() if not k.endswith("_image")}
        copy["detections"] = [
            {k: v for k, v in entry.items() if not k.endswith("_image")}
            for entry in manifest.get("detections", [])
        ]
        stripped.append(copy)
    path = out_root / "results.json"
    path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Produced by observing services.waste.waste_pipeline.analyze_waste, not by a separate "
            "debug implementation. classifier.class is the raw argmax before the confidence "
            "threshold and the non-waste gate; reported.* is what the API returned."
        ),
        "runs": stripped,
    }, indent=2))
    return path


def camelize(value: Any) -> Any:
    """snake_case keys -> camelCase, for the HTTP response only.

    The files on disk keep snake_case, because `results.json` is read by people and by scripts and
    its field names are the ones the diagnosis was specified in. Only the wire format is converted,
    so the debug payload matches the rest of the API. Values are never touched — a class name like
    `plastic_bottles` is data, not a key.
    """
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            head, *rest = key.split("_")
            out[head + "".join(word.title() for word in rest)] = camelize(item)
        return out
    if isinstance(value, list):
        return [camelize(item) for item in value]
    return value


def clear(out_root: Path = DEBUG_ROOT) -> None:
    """Remove previous artefacts so a diagnosis is never read against a stale run."""
    out_root = Path(out_root)
    if out_root.exists():
        shutil.rmtree(out_root)
