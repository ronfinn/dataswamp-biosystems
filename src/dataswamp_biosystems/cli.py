"""Command-line interface for Data Swamp Biosystems."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from dataswamp_biosystems import __version__
from dataswamp_biosystems.adapters.datahub import (
    DEFAULT_BATCH_SIZE,
    DataHubClient,
    DataHubConfigError,
    DataHubTransportError,
    ExportMode,
    LoadedExport,
    build_mcps,
    build_source,
    compare,
    execute_ingestion,
    export_datahub,
    load_export,
    plan_ingestion,
    read_back,
    validate_export,
    write_roundtrip,
)
from dataswamp_biosystems.adapters.openmetadata import (
    VERIFIED_OPENMETADATA_VERSION,
    OpenMetadataClient,
    build_plan,
)
from dataswamp_biosystems.adapters.openmetadata import (
    ExportMode as OpenMetadataExportMode,
)
from dataswamp_biosystems.adapters.openmetadata import (
    build_source as build_openmetadata_source,
)
from dataswamp_biosystems.adapters.openmetadata import (
    compare as compare_openmetadata,
)
from dataswamp_biosystems.adapters.openmetadata import (
    execute_ingestion as execute_openmetadata_ingestion,
)
from dataswamp_biosystems.adapters.openmetadata import (
    export_openmetadata as run_openmetadata_export,
)
from dataswamp_biosystems.adapters.openmetadata import (
    load_export as load_openmetadata_export,
)
from dataswamp_biosystems.adapters.openmetadata import (
    plan_ingestion as plan_openmetadata_ingestion,
)
from dataswamp_biosystems.adapters.openmetadata import (
    read_back as read_back_openmetadata,
)
from dataswamp_biosystems.adapters.openmetadata import (
    validate_plan as validate_openmetadata_plan,
)
from dataswamp_biosystems.adapters.openmetadata import (
    write_roundtrip as write_openmetadata_roundtrip,
)
from dataswamp_biosystems.adapters.openmetadata.errors import (
    OpenMetadataConfigError,
    OpenMetadataTransportError,
)
from dataswamp_biosystems.adapters.openmetadata.ingest import (
    LoadedExport as LoadedOpenMetadataExport,
)
from dataswamp_biosystems.baselines import (
    BASELINE_NAMES,
    BaselineError,
    ObservedInput,
    ObservedInputError,
    baseline_infos,
    get_baseline,
    run_baseline,
    write_predictions,
)
from dataswamp_biosystems.bundle import (
    BundleConfigError,
    BundleReader,
    BundleValidationError,
    Layer,
    build_bundle,
    verify_bundle,
)
from dataswamp_biosystems.canonical import (
    ESTATE_DIRNAME,
    OBSERVED_DIRNAME,
    TRUTH_DIRNAME,
    generate_canonical,
)
from dataswamp_biosystems.company import (
    DEFAULT_CONFIG_DIR,
    CanonicalConfig,
    ConfigLoadError,
    ConfigValidationError,
    load_config,
    resolve_config_dir,
)
from dataswamp_biosystems.comparison import (
    ComparisonConfigError,
    IncompatibleRunsError,
    compare_runs,
    load_run,
    write_comparison,
)
from dataswamp_biosystems.estate import (
    EstateConfigError,
    EstateValidationError,
    Profile,
    read_estate_meta,
    validate_estate,
    write_estate,
)
from dataswamp_biosystems.evaluation import (
    EvaluationConfigError,
    PredictionValidationError,
    evaluate,
    load_ground_truth,
    load_predictions,
    prediction_digest,
    write_evaluation,
)
from dataswamp_biosystems.examples import example_path
from dataswamp_biosystems.observed import (
    DEFECTS,
    DIFFICULTY_ORDER,
    DifficultySelection,
    ObservedConfigError,
    ObservedProfile,
    ObservedValidationError,
    TruthImmutabilityError,
    contract_coverage,
    read_observed_meta,
    registry_rows,
    resolve_selection,
    resolve_truth_dir,
    rules_by_difficulty,
    validate_registry,
)
from dataswamp_biosystems.observed import (
    inject_defects as run_defect_injection,
)
from dataswamp_biosystems.observed import (
    validate_observed as validate_observed_estate,
)
from dataswamp_biosystems.paths import (
    CONFIG_INPUT_LABEL,
    TRUTH_INPUT_LABEL,
    UnsafeOutputDirectoryError,
    ensure_safe_output_dir,
)
from dataswamp_biosystems.truth import (
    GenerationPlan,
    TruthConfigError,
    TruthValidationError,
    generate_truth_graph,
    load_generation_plan,
    validate_plan_against_config,
    validate_truth_graph,
    write_truth_graph,
)
from dataswamp_biosystems.truth.errors import TruthIssueCollector
from dataswamp_biosystems.truth.writer import MANIFEST_NAME, shard_bytes

app = typer.Typer(help="Data Swamp Biosystems command-line interface.")

DEFAULT_TRUTH_DIR = Path("generated") / "truth"
DEFAULT_ESTATE_DIR = Path("generated") / "estate"
DEFAULT_OBSERVED_DIR = Path("generated") / "observed"
DEFAULT_EVALUATION_DIR = Path("generated") / "evaluation"
DEFAULT_COMPARISON_DIR = Path("generated") / "comparison"

# Both evaluation directories a comparison reads are protected inputs: a
# comparison must never be able to replace a run it is differencing.
BASELINE_INPUT_LABEL = "baseline evaluation directory"
CANDIDATE_INPUT_LABEL = "candidate evaluation directory"

# The observed state is a required *input* to evaluation, so it joins the config
# and truth directories as a protected path — an evaluation run must never be
# able to replace the ground truth it is scored against.
OBSERVED_INPUT_LABEL = "observed ground-truth directory"
# The prediction *file* is protected, not its parent directory: protecting the
# parent would reject every output under the repository whenever a submission
# sits at the repository root, while protecting the file still rejects an output
# directory that is, or contains, the submission being scored.
PREDICTIONS_INPUT_LABEL = "prediction file"

# A baseline writes a single submission file rather than a directory, so the
# default is a filename in the working directory.
DEFAULT_BASELINE_OUTPUT = Path("predictions.jsonl")
BASELINE_OUTPUT_LABEL = "baseline submission file"

DEFAULT_BUNDLE_DIR = Path("dist") / "dataswamp-benchmark"
DEFAULT_DATAHUB_EXPORT_DIR = Path("export") / "datahub"
DEFAULT_OPENMETADATA_EXPORT_DIR = Path("export") / "openmetadata"
DEFAULT_ROUNDTRIP_DIR = Path("generated") / "roundtrip"
DEFAULT_OM_ROUNDTRIP_DIR = Path("generated") / "om-roundtrip"

# The demo writes every layer, the bundle and the export beneath one directory,
# so a new user has a single thing to look at — and a single thing to delete.
DEFAULT_DEMO_DIR = Path("dataswamp-demo")

# Every layer directory a bundle reads is a protected input for the build, and
# the bundle itself is a protected input for an adapter export: neither command
# may replace the artefacts it is packaging or translating.
ESTATE_INPUT_LABEL = "estate input directory"
EVALUATION_INPUT_LABEL = "evaluation input directory"
BUNDLE_INPUT_LABEL = "benchmark bundle directory"
DATAHUB_EXPORT_INPUT_LABEL = "DataHub export directory"
OPENMETADATA_EXPORT_INPUT_LABEL = "OpenMetadata export directory"

_LAYER_INPUT_LABELS: dict[Layer, str] = {
    Layer.TRUTH: TRUTH_INPUT_LABEL,
    Layer.ESTATE: ESTATE_INPUT_LABEL,
    Layer.OBSERVED: OBSERVED_INPUT_LABEL,
    Layer.EVALUATION: EVALUATION_INPUT_LABEL,
}


def _load_config_or_exit(config_dir: Path) -> CanonicalConfig:
    """Load the canonical config, mapping failures to CLI exit codes 1/2."""
    try:
        return load_config(config_dir)
    except ConfigLoadError as exc:
        typer.echo(f"Could not load configuration: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except ConfigValidationError as exc:
        typer.echo(f"Configuration is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc


def _load_plan_or_exit(config_dir: Path, config: CanonicalConfig) -> GenerationPlan:
    """Load and cross-validate the generation plan, mapping failures to exit codes."""
    try:
        plan = load_generation_plan(config_dir)
    except TruthConfigError as exc:
        typer.echo(f"Could not load generation plan: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    issues = TruthIssueCollector()
    validate_plan_against_config(plan, config, issues)
    try:
        issues.raise_if_any()
    except TruthValidationError as exc:
        typer.echo(f"Generation plan is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc
    return plan


def _prepare_output_dir_or_exit(
    output_dir: Path,
    protected_paths: dict[str, Path],
    *,
    force: bool,
) -> None:
    """Reject an unsafe or non-empty output directory before anything is written.

    Runs the shared containment policy first, so a path overlapping a protected
    input is refused before the non-empty/``--force`` question is even asked —
    ``--force`` must never be a route to replacing a required input. Both
    conditions are CLI usage errors and exit with code 2.
    """
    try:
        ensure_safe_output_dir(output_dir, protected_paths=protected_paths)
    except UnsafeOutputDirectoryError as exc:
        typer.echo(f"Refusing to generate into {output_dir}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        typer.echo(
            f"Output directory {output_dir} is not empty; pass --force to overwrite.", err=True
        )
        raise typer.Exit(code=2)


@app.callback()
def callback() -> None:
    """Data Swamp Biosystems command-line interface."""


@app.command()
def version() -> None:
    """Print the installed package version and exit."""
    typer.echo(__version__)


@app.command(name="validate-config")
def validate_config(
    config_dir: Annotated[
        Path,
        typer.Option(
            "--config-dir",
            help="Directory containing the canonical configuration YAML files.",
        ),
    ] = DEFAULT_CONFIG_DIR,
) -> None:
    """Load and validate the canonical company configuration.

    Exit codes: 0 = valid, 1 = validation issues, 2 = configuration could not
    be loaded (missing file or malformed YAML).
    """
    config_dir = resolve_config_dir(config_dir)
    config = _load_config_or_exit(config_dir)

    typer.echo(f"Configuration is valid ({config.company.display_name}).")
    typer.echo("Entity counts:")
    for name, count in config.entity_counts().items():
        typer.echo(f"  {name.replace('_', ' ')}: {count}")


@app.command(name="generate-truth")
def generate_truth(
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Generation seed; defaults to config generation.seed."),
    ] = None,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the truth graph into."),
    ] = DEFAULT_TRUTH_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Generate the deterministic truth graph under ``output_dir``.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the configuration directory (which also rules out the repository root
    and any parent of it).

    Exit codes: 0 = written, 1 = invalid config/plan or failed invariants,
    2 = a required file could not be loaded, or an unsafe/non-empty output
    directory was given.
    """
    config_dir = resolve_config_dir(config_dir)
    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    resolved_seed = seed if seed is not None else config.generation.seed
    if resolved_seed < 0:
        typer.echo(f"Seed must be a non-negative integer, got {resolved_seed}.", err=True)
        raise typer.Exit(code=2)

    _prepare_output_dir_or_exit(output_dir, {CONFIG_INPUT_LABEL: config_dir}, force=force)

    graph = generate_truth_graph(config, plan, resolved_seed)
    try:
        validate_truth_graph(graph, config, plan)
    except TruthValidationError as exc:
        typer.echo(f"Generated truth graph is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    write_truth_graph(graph, output_dir)
    typer.echo(f"Truth graph written to {output_dir} (seed {resolved_seed}).")
    typer.echo("Entity counts:")
    for name, count in graph.entity_counts().items():
        typer.echo(f"  {name.replace('_', ' ')}: {count}")


@app.command(name="validate-truth")
def validate_truth(
    truth_dir: Annotated[
        Path,
        typer.Option("--truth-dir", help="Directory containing a generated truth graph."),
    ] = DEFAULT_TRUTH_DIR,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
) -> None:
    """Validate a generated truth graph against config, invariants, and its own bytes.

    Regenerates from the seed recorded in the manifest and confirms both that
    every invariant holds and that the on-disk shards are byte-identical to what
    the generator produces — an end-to-end determinism and integrity check.

    Exit codes: 0 = valid, 1 = invalid or drifted, 2 = manifest missing/unreadable.
    """
    manifest_path = truth_dir / MANIFEST_NAME
    if not manifest_path.exists():
        typer.echo(f"No manifest found at {manifest_path}.", err=True)
        raise typer.Exit(code=2)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        seed = int(manifest["meta"]["seed"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        typer.echo(f"Could not read manifest {manifest_path}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    config_dir = resolve_config_dir(config_dir)
    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    graph = generate_truth_graph(config, plan, seed)
    try:
        validate_truth_graph(graph, config, plan)
    except TruthValidationError as exc:
        typer.echo(f"Truth graph is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    drifted: list[str] = []
    for name, data in shard_bytes(graph).items():
        on_disk = (truth_dir / name).read_bytes() if (truth_dir / name).exists() else b""
        if on_disk != data:
            drifted.append(name)
    if drifted:
        typer.echo("On-disk shards differ from the regenerated graph:", err=True)
        for name in drifted:
            typer.echo(f"  - {name}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Truth graph at {truth_dir} is valid (seed {seed}).")


@app.command(name="generate-files")
def generate_files(
    profile: Annotated[
        Profile,
        typer.Option("--profile", help="Estate profile controlling scale and disk footprint."),
    ] = Profile.TINY,
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Generation seed; defaults to config generation.seed."),
    ] = None,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the estate into."),
    ] = DEFAULT_ESTATE_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Generate representative scientific files for the truth graph's assets.

    The truth graph is regenerated in memory from the same config and seed (it is
    consumed, never re-invented), then a per-asset file set is materialized under
    ``output_dir``.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the configuration directory or the default truth directory — an
    estate belongs alongside a truth graph, never on top of one.

    Exit codes: 0 = written, 1 = invalid config/plan or a safety breach
    (path/budget), 2 = a required file could not be loaded, or an unsafe/non-empty
    output directory was given.
    """
    config_dir = resolve_config_dir(config_dir)
    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    resolved_seed = seed if seed is not None else config.generation.seed
    if resolved_seed < 0:
        typer.echo(f"Seed must be a non-negative integer, got {resolved_seed}.", err=True)
        raise typer.Exit(code=2)

    _prepare_output_dir_or_exit(
        output_dir,
        {CONFIG_INPUT_LABEL: config_dir, TRUTH_INPUT_LABEL: DEFAULT_TRUTH_DIR},
        force=force,
    )

    graph = generate_truth_graph(config, plan, resolved_seed)
    try:
        validate_truth_graph(graph, config, plan)
    except TruthValidationError as exc:
        typer.echo(f"Truth graph is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        summary = write_estate(graph, profile, resolved_seed, output_dir)
    except EstateValidationError as exc:
        typer.echo(f"Estate generation failed — {len(exc.issues)} issue(s):", err=True)
        for est_issue in exc.issues:
            typer.echo(f"  - {est_issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    counts = summary["counts"]
    sizes = summary["sizes"]
    typer.echo(f"Estate written to {output_dir} (profile {profile.value}, seed {resolved_seed}).")
    typer.echo(f"  files: {counts['files']} ({counts['placeholders']} placeholders)")
    typer.echo(f"  assets covered: {counts['assets']}")
    typer.echo(f"  physical bytes: {sizes['total_physical_bytes']}")
    typer.echo(f"  represented logical bytes: {sizes['total_logical_bytes']}")
    typer.echo(f"  formats: {', '.join(summary['formats_generated'])}")


@app.command(name="validate-files")
def validate_files(
    estate_dir: Annotated[
        Path,
        typer.Option("--estate-dir", help="Directory containing a generated estate."),
    ] = DEFAULT_ESTATE_DIR,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
) -> None:
    """Validate a generated estate against the truth graph, its bytes, and disk.

    Regenerates the truth graph from the estate's recorded seed and confirms
    checksums, path safety, asset references, placeholder sidecars, and a
    byte-for-byte manifest match. Exit codes: 0 = valid, 1 = invalid or drifted,
    2 = the estate summary/manifest is missing or unreadable.
    """
    try:
        meta = read_estate_meta(estate_dir)
        truth_seed = int(str(meta["truth_seed"]))
    except (EstateConfigError, KeyError, ValueError) as exc:
        typer.echo(f"Could not read estate at {estate_dir}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    config_dir = resolve_config_dir(config_dir)
    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    graph = generate_truth_graph(config, plan, truth_seed)

    try:
        validate_estate(estate_dir, graph)
    except EstateConfigError as exc:
        typer.echo(f"Could not read estate at {estate_dir}: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except EstateValidationError as exc:
        typer.echo(f"Estate is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Estate at {estate_dir} is valid (profile {meta['profile']}, seed {meta['seed']}).")


@app.command(name="list-defects")
def list_defects(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the registry as JSON instead of text."),
    ] = False,
) -> None:
    """Print the defect-rule registry.

    Each rule is annotated with its remediation contract — how it can be
    remediated and whether that requires approval, which are independent — plus
    rule counts per category and per benchmark contract state.

    Exit codes: 0 = printed.
    """
    rows = registry_rows()
    tiers = rules_by_difficulty()
    if as_json:
        # Coverage travels with the rules so a consumer can see which benchmark
        # states the catalogue exercises without re-deriving it from the rows.
        payload = {
            "rules": rows,
            "contract_state_coverage": contract_coverage(),
            "difficulty_coverage": {tier.value: list(rule_ids) for tier, rule_ids in tiers.items()},
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    by_category: dict[str, int] = {}
    for row in rows:
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1

    typer.echo(f"{len(rows)} defect rule(s) across {len(by_category)} categories:")
    for row in rows:
        # Show the two independent dimensions, not a single fixability flag.
        flags = [f"remediation={row['remediation_availability']}"]
        flags.append(f"approval={row['approval_policy']}")
        if row["approver_role"] != "none":
            flags.append(f"approver={row['approver_role']}")
        if row["non_remediable_reason"] != "none":
            flags.append(f"reason={row['non_remediable_reason']}")
        flag_text = f" [{', '.join(flags)}]"
        typer.echo(
            f"  {row['rule_id']} [{row['category']}/{row['severity']}/"
            f"{row['difficulty']}] {row['title']}{flag_text}"
        )
    typer.echo("Rules by category:")
    for category in sorted(by_category):
        typer.echo(f"  {category}: {by_category[category]}")
    typer.echo("Rules by contract state:")
    for state, rule_ids in contract_coverage().items():
        typer.echo(f"  {state}: {len(rule_ids)}")
    # Difficulty is detection complexity, derived from each rule's reasoning
    # scope — printed apart from severity so the two are not read as one axis.
    typer.echo("Rules by difficulty (reasoning complexity, not severity):")
    for tier in DIFFICULTY_ORDER:
        typer.echo(f"  {tier.value}: {len(tiers[tier])}")


@app.command(name="validate-defects")
def validate_defects() -> None:
    """Validate the defect-rule registry and its remediation contracts.

    Checks structural well-formedness, that every rule's remediation contract is
    internally consistent (remediation availability and approval policy are
    independent, so neither may be inferred from the other), that every rule
    declares exactly one reasoning scope from which its difficulty tier is
    derived, and that the catalogue collectively covers every benchmark contract
    state. Requires no generated benchmark output.

    Exit codes: 0 = valid, 1 = the registry has structural or contract problems.
    """
    problems = validate_registry(DEFECTS)
    if problems:
        typer.echo(f"Defect registry is invalid — {len(problems)} problem(s):", err=True)
        for problem in problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Defect registry is valid ({len(DEFECTS)} rules).")
    typer.echo("Contract-state coverage:")
    for state, rule_ids in contract_coverage().items():
        typer.echo(f"  {state}: {len(rule_ids)} rule(s)")
    typer.echo("Difficulty coverage (every rule classified by reasoning scope):")
    for tier, tier_rules in rules_by_difficulty().items():
        typer.echo(f"  {tier.value}: {len(tier_rules)} rule(s)")


@app.command(name="inject-defects")
def inject_defects(
    truth: Annotated[
        Path,
        typer.Option("--truth", help="Path to the truth manifest or its directory."),
    ] = DEFAULT_TRUTH_DIR / MANIFEST_NAME,
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Defect seed; defaults to config generation.seed."),
    ] = None,
    profile: Annotated[
        ObservedProfile,
        typer.Option("--profile", help="Maturity profile controlling the defect mix."),
    ] = ObservedProfile.DEMO,
    difficulty: Annotated[
        DifficultySelection,
        typer.Option(
            "--difficulty",
            help=(
                "Benchmark tier: how much evidence a detector must relate before it "
                "can decide (bronze = one record, silver = one join, gold = several "
                "assets or a peer comparison). This is reasoning complexity, not "
                "severity and not maturity — use --profile for how many defects are "
                "injected. 'mixed' is the full ordinary rule catalogue and the "
                "default, and never includes adversarial scenarios. 'adversarial' is "
                "explicit and opt-in: it switches to the scenario engine, which "
                "constructs near-miss controls, decoys and overlapping evidence "
                "rather than filtering rules."
            ),
        ),
    ] = DifficultySelection.MIXED,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the observed state into."),
    ] = DEFAULT_OBSERVED_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Derive the observed state from an on-disk truth graph, without mutating it.

    ``--profile`` and ``--difficulty`` are independent filters: the profile sets
    how many defects are injected, the tier sets which rules may inject them. A
    tier whose rules have nothing to draw from under the chosen profile is an
    error rather than an empty benchmark.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the configuration directory or the truth directory it reads from.

    Exit codes: 0 = written, 1 = invalid config/plan, failed generation checks,
    or a truth-immutability breach, 2 = the truth graph could not be read, an
    empty profile/tier intersection, or an unsafe/non-empty output directory was
    given.
    """
    config_dir = resolve_config_dir(config_dir)
    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    resolved_seed = seed if seed is not None else config.generation.seed
    if resolved_seed < 0:
        typer.echo(f"Seed must be a non-negative integer, got {resolved_seed}.", err=True)
        raise typer.Exit(code=2)

    _prepare_output_dir_or_exit(
        output_dir,
        {CONFIG_INPUT_LABEL: config_dir, TRUTH_INPUT_LABEL: resolve_truth_dir(truth)},
        force=force,
    )

    tier = resolve_selection(difficulty)
    try:
        report = run_defect_injection(truth, config, plan, profile, resolved_seed, output_dir, tier)
    except ObservedConfigError as exc:
        typer.echo(f"Could not inject defects: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except TruthImmutabilityError as exc:
        typer.echo(f"Truth immutability breach: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ObservedValidationError as exc:
        typer.echo(f"Observed-state generation failed — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    totals = report.result.summary["totals"]
    typer.echo(
        f"Observed state written to {output_dir} "
        f"(profile {profile.value}, difficulty {difficulty.value}, "
        f"defect seed {resolved_seed})."
    )
    typer.echo(f"  defects injected: {totals['defects']}")
    typer.echo(f"  rules fired: {totals['rules_fired']} / {totals['rules_defined']}")
    typer.echo(
        f"  assets: {totals['assets']} ({totals['control_assets']} control, "
        f"{totals['affected_assets']} affected, {totals['clean_assets']} clean)"
    )
    typer.echo(
        f"  control records: {totals['control_records']} ({totals['reserved_controls']} reserved)"
    )
    coverage = report.result.summary.get("scenarios")
    if coverage is not None:
        scenario_totals = coverage["totals"]
        typer.echo(
            f"  adversarial scenarios: {scenario_totals['scenarios']} "
            f"({scenario_totals['positive_scenarios']} positive, "
            f"{scenario_totals['near_miss_controls']} near-miss control)"
        )
        for case_type, count in coverage["by_case_type"].items():
            typer.echo(f"    {case_type}: {count}")


@app.command(name="validate-observed")
def validate_observed(
    observed_dir: Annotated[
        Path,
        typer.Option("--observed-dir", help="Directory containing a generated observed state."),
    ] = DEFAULT_OBSERVED_DIR,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
) -> None:
    """Validate a generated observed state against its bytes and its bookkeeping.

    Regenerates the observed state from the recorded profile and defect seed and
    confirms it is byte-identical to disk, then checks structural completeness,
    referential integrity, mutation fidelity, the absence of contradictory
    mutations, and the integrity of the control partition — that every emitted
    control resolves to a real entity, is untargeted by any defect or mutation,
    and is unchanged from truth in the observed graph. Exit codes: 0 = valid,
    1 = invalid or drifted, 2 = the observed summary is missing or unreadable.
    """
    try:
        meta = read_observed_meta(observed_dir)
        truth_seed = int(str(meta["truth_seed"]))
    except (ObservedConfigError, KeyError, ValueError) as exc:
        typer.echo(f"Could not read observed state at {observed_dir}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    config_dir = resolve_config_dir(config_dir)
    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    graph = generate_truth_graph(config, plan, truth_seed)

    try:
        validate_observed_estate(observed_dir, graph, config)
    except ObservedConfigError as exc:
        typer.echo(f"Could not read observed state at {observed_dir}: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except ObservedValidationError as exc:
        typer.echo(f"Observed state is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Observed state at {observed_dir} is valid "
        f"(profile {meta['profile']}, defect seed {meta['defect_seed']})."
    )


def _score_or_exit(
    observed_dir: Path,
    submission: Path,
    evaluation_dir: Path,
) -> dict[str, Any]:
    """Load ground truth, validate and score ``submission``, write the reports.

    The single place the CLI performs an evaluation. ``run-baseline --evaluate``
    and ``demo`` both come through here rather than reimplementing scoring, so
    there is exactly one evaluator and one set of exit-code mappings.
    """
    try:
        truth = load_ground_truth(observed_dir)
    except EvaluationConfigError as exc:
        typer.echo(f"Could not read ground truth: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    try:
        submitted, raw = load_predictions(
            submission,
            known_entities=truth.known_entities,
            known_rules=truth.rule_ids,
        )
    except EvaluationConfigError as exc:
        typer.echo(f"Could not read predictions: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except PredictionValidationError as exc:
        typer.echo(f"Predictions are invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    result = evaluate(truth, submitted, prediction_digest=prediction_digest(raw))
    return write_evaluation(result, evaluation_dir)


def _echo_scorecard(summary: dict[str, Any]) -> None:
    """Print the shared four-line scorecard every scoring command ends with."""
    micro = summary["findings"]["overall_micro"]
    counts = micro["counts"]
    metrics = micro["metrics"]

    def show(name: str) -> str:
        value = metrics[name]["value"]
        return "n/a" if value is None else f"{value:.4f}"

    typer.echo(f"  TP {counts['tp']}  FP {counts['fp']}  FN {counts['fn']}  TN {counts['tn']}")
    typer.echo(
        f"  precision {show('precision')}  recall {show('recall')}  "
        f"specificity {show('specificity')}  F1 {show('f1')}"
    )
    typer.echo(
        f"  reserved-control false positives: {summary['reserved_controls']['false_positives']}"
    )
    typer.echo(f"  unsafe remediations: {summary['remediation']['counts']['unsafe_actions']}")


@app.command(name="evaluate")
def evaluate_predictions(
    predictions: Annotated[
        Path,
        typer.Option("--predictions", help="JSONL file of agent predictions to score."),
    ],
    observed_dir: Annotated[
        Path,
        typer.Option("--observed-dir", help="Directory containing the observed ground truth."),
    ] = DEFAULT_OBSERVED_DIR,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the evaluation reports into."),
    ] = DEFAULT_EVALUATION_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Score a prediction file against an emitted observed state.

    Ground truth and the submission are both fully validated *before* anything is
    written, so an invalid submission never replaces a previous evaluation.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the configuration directory, the observed ground-truth directory, or
    the directory holding the prediction file — ``--force`` overrides only the
    non-empty check, never path safety.

    Exit codes: 0 = evaluated, 1 = the submission violates the prediction
    contract, 2 = ground truth or predictions could not be read, or an
    unsafe/non-empty output directory was given.
    """
    _prepare_output_dir_or_exit(
        output_dir,
        {
            CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR,
            OBSERVED_INPUT_LABEL: observed_dir,
            PREDICTIONS_INPUT_LABEL: predictions,
        },
        force=force,
    )

    summary = _score_or_exit(observed_dir, predictions, output_dir)

    counts = summary["findings"]["overall_micro"]["counts"]
    typer.echo(
        f"Evaluation written to {output_dir} "
        f"(profile {summary['benchmark']['profile']}, "
        f"{summary['submission']['predictions']} prediction(s))."
    )
    typer.echo(
        f"  pairs: {summary['universe']['evaluated_pairs']} "
        f"({counts['positives']} positive, {counts['negatives']} negative)"
    )
    _echo_scorecard(summary)
    typer.echo(f"  out-of-scope false positives: {summary['out_of_scope']['false_positives']}")
    typer.echo(
        f"  remediations: {summary['remediation']['counts']['submitted']} submitted, "
        f"{summary['remediation']['counts']['fully_correct']} fully correct, "
        f"{summary['remediation']['counts']['unsafe_actions']} unsafe"
    )


@app.command(name="compare-runs")
def compare_evaluation_runs(
    baseline: Annotated[
        Path,
        typer.Option("--baseline", help="Directory containing the baseline evaluation."),
    ],
    candidate: Annotated[
        Path,
        typer.Option("--candidate", help="Directory containing the candidate evaluation."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the comparison into."),
    ] = DEFAULT_COMPARISON_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Compare two emitted evaluation runs and report what changed.

    Consumes what ``dataswamp evaluate`` already wrote: it re-scores nothing,
    reads no prediction file and never opens the observed ground truth, so the
    numbers reported are the evaluator's own, differenced. Both input
    directories are read-only.

    The two runs must describe the same benchmark universe. If any identity
    field differs — ground-truth fingerprint, profile, either seed, the observed
    or evaluator versions, or the derived universe shape — the comparison is
    refused and every differing field is named. Differencing metrics across
    universes produces a number that looks meaningful and is not.

    A regression does **not** fail this command: it answers what changed, and
    applies no threshold or policy gate.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside either evaluation directory — ``--force`` overrides only the
    non-empty check, never path safety.

    Exit codes: 0 = compared, 1 = the runs are not comparable, 2 = an evaluation
    directory could not be read, or an unsafe/non-empty output directory was
    given.
    """
    _prepare_output_dir_or_exit(
        output_dir,
        {
            BASELINE_INPUT_LABEL: baseline,
            CANDIDATE_INPUT_LABEL: candidate,
        },
        force=force,
    )

    try:
        left = load_run(baseline)
        right = load_run(candidate)
    except ComparisonConfigError as exc:
        typer.echo(f"Could not read evaluation output: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    try:
        result = compare_runs(left, right)
    except IncompatibleRunsError as exc:
        typer.echo(
            f"Refusing to compare — {len(exc.mismatches)} benchmark identity field(s) differ:",
            err=True,
        )
        for mismatch in exc.mismatches:
            typer.echo(f"  - {mismatch.render()}", err=True)
        typer.echo("Two runs must score the same universe for a delta to mean anything.", err=True)
        raise typer.Exit(code=1) from exc

    summary = write_comparison(result, output_dir)
    headline = summary["headline"]

    typer.echo(
        f"Comparison written to {output_dir} "
        f"(profile {summary['benchmark']['profile']}, "
        f"{headline['pairs_changed']} pair(s) changed)."
    )
    if summary["runs"]["identical_submission"]:
        typer.echo("  the two runs scored an identical submission")
    typer.echo(
        f"  findings: {headline['newly_solved']} newly solved, "
        f"{headline['newly_broken']} newly broken"
    )
    typer.echo(
        f"  control false positives: {headline['new_control_false_positives']} new "
        f"({headline['new_reserved_control_false_positives']} on reserved controls), "
        f"{headline['resolved_control_false_positives']} resolved"
    )
    typer.echo(
        f"  rules: {headline['rules_regressed']} regressed, {headline['rules_improved']} improved"
    )
    typer.echo(
        f"  remediations: {headline['remediations_changed']} changed "
        f"({headline['remediations_regressed']} regressed)"
    )
    for name in sorted(summary["dimensions"]):
        delta = summary["dimensions"][name]
        rendered = "n/a" if delta["delta"] is None else f"{delta['delta']:+.4f}"
        typer.echo(f"  {name}: {rendered} ({delta['direction']})")


@app.command(name="list-baselines")
def list_baselines() -> None:
    """List the reference baseline agents and the observed fields each one reads.

    The read list is derived from the agents themselves, so it cannot drift away
    from what the code actually inspects.
    """
    infos = baseline_infos()
    typer.echo(f"{len(infos)} reference baseline agent(s):")
    for info in infos:
        typer.echo(f"  {info.name} (v{info.version})")
        typer.echo(f"    {info.summary}")
        if info.reads:
            typer.echo(f"    reads: {', '.join(info.reads)}")
        else:
            typer.echo("    reads: nothing")


@app.command(name="run-baseline")
def run_baseline_command(
    agent: Annotated[
        str,
        typer.Option("--agent", help=f"Baseline to run: {', '.join(BASELINE_NAMES)}."),
    ],
    observed_dir: Annotated[
        Path,
        typer.Option("--observed-dir", help="Directory containing the observed state to read."),
    ] = DEFAULT_OBSERVED_DIR,
    output: Annotated[
        Path,
        typer.Option("--output", help="JSONL file to write the submission to."),
    ] = DEFAULT_BASELINE_OUTPUT,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing submission, and a non-empty --evaluation-dir.",
        ),
    ] = False,
    score: Annotated[
        bool,
        typer.Option("--evaluate", help="Score the submission after writing it."),
    ] = False,
    evaluation_dir: Annotated[
        Path,
        typer.Option("--evaluation-dir", help="Where --evaluate writes its reports."),
    ] = DEFAULT_EVALUATION_DIR,
) -> None:
    """Run a reference baseline agent and write a prediction submission.

    The agent reads ``observed-graph.json`` from ``--observed-dir`` and nothing
    else — not the expected findings, the expected remediations, the controls,
    the rule scope, the mutation log or the truth graph. Baselines are scored as
    genuine participants, so a baseline that could see the answers would publish
    a meaningless number.

    Output is deterministic: predictions are emitted in ``(entity_id, rule_id)``
    order with a stable encoding, so two runs over the same observed state
    produce byte-identical files. No credentials, server or network access is
    involved.

    ``--evaluate`` scores the submission through the ordinary evaluator and
    writes its reports to ``--evaluation-dir``. ``--force`` covers both outputs:
    an existing submission file and a non-empty evaluation directory. It never
    overrides path safety.

    Exit codes: 0 = written, 1 = the submission failed evaluation's contract,
    2 = an unknown agent, an unreadable observed state, or a refused output path.
    """
    try:
        baseline = get_baseline(agent)
    except BaselineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    # The submission is a *file*, so the file itself is what must not overlap a
    # protected input — protecting its parent would reject any output beside the
    # configuration directory, which is where a user naturally puts one.
    try:
        ensure_safe_output_dir(
            output,
            protected_paths={
                CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR,
                OBSERVED_INPUT_LABEL: observed_dir,
                TRUTH_INPUT_LABEL: DEFAULT_TRUTH_DIR,
            },
        )
    except UnsafeOutputDirectoryError as exc:
        typer.echo(f"Refusing to write {output}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if output.exists() and not force:
        typer.echo(f"Output file {output} already exists; pass --force to overwrite.", err=True)
        raise typer.Exit(code=2)
    if output.is_dir():
        typer.echo(f"Output {output} is a directory, not a file.", err=True)
        raise typer.Exit(code=2)

    try:
        observed = ObservedInput.load(observed_dir)
    except ObservedInputError as exc:
        typer.echo(f"Could not read the observed state: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    run = run_baseline(baseline, observed)
    write_predictions(run, output)

    scenario = ", ".join(f"{key} {value}" for key, value in sorted(run.scenario.items()))
    typer.echo(
        f"{run.info.name} v{run.info.version} wrote {run.prediction_count} prediction(s) "
        f"to {output}."
    )
    typer.echo(f"  rules used: {len(run.rules_used)}")
    if scenario:
        typer.echo(f"  scenario: {scenario}")

    if not score:
        return

    _prepare_output_dir_or_exit(
        evaluation_dir,
        {
            CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR,
            OBSERVED_INPUT_LABEL: observed_dir,
            PREDICTIONS_INPUT_LABEL: output,
        },
        force=force,
    )
    summary = _score_or_exit(observed_dir, output, evaluation_dir)
    typer.echo(f"Evaluation written to {evaluation_dir}.")
    _echo_scorecard(summary)


@app.command(name="build-bundle")
def build_bundle_command(
    truth_dir: Annotated[
        Path,
        typer.Option("--truth-dir", help="Directory containing a generated truth graph."),
    ] = DEFAULT_TRUTH_DIR,
    estate_dir: Annotated[
        Path,
        typer.Option("--estate-dir", help="Directory containing a generated file estate."),
    ] = DEFAULT_ESTATE_DIR,
    observed_dir: Annotated[
        Path,
        typer.Option("--observed-dir", help="Directory containing a generated observed state."),
    ] = DEFAULT_OBSERVED_DIR,
    evaluation_dir: Annotated[
        Path,
        typer.Option("--evaluation-dir", help="Directory containing an evaluation report."),
    ] = DEFAULT_EVALUATION_DIR,
    layers: Annotated[
        list[Layer] | None,
        typer.Option(
            "--layer",
            help="Layer to include; repeatable. Defaults to every layer whose directory exists.",
        ),
    ] = None,
    release: Annotated[
        str | None,
        typer.Option("--release", help="Benchmark release name; defaults to the package version."),
    ] = None,
    datahub_export_dir: Annotated[
        Path | None,
        typer.Option(
            "--datahub-export",
            help="Embed an existing DataHub export under adapters/datahub/ in the bundle.",
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the bundle into."),
    ] = DEFAULT_BUNDLE_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Package generated benchmark output into a versioned, checksummed bundle.

    Only the layers actually present are bundled, so a truth-only bundle, a
    truth+estate bundle, one with the observed ground truth, and a complete
    benchmark with a worked evaluation are all first-class. A layer may only be
    included alongside the layers it was derived from.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the configuration directory or any bundled layer directory —
    ``--force`` overrides only the non-empty check, never path safety.

    Exit codes: 0 = written, 2 = an input could not be read or an unsafe/non-empty
    output directory was given.
    """
    candidates: dict[Layer, Path] = {
        Layer.TRUTH: truth_dir,
        Layer.ESTATE: estate_dir,
        Layer.OBSERVED: observed_dir,
        Layer.EVALUATION: evaluation_dir,
    }
    if layers:
        selected = {layer: candidates[layer] for layer in dict.fromkeys(layers)}
    else:
        selected = {layer: path for layer, path in candidates.items() if path.is_dir()}
    if Layer.TRUTH not in selected:
        typer.echo(
            f"A bundle must include the truth layer; no truth graph at {truth_dir}.", err=True
        )
        raise typer.Exit(code=2)

    protected = {CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR}
    protected.update({_LAYER_INPUT_LABELS[layer]: path for layer, path in selected.items()})
    if datahub_export_dir is not None:
        protected[DATAHUB_EXPORT_INPUT_LABEL] = datahub_export_dir
    _prepare_output_dir_or_exit(output_dir, protected, force=force)

    try:
        manifest = build_bundle(
            output_dir,
            sources=selected,
            release=release,
            adapter_exports=({"datahub": datahub_export_dir} if datahub_export_dir else None),
        )
    except BundleConfigError as exc:
        typer.echo(f"Could not build the bundle: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(
        f"Bundle written to {output_dir} "
        f"(release {manifest.benchmark_release}, schema {manifest.bundle_schema_version})."
    )
    typer.echo(f"  layers: {', '.join(manifest.layers)}")
    typer.echo(f"  bundled files: {len(manifest.files)}")
    for name, count in manifest.counts.items():
        typer.echo(f"  {name}: {count}")
    typer.echo(f"  bundle fingerprint: {manifest.bundle_fingerprint}")


@app.command(name="verify-bundle")
def verify_bundle_command(
    bundle_dir: Annotated[
        Path,
        typer.Argument(help="Directory containing a benchmark bundle."),
    ],
    strict: Annotated[
        bool,
        typer.Option(
            "--strict/--no-strict",
            help="Reject files present in the bundle but absent from the manifest.",
        ),
    ] = True,
) -> None:
    """Verify a benchmark bundle's manifest, checksums, structure and provenance.

    Every invariant is checked and every failure reported, each naming the file
    and the invariant it broke. Nothing is written and the bundle is never
    modified.

    Exit codes: 0 = valid, 1 = one or more invariants failed, 2 = the manifest is
    missing or unreadable.
    """
    try:
        manifest = verify_bundle(bundle_dir, strict=strict)
    except BundleConfigError as exc:
        typer.echo(f"Could not read the bundle: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except BundleValidationError as exc:
        typer.echo(f"Bundle is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Bundle at {bundle_dir} is valid "
        f"(release {manifest.benchmark_release}, {len(manifest.files)} file(s))."
    )
    typer.echo(f"  layers: {', '.join(manifest.layers)}")
    typer.echo(f"  bundle fingerprint: {manifest.bundle_fingerprint}")
    typer.echo(f"  environment fingerprint: {manifest.environment_fingerprint}")
    for name, record in sorted(manifest.adapters.items()):
        typer.echo(f"  adapter {name}: {record.get('mode', '')} at {record.get('path', '')}")


@app.command(name="export-datahub")
def export_datahub_command(
    bundle_dir: Annotated[
        Path,
        typer.Option("--bundle", help="Directory containing a benchmark bundle."),
    ] = DEFAULT_BUNDLE_DIR,
    mode: Annotated[
        ExportMode,
        typer.Option(
            "--mode",
            help="observed = what an agent under test may see; truth = privileged ground truth.",
        ),
    ] = ExportMode.OBSERVED,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the DataHub export into."),
    ] = DEFAULT_DATAHUB_EXPORT_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Emit deterministic DataHub metadata from a verified benchmark bundle.

    No DataHub server, token or network access is involved: the command writes
    the Metadata Change Proposals DataHub's file source ingests, plus a ready-to-
    run recipe that reads credentials from the environment.

    ``--mode observed`` (the default) is built from the observed catalogue graph
    alone and contains no ground truth. ``--mode truth`` is a privileged export
    for benchmark administration: it is tagged and manifested as such.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the bundle it reads.

    Exit codes: 0 = written, 1 = the emitted payload failed validation,
    2 = the bundle could not be read or an unsafe/non-empty output directory was
    given.
    """
    _prepare_output_dir_or_exit(
        output_dir,
        {CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR, BUNDLE_INPUT_LABEL: bundle_dir},
        force=force,
    )

    # Validate the payload before anything is written, so a mapping fault never
    # replaces a previous, sound export.
    try:
        with BundleReader.open(bundle_dir) as reader:
            problems = validate_export(build_mcps(build_source(reader, mode)), mode)
    except BundleConfigError as exc:
        typer.echo(f"Could not read the bundle: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except BundleValidationError as exc:
        typer.echo(f"Bundle is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=2) from exc
    if problems:
        typer.echo(f"DataHub export is invalid — {len(problems)} problem(s):", err=True)
        for problem in problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(code=1)

    manifest = export_datahub(bundle_dir, output_dir, mode=mode)
    counts = manifest["counts"]
    typer.echo(f"DataHub export written to {output_dir} (mode {manifest['mode']}).")
    if manifest["privileged"]:
        typer.echo("  PRIVILEGED: this export carries benchmark ground truth.")
    typer.echo(f"  entities: {counts['entities']}")
    typer.echo(f"  aspects: {counts['aspects']}")
    for entity_type, count in counts["by_entity_type"].items():
        typer.echo(f"    {entity_type}: {count}")


@app.command(name="export-openmetadata")
def export_openmetadata_command(
    bundle_dir: Annotated[
        Path,
        typer.Option("--bundle", help="Directory containing a benchmark bundle."),
    ] = DEFAULT_BUNDLE_DIR,
    mode: Annotated[
        OpenMetadataExportMode,
        typer.Option(
            "--mode",
            help="observed = what an agent under test may see; truth = privileged ground truth.",
        ),
    ] = OpenMetadataExportMode.OBSERVED,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the OpenMetadata export into."),
    ] = DEFAULT_OPENMETADATA_EXPORT_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Emit a deterministic OpenMetadata load plan from a verified benchmark bundle.

    No OpenMetadata server, token or network access is involved: the command
    writes the ordered ``Create<Entity>`` plan, the lineage and deferred-result
    plans, and the mapping-coverage report. The emitted JSONL is the interchange
    contract — there is no ingestion command yet, and this project has never
    loaded the plan into a running OpenMetadata instance, so no live
    compatibility is claimed.

    ``--mode observed`` (the default) is built from the observed catalogue graph
    alone and contains no ground truth. ``--mode truth`` is a privileged export
    for benchmark administration: it is tagged, propertied and manifested as such.

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the bundle it reads.

    Exit codes: 0 = written, 1 = the emitted plan failed validation,
    2 = the bundle could not be read or an unsafe/non-empty output directory was
    given.
    """
    _prepare_output_dir_or_exit(
        output_dir,
        {CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR, BUNDLE_INPUT_LABEL: bundle_dir},
        force=force,
    )

    # Validate the plan before anything is written, so a mapping fault never
    # replaces a previous, sound export.
    try:
        with BundleReader.open(bundle_dir) as reader:
            problems = validate_openmetadata_plan(
                build_plan(build_openmetadata_source(reader, mode))
            )
    except BundleConfigError as exc:
        typer.echo(f"Could not read the bundle: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except BundleValidationError as exc:
        typer.echo(f"Bundle is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=2) from exc
    if problems:
        typer.echo(f"OpenMetadata export is invalid — {len(problems)} problem(s):", err=True)
        for problem in problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(code=1)

    manifest = run_openmetadata_export(bundle_dir, output_dir, mode=mode)
    counts = manifest["counts"]
    typer.echo(f"OpenMetadata export written to {output_dir} (mode {manifest['mode']}).")
    if manifest["privileged"]:
        typer.echo("  PRIVILEGED: this export carries benchmark ground truth.")
    typer.echo(f"  plan records: {counts['records']}")
    typer.echo(f"  custom properties: {counts['custom_properties']}")
    typer.echo(f"  entities: {counts['entities']}")
    typer.echo(f"  lineage edges: {counts['lineage_edges']}")
    typer.echo(f"  deferred test results: {counts['deferred_test_results']}")
    if VERIFIED_OPENMETADATA_VERSION is None:
        typer.echo(
            "  No live OpenMetadata compatibility point is claimed: this plan has never "
            "been loaded into a running instance by this project."
        )
    typer.echo(f"  mapping coverage: {output_dir / 'mapping-coverage.json'}")


def _load_export_or_exit(export_dir: Path) -> LoadedExport:
    """Read and fully verify an emitted DataHub export, or exit with code 2."""
    try:
        return load_export(export_dir)
    except DataHubConfigError as exc:
        typer.echo(f"Could not read the DataHub export: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@app.command(name="ingest-datahub")
def ingest_datahub_command(
    export_dir: Annotated[
        Path,
        typer.Option("--export-dir", help="Directory containing an emitted DataHub export."),
    ] = DEFAULT_DATAHUB_EXPORT_DIR,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", help="Proposals per transmitted batch."),
    ] = DEFAULT_BATCH_SIZE,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would be sent. Performs no network activity."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm transmission to the configured catalogue."),
    ] = False,
    privileged_ack: Annotated[
        bool,
        typer.Option(
            "--i-understand-this-is-ground-truth",
            help="Required to transmit a privileged truth-mode export.",
        ),
    ] = False,
) -> None:
    """Transmit an emitted DataHub export to a live catalogue.

    The export is verified first — digests, payload validity, proposal
    uniqueness and privilege mode — and then transmitted. Nothing is regenerated,
    no bundle is opened and no benchmark ground truth is consulted: the emitted
    export is the whole input.

    Ingestion does not remap, synthesize, enrich or reinterpret emitted metadata.
    Entity identity, entity type, aspect identity and semantic aspect content are
    preserved; the transport alone encodes that content into the wire
    representation the DataHub API requires.

    ``--dry-run`` performs **no network activity at all**. It reads and verifies
    the export, builds the transmission batches and reports them; it opens no
    socket and makes no health or connectivity check.

    Credentials are read from the environment only, never from the command
    line: ``DATAHUB_GMS_URL`` and, if your instance needs one,
    ``DATAHUB_GMS_TOKEN``.

    Exit codes: 0 = transmitted (or planned, for a dry run), 1 = the export is
    valid but transmission was refused for want of confirmation, 2 = the export
    could not be read or the catalogue could not be reached.
    """
    export = _load_export_or_exit(export_dir)
    try:
        plan = plan_ingestion(export, batch_size)
    except DataHubConfigError as exc:
        typer.echo(f"Cannot plan ingestion: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"DataHub export {export_dir} (mode {export.mode.value}) verified.")
    typer.echo(f"  proposals: {plan.proposal_count}")
    typer.echo(f"  batches: {len(plan.batches)} of at most {batch_size}")
    typer.echo(f"  payload digest: {export.payload_digest}")

    if dry_run:
        typer.echo("Dry run: nothing was transmitted and no connection was opened.")
        return

    if export.privileged:
        typer.echo("", err=True)
        typer.echo(
            "PRIVILEGED EXPORT: this payload carries benchmark ground truth. Ingesting it "
            "into a shared catalogue publishes the answer key.",
            err=True,
        )
        if not privileged_ack:
            typer.echo(
                "Refusing to transmit a truth-mode export without "
                "--i-understand-this-is-ground-truth.",
                err=True,
            )
            raise typer.Exit(code=1)

    if not yes:
        typer.echo(
            "Refusing to transmit without --yes: ingestion writes to a system outside this "
            "repository.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        client = DataHubClient.from_environment()
        sent = execute_ingestion(plan, client)
    except DataHubConfigError as exc:
        typer.echo(f"Cannot reach a catalogue: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except DataHubTransportError as exc:
        typer.echo(f"Ingestion failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"Transmitted {sent} proposal(s) to {client.endpoint}.")
    typer.echo("Every proposal is an UPSERT, so re-running this command converges.")


@app.command(name="verify-ingestion")
def verify_ingestion_command(
    export_dir: Annotated[
        Path,
        typer.Option("--export-dir", help="Directory containing the emitted DataHub export."),
    ] = DEFAULT_DATAHUB_EXPORT_DIR,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the round-trip report into."),
    ] = DEFAULT_ROUNDTRIP_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Read a catalogue back and compare it against an emitted DataHub export.

    Four claims are judged and reported separately: completeness (every
    proposal is retrievable), fidelity (each aspect is semantically unchanged
    under the versioned normalization contract), containment (no DataSwamp
    aspect or entity the export never contained) and — for an observed export —
    non-leakage of benchmark ground truth.

    The export is the only statement of what should be there. No bundle, defect
    ledger, rule scope, scenario, expected finding or control partition is
    opened, so this command is unprivileged by construction.

    Exit codes: 0 = clean, 1 = discrepancies or leak findings were reported,
    2 = the export could not be read, the catalogue could not be reached, or an
    unsafe/non-empty output directory was given.
    """
    _prepare_output_dir_or_exit(
        output_dir,
        {
            CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR,
            DATAHUB_EXPORT_INPUT_LABEL: export_dir,
        },
        force=force,
    )
    export = _load_export_or_exit(export_dir)

    try:
        client = DataHubClient.from_environment()
        readback = read_back(export, client)
    except DataHubConfigError as exc:
        typer.echo(f"Cannot reach a catalogue: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except DataHubTransportError as exc:
        typer.echo(f"Readback failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    result = compare(list(export.proposals), readback, export.mode)
    report = write_roundtrip(output_dir, result, export, client.endpoint)

    typer.echo(f"Round-trip report written to {output_dir}.")
    for name, claim in report["claims"].items():
        typer.echo(f"  {name}: {claim['status']}")
    total = report["discrepancies"]["total"]
    leaks = report["claims"]["non-leakage"]["findings"]
    typer.echo(f"  discrepancies: {total}")
    typer.echo(f"  leak findings: {leaks}")
    unavailable = sorted(
        family
        for family, coverage in report["claims"]["containment"]["entity_family_coverage"].items()
        if coverage != "scanned"
    )
    if unavailable:
        typer.echo(
            "  extra-entity coverage unavailable for: " + ", ".join(unavailable),
        )
    if total or leaks:
        raise typer.Exit(code=1)


def _load_om_export_or_exit(export_dir: Path) -> LoadedOpenMetadataExport:
    """Read and fully verify an emitted OpenMetadata export, or exit with code 2."""
    try:
        return load_openmetadata_export(export_dir)
    except OpenMetadataConfigError as exc:
        typer.echo(f"Could not read the OpenMetadata export: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@app.command(name="ingest-openmetadata")
def ingest_openmetadata_command(
    export_dir: Annotated[
        Path,
        typer.Option("--export-dir", help="Directory containing an emitted OpenMetadata export."),
    ] = DEFAULT_OPENMETADATA_EXPORT_DIR,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would be sent. Performs no network activity."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm transmission to the configured catalogue."),
    ] = False,
    privileged_ack: Annotated[
        bool,
        typer.Option(
            "--i-understand-this-is-ground-truth",
            help="Required to transmit a privileged truth-mode export.",
        ),
    ] = False,
) -> None:
    """Replay an emitted OpenMetadata export into a live catalogue.

    The export is verified first — every manifest digest, the declared mode and
    its privilege flag, and the offline plan validator's full set of checks
    including FQN uniqueness, reference closure and load ordering — and only then
    replayed. Nothing is regenerated, no bundle is opened and no benchmark ground
    truth is consulted: the emitted export is the whole input.

    Replay preserves the emitted order exactly. OpenMetadata's model is
    order-dependent — a container needs its parent, an extension key needs its
    custom property, a lineage edge needs both endpoints — so the plan is never
    sorted, grouped or batched for convenience. The transport resolves the
    references the export declares as unresolvable offline, and changes nothing
    else.

    ``--dry-run`` performs **no network activity at all**. It reads and verifies
    the export, builds the replay plan and reports it; it opens no socket and
    makes no health or connectivity check.

    Credentials are read from the environment only, never from the command line:
    ``OPENMETADATA_HOST_PORT`` and, if your instance needs one,
    ``OPENMETADATA_JWT_TOKEN``.

    No OpenMetadata release has ever accepted this export: the request shapes were
    read from upstream's resource classes and proved against an offline fake, and
    no compatibility point is claimed.

    Exit codes: 0 = replayed (or planned, for a dry run), 1 = the export is valid
    but transmission was refused for want of confirmation, 2 = the export could
    not be read or the catalogue could not be reached.
    """
    export = _load_om_export_or_exit(export_dir)
    try:
        plan = plan_openmetadata_ingestion(export)
    except OpenMetadataConfigError as exc:
        typer.echo(f"Cannot plan ingestion: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"OpenMetadata export {export_dir} (mode {export.mode.value}) verified.")
    typer.echo(f"  operations: {len(plan.operations)}")
    typer.echo(f"  to transmit: {plan.transmitted_count}")
    typer.echo(f"  blocked (no honest OpenMetadata target): {plan.blocked_count}")
    for kind, count in plan.counts_by_kind().items():
        typer.echo(f"    {kind}: {count}")

    if dry_run:
        typer.echo("Dry run: nothing was transmitted and no connection was opened.")
        return

    if export.privileged:
        typer.echo("", err=True)
        typer.echo(
            "PRIVILEGED EXPORT: this plan carries benchmark ground truth. Loading it into "
            "a shared catalogue publishes the answer key.",
            err=True,
        )
        if not privileged_ack:
            typer.echo(
                "Refusing to transmit a truth-mode export without "
                "--i-understand-this-is-ground-truth.",
                err=True,
            )
            raise typer.Exit(code=1)

    if not yes:
        typer.echo(
            "Refusing to transmit without --yes: ingestion writes to a system outside this "
            "repository.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        client = OpenMetadataClient.from_environment()
        sent = execute_openmetadata_ingestion(plan, client)
    except OpenMetadataConfigError as exc:
        typer.echo(f"Cannot reach a catalogue: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except OpenMetadataTransportError as exc:
        typer.echo(f"Ingestion failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"Replayed {sent} operation(s) to {client.endpoint}.")
    typer.echo("Every write is a create-or-update, so re-running this command converges.")


@app.command(name="verify-om-ingestion")
def verify_om_ingestion_command(
    export_dir: Annotated[
        Path,
        typer.Option("--export-dir", help="Directory containing the emitted OpenMetadata export."),
    ] = DEFAULT_OPENMETADATA_EXPORT_DIR,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the round-trip report into."),
    ] = DEFAULT_OM_ROUNDTRIP_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Read an OpenMetadata catalogue back and compare it against an emitted export.

    Four claims are judged and reported separately: completeness (every emitted
    operation that should materialise did), fidelity (every value the export sent
    survives a normalization-equivalent readback), containment (no unexpected
    DataSwamp-owned state within scopes where ownership can be proved) and — for
    an observed export — non-leakage of benchmark ground truth.

    Containment coverage is declared per entity family rather than claimed
    uniformly, and reported as unavailable where DataSwamp ownership cannot be
    established. An entity outside every ownership rule is somebody else's and is
    never reported as a DataSwamp extra.

    The export is the only statement of what should be there. No bundle, defect
    ledger, rule scope, scenario, expected finding or control partition is opened,
    so this command is unprivileged by construction.

    Exit codes: 0 = all four claims pass, 1 = discrepancies or leak findings were
    reported, 2 = the export could not be read, the catalogue could not be
    reached, or an unsafe/non-empty output directory was given.
    """
    _prepare_output_dir_or_exit(
        output_dir,
        {
            CONFIG_INPUT_LABEL: DEFAULT_CONFIG_DIR,
            OPENMETADATA_EXPORT_INPUT_LABEL: export_dir,
        },
        force=force,
    )
    export = _load_om_export_or_exit(export_dir)

    try:
        client = OpenMetadataClient.from_environment()
        readback = read_back_openmetadata(export, client)
    except OpenMetadataConfigError as exc:
        typer.echo(f"Cannot reach a catalogue: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except OpenMetadataTransportError as exc:
        typer.echo(f"Readback failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    result = compare_openmetadata(export.records, readback, export.mode)
    report = write_openmetadata_roundtrip(output_dir, result, export)

    typer.echo(f"OpenMetadata round-trip report written to {output_dir}.")
    for name, claim in report["claims"].items():
        typer.echo(f"  {name}: {claim['status']}")
    total = report["discrepancies"]["total"]
    leaks = report["claims"]["non-leakage"]["findings"]
    typer.echo(f"  discrepancies: {total}")
    typer.echo(f"  leak findings: {leaks}")
    unavailable = sorted(
        family
        for family, coverage in report["claims"]["containment"]["entity_family_coverage"].items()
        if coverage == "unavailable"
    )
    if unavailable:
        typer.echo("  extra-entity coverage unavailable for: " + ", ".join(unavailable))
    if VERIFIED_OPENMETADATA_VERSION is None:
        typer.echo(
            "  No live OpenMetadata compatibility point is claimed: no pinned real-server "
            "canary has run against this adapter."
        )
    if total or leaks:
        raise typer.Exit(code=1)


@app.command(name="demo")
def demo(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the whole demo into."),
    ] = DEFAULT_DEMO_DIR,
    predictions: Annotated[
        Path | None,
        typer.Option(
            "--predictions",
            help="Submission to score; defaults to the packaged 'partial' example.",
        ),
    ] = None,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Run the whole benchmark workflow end to end into one directory.

    Generates the canonical scenario (truth graph, file estate, observed state),
    scores a prediction file against it, packages and verifies a portable
    bundle, and emits the observed DataHub metadata — the same code paths the
    individual commands use, in the order the documentation describes them.

    Everything is deterministic and offline: no seed, credential, network access
    or DataHub server is involved, and re-running into a fresh directory
    reproduces identical benchmark bytes.

    Exit codes: 0 = complete, 1 = a generated or emitted artefact failed its own
    validation, 2 = an input could not be read, or an unsafe/non-empty output
    directory was given.
    """
    config_dir = resolve_config_dir(config_dir)
    submission = predictions if predictions is not None else example_path()

    _prepare_output_dir_or_exit(
        output_dir,
        {CONFIG_INPUT_LABEL: config_dir, PREDICTIONS_INPUT_LABEL: submission},
        force=force,
    )
    if not submission.is_file():
        typer.echo(f"Could not read predictions: no such file: {submission}", err=True)
        raise typer.Exit(code=2)

    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)

    generated = output_dir / "generated"
    truth_dir = generated / TRUTH_DIRNAME
    estate_dir = generated / ESTATE_DIRNAME
    observed_dir = generated / OBSERVED_DIRNAME
    evaluation_dir = generated / "evaluation"
    bundle_dir = output_dir / "bundle"
    datahub_dir = output_dir / "export" / "datahub"

    typer.echo(f"[1/5] Generating the canonical scenario into {generated} ...")
    generate_canonical(generated, config, plan)

    typer.echo(f"[2/5] Scoring {submission} ...")
    summary = _score_or_exit(observed_dir, submission, evaluation_dir)

    typer.echo(f"[3/5] Packaging a bundle into {bundle_dir} ...")
    build_bundle(
        bundle_dir,
        sources={
            Layer.TRUTH: truth_dir,
            Layer.ESTATE: estate_dir,
            Layer.OBSERVED: observed_dir,
            Layer.EVALUATION: evaluation_dir,
        },
    )

    typer.echo("[4/5] Verifying the bundle ...")
    try:
        manifest = verify_bundle(bundle_dir, strict=True)
    except BundleValidationError as exc:
        typer.echo(f"Bundle is invalid — {len(exc.issues)} issue(s):", err=True)
        for bundle_issue in exc.issues:
            typer.echo(f"  - {bundle_issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[5/5] Exporting observed DataHub metadata into {datahub_dir} ...")
    export = export_datahub(bundle_dir, datahub_dir, mode=ExportMode.OBSERVED)

    typer.echo("")
    typer.echo("Demo complete. Output:")
    typer.echo(f"  truth graph        {truth_dir}")
    typer.echo(f"  file estate        {estate_dir}")
    typer.echo(f"  observed state     {observed_dir}")
    typer.echo(f"  evaluation report  {evaluation_dir / 'evaluation-report.md'}")
    typer.echo(f"  benchmark bundle   {bundle_dir}")
    typer.echo(f"  DataHub metadata   {datahub_dir}")
    typer.echo("")
    typer.echo(f"Scored submission: {submission}")
    _echo_scorecard(summary)
    typer.echo(f"Bundle fingerprint: {manifest.bundle_fingerprint}")
    typer.echo(f"DataHub entities:   {export['counts']['entities']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
