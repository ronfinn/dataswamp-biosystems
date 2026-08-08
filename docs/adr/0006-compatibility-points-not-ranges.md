# ADR 0006: Compatibility is claimed as tested points, not asserted ranges

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

[ADR 0005](0005-direct-rest-datahub-client.md) chose to talk to DataHub over
REST from the standard library rather than take `acryl-datahub` as a dependency.
It named the cost explicitly: payloads are validated against this adapter's own
contract rather than DataHub's PDL schemas, so *"a DataHub release that reshapes
an aspect would be caught at ingestion time, not at build time"*. Its stated
mitigation was **evidence** — a live integration job against a pinned release,
plus a documented drift policy governing what a failure there means.

Both halves of that mitigation now exist, and building them taught two things
that ADR 0005 could not have known.

**The first live run against a real server failed, and the cause was ours.**
Ingestion posted OpenAPI-dialect aspects (`{"aspect": {"json": ...}}`) to the
rest.li endpoint `/aspects?action=ingestProposalBatch`, which deserializes an
aspect as `GenericAspect` — `value` as serialized bytes plus `contentType`.
DataHub v1.7.0 answered `HTTP 500 RequiredFieldNotPresentException: Field
"value" is required`. **111 offline tests passed throughout**, because the fake
GMS read the aspect out of whatever body arrived, so any envelope the client
chose was self-consistently correct.

**The second live run produced 4,398 discrepancies, none of which were ours.**
Every one was the server *adding* derived metadata — key aspects parsed from the
URNs we sent, materialised browse paths, denormalised copies of fields we had
already supplied. Zero of the 861 field-level differences altered a value
DataSwamp sent.

Two failures, superficially identical — a red canary — with opposite correct
responses. The first demanded a transport fix; the second demanded a
normalization-contract change. Had either been treated as the other, the result
would have been a silently broken adapter or a fidelity check that always
passes.

Meanwhile `DATAHUB_MODEL_VERSION` declares `>=0.13,<2`, a range covering dozens
of releases. Exactly one of them has ever been run.

## Decision

**A compatibility claim is backed by a named release that was actually tested,
and by nothing else. Ranges are declared targets, never evidence.**

Concretely, the project distinguishes four things that are routinely conflated,
and never lets one stand in for another:

| | What it is | What backs it |
| --- | --- | --- |
| `DATAHUB_MODEL_VERSION` | The metadata model the **emitted payload** is written *for*. A declared target. | Committed fixtures pinning the emitted bytes. Not a test against any server. |
| Emitted-payload compatibility | That `mcps.jsonl` matches DataHub's aspect shapes | Offline validator + fixtures |
| Live REST compatibility | That the **transport** works against a running GMS | The live canary, against one pinned release |
| `VERIFIED_DATAHUB_VERSION` | The one release the live path was actually run against | A green canary run, and only that |

**Widening a claim requires a run, not an argument.** `DATAHUB_MODEL_VERSION`'s
upper bound may not move because a changelog was read, a schema was inspected or
a shape "has been stable"; it moves when a tested compatibility point exists on
the other side. The same rule governs `VERIFIED_DATAHUB_VERSION`, which by
construction can only ever name one release.

**A red canary is triaged before anything is edited.** The triage produces one
of four verdicts — DataSwamp bug, server-derived metadata, upstream model
change, or infrastructure flake — and each has a different permitted response.
The decision tree, its evidentiary bar and its per-branch requirements live in
[docs/datahub.md](../datahub.md#when-the-canary-goes-red), because they are
operational procedure; what is architectural, and recorded here, is the rule
that **the verdict is chosen from evidence before a fix is chosen**, and that
normalization is never the default answer.

## Rationale

**An untested range is worse than no claim.** A user reading `>=0.13,<2`
reasonably concludes the adapter works against DataHub 0.14. Nothing establishes
that. A claim that cannot be falsified by any test in this repository is not a
guarantee, it is a guess with a version number on it — and it is exactly the
kind of guess ADR 0005 accepted responsibility for avoiding when it declined the
SDK's schema validation.

**Points compose honestly; ranges do not.** "Verified against v1.7.0" is true
forever, ages visibly, and can be extended by adding another point. "Compatible
with >=0.13,<2" silently becomes false the moment upstream changes something,
and nothing in the repository notices.

**The default response to red must not be the cheapest one.** Adding a field to
the ignore list turns any failure green in one line. Requiring a verdict first —
with an evidentiary bar and a paired test for the one branch that permits
widening — makes the cheap response reachable only when it is also the correct
one. This is the concrete defence of the property `normalize.py` was written to
protect: a fidelity check that always returns "identical" is worse than no check,
because it looks like evidence.

**Separating the axes prevents a category error.** The emitted payload and the
live transport fail independently and are fixed differently. The dialect
mismatch changed *no* payload and *no* aspect shape; it was purely a transport
bug, and classifying it as normalization drift would have widened the ignore list
to accommodate a bug in our own code.

## What this trades away

**The declared range stays broader than the evidence.**
`DATAHUB_MODEL_VERSION = ">=0.13,<2"` remains as a statement of intent about
payload shape, and only v1.7.0 sits inside it as a tested point. That gap is
documented rather than closed, because narrowing the declaration to a single
version would misrepresent the payload's actual portability in the other
direction. A test asserts the tested point lies *inside* the declared range, so
the two can never become incoherent.

**Establishing a new point costs a real CI run.** Roughly twenty minutes of
runner time and a pinned image set per release. That is the price of a claim
that means something, and it is paid weekly by a canary rather than per-PR.

**Compatibility knowledge accrues slowly.** The project will know it works
against a handful of named releases rather than asserting a broad range. This is
the intended trade.

## Consequences

- `VERIFIED_DATAHUB_VERSION`, the `live-datahub` workflow pin and the version
  documented in `docs/datahub.md` move together or not at all, enforced by
  `tests/adapters/test_live_pin.py`.
- The tested point must lie within the declared `DATAHUB_MODEL_VERSION` range,
  also enforced there.
- `live_support` in every round-trip report names the tested release rather than
  a range, so a stored report can never overstate its evidence.
- A red canary is recorded and triaged per
  [docs/datahub.md](../datahub.md#when-the-canary-goes-red); an accepted upstream
  difference is tracked as a declared rule with a justification, never as a
  suppression.
- ADR 0005's deferred "documented drift policy" is discharged by this ADR
  together with that section.
