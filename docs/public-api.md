# Public API and stability

What this project promises to keep working at v0.1, what it does not, and where
the boundary is. The honest summary: **the CLI, the on-disk artefact formats and
a small set of Python entry points are the supported surface. Everything else is
implementation.**

## Stability tiers

| Tier | What it means |
| --- | --- |
| **Stable** | Intended to keep working across v0.1.x. A breaking change needs a version bump and a changelog entry. |
| **Experimental** | Real and documented, but the shape may change without a major bump. Pin a version if you depend on it. |
| **Internal** | Not a public interface. It may change or disappear in any release, even if importable. |

Because the project is at a release *candidate*, "stable" means *intended to be
stable* — the contract begins at the v0.1.0 release, not before it.

## Stable: the command-line interface

The documented workflow, in order:

```text
validate-config
generate-truth      validate-truth
generate-files      validate-files
inject-defects      validate-observed
evaluate
build-bundle        verify-bundle
export-datahub
demo
```

Plus `version`, `list-defects`, `validate-defects`, `list-baselines` and
`run-baseline`.

Stable per command: the command name, its options, and its **exit codes** —
`0` success, `1` the input was read but is invalid (failed validation, a
contract violation), `2` a usage or I/O problem (an input could not be read, an
unsafe or non-empty output directory). Scripts should branch on exit codes, not
on message text: human-readable output may be reworded.

## Stable: on-disk formats

These are the real interoperability surface — most consumers should read files,
not import Python.

| Artefact | Versioned by |
| --- | --- |
| Truth graph shards + manifest | `truth_schema_version` |
| Estate manifest + sidecars | `estate_schema_version` |
| Observed ledgers, controls, rule scope | `observed_schema_version` |
| Prediction submissions | `schema_version` (currently `1`) |
| Evaluation reports | `evaluation_schema_version` |
| Bundle manifest + checksums | `bundle_schema_version` |
| DataHub Metadata Change Proposals | `DATAHUB_MODEL_VERSION` |

Each declares its own version, and a reader that meets an unsupported version is
told so rather than best-effort parsing it.

## Stable: Python entry points

```python
# Reading and verifying a bundle — the recommended way to consume a benchmark.
from dataswamp_biosystems.bundle import (
    BundleReader, Layer, BundleManifest, verify_bundle,
    BundleError, BundleConfigError, BundleValidationError,
)

# Parsing and scoring predictions.
from dataswamp_biosystems.evaluation import (
    Prediction, PredictedRemediation, PREDICTION_SCHEMA_VERSION,
    parse_predictions, load_predictions,
    GroundTruth, load_ground_truth,
    evaluate, prediction_digest, write_evaluation,
    EvaluationError, EvaluationConfigError, PredictionValidationError,
)

# Running a reference baseline agent against an observed state.
from dataswamp_biosystems.baselines import (
    BASELINE_NAMES, BaselineAgent, BaselineInfo, BaselineRun,
    ObservedInput, get_baseline, baseline_infos,
    run_baseline, render_predictions, write_predictions,
    BaselineError, UnknownBaselineError, ObservedInputError,
)

# Emitting DataHub metadata from a verified bundle.
from dataswamp_biosystems.adapters.datahub import ExportMode, export_datahub

# The package version.
from dataswamp_biosystems import __version__
```

A worked example using exactly these is
[`examples/python_api_example.py`](../examples/python_api_example.py).

`BundleReader` is the intended entry point for a *consumer*: it verifies-then-
streams, never loads a whole layer into memory, and hides the bundle layout. If
you find yourself joining paths inside a bundle by hand, that is a signal the
reader is missing a method — please open an issue.

## Experimental

Usable and documented, but the shapes are still settling:

* **Generator entry points** — `truth.generate_truth_graph`,
  `estate.write_estate`, `observed.generate_observed`,
  `canonical.generate_canonical`. Stable *behaviour* (same seed → same bytes);
  the signatures may gain parameters.
* **The defect registry** — `observed.DEFECTS`, `registry_rows`,
  `contract_coverage`. Rule ids are stable within a schema version; the registry
  will grow, and growth changes benchmark results.
* **`company.load_config` and the config models** — the YAML schema is versioned
  and stable; the Python model classes are not yet frozen.
* **`paths.ensure_safe_output_dir`** — the containment policy is deliberately
  shared, but it is a project-internal safety mechanism first.

## Internal

Not public, whatever their import path suggests: everything under
`truth.serialize`, `truth.writer`, `estate.formats`, `observed.engine` internals,
`observed.index`, `evaluation.engine` internals, `bundle.builder`,
`adapters.datahub.mapping` internals, and any module or name prefixed with `_`.

Depending on these is not a bug report we can act on.

## Unsupported use cases

Stated plainly, so nobody builds on a promise that was never made:

* **Real data.** Ingesting, deriving from or mixing in real clinical, patient or
  proprietary data is out of scope and explicitly unsupported.
* **Compliance evidence.** Passing this benchmark is not evidence of regulatory
  or legal compliance, and no report should be presented as such.
* **Scale or performance testing.** The canonical scenario is small on purpose.
  The `stress` estate profile is bigger, not big.
* **Scientific validity.** The generated data is structurally realistic and
  scientifically meaningless. It must not be used to develop or validate
  analytical or clinical methods.
* **Cross-version score comparison.** Scores are only comparable within one
  generator version, config fingerprint, profile and seed. The provenance and
  bundle manifest record all four so a comparison can be checked.
* **Live catalogue ingestion.** The DataHub adapter emits files offline. It does
  not talk to a server, and round-trip validation is not implemented.
