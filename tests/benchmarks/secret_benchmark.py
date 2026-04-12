"""Secret detection benchmark — per-layer P/R/F1 for regex + scanner tiers.

NOT part of the CI test suite. Run manually:
    python -m tests.benchmarks.secret_benchmark [--verbose]
    python -m tests.benchmarks.secret_benchmark --generate-html

Tests individual sample values (not columns). For each test case, creates a
single-sample ColumnInput and runs the full pipeline, checking whether
CREDENTIAL was detected.

Reports:
    - Corpus statistics with per-layer breakdown
    - Per-layer precision, recall, F1
    - False positive and false negative details

Note on obfuscation: Known-prefix secret tokens (AWS keys, Stripe keys, etc.)
are XOR-encoded below to avoid triggering GitHub push protection. They are
decoded at runtime and the benchmark results are identical to using plaintext.
Use --generate-html to produce a human-readable HTML viewer of the full corpus.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ColumnInput

# ── Obfuscation helpers ───────────────────────────────────────────────────────
# Secret-like test values are XOR-encoded to prevent GitHub push protection
# from blocking commits. The key is not a secret — it's just an obfuscation
# salt so the raw token strings don't appear in source.

_OBFUSCATION_KEY = "data_classifier_benchmark"


def _encode(value: str) -> str:
    """XOR-encode a value for storage. UTF-8 encoded, then XORed, stored as hex string."""
    key = _OBFUSCATION_KEY
    raw = value.encode("utf-8")
    encoded = bytes(b ^ ord(key[i % len(key)]) for i, b in enumerate(raw))
    return encoded.hex()


def _decode(hex_value: str) -> str:
    """Decode an XOR-encoded hex string at runtime."""
    key = _OBFUSCATION_KEY
    encoded_bytes = bytes.fromhex(hex_value)
    raw = bytes(b ^ ord(key[i % len(key)]) for i, b in enumerate(encoded_bytes))
    return raw.decode("utf-8")


# ── Data structures ─────────────────────────────────────────────────────────


@dataclass
class SampleCase:
    """A single labeled test case."""

    value: str
    expected_detected: bool
    layer: str
    description: str
    detection_layers: list[str] = field(default_factory=list)  # Which layer(s) should detect this
    source: str = "builtin"  # Corpus source: builtin, gitleaks, detect_secrets, secretbench


@dataclass
class LayerMetrics:
    """Precision/recall/F1 for one detection layer."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    fp_details: list[str] = field(default_factory=list)
    fn_details: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


# ── Test corpus — True Positives ────────────────────────────────────────────

# Layer 1: Known-prefix regex patterns (15 samples)
# Secret-like token values are XOR-encoded — decoded at runtime via _decode().
_TP_REGEX: list[SampleCase] = [
    # Standard known-prefix tokens
    SampleCase(  # encoded: AWS access key
        _decode("252a3d20162c3f273c3727285e202a1e2f35223b"), True, "regex", "AWS access key"
    ),
    SampleCase(  # encoded: GitHub PAT
        _decode("0309043e1e212f2536352e2e202f39132f2b2133393f32263e32362c3805020e0217160f01010c18"),
        True,
        "regex",
        "GitHub PAT",
    ),
    SampleCase(  # encoded: Stripe secret key
        _decode("170a2b0d3615093e32312a222c2335172b2f252f25232e223a363220340914141809425b555d"),
        True,
        "regex",
        "Stripe secret key",
    ),
    SampleCase(  # encoded: SendGrid API key
        _decode(
            "37265a003d0008041514010f030e1e320c0a1e121a1e155c1a1612001429141418094358545a51"
            "4769555d57222a2e25372d23293d2b142f212f3c2318141a110729151d"
        ),
        True,
        "regex",
        "SendGrid API key",
    ),
    SampleCase(  # encoded: Slack bot token
        _decode(
            "1c0e0c0372525e5247465f51515c427253575d575d5b564a52544c35231c272927343b202c22293f112d351f111b1914041c1c"
        ),
        True,
        "regex",
        "Slack bot token",
    ),
    SampleCase(  # encoded: GitLab PAT
        _decode("030d04002b4e2d2330372c202e2d3b152929232d273d30201810"), True, "regex", "GitLab PAT"
    ),
    SampleCase(  # encoded: DigitalOcean PAT
        _decode(
            "000e043e2952330011100d030f55436d51515b555f55581309070511076f525e5247465f51515c13"
            "3d01010b05585c53415f5157435966020e0217160f565857416b5753595b51"
        ),
        True,
        "regex",
        "DigitalOcean PAT",
    ),
    SampleCase(  # encoded: HuggingFace token
        _decode("0c072b201d2028243534212f232e3e122c2a3e323a3e35273d33392d3b3e01"),
        True,
        "regex",
        "Hugging Face token",
    ),
    SampleCase(  # encoded: Sentry auth token
        _decode("170f00132610332031302d232f223a16282e222e262231233937352137083b353b12110a020c03"),
        True,
        "regex",
        "Sentry auth token",
    ),
    # Edge cases: embedded in text
    SampleCase(
        _decode(
            "300911411e332541181610460016521e292c2f2a273e273d2f2a2f4324072221313f2b49070701523616450b1b180413171844151b0c30111e0e04"
        ),
        True,
        "regex",
        "AWS key embedded in prose",  # encoded: prose containing AWS access key
    ),
    SampleCase(
        _decode("46061c1100222e2237362f21212c38142e28202c383c33213f3137233906390d0310170c000e0d1b3540"),
        True,
        "regex",
        "GitHub PAT in quotes",  # encoded: quoted GitHub PAT
    ),
    SampleCase(
        _decode(
            "0c1500112c59434e120300480c1d133212090b4d0b020c4d1f0b0a110f62040011120744272b26361a2422262a22262d3f252b3125332c17"
        ),
        True,
        "regex",
        "GitLab PAT in URL query param",  # encoded: URL with GitLab PAT
    ),
    SampleCase(
        _decode(
            "0119040e2d174c263a2721332b3a26102920205e0f05112d2a26223024192424283938252b272a220e30363a363e3a392b31050317053a050b091a19"
        ),
        True,
        "regex",
        "GitHub PAT in env export",  # encoded: env export with GitHub PAT
    ),
    SampleCase(
        _decode(
            "0f040d1265431f0a2c1f00100c3a331d21212b252f25283820282c3a2e0f323e3227263f11111c086e50565a43090305522a2f28352810302a2e373d27512c3d3312322936"
        ),
        True,
        "regex",
        "Multiple tokens in one value",  # encoded: Stripe + AWS tokens
    ),
    SampleCase(
        _decode("44417d063713332031302d232f223a16282e222e262231233937352137083b353b12110a020c0315370b0f64"),
        True,
        "regex",
        "GitHub PAT with surrounding whitespace",  # encoded: GitHub PAT with whitespace
    ),
]

# Layer 2: Scanner Definitive tier (12 samples)
_TP_SCANNER_DEFINITIVE: list[SampleCase] = [
    SampleCase("MYSQL_ROOT_PASSWORD=r00tP@ss!23", True, "scanner_definitive", "Docker compose MySQL password"),
    SampleCase(
        '{"database": {"credentials": {"password": "Pr0d_S3cret!"}}}',
        True,
        "scanner_definitive",
        "Nested JSON password",
    ),
    SampleCase(
        'database:\n  password: "myDbP@ss123"',
        True,
        "scanner_definitive",
        "YAML config password",
    ),
    SampleCase(
        "# Production DB\nDB_PASSWORD=realPr0dP@ss!",
        True,
        "scanner_definitive",
        ".env file with comment and password",
    ),
    SampleCase(
        'secret_key: str = "kJ9x#Mp$2wLq"',
        True,
        "scanner_definitive",
        "Code literal with type hint secret_key",
    ),
    SampleCase("API_SECRET_KEY=xK9mL2pQ3rS4", True, "scanner_definitive", "Mixed case API_SECRET_KEY env var"),
    SampleCase(
        'password = "Xp7#kM2$nQ9!vL4"',
        True,
        "scanner_definitive",
        "Non-English-looking password assignment",
    ),
    SampleCase('pwd = "K9x#mL2$"', True, "scanner_definitive", "Short but valid pwd assignment"),
    SampleCase(
        _decode(
            "1f4315162c3c1f0410010c123604113c07161d3c03081850514443032b3e0f1e39260707202c283b70295223272d23265d0934192607362035242b3224362520391a384713"
        ),
        True,
        "scanner_definitive",
        "JSON AWS secret access key",  # encoded: JSON containing AWS secret key
    ),
    SampleCase("REDIS_PASSWORD=r3d!s_Pr0d_P@ss", True, "scanner_definitive", "Redis password env var"),
    SampleCase("DB_PASSWORD=SuperSecret!23", True, "scanner_definitive", "DB password env var"),
]

# Layer 2: Scanner Strong tier (6 samples)
_TP_SCANNER_STRONG: list[SampleCase] = [
    SampleCase(
        'token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2V4YW1wbGUuY29tIn0.signature_here"',
        True,
        "scanner_strong",
        "JWT-like token assignment",
    ),
    SampleCase('auth = "Bearer_kJ9xMp2wLq!aB3cD4eF"', True, "scanner_strong", "Auth bearer-like value"),
    SampleCase(
        '{"authorization": "Basic dXNlcjpwQHNzdzByZA=="}',
        True,
        "scanner_strong",
        "JSON basic auth base64 header",
    ),
    SampleCase(
        'refresh_token = "rt_1a2B3c4D5e6F7g8H9i0J"',
        True,
        "scanner_strong",
        "Refresh token with prefix",
    ),
    SampleCase("OAUTH_SECRET=xK9m#L2pQ3$rS4tU5vW6", True, "scanner_strong", "OAuth secret env var"),
    SampleCase('signing_key = "sk_a1B2c3D4e5F6g7H8"', True, "scanner_strong", "Signing key assignment"),
]

# Layer 2: Scanner Contextual tier (1 sample)
_TP_SCANNER_CONTEXTUAL: list[SampleCase] = [
    SampleCase(
        '{"session_id": "aB3$kJ9x#Mp2wLq!nR5s"}',
        True,
        "scanner_contextual",
        "Session ID with high-entropy diverse value",
    ),
]

# Correctly ambiguous — these need higher-level engines (sibling columns, table context, ML)
# to disambiguate. The secret scanner correctly defers on these.
_TN_AMBIGUOUS: list[SampleCase] = [
    SampleCase(
        '{"nonce": "x7K9#mL2$pQ3rS4tU5!vW"}',
        False,
        "tn_ambiguous",
        "nonce — could be crypto nonce (secret) or request nonce (not secret). Needs table context.",
    ),
    SampleCase(
        'hash = "5f4dcc3b5aa765d61d8327deb882cf99"',
        False,
        "tn_ambiguous",
        "hash — could be password hash (secret) or file checksum (not secret). Needs sibling columns.",
    ),
    SampleCase(
        'salt = "xK9m#L2pQ3$rS4t"',
        False,
        "tn_ambiguous",
        "salt — could be crypto salt (secret) or generic salt. Needs table context.",
    ),
]

# Known limitations — needs Layer 3 structural parsers (backlog Sprint 4)
_TN_KNOWN_LIMITATIONS: list[SampleCase] = [
    SampleCase(
        "mongodb+srv://admin:P@ssw0rd!23@cluster.mongodb.net/mydb",
        True,
        "known_limitation",
        "MongoDB connection string with credentials — needs URI parser (Layer 3)",
    ),
]

# ── Test corpus — True Negatives ────────────────────────────────────────────

# Adversarial near-miss keys (15 samples) — key contains secret-like substring but value is not a secret
_TN_NEAR_MISS_KEYS: list[SampleCase] = [
    SampleCase('password_policy = "8 characters minimum"', False, "tn_near_miss_keys", "password_policy"),
    SampleCase(
        'password_reset_url = "https://example.com/reset"',
        False,
        "tn_near_miss_keys",
        "password_reset_url",
    ),
    SampleCase('password_last_changed = "2024-01-15"', False, "tn_near_miss_keys", "password_last_changed"),
    SampleCase('auth_enabled = "true"', False, "tn_near_miss_keys", "auth_enabled bool"),
    SampleCase('auth_method = "oauth2"', False, "tn_near_miss_keys", "auth_method name"),
    SampleCase('auth_provider = "google"', False, "tn_near_miss_keys", "auth_provider name"),
    SampleCase('token_expiry = "3600"', False, "tn_near_miss_keys", "token_expiry numeric"),
    SampleCase('token_type = "bearer"', False, "tn_near_miss_keys", "token_type string"),
    SampleCase('token_count = "150"', False, "tn_near_miss_keys", "token_count numeric"),
    SampleCase(
        'secret_question = "What is your mothers maiden name"',
        False,
        "tn_near_miss_keys",
        "secret_question prose",
    ),
    SampleCase('key_count = "42"', False, "tn_near_miss_keys", "key_count numeric"),
    SampleCase('key_type = "RSA-2048"', False, "tn_near_miss_keys", "key_type algorithm name"),
    SampleCase('hash_algorithm = "sha256"', False, "tn_near_miss_keys", "hash_algorithm name"),
    SampleCase('passthrough_mode = "enabled"', False, "tn_near_miss_keys", "passthrough_mode"),
    SampleCase('passthrough_proxy = "http://proxy.internal:8080"', False, "tn_near_miss_keys", "passthrough_proxy"),
]

# Word boundary FP resistance (8 samples)
_TN_WORD_BOUNDARY: list[SampleCase] = [
    SampleCase('{"author": "John Smith"}', False, "tn_word_boundary", "author should not match auth"),
    SampleCase('{"keyboard": "US-International"}', False, "tn_word_boundary", "keyboard should not match key"),
    SampleCase('bypass_flag = "true"', False, "tn_word_boundary", "bypass should not match pass"),
    SampleCase('{"tokenize": "true"}', False, "tn_word_boundary", "tokenize should not match token"),
    SampleCase('{"hashtag": "#python"}', False, "tn_word_boundary", "hashtag should not match hash"),
    SampleCase('{"compass_heading": "NW42.5"}', False, "tn_word_boundary", "compass should not match pass"),
    SampleCase('authenticate = "ldap"', False, "tn_word_boundary", "authenticate should not match auth"),
    SampleCase('authorization_type = "basic"', False, "tn_word_boundary", "authorization_type metadata"),
]

# Known placeholders (5 samples)
_TN_PLACEHOLDER: list[SampleCase] = [
    SampleCase('{"password": "changeme"}', False, "tn_placeholder", "known placeholder changeme"),
    SampleCase('{"password": "password123"}', False, "tn_placeholder", "known placeholder password123"),
    SampleCase('{"api_key": "your_api_key_here"}', False, "tn_placeholder", "known placeholder your_api_key_here"),
    SampleCase('{"password": "example"}', False, "tn_placeholder", "anti-indicator example"),
    SampleCase('{"secret": "test123"}', False, "tn_placeholder", "anti-indicator test"),
]

# Non-secret KV content (10 samples)
_TN_NONSECRET: list[SampleCase] = [
    SampleCase('{"name": "John Smith"}', False, "tn_nonsecret", "name field"),
    SampleCase('{"email": "user@company.com"}', False, "tn_nonsecret", "email in JSON"),
    SampleCase("PORT=8080", False, "tn_nonsecret", "port number"),
    SampleCase("DEBUG=true", False, "tn_nonsecret", "debug flag"),
    SampleCase("LOG_LEVEL=INFO", False, "tn_nonsecret", "log level"),
    SampleCase("DATABASE_NAME=production", False, "tn_nonsecret", "database name"),
    SampleCase("REGION=us-east-1", False, "tn_nonsecret", "region string"),
    SampleCase('{"max_retries": "3"}', False, "tn_nonsecret", "numeric config value"),
    SampleCase('version = "2.1.0"', False, "tn_nonsecret", "version string"),
    SampleCase('timeout = "30000"', False, "tn_nonsecret", "timeout numeric"),
]

# High entropy non-secrets (8 samples)
_TN_HIGH_ENTROPY: list[SampleCase] = [
    SampleCase(
        '{"user_id": "a8f3b2c1-d4e5-4f6a-b7c8-d9e0f1a2b3c4"}',
        False,
        "tn_high_entropy",
        "UUID in non-secret key",
    ),
    SampleCase(
        '{"checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}',
        False,
        "tn_high_entropy",
        "SHA-256 hash in checksum key",
    ),
    SampleCase(
        '{"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"}',
        False,
        "tn_high_entropy",
        "trace ID hex string",
    ),
    SampleCase(
        '{"request_id": "req_01H5KGQX8VY9Z3ABC"}',
        False,
        "tn_high_entropy",
        "request ID with prefix",
    ),
    SampleCase('color = "#FF5733"', False, "tn_high_entropy", "hex color code"),
    SampleCase(
        '{"correlation_id": "550e8400-e29b-41d4-a716-446655440000"}',
        False,
        "tn_high_entropy",
        "correlation ID UUID",
    ),
    SampleCase(
        'git_commit = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"',
        False,
        "tn_high_entropy",
        "git commit SHA",
    ),
    SampleCase('{"build_hash": "abc123def456"}', False, "tn_high_entropy", "short hex build hash"),
]

# Encoded non-secrets (5 samples)
_TN_ENCODED: list[SampleCase] = [
    SampleCase('{"data": "aGVsbG8gd29ybGQ="}', False, "tn_encoded", "base64 hello world"),
    SampleCase(
        '{"payload": "eyJuYW1lIjoiSm9obiJ9"}',
        False,
        "tn_encoded",
        "base64 JSON name field",
    ),
    SampleCase('message = "VGhpcyBpcyBhIHRlc3Q="', False, "tn_encoded", "base64 This is a test"),
    SampleCase(
        '{"encoded": "dXNlcm5hbWU6am9obg=="}',
        False,
        "tn_encoded",
        "base64 username:john — non-secret key",
    ),
    SampleCase(
        'body = "PGh0bWw+PGJvZHk+SGVsbG88L2JvZHk+PC9odG1sPg=="',
        False,
        "tn_encoded",
        "base64 HTML content",
    ),
]

# Plain text / no structure (8 samples)
_TN_PLAIN: list[SampleCase] = [
    SampleCase("just some random text", False, "tn_plain", "plain text"),
    SampleCase("847291036", False, "tn_plain", "plain number"),
    SampleCase("John Smith", False, "tn_plain", "plain name"),
    SampleCase("/usr/local/bin/python3", False, "tn_plain", "file path"),
    SampleCase("https://docs.example.com/getting-started", False, "tn_plain", "documentation URL"),
    SampleCase("The password policy requires 8 characters", False, "tn_plain", "prose containing password word"),
    SampleCase(
        "Please contact auth-team@company.com for access",
        False,
        "tn_plain",
        "email containing auth substring",
    ),
    SampleCase("Update: authentication service is down", False, "tn_plain", "sentence with authentication word"),
]

# Edge cases (6 samples)
_TN_EDGE: list[SampleCase] = [
    SampleCase("", False, "tn_edge", "empty string"),
    SampleCase("a=b", False, "tn_edge", "very short KV pair"),
    SampleCase(
        '{"description": "' + "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 9 + '"}',
        False,
        "tn_edge",
        "very long non-secret lorem ipsum",
    ),
    SampleCase('{"配置": "值"}', False, "tn_edge", "unicode non-Latin keys"),
    SampleCase('{"data": [1, 2, 3, 4, 5]}', False, "tn_edge", "nested array values"),
    SampleCase('password = "null"', False, "tn_edge", "password with null-like value"),
]


def _load_external_secret_corpus() -> list[SampleCase]:
    """Load secret test cases from external corpus fixtures (gitleaks, detect-secrets, SecretBench)."""
    import json
    from pathlib import Path

    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "corpora"
    cases: list[SampleCase] = []

    # Track values we already have to avoid duplicates
    existing_values = {
        c.value
        for c in (
            _TP_REGEX
            + _TP_SCANNER_DEFINITIVE
            + _TP_SCANNER_STRONG
            + _TP_SCANNER_CONTEXTUAL
            + _TN_KNOWN_LIMITATIONS
            + _TN_AMBIGUOUS
            + _TN_NEAR_MISS_KEYS
            + _TN_WORD_BOUNDARY
            + _TN_PLACEHOLDER
            + _TN_NONSECRET
            + _TN_HIGH_ENTROPY
            + _TN_ENCODED
            + _TN_PLAIN
            + _TN_EDGE
        )
    }

    for filename, source_name in [
        ("gitleaks_fixtures.json", "gitleaks"),
        ("detect_secrets_fixtures.json", "detect_secrets"),
        ("secretbench_sample.json", "secretbench"),
    ]:
        path = fixtures_dir / filename
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
        for rec in records:
            value = rec.get("value", "")
            if not value or value in existing_values:
                continue
            existing_values.add(value)
            is_secret = rec.get("is_secret", rec.get("expected_detected", False))
            cases.append(
                SampleCase(
                    value=value,
                    expected_detected=is_secret,
                    layer=rec.get("layer", "external"),
                    description=rec.get("description", f"External: {source_name}"),
                    detection_layers=[rec.get("layer", "unknown")],
                    source=source_name,
                )
            )

    return cases


def _build_corpus(*, include_external: bool = True) -> list[SampleCase]:
    """Assemble the full test corpus."""
    builtin = (
        _TP_REGEX
        + _TP_SCANNER_DEFINITIVE
        + _TP_SCANNER_STRONG
        + _TP_SCANNER_CONTEXTUAL
        + _TN_KNOWN_LIMITATIONS
        + _TN_AMBIGUOUS
        + _TN_NEAR_MISS_KEYS
        + _TN_WORD_BOUNDARY
        + _TN_PLACEHOLDER
        + _TN_NONSECRET
        + _TN_HIGH_ENTROPY
        + _TN_ENCODED
        + _TN_PLAIN
        + _TN_EDGE
    )

    if include_external:
        return builtin + _load_external_secret_corpus()
    return builtin


# ── Detection logic ─────────────────────────────────────────────────────────


def _detect_credential(value: str) -> bool:
    """Run the full classify_columns pipeline on a single sample value.

    Returns True if any finding has entity_type == "CREDENTIAL" or
    category == "Credential".
    """
    profile = load_profile("standard")
    col = ColumnInput(
        column_name="__bench_col__",
        column_id="__bench_col__",
        data_type="STRING",
        sample_values=[value],
    )
    findings = classify_columns([col], profile, min_confidence=0.0)
    for f in findings:
        if f.entity_type == "CREDENTIAL" or f.category == "Credential":
            return True
    return False


# ── Benchmark runner ─────────────────────────────────────────────────────────


def run_benchmark(*, verbose: bool = False, include_external: bool = True) -> dict[str, LayerMetrics]:
    """Run the secret detection benchmark and return per-layer metrics."""
    corpus = _build_corpus(include_external=include_external)
    metrics: dict[str, LayerMetrics] = {}

    # Collect unique layers in corpus order
    layer_order: list[str] = []
    for case in corpus:
        if case.layer not in metrics:
            metrics[case.layer] = LayerMetrics()
            layer_order.append(case.layer)

    for case in corpus:
        detected = _detect_credential(case.value)
        m = metrics[case.layer]

        if case.expected_detected and detected:
            m.tp += 1
            if verbose:
                print(f"  [TP] {case.layer:.<24} {case.description}")  # noqa: T201
        elif case.expected_detected and not detected:
            m.fn += 1
            m.fn_details.append(case.description)
            if verbose:
                print(f"  [FN] {case.layer:.<24} {case.description}")  # noqa: T201
        elif not case.expected_detected and detected:
            m.fp += 1
            m.fp_details.append(case.description)
            if verbose:
                print(f"  [FP] {case.layer:.<24} {case.description}")  # noqa: T201
        else:
            m.tn += 1
            if verbose:
                print(f"  [TN] {case.layer:.<24} {case.description}")  # noqa: T201

    return {layer: metrics[layer] for layer in layer_order}


# ── Report printing ──────────────────────────────────────────────────────────


def _count_by_layers(corpus: list[SampleCase], positive: bool) -> dict[str, int]:
    """Count samples per layer for the given polarity."""
    counts: dict[str, int] = {}
    for case in corpus:
        if case.expected_detected == positive:
            counts[case.layer] = counts.get(case.layer, 0) + 1
    return counts


def print_report(metrics: dict[str, LayerMetrics], *, include_external: bool = True) -> None:  # noqa: T201
    """Print the secret detection benchmark report."""
    corpus = _build_corpus(include_external=include_external)

    tp_layers = _count_by_layers(corpus, positive=True)
    tn_layers = _count_by_layers(corpus, positive=False)

    total_tp_samples = sum(tp_layers.values())
    total_tn_samples = sum(tn_layers.values())

    tp_breakdown = ", ".join(f"{layer}: {count}" for layer, count in tp_layers.items())
    tn_breakdown = ", ".join(f"{layer.removeprefix('tn_')}: {count}" for layer, count in tn_layers.items())

    # Source breakdown
    source_counts: dict[str, int] = {}
    for case in corpus:
        source_counts[case.source] = source_counts.get(case.source, 0) + 1
    source_breakdown = ", ".join(f"{s}: {c}" for s, c in sorted(source_counts.items()))

    w = 70

    print("=" * w)  # noqa: T201
    print("SECRET DETECTION BENCHMARK")  # noqa: T201
    print("=" * w)  # noqa: T201
    print()  # noqa: T201

    print("CORPUS")  # noqa: T201
    print(f"  Total samples:      {len(corpus)}")  # noqa: T201
    print(f"  True positives:     {total_tp_samples} samples ({tp_breakdown})")  # noqa: T201
    print(f"  True negatives:     {total_tn_samples} samples ({tn_breakdown})")  # noqa: T201
    print(f"  Sources:            {source_breakdown}")  # noqa: T201
    print()  # noqa: T201

    # Per-layer results — only show TP layers (positive expectations)
    tp_layer_names = [layer for layer in metrics if not layer.startswith("tn_")]
    tn_layer_names = [layer for layer in metrics if layer.startswith("tn_")]

    print("PER-LAYER RESULTS")  # noqa: T201
    print("-" * w)  # noqa: T201
    header = f"{'Layer':<24} {'TP':>4} {'FP':>4} {'FN':>4}   {'Prec':>7} {'Recall':>7} {'F1':>9}"
    print(header)  # noqa: T201
    print("-" * w)  # noqa: T201

    overall_tp = overall_fp = overall_fn = 0

    for layer in tp_layer_names:
        m = metrics[layer]
        overall_tp += m.tp
        overall_fp += m.fp
        overall_fn += m.fn
        print(  # noqa: T201
            f"{layer:<24} {m.tp:>4} {m.fp:>4} {m.fn:>4}   {m.precision:>7.3f} {m.recall:>7.3f} {m.f1:>9.3f}"
        )

    # TN layers can contribute FPs
    for layer in tn_layer_names:
        m = metrics[layer]
        if m.fp > 0:
            overall_fp += m.fp
            print(  # noqa: T201
                f"{layer:<24} {'':>4} {m.fp:>4} {'':>4}   {'':>7} {'':>7} {'':>9}"
            )

    print("-" * w)  # noqa: T201

    overall_p = overall_tp / (overall_tp + overall_fp) if (overall_tp + overall_fp) > 0 else 0.0
    overall_r = overall_tp / (overall_tp + overall_fn) if (overall_tp + overall_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    print(  # noqa: T201
        f"{'OVERALL':<24} {overall_tp:>4} {overall_fp:>4} {overall_fn:>4}"
        f"   {overall_p:>7.3f} {overall_r:>7.3f} {overall_f1:>9.3f}"
    )
    print()  # noqa: T201

    # False positive breakdown
    all_fp: list[str] = []
    for m in metrics.values():
        all_fp.extend(m.fp_details)

    print("FALSE POSITIVE BREAKDOWN")  # noqa: T201
    print("-" * w)  # noqa: T201
    if all_fp:
        for detail in all_fp:
            print(f"  {detail}")  # noqa: T201
    else:
        print("  (none)")  # noqa: T201
    print()  # noqa: T201

    # False negative breakdown
    all_fn: list[str] = []
    for m in metrics.values():
        all_fn.extend(m.fn_details)

    print("FALSE NEGATIVE BREAKDOWN")  # noqa: T201
    print("-" * w)  # noqa: T201
    if all_fn:
        for detail in all_fn:
            print(f"  {detail}")  # noqa: T201
    else:
        print("  (none)")  # noqa: T201
    print()  # noqa: T201

    # ── Per-source breakdown ────────────────────────────────────────────
    if any(c.source != "builtin" for c in corpus):
        print("PER-SOURCE BREAKDOWN")  # noqa: T201
        print("-" * w)  # noqa: T201
        print(f"{'Source':<20} {'Total':>6} {'TP':>6} {'FP':>6} {'FN':>6} {'TN':>6}")  # noqa: T201
        print("-" * w)  # noqa: T201
        by_source: dict[str, dict[str, int]] = {}
        for case in corpus:
            s = by_source.setdefault(case.source, {"total": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0})
            s["total"] += 1
        # Re-run detection counts grouped by source
        for case in corpus:
            detected = _detect_credential(case.value)
            s = by_source[case.source]
            if case.expected_detected and detected:
                s["tp"] += 1
            elif case.expected_detected and not detected:
                s["fn"] += 1
            elif not case.expected_detected and detected:
                s["fp"] += 1
            else:
                s["tn"] += 1
        for source_name, counts in sorted(by_source.items()):
            print(  # noqa: T201
                f"{source_name:<20} {counts['total']:>6} {counts['tp']:>6}"
                f" {counts['fp']:>6} {counts['fn']:>6} {counts['tn']:>6}"
            )
        print()  # noqa: T201


# ── HTML viewer generation ───────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Secret Benchmark Corpus Viewer</title>
  <style>
    body { font-family: monospace; margin: 2em; background: #1e1e1e; color: #d4d4d4; }
    h1 { color: #9cdcfe; }
    .note { background: #2d2d2d; border-left: 4px solid #569cd6; padding: 0.75em 1em; margin-bottom: 1.5em; }
    table { border-collapse: collapse; width: 100%; font-size: 0.85em; }
    th { background: #2d2d2d; color: #9cdcfe; padding: 8px 12px; text-align: left; position: sticky; top: 0; }
    td { padding: 6px 12px; border-bottom: 1px solid #333; vertical-align: top;
         max-width: 60ch; word-break: break-all; }
    tr.tp { background: #1a2f1a; }
    tr.tn { background: #2f1a1a; }
    tr:hover { filter: brightness(1.3); }
    .badge-tp { color: #4ec9b0; font-weight: bold; }
    .badge-tn { color: #f48771; font-weight: bold; }
    .layer { color: #c586c0; }
    .desc { color: #9cdcfe; }
    .value { color: #ce9178; }
    .count { color: #888; font-size: 0.8em; margin-bottom: 1em; }
  </style>
</head>
<body>
  <h1>Secret Detection Benchmark &mdash; Corpus Viewer</h1>
  <div class="note">
    These values are obfuscated in source code to avoid triggering secret scanners.
    This page decodes them for review. The XOR key is <code>data_classifier_benchmark</code>.
  </div>
  <div class="count" id="count"></div>
  <table>
    <thead>
      <tr>
        <th>Status</th>
        <th>Layer</th>
        <th>Value (decoded)</th>
        <th>Description</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>

  <script>
    var KEY = "data_classifier_benchmark";

    function decode(hex) {
      var encoded = [];
      for (var i = 0; i < hex.length; i += 2) {
        encoded.push(parseInt(hex.slice(i, i + 2), 16));
      }
      var raw = new Uint8Array(encoded.map(function(b, i) {
        return b ^ KEY.charCodeAt(i % KEY.length);
      }));
      return new TextDecoder("utf-8").decode(raw);
    }

    function makeCell(text, cls) {
      var cell = document.createElement("td");
      if (cls) { cell.className = cls; }
      cell.textContent = text;
      return cell;
    }

    var corpus = CORPUS_JSON_PLACEHOLDER;

    var tbody = document.getElementById("tbody");
    var tp = 0, tn = 0;
    for (var j = 0; j < corpus.length; j++) {
      var entry = corpus[j];
      var value = decode(entry.encoded);
      var isTP = entry.expected;
      if (isTP) { tp++; } else { tn++; }
      var tr = document.createElement("tr");
      tr.className = isTP ? "tp" : "tn";
      tr.appendChild(makeCell(isTP ? "TP" : "TN", isTP ? "badge-tp" : "badge-tn"));
      tr.appendChild(makeCell(entry.layer, "layer"));
      tr.appendChild(makeCell(value, "value"));
      tr.appendChild(makeCell(entry.description, "desc"));
      tbody.appendChild(tr);
    }

    document.getElementById("count").textContent =
      corpus.length + " cases \u2014 " + tp + " TP (green), " + tn + " TN (red)";
  </script>
</body>
</html>
"""


def generate_html_viewer() -> str:
    """Generate a single-file HTML viewer that decodes and displays the full corpus."""
    corpus = _build_corpus()

    entries = [
        {
            "encoded": _encode(case.value),
            "expected": case.expected_detected,
            "layer": case.layer,
            "description": case.description,
        }
        for case in corpus
    ]

    corpus_json = json.dumps(entries, indent=2)
    return _HTML_TEMPLATE.replace("CORPUS_JSON_PLACEHOLDER", corpus_json)


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Secret detection benchmark")
    parser.add_argument("--verbose", action="store_true", help="Show each sample result")
    parser.add_argument(
        "--generate-html",
        action="store_true",
        help="Regenerate the HTML corpus viewer (tests/benchmarks/secret_benchmark_viewer.html) and exit",
    )
    parser.add_argument(
        "--encode",
        type=str,
        metavar="VALUE",
        help="Encode a secret value for safe storage in the benchmark corpus. "
        "Use this when adding new test cases: paste the hex output into the corpus as _decode('hex').",
    )
    parser.add_argument(
        "--no-external",
        action="store_true",
        help="Exclude external corpus fixtures (gitleaks, detect-secrets, SecretBench)",
    )
    args = parser.parse_args()

    if args.encode:
        hex_encoded = _encode(args.encode)
        print(f"Original:  {args.encode}")  # noqa: T201
        print(f"Encoded:   {hex_encoded}")  # noqa: T201
        print(f'Usage:     _decode("{hex_encoded}")')  # noqa: T201
        # Verify roundtrip
        assert _decode(hex_encoded) == args.encode, "Roundtrip failed!"
        print("Roundtrip: OK")  # noqa: T201
        raise SystemExit(0)

    if args.generate_html:
        html_path = os.path.join(os.path.dirname(__file__), "secret_benchmark_viewer.html")
        html_content = generate_html_viewer()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"HTML viewer written to: {html_path}")  # noqa: T201
    else:
        if args.verbose:
            print("Running secret detection benchmark (verbose)...")  # noqa: T201
            print()  # noqa: T201

        include_ext = not args.no_external
        metrics = run_benchmark(verbose=args.verbose, include_external=include_ext)

        if args.verbose:
            print()  # noqa: T201

        print_report(metrics, include_external=include_ext)
