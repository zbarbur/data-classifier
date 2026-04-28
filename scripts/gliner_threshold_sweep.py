"""GLiNER threshold sweep — Sprint 16 Item 2.

Runs the family benchmark at multiple GLiNER thresholds to find the
optimal value for CONTACT family recall without regressing other families.

Usage:
    .venv/bin/python scripts/gliner_threshold_sweep.py

Requires ML extras (gliner, onnxruntime) and DVC-tracked corpora.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

# Thresholds to sweep
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50]


def run_sweep() -> None:
    # Import here so module-level engine init doesn't fire early
    import data_classifier
    from data_classifier.engines.gliner_engine import GLiNER2Engine

    # We need to re-build engines for each threshold.
    # Capture the baseline engine list (non-GLiNER engines).
    base_engines = [e for e in data_classifier._DEFAULT_ENGINES if not isinstance(e, GLiNER2Engine)]

    results: dict[float, dict] = {}

    for threshold in THRESHOLDS:
        print(f"\n{'=' * 60}")
        print(f"Threshold: {threshold}")
        print(f"{'=' * 60}")

        # Build a fresh GLiNER engine with this threshold
        import os

        onnx_path = os.environ.get("GLINER_ONNX_PATH")
        api_key = os.environ.get("GLINER_API_KEY")
        gliner_engine = GLiNER2Engine(
            onnx_path=onnx_path,
            api_key=api_key,
            gliner_threshold=threshold,
        )

        # Swap engines
        engines = base_engines + [gliner_engine]
        data_classifier._DEFAULT_ENGINES = engines

        # Run the family benchmark
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "predictions.jsonl"
            summary_path = Path(tmpdir) / "summary.json"

            from tests.benchmarks.family_accuracy_benchmark import main as bench_main

            bench_main(
                [
                    "--out",
                    str(out_path),
                    "--summary",
                    str(summary_path),
                ]
            )

            summary = json.loads(summary_path.read_text())
            results[threshold] = summary

    # Print comparison table
    print(f"\n{'=' * 80}")
    print("THRESHOLD SWEEP RESULTS")
    print(f"{'=' * 80}")

    # Extract family F1s
    families = set()
    for summary in results.values():
        for key in summary.get("shadow", {}).get("overall", {}).get("family", {}).get("per_family", {}):
            families.add(key)
        for key in summary.get("live", {}).get("overall", {}).get("family", {}).get("per_family", {}):
            families.add(key)

    # Use live path metrics
    header = f"{'Threshold':>10} | {'cross_family':>13} | {'family_f1':>10}"
    for fam in sorted(families):
        header += f" | {fam[:12]:>12}"
    print(header)
    print("-" * len(header))

    for threshold in THRESHOLDS:
        summary = results[threshold]
        live = summary.get("live", {}).get("overall", {}).get("family", {})
        cross = live.get("cross_family_rate", "?")
        macro = live.get("family_macro_f1", "?")
        row = f"{threshold:>10.2f} | {cross:>13.4f} | {macro:>10.4f}"
        per_fam = live.get("per_family", {})
        for fam in sorted(families):
            f1 = per_fam.get(fam, {}).get("f1", "?")
            if isinstance(f1, (int, float)):
                row += f" | {f1:>12.4f}"
            else:
                row += f" | {'?':>12}"
        print(row)

    # Save full results
    out_file = Path("docs/research/meta_classifier/sprint16_threshold_sweep.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    serializable = {str(k): v for k, v in results.items()}
    out_file.write_text(json.dumps(serializable, indent=2))
    print(f"\nFull results saved to {out_file}")


if __name__ == "__main__":
    run_sweep()
