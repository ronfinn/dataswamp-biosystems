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
evaluate            compare-runs
build-bundle        verify-bundle
export-datahub      export-openmetadata
ingest-datahub      verify-ingestion
ingest-openmetadata verify-om-ingestion
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
| Observed ledgers, controls, rule scope, scenarios | `observed_schema_version` (currently `4`; `{3, 4}` readable) |
| Prediction submissions | `schema_version` (currently `1`) |
| Evaluation reports | `evaluation_schema_version` (currently `2`) |
| Comparison reports | `comparison_schema_version` (currently `1`) |
| Bundle manifest + checksums | `bundle_schema_version` |
| DataHub Metadata Change Proposals | `DATAHUB_MODEL_VERSION` |
| DataHub round-trip reports | `roundtrip_schema_version` (currently `1`) |
| OpenMetadata load plan | `OPENMETADATA_SCHEMA_TARGET` (payload) + `OM_ADAPTER_VERSION` (plan) |
| OpenMetadata mapping coverage | `coverage_schema_version` (currently `1`) |

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

# Comparing two emitted evaluation runs.
from dataswamp_biosystems.comparison import (
    EvaluationRun, load_run,
    compare_runs, ComparisonResult, write_comparison,
    benchmark_identity, check_compatible,
    COMPARISON_SCHEMA_VERSION, COMPARATOR_VERSION,
    ComparisonError, ComparisonConfigError, IncompatibleRunsError,
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

# Ingesting an emitted export into a live catalogue, and verifying the result.
from dataswamp_biosystems.adapters.datahub import (
    DataHubClient, DataHubAdapterError, DataHubConfigError, DataHubTransportError,
    load_export, plan_ingestion, execute_ingestion, read_back,
    compare, write_roundtrip, ROUNDTRIP_SCHEMA_VERSION, NORMALIZATION_VERSION,
)

# Emitting an OpenMetadata load plan from a verified bundle, and replaying it.
# (Experimental — no running OpenMetadata has ever accepted this export. See the
# OpenMetadata entry below.)
from dataswamp_biosystems.adapters.openmetadata import ExportMode, export_openmetadata
from dataswamp_biosystems.adapters.openmetadata import (
    OpenMetadataClient, load_export, plan_ingestion, execute_ingestion, read_back,
    compare, write_roundtrip, OM_ROUNDTRIP_SCHEMA_VERSION, OM_NORMALIZATION_VERSION,
)

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
* **The difficulty model** — `observed.Difficulty`, `ReasoningScope`,
  `difficulty_for`, `reasoning_scope_for`, `rules_at`, `rules_by_difficulty`,
  `selectable_rules`, `DifficultySelection`, `resolve_selection`. The tier of a
  given rule is stable within `DIFFICULTY_MODEL_VERSION`; that constant is bumped
  when a reclassification makes a published tier result non-comparable.
  No rule holds `Difficulty.ADVERSARIAL`, so `selectable_rules` still raises
  `UnavailableDifficultyError` for it — the tier is generated by constructing
  scenarios, not by filtering rules. See
  [docs/difficulty-tiers.md](difficulty-tiers.md).
* **The scenario model** — `observed.CaseType`, `ScenarioPolarity`,
  `ExpectedDetection`, `ExpectedRemediationBehaviour`, `ScenarioCase`,
  `ScenarioTransformation`, `SCENARIO_CLASSES`, `NEAR_MISS_DEFS`,
  `NEAR_MISS_VALIDITY_CHECKS`, `plan_scenarios`, `scenario_coverage`. Record
  shapes are stable within `SCENARIO_MODEL_VERSION`; the set of constructed case
  classes will grow, and growth changes adversarial results. See
  [docs/adversarial-scenarios.md](adversarial-scenarios.md).
* **The DataHub live path** — `DataHubClient`, `load_export`, `plan_ingestion`,
  `execute_ingestion`, `read_back`, `compare`, `write_roundtrip`, and the
  normalization and containment tables. The report shape is versioned by
  `roundtrip_schema_version`, and the forgiveness rules by
  `NORMALIZATION_VERSION`. Live GMS support is **experimental,
  contract-level**: the REST endpoints have not yet been exercised against a
  pinned real DataHub release, and every emitted report says so in its
  `live_support` field. See [docs/datahub.md](datahub.md) and
  [ADR 0005](adr/0005-direct-rest-datahub-client.md).
* **The OpenMetadata adapter** — `export_openmetadata`, `build_plan`,
  `build_source`, `validate_plan`, `SourceGraph`, `ExportPlan`, `PlanRecord`,
  `Reference`, and the coverage model (`Fidelity`, `State`, `Concept`,
  `ConceptCounts`, `CONCEPTS`, `build_coverage`). The emitted plan's shape is
  versioned by `OM_ADAPTER_VERSION` and the payload shapes by
  `OPENMETADATA_SCHEMA_TARGET`; the coverage report by
  `coverage_schema_version`.
* **The OpenMetadata live path** — `OpenMetadataClient`, `load_export`,
  `plan_ingestion`, `execute_ingestion`, `read_back`, `compare`,
  `write_roundtrip`, and the claim/coverage model (`Claim`, `Coverage`,
  `DiscrepancyKind`, `Readback`, `RoundTripResult`). Versioned by
  `OM_ROUNDTRIP_SCHEMA_VERSION` (`1`) and `OM_NORMALIZATION_VERSION` (`2`), both
  **entirely independent of DataHub's**. Credentials come from
  `OPENMETADATA_HOST_PORT` / `OPENMETADATA_JWT_TOKEN` and nowhere else; a token is
  never a CLI argument and never reaches a report. `VERIFIED_OPENMETADATA_VERSION`
  is `1.13.3` — a point earned in **observed mode**, never a range — and every
  emitted manifest and round-trip report states that scope. See
  [docs/openmetadata.md](openmetadata.md) and
  [ADR 0007](adr/0007-no-catalogue-client-dependency.md).
* **`company.load_config` and the config models** — the YAML schema is versioned
  and stable; the Python model classes are not yet frozen.
* **`paths.ensure_safe_output_dir`** — the containment policy is deliberately
  shared, but it is a project-internal safety mechanism first.

## Internal

Not public, whatever their import path suggests: everything under
`truth.serialize`, `truth.writer`, `estate.formats`, `observed.engine` internals,
`observed.index`, `evaluation.engine` internals, `bundle.builder`,
`adapters.datahub.mapping` internals, `adapters.openmetadata.mapping` internals,
and any module or name prefixed with `_`.

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
* **Cross-version score comparison.** `compare-runs` enforces this rather than
  documenting it: two runs must share a ground-truth fingerprint, profile,
  seeds, observed generator/schema versions, evaluator and prediction schema
  versions, and universe shape, or the comparison is refused with the differing
  field named. Scores are only comparable within one
  generator version, config fingerprint, profile and seed. The provenance and
  bundle manifest record all four so a comparison can be checked.
* **A verified live OpenMetadata compatibility point.** Stronger than the DataHub
  caveat below. `ingest-openmetadata` and `verify-om-ingestion` exist and work,
  and an **observed-mode** plan has now been loaded into a real, pinned
  OpenMetadata `1.13.3` by a green canary, so `VERIFIED_OPENMETADATA_VERSION` is
  `1.13.3`. That is a tested point, not a range, and **truth mode has not been run
  against a real server**. The declared `>=1.9,<2` model range remains a target for
  the emitted payload shape, not tested evidence: schema validity is not load
  success, and a green fake is not a green server.
* **A verified live DataHub compatibility point.** `ingest-datahub` and
  `verify-ingestion` do talk to a server, and round-trip validation is
  implemented and offline-testable — but the REST endpoints they use have not
  been exercised against a pinned real DataHub release in this repository. Treat
  live support as experimental until a report says otherwise.
