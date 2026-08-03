# Contributing

Contributions, discussions, bug reports and feature proposals are welcome. This
is a small project — the process below is deliberately light, and describes the
tooling that actually exists rather than a process for a large team.

Before starting a substantial change, please open an issue describing the
problem or use case, the proposed behaviour, the expected output, any relevant
scientific or metadata standard, and how the change could be tested.

## Development setup

Requires Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ronfinn/dataswamp-biosystems.git
cd dataswamp-biosystems
uv sync                       # install the locked environment
uv run dataswamp --help
uv run pre-commit install     # optional: run the hooks on every commit
```

`uv sync --frozen` installs exactly the committed lockfile and is what CI uses.
Use it when you want to reproduce a CI result locally.

## The quality gates

All five must pass with zero errors before a change is complete. CI runs the
same commands.

```bash
uv run --frozen pytest              # the complete suite
uv run --frozen ruff check .        # lint
uv run --frozen ruff format --check .
uv run --frozen mypy src            # strict, no exceptions
uv run --frozen pre-commit run --all-files
```

Useful subsets while iterating:

```bash
uv run pytest tests/observed                      # one layer
uv run pytest tests/test_cli.py::test_version_command_exits_successfully
uv run pytest -m "not slow"                       # skip full-profile generation
uv run pytest tests/test_golden.py                # the determinism contract
```

New code needs tests covering its behaviour. For anything that generates output,
that means explicit tests for determinism (same seed → identical bytes), record
counts and referential integrity — not just that it runs.

## The rules that are not negotiable

These are enforced by tests, and a change that breaks one is an architectural
change, not a bug fix:

* **Synthetic data only.** Every person, institution, study, dataset and
  identifier must be fictional and synthetically generated. Fictional identities
  use the `dataswamp.example` domain. Never import, reference or derive from real
  clinical, patient or proprietary data — if a task seems to require it, stop and
  raise the concern.
* **No catalogue in a core layer.** `company/`, `truth/`, `estate/`,
  `observed/`, `evaluation/` and `bundle/` must never import or name DataHub.
  The adapter depends on them, never the reverse.
  (`tests/adapters/test_isolation.py`)
* **No catalogue client as a dependency.** The adapter emits documented payload
  shapes and is testable with no server, no network and no credentials.
* **The observed layer never mutates the truth graph**, and the evaluator never
  regenerates or rewrites ground truth.
* **Never report an undefined metric as zero**, and never widen a rule's
  denominator with entities outside its population.
* **No non-determinism in generator code** — no wall-clock time, no unseeded
  randomness, no reliance on unordered set or dict iteration for output order.
* **Never commit generated output.** Everything under `generated/` is ignored.
* **Do not "fix" injected defects.** They are test fixtures, not bugs.

## Common tasks

### Adding a defect rule

1. Add a `DefectDef` to the in-code registry in
   `src/dataswamp_biosystems/observed/defects.py`, with its category, severity,
   target fields, mutation, expected finding and full remediation contract
   (`action_class`, availability, approval policy, approver role).
2. Implement its mutation in the engine if no existing mutation fits.
3. Give it a per-profile injection rate in
   `src/dataswamp_biosystems/observed/profiles.py`.
4. `uv run dataswamp validate-defects` — the registry validator checks contract
   coverage and required states, and will tell you what is missing.
5. Add tests under `tests/observed/`: that the rule fires, that its expected
   finding and remediation are emitted, and that its control exclusions land in
   `rule-scope.jsonl`.
6. Regenerate the golden digests (below) and the example submissions — a new
   rule changes the canonical scenario's bytes and its published example scores.

See [docs/observed-state.md](docs/observed-state.md).

### Adding a schema field

1. Add the field to the entity model, with a default that keeps existing
   documents valid if the change is meant to be backward-compatible.
2. Decide whether it is a **breaking** change. If a reader of the previous
   version would misinterpret the new document, bump that layer's
   `*_SCHEMA_VERSION` and update `SUPPORTED_*_SCHEMA_VERSIONS`.
3. Update the layer's serializer, validator and documentation together — a field
   that is written but not validated is worse than no field.
4. Update the DataHub mapping if the field should surface in a catalogue, and
   regenerate the adapter fixtures.
5. Regenerate the golden digests and note the change in `CHANGELOG.md`.

### Regenerating the golden digests

The committed digests in `tests/golden/canonical-digests.json` pin the canonical
scenario's bytes. **`pytest` never rewrites them.** Regenerate deliberately:

```bash
uv run --frozen python scripts/update_golden_digests.py \
    --confirm --reason "..." --cause "..."
```

Then follow the reviewer checklist in
[docs/reproducibility.md](docs/reproducibility.md). A golden change in a pull
request needs an explicit justification: it means generated benchmark output
changed, which means published scores are no longer comparable.

### Regenerating the DataHub fixtures

```bash
uv run --frozen python scripts/update_datahub_fixtures.py --confirm --reason "..."
```

### Regenerating the example submissions

```bash
uv run --frozen python scripts/update_example_predictions.py --confirm
```

Then update the score tables in `examples/README.md` and `README.md` to match.

## Release checklist

See [docs/release-checklist.md](docs/release-checklist.md) for the exact
commands run before a release, including the package build and clean-install
smoke test.

## Reporting a security issue

Do not open a public issue for a vulnerability — see [SECURITY.md](SECURITY.md).

## Pull requests

* Branch from `main`; keep the change focused and avoid unrelated refactoring.
* Stage intended files explicitly; never commit generated output, `.env` files,
  credentials or scratch files.
* Say in the description what changed in generated bytes, if anything, and why.
* CI must be green before merge. Do not bypass checks.
