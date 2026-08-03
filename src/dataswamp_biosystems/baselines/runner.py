"""Run a baseline agent and write its submission.

The runner is the only part of the package that knows about the filesystem on
the *output* side, and it does three things: load the permitted observed input,
collect the agent's predictions in canonical order, and render them as JSONL.

Writing is atomic — the submission is staged beside its destination and moved
into place — so an interrupted run never leaves a half-written file that the
evaluator would then reject line by line.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dataswamp_biosystems.baselines.base import BaselineAgent, BaselineInfo
from dataswamp_biosystems.baselines.observed_input import ObservedInput
from dataswamp_biosystems.evaluation.predictions import Prediction

# The submission encoding, fixed here so every baseline writes byte-identically:
# UTF-8, one compact JSON object per line, keys sorted, newline-terminated.
_SEPARATORS = (",", ":")


@dataclass(frozen=True)
class BaselineRun:
    """What one baseline produced, before anything is written."""

    info: BaselineInfo
    predictions: tuple[Prediction, ...]
    #: Profile, seeds and generator versions read from the observed graph's meta.
    #: A baseline score is only comparable to another quoting the same values.
    scenario: dict[str, str]

    @property
    def prediction_count(self) -> int:
        return len(self.predictions)

    @property
    def rules_used(self) -> tuple[str, ...]:
        return tuple(sorted({p.rule_id for p in self.predictions if p.rule_id}))


def run_baseline(agent: BaselineAgent, observed: ObservedInput) -> BaselineRun:
    """Run ``agent`` over ``observed`` and return its predictions in canonical order."""
    predictions = tuple(agent.predict(observed))
    return BaselineRun(
        info=agent.info,
        predictions=predictions,
        scenario=observed.scenario,
    )


def render_predictions(predictions: tuple[Prediction, ...]) -> str:
    """Render predictions as JSONL. Deterministic for a given prediction list."""
    return "".join(
        json.dumps(
            prediction.model_dump(mode="json"),
            sort_keys=True,
            separators=_SEPARATORS,
            ensure_ascii=False,
        )
        + "\n"
        for prediction in predictions
    )


def write_predictions(run: BaselineRun, output_path: Path | str) -> Path:
    """Write ``run``'s submission to ``output_path`` atomically; return the path.

    An empty submission is a real submission — the null baseline's whole claim —
    so a zero-byte file is written rather than skipped.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = render_predictions(run.predictions).encode("utf-8")

    tmp = output_path.parent / f".{output_path.name}.tmp-{os.getpid()}"
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, output_path)
    finally:
        tmp.unlink(missing_ok=True)
    return output_path


def run_and_write(
    agent: BaselineAgent,
    observed_dir: Path | str,
    output_path: Path | str,
) -> BaselineRun:
    """Load the observed input, run ``agent``, and write the submission."""
    run = run_baseline(agent, ObservedInput.load(observed_dir))
    write_predictions(run, output_path)
    return run


__all__ = [
    "BaselineRun",
    "render_predictions",
    "run_and_write",
    "run_baseline",
    "write_predictions",
]
