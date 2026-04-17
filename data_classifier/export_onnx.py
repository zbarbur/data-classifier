"""Export GLiNER ONNX model to a standard location for auto-discovery.

This module is a thin wrapper around scripts/export_onnx_model.py that
writes the model to a location where GLiNER2Engine can auto-discover it.

Usage:
    # Export to the installed package's models/ directory (bundled)
    python -m data_classifier.export_onnx

    # Export to user cache (~/.cache/data_classifier/models/)
    python -m data_classifier.export_onnx --user

    # Export to a custom location
    python -m data_classifier.export_onnx --output /path/to/models

After export, any code that creates GLiNER2Engine() will auto-find the
model — no environment variables or explicit paths needed.

Requirements:
    pip install "data_classifier[ml-full]"  (torch + onnx for export)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export GLiNER model to auto-discovered location")
    parser.add_argument(
        "--user",
        action="store_true",
        help="Export to user cache (~/.cache/data_classifier/models/gliner_onnx/)",
    )
    parser.add_argument(
        "--output",
        help="Custom output directory (overrides --user and default package location)",
    )
    parser.add_argument(
        "--model",
        default="urchade/gliner_multi_pii-v1",
        help="HuggingFace model ID (default: urchade/gliner_multi_pii-v1)",
    )
    parser.add_argument(
        "--no-quantize",
        action="store_true",
        help="Skip INT8 quantization (larger, slightly higher precision)",
    )
    args = parser.parse_args()

    # Determine output path
    if args.output:
        output_dir = Path(args.output)
    elif args.user:
        output_dir = Path.home() / ".cache" / "data_classifier" / "models" / "gliner_onnx"
    else:
        # Default: package's bundled models/ directory
        import data_classifier

        output_dir = Path(data_classifier.__file__).parent / "models" / "gliner_onnx"

    output_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        import onnx  # noqa: F401
    except ImportError:
        logger.error("onnx package required. Install with: pip install 'data_classifier[ml-full]'")
        sys.exit(1)

    try:
        from gliner import GLiNER
    except ImportError:
        logger.error("gliner package required. Install with: pip install 'data_classifier[ml-full]'")
        sys.exit(1)

    logger.info("Loading model: %s", args.model)
    model = GLiNER.from_pretrained(args.model)

    logger.info("Exporting to ONNX: %s", output_dir)
    quantize = not args.no_quantize
    model.export_to_onnx(str(output_dir), quantize=quantize)

    logger.info("Export complete. Contents:")
    total_mb = 0.0
    for name in sorted(output_dir.iterdir()):
        size_mb = name.stat().st_size / 1024 / 1024
        total_mb += size_mb
        logger.info("  %-40s %8.1f MB", name.name, size_mb)
    logger.info("  %-40s %8.1f MB", "TOTAL", total_mb)
    logger.info("")
    logger.info("GLiNER2Engine() will now auto-discover this model at startup.")


if __name__ == "__main__":
    main()
