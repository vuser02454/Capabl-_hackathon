"""Annotated previews + contact sheet for a YOLO dataset audited by audit_yolo.py.

Sampling is stratified deliberately: across source sessions, across object-count regimes and
across the filename range. A contact sheet of twenty random frames from one dense session would
show a dataset that does not exist.
"""
import argparse, json, os, random, re
from collections import defaultdict
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("--records", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--session-regex", default=r"^(exp\d+)_")
ap.add_argument("--target", type=int, default=20)
ap.add_argument("--seed", type=int, default=1337)
ap.add_argument("--max-width", type=int, default=1280)
a = ap.parse_args()

random.seed(a.seed)
doc = json.load(open(a.records))
names, recs = doc["classes"], [r for r in doc["records"] if "width" in r]
PD = os.path.join(a.out, "previews"); os.makedirs(PD, exist_ok=True)
sess = lambda s: (re.match(a.session_regex, s).group(1) if re.match(a.session_regex, s) else "_unmatched")

by_sess = defaultdict(list)
for r in recs: by_sess[sess(r["stem"])].append(r)

picked, seen = [], set()
def take(r):
    if r["stem"] not in seen:
        seen.add(r["stem"]); picked.append(r)

# one per session, largest sessions first, then extremes of object count
for s, _ in sorted(by_sess.items(), key=lambda kv: -len(kv[1])):
    if len(picked) >= a.target - 6: break
    take(random.choice(by_sess[s]))
for r in sorted(recs, key=lambda r: -len(r["objects"]))[:3]: take(r)      # densest
for r in sorted(recs, key=lambda r: len(r["objects"]))[:3]: take(r)       # sparsest
# smallest and largest single objects, so the size extremes are visible
area = lambda r: [o["cxcywh"][2] * o["cxcywh"][3] for o in r["objects"]] or [0]
for r in sorted(recs, key=lambda r: max(area(r)))[:1]: take(r)
for r in sorted(recs, key=lambda r: -max(area(r)))[:1]: take(r)

manifest = []
for r in picked[:a.target]:
    with Image.open(r["image"]) as im:
        im = im.convert("RGB"); W, H = im.size
        d = ImageDraw.Draw(im)
        for o in r["objects"]:
            cx, cy, bw, bh = o["cxcywh"]
            x1, y1, x2, y2 = (cx-bw/2)*W, (cy-bh/2)*H, (cx+bw/2)*W, (cy+bh/2)*H
            d.rectangle([x1, y1, x2, y2], outline=(255, 60, 0), width=max(2, W//640))
            d.text((x1+3, max(0, y1-13)), names[o["cls"]], fill=(255, 230, 0))
        d.text((8, 8), f'{sess(r["stem"])} | {r["stem"]} | {len(r["objects"])} obj | {W}x{H}',
               fill=(0, 255, 120))
        scale = min(W, a.max_width) / W
        out = os.path.join(PD, f'{sess(r["stem"])}__{r["stem"]}__{len(r["objects"])}obj.jpg')
        im.resize((int(W*scale), int(H*scale))).save(out, quality=88)
    manifest.append({"preview": out, "stem": r["stem"], "session": sess(r["stem"]),
                     "objects": len(r["objects"]), "size": f"{W}x{H}", "source_image": r["image"]})

cols, cell = 5, 384
th = sorted(os.listdir(PD))
th = [t for t in th if t.endswith(".jpg")]
rows = (len(th)+cols-1)//cols
sheet = Image.new("RGB", (cols*cell, rows*int(cell*9/16)), (16, 18, 22))
for i, t in enumerate(th):
    with Image.open(os.path.join(PD, t)) as im:
        sheet.paste(im.convert("RGB").resize((cell, int(cell*9/16))),
                    ((i % cols)*cell, (i//cols)*int(cell*9/16)))
sheet.save(os.path.join(a.out, "TUDGV_CONTACT_SHEET.jpg"), quality=88)
json.dump(manifest, open(os.path.join(PD, "previews.json"), "w"), indent=2)
print(f"previews={len(manifest)} sessions={len({m['session'] for m in manifest})} "
      f"obj range={min(m['objects'] for m in manifest)}-{max(m['objects'] for m in manifest)}")
