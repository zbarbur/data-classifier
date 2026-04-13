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

#: Default Google Artifact Registry Generic repo hosting the ONNX tarballs.
#: The version placeholder ``{version}`` is substituted at call time.
DEFAULT_URL_TEMPLATE = (
    "https://us-central1-docker.pkg.dev/data-classifier-prod/data-classifier-models/gliner_onnx-{version}.tar.gz"
)

#: Default cache root — matches ``gliner_engine._find_bundled_onnx_model``
#: search path 2 of 3, so the engine auto-discovers the unpacked model.
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "data_classifier" / "models" / "gliner_onnx"

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
    """Return the installed ``data_classifier`` package version.

    Uses :mod:`importlib.metadata` so the lookup works against both
    editable and wheel installs. Falls back to the literal string
    ``"unknown"`` if the distribution metadata is missing — callers
    should then supply ``--version`` explicitly.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover — stdlib on 3.8+
        return "unknown"

    try:
        return version("data_classifier")
    except PackageNotFoundError:
        return "unknown"


# ── URL helpers ─────────────────────────────────────────────────────────────


def _build_default_url(version: str) -> str:
    return DEFAULT_URL_TEMPLATE.format(version=version)


def _default_checksum_url(tarball_url: str) -> str:
    return tarball_url + ".sha256"


# ── HTTP ─────────────────────────────────────────────────────────────────────


def _http_get(url: str, *, dest: Path, quiet: bool) -> None:
    """Download ``url`` to ``dest``, streaming in ``_CHUNK_BYTES`` blocks.

    Wraps low-level ``urllib`` exceptions in :class:`DownloadError` so
    ``main()`` can emit a clean one-line message.
    """
    try:
        with urllib.request.urlopen(url) as response:  # noqa: S310 — URL is user-supplied CLI input
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


def _http_get_text(url: str) -> str:
    """Fetch ``url`` and return its body as a UTF-8 string."""
    try:
        with urllib.request.urlopen(url) as response:  # noqa: S310 — URL is user-supplied CLI input
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
    """Extract ``tar`` into ``dest`` with path-traversal protection."""
    for member in tar.getmembers():
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
        _http_get(url, dest=tarball_path, quiet=quiet)

        if not quiet:
            logger.info("fetching checksum %s", checksum_url)
        checksum_body = _http_get_text(checksum_url)
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
        help="model version to fetch (default: installed data_classifier version)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="override the full download URL (useful for internal mirrors or testing)",
    )
    parser.add_argument(
        "--checksum-url",
        default=None,
        help="override the SHA-256 checksum URL (default: <url>.sha256)",
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
        if version == "unknown":
            sys.stderr.write("error: could not discover data_classifier version; pass --version explicitly\n")
            return 2
        url = _build_default_url(version)

    try:
        download_model(
            to=args.to,
            url=url,
            checksum_url=args.checksum_url,
            force=args.force,
            quiet=args.quiet,
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
