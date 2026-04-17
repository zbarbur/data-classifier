"""Lean, stdlib-only CLI to download a pre-exported GLiNER ONNX model tarball.

This module fetches a GLiNER2 ONNX model tarball from our Google Artifact
Registry Generic repo (or any HTTP(S) URL) and unpacks it into the
auto-discovery cache at ``~/.cache/data_classifier/models/gliner_onnx/``.
BQ's Dockerfile runs this at build time so the model is baked into the
container image, eliminating the HuggingFace runtime download that fails
on Cloud Run cold starts with 429 rate limit errors.

Runtime constraints
-------------------
This module must import cleanly in a Python environment with **only** the
``[ml]`` optional extras installed (onnxruntime + gliner). It must NOT
import ``torch``, ``transformers``, ``onnx``, ``requests``, or any other
heavy dependency. It uses only the Python standard library:

- ``urllib.request`` for HTTP(S) downloads (not ``requests``)
- ``hashlib`` for SHA-256 verification (not ``cryptography``)
- ``tarfile`` for archive extraction (stdlib only)
- ``importlib.metadata`` for version discovery

Usage
-----
::

    # As a module
    python -m data_classifier.download_models [--to PATH] [--version V] ...

    # As an installed console script
    data-classifier-download-models [--to PATH] [--version V] ...

The CLI is intentionally fail-fast: mismatched checksum, network errors,
and HTTP errors produce a single-line error message on stderr and a
non-zero exit code, never a raw traceback.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

#: Pinned GLiNER2 ONNX model version.
#:
#: **Decoupled from the ``data_classifier`` package version.** The ONNX
#: model is a separate build-time artifact derived from an upstream
#: HuggingFace checkpoint — it does not change when we rev the library.
#: The release pipeline publishes a new model tarball only when the
#: upstream base model changes (rarely — once every few quarters at
#: most), and existing ``data_classifier`` releases continue to consume
#: the pinned model until someone bumps this constant deliberately.
#:
#: The literal value encodes the upstream HuggingFace model ID
#: (``urchade/gliner_multi_pii-v1``) with slashes replaced by dashes for
#: filename compatibility.
DEFAULT_MODEL_VERSION = "urchade-gliner_multi_pii-v1"

#: Google Artifact Registry Generic repo URL template for the ONNX tarballs.
#:
#: Uses the Artifact Registry REST download endpoint with the
#: ``<package>:<version>:<filename>`` file ID format that AR Generic
#: repos produce. Authentication is via a GCP access token in the
#: ``Authorization: Bearer`` header — see :func:`_get_access_token` for
#: the discovery strategy.
#:
#: BQ's Cloud Build fetches this via its default service account token
#: from the metadata service (zero extra setup). Dev machines fall back
#: to ``gcloud auth print-access-token`` if gcloud is on PATH, or accept
#: an explicit ``--access-token`` CLI flag.
#:
#: The ``{version}`` placeholder is substituted with ``DEFAULT_MODEL_VERSION``
#: by default. Override the entire URL with ``--url`` for testing or
#: mirrors.
DEFAULT_URL_TEMPLATE = (
    "https://artifactregistry.googleapis.com/v1/projects/dag-bigquery-dev"
    "/locations/us-central1/repositories/data-classifier-models/files/"
    "gliner-onnx:{version}:gliner_onnx-{version}.tar.gz:download?alt=media"
)

#: Default cache root — matches ``gliner_engine._find_bundled_onnx_model``
#: search path 2 of 3, so the engine auto-discovers the unpacked model.
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "data_classifier" / "models" / "gliner_onnx"

#: GCP metadata server endpoint for fetching the default service account
#: access token. Only reachable from GCP compute environments (Cloud
#: Build, Cloud Run, Compute Engine). Returns quickly with a 404-ish
#: connection error outside GCP.
_METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"

#: Chunk size for streaming HTTP reads (64 KiB).
_CHUNK_BYTES = 64 * 1024

#: Marker file that must exist in the extracted directory for the engine
#: to auto-discover a GLiNER ONNX model.
_MARKER_FILE = "gliner_config.json"


class DownloadError(RuntimeError):
    """Raised for any recoverable download/extract failure.

    Keeps ``main()`` free of tracebacks — the handler catches this and
    prints only the stringified message on stderr.
    """


# ── Version discovery ───────────────────────────────────────────────────────


def _default_version() -> str:
    """Return the pinned GLiNER ONNX model version.

    Returns :data:`DEFAULT_MODEL_VERSION`, which is deliberately decoupled
    from the installed ``data_classifier`` package version — the ONNX
    model is a separate artifact with its own lifecycle. Pass
    ``--version`` to override and fetch a different model version (e.g.
    a dev-branch or pre-release model).
    """
    return DEFAULT_MODEL_VERSION


def _installed_package_version() -> str:
    """Return the installed ``data_classifier`` package version.

    Kept as a reference helper for callers that want to log or report
    the package version alongside the model version. Not used to derive
    the download URL.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover — stdlib on 3.8+
        return "unknown"

    try:
        return version("data_classifier")
    except PackageNotFoundError:
        return "unknown"


# ── Auth token discovery ────────────────────────────────────────────────────


def _get_access_token(explicit: str | None = None) -> str | None:
    """Obtain a GCP access token for Artifact Registry downloads.

    Discovery strategy (first hit wins):

    1. ``explicit`` argument — passed via ``--access-token`` CLI flag.
    2. ``GCP_ACCESS_TOKEN`` environment variable — for explicit CI setups.
    3. GCP metadata service — works on Cloud Build, Cloud Run, Compute
       Engine, and anywhere else the Google metadata server is
       reachable. This is the primary path for BQ's Dockerfile
       ``RUN python -m data_classifier.download_models`` step.
    4. ``gcloud auth print-access-token`` — fallback for dev machines
       that have the gcloud CLI installed. Skipped if ``gcloud`` is not
       on ``PATH`` to avoid a slow subprocess spawn on machines without
       it.

    Returns ``None`` if no token could be obtained. Callers may still
    proceed for public URLs (e.g. a mirror or ``--url`` override
    pointing at an unauthenticated HTTP endpoint).
    """
    import os

    if explicit:
        return explicit

    env_token = os.environ.get("GCP_ACCESS_TOKEN")
    if env_token:
        return env_token

    # Try the metadata service — this is the BQ Cloud Build path.
    try:
        req = urllib.request.Request(
            _METADATA_TOKEN_URL,
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2.0) as response:  # noqa: S310 — fixed metadata URL
            import json

            payload = json.loads(response.read().decode("utf-8"))
            token = payload.get("access_token")
            if token:
                return token
    except (urllib.error.URLError, OSError, ValueError):
        # Not on GCP compute, metadata unreachable, or malformed
        # response. Fall through to the gcloud path.
        pass

    # Last resort: shell out to gcloud if available.
    import shutil as _shutil
    import subprocess

    if _shutil.which("gcloud") is None:
        return None

    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
            return token or None
    except (OSError, subprocess.TimeoutExpired):
        pass

    return None


# ── URL helpers ─────────────────────────────────────────────────────────────


def _build_default_url(version: str) -> str:
    return DEFAULT_URL_TEMPLATE.format(version=version)


def _default_checksum_url(tarball_url: str) -> str:
    """Derive the SHA-256 checksum URL from a tarball URL.

    For the default Artifact Registry Generic REST endpoint, the
    checksum is a separate file artifact with ``.sha256`` appended to
    the tarball filename **before** the ``:download?alt=media``
    suffix — because the AR file-ID (``<package>:<version>:<name>``)
    includes the filename, and the ``:download`` action comes after.

    For plain HTTP URLs (mirrors, test fixtures, ``--url`` overrides
    pointing at a simple static host), we just append ``.sha256`` to
    the end.

    .. warning::
        The plain-URL branch does not handle query strings — a mirror
        URL like ``https://example.com/model.tar.gz?token=xyz`` would
        be rewritten to ``https://example.com/model.tar.gz?token=xyz.sha256``,
        which is broken. Pass ``--checksum-url`` explicitly when using
        a mirror that needs query-string auth.
    """
    ar_suffix = ":download?alt=media"
    if ar_suffix in tarball_url:
        prefix = tarball_url[: -len(ar_suffix)]
        return f"{prefix}.sha256{ar_suffix}"
    return tarball_url + ".sha256"


# ── HTTP ─────────────────────────────────────────────────────────────────────


def _build_request(url: str, access_token: str | None) -> urllib.request.Request:
    """Construct an HTTP request with optional Bearer auth.

    Private helper used by :func:`_http_get` and :func:`_http_get_text`
    to attach the Authorization header when an access token is
    available. Skipping auth on public URLs is intentional — the caller
    controls whether a token is present.
    """
    req = urllib.request.Request(url)
    if access_token:
        req.add_header("Authorization", f"Bearer {access_token}")
    return req


def _http_get(url: str, *, dest: Path, quiet: bool, access_token: str | None = None) -> None:
    """Download ``url`` to ``dest``, streaming in ``_CHUNK_BYTES`` blocks.

    Attaches a ``Bearer`` token when ``access_token`` is set — required
    for Google Artifact Registry downloads.

    Wraps low-level ``urllib`` exceptions in :class:`DownloadError` so
    ``main()`` can emit a clean one-line message.
    """
    try:
        req = _build_request(url, access_token)
        with urllib.request.urlopen(req) as response:  # noqa: S310 — URL is user-supplied CLI input
            total = response.getheader("Content-Length")
            total_bytes = int(total) if total and total.isdigit() else None
            bytes_read = 0
            with dest.open("wb") as out:
                while True:
                    chunk = response.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    out.write(chunk)
                    bytes_read += len(chunk)
                    if not quiet and total_bytes:
                        pct = 100.0 * bytes_read / total_bytes
                        logger.info("  downloaded %6.1f%% (%d / %d bytes)", pct, bytes_read, total_bytes)
    except urllib.error.HTTPError as exc:
        raise DownloadError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"network error fetching {url}: {exc.reason}") from exc
    except (OSError, ConnectionError) as exc:
        raise DownloadError(f"I/O error fetching {url}: {exc}") from exc


def _http_get_text(url: str, access_token: str | None = None) -> str:
    """Fetch ``url`` and return its body as a UTF-8 string.

    Attaches a ``Bearer`` token when ``access_token`` is set.
    """
    try:
        req = _build_request(url, access_token)
        with urllib.request.urlopen(req) as response:  # noqa: S310 — URL is user-supplied CLI input
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise DownloadError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"network error fetching {url}: {exc.reason}") from exc
    except (OSError, ConnectionError) as exc:
        raise DownloadError(f"I/O error fetching {url}: {exc}") from exc


# ── Checksum ────────────────────────────────────────────────────────────────


def _sha256_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of ``path``."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_BYTES), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _parse_checksum_body(body: str) -> str:
    """Extract a 64-char hex SHA-256 from a ``sha256sum``-style body.

    Accepts either the bare digest (``<hex>``) or the standard
    ``<hex>  <filename>`` layout. Raises :class:`DownloadError` if no
    valid digest is found.
    """
    stripped = body.strip()
    if not stripped:
        raise DownloadError("checksum file is empty")
    first_token = stripped.split()[0].lower()
    if len(first_token) != 64 or any(c not in "0123456789abcdef" for c in first_token):
        raise DownloadError(f"checksum file does not contain a valid SHA-256 digest (got {first_token!r})")
    return first_token


# ── Tar extraction ──────────────────────────────────────────────────────────


def _is_within_directory(directory: Path, target: Path) -> bool:
    """Return True iff ``target`` resolves to a path inside ``directory``.

    Used to block tar entries that attempt to escape the target dir via
    ``../`` traversal or absolute paths (CVE-2007-4559 style).
    """
    try:
        directory_resolved = directory.resolve()
        target_resolved = target.resolve()
    except (OSError, RuntimeError):
        return False
    return directory_resolved == target_resolved or directory_resolved in target_resolved.parents


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract ``tar`` into ``dest`` with path-traversal protection.

    On Python 3.12+ ``tarfile.data_filter`` provides a second line of
    defense that also blocks link members; on 3.11 that filter does not
    exist, so the pre-scan below is the only defense. We therefore
    reject symlink and hardlink members unconditionally on every Python
    version (Sprint 9 hardening — see backlog item
    ``tar-safety-on-python-3-11-...``).
    """
    for member in tar.getmembers():
        if member.issym() or member.islnk():
            raise DownloadError(f"Refusing to extract symlink/hardlink member: {member.name}")
        member_path = dest / member.name
        if not _is_within_directory(dest, member_path):
            raise DownloadError(f"tarball contains unsafe path outside destination: {member.name!r}")
    # tarfile.data_filter landed in 3.12; fall back to the looser filter on 3.11
    # so the CLI works across the full supported Python range.
    extract_kwargs: dict = {}
    if hasattr(tarfile, "data_filter"):
        extract_kwargs["filter"] = "data"
    tar.extractall(dest, **extract_kwargs)  # noqa: S202 — we validated members above


def _flatten_single_top_dir(staging: Path) -> Path:
    """If ``staging`` has exactly one subdir and no other entries, return it.

    Tarballs produced via ``tar czf ... -C /tmp gliner_onnx/`` contain a
    single top-level directory; we want the caller to extract to the
    target path directly rather than nest ``gliner_onnx/gliner_onnx/``.
    Returns ``staging`` unchanged if the layout is flat.
    """
    entries = list(staging.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return staging


# ── Core orchestration ──────────────────────────────────────────────────────


def download_model(
    *,
    to: Path,
    url: str,
    checksum_url: str | None = None,
    force: bool = False,
    quiet: bool = False,
    access_token: str | None = None,
) -> Path:
    """Download and extract a GLiNER ONNX tarball into ``to``.

    Args:
        to: Destination directory. Parent directories are created if
            missing. If ``to`` already exists and contains a
            :data:`_MARKER_FILE`, the download is skipped unless
            ``force`` is True.
        url: Tarball URL. Must resolve to a ``.tar.gz`` archive.
        checksum_url: SHA-256 checksum URL. If omitted, defaults to
            ``url + ".sha256"``.
        force: Re-download even if ``to`` already exists.
        quiet: Suppress progress logging on stdout.
        access_token: Optional GCP access token for Artifact Registry
            downloads. When set, attached as ``Authorization: Bearer``
            on both the tarball and checksum fetches. Not needed for
            public URLs.

    Returns:
        The ``to`` path on success.

    Raises:
        DownloadError: On network failure, HTTP error, checksum
            mismatch, unsafe tar entries, or any other recoverable
            failure. The target directory is left untouched on failure
            (existing contents are preserved).
    """
    to = Path(to).expanduser()

    if to.exists() and not force:
        marker = to / _MARKER_FILE
        if marker.exists():
            if not quiet:
                logger.info("model already present at %s (use --force to re-download)", to)
            return to

    if checksum_url is None:
        checksum_url = _default_checksum_url(url)

    to.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="data_classifier_dl_") as tmpdir:
        tmp_path = Path(tmpdir)
        tarball_path = tmp_path / "model.tar.gz"

        if not quiet:
            logger.info("downloading %s", url)
        _http_get(url, dest=tarball_path, quiet=quiet, access_token=access_token)

        if not quiet:
            logger.info("fetching checksum %s", checksum_url)
        checksum_body = _http_get_text(checksum_url, access_token=access_token)
        expected_sha = _parse_checksum_body(checksum_body)

        actual_sha = _sha256_file(tarball_path)
        if actual_sha != expected_sha:
            raise DownloadError(
                f"SHA-256 mismatch: expected {expected_sha}, got {actual_sha} — "
                f"refusing to extract (target directory left untouched)"
            )

        if not quiet:
            logger.info("checksum ok (%s)", actual_sha)

        staging = tmp_path / "extract"
        staging.mkdir()
        if not quiet:
            logger.info("extracting tarball to staging area")
        try:
            with tarfile.open(tarball_path, "r:gz") as tar:
                _safe_extract(tar, staging)
        except tarfile.TarError as exc:
            raise DownloadError(f"failed to extract tarball: {exc}") from exc

        payload = _flatten_single_top_dir(staging)

        # Only after successful download + checksum + extract do we touch
        # the real destination directory — this preserves the "mismatch
        # does not touch the target" acceptance criterion.
        if to.exists():
            shutil.rmtree(to)
        to.mkdir(parents=True, exist_ok=True)
        for entry in payload.iterdir():
            target = to / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target)
            else:
                shutil.copy2(entry, target)

        if not quiet:
            logger.info("installed model to %s", to)

    return to


# ── CLI ─────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-classifier-download-models",
        description=(
            "Download a pre-exported GLiNER ONNX model tarball from our "
            "Artifact Registry Generic repo and unpack it into the "
            "auto-discovery cache. Used by BQ's Dockerfile at build time."
        ),
    )
    parser.add_argument(
        "--to",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"destination directory (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--version",
        default=None,
        help=f"GLiNER model version to fetch (default: {DEFAULT_MODEL_VERSION})",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="override the full download URL (useful for internal mirrors or testing)",
    )
    parser.add_argument(
        "--checksum-url",
        default=None,
        help="override the SHA-256 checksum URL (default: derived from --url)",
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help=(
            "explicit GCP access token for Artifact Registry downloads. "
            "If omitted, the CLI tries GCP_ACCESS_TOKEN env var, then the "
            "metadata service (on GCP compute), then `gcloud auth "
            "print-access-token` (if gcloud is on PATH)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download even if the target path already exists",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress output on stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns an exit code (0 on success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    log_level = logging.WARNING if args.quiet else logging.INFO
    # Attach a minimal handler only if the root logger has none — avoids
    # duplicating messages if the caller already configured logging.
    if not logging.getLogger().handlers:
        logging.basicConfig(level=log_level, format="%(message)s", stream=sys.stdout)
    else:
        logging.getLogger().setLevel(log_level)

    version = args.version or _default_version()

    if args.url:
        url = args.url
    else:
        if not version:
            sys.stderr.write("error: could not resolve GLiNER model version; pass --version explicitly\n")
            return 2
        url = _build_default_url(version)

    # Auth token is only needed for Artifact Registry URLs, not for
    # arbitrary mirrors. We still try to obtain one when the default URL
    # is in use; when --url is a public mirror, the token is harmless
    # (the server ignores the Authorization header).
    access_token = _get_access_token(explicit=args.access_token)

    try:
        download_model(
            to=args.to,
            url=url,
            checksum_url=args.checksum_url,
            force=args.force,
            quiet=args.quiet,
            access_token=access_token,
        )
    except DownloadError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("error: interrupted\n")
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
