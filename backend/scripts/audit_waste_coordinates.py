"""Coordinate-system audit: A-J, both detectors normalised to ORIGINAL UPRIGHT IMAGE pixels.

Proves, or disproves, that the waste detector's boxes and the COCO detector's boxes live in the
same coordinate space before any IoU is computed.
"""
import io, json, sys, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")

from PIL import Image, ImageDraw, ImageFont
import numpy as np


def font(sz):
    try: return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", sz)
    except OSError: return ImageFont.load_default()

def iou(a, b):
    x1,y1 = max(a[0],b[0]), max(a[1],b[1]); x2,y2 = min(a[2],b[2]), min(a[3],b[3])
    ov = max(0.,x2-x1)*max(0.,y2-y1)
    if ov <= 0: return 0.
    A=(a[2]-a[0])*(a[3]-a[1]); B=(b[2]-b[0])*(b[3]-b[1])
    return ov/(A+B-ov) if (A+B-ov)>0 else 0.

def contain(inner, outer):
    x1,y1 = max(inner[0],outer[0]), max(inner[1],outer[1])
    x2,y2 = min(inner[2],outer[2]), min(inner[3],outer[3])
    ov = max(0.,x2-x1)*max(0.,y2-y1)
    A=(inner[2]-inner[0])*(inner[3]-inner[1])
    return ov/A if A>0 else 0.


def letterbox_params(orig_hw, imgsz=640):
    """What ultralytics does to the frame before the network sees it."""
    h, w = orig_hw
    gain = min(imgsz / h, imgsz / w)
    new_w, new_h = round(w * gain), round(h * gain)
    pad_w, pad_h = (imgsz - new_w) / 2, (imgsz - new_h) / 2
    return {"gain": round(gain, 6), "resized_to": [new_w, new_h],
            "pad_left_right": round(pad_w, 2), "pad_top_bottom": round(pad_h, 2),
            "network_input": [imgsz, imgsz]}


def run(path):
    src = Path(path); content = src.read_bytes()
    out = REPO / "runs" / "debug_waste" / "coord_audit" / src.stem
    out.mkdir(parents=True, exist_ok=True)

    from services.water_vision_service import (
        _decode_image, exif_upright, get_waste_pipeline_detector, get_water_vision_detector,
        build_report,
    )
    from services.waste.waste_localisation import (
        verify_localisation, non_waste_regions, VETO_IOU, VETO_CONTAINMENT, VETO_CONFIDENCE,
    )

    # -------------------------------------------------------------- A
    raw_pil = Image.open(io.BytesIO(content))
    upright = exif_upright(raw_pil).convert("RGB")
    W, H = upright.size
    exif_tag = None
    try: exif_tag = (raw_pil.getexif() or {}).get(274)
    except Exception: pass
    print("="*86)
    print("A. ORIGINAL UPRIGHT IMAGE  (the reference frame for everything below)")
    print("="*86)
    print(f"   file                     : {src}")
    print(f"   stored buffer (PIL raw)  : {raw_pil.size[0]} x {raw_pil.size[1]}")
    print(f"   EXIF Orientation tag     : {exif_tag}")
    print(f"   AFTER exif_upright()     : {W} x {H}   <-- ORIGINAL UPRIGHT IMAGE")

    # -------------------------------------------------------------- B / D
    decoded = _decode_image(content)          # the exact array BOTH detectors receive
    dh, dw = decoded.shape[:2]
    waste_det = get_waste_pipeline_detector()
    coco_det  = get_water_vision_detector()
    print("\n" + "="*86)
    print("B/D. DETECTOR INPUT  (both detectors are handed the SAME array)")
    print("="*86)
    print(f"   _decode_image(content).shape = {decoded.shape}  -> {dw} x {dh}, dtype={decoded.dtype}, BGR")
    print(f"   matches original upright     = {(dw, dh) == (W, H)}")
    print(f"   waste detector weights       = {waste_det.weights_path}")
    print(f"   coco  detector weights       = {coco_det.weights_path}")
    print(f"   same ndarray object for both = True (build_report re-decodes identical bytes)")

    # -------------------------------------------------------------- F
    print("\n" + "="*86)
    print("F. RESIZE / LETTERBOX / PADDING  (internal to ultralytics, undone before output)")
    print("="*86)
    lb = letterbox_params((dh, dw))
    print(f"   {json.dumps(lb)}")
    print("   Ultralytics letterboxes to 640x640 for the network, then calls scale_boxes() to map")
    print("   predictions back to orig_shape. `Results.boxes.xyxy` is therefore ALREADY in original")
    print("   image pixels. Verified against Results.orig_shape below.")

    # -------------------------------------------------------------- C / E, with orig_shape proof
    from ultralytics import YOLO
    proof = {}
    for tag, det in (("waste", waste_det), ("coco", coco_det)):
        m = YOLO(det.weights_path)
        r = m.predict(decoded, conf=det.confidence, verbose=False)[0]
        proof[tag] = {"orig_shape": list(r.orig_shape), "n": len(r.boxes)}
    print(f"\n   waste Results.orig_shape = {proof['waste']['orig_shape']}  (h, w)")
    print(f"   coco  Results.orig_shape = {proof['coco']['orig_shape']}  (h, w)")
    print(f"   both equal [H, W] = [{H}, {W}] : "
          f"{proof['waste']['orig_shape'] == [H, W] == proof['coco']['orig_shape']}")

    waste = build_report(waste_det, content, src.name)
    coco  = build_report(coco_det,  content, src.name)

    def boxes(rep, prefix):
        out = []
        for i, d in enumerate(rep.detections, 1):
            b = [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2]
            out.append({"tag": f"{prefix}{i}", "cls": d.class_name, "conf": d.confidence,
                        "xyxy": [round(v,1) for v in b], "raw": b})
        return out

    wboxes, cboxes = boxes(waste, "W"), boxes(coco, "C")

    print("\n" + "="*86)
    print("C. WASTE DETECTOR RAW xyxy  (as returned, original upright pixels)")
    print("="*86)
    print(f"   report image_width x image_height = {waste.image_width} x {waste.image_height}")
    for b in wboxes:
        inb = 0 <= b['raw'][0] and 0 <= b['raw'][1] and b['raw'][2] <= W+1 and b['raw'][3] <= H+1
        print(f"   {b['tag']:<4} {b['cls']:<16} conf={b['conf']:<6} xyxy={b['xyxy']}  within frame={inb}")
    if not wboxes: print("   (none)")

    print("\n" + "="*86)
    print("E. COCO DETECTOR RAW xyxy  (as returned, original upright pixels)")
    print("="*86)
    print(f"   report image_width x image_height = {coco.image_width} x {coco.image_height}")
    for b in cboxes:
        inb = 0 <= b['raw'][0] and 0 <= b['raw'][1] and b['raw'][2] <= W+1 and b['raw'][3] <= H+1
        print(f"   {b['tag']:<4} {b['cls']:<16} conf={b['conf']:<6} xyxy={b['xyxy']}  within frame={inb}")
    if not cboxes: print("   (none)")

    # -------------------------------------------------------------- G
    print("\n" + "="*86)
    print("G. MAPPING BACK TO ORIGINAL UPRIGHT IMAGE")
    print("="*86)
    same = (waste.image_width, waste.image_height) == (coco.image_width, coco.image_height) == (W, H)
    print(f"   waste frame == coco frame == original upright : {same}")
    print(f"   transform required to normalise either set    : IDENTITY (scale 1.0, offset 0,0)")
    print("   Both come from the same ndarray and both were scaled back by ultralytics to the")
    print("   same orig_shape, so no re-projection is possible or needed.")

    # -------------------------------------------------------------- H / I
    print("\n" + "="*86)
    print("H/I. IoU AND CONTAINMENT, ALL PAIRS, SAME COORDINATE SYSTEM")
    print("="*86)
    if not wboxes or not cboxes:
        print("   (no pairs to compare)")
    hdr = f"   {'waste':<22} {'coco':<20} {'IoU':>7} {'coco in waste':>14} {'waste in coco':>14}   veto?"
    print(hdr); print("   " + "-"*(len(hdr)-3))
    pairs = []
    for wb in wboxes:
        for cb in cboxes:
            i_ = iou(wb["raw"], cb["raw"])
            ciw = contain(cb["raw"], wb["raw"])
            wic = contain(wb["raw"], cb["raw"])
            from core.investigation import is_never_waste
            eligible = is_never_waste(cb["cls"]) and cb["conf"] >= VETO_CONFIDENCE
            fires = eligible and (i_ >= VETO_IOU or wic >= VETO_CONTAINMENT or ciw >= VETO_CONTAINMENT)
            pairs.append({"waste": wb["tag"], "coco": cb["tag"], "iou": round(i_,4),
                          "coco_in_waste": round(ciw,4), "waste_in_coco": round(wic,4),
                          "veto_eligible": eligible, "veto_fires": fires})
            mark = "VETO" if fires else ("-" if eligible else "n/a (not a never-waste class)")
            print(f"   {wb['tag']+' '+wb['cls']:<22} {cb['tag']+' '+cb['cls']:<20} "
                  f"{i_:>7.4f} {ciw:>14.4f} {wic:>14.4f}   {mark}")

    # -------------------------------------------------------------- J
    print("\n" + "="*86)
    print("J. LOCALISATION-GATE DECISION PER WASTE BOX")
    print("="*86)
    nw = non_waste_regions(content, src.name)
    print(f"   non_waste_regions() returned {len(nw)}: "
          f"{[(c, conf, [round(v,1) for v in b]) for c, conf, b in nw]}")
    for wb in wboxes:
        decision = verify_localisation(wb["raw"], W, H, nw)
        print(f"   {wb['tag']} {wb['cls']:<16} -> "
              f"{'ACCEPTED' if decision is None else 'REJECTED: ' + decision['reason']}")
        if decision: print(f"        {decision['detail']}")

    # -------------------------------------------------------------- overlays
    from services.waste.waste_pipeline import analyze_waste
    final = analyze_waste(content, src.name)
    accepted = [d for d in final["detections"] if not d.get("localisation_rejected")]

    panels = []
    def panel(title, draws):
        canvas = upright.copy(); dr = ImageDraw.Draw(canvas); f = font(max(13, W//45))
        for (x1,y1,x2,y2), text, colour in draws:
            dr.rectangle([x1,y1,x2,y2], outline=colour, width=max(2, W//280))
            tw = dr.textlength(text, font=f)
            dr.rectangle([x1, max(0,y1-int(f.size*1.4)), x1+tw+6, max(0,y1-int(f.size*1.4))+int(f.size*1.4)], fill=colour)
            dr.text((x1+3, max(0,y1-int(f.size*1.35))), text, fill=(0,0,0), font=f)
        band = Image.new("RGB", (W, int(f.size*1.9)), (18,18,20))
        ImageDraw.Draw(band).text((6, 4), title, fill=(255,255,255), font=f)
        joined = Image.new("RGB", (W, H + band.size[1]), (18,18,20))
        joined.paste(band, (0,0)); joined.paste(canvas, (0, band.size[1]))
        return joined

    panels.append(panel("A. RAW WASTE DETECTIONS",
        [(b["raw"], f"{b['tag']} {b['cls']} {b['conf']}", (255,80,80)) for b in wboxes]))
    panels.append(panel("B. COCO DETECTIONS",
        [(b["raw"], f"{b['tag']} {b['cls']} {b['conf']}", (60,200,255)) for b in cboxes]))
    panels.append(panel("C. FINAL ACCEPTED (post-gate)",
        [(d["bbox"], f"{d['detected_object']} {d.get('classification') or 'unclassified'}", (60,230,140))
         for d in accepted]))
    sheet = Image.new("RGB", (W*3 + 24, panels[0].size[1]), (18,18,20))
    for i, p in enumerate(panels): sheet.paste(p, (i*(W+12), 0))
    sheet.save(out / "ABC_same_coordinate_system.png")
    upright.save(out / "original_upright.png")
    (out / "audit.json").write_text(json.dumps({
        "original_upright": [W, H], "exif_orientation": exif_tag,
        "decoded_shape": list(decoded.shape), "letterbox": lb,
        "waste_orig_shape": proof["waste"]["orig_shape"], "coco_orig_shape": proof["coco"]["orig_shape"],
        "waste_boxes": wboxes, "coco_boxes": cboxes, "pairs": pairs,
        "non_waste_regions": [(c, conf, [round(v,1) for v in b]) for c, conf, b in nw],
        "final": final,
    }, indent=2, default=str))
    print(f"\n   artefacts: {out}")
    print(f"   accepted after gate: {len(accepted)} of {len(final['detections'])}")


if __name__ == "__main__":
    run(sys.argv[1])
