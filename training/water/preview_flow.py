"""Annotated previews + contact sheet for the Flow-Img export."""
import json, os, random
from PIL import Image, ImageDraw

recs = json.load(open("runs/water/flow_integration/_records.json"))["records"]
O = "runs/water/flow_integration"
PD = os.path.join(O, "previews")
os.makedirs(PD, exist_ok=True)
random.seed(1337)

# Spread the sample across the numbering range and across object-count regimes,
# so the sheet is not accidentally all sparse frames.
recs_sorted = sorted(recs, key=lambda r: r["stem"])
spread = [recs_sorted[i] for i in range(0, len(recs_sorted), len(recs_sorted) // 12)][:12]
dense = sorted(recs, key=lambda r: -len(r["objects"]))[:4]
sparse = [r for r in recs if len(r["objects"]) == 1][:4]
picked, seen = [], set()
for r in spread + dense + sparse:
    if r["stem"] not in seen:
        seen.add(r["stem"]); picked.append(r)

manifest = []
for r in picked:
    with Image.open(r["image"]) as im:
        im = im.convert("RGB"); W, H = im.size
        d = ImageDraw.Draw(im)
        for o in r["objects"]:
            cx, cy, bw, bh = o["cxcywh"]
            x1, y1 = (cx - bw/2)*W, (cy - bh/2)*H
            x2, y2 = (cx + bw/2)*W, (cy + bh/2)*H
            d.rectangle([x1, y1, x2, y2], outline=(255, 60, 0), width=2)
            d.text((x1+2, max(0, y1-11)), "bottle", fill=(255, 230, 0))
        d.text((6, 6), f'{r["stem"][:14]} | {len(r["objects"])} obj | {W}x{H}', fill=(0, 255, 120))
        out = os.path.join(PD, f'{r["stem"][:14]}_{len(r["objects"])}obj.jpg')
        im.save(out, quality=90)
    manifest.append({"preview": out, "stem": r["stem"], "objects": len(r["objects"]), "size": f"{W}x{H}",
                     "source_image": r["image"]})

cols, cell = 5, 384
th = sorted(os.listdir(PD))
rows = (len(th)+cols-1)//cols
sheet = Image.new("RGB", (cols*cell, rows*cell), (16, 18, 22))
for i, t in enumerate(th):
    with Image.open(os.path.join(PD, t)) as im:
        sheet.paste(im.convert("RGB").resize((cell, cell)), ((i % cols)*cell, (i//cols)*cell))
sheet.save(os.path.join(O, "FLOW_CONTACT_SHEET.jpg"), quality=88)
json.dump(manifest, open(os.path.join(PD, "previews.json"), "w"), indent=2)
print(f"previews={len(manifest)} objects range={min(m['objects'] for m in manifest)}-{max(m['objects'] for m in manifest)}")
