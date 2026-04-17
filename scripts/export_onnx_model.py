"""Export GLiNER model to ONNX format for production deployment.

This script downloads the GLiNER model from HuggingFace, exports it to
quantized ONNX format, and saves it to a local directory.  The exported
model can then be used without torch or HuggingFace access at runtime.

Usage:
    # Export default PII model (quantized, ~350MB)
    python scripts/export_onnx_model.py

    # Export to custom directory
    python scripts/export_onnx_model.py --output models/gliner

    # Export a different model
    python scripts/export_onnx_model.py --model urchade/gliner_large-v2.1

    # Skip quantization (larger but higher precision)
    python scripts/export_onnx_model.py --no-quantize

After export, use the ONNX model:
    GLiNER2Engine(onnx_path="models/gliner_onnx")

Requirements:
    pip install gliner onnx  (only needed for export, not inference)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export GLiNER model to ONNX")
    parser.add_argument(
        "--model",
        default="fastino/gliner2-base-v1",
        help="HuggingFace model ID (default: fastino/gliner2-base-v1)",
    )
    parser.add_argument(
        "--output",
        default="models/gliner_onnx",
        help="Output directory (default: models/gliner_onnx)",
    )
    parser.add_argument(
        "--no-quantize",
        action="store_true",
        help="Skip INT8 quantization (larger model, slightly higher precision)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check dependencies
    try:
        import onnx  # noqa: F401
    except ImportError:
        print("ERROR: onnx package required for export. Run: pip install onnx", file=sys.stderr)
        sys.exit(1)

    from gliner import GLiNER

    # Load model
    print(f"Loading model: {args.model}", file=sys.stderr)
    t0 = time.monotonic()
    model = GLiNER.from_pretrained(args.model)
    print(f"  Loaded in {time.monotonic() - t0:.1f}s", file=sys.stderr)

    # Export to ONNX
    quantize = not args.no_quantize
    print(f"Exporting to ONNX (quantize={quantize})...", file=sys.stderr)
    t0 = time.monotonic()
    result = model.export_to_onnx(str(output_dir), quantize=quantize)
    print(f"  Exported in {time.monotonic() - t0:.1f}s", file=sys.stderr)

    # Report
    print(f"\nExport complete: {output_dir}", file=sys.stderr)
    for name in sorted(os.listdir(output_dir)):
        size_mb = os.path.getsize(output_dir / name) / 1024 / 1024
        print(f"  {name:40s} {size_mb:>8.1f} MB", file=sys.stderr)

    total_mb = sum(os.path.getsize(output_dir / f) for f in os.listdir(output_dir)) / 1024 / 1024
    print(f"  {'TOTAL':40s} {total_mb:>8.1f} MB", file=sys.stderr)

    if quantize and result.get("quantized_path"):
        print("\nUse in code:", file=sys.stderr)
        print(f'  GLiNER2Engine(onnx_path="{output_dir}")', file=sys.stderr)


if __name__ == "__main__":
    main()
