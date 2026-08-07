# Commercial licensing — DRAFT

> **DRAFT for project-owner and legal review. Not operative, not an offer, and
> not legal advice.** No commercial licence exists for the generated benchmark
> data today, and nothing here creates one. This document describes how
> commercial enquiries *would* be handled if the draft
> [DataSwamp Community Research License v1.0](DATASWAMP-COMMUNITY-RESEARCH-LICENSE-1.0-DRAFT.md)
> is adopted.

## The two-licence model

Data Swamp Biosystems would be distributed under two distinct licences:

| Part | Licence | Status |
| --- | --- | --- |
| **Source code** — generators, CLI, tests, tracked configuration | MIT License (`LICENSE`) | Unchanged. Fully permissive, including commercial use. |
| **Generated benchmark data** — truth graphs, file estates, observed states, evaluation reports, published bundles | DataSwamp Community Research License v1.0 (`LicenseRef-DataSwamp-Community-Research-1.0`) | Draft. Noncommercial research use permitted; commercial use requires separate permission. |

The split matters and is easy to state wrongly. **The MIT grant on the code is
not narrowed by the data licence.** A commercial organisation may read, fork,
modify, redistribute, and build products on the *software* under MIT, with no
permission from anyone. What would require permission is commercial use of the
*generated data* — the benchmark artefacts themselves.

A consequence worth being explicit about: because the generators are MIT and
deterministic, a commercial organisation can run them and produce output itself.
[LEGAL REVIEW: whether output that a third party generates by running the MIT
software on its own machine is "Licensed Material" subject to the data licence
is the central question of this model, and this draft does not resolve it. The
options are broadly (a) the data licence covers only artefacts distributed by
the project; (b) it covers all output of the software including third-party
runs, which effectively adds a field-of-use restriction on top of MIT and is in
tension with the MIT grant. This must be decided expressly before the licence
becomes operative — it determines whether the model works at all.]

## What needs a commercial licence

The uses listed in Section 5 of the draft licence: use by or on behalf of a
for-profit organisation, internal commercial benchmarking, commercial products
and services, paid benchmarking services, commercial consultancy where the
benchmark is a material component, hosted commercial benchmark services,
commercial redistribution, commercial model training and fine-tuning, commercial
AI/model/agent development and evaluation, and commercial deployment.

## What does not

- Personal, academic, nonprofit, and educational research.
- Reproducibility studies and noncommercial benchmarking.
- **Publishing benchmark results.** Anyone may publish, cite, quote, and discuss
  results — including a for-profit organisation discussing published findings.
  Section 5 restricts *use of the material*, not *discussion of findings*.
- Personal study by someone who happens to be commercially employed, outside the
  scope of that employment (draft Section 5.13).
- Anything at all involving only the **source code**, which is MIT.

## Enquiry process (draft)

1. The enquirer describes the intended use, the organisation, and the scope.
2. The licensor reviews it and decides whether to grant permission.
3. Any permission is granted **in writing** and is specific to the described
   scope. Nothing is implied, and silence is not permission.

[LEGAL REVIEW: the following are deliberately absent and must be decided by the
project owner and their adviser, not drafted by an engineer:]

- **Contact channel.** No email address or contact route is stated here, because
  inventing one would be worse than leaving it open. It must be real and
  monitored.
- **Fees and pricing.** No price, rate, tier, or fee structure is stated, and
  none should be inferred. Whether commercial permission is free-on-request,
  priced, or case-by-case is entirely undecided.
- **Contract terms.** No template agreement, no term length, no renewal,
  termination, audit, indemnity, or support obligations are drafted here.
- **Whether to grant at all.** The licensor is under no obligation to grant a
  commercial licence to anyone.

## Frequently anticipated questions (draft answers, subject to review)

**Can a company use the software?** Yes — the software is MIT and always has
been. This model would not change that.

**Can a company read a published paper that used the benchmark?** Yes, without
restriction (draft Section 5.14).

**Can a university researcher whose grant comes from industry use it?** Not
clearly answered by the current draft. [LEGAL REVIEW: industry-funded academic
research sits exactly on the Section 1.5 / 5.1 boundary — the work is done by a
nonprofit institution but may be "on behalf of" a for-profit sponsor. The
operative licence should address this case expressly rather than leaving it to
interpretation.]

**Can a company employee evaluate their employer's agent against it privately?**
No — that is internal commercial benchmarking (draft Section 5.2) and requires
permission.

**Is this open source?** No. It is source-available for the code (which is in
fact open source, under MIT) and community-licensed for the data (which is not).
The data licence restricts commercial use, so it does not meet the Open Source
Definition and must not be described as open source, as an open licence, or with
an unqualified "open".
