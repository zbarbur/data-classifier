# gliner_onnx/ — empty by design

This directory is intentionally empty in the source tree. It exists so
that the ``models/gliner_onnx/*`` glob in ``pyproject.toml``'s
``[tool.setuptools.package-data]`` has a matching directory when the
wheel is built, which in turn lets the wheel ship any ONNX model files
that downstream consumers bake in at build time (see below).

## Where the model actually comes from

The GLiNER2 ONNX model (~350 MB) is **not** bundled in the git repo and
is **not** shipped in the PyPI / GitHub wheels — it is distributed as a
separate tarball via Google Artifact Registry. Production containers
download and unpack it at image build time by running:

```bash
python -m data_classifier.download_models
# or equivalently after pip install:
data-classifier-download-models
```

This fetches
``gliner_onnx-<version>.tar.gz`` from the
``data-classifier-models`` Artifact Registry Generic repo, verifies its
SHA-256 checksum, and unpacks the contents into
``~/.cache/data_classifier/models/gliner_onnx/``. The
``GLiNER2Engine._find_bundled_onnx_model()`` auto-discovery logic then
finds the model at that path with no environment variable or config
change required.

## Why not vendor the ONNX files here?

1. **Size** — a 350 MB artifact would bloat every wheel download and
   inflate git-history footprint, even for users who never touch the
   ML engine.
2. **Licensing/provenance** — the model is re-exportable from the
   upstream HuggingFace weights, so distributing it alongside the
   library conflates two separate artifact lifecycles.
3. **Cloud Run cold-start rate limits** — downloading from HuggingFace
   on every container start hit HTTP 429 rate limits in production.
   Baking the model into the image at build time via the CLI avoids
   this entirely.

See ``docs/CLIENT_INTEGRATION_GUIDE.md`` section 1c for the full
Dockerfile recipe.
