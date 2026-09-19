"""Annotated previews and a contact sheet, so the dataset can be inspected by eye."""
import argparse, csv, json, os, random
from collections import defaultdict
from PIL import Image, ImageDraw
Image.MAX_IMAGE_PIXELS = None

ap = argparse.ArgumentParser()
ap.add_argument("--dataset", default="datasets/water/IWHR_AI_Lable_Floater_V1_yolo")
ap.add_argument("--out", default="runs/water/iwhr_integration")
ap.add_argument("--per-group", type=int, default=2)
ap.add_argument("--seed", type=int, default=1337)
a = ap.parse_args()

random.seed(a.seed)
prev_dir = os.path.join(a.out, "previews")
os.makedirs(prev_dir, exist_ok=True)
rows = list(csv.DictReader(open(os.path.join(a.dataset, "provenance.csv"))))
by_group = defaultdict(list)
for r in rows: by_group[r["source_group"]].append(r)

picked = []
for g in sorted(by_group):
    picked += random.sample(by_group[g], min(a.per_group, len(by_group[g])))

names = {}
for line in open(os.path.join(a.dataset, "data.yaml")):
    s = line.strip()
    if s[:1].isdigit() and ":" in s:
        k, v = s.split(":", 1); names[int(k)] = v.strip()

manifest = []
for r in picked:
    ipath = os.path.join(a.dataset, "images", r["split"], r["yolo_stem"] + ".jpg")
    lpath = os.path.join(a.dataset, "labels", r["split"], r["yolo_stem"] + ".txt")
    with Image.open(ipath) as im:
        im = im.convert("RGB"); W, H = im.size
        d = ImageDraw.Draw(im)
        n = 0
        for line in open(lpath):
            if not line.strip(): continue
            c, cx, cy, bw, bh = line.split()
            cx, cy, bw, bh = float(cx)*W, float(cy)*H, float(bw)*W, float(bh)*H
            x1, y1, x2, y2 = cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2
            d.rectangle([x1, y1, x2, y2], outline=(255, 60, 0), width=max(2, W//480))
            d.text((x1+3, max(0, y1-14)), names.get(int(c), c), fill=(255, 230, 0))
            n += 1
        d.text((8, 8), f'{r["source_group"]} | {r["split"]} | {n} floater | {W}x{H} | {r["internal_filename"]}',
               fill=(0, 255, 120))
        out = os.path.join(prev_dir, f'{r["source_group"]}__{r["yolo_stem"]}.jpg')
        im.copy().resize((min(W, 1280), int(H*min(W,1280)/W))).save(out, quality=86)
    manifest.append({"preview": os.path.relpath(out), "source_group": r["source_group"],
                     "split": r["split"], "objects": n, "size": f"{W}x{H}",
                     "original_image": r["original_image"], "internal_filename": r["internal_filename"]})

# contact sheet
cols, cell = 5, 384
thumbs = sorted(os.listdir(prev_dir))
rowsn = (len(thumbs)+cols-1)//cols
sheet = Image.new("RGB", (cols*cell, rowsn*int(cell*9/16)), (16, 18, 22))
for i, t in enumerate(thumbs):
    with Image.open(os.path.join(prev_dir, t)) as im:
        im = im.convert("RGB").resize((cell, int(cell*9/16)))
        sheet.paste(im, ((i % cols)*cell, (i//cols)*int(cell*9/16)))
sheet.save(os.path.join(a.out, "IWHR_CONTACT_SHEET.jpg"), quality=88)
json.dump(manifest, open(os.path.join(prev_dir, "previews.json"), "w"), indent=2)
print(f"previews={len(manifest)} contact_sheet={os.path.join(a.out,'IWHR_CONTACT_SHEET.jpg')}")
print(f"groups covered: {sorted({m['source_group'] for m in manifest})}")
