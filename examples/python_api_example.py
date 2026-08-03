#!/usr/bin/env python
"""Read a benchmark bundle and score a submission, through the Python API.

The CLI is the primary interface, but everything it does is available as a
library. This script uses only the interfaces listed as stable in
``docs/public-api.md``:

* :func:`dataswamp_biosystems.bundle.verify_bundle` — verify before trusting;
* :class:`dataswamp_biosystems.bundle.BundleReader` — stream a bundle's layers;
* :func:`dataswamp_biosystems.evaluation.load_ground_truth` — the answer key;
* :func:`dataswamp_biosystems.evaluation.load_predictions` — parse and validate;
* :func:`dataswamp_biosystems.evaluation.evaluate` — score.

Usage::

    dataswamp demo --output-dir ./dataswamp-demo
    python examples/python_api_example.py ./dataswamp-demo/bundle
"""

from __future__ import annotations

import sys
from pathlib import Path

from dataswamp_biosystems.bundle import BundleReader, Layer, verify_bundle
from dataswamp_biosystems.evaluation import (
    evaluate,
    load_ground_truth,
    load_predictions,
    prediction_digest,
)
from dataswamp_biosystems.examples import example_path


def main(bundle_dir: Path, predictions_path: Path) -> int:
    # 1. Verify before reading. A bundle is only worth reading if its manifest,
    #    checksums and structure all check out.
    manifest = verify_bundle(bundle_dir, strict=True)
    print(f"bundle {manifest.benchmark_release}: {len(manifest.files)} file(s)")
    print(f"  layers: {', '.join(manifest.layers)}")
    print(f"  fingerprint: {manifest.bundle_fingerprint}")

    # 2. Stream what it carries. The reader never loads a whole layer into
    #    memory; every iter_* method is a generator.
    with BundleReader.open(bundle_dir) as reader:
        assets = sum(1 for _ in reader.iter_assets())
        controls = sum(1 for _ in reader.iter_controls())
        rules = reader.rule_scope()
        print(f"  assets: {assets}   control entities: {controls}   rules: {len(rules)}")

        if reader.has_layer(Layer.ESTATE):
            print(f"  materialized files: {sum(1 for _ in reader.iter_files())}")

    # 3. Load the answer key and score a submission against it. Ground truth is
    #    read-only here: scoring never regenerates or rewrites it.
    observed_dir = bundle_dir / "observed"
    truth = load_ground_truth(observed_dir)
    submitted, raw = load_predictions(
        predictions_path,
        known_entities=truth.known_entities,
        known_rules=truth.rule_ids,
    )
    result = evaluate(truth, submitted, prediction_digest=prediction_digest(raw))

    micro = result.summary["findings"]["overall_micro"]
    counts, metrics = micro["counts"], micro["metrics"]

    def show(name: str) -> str:
        value = metrics[name]["value"]
        # An undefined metric is null, never 0.0 — reporting it as zero would
        # misrepresent "no denominator" as "scored badly".
        return "n/a" if value is None else f"{value:.4f}"

    print(f"\nscored {predictions_path.name}: {len(submitted)} prediction(s)")
    print(f"  TP {counts['tp']}  FP {counts['fp']}  FN {counts['fn']}  TN {counts['tn']}")
    print(f"  precision {show('precision')}  recall {show('recall')}  F1 {show('f1')}")
    print(
        f"  reserved-control false positives: "
        f"{result.summary['reserved_controls']['false_positives']}"
    )
    print(f"  unsafe remediations: {result.summary['remediation']['counts']['unsafe_actions']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    bundle = Path(sys.argv[1])
    predictions = Path(sys.argv[2]) if len(sys.argv) > 2 else example_path("partial")
    raise SystemExit(main(bundle, predictions))
