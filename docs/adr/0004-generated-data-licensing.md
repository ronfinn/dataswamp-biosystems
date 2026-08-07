# ADR 0004: License generated benchmark data under CC BY-NC 4.0

- **Status:** Accepted
- **Date:** 2026-08-07

Supersedes the open-decision document `docs/generated-data-licensing-decision.md`,
which is removed by the change that adds this record. Closes the follow-up issue
*"Select and document generated benchmark-data licence"*.

## Context

The **software** in this repository has always been MIT-licensed. The licence for
the **data the software emits** — truth graphs, file estates, observed states,
evaluation reports and packaged benchmark bundles — was deliberately left
undesignated: bundles declared `generated_data_license: not-separately-defined`,
and the project stated the gap rather than implying a grant.

That position was tenable while nothing was published. It is not tenable for a
release. A benchmark exists to be published, cited and compared against, and
someone holding a bundle must be able to read the terms before relying on it.
Two properties of the material shaped the choice:

- It carries **no inherited obligation** — no third-party licensed dataset is
  included or referenced — and **no privacy or confidentiality constraint**,
  because every person, institution, study and identifier is fictional.
- It is **expensive to produce and easy to resell**. A benchmark corpus is
  exactly the kind of artefact a commercial vendor would fold into a paid
  product, and the project owner wants that conversation to happen explicitly.

## Decision

- **The software remains MIT.** Unchanged, unnarrowed, commercial use included.
- **The official generated benchmark datasets and bundles distributed by the
  project, from release v0.1.0 onward, are licensed under Creative Commons
  Attribution-NonCommercial 4.0 International** (SPDX `CC-BY-NC-4.0`).
- **Noncommercial research, education and AI/model/agent evaluation are
  permitted** under that licence, with attribution.
- **Commercial permission is handled separately**, granted individually by the
  project owner; `COMMERCIAL-LICENSING.md` describes the boundary.
- **The designation is prospective.** Nothing distributed before v0.1.0 is
  retroactively relicensed.
- **The project makes no claim over independently generated output.** Data a
  third party produces by running the MIT-licensed software themselves is
  outside the scope of the data licence. v0.1 does not attempt to reach it, and
  the artefacts say so.
- **No custom licence.** A bespoke "community research" licence was drafted and
  abandoned in favour of a standard, well-understood, SPDX-identified one.

## Rationale

Four requirements, and CC BY-NC 4.0 is the smallest thing that meets all of them:

- **Research accessibility** — the material must be usable by academic,
  nonprofit and independent researchers without asking anyone.
- **Attribution** — a benchmark that is cited must be citable.
- **Commercial-use reservation** — commercial exploitation of the distributed
  corpus should be a deliberate, individually-granted permission.
- **Simple standard licensing** — a widely-recognised licence with a stable
  machine-readable identifier beats a custom one nobody has read. A bespoke
  licence would have imposed a review cost on every prospective user and gained
  the project nothing that CC BY-NC 4.0 does not already provide.

Keeping the *software* MIT is what makes the noncommercial data licence
non-restrictive in practice: anyone who needs an unencumbered estate — including
a commercial user — can generate their own from the MIT generators. The data
licence is a term on the project's *distribution*, not a gate on the capability.

## Consequences

- `DATA-LICENSE.md` is the single authoritative wording;
  `src/dataswamp_biosystems/licensing.py` is its single programmatic source, and
  the file ships inside the wheel so an installed-only user can build a bundle.
- Every bundle carries a **verbatim copy** of `DATA-LICENSE.md`, so the terms
  travel with the bytes they govern. `LICENSES.md` summarises and points at it
  rather than paraphrasing it — there is one text to keep correct.
- Manifests declare `generated_data_license: CC-BY-NC-4.0` alongside
  `software_license: MIT`, plus the licence URL, the release the designation
  starts from, and the commercial-permission note. `verify-bundle` checks that
  the licensing material is present and states both licences.
- `BUNDLE_SCHEMA_VERSION` is **not** bumped. `licensing` is a free-form block and
  `generated_data_license` a free string; changing a value and adding keys to an
  open block is not a schema change, and bumping it would invalidate readers for
  no reason.
- **Bundle fingerprints change**, because bundle bytes changed. Bundles are not
  covered by the golden-digest contract, so no canonical digest is affected —
  the truth, estate and observed layers are byte-identical to before.
- The project does not describe the generated benchmark data as "open source". It
  is publicly available for noncommercial research, which is a different claim.

## Not decided here

This record states the project's licensing position. It is not legal advice, it
does not interpret CC BY-NC 4.0 beyond that licence's own terms, and it sets no
commercial pricing or contractual terms.
