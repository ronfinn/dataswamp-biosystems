"""Command-line interface for Data Swamp Biosystems."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from dataswamp_biosystems import __version__
from dataswamp_biosystems.company import (
    DEFAULT_CONFIG_DIR,
    CanonicalConfig,
    ConfigLoadError,
    ConfigValidationError,
    load_config,
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
from dataswamp_biosystems.observed import (
    DEFECTS,
    ObservedConfigError,
    ObservedProfile,
    ObservedValidationError,
    TruthImmutabilityError,
    contract_coverage,
    read_observed_meta,
    registry_rows,
    resolve_truth_dir,
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

# The observed state is a required *input* to evaluation, so it joins the config
# and truth directories as a protected path — an evaluation run must never be
# able to replace the ground truth it is scored against.
OBSERVED_INPUT_LABEL = "observed ground-truth directory"
# The prediction *file* is protected, not its parent directory: protecting the
# parent would reject every output under the repository whenever a submission
# sits at the repository root, while protecting the file still rejects an output
# directory that is, or contains, the submission being scored.
PREDICTIONS_INPUT_LABEL = "prediction file"


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
    if as_json:
        # Coverage travels with the rules so a consumer can see which benchmark
        # states the catalogue exercises without re-deriving it from the rows.
        payload = {"rules": rows, "contract_state_coverage": contract_coverage()}
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
            f"  {row['rule_id']} [{row['category']}/{row['severity']}] {row['title']}{flag_text}"
        )
    typer.echo("Rules by category:")
    for category in sorted(by_category):
        typer.echo(f"  {category}: {by_category[category]}")
    typer.echo("Rules by contract state:")
    for state, rule_ids in contract_coverage().items():
        typer.echo(f"  {state}: {len(rule_ids)}")


@app.command(name="validate-defects")
def validate_defects() -> None:
    """Validate the defect-rule registry and its remediation contracts.

    Checks structural well-formedness, that every rule's remediation contract is
    internally consistent (remediation availability and approval policy are
    independent, so neither may be inferred from the other), and that the
    catalogue collectively covers every benchmark contract state. Requires no
    generated benchmark output.

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

    ``output_dir`` is replaced wholesale, so it may not be, contain, or sit
    inside the configuration directory or the truth directory it reads from.

    Exit codes: 0 = written, 1 = invalid config/plan, failed generation checks,
    or a truth-immutability breach, 2 = the truth graph could not be read, or an
    unsafe/non-empty output directory was given.
    """
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

    try:
        report = run_defect_injection(truth, config, plan, profile, resolved_seed, output_dir)
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
        f"(profile {profile.value}, defect seed {resolved_seed})."
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

    try:
        truth = load_ground_truth(observed_dir)
    except EvaluationConfigError as exc:
        typer.echo(f"Could not read ground truth: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    try:
        submitted, raw = load_predictions(
            predictions,
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
    summary = write_evaluation(result, output_dir)

    micro = summary["findings"]["overall_micro"]
    counts = micro["counts"]
    metrics = micro["metrics"]

    def show(name: str) -> str:
        value = metrics[name]["value"]
        return "n/a" if value is None else f"{value:.4f}"

    typer.echo(
        f"Evaluation written to {output_dir} "
        f"(profile {summary['benchmark']['profile']}, "
        f"{summary['submission']['predictions']} prediction(s))."
    )
    typer.echo(
        f"  pairs: {summary['universe']['evaluated_pairs']} "
        f"({counts['positives']} positive, {counts['negatives']} negative)"
    )
    typer.echo(f"  TP {counts['tp']}  FP {counts['fp']}  FN {counts['fn']}  TN {counts['tn']}")
    typer.echo(
        f"  precision {show('precision')}  recall {show('recall')}  "
        f"specificity {show('specificity')}  F1 {show('f1')}"
    )
    typer.echo(
        f"  reserved-control false positives: {summary['reserved_controls']['false_positives']}"
    )
    typer.echo(f"  out-of-scope false positives: {summary['out_of_scope']['false_positives']}")
    typer.echo(
        f"  remediations: {summary['remediation']['counts']['submitted']} submitted, "
        f"{summary['remediation']['counts']['fully_correct']} fully correct, "
        f"{summary['remediation']['counts']['unsafe_actions']} unsafe"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
