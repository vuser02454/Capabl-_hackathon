# Waste detection and segregation pipeline

Two stages, two models, two different questions:

```
image → YOLO detection → crop each box → waste classifier → segregation category
        (where is it)                     (what is it)      (biodegradable?)
```

They are kept separate deliberately. The detector currently configured is **COCO-pretrained**, so
its class names are general object labels (`bottle`, `cup`, `person`) rather than waste labels.
Asking it to assign a waste category would mean inventing classes it was never trained on. The
classifier answers that question, on a crop, from a model trained on actual waste images.

## What is and is not trained here

| Stage | Status |
| --- | --- |
| Waste **classification** (8 classes) | **Trained from `garbage_Dataset`.** Real metrics in `runs/evaluation/`, measured through the same preprocessing that is served — see below for why that sentence is necessary. |
| Waste **detection** (bounding boxes) | **Not trained.** See below. |

**`garbage_Dataset` contains no bounding-box annotations.** It is an image-classification dataset:
15,366 images in `split/category/class/` folders, and nothing else — no `labels/`, no COCO JSON, no
Pascal VOC XML. A detection model cannot be trained from it, so none was. The detection stage uses
the existing `yolov8n.pt` already configured in EcoSentinel.

To train a real waste **detector**, you need a dataset with boxes. That is a separate acquisition
step, not something this pipeline can synthesise.

## Dataset

```
garbage_Dataset/
├── train/
│   ├── biodegradable/{food_waste, leaf_waste, paper_waste, wood_waste}
│   └── non_biodegradable/{plastic_bottles, plastic_bags, metal_cans, ewaste}
└── val/   (same structure)
```

The layout was kept exactly as shipped. The scripts discover classes from the leaf directory name,
so the two-level `category/class` nesting needs no restructuring.

Note this dataset has **`ewaste`**, which the Kaggle waste-segregation class list does not, and has
**no generic `waste` class**. The taxonomy follows the data that exists.

## Reproduce

```bash
# 1. Dataset quality report (reports; deletes nothing)
python training/validate_dataset.py --dataset garbage_Dataset --out runs/dataset_report.json

# 2. Train the classifier
python training/train_waste_classifier.py --epochs 10 --batch-size 48 --workers 4

# 3. Evaluate on the held-out split
python training/evaluate_classifier.py --weights runs/classification/best.pt

# 4. Inference
python inference_waste.py --status
python inference_waste.py --source path/to/image.jpg
python inference_waste.py --source path/to/video.mp4 --stride 15
python inference_waste.py --source 0                    # webcam
```

Seeds are fixed (`--seed`, default 1337) and every run writes `runs/classification/training_manifest.json`
with the arguments, class list, device, library versions, dataset statistics and full epoch history.

## Preprocessing must be identical in training and serving

`training/waste_preprocess.py` is the single definition of how an image becomes a tensor, imported
by the training script, the evaluator **and** the backend classifier. It is a separate module
because the two sides were once written separately, drifted, and cost the served model half its
accuracy without a single metric moving.

The classifier trains on `garbage_Dataset`, whose images are roughly square full-frame photos of
one object. Validation used `Resize(short side 258)` then `CenterCrop(224)` — on a square photo
that keeps nearly everything, and it scored macro-F1 0.911.

Serving feeds it **detector crops**, which are not square: a bottle crop is typically 2.6x taller
than wide. `Resize(258)` makes that 258x680 and `CenterCrop(224)` then keeps a 224x224 patch of the
middle — about a fifth of the object, usually just the label. The shape that identifies a bottle is
discarded before the network sees a pixel.

Measured on 145 real detector crops of plastic bottles, changing nothing but the transform:

| Transform | Classified `plastic_bottles` |
| --- | --- |
| `Resize` + `CenterCrop` (what was served) | 36% |
| `Resize` to square, ignoring aspect ratio | 56% |
| Letterbox — preserve aspect, pad the short side | **87%** |

Every checkpoint now records `preprocess: "letterbox_v1"`, and the backend reports a mismatch in
`/api/waste/pipeline-status` rather than leaving it to surface as unexplained misclassification.

The lesson generalises: **an offline metric only describes the pipeline it was measured through.**
0.911 was a true number about a transform nobody served.

### Retraining under the new preprocessing made the model worse

The obvious follow-up — retrain so training and serving match exactly — was tried twice and
**rejected both times**. Measured on 392 detector crops from held-out images:

| Weights | top-1 on crops | asserted (>=60%) | of those, wrong |
| --- | --- | --- | --- |
| `runs/classification` (**served**) | **79.3%** | 278 | 27 (9.7%) |
| `runs/classification_letterbox` (letterbox_v1) | 72.2% | 281 | 42 (14.9%) |
| `runs/classification_letterbox_v2` (boxjitter_v2) | 72.7% | 289 | 38 (13.1%) |

Almost all of the gap is `ewaste`: 79/96 served against 44/96 retrained. The first attempt also had
a genuine bug — it letterboxed before `RandomResizedCrop`, so the model trained on grey padding —
and fixing that (`RandomBoxJitter`, applied to the original image first) recovered 0.5 points, not
the 7 that were missing. The augmentation fix was kept because it is correct; the weights were not,
because they are worse.

So the served combination is **not** a matched one: weights trained with `RandomResizedCrop`, served
with letterbox. It is the best of the four combinations measured, and `status()` reports that its
training preprocessing is unrecorded and therefore unverified, rather than implying it was checked.

The retrained runs are kept rather than deleted — they are the evidence for not deploying them.

## The classifier cannot say "not waste"

It has eight waste classes and a softmax that must distribute 1.0 across them, whatever it is
shown. On real TACO images it called a `dog` wood_waste at 84% confidence and a `car` food_waste at
64% — both above the 60% threshold, so **raising the threshold cannot fix this**. The model was
never given the option of abstaining.

`core.investigation.NEVER_WASTE_CLASSES` is therefore an *exclusion* list — people, animals,
vehicles, fixed street furniture — and the pipeline withholds the segregation claim when the
detector's own class is on it. The detection is still reported and the classifier's guess is kept
as `candidate`; only the assertion is withheld.

It is deliberately **not** the inverse of `POLLUTION_CLASS_HINTS`. COCO routinely calls a plastic
bottle a `vase` or a `teddy bear`; requiring membership in a waste-sounding list would discard ten
of the twenty-one correct bottle detections measured on this dataset.

A dumped car or a broken bench is litter in the ordinary sense, but neither is one of the eight
classes, so any confident label on them is wrong regardless.

## Two dataset problems the validator found, and what was done

**111 duplicate image groups across train and val.** The same image appearing in both splits turns
validation into a memorisation test — the number looks excellent until the model meets real data.
Training **excludes these from the train set** and leaves validation exactly as shipped, so the
held-out set is not quietly reshaped by whatever the training code decided to drop.

**56:1 class imbalance** (`food_waste` 10,066 vs `ewaste` 180). Unweighted, the cheapest way to cut
loss is to answer `food_waste` and be wrong about everything rare. Training uses a weighted sampler,
and the best checkpoint is selected on **macro F1**, not accuracy — on this distribution accuracy
rewards ignoring the rare classes.

Also found: 7 unusable images (5 truncated JPEGs, 2 below 32px). These are skipped and recorded;
nothing is deleted.

## Configuration

`training/config/waste_categories.json` holds the segregation mapping, the handling heuristic, and
both confidence thresholds. It is data, not code, because what counts as recyclable varies by
municipality — a hard-coded mapping quietly exports one region's rules everywhere.

Two distinct concepts live there:

- `category` — the segregation label the classifier predicts (`biodegradable` / `non_biodegradable`)
- `handling` — an **application-level policy heuristic** (`organic`, `recyclable`, `persistent`,
  `hazardous`). The model does not predict this and never sees it.

## Confidence handling

| Situation | Result |
| --- | --- |
| Classification ≥ threshold (default 0.60) | `status: confirmed`, segregation asserted |
| Classification < threshold | `status: needs_review`, `segregation: uncertain`, top class exposed as `candidate` only |
| Crop smaller than 24px | `uncertain` — too few pixels to do anything but guess |
| Detector class cannot be waste (`person`, `car`, `dog`) | `uncertain`, `needs_review`; the guess is kept as `candidate` only |
| No trained classifier | `status: unavailable` — a **missing model**, not "nothing found" |

The last row matters: "no classifier" and "no waste" produce identical object counts and mean
opposite things, so they are never collapsed.

## EcoSentinel integration

```
backend/services/waste/
├── waste_classifier.py   # stage 2: crop → class → segregation
└── waste_pipeline.py     # analyze_waste(image) → structured JSON
```

```
GET  /api/waste/pipeline-status    # which stages are available
POST /api/waste/segregate          # two-stage analysis of an uploaded image
```

`summary` reports more than a count, because a bare count hides what produced it:

| Field | Meaning |
| --- | --- |
| `total_objects` | Objects **after** merging duplicate boxes |
| `duplicate_boxes_merged` | How many boxes were folded in to get there |
| `non_waste_objects` | Detections whose class rules out waste entirely |
| `uncertain` | Counted separately, never folded into either category |

Duplicate merging exists because YOLO runs NMS **per class**, so one bottle survives twice — as
`bottle` 0.66 and `vase` 0.39 over nearly identical pixels. Left alone, one bottle is reported as
two objects, and that count is what the report and the language model build their claims on.
Merging is class-agnostic at 0.7 IoU, and the absorbed class names travel with the survivor as
`also_detected_as` rather than being discarded.

The existing waste agent, water vision service and LangGraph pipeline are untouched.

## Kaggle waste-segregation dataset

**Not downloaded.** There are no Kaggle credentials on this machine (`~/.kaggle/kaggle.json` is
absent and the `kaggle` CLI is not installed), so no attempt was made to fabricate its contents.

To add it:

```bash
pip install kaggle
mkdir -p ~/.kaggle
# Put your kaggle.json (Account → Create New API Token) at ~/.kaggle/kaggle.json
chmod 600 ~/.kaggle/kaggle.json

kaggle datasets download -d aashidutt3/waste-segregation-image-dataset -p datasets/kaggle --unzip
```

Then run `validate_dataset.py` against it **before** merging anything: it is also a classification
dataset, its class names differ from this one's (`plastic_bottles` vs `Plastic Bottles`, no
`ewaste`), and merging on assumed names would silently create duplicate or empty classes.
