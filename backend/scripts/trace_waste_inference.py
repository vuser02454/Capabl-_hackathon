"""Trace the production waste inference path for one image.

Prints runtime model identity, every RAW detector box before classification, the production
pipeline result, and a cross-model overlap analysis (COCO yolov8n) that says WHAT each waste box
actually sits on top of. Writes artefacts to runs/debug_waste/trace/<stem>/.

Read-only with respect to the application: it calls analyze_waste, it does not re-implement it.
"""
import io, json, sys, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")

from PIL import Image, ImageDraw, ImageFont

def font(sz):
    try: return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", sz)
    except OSError: return ImageFont.load_default()

def iou(a, b):
    x1,y1 = max(a[0],b[0]), max(a[1],b[1]); x2,y2 = min(a[2],b[2]), min(a[3],b[3])
    ov = max(0.,x2-x1)*max(0.,y2-y1)
    if ov <= 0: return 0.
    A = (a[2]-a[0])*(a[3]-a[1]); B = (b[2]-b[0])*(b[3]-b[1])
    return ov/(A+B-ov) if (A+B-ov) > 0 else 0.

def contain(inner, outer):
    """Fraction of `inner` covered by `outer`."""
    x1,y1 = max(inner[0],outer[0]), max(inner[1],outer[1])
    x2,y2 = min(inner[2],outer[2]), min(inner[3],outer[3])
    ov = max(0.,x2-x1)*max(0.,y2-y1)
    A = (inner[2]-inner[0])*(inner[3]-inner[1])
    return ov/A if A > 0 else 0.

def main(image_path: str):
    src = Path(image_path)
    content = src.read_bytes()
    stem = src.stem
    out = REPO / "runs" / "debug_waste" / "trace" / stem
    out.mkdir(parents=True, exist_ok=True)
    # The same upright frame the detector and the pipeline use, so crops here are cut from the
    # pixels the boxes were drawn on.
    from services.water_vision_service import exif_upright
    image = exif_upright(Image.open(io.BytesIO(content))).convert("RGB")
    W, H = image.size

    from config import settings
    from services.water_vision_service import (
        get_waste_pipeline_detector, get_water_vision_detector, build_report, _resolve_weights
    )
    from services.waste.waste_classifier import get_waste_classifier
    from core.investigation import is_never_waste

    report = {"image": str(src), "image_size": [W, H]}

    # ---------------------------------------------------------------- 1. runtime model identity
    det = get_waste_pipeline_detector()
    weights = getattr(det, "weights_path", None)
    print("=" * 78); print("1. RUNTIME MODEL IDENTITY (production accessor)"); print("=" * 78)
    print(f"  settings.waste_detector_model_path = {settings.waste_detector_model_path!r}")
    print(f"  resolved                           = {_resolve_weights(settings.waste_detector_model_path)}")
    print(f"  detector class                     = {type(det).__name__}")
    print(f"  detector.weights_path              = {weights}")
    print(f"  detector.model (UI label)          = {getattr(det, 'model', None)}")
    print(f"  detector.confidence                = {getattr(det, 'confidence', None)}")

    from ultralytics import YOLO
    y = YOLO(weights)
    meta = {
        "weights_path": str(Path(weights).resolve()),
        "ui_label": getattr(det, "model", None),
        "task": y.task,
        "names": {int(k): v for k, v in y.names.items()},
        "nc": len(y.names),
        "conf_threshold": getattr(det, "confidence", None),
    }
    import torch
    ck = torch.load(weights, map_location="cpu", weights_only=False)
    meta["trained_from"] = (ck.get("train_args") or {}).get("model")
    meta["trained_on"] = (ck.get("train_args") or {}).get("data")
    meta["train_metrics"] = {k: round(float(v), 4) for k, v in (ck.get("train_metrics") or {}).items()}
    meta["trained_at"] = ck.get("date")
    del ck
    print(f"  model.task                         = {meta['task']}")
    print(f"  model.names ({meta['nc']})                  = {meta['names']}")
    print(f"  trained from                       = {meta['trained_from']}")
    print(f"  trained on                         = {meta['trained_on']}")
    print(f"  train metrics                      = {meta['train_metrics']}")
    report["detector"] = meta

    clf = get_waste_classifier()
    st = clf.status()
    print(f"\n  classifier weights                 = {st['weights']}")
    print(f"  classifier classes ({len(st['classes'])})           = {st['classes']}")
    print(f"  classifier threshold               = {st['threshold']}")
    print(f"  classifier detail                  = {st['detail']}")
    report["classifier"] = st

    # ---------------------------------------------------------------- 2. RAW detector output
    print("\n" + "=" * 78); print("2. RAW DETECTOR OUTPUT (before dedup, crop, classification)"); print("=" * 78)
    vision = build_report(det, content, src.name)
    raw = []
    for i, d in enumerate(vision.detections, 1):
        b = [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2]
        bw, bh = b[2]-b[0], b[3]-b[1]
        area = bw*bh/(W*H)
        raw.append({
            "n": i, "class": d.class_name, "conf": d.confidence,
            "xyxy": [round(v,1) for v in b],
            "crop_wh": [round(bw), round(bh)], "frame_fraction": round(area, 4),
            "semantic_category": d.semantic_category,
            "is_never_waste_gate_fires": is_never_waste(d.class_name),
        })
        print(f"  #{i:<2} {d.class_name:<16} conf={d.confidence:<6} xyxy={[round(v,1) for v in b]} "
              f"crop={round(bw)}x{round(bh)} frame={area:6.1%} never_waste_gate={is_never_waste(d.class_name)}")
    if not raw:
        print("  (no detections)")
    report["raw_detections"] = raw
    report["vision_status"] = vision.status
    report["vision_model_label"] = vision.model

    # ---------------------------------------------------------------- 3. cross-model: what IS it?
    print("\n" + "=" * 78); print("3. CROSS-MODEL GROUND TRUTH PROBE (COCO yolov8n, conf 0.25)"); print("=" * 78)
    coco_det = get_water_vision_detector()
    coco = build_report(coco_det, content, src.name)
    coco_boxes = []
    for i, d in enumerate(coco.detections, 1):
        b = [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2]
        coco_boxes.append({"n": i, "class": d.class_name, "conf": d.confidence, "xyxy": b})
        print(f"  C{i:<2} {d.class_name:<16} conf={d.confidence:<6} xyxy={[round(v,1) for v in b]}")
    if not coco_boxes:
        print("  (no COCO detections)")
    report["coco_detections"] = [{**c, "xyxy": [round(v,1) for v in c["xyxy"]]} for c in coco_boxes]

    print("\n  Overlap of each WASTE box with each COCO object:")
    overlaps = []
    for r in raw:
        best = []
        for c in coco_boxes:
            i_ = iou(r["xyxy"], c["xyxy"]); cv = contain(c["xyxy"], r["xyxy"]); cv2 = contain(r["xyxy"], c["xyxy"])
            if i_ > 0.05 or cv > 0.5 or cv2 > 0.5:
                best.append({"coco": c["class"], "coco_conf": c["conf"], "iou": round(i_,3),
                             "coco_inside_waste": round(cv,3), "waste_inside_coco": round(cv2,3)})
        best.sort(key=lambda x: -x["iou"])
        overlaps.append({"waste_box": r["n"], "waste_class": r["class"], "matches": best})
        label = ", ".join(f"{m['coco']}({m['coco_conf']}) IoU={m['iou']} coco⊂waste={m['coco_inside_waste']}"
                          for m in best) or "— nothing COCO recognises"
        print(f"    waste #{r['n']} '{r['class']}' ({r['conf']}) overlaps: {label}")
    report["waste_vs_coco_overlap"] = overlaps

    # ---------------------------------------------------------------- 4. production pipeline
    print("\n" + "=" * 78); print("4. PRODUCTION PIPELINE RESULT (analyze_waste — what the UI shows)"); print("=" * 78)
    from services.waste.waste_pipeline import analyze_waste
    result = analyze_waste(content, src.name)
    for d in result["detections"]:
        print(f"  {d['id']} bbox={d['bbox']}")
        print(f"      UI box label (detected_object) = '{d['detected_object']}'  det_conf={d['detection_confidence']}")
        print(f"      classification={d.get('classification')!r} conf={d.get('classification_confidence')}"
              f" candidate={d.get('candidate')!r}")
        print(f"      segregation={d.get('segregation')} status={d.get('status')} label_source={d.get('label_source')}")
        if d.get("localisation_rejected"):
            print(f"      LOCALISATION REJECTED: {d['localisation_rejected']}")
        if d.get("message"): print(f"      message: {d['message']}")
    print(f"  summary: {result['summary']}")
    print(f"  model reported to UI: {result['model']}")
    report["pipeline_result"] = result

    # ---------------------------------------------------------------- 5. classifier on controlled crops
    print("\n" + "=" * 78); print("5. CLASSIFIER-ONLY ON CONTROLLED CROPS"); print("=" * 78)
    crops = {"__full_image__": [0, 0, W, H]}
    for c in coco_boxes:
        crops[f"coco_{c['n']}_{c['class']}"] = c["xyxy"]
    for r in raw:
        crops[f"wastebox_{r['n']}_{r['class']}"] = r["xyxy"]
    controlled = {}
    for name, box in crops.items():
        region = image.crop((int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        if min(region.size) < 24:
            controlled[name] = {"skipped": "crop below MIN_CROP_PIXELS"}; continue
        cap = {}
        rec = clf.classify(region, capture=cap)
        probs = sorted(zip(cap.get("classes", []), cap.get("probabilities", [])), key=lambda x: -x[1])[:3]
        controlled[name] = {"box": [round(v,1) for v in box], "crop_wh": list(region.size),
                            "classification": rec.get("classification"),
                            "confidence": rec.get("classification_confidence"),
                            "candidate": rec.get("candidate"),
                            "top3": [(c, round(p,4)) for c, p in probs]}
        print(f"  {name:<34} {region.size[0]:>4}x{region.size[1]:<4} -> "
              f"{rec.get('classification') or ('~'+str(rec.get('candidate')))} "
              f"top3={[(c, round(p,3)) for c,p in probs]}")
        region.save(out / f"crop_{name}.png")
    report["controlled_crops"] = controlled

    # ---------------------------------------------------------------- artefacts
    ann = image.copy(); draw = ImageDraw.Draw(ann); f = font(max(14, W//55))
    for r in raw:
        x1,y1,x2,y2 = r["xyxy"]
        draw.rectangle([x1,y1,x2,y2], outline=(255,80,80), width=max(2, W//350))
        t = f"W{r['n']} {r['class']} {r['conf']}"
        draw.rectangle([x1, max(0,y1-22), x1+len(t)*8, max(0,y1-22)+20], fill=(255,80,80))
        draw.text((x1+3, max(0,y1-21)), t, fill=(0,0,0), font=f)
    for c in coco_boxes:
        x1,y1,x2,y2 = c["xyxy"]
        draw.rectangle([x1,y1,x2,y2], outline=(60,200,255), width=max(2, W//400))
        t = f"C{c['n']} {c['class']} {c['conf']}"
        draw.text((x1+3, min(H-16, y2+2)), t, fill=(60,200,255), font=f)
    ann.save(out / "A_raw_detector_vs_coco.png")
    image.save(out / "original.png")
    (out / "trace.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nArtefacts: {out}")

if __name__ == "__main__":
    main(sys.argv[1])
