"""Benchmark run comparison: what changed between two evaluated submissions.

The evaluator scores one submission against one ground truth. This layer answers
the question that follows it — *did my change help?* — by differencing two
already-emitted evaluation directories.

It is strictly downstream of the evaluation contract. It re-scores nothing,
reads no prediction file, never opens the observed ground truth or the privileged
answer key, and never writes to either input. Depends only on ``company/``,
``truth/`` (for the shared serializer) and ``evaluation/`` — never on DataHub.

See ``docs/run-comparison.md``.
"""

from dataswamp_biosystems.comparison.deltas import (
    IMPROVED,
    REGRESSED,
    UNCHANGED,
    UNDEFINED,
    count_delta,
    error_count_delta,
    higher_is_better,
    metric_block_delta,
    metric_delta,
    success_count_delta,
)
from dataswamp_biosystems.comparison.engine import (
    COMPARATOR_VERSION,
    COMPARED_METRICS,
    COMPARISON_SCHEMA_VERSION,
    ComparisonResult,
    compare_runs,
    has_regressions,
)
from dataswamp_biosystems.comparison.entities import (
    ControlRegressionRecord,
    PairTransition,
    PairTransitionRecord,
    RemediationRegressionRecord,
    RemediationTransition,
    RuleRegressionRecord,
    RuleStatus,
)
from dataswamp_biosystems.comparison.errors import (
    ComparisonConfigError,
    ComparisonError,
    IdentityMismatch,
    IncompatibleRunsError,
)
from dataswamp_biosystems.comparison.identity import (
    IDENTITY_FIELDS,
    benchmark_identity,
    check_compatible,
)
from dataswamp_biosystems.comparison.loader import REQUIRED_FILES, EvaluationRun, load_run
from dataswamp_biosystems.comparison.writer import (
    COMPARISON_REPORT_NAME,
    COMPARISON_SUMMARY_NAME,
    CONTROL_REGRESSIONS_NAME,
    METRIC_DELTAS_NAME,
    PAIR_TRANSITIONS_NAME,
    REMEDIATION_REGRESSIONS_NAME,
    RULE_REGRESSIONS_NAME,
    comparison_bytes,
    render_report,
    write_comparison,
)

__all__ = [
    "COMPARATOR_VERSION",
    "COMPARISON_SCHEMA_VERSION",
    "COMPARED_METRICS",
    "ComparisonResult",
    "compare_runs",
    "has_regressions",
    "ComparisonError",
    "ComparisonConfigError",
    "IncompatibleRunsError",
    "IdentityMismatch",
    "IDENTITY_FIELDS",
    "benchmark_identity",
    "check_compatible",
    "REQUIRED_FILES",
    "EvaluationRun",
    "load_run",
    "IMPROVED",
    "REGRESSED",
    "UNCHANGED",
    "UNDEFINED",
    "higher_is_better",
    "metric_delta",
    "count_delta",
    "error_count_delta",
    "success_count_delta",
    "metric_block_delta",
    "PairTransition",
    "RuleStatus",
    "RemediationTransition",
    "PairTransitionRecord",
    "RuleRegressionRecord",
    "ControlRegressionRecord",
    "RemediationRegressionRecord",
    "COMPARISON_SUMMARY_NAME",
    "METRIC_DELTAS_NAME",
    "PAIR_TRANSITIONS_NAME",
    "RULE_REGRESSIONS_NAME",
    "CONTROL_REGRESSIONS_NAME",
    "REMEDIATION_REGRESSIONS_NAME",
    "COMPARISON_REPORT_NAME",
    "render_report",
    "comparison_bytes",
    "write_comparison",
]
