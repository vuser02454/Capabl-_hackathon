# TUD-GV — visual and object-size audit

Phases 7-9. Statistics from all 1,501 images and 8,181 boxes. Qualitative findings come from
inspecting 20 rendered previews spanning 15 of the 30 sessions, object counts from 1 to 14, and
both the smallest and largest annotated objects (`previews/`, `TUDGV_CONTACT_SHEET.jpg`).

## Object-size statistics (Phase 8)

Images are native **1920x1080**, so pixel figures are directly meaningful.

| Statistic | Value |
| --- | --- |
| Median box width | **70.0 px** |
| Median box height | **68.0 px** |
| Median box area | **4,543 px²** |
| Median box aspect ratio | **1.025** (near-square) |
| Smallest boxes | 17x30, 25x25, 29x22 px |
| Largest boxes | 223x463, 226x447, 227x444 px |

| Relative area (fraction of frame) | p1 | p5 | p10 | median | p90 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | 0.049% | 0.087% | 0.118% | **0.219%** | 0.660% | 1.893% | **4.979%** |

| Tiny-object share | Count | % |
| --- | --- | --- |
| Under 1% of frame | 7,849 | **95.94%** |
| Under 0.1% of frame | 547 | 6.69% |
| Under 0.05% of frame | 86 | 1.05% |

Objects per image: min 1, median 5, mean 5.45, p90 9, p99 11, **max 14**. **No image is empty** —
there are no negative/background frames.

### The distribution is unusually tight

TUD-GV has the **highest tiny-object share** of the three datasets (95.94%) yet **not** the
smallest median. Both follow from the same fact: the camera-to-water distance is effectively
constant, so object size varies over a narrow range. The largest box in the entire dataset is
**4.98% of the frame**, against IWHR's 63.19%. There is no close-up regime here at all.

### Conceptual comparison (no training, no merging)

| | IWHR | FloW-Img | **TUD-GV** |
| --- | --- | --- | --- |
| Native frame | 1920x1080 | **640x640, stretch-resized** | 1920x1080 |
| Median relative box area | 0.847% | 0.095% | **0.219%** |
| Max relative box area | 63.195% | 7.381% | **4.979%** |
| Tiny (<1% frame) | 53.87% | 93.87% | **95.94%** |
| Median box aspect ratio | — | 0.986 | 1.025 |
| Objects per image (median) | 6 | 2 | **5** |
| Images with no objects | 0 | 0 | **0** |

TUD-GV sits between the other two on median object size but is far more **uniform** than either.
IWHR spans two capture modes with a 17x size gap between them; FloW's geometry is distorted by a
non-aspect-preserving resize; TUD-GV is one consistent viewpoint throughout.

Because FloW was stretch-resized, its **aspect-ratio** figure is not comparable with TUD-GV's.
Relative-area comparisons survive the resize; shape comparisons do not.

## Class semantics, read from the annotations (Phase 7)

`classes.txt` is 6 bytes: the literal string `litter`, with no trailing newline. One class, class
id `0`, used by all 8,181 objects. There is no material, polymer, subtype or attribute field
anywhere in the annotation format — a YOLO txt line carries only `class_id cx cy w h`.

Visual inspection confirms the name is used in its ordinary generic sense. Within a single frame
the same `litter` label is applied to:

- transparent and white plastic bags
- an orange plastic bag
- a green PET bottle and a blue/white bottle
- a white rigid container or bowl
- assorted small wrappers and foam fragments

All annotated objects observed were **anthropogenic and floating on the water surface**. Organic
surface matter visible in the same frames was **not** annotated, so the labelling is selective for
litter rather than for "anything on the surface".

> **TUD-GV is generic floating-litter detection.** The schema supports no material distinction, and
> none is inferred here. It must not be read as `plastic`, `bottle`, `bag` or `metal`, even though
> objects of all those kinds are visibly present — the annotation does not separate them.

Proportionate caveat: 20 of 1,501 frames were inspected by eye. At a median box of 70x68 px most
objects are identifiable in a full-resolution preview, which is better than FloW (20x19 px), but
this remains a sample.

## Visual domain (Phase 9)

| Property | Observation |
| --- | --- |
| **Camera angle** | **Overhead, looking down** at the water surface. No sky, no horizon, no skyline in any inspected frame |
| **Camera height** | Elevated and fixed — consistent with a bridge, pole or bank-mounted installation above the water |
| **Camera distance** | Short and near-constant, which is what produces the tight object-size distribution |
| **Water type** | Narrow inland channel or canal; a timber-piled bank revetment runs through most frames |
| **Turbidity** | Turbid throughout — green to dark olive, opaque. No clear water observed |
| **Lighting** | Daylight; both flat overcast and hard directional sun with strong cast shadows across the water |
| **Reflections / glare** | Prominent — specular ripple highlights and bright glare bands are routine, and visually resemble small pale litter |
| **Surface texture** | Persistent wind ripple; a light/dark water boundary crosses many frames |
| **Vegetation** | Bank vegetation and dry grass at the frame edge; little in-water vegetation |
| **Shoreline** | Present in most frames as a timber revetment and bare earth strip along one edge |
| **Buildings** | **None observed** |
| **People / boats / vehicles** | **None observed** in the sample |
| **Weather** | No rain, snow or fog observed; dry conditions throughout |
| **Object density** | Moderate and even — median 5, max 14 per frame |
| **Occlusion** | Partial occlusion by ripple and by the water line; objects partly submerged are still boxed |
| **Image quality** | Uniform 1920x1080 JPEG RGB, sharp, no compression artifacts noted, no EXIF |
| **Staging** | The `exp` naming, the repeated fixed viewpoint and the controlled litter density suggest **experimental releases** rather than opportunistic capture. Stated as an inference from structure, not from any documentation |

### What this means for dataset composition

The dataset is **one viewpoint, many sessions** — the opposite of IWHR, which is two very different
capture modes under one label. That uniformity is a strength for a leakage-safe split and a
limitation for generalisation: a detector trained here sees a single camera geometry, one water
type, and no sky, buildings, boats or people at all.
