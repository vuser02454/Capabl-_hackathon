# IWHR — visual quality audit

Phase 7. Statistics from all 3,000 images and 23,689 boxes; the qualitative findings come from
inspecting rendered previews of every source group, not from the dataset's name.

Contact sheet: `IWHR_CONTACT_SHEET.jpg` (21 frames, 2 per source group, seed 1337).
Full-size annotated previews: `previews/` with `previews.json`.

## The dataset is two visually different datasets sharing one label

This is the central finding of the visual audit, and it is measurable, not impressionistic.

| Source group | Split | Images | obj/img | Median box, % of frame | Median box, px | % tiny (<1%) |
| --- | --- | --- | --- | --- | --- | --- |
| `rubbish` | train | 1,509 | 7.2 | 1.113% | 23,079 | 47.3% |
| `fishing-3` | train | 136 | 4.7 | 2.258% | 46,827 | 27.3% |
| `fishing-4` | train | 187 | 4.8 | 2.032% | 42,146 | 29.3% |
| `fishing-1` | train | 366 | 7.1 | 0.907% | 18,810 | 52.5% |
| `fishing-2` | train | 6 | 4.8 | 0.703% | 14,586 | 69.0% |
| `image` | val | 442 | 14.8 | 0.664% | 13,779 | 59.3% |
| `2022-08-18` | test | 70 | 16.0 | 0.252% | 5,234 | 87.5% |
| `2022-06-18` | test | 1 | 12.0 | 0.341% | 7,067 | 83.3% |
| `_bare_numeric` | test | 163 | 2.0 | **0.084%** | **1,740** | **97.6%** |
| `2022-07-20` | val | 108 | 5.1 | **0.066%** | **1,375** | **97.4%** |
| `5-11_mix_data` | test | 12 | 4.0 | **0.064%** | **1,335** | **100.0%** |

**The median training object is 23,079 px. The median object in three of the test/val groups is
about 1,400 px — a 17x difference in area, roughly 4x in linear size.**

Two capture modes are present:

**A. Close-up shoreline photography** (`rubbish`, `fishing-*` — 2,204 images, the whole train
component). Handheld, 1-3 m from the subject. Bottles, cans and packaging **resting on dry rock,
sand and mud**, frequently not in the water at all. Large, high-contrast, individually distinct
objects. Chinese-language packaging throughout.

**B. Fixed-camera water surveillance** (`image`, `2022-*`, `_bare_numeric`, `5-11_mix_data` —
796 images). Elevated, wide view of a canal, pond or river. Burned-in Chinese timestamp overlay
(`2022年11月01日 星期二 09:17:23`) in the top-left of many frames. Objects are small, low-contrast
patches on the water surface.

## What is actually labelled `floater`

Inspection contradicts the class name in the largest group:

- `rubbish` / `fishing-*`: **litter on dry rock and shoreline**, not floating. A glass bottle on a
  boulder, a Coke can wedged in bank vegetation, plastic packaging on dry stone.
- `image` / `2022-*`: **natural organic matter** — yellow leaf mats, algae and surface scum drifting
  on a canal. Anthropogenic litter is a minority of the boxes in these frames.
- Surveillance groups generally: diffuse debris patches whose material is unresolvable at that
  pixel size.

A model trained on this label learns "visually salient object on or beside water", which is a
legitimate and useful target. It does **not** learn "plastic waste", and its output must not be
reported as one.

## Conditions observed

| Condition | Present | Notes |
| --- | --- | --- |
| Bright daylight / hard shadows | Yes | Strong cast shadows on rock in `fishing-*`, `rubbish` |
| Overcast / flat light | Yes | Most surveillance frames |
| Specular reflections | Yes | Sky and bank reflections on still water, routinely |
| Shadows on water | Yes | Bank and vegetation shadows overlapping annotated objects |
| Vegetation | Yes | Reeds, grass, overhanging branches, bank scrub |
| Waves / surface texture | Yes | Wind ripple and wake; also mirror-still water |
| Turbid water | Yes | Brown, green and grey-green water across groups |
| Clear water | Yes | Some shallow close-ups |
| Small objects | **Dominant** | 53.9% of all boxes are under 1% of frame area |
| Large objects | Yes | Max box is 63.2% of the frame |
| Shoreline / rocks | Yes | The dominant setting of the train component |
| Boats | Yes | A boat hull appears in frame in at least one `fishing` group frame |
| Buildings / urban skyline | Yes | Apartment blocks on the far bank in wide shots |
| People | Not observed in the sample | Not asserted as absent across all 3,000 |
| Natural debris (leaves, algae, foam) | Yes — **and it is annotated as `floater`** | The defining ambiguity of this dataset |
| Timestamp overlay burned into pixels | Yes | A fixed, high-contrast artifact a detector can key on |

## Geometry

| Statistic | Value |
| --- | --- |
| Objects per image | min 1, median 6, mean 7.9, p90 16, p99 32, **max 43** |
| Images with zero objects | **0** — no negative/background frames |
| Box width (px) | min 1.0, median 157.0, max 1919.0 |
| Box height (px) | min 1.0, median 118.0, max 920.0 (median box area 17,675 px) |
| Relative area p1 / p10 / median / p90 / max | 0.016% / 0.107% / 0.847% / 6.116% / 63.195% |
| Tiny objects (<1% of frame) | **12,761 of 23,689 = 53.87%** |
| Truncated flag set | 3,829 objects (16.2%) |
| Difficult flag set | 0 |

Aspect ratios: 2,989 landscape (1.778 x2,988 and 2.182 x1), 11 portrait (0.458 x9, 0.562 x2).

Degenerate boxes are negligible and were counted rather than assumed: **1** box is 1x1 px, **3**
have a side of 2 px or less, **30** (0.13%) have a side of 8 px or less. They pass validation
because they have positive area. They are recorded, not removed — 30 boxes in 23,689 change
nothing, and deleting annotations to tidy a statistic is how a dataset stops matching its source.

## Quality concerns

1. **Annotation completeness looks inconsistent in the surveillance groups.** In turbid wide shots,
   visually similar debris patches are boxed in some places and not in others. Not quantified — it
   would need re-annotation to prove — but it means recall measured on these frames may be
   pessimistic, and unmatched detections are not automatically false positives.
2. **No negative images.** Every frame contains at least one object, so the dataset offers no
   evidence about the false-positive rate on clean water. EcoSentinel's existing reference matcher
   already has a clean-water blind spot (15-33% recall on `Baja`); IWHR does not fix it and cannot
   measure it.
3. **The timestamp overlay is a learnable shortcut**, present in one capture mode and absent in the
   other — the same mode that splits train from val/test.
4. **53.9% tiny objects** against an inference path that feeds full frames to YOLO at default
   settings. Small-object recall would need its own measurement before any claim is made.
5. **Domain mismatch between splits is forced.** The leakage-safe split necessarily puts the
   close-up litter sessions in train and the wide surveillance sessions in val/test. That is an
   honest generalisation test, but it is **not** an i.i.d. evaluation, and a low validation score
   would not by itself mean the model failed to learn.
