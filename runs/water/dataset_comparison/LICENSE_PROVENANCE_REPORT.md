# Water datasets — license and provenance verification

Licenses verified against **authoritative source records** (Figshare API, Zenodo API, the
publishers' own pages), not against what shipped in the download. Two of the three "unknown"
licenses are now resolved.

**Ownership and relicensing rights are not inferred anywhere in this document.** Where a
re-uploader's declaration conflicts with an upstream record, both are reported and the conflict is
left open.

## Summary

| Dataset | Prior status | **Verified status** | Evidence |
| --- | --- | --- | --- |
| IWHR | None found on disk | **Apache 2.0** (dataset files) | Figshare API record, DOI `10.6084/m9.figshare.27376851.v1` |
| TUD-GV | None found on disk | **CC BY 4.0** | Zenodo API record, DOI `10.5281/zenodo.13730228` |
| FloW-Img | CC BY 4.0 declared by re-uploader | **UNRESOLVED — conflict** | Upstream is access-gated with no public licence; Roboflow re-upload declares CC BY 4.0 |

---

## IWHR — RESOLVED (Apache 2.0)

**Authoritative record:** `https://api.figshare.com/v2/articles/27376851`

| Field | Value |
| --- | --- |
| Title | IWHR_AI_Lable_Floater_V1: An annotated Dataset and Benchmark for Detecting Floating Debris in Inland Waters |
| DOI | `10.6084/m9.figshare.27376851.v1` |
| **Licence (dataset files)** | **Apache 2.0** — `https://www.apache.org/licenses/LICENSE-2.0.html` |
| Authors | Guangchao Qiao; Mingxiang Yang; Hao Wang |
| Published | 2024-11-07 |
| Citation | Qiao, Guangchao; Yang, Mingxiang; wang, Hao (2024). figshare. Dataset. https://doi.org/10.6084/m9.figshare.27376851.v1 |

The local directory name `water_datasets/27376851/` **is the Figshare article id**, which is how the
record was located. The Figshare record states **3,000 images**; the audit counted 3,000. The
associated paper states **23,692 annotated instances**; the audit's independent recount of
`<bndbox>` elements was 23,692. Both match exactly, which corroborates that the local copy is this
dataset and is complete.

### A licence distinction that must not be collapsed

| Artifact | Licence | Source |
| --- | --- | --- |
| **Dataset files** | **Apache 2.0** | Figshare record |
| **The paper** | CC BY-NC-ND 4.0 | Europe PMC record for PMID 40044696 / PMC11882902 |

The **dataset** is Apache 2.0 — permissive, commercial use allowed, no share-alike. The **article
text** is CC BY-NC-ND, which is non-commercial and no-derivatives. These govern different
artifacts. Training on the dataset is governed by the dataset licence; reproducing the paper's text
or figures is governed by the article licence. **This report does not determine which applies to a
model trained on the data** — Apache 2.0 is silent on model outputs, and that question is legal, not
technical.

### Annotation policy — now documented, previously recorded as UNKNOWN

The paper (PMC11882902) states the inclusion criterion directly:

> "floating objects made up of water plants, algae or other litter accumulations also need to be
> annotated"

and describes the content as

> "common household wastes such as plastic bottles and foam boards, as well as floating debris such
> as water plants and algae"

**This converts contradiction C1 from an inference to a documented fact.** IWHR annotates water
plants and algae as `floater` *by design*. The earlier audit reached this visually; the source now
confirms it. C1 is therefore not an artifact of sampling and cannot be resolved by re-inspection.

Additional provenance recovered: capture by "shore-based devices such as video surveillance cameras
and mobile phones" — which explains the two capture modes the audit measured — collected in 2022 on
the Grand Canal (Beiguan Barrage to Tongji Road Bridge) and the nearby Reduce Transportation Ditch,
Tongzhou District, Beijing.

**Still not documented:** whether objects on the bank or on dry land were in scope. Contradiction
**C4 remains an observed behaviour with no documented policy.**

---

## TUD-GV — RESOLVED (CC BY 4.0)

**Authoritative record:** `https://zenodo.org/api/records/13730228`

| Field | Value |
| --- | --- |
| Title | TUD-GV Dataset for Floating Litter Detection (object detection task) |
| DOI | `10.5281/zenodo.13730228` (concept record 13730227) |
| **Licence** | **`cc-by-4.0`** — Creative Commons Attribution 4.0 International |
| Creators | Tianlong Jia (TU Delft); Andre Jehan Vallendar (TU Delft); Rinze de Vries (Noria Sustainable Innovators); Zoran Kapelan (TU Delft); Riccardo Taormina (TU Delft) |
| Published | 2024-09-07 |
| Related publication | Jia et al. (2024), *Water Research* 266:122405 — `https://doi.org/10.1016/j.watres.2024.122405` |
| Files | `images.zip` (840.3 MB, 1,501 images), `labels_txt.zip` (405.7 KB, 8,181 annotations), `classes.txt` (6 bytes, "litter") |

Every structural detail matches the local audit exactly: **1,501 images, 8,181 annotations,
`labels_txt`, and a 6-byte `classes.txt`.** The 6-byte figure is an unusually specific
corroboration that the local copy is this record.

"TUD-GV" is **TU Delft — Green Village**: a field-lab drainage canal on the TU Delft campus,
Netherlands. Captured over 10 days in February and April 2021 using two action cameras (GoPro HERO4,
GoPro MAX 360) and a phone (Huawei P30 Pro) mounted at four locations on a bridge, all recording at
1080p. This confirms the audit's inferences — fixed overhead viewpoint, native 1920x1080, and the
`exp` naming denoting controlled experimental releases.

The 1,501 annotated images are a subset of a larger 9,473-image TUD-GV collection.

**CC BY 4.0 requires attribution.** Any model, publication or deployment derived from it must
credit Jia et al. and cite the DOI. That is an obligation, not a blocker.

---

## FloW-Img — UNRESOLVED (conflicting records)

Two records exist and they do not agree.

### Upstream original

| Field | Value |
| --- | --- |
| Dataset | FloW (FloW-Img + FloW-RI), ORCA Tech with Mila, Tsinghua, Northwestern Polytechnical University |
| Publication | Cheng et al., "FloW: A Dataset and Benchmark for Floating Waste Detection in Inland Waters", ICCV 2021, pp. 10953-10962 |
| Repository | `https://github.com/ORCA-Uboat/FloW-Dataset` |
| **Licence** | **None stated.** No LICENSE file, no terms-of-use text found in the repository |
| **Access** | **Gated.** Users must "apply for downloading the dataset in 'Customer Support -> Dataset -> FloW'" via the ORCA-TECH website |
| Size | **2,000 images, 5,271 labelled pieces** of floating waste |
| Class | `bottle` |
| Annotation policy | **Documented:** "the reflection of the bottle is excluded from the label area to avoid ambiguity when labeling the data" |

### The local Roboflow export

| Field | Value |
| --- | --- |
| Project | `small-objects-5irpk/flow-img`, version 2 |
| **Declared licence** | **CC BY 4.0**, in `data.yaml` and `README.dataset.txt` |
| Attribution | "Provided by a Roboflow user" — no named author, no citation, no DOI |
| Size | **1,200 images, 3,248 boxes** |

### The conflict, stated without resolving it

The upstream dataset is **access-controlled and states no public licence**. The local copy is a
re-upload by an unnamed third party declaring **CC BY 4.0**.

- The export holds **1,200 of 2,000 images (60%)** and **3,248 of 5,271 boxes (61.6%)** — it is a
  partial subset, as the audit inferred from the contiguous `000001`-`001200` stems.
- **Whether the re-uploader had the right to redistribute or to apply CC BY 4.0 is not established
  by anything available, and is not inferred here.** A licence asserted downstream of a gated
  source does not by itself transfer rights.
- The original authors are **not credited** anywhere in the export, so even taking CC BY 4.0 at
  face value, the attribution the licence requires is absent from what was delivered.

**Status: LICENCE_NOT_VERIFIED for redistribution or deployment purposes.** This is a question for
the dataset owner or legal review, not one this audit can close.

### One documented annotation fact worth carrying forward

The upstream paper states bottle **reflections are deliberately excluded** from label areas. The
earlier label-contract analysis recorded FloW's negative definition as UNKNOWN; this is one
documented exclusion. It refines but does not overturn contradiction **C2** — non-bottle litter
remains out of scope with no documented statement either way.

---

## Corrections to earlier reports

`LABEL_CONTRACTS.md` stated that **no** dataset ships annotation guidelines. That remains true of
what was *delivered on disk*, but is now too strong as a statement about the datasets themselves:

| Dataset | Annotation policy in the source literature |
| --- | --- |
| IWHR | **Documented** — water plants and algae are explicitly in scope |
| FloW-Img | **Partially documented** — bottle reflections explicitly excluded |
| TUD-GV | **Not located** — the *Water Research* paper may contain it; not retrieved here |

The negative definitions remain UNKNOWN for all three: none of these sources states what annotators
were told **not** to box, other than FloW's reflections. **Unannotated still does not mean
negative.**
