# ADR 0005: Talk to a live DataHub over REST from the standard library

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

The DataHub adapter shipped in v0.1.0 as an emitter: it translates a verified
benchmark bundle into Metadata Change Proposals and writes them to disk, and
hands the actual ingestion to DataHub's own tooling via a generated recipe. That
was the right scope for a first milestone, and `docs/datahub.md` recorded the
limitation honestly — "there is no live-instance ingestion, no authenticated
remote push and no round-trip read-back from a server".

Closing that gap needs two operations against a running Metadata Service:
transmit a batch of proposals, and read aspects back for comparison. There are
two ways to get them.

**Take `acryl-datahub` as a dependency.** It is the vendor's own client, it
models every aspect as a typed Python object, and it would validate payloads
against DataHub's PDL schemas rather than against our own contract.

**Call the documented REST endpoints from `urllib.request`.** The payloads
already exist — the adapter emits them, byte-for-byte pinned by committed
fixtures — so the client's entire job is to put a JSON body on the wire and
parse one back.

## Decision

**Call the REST endpoints directly, using the standard library only. Do not add
`acryl-datahub`, `requests`, `httpx` or any other client, not even as an optional
extra.**

Every endpoint path, HTTP verb, request envelope and response shape is confined
to a single module, `adapters/datahub/client.py`. Nothing in `ingest.py`,
`readback.py`, `roundtrip.py`, `normalize.py` or `report.py` knows a URL exists;
they speak in proposals, URNs and aspects. A test enforces that boundary.

## Rationale

**The package's premise is catalogue independence.** Core layers may not import
or name DataHub, and `tests/adapters/test_isolation.py` enforces it. A catalogue
client in the dependency tree — even behind an extra — makes that premise
contingent on a large transitive tree resolving, and makes the adapter's tests
contingent on it too. The whole point of the adapter is that it is testable with
no server, no network and no credentials.

**An optional extra is not free.** It multiplies the CI matrix, needs its own
lower-bound compatibility job, and creates a second code path that is exercised
less than the first. "Optional" dependencies are the ones that break quietly.

**The SDK's advantage does not apply here.** Its value would be typed
construction and PDL validation of payloads — but this adapter does not
*construct* payloads at the live stage. It transmits an already-emitted file
whose shape is pinned by committed fixtures. Re-validating those bytes through
the SDK on the way out would be checking our own fixtures against a second
source, at the cost of the entire dependency tree.

**Zero-dependency ingestion is a feature for the user.** The live path has the
same footprint as the offline one, so a `pip install dataswamp-biosystems` is
enough to push a benchmark into a catalogue. Users who prefer the vendor client
still have the generated recipe; that remains their choice, not this package's
dependency.

## What this trades away

**Payloads are validated against this adapter's contract, not DataHub's PDL
schemas.** A DataHub release that reshapes an aspect would be caught at
ingestion time, not at build time. The mitigation is not a dependency but
evidence: an optional live integration job against a pinned DataHub Quickstart
release establishes a tested compatibility point, and a documented drift policy
governs what a failure there means.

**The REST endpoints are unverified at this version.** The offline
`DATAHUB_MODEL_VERSION` range describes the emitted *payload* shape. It says
nothing about these endpoints, and it must not be read as though it did. Live
GMS support is therefore recorded as **experimental, contract-level** — in the
module, in `docs/datahub.md`, and in the `live_support` field of every emitted
round-trip report, so a stored report can never overstate the evidence behind
it.

**We maintain a small amount of protocol code.** That is the accepted cost, and
it is bounded by the isolation rule: it is one file, and a moved endpoint changes
one file.

## Consequences

- `pyproject.toml` is unchanged. The live path adds no dependency.
- `client.py` is the only module in the project that opens a socket, enforced by
  a test that also forbids endpoint strings from appearing elsewhere.
- Credentials are read from `DATAHUB_GMS_URL` / `DATAHUB_GMS_TOKEN` and nowhere
  else. The token is never a CLI argument, never in a `repr`, never in an
  exception, and never written to a file.
- The first tested real-server compatibility point is future work, tracked
  separately from the offline-provable core.
