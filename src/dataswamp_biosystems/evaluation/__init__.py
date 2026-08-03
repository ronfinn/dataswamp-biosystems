"""Deterministic benchmark evaluation: score an agent's predictions against ground truth.

The imperfection engine emits labelled ground truth — expected findings, expected
remediations, the control partition and per-rule scope. This layer consumes it
and computes *evidence*: confusion-matrix and remediation metrics, machine- and
human-readable, byte-identical for identical inputs.

It computes no opinion. There are no scoring weights, no readiness index and no
single composite score: the report keeps finding detection, control preservation,
remediation correctness, approval reasoning and non-remediation correctness as
five separate dimensions, because weighting them against each other is a
judgement this layer has no mandate to make.

Like every other layer it is catalogue-independent, never mutates its inputs, and
depends only on ``company``/``truth``/``observed``. See ``docs/evaluation.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.evaluation.engine import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATOR_VERSION,
    EvaluationResult,
    evaluate,
    prediction_digest,
)
from dataswamp_biosystems.evaluation.entities import (
    FindingResult,
    GroupMetricRecord,
    Outcome,
    RemediationResult,
    RemediationState,
)
from dataswamp_biosystems.evaluation.errors import (
    EvaluationConfigError,
    EvaluationError,
    PredictionIssue,
    PredictionIssueKind,
    PredictionValidationError,
)
from dataswamp_biosystems.evaluation.ground_truth import (
    GROUND_TRUTH_FILES,
    GroundTruth,
    ground_truth_fingerprint,
    load_ground_truth,
)
from dataswamp_biosystems.evaluation.metrics import (
    Counts,
    breakdown,
    macro_block,
    metric_block,
    metrics_from_counts,
    ratio,
)
from dataswamp_biosystems.evaluation.predictions import (
    PREDICTION_SCHEMA_VERSION,
    STATUS_ABSTAIN,
    STATUS_CLEAN,
    STATUS_FINDING,
    SUPPORTED_PREDICTION_SCHEMA_VERSIONS,
    PredictedRemediation,
    Prediction,
    load_predictions,
    parse_predictions,
)
from dataswamp_biosystems.evaluation.writer import (
    CATEGORY_METRICS_NAME,
    EVALUATION_REPORT_NAME,
    EVALUATION_SUMMARY_NAME,
    FINDING_RESULTS_NAME,
    REMEDIATION_RESULTS_NAME,
    RULE_METRICS_NAME,
    evaluation_bytes,
    render_report,
    write_evaluation,
)

__all__ = [
    "EVALUATOR_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationResult",
    "evaluate",
    "prediction_digest",
    "Outcome",
    "RemediationState",
    "FindingResult",
    "RemediationResult",
    "GroupMetricRecord",
    "EvaluationError",
    "EvaluationConfigError",
    "PredictionValidationError",
    "PredictionIssue",
    "PredictionIssueKind",
    "GROUND_TRUTH_FILES",
    "GroundTruth",
    "ground_truth_fingerprint",
    "load_ground_truth",
    "Counts",
    "ratio",
    "metrics_from_counts",
    "metric_block",
    "macro_block",
    "breakdown",
    "PREDICTION_SCHEMA_VERSION",
    "SUPPORTED_PREDICTION_SCHEMA_VERSIONS",
    "STATUS_FINDING",
    "STATUS_CLEAN",
    "STATUS_ABSTAIN",
    "Prediction",
    "PredictedRemediation",
    "parse_predictions",
    "load_predictions",
    "EVALUATION_SUMMARY_NAME",
    "FINDING_RESULTS_NAME",
    "REMEDIATION_RESULTS_NAME",
    "RULE_METRICS_NAME",
    "CATEGORY_METRICS_NAME",
    "EVALUATION_REPORT_NAME",
    "render_report",
    "evaluation_bytes",
    "write_evaluation",
]
