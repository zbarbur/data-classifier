"""Unit tests for :mod:`data_classifier.download_models`.

These tests spin up a real HTTP server on ``127.0.0.1`` via
:mod:`http.server` so the stdlib ``urllib`` code path is exercised
end-to-end, including checksum verification and tarball extraction.
No real network traffic is issued.
"""

from __future__ import annotations

import hashlib
import io
import socket
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import data_classifier.download_models as dm

# ── Mock server fixture ─────────────────────────────────────────────────────


class _RouteHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves a routes dict: path → (status, content-type, body).

    ``body`` may be ``bytes`` (served as-is), a ``str`` (encoded UTF-8), or
    the sentinel ``"RESET"`` which triggers an abrupt connection close to
    simulate a network reset.
    """

    routes: dict[str, tuple[int, str, bytes | str]] = {}

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        entry = self.routes.get(self.path)
        if entry is None:
            self.send_error(404, "not found")
            return
        status, content_type, body = entry
        if body == "RESET":
            # Simulate a connection reset mid-handshake.
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        if isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Silence the default stderr chatter during tests.
        return


@pytest.fixture()
def mock_server():
    """Yield ``(base_url, set_routes)`` for a fresh HTTP server per test."""
    handler_cls = type(
        "_BoundRouteHandler",
        (_RouteHandler,),
        {"routes": {}},
    )
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def set_routes(routes: dict[str, tuple[int, str, bytes | str]]) -> None:
        handler_cls.routes = routes

    try:
        yield base_url, set_routes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# ── Helpers to build a test tarball ─────────────────────────────────────────


def _build_tarball(members: dict[str, bytes], *, top_dir: str | None = "gliner_onnx") -> bytes:
    """Build a gzip tarball in-memory.

    If ``top_dir`` is set, every member is nested under ``top_dir/``
    (mirroring the ``tar czf ... -C /tmp gliner_onnx/`` layout used by
    the publish pipeline). If ``top_dir`` is None, members are written
    at the archive root.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            full_name = f"{top_dir}/{name}" if top_dir else name
            info = tarfile.TarInfo(name=full_name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_model_members() -> dict[str, bytes]:
    """Return the minimum file set that looks like a real GLiNER ONNX export."""
    return {
        "gliner_config.json": b'{"model": "gliner_multi_pii-v1"}',
        "model.onnx": b"\x00fake-onnx-bytes\x00",
        "tokenizer.json": b'{"vocab": {}}',
    }


# ── Tests ───────────────────────────────────────────────────────────────────


class TestCLIHelp:
    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            dm.main(["--help"])
        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        assert "--to" in captured.out
        assert "--version" in captured.out
        assert "--url" in captured.out
        assert "--force" in captured.out


class TestSuccessPath:
    def test_downloads_and_extracts_tarball(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        checksum_body = f"{_sha256_hex(tarball)}  gliner_onnx-test.tar.gz\n"
        set_routes(
            {
                "/model.tar.gz": (200, "application/gzip", tarball),
                "/model.tar.gz.sha256": (200, "text/plain", checksum_body),
            }
        )

        target = tmp_path / "gliner_onnx"
        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/model.tar.gz",
                "--quiet",
            ]
        )

        assert exit_code == 0
        assert (target / "gliner_config.json").exists()
        assert (target / "model.onnx").read_bytes() == b"\x00fake-onnx-bytes\x00"
        assert (target / "tokenizer.json").exists()

    def test_custom_checksum_url_is_honored(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        set_routes(
            {
                "/m.tar.gz": (200, "application/gzip", tarball),
                "/checksums/m.sha256": (200, "text/plain", _sha256_hex(tarball)),
            }
        )

        target = tmp_path / "gliner_onnx"
        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/m.tar.gz",
                "--checksum-url",
                f"{base_url}/checksums/m.sha256",
                "--quiet",
            ]
        )
        assert exit_code == 0
        assert (target / "gliner_config.json").exists()

    def test_creates_missing_parent_dirs(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        set_routes(
            {
                "/model.tar.gz": (200, "application/gzip", tarball),
                "/model.tar.gz.sha256": (200, "text/plain", _sha256_hex(tarball)),
            }
        )

        # Deep nested path that does NOT yet exist — the CLI must mkdir -p it.
        target = tmp_path / "nested" / "a" / "b" / "c" / "gliner_onnx"
        assert not target.parent.exists()

        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/model.tar.gz",
                "--quiet",
            ]
        )
        assert exit_code == 0
        assert (target / "gliner_config.json").exists()

    def test_handles_flat_tarball_without_top_dir(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
    ) -> None:
        """A tarball without a nested top dir should still extract correctly."""
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members(), top_dir=None)
        set_routes(
            {
                "/flat.tar.gz": (200, "application/gzip", tarball),
                "/flat.tar.gz.sha256": (200, "text/plain", _sha256_hex(tarball)),
            }
        )

        target = tmp_path / "gliner_onnx"
        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/flat.tar.gz",
                "--quiet",
            ]
        )
        assert exit_code == 0
        assert (target / "gliner_config.json").exists()


class TestIdempotencyAndForce:
    def test_existing_target_is_skipped_without_force(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        set_routes(
            {
                "/m.tar.gz": (200, "application/gzip", tarball),
                "/m.tar.gz.sha256": (200, "text/plain", _sha256_hex(tarball)),
            }
        )

        target = tmp_path / "gliner_onnx"
        target.mkdir()
        marker = target / "gliner_config.json"
        marker.write_text('{"pre-existing": true}')

        exit_code = dm.main(["--to", str(target), "--url", f"{base_url}/m.tar.gz", "--quiet"])
        assert exit_code == 0
        # Existing content preserved — no re-download happened.
        assert '{"pre-existing": true}' in marker.read_text()

    def test_force_overwrites_existing_target(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        set_routes(
            {
                "/m.tar.gz": (200, "application/gzip", tarball),
                "/m.tar.gz.sha256": (200, "text/plain", _sha256_hex(tarball)),
            }
        )

        target = tmp_path / "gliner_onnx"
        target.mkdir()
        (target / "gliner_config.json").write_text('{"stale": true}')
        (target / "stale_leftover.bin").write_bytes(b"junk")

        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/m.tar.gz",
                "--force",
                "--quiet",
            ]
        )
        assert exit_code == 0
        # The freshly extracted config.json replaced the stale one.
        assert '"gliner_multi_pii-v1"' in (target / "gliner_config.json").read_text()
        # The stale leftover file was removed (directory was cleaned).
        assert not (target / "stale_leftover.bin").exists()


class TestFailureModes:
    def test_sha_mismatch_aborts_without_touching_target(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        wrong_sha = "0" * 64  # 64-char hex but not the real digest
        set_routes(
            {
                "/m.tar.gz": (200, "application/gzip", tarball),
                "/m.tar.gz.sha256": (200, "text/plain", wrong_sha),
            }
        )

        target = tmp_path / "gliner_onnx"
        target.mkdir()
        sentinel = target / "gliner_config.json"
        sentinel.write_text('{"original": true}')

        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/m.tar.gz",
                "--force",  # even with --force, mismatch must not touch target
                "--quiet",
            ]
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "SHA-256 mismatch" in captured.err
        # Target directory contents preserved intact.
        assert sentinel.read_text() == '{"original": true}'
        assert not (target / "model.onnx").exists()

    def test_http_404_exits_nonzero_with_clean_error(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base_url, _ = mock_server
        target = tmp_path / "gliner_onnx"
        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/does-not-exist.tar.gz",
                "--quiet",
            ]
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.err.startswith("error: ")
        assert "Traceback" not in captured.err
        assert "HTTP 404" in captured.err

    def test_network_failure_exits_nonzero_with_clean_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Use a port that nothing is listening on.
        # Ports in the 1-1023 range typically fail fast with connection refused.
        target = tmp_path / "gliner_onnx"
        # Pick a random free ephemeral port and close the socket so it's reliably empty.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _, dead_port = sock.getsockname()
        sock.close()

        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"http://127.0.0.1:{dead_port}/model.tar.gz",
                "--quiet",
            ]
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.err.startswith("error: ")
        assert "Traceback" not in captured.err

    def test_empty_checksum_file_is_rejected(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        set_routes(
            {
                "/m.tar.gz": (200, "application/gzip", tarball),
                "/m.tar.gz.sha256": (200, "text/plain", "   \n"),
            }
        )

        target = tmp_path / "gliner_onnx"
        exit_code = dm.main(["--to", str(target), "--url", f"{base_url}/m.tar.gz", "--quiet"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "checksum" in captured.err.lower()

    def test_malformed_checksum_is_rejected(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base_url, set_routes = mock_server
        tarball = _build_tarball(_valid_model_members())
        set_routes(
            {
                "/m.tar.gz": (200, "application/gzip", tarball),
                "/m.tar.gz.sha256": (200, "text/plain", "not-a-valid-hex-digest"),
            }
        )

        target = tmp_path / "gliner_onnx"
        exit_code = dm.main(["--to", str(target), "--url", f"{base_url}/m.tar.gz", "--quiet"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "valid SHA-256 digest" in captured.err


class TestUnsafeTarball:
    def test_path_traversal_entry_aborts(
        self,
        mock_server: tuple[str, object],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base_url, set_routes = mock_server
        # Build a tarball with a ../ escape attempt.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="../evil.txt")
            payload = b"pwned"
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        tarball = buf.getvalue()
        set_routes(
            {
                "/evil.tar.gz": (200, "application/gzip", tarball),
                "/evil.tar.gz.sha256": (200, "text/plain", _sha256_hex(tarball)),
            }
        )

        target = tmp_path / "gliner_onnx"
        exit_code = dm.main(
            [
                "--to",
                str(target),
                "--url",
                f"{base_url}/evil.tar.gz",
                "--quiet",
            ]
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "unsafe path" in captured.err.lower()
        # The attacker's escape file must not exist anywhere nearby.
        assert not (tmp_path / "evil.txt").exists()


class TestVersionDiscovery:
    def test_default_version_returns_pinned_model_version(self) -> None:
        # _default_version returns the pinned GLiNER model version —
        # deliberately decoupled from the data_classifier package version
        # because the model is a separate artifact with its own lifecycle.
        assert dm._default_version() == dm.DEFAULT_MODEL_VERSION

    def test_default_model_version_constant_has_sensible_format(self) -> None:
        # Belt-and-suspenders: the pinned version should look like a
        # filename-safe identifier (letters, digits, dashes, underscores).
        version = dm.DEFAULT_MODEL_VERSION
        assert isinstance(version, str)
        assert version != ""
        assert all(c.isalnum() or c in "-_." for c in version), f"unsafe chars in {version!r}"

    def test_installed_package_version_uses_importlib_metadata(self) -> None:
        # Separate helper for callers that want the package version
        # (e.g. for logging or reporting). NOT used for URL construction.
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _pkg_version

        try:
            expected = _pkg_version("data_classifier")
        except PackageNotFoundError:
            expected = "unknown"
        assert dm._installed_package_version() == expected

    def test_missing_version_without_url_returns_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Simulate the edge case where the caller passes --version "" —
        # the CLI should emit a clean error, not a traceback.
        monkeypatch.setattr(dm, "_default_version", lambda: "")
        exit_code = dm.main(["--to", str(tmp_path / "gliner_onnx"), "--quiet"])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "could not resolve GLiNER model version" in captured.err


class TestUrlBuilding:
    def test_default_url_template_substitutes_version(self) -> None:
        url = dm._build_default_url("test-model-v1")
        # Our AR Generic REST URL embeds the version twice: once in the
        # package path and once in the filename.
        assert url.count("test-model-v1") == 2
        assert url.endswith(".tar.gz:download?alt=media")

    def test_default_checksum_url_for_plain_http(self) -> None:
        # Plain mirror URLs (e.g. --url overrides) get a simple ".sha256"
        # appended to the end.
        assert dm._default_checksum_url("https://example/x.tar.gz") == "https://example/x.tar.gz.sha256"

    def test_default_checksum_url_for_ar_generic_rest(self) -> None:
        # The AR Generic REST download endpoint has a ":download?alt=media"
        # suffix that must come AFTER the ".sha256" — so the checksum URL
        # is built by inserting ".sha256" before the suffix, not at the
        # very end of the URL.
        tarball = (
            "https://artifactregistry.googleapis.com/v1/projects/X/locations/Y/repositories/Z"
            "/files/pkg:ver:name.tar.gz:download?alt=media"
        )
        expected = (
            "https://artifactregistry.googleapis.com/v1/projects/X/locations/Y/repositories/Z"
            "/files/pkg:ver:name.tar.gz.sha256:download?alt=media"
        )
        assert dm._default_checksum_url(tarball) == expected


class TestAccessTokenDiscovery:
    """Pin the GCP access token lookup strategy for AR downloads."""

    def test_explicit_token_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GCP_ACCESS_TOKEN", "from-env")
        assert dm._get_access_token(explicit="from-cli") == "from-cli"

    def test_env_token_when_no_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GCP_ACCESS_TOKEN", "from-env")
        assert dm._get_access_token() == "from-env"

    def test_returns_none_when_nothing_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear env, force metadata service to fail, force gcloud absent.
        monkeypatch.delenv("GCP_ACCESS_TOKEN", raising=False)

        import urllib.error

        def fake_urlopen(*args: object, **kwargs: object) -> object:
            raise urllib.error.URLError("no metadata server")

        monkeypatch.setattr(dm.urllib.request, "urlopen", fake_urlopen)

        import shutil as _sh

        monkeypatch.setattr(_sh, "which", lambda _: None)
        assert dm._get_access_token() is None


class TestLeanRuntime:
    """Sanity checks that the module never imports heavy ML deps at top level.

    The production BQ container installs only ``[ml]`` extras (onnxruntime +
    gliner); importing ``data_classifier.download_models`` must not pull in
    ``torch``, ``transformers``, ``onnx``, or ``requests``.
    """

    FORBIDDEN = {"torch", "transformers", "onnx", "requests"}

    def test_module_does_not_import_heavy_deps(self) -> None:
        # Force a fresh import so we observe the real side effects.
        for mod_name in list(sys.modules):
            if mod_name == "data_classifier.download_models":
                del sys.modules[mod_name]
        # Snapshot sys.modules before.
        before = set(sys.modules)
        import data_classifier.download_models  # noqa: F401

        newly_imported = set(sys.modules) - before
        leaked = self.FORBIDDEN & newly_imported
        assert not leaked, f"download_models leaked heavy deps: {leaked}"

    def test_module_sources_only_stdlib_at_top_level(self) -> None:
        """Belt-and-suspenders: grep the source for forbidden top-level imports."""
        source = Path(dm.__file__).read_text()
        # We only care about TOP-LEVEL imports. The simplest approximation:
        # any line starting with "import X" or "from X" at column 0 where
        # X is in FORBIDDEN.
        offenders = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped != line:
                continue  # indented — inside a function, allowed
            for mod in self.FORBIDDEN:
                if stripped.startswith(f"import {mod}") or stripped.startswith(f"from {mod}"):
                    offenders.append((lineno, line))
        assert not offenders, f"forbidden top-level imports: {offenders}"
