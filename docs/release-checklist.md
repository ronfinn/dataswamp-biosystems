# Release checklist

The exact commands run before cutting a release, in order. Every one of them has
been run against this release candidate.

Run from a clean checkout of the commit you intend to release, with a clean
working tree.

## 1. Quality gates

```bash
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pre-commit run --all-files
```

The golden-digest contract runs as part of the suite. If it fails, **stop**:
generated benchmark output has changed, published scores are no longer
comparable, and the change needs a deliberate justification and a regeneration
(see [reproducibility.md](reproducibility.md)) rather than a release.

## 2. Version consistency

One authoritative version, mirrored in exactly two places plus its test:

```bash
grep -n '^version' pyproject.toml
grep -n '__version__' src/dataswamp_biosystems/__init__.py
grep -n '__version__ ==' tests/test_package.py
```

All three must agree. Confirm `CHANGELOG.md` has an entry for this version and
that it does not describe anything the release does not do.

## 3. Build both distributions

```bash
rm -rf dist/
uv build
ls -l dist/
```

Produces a wheel and a source distribution.

## 4. Inspect the distribution contents

```bash
python -m zipfile -l dist/*.whl | grep -E '_config|_examples' | head
python -m zipfile -l dist/*.whl | grep -Ei '\.env|secret|credential|\.pyc|__pycache__|\.DS_Store' || echo "clean"
```

The wheel must contain `dataswamp_biosystems/_config/` (the canonical
configuration) and `dataswamp_biosystems/_examples/predictions/` (the example
submissions), and must contain no credential-ish, cache or scratch files. This
is also asserted by `tests/test_distribution.py`.

## 5. Clean-environment install and smoke test

```bash
uv venv --python 3.12 /tmp/dsw-release
VIRTUAL_ENV=/tmp/dsw-release uv pip install dist/*.whl
cd /tmp                                  # deliberately outside the checkout
/tmp/dsw-release/bin/dataswamp version
/tmp/dsw-release/bin/dataswamp --help
/tmp/dsw-release/bin/dataswamp validate-config
/tmp/dsw-release/bin/dataswamp validate-defects
/tmp/dsw-release/bin/dataswamp list-baselines
```

`validate-config` outside the checkout proves the packaged configuration
resolves — an installed user has no `config/` directory of their own.

## 6. The quick start, as documented

```bash
cd /tmp
/tmp/dsw-release/bin/dataswamp demo --output-dir /tmp/dsw-demo
```

Check the reported metrics match the tables in `README.md` and
`examples/README.md`.

## 7. Determinism

```bash
/tmp/dsw-release/bin/dataswamp demo --output-dir /tmp/dsw-demo-2
diff -r /tmp/dsw-demo /tmp/dsw-demo-2 && echo "byte-identical"
```

## 8. Each example submission scores as documented

From the checkout (the same files ship inside the wheel under
`dataswamp_biosystems/_examples/predictions/`):

```bash
cd /path/to/dataswamp-biosystems
for f in perfect partial unsafe; do
  /tmp/dsw-release/bin/dataswamp evaluate \
    --observed-dir /tmp/dsw-demo/generated/observed \
    --predictions examples/predictions/$f.jsonl \
    --output-dir /tmp/dsw-eval-$f --force
done
```

The numbers must match the tables in `examples/README.md`.

## 8a. Each reference baseline scores as documented

```bash
for agent in null naive-metadata rule-based; do
  /tmp/dsw-release/bin/dataswamp run-baseline --agent $agent \
    --observed-dir /tmp/dsw-demo/generated/observed \
    --output /tmp/dsw-baseline-$agent.jsonl --force \
    --evaluate --evaluation-dir /tmp/dsw-baseline-eval-$agent
done
```

The numbers must match the tables in `docs/baselines.md` and `README.md`. A
mismatch means a published baseline result has changed and the release is not
ready — regenerate deliberately with `scripts/update_baseline_scores.py` and
justify the change, rather than editing a table to fit.

## 9. Bundle and export

```bash
/tmp/dsw-release/bin/dataswamp verify-bundle /tmp/dsw-demo/bundle
/tmp/dsw-release/bin/dataswamp export-datahub \
    --bundle /tmp/dsw-demo/bundle --mode observed --output-dir /tmp/dsw-datahub --force
```

`verify-bundle` must exit 0 with every checksum recomputed. The DataHub export
must need no server, token or network.

## 10. Python API example

```bash
/tmp/dsw-release/bin/python examples/python_api_example.py /tmp/dsw-demo/bundle
```

## 11. CI

The full matrix must be green on the commit being released: `canonical` (locked
lockfile, Python 3.12 and 3.13) and `lowest-direct` (declared minimum
dependencies, Python 3.12 and 3.13).

## 12. Only then — publish

Not part of this release candidate, and deliberately not automated:

1. Resolve the open decisions listed at the top of
   [release-notes-v0.1.0-draft.md](release-notes-v0.1.0-draft.md). The
   generated-data licence is settled — CC BY-NC 4.0, see
   [ADR 0004](adr/0004-generated-data-licensing.md).
2. Set the final version and update `CHANGELOG.md`.
3. Tag the release commit.
4. Create the GitHub Release from the draft release notes.
5. Publish to PyPI, if and when that is decided.

Steps 3–5 have **not** been performed for `0.1.0rc1`.
