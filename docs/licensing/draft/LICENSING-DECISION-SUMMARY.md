# Licensing decision summary — DRAFT

> **DRAFT for project-owner and legal review. Not operative. Not legal advice.**
> Nothing in this directory is in force. `README.md`, every bundle's
> `LICENSES.md`, and the manifest field `generated_data_license:
> not-separately-defined` remain the operative position until the project owner
> approves a change deliberately. Tracked by issue #18, which this draft does
> **not** close.

## The decision in principle

| Part | Licence |
| --- | --- |
| Source code | **MIT License** — unchanged. `LICENSE` is not modified by this draft. |
| Generated benchmark data | **DataSwamp Community Research License v1.0**, identifier `LicenseRef-DataSwamp-Community-Research-1.0`. Noncommercial research use permitted with attribution; commercial use requires separate written permission. |

The licence is a **custom, source-available community licence**. It is not
OSI-approved, not a Creative Commons licence, not on the SPDX License List, and
not an open-source licence — because it restricts commercial use, it cannot be.
The `LicenseRef-` prefix is the SPDX convention for a licence that is *not* on
that list, and using it is not a claim of listing.

## Draft documents in this directory

1. [`DATASWAMP-COMMUNITY-RESEARCH-LICENSE-1.0-DRAFT.md`](DATASWAMP-COMMUNITY-RESEARCH-LICENSE-1.0-DRAFT.md)
   — the draft licence text.
2. [`COMMERCIAL-LICENSING-DRAFT.md`](COMMERCIAL-LICENSING-DRAFT.md) — how
   commercial enquiries would be handled, and what is deliberately undecided.
3. This summary, including the repository integration plan.

## Major clauses of the draft licence

| § | Clause | Substance |
| --- | --- | --- |
| 1 | Definitions | Licensor, Licensed Material, Software (expressly excluded), You, Noncommercial Purpose, For-Profit Organisation, Benchmark Results, Modified Material |
| 2 | Licensed material | Generated artefacts only; wholly synthetic; no inherited third-party obligations |
| 3 | Permitted noncommercial uses | Personal, academic, nonprofit research; education; reproducibility; noncommercial benchmarking; modification; publication of results; redistribution |
| 4 | AI/model/agent research | Evaluation, agent development, academic training and fine-tuning; §4.5 makes §5 govern any overlap |
| 5 | Commercial-use restriction | Twelve enumerated restricted uses; §5.13 carves out personal use by commercially employed individuals; §5.14 protects reading and citing published results |
| 6 | Attribution | Project, licensor, version, repository, licence name; suggested form; medium-appropriate; publication needs attribution but no permission |
| 7 | Modification and redistribution | Modified material must be clearly marked as modified and must not be presented as canonical; licence and notices travel with the material; no added restrictions; no sublicensing |
| 8 | No endorsement | No name or logo use to imply approval; factual citation permitted |
| 9 | Reservation of rights | All rights reserved; ordinary trademark reservation only; **no patent clause** (flagged) |
| 10 | Warranty disclaimer | "As is"; explicit statement that the data is fictional and not fit for clinical or regulatory use |
| 11 | Limitation of liability | Standard exclusion, subject to the unchosen governing law |
| 12 | Termination | Automatic on breach; 30-day first-breach cure; survival; downstream recipients unaffected; published results need not be retracted |
| 13 | Separate commercial licensing | Written permission only; no terms or pricing stated |
| 14 | Governing law | **Deliberately not chosen** |
| 15 | Severability | Reform-not-strike |

## Unresolved legal-review questions

These are flagged in the drafts and are **not** engineering decisions:

1. **Third-party generated output.** The generators are MIT and deterministic.
   Does data a third party generates by running the MIT software on its own
   machine fall under the data licence? This is the load-bearing question of the
   whole model — if the answer is "yes", the data licence functions as a
   field-of-use restriction layered on an MIT grant, which is in tension with
   that grant. If "no", the licence governs only artefacts the project
   distributes. The operative licence must answer this expressly.
2. **Retroactivity.** Bundles already published say, in `LICENSES.md`, to "treat
   the generated contents as covered by the same MIT terms as the software
   unless and until the project states otherwise." Whether the new licence
   applies to already-distributed bundles, or only to those built after
   adoption, must be decided and stated. Applying restrictive terms
   retroactively to material distributed under an MIT-treatment notice is the
   kind of change that needs advice rather than a code edit.
3. **Model weights and downstream reach** (draft §4.6). Does a model trained on
   the material under §4.3 carry any obligation, and may it later be deployed
   commercially?
4. **Industry-funded academic research.** Nonprofit institution, for-profit
   sponsor — squarely on the §1.5 / §5.1 boundary, and currently unanswered.
5. **Licensor identity** (§1.1). The operative version must name the licensor
   precisely. This draft asserts no legal entity or ownership structure beyond
   the existing copyright notice.
6. **Governing law and court jurisdiction** (§14). Not chosen.
7. **Patent grant or retaliation** (§9.3). Absent by design; silence should be a
   chosen position.
8. **Commercial contact channel** (§13). No email or route invented.
9. **Fees, pricing, and commercial contract terms.** Entirely undecided; no
   template agreement drafted.
10. **Liability savings clause** (§11). May be needed depending on the governing
    law chosen under §14.
11. **Enforceability of the noncommercial boundary.** "Noncommercial" is a
    definitional line that has caused real-world disputes for other licences;
    whether the §1.5 / §1.6 definitions are tight enough is a reviewer question.

## Repository integration plan — for later, once approved

**None of this is implemented in this branch, and none of it should be until the
terms are approved.**

| # | Target | Change |
| --- | --- | --- |
| 1 | `LICENSE` | **No change.** The code stays MIT. |
| 2 | New canonical licence file at repository root, e.g. `LICENSE-GENERATED-DATA` (or `LICENSES/`) | Approved licence text, promoted out of `docs/licensing/draft/`. The draft directory is then removed or archived. |
| 3 | `src/dataswamp_biosystems/bundle/builder.py::_render_licenses()` | Replace the "not separately defined … treat as MIT" paragraph with the adopted terms, a pointer to the shipped full text, and the required attribution form. Keep the software/data split explicit so no reader concludes the code became noncommercial. |
| 4 | `src/dataswamp_biosystems/bundle/builder.py::_licensing_block()` | `generated_data_license: "not-separately-defined"` → `"LicenseRef-DataSwamp-Community-Research-1.0"`. |
| 5 | Bundle contents | Ship the full licence text inside every bundle via the existing `SECTION_BUNDLE` mechanism that already carries `LICENSES.md`, so a consumer holding only a bundle directory has the terms in full. |
| 6 | Packaging (`pyproject.toml`) | Add the new licence file alongside the existing force-included `LICENSE` so an installed package carries it with no checkout. Mirrors what `examples/` and `config/` already do. |
| 7 | `README.md` | Replace the "Licensing" section's open-decision wording with the two-licence table. State plainly that the data licence is not open source, not OSI-approved, not Creative Commons, not SPDX-listed. |
| 8 | `docs/bundles.md` | Update the "Licensing" section and the `licensing` row of the manifest field table. |
| 9 | `docs/adr/0004-generated-data-license.md` | New ADR recording the decision and its rationale, superseding `docs/generated-data-licensing-decision.md`, which is then deleted (it exists only to record the gap). |
| 10 | `docs/generated-data-licensing-decision.md` | Delete, superseded by the ADR. Update every inbound link (`README.md`, issue #18, `docs/roadmap.md` / `docs/progress.md` if referenced). |
| 11 | `CHANGELOG.md` | User-visible entry: the terms under which bundles are distributed changed. Say explicitly whether it is retroactive (question 2 above). |
| 12 | `docs/release-notes-v0.1.0-draft.md` and `docs/release-checklist.md` | Note the designation in release notes; add a licence-notice check to the checklist. |
| 13 | `CLAUDE.md` | Replace the "never present generated-benchmark-data licensing as resolved" rule with the settled position, so the standing instruction matches reality. |
| 14 | Tests | Update `tests/bundle/test_builder.py` (currently asserts `generated_data_license == "not-separately-defined"`); assert the new identifier, that the full text ships in the bundle and the wheel (`tests/test_distribution.py`), and that the notice keeps the software/data split. |
| 15 | Bundle fingerprints | Notice text is bundle content, so bundle bytes and fingerprints change. Bundles are **not** covered by the golden digest contract, so no golden digest is regenerated — but any fingerprint quoted in documentation must be requoted. |
| 16 | DataHub adapter | Check whether the export manifest restates the data licence; if it does, it follows item 4. No adapter behaviour change otherwise. |

### Why `BUNDLE_SCHEMA_VERSION` need not change

`BundleManifest.licensing` is typed `dict[str, Any]`, and
`generated_data_license` is a **free string** within it. Replacing
`"not-separately-defined"` with
`"LicenseRef-DataSwamp-Community-Research-1.0"` changes the *value*, not the
schema: the key still exists, still holds a string, and every existing reader
and verifier parses it unchanged. `BUNDLE_SCHEMA_VERSION` and the committed
DataHub fixtures would only need to move if the field were converted from a free
string to a constrained vocabulary (an enum or a validated identifier set) —
which is a separate decision, and one this plan does not take. If it is ever
taken, it requires the version bump *and* fixture regeneration through
`scripts/update_datahub_fixtures.py --confirm`.

## Self-review findings

One review pass was performed against the risks the project owner named. What it
found, and what was changed in response:

1. **Permitted AI research vs prohibited commercial AI use.** The two lists
   describe overlapping *activities* distinguished only by actor and purpose,
   which is a genuine contradiction risk. Resolved by adding §4.5: where both
   could apply, §5 governs. §4.6 flags the model-weights question rather than
   answering it.
2. **Ambiguity around for-profit organisations.** "Use by a for-profit
   organisation" would otherwise sweep in an employee's evening study. Added
   §1.6 (definition including commercial arms of nonprofits) and §5.13 (personal
   use outside the scope of employment). Industry-funded academic research is
   flagged as unresolved rather than silently decided.
3. **Attribution.** Made proportionate (§6.3) so it does not become
   unsatisfiable in a figure caption, and §6.4 makes clear that publishing
   results carries no condition beyond attribution — no copyleft-by-accident on
   a researcher's paper or code.
4. **Redistribution.** §7.4–7.6 keep the licence and notices travelling with the
   material and forbid added restrictions and sublicensing; §12.4 protects
   compliant downstream recipients from an upstream breach.
5. **Modified benchmark identification.** §7.2 requires a clear modification
   notice; §7.3 additionally forbids presenting modified material as canonical
   and requires results measured against it to say so — a scientific-integrity
   concern for a benchmark, not only a licensing one.
6. **Not licensing the MIT software under the data licence.** The highest-risk
   error. §1.3 excludes the Software by definition and states that nothing in
   the licence modifies the MIT grant; §2 repeats the scope limit; the
   commercial draft leads with the split; and integration items 3 and 14 require
   the bundle notice and its test to preserve it.
7. **No false claims of OSI/CC/SPDX/open-source status.** Stated negatively and
   explicitly in the licence header, §16, the commercial draft, and this summary,
   and required of the README in integration item 7.
8. **The word "open".** The project's own description ("an open, entirely
   fictional synthetic oncology data estate") predates this and now reads
   ambiguously. Flagged for the approved-licence pass: prefer "openly published"
   or "publicly available" where availability is meant, and never "open licence"
   or an unqualified "open" for the data terms. Not changed in this branch,
   which touches no operative file.
