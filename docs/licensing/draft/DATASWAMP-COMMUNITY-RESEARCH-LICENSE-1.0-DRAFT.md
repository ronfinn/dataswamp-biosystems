# DataSwamp Community Research License v1.0 — DRAFT

> **THIS IS A DRAFT, NOT AN OPERATIVE LICENCE.**
>
> This text has not been adopted, is not in force, and grants nothing to anyone.
> It is circulated for project-owner and legal review only. Nothing in this
> document is legal advice. Until this draft is approved and the repository's
> operative licensing files are changed deliberately, the position stated in
> `README.md`, in every bundle's `LICENSES.md`, and in the manifest field
> `generated_data_license` continues to govern.
>
> Bracketed `[LEGAL REVIEW: …]` markers indicate points that were deliberately
> **not** decided in this draft and that require the project owner or their
> adviser to resolve. They are not placeholders to be filled in by an engineer.

**Machine-readable identifier:** `LicenseRef-DataSwamp-Community-Research-1.0`

This is a custom, source-available community licence. It is **not** an
open-source licence as defined by the Open Source Initiative, it is **not**
OSI-approved, it is **not** a Creative Commons licence, and it is **not** a
licence listed on the SPDX License List. The `LicenseRef-` prefix is the SPDX
convention for exactly this: an identifier for a licence that is *not* on that
list. Because this licence restricts commercial use, it does not satisfy the
Open Source Definition, and it must not be described as "open source" or as an
"open licence" anywhere in this project. (The project may still describe itself
as *openly published* or *publicly available*; those describe availability, not
licensing.)

---

## 1. Definitions

**1.1 "Licensor"** means the copyright holder of the Licensed Material as
identified in the repository's copyright notice.
[LEGAL REVIEW: the operative version must name the licensor precisely. This
draft deliberately asserts no legal entity, company, or ownership structure
beyond what the repository's existing copyright notice states.]

**1.2 "Licensed Material"** means the generated benchmark data produced by the
Data Swamp Biosystems software — including truth graphs, scientific-file
estates, observed states, defect ledgers, control partitions, adversarial
scenario answer keys, evaluation reports, and published benchmark bundles —
together with any documentation distributed as part of a benchmark bundle.

**1.3 "Software"** means the Data Swamp Biosystems source code, generators,
command-line interface, tests, and tracked configuration. **The Software is NOT
Licensed Material and is NOT governed by this Licence.** The Software remains
licensed under the MIT License as stated in the repository's `LICENSE` file.
Nothing in this Licence restricts, modifies, supersedes, or adds any condition
to the MIT grant covering the Software. Where an artefact contains both — for
example a bundle that embeds documentation generated from the source
repository — each part remains under its own licence.

**1.4 "You"** means the individual or legal entity exercising the permissions
granted by this Licence, and any entity that controls, is controlled by, or is
under common control with that entity.

**1.5 "Noncommercial Purpose"** means a purpose that is not primarily intended
for or directed toward commercial advantage or monetary compensation, and that
is not carried out by or on behalf of a For-Profit Organisation. Research,
teaching, and publication carried out by an individual acting personally, by an
accredited educational institution, or by a nonprofit research organisation is
presumed to be a Noncommercial Purpose.

**1.6 "For-Profit Organisation"** means any entity organised or operated for
profit, including a company, corporation, partnership, or sole trader acting in
that capacity, and including the for-profit subsidiary or commercial arm of an
otherwise nonprofit body.

**1.7 "Commercial Use"** means any use described in Section 5.

**1.8 "Benchmark Results"** means metrics, scores, tables, figures, analyses,
and narrative findings **derived from** evaluation against the Licensed
Material, as distinct from the Licensed Material itself.

**1.9 "Modified Material"** means Licensed Material that You have altered,
adapted, subsetted, extended, re-generated with different parameters, or
combined with other material.

---

## 2. Licensed Material

This Licence applies only to the Licensed Material as defined in Section 1.2.
It does not apply to the Software (Section 1.3), and it does not purport to
license anything the Licensor does not own.

The Licensed Material is entirely synthetic. It contains no real patient data,
no real personal data, no real biological measurements, and no confidential or
proprietary third-party content. No third-party licensed dataset is included in
or required by the Licensed Material, so no inherited third-party obligation
attaches to it.

---

## 3. Grant for permitted noncommercial uses

Subject to Your compliance with this Licence — in particular the attribution
requirements of Section 6 and the commercial-use restriction of Section 5 — the
Licensor grants You a worldwide, royalty-free, non-exclusive, revocable licence
to use, reproduce, modify, and redistribute the Licensed Material for the
following purposes:

**3.1** personal noncommercial research;

**3.2** academic research;

**3.3** nonprofit research;

**3.4** education and teaching;

**3.5** reproducibility studies, including independent regeneration and
verification of published results;

**3.6** noncommercial benchmarking;

**3.7** modification of the Licensed Material for any purpose in this Section 3;

**3.8** publication of Benchmark Results, including in papers, preprints,
theses, talks, blog posts, and public leaderboards. **Publication of Benchmark
Results is permitted without restriction as to the publisher's commercial
character** — see Section 6.4;

**3.9** redistribution of the Licensed Material, modified or unmodified, for any
purpose in this Section 3, subject to Section 7.

---

## 4. AI, model, and agent research uses

Section 3 extends expressly to AI, machine-learning, model, and agent work, so
long as that work is for a Noncommercial Purpose. Permitted uses include:

**4.1** evaluating AI models, agents, or systems against the Licensed Material;

**4.2** developing and testing data-governance, cataloguing, lineage, and data
quality agents against the Licensed Material;

**4.3** training or fine-tuning models on the Licensed Material for academic or
nonprofit research;

**4.4** publishing the resulting Benchmark Results under Section 3.8.

**4.5 Boundary between Sections 4 and 5.** Sections 4 and 5 divide the same
activities by *who is doing them and why*, not by *what technique is used*. An
identical evaluation run is permitted under Section 4 when performed for a
Noncommercial Purpose and restricted under Section 5 when performed by or on
behalf of a For-Profit Organisation or for commercial advantage. Where the two
Sections could both be read to apply to a single activity, **Section 5
governs**, and separate written permission is required.

**4.6 Model weights.** [LEGAL REVIEW: this draft does not decide whether a model
trained on the Licensed Material under Section 4.3 carries any downstream
obligation, and whether such a model may later be used commercially. The
project owner should decide expressly between (a) no downstream reach — the
restriction binds use of the Licensed Material only; (b) a stated restriction on
commercial deployment of models trained on it. This draft states neither, and
the operative version must not leave the question silent.]

---

## 5. Commercial-use restriction

The following require **separate written permission from the Licensor** and are
**not** granted by this Licence:

**5.1** use by or on behalf of a For-Profit Organisation, including use by an
employee, contractor, or agent of a For-Profit Organisation in the course of
that engagement;

**5.2** internal commercial benchmarking, including benchmarking conducted
privately within a For-Profit Organisation and never published;

**5.3** incorporation into, or use in the development of, a commercial product
or service;

**5.4** paid benchmarking services;

**5.5** commercial consultancy in which the Licensed Material is a material
component of the service delivered;

**5.6** hosted or managed commercial benchmark services;

**5.7** commercial redistribution, including distribution for a fee and
distribution as part of a paid offering;

**5.8** commercial model training;

**5.9** commercial model fine-tuning;

**5.10** commercial AI, model, or agent development;

**5.11** commercial AI, model, or agent evaluation;

**5.12** commercial deployment involving the Licensed Material.

**5.13 Individuals employed commercially.** An individual who is employed by a
For-Profit Organisation may use the Licensed Material for personal research,
study, or education carried out on their own behalf and outside the scope of
their employment. Section 5.1 restricts use *in the course of, or for the
benefit of,* that employment.

**5.14 Reading, citing, and reproducing published results is never restricted.**
Nothing in this Section restricts anyone — including a For-Profit
Organisation — from reading, citing, quoting, or reproducing published Benchmark
Results. Section 5 restricts use of the Licensed Material, not discussion of
findings about it.

**5.15** See Section 13 for how to seek permission.

---

## 6. Attribution

**6.1** Any distribution of the Licensed Material or Modified Material, and any
publication of Benchmark Results, must include an attribution notice
identifying:

- **Data Swamp Biosystems** — the project;
- the **licensor**, as identified in the repository's copyright notice;
- the **benchmark or release version**, where applicable — for example the
  bundle's release identifier or the benchmark version evaluated against;
- the **repository location**, where practical;
- **DataSwamp Community Research License v1.0**
  (`LicenseRef-DataSwamp-Community-Research-1.0`).

**6.2 Suggested form** (adapt as the medium requires):

> Generated benchmark data from Data Swamp Biosystems, © [licensor], release
> [version], [repository URL], used under the DataSwamp Community Research
> License v1.0 (`LicenseRef-DataSwamp-Community-Research-1.0`).

**6.3** Attribution must be reasonable for the medium. In a redistributed bundle
it belongs in the bundle's licensing notice file; in a paper it belongs in the
methods or acknowledgements; in a repository it belongs in the README or a
notices file. It need not appear on every page or in every figure.

**6.4** Publishing Benchmark Results requires attribution under this Section but
requires no permission and imposes no other condition. In particular, publishing
results does not oblige You to distribute the Licensed Material and does not
place any licence condition on Your paper, code, or model.

---

## 7. Modification and redistribution

**7.1** You may create and redistribute Modified Material for any purpose
permitted by Section 3.

**7.2 Modified Material must be clearly and prominently identified as
modified.** The notice must state that the material has been changed from the
Licensor's original and must not present the modification as the Licensor's own
output. Where the medium allows, state what was changed, or link to a
description.

**7.3** Modified Material must not be labelled or presented in a way that could
lead a reader to believe it is a canonical, official, or reference Data Swamp
Biosystems benchmark, unless the Licensor has agreed otherwise in writing. If
You publish Benchmark Results measured against Modified Material, say so — a
score against a modified benchmark is not comparable to a score against the
canonical one, and presenting it as such misleads readers.

**7.4** Redistribution — modified or unmodified — must carry this Licence (or a
link to it) and the attribution notice required by Section 6, so that a
downstream recipient receives the terms with the material.

**7.5** You must not apply additional restrictions to a recipient that would
prevent them exercising the rights this Licence grants them, and You must not
sublicense the Licensed Material under different terms.

**7.6** You must not remove, obscure, or alter any licensing, attribution,
provenance, or content-assurance notice contained in the Licensed Material.

---

## 8. No endorsement

This Licence grants no right to use the name "Data Swamp Biosystems",
"DataSwamp", the licensor's name, or any project name or logo to endorse,
promote, or imply approval of any product, service, publication, or result.
Factual, descriptive reference — stating that You evaluated against the
benchmark, or citing it by name — is permitted and is in fact required by
Section 6.

---

## 9. Reservation of rights

All rights not expressly granted are reserved by the Licensor.

**9.1** This Licence grants copyright and database-style rights in the Licensed
Material only, to the extent the Licensor holds them.

**9.2 Trademarks.** All trademark and name rights are reserved. This Licence
grants no trademark licence beyond the descriptive, factual use permitted by
Section 8.
[LEGAL REVIEW: this draft deliberately asserts no registered mark and claims no
trademark rights beyond an ordinary reservation.]

**9.3 Patents.** [LEGAL REVIEW: this draft contains no patent grant and no
patent-retaliation clause, deliberately. Whether the operative licence should
include either is a legal-review decision. Silence has consequences and should
be a chosen position rather than an oversight.]

---

## 10. Warranty disclaimer

THE LICENSED MATERIAL IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, ACCURACY, AND NON-INFRINGEMENT.

The Licensed Material is **entirely synthetic and fictional**. It is not real
clinical, biological, or organisational data; it does not describe any real
person, patient, institution, study, or dataset; and it must not be used for
clinical, diagnostic, regulatory, or any other real-world decision-making. Any
resemblance to a real entity is coincidental.

---

## 11. Limitation of liability

TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL THE
LICENSOR BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION
WITH THE LICENSED MATERIAL OR ITS USE OR OTHER DEALINGS IN IT.

[LEGAL REVIEW: some jurisdictions do not permit the exclusion of certain
warranties or liabilities. Whether a savings clause is needed depends on the
governing law, which this draft does not choose — see Section 14.]

---

## 12. Termination

**12.1** This Licence terminates automatically if You breach it.

**12.2** If the breach is curable and You cure it within 30 days of becoming
aware of it, Your rights are reinstated as of the cure, provided this is the
first time the Licensor has notified You of that breach.

**12.3** Sections 8 through 11 survive termination.

**12.4** Termination of Your rights does not terminate the rights of anyone who
received the Licensed Material from You and remains in compliance.

**12.5** Termination does not require You to retract or withdraw Benchmark
Results already published in compliance with this Licence.

---

## 13. Separate commercial licensing

Uses restricted by Section 5 may be permitted under a separate written agreement
with the Licensor. See `COMMERCIAL-LICENSING-DRAFT.md` for how enquiries are
handled.

No commercial terms, fees, or pricing are stated in this Licence, and none
should be inferred from it. A commercial licence exists only when the Licensor
has granted one in writing.

[LEGAL REVIEW: the contact route for commercial enquiries is not stated in this
draft. It must be a real, monitored channel chosen by the project owner.]

---

## 14. Governing law and jurisdiction

[LEGAL REVIEW: **deliberately not stated.** This draft chooses no governing law
and no court jurisdiction. Both are decisions for the project owner and their
adviser, and both depend on the licensor's actual location and legal status.]

---

## 15. Severability

If any provision of this Licence is held unenforceable, that provision shall be
reformed only to the extent necessary to make it enforceable, and the remaining
provisions shall remain in full force.

---

## 16. Version

DataSwamp Community Research License **v1.0 — DRAFT, NOT IN FORCE**.
Identifier: `LicenseRef-DataSwamp-Community-Research-1.0`.

Not OSI-approved. Not a Creative Commons licence. Not on the SPDX License List.
Not an open-source licence.
