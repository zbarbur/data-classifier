"""Structured Secret Scanner Engine — detects secrets in structured content.

Finds credentials embedded in JSON, YAML, env files, and code string literals
by combining key-name scoring with Shannon entropy analysis.  Catches secrets
that regex engines cannot detect — values with no known prefix or format,
identified only by their key name and high entropy.

Example detections:
  - ``"db_password": "kJ#9xMp$2wLq!"`` — key name + high entropy
  - ``export API_TOKEN=a8f3b2c1d4e5`` — env var name + entropy
  - ``password = "SuperSecret123!"`` — code literal assignment

Order 4 in the engine cascade (after heuristic_stats).
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

from data_classifier.config import load_engine_config
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
    SampleAnalysis,
)
from data_classifier.engines.heuristic_engine import (
    compute_char_class_diversity,
    compute_char_class_evenness,
    compute_shannon_entropy,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.engines.parsers import parse_key_values
from data_classifier.engines.structural_parsers import detect_structural_secrets

logger = logging.getLogger(__name__)

_SECRET_KEY_NAMES_FILE = Path(__file__).parent.parent / "patterns" / "secret_key_names.json"
_PLACEHOLDER_VALUES_FILE = Path(__file__).parent.parent / "patterns" / "known_placeholder_values.json"

# Theoretical maximum entropy per character for each detected charset
_CHARSET_MAX_ENTROPY: dict[str, float] = {
    "hex": math.log2(16),  # 4.0
    "base64": math.log2(64),  # 6.0
    "alphanumeric": math.log2(62),  # 5.95
    "full": math.log2(95),  # 6.57
}


def _detect_charset(value: str) -> str:
    """Detect the character set of a value for entropy threshold selection.

    Args:
        value: The string to analyze.

    Returns:
        One of ``"hex"``, ``"base64"``, ``"alphanumeric"``, or ``"full"``.
    """
    if re.fullmatch(r"[0-9a-fA-F]+", value):
        return "hex"
    if re.fullmatch(r"[A-Za-z0-9+/=]+", value):
        return "base64"
    if re.fullmatch(r"[A-Za-z0-9]+", value):
        return "alphanumeric"
    return "full"


def _compute_relative_entropy(value: str) -> float:
    """Compute entropy as fraction of theoretical maximum for the detected charset.

    Args:
        value: The string to analyze.

    Returns:
        Relative entropy between 0.0 and 1.0.
    """
    entropy = compute_shannon_entropy(value)
    charset = _detect_charset(value)
    max_entropy = _CHARSET_MAX_ENTROPY.get(charset, _CHARSET_MAX_ENTROPY["full"])
    if max_entropy == 0:
        return 0.0
    return min(1.0, entropy / max_entropy)


def _score_relative_entropy(relative_entropy: float) -> float:
    """Convert relative entropy to a 0.0-1.0 score.

    Linear scaling: returns 0.0 below 0.5, then scales linearly up to 1.0.

    Args:
        relative_entropy: Relative entropy between 0.0 and 1.0.

    Returns:
        Score between 0.0 and 1.0.
    """
    if relative_entropy < 0.5:
        return 0.0
    return min(1.0, relative_entropy)


# Regex for values that are obviously not credentials
_DATE_LIKE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
_URL_LIKE = re.compile(r"^https?://", re.IGNORECASE)
_IP_LIKE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_NUMERIC_ONLY = re.compile(r"^[\d\s.,+-]+$")

# Code expression patterns — values that are code references, not secrets.
# Must contain at least one property accessor (dot, bracket) or end with
# a statement terminator (;). Bare identifiers do NOT match.
# e.g. form.password.data, textBox2.Text, message.text, request.POST["x"]
_CODE_DOT_NOTATION = re.compile(r"^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)+[;,]?$")
_CODE_BRACKET_ACCESS = re.compile(r"^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*\[[^\]]+\][;,]?$")
_CODE_SEMICOLON = re.compile(r"^[a-zA-Z_]\w*;$")

# Code call pattern — value contains assignment or statement body e.g. "request.session.auth_token;"
# Catches mixed-context expressions that dot-notation alone misses.
_CODE_CALL = re.compile(r"[({].*[=;]")

# Shell/env variable reference — value starts with $ (e.g. $password, ${DB_PASS}).
# Excludes password hash prefixes: $2b$, $2y$, $2a$, $5$, $6$, $argon2, $scrypt
# which use the crypt(3) $algorithm$params$hash convention.
_SHELL_VARIABLE = re.compile(r"^\$(?!2[aby]\$|[56]\$|argon2|scrypt)[\w{]")

# ALL_CAPS constant names — e.g. API_KEY_BINANCE, ARGILLA_API_KEY, VERACODE-HMAC-SHA-256.
# Separators can be underscores or hyphens. Must have at least one separator
# (pure uppercase like ABCDEF could be hex).
_CONSTANT_NAME = re.compile(r"^[A-Z][A-Z0-9]*([_-][A-Z0-9]+)+$")

# Code punctuation — value is just brackets, parens, semicolons.
# e.g. "));", "])", "{};" — obviously not a secret.
_CODE_PUNCTUATION = re.compile(r"^[\[\](){};<>,./\\|!@#%^&*\-+=~`\s]+$")

# File/directory path — e.g. /home/user/.config/token, C:\Users\secret
_FILE_PATH = re.compile(r"^[/~][\w./\-]+$|^[A-Z]:\\[\w\\.\-]+$")

# ── Known secret prefixes (KV fast-path gate only) ───────────────────────────
# These prefixes activate KV parsing even when no `=`/`:` is present.
# Prefix-based *detection* is handled by the regex engine's specific patterns
# (e.g. aws_access_key, github_token, jwt_token) which are more precise.
_SECRET_PREFIXES: tuple[str, ...] = (
    "-----BEGIN",
    "ssh-ed25519",
    "ssh-rsa",
    "github_pat_",
    "ghp_",
    "gho_",
    "ghs_",
    "ghr_",
    "ghu_",
    "AKIA",
    "ASIA",
    "xoxb-",
    "xoxp-",
    "xoxa-",
    "xoxr-",
    "sk-",
    "eyJ",
    "Bearer ",
    "Basic ",
    "Token ",
    "Authorization",
)

# KV structure characters — fast-path gate for Path 2 (KV parsing).
_KV_CHARS: frozenset[str] = frozenset("=\"':")

# ── Path 3: Population-level analysis constants ──────────────────────────────
_MIN_STATISTICAL_SAMPLES = 5
_STATISTICAL_ENTROPY_THRESHOLD = 0.7
_STATISTICAL_DIVERSITY_THRESHOLD = 3
_STATISTICAL_BASE_CONFIDENCE = 0.55
_STATISTICAL_MAX_CONFIDENCE = 0.80
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


# ── Gitleaks placeholder FP suppression (item: gitleaks-fp-analysis) ────────
# Sprint 4 gitleaks corpus analysis surfaced ~37 false positive cases where
# the secret scanner fired on obvious placeholder / template values
# ("YOUR_API_KEY_HERE", "xxxxxxxxxxxx", "<your-token>", etc.).  These regex
# patterns suppress them without hiding real secrets — the control case
# (a real-looking AWS access key) still fires.
#
# Order matters for performance only (cheap checks first).  Each pattern is
# applied case-insensitively against the extracted KV value (not the full
# sample), so it only triggers on the specific field that looked like a
# secret.
_PLACEHOLDER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 5+ consecutive x/X — e.g. "xxxxxxxxxxxx", "AKIAXXXXXXXXXXXXXXXX"
    re.compile(r"x{5,}", re.IGNORECASE),
    # Any character repeated 8+ times — e.g. "glc_111111111111..."
    re.compile(r"(.)\1{7,}"),
    # Angle-bracket placeholders — e.g. "<your-api-key>", "<TOKEN>"
    re.compile(r"<[^>]{1,80}>"),
    # Square-bracket placeholders — e.g. "[PASSWORD]", "[YOUR_KEY]"
    re.compile(r"^\[[A-Z_]{2,}\]$"),
    # YOUR_*_KEY / YOUR_*_TOKEN / YOUR_*_SECRET style — allow any words
    # between "your" and the credential suffix (e.g. "your-openai-api-key",
    # "YOUR_TELEGRAM_BOT_TOKEN")
    re.compile(
        r"your[_\-\s][\w\-\s]{0,30}(key|token|secret|password|credential)\b",
        re.IGNORECASE,
    ),
    # PUT_YOUR_*_HERE style
    re.compile(r"put[_\-\s]?your", re.IGNORECASE),
    re.compile(r"insert[_\-\s]?your", re.IGNORECASE),
    re.compile(r"replace[_\-\s]?(me|with|this)", re.IGNORECASE),
    # Placeholder sentinel words
    re.compile(r"placeholder", re.IGNORECASE),
    re.compile(r"redacted", re.IGNORECASE),
    re.compile(r"\bexample\b", re.IGNORECASE),
    re.compile(r"^sample[_\-]", re.IGNORECASE),
    re.compile(r"^dummy[_\-]?", re.IGNORECASE),
    # Common templating markers
    re.compile(r"\{\{.*\}\}"),  # {{VAR}} Jinja / mustache
    re.compile(r"\$\{[A-Z_]+\}"),  # ${VAR} shell
    # AWS documentation example keys (all end in "EXAMPLE")
    re.compile(r"EXAMPLE$"),
    # Common "here" / "goes here" hints
    re.compile(r"(key|token|secret|password)[_\-\s]here", re.IGNORECASE),
    re.compile(r"goes[_\-\s]here", re.IGNORECASE),
    # "changeme" and common lazy placeholders (word-boundary to avoid
    # matching real tokens that coincidentally contain these letters)
    re.compile(r"\bchangeme\b", re.IGNORECASE),
    re.compile(r"\bfoobar\b", re.IGNORECASE),
    re.compile(r"\btodo\b", re.IGNORECASE),
    re.compile(r"\bfixme\b", re.IGNORECASE),
    # Long sequential alphabetic run (10+ chars) — e.g. "abcdefghijkl".
    # Shorter runs (ABCDEF) appear in hex tokens; require 10+ to avoid FPs.
    re.compile(
        r"abcdefghij|bcdefghijk|cdefghijkl|defghijklm|efghijklmn|fghijklmno|ghijklmnop|hijklmnopq|ijklmnopqr|jklmnopqrs|klmnopqrst|lmnopqrstu|mnopqrstuv|nopqrstuvw|opqrstuvwx|pqrstuvwxy|qrstuvwxyz",
        re.IGNORECASE,
    ),
)


def _is_placeholder_value(value: str) -> bool:
    """Return True if ``value`` looks like a gitleaks-style placeholder.

    Used by the secret scanner to suppress findings on template/example
    values such as ``"xxxxxxxxxxxxxxxx"``, ``"YOUR_API_KEY_HERE"``,
    ``"<your-token>"``, ``"{{API_KEY}}"``.

    Args:
        value: The extracted KV value to test.

    Returns:
        ``True`` if the value matches any placeholder pattern.
    """
    for pat in _PLACEHOLDER_PATTERNS:
        if pat.search(value):
            return True
    return False


# Sprint 13 S0: compound-name suffixes that indicate the key is NOT a
# credential. These are identifiers, UI fields, blockchain addresses, etc.
# The key "token_address" contains "token" (a secret-bearing word) but the
# full compound name means "blockchain wallet address" (public by design).
# Suffixes deliberately conservative — _token, _secret, _key are NOT here.
_NON_SECRET_SUFFIXES: tuple[str, ...] = (
    "_address",
    "_field",
    "_id",
    "_name",
    "_input",
    "_label",
    "_placeholder",
    "_url",
    "_endpoint",
    "_file",
    "_path",
    "_dir",
    "_prefix",
    "_suffix",
    "_format",
    "_type",
    "_mode",
    "_status",
    "_count",
    "_size",
    "_length",
)

# Explicit allowlist: compound names ending with a stoplist suffix that ARE
# actually sensitive. session_id and auth_id carry session tokens which are
# credentials in DLP context.
_NON_SECRET_ALLOWLIST: frozenset[str] = frozenset(
    {
        "session_id",
        "auth_id",
        "client_id",
    }
)


def _is_compound_non_secret(key: str) -> bool:
    """Return True if the key name is a compound that typically does NOT hold a secret."""
    lower = key.lower().strip()
    if lower in _NON_SECRET_ALLOWLIST:
        return False
    return any(lower.endswith(suffix) for suffix in _NON_SECRET_SUFFIXES)


def _has_secret_indicators(value: str) -> bool:
    """Return True if a value shows any structural hint of carrying a secret.

    Used by the secret scanner as a fast-path gate: when this returns False,
    the value contains no KV delimiters (``=``, ``:``, quotes) and no known
    secret prefix (``ghp_``, ``AKIA``, ``ssh-rsa``, ``eyJ`` JWT, ...), so
    there is nothing for the parser to extract and we can skip it entirely.

    This sharpens both perf (non-secret values skip expensive parsing) and
    precision (fewer opportunities for regex-style false positives on pure
    random strings).  Raw secret tokens whose only signal is a known prefix
    still pass through the full pipeline because their prefix is listed.

    Args:
        value: The sample value to screen.

    Returns:
        ``True`` if the value may carry a secret, ``False`` if it can be
        skipped by the scanner.
    """
    if not value:
        return False
    # KV chars: fastest check — single pass over the string.
    for ch in value:
        if ch in _KV_CHARS:
            return True
    # Known secret prefixes — check for presence anywhere so a leading space
    # or quote doesn't hide the prefix (prefix-at-start is the common case
    # but substring containment is cheap and more forgiving).
    for prefix in _SECRET_PREFIXES:
        if prefix in value:
            return True
    return False


# Common config values that are not credentials
_CONFIG_VALUES: frozenset[str] = frozenset(
    {
        "true",
        "false",
        "yes",
        "no",
        "on",
        "off",
        "enabled",
        "disabled",
        "none",
        "null",
        "info",
        "debug",
        "warn",
        "error",
        "trace",
        "production",
        "staging",
        "development",
        "test",
    }
)


def _value_is_obviously_not_secret(value: str, *, prose_threshold: float = 0.6) -> bool:
    """Check if a value is obviously NOT a credential.

    Rejects prose text, dates, URLs, and common config values even when
    the key name strongly suggests a secret. This prevents false positives
    on keys like ``password_policy``, ``password_last_changed``.

    Args:
        value: The value string to check.
        prose_threshold: Fraction of alpha characters above which a
            space-containing value is considered prose (from config).

    Returns:
        True if the value is clearly not a credential.
    """
    v_lower = value.lower().strip()

    # Common config values
    if v_lower in _CONFIG_VALUES:
        return True

    # URLs
    if _URL_LIKE.match(value):
        return True

    # Date-like patterns (2024-01-15, 2024/01/15)
    if _DATE_LIKE.match(value):
        return True

    # IP addresses (192.168.1.1)
    if _IP_LIKE.match(value):
        return True

    # Pure numeric values (phone numbers, IDs, amounts)
    if _NUMERIC_ONLY.match(value):
        return True

    # Code expressions — dot-notation property access, bracket notation.
    # e.g. form.password.data, textBox2.Text, request.POST["x"], tokenApp;
    # Guard: skip if any dot-separated segment is suspiciously long (>32 chars)
    # — that pattern is a JWT or similar token, not a code identifier chain.
    if _CODE_DOT_NOTATION.match(value):
        if all(len(seg) <= 32 for seg in value.rstrip(";,").split(".")):
            return True
    if _CODE_BRACKET_ACCESS.match(value) or _CODE_SEMICOLON.match(value):
        return True

    # Code call pattern — assignment or statement body inside parens/braces.
    # e.g. "request.session.auth_token;", "(foo=bar;)"
    if _CODE_CALL.search(value):
        return True

    # Shell/env variable references — e.g. $password, ${DB_PASS}
    if _SHELL_VARIABLE.match(value):
        return True

    # ALL_CAPS constant names — e.g. API_KEY_BINANCE, ARGILLA_API_KEY
    if _CONSTANT_NAME.match(value):
        return True

    # Code punctuation — e.g. "));", "])", "{};"
    if _CODE_PUNCTUATION.match(value):
        return True

    # File paths — e.g. /home/user/.yt/token, ~/config/secret
    if _FILE_PATH.match(value):
        return True

    # Single plain word — only letters and hyphens, no digits or special chars
    # (e.g. "Steganography", "authorization-text"). Real secrets have mixed classes.
    # Guard: skip if value is long (>30 chars) — long alpha-hyphen strings like
    # "pk-LMZITIrROWZRwazmrhTnzuXMDjHRhbtKNAKSkyQciVKwteQc" are real API keys.
    if len(value.strip()) <= 30 and re.fullmatch(r"[a-zA-Z]+(-[a-zA-Z]+)*", value.strip()):
        return True

    # String concatenation — value is a variable reference or expression.
    # Covers: "+my_token+", '" + textBox2.Text + "', etc.
    stripped = value.strip().strip("\"'").strip()
    if stripped.startswith("+") or stripped.endswith("+"):
        return True

    # Prose — contains spaces and is mostly alphabetic
    # Real credentials rarely have spaces; descriptions/policies always do
    if " " in value:
        alpha_chars = sum(1 for c in value if c.isalpha())
        if alpha_chars / max(len(value), 1) > prose_threshold:
            return True

    # Non-spaced scripts (CJK, Cyrillic, Arabic): any character in these
    # ranges means human language, not a credential.  Secrets are ASCII.
    if re.search(r"[\u3000-\u9FFF\uAC00-\uD7AF\u0400-\u04FF\u0600-\u06FF]", value):
        return True

    return False


def _match_key_pattern(key_lower: str, pattern: str, match_type: str) -> bool:
    """Check if a key matches a pattern according to the match_type rule.

    Args:
        key_lower: The lowered key name to test.
        pattern: The pattern to match against.
        match_type: One of ``"substring"``, ``"word_boundary"``, or ``"suffix"``.

    Returns:
        True if the key matches.
    """
    if match_type == "word_boundary":
        return bool(re.search(rf"(^|[_\-\s.]){re.escape(pattern)}($|[_\-\s.])", key_lower))
    if match_type == "suffix":
        return bool(re.search(rf"[_\-\s.]{re.escape(pattern)}$", key_lower))
    # Default: substring
    return pattern in key_lower


_DEFAULT_SUBTYPE = "OPAQUE_SECRET"


def _score_key_name(key: str, key_entries: list[dict]) -> tuple[float, str, str]:
    """Score a key name against the secret key-name dictionary.

    Performs matching according to each entry's ``match_type``: substring,
    word_boundary, or suffix.  Returns the highest matching score, its tier,
    and its credential subtype (one of ``API_KEY``, ``PRIVATE_KEY``,
    ``PASSWORD_HASH``, or ``OPAQUE_SECRET``).

    Args:
        key: The key name to score (e.g. ``"DB_PASSWORD"``).
        key_entries: List of dicts with ``pattern``, ``score``, ``match_type``,
            ``tier``, and ``subtype`` keys.

    Returns:
        Tuple of (score, tier, subtype).  ``(0.0, "", "OPAQUE_SECRET")`` if no
        pattern matches.
    """
    key_lower = key.lower()
    best_score = 0.0
    best_tier = ""
    best_subtype = _DEFAULT_SUBTYPE
    for entry in key_entries:
        pattern = entry["pattern"]
        match_type = entry.get("match_type", "substring")
        if _match_key_pattern(key_lower, pattern, match_type):
            if entry["score"] > best_score:
                best_score = entry["score"]
                best_tier = entry.get("tier", _tier_from_score(entry["score"]))
                best_subtype = entry.get("subtype", _DEFAULT_SUBTYPE)
    return best_score, best_tier, best_subtype


def _tier_from_score(score: float) -> str:
    """Derive tier from score when not explicitly set.

    Args:
        score: The key-name score.

    Returns:
        Tier string: ``"definitive"``, ``"strong"``, or ``"contextual"``.
    """
    if score >= 0.90:
        return "definitive"
    if score >= 0.70:
        return "strong"
    return "contextual"


class SecretScannerEngine(ClassificationEngine):
    """Structured secret scanner — order 4 in the cascade.

    Detects credentials embedded in structured content (JSON, YAML, env
    files, code literals) by combining key-name scoring with Shannon
    entropy analysis.  Catches secrets that regex cannot detect.
    """

    name = "secret_scanner"
    order = 4
    min_confidence = 0.0
    supported_modes = frozenset({"structured", "unstructured"})

    def __init__(self) -> None:
        self._config: dict | None = None
        self._key_entries: list[dict] | None = None
        self._placeholder_values: frozenset[str] | None = None

    def startup(self) -> None:
        """Load engine configuration and key-name dictionary."""
        full_config = load_engine_config()
        self._config = full_config.get("secret_scanner", {})
        self._key_entries = _load_key_names()
        self._placeholder_values = _load_placeholder_values()
        logger.info("SecretScannerEngine: loaded %d key-name patterns", len(self._key_entries))

    def _ensure_config(self) -> None:
        """Lazily load config if startup() was not called."""
        if self._config is None or self._key_entries is None:
            self.startup()

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
        prior_findings: list[ClassificationFinding] | None = None,
    ) -> list[ClassificationFinding]:
        """Classify a column by scanning sample values for embedded secrets.

        Runs three detection paths in order of signal strength:

        1. **Column name** — column name scores against the key-name
           dictionary, each cell value is the candidate.
        2. **KV parsing** — parse key=value structure from text, score
           the key name with tiered entropy gating. If regex already
           matched the value, its ``detection_type`` and ``display_name``
           are used directly instead of generic entropy analysis.
        3. **Population** — no per-value signal, but the column's values
           collectively exhibit secret-like characteristics (high entropy,
           consistent length, high diversity).

        All paths share the same suppression pipeline (placeholders,
        anti-indicators, compound non-secret names).

        Args:
            prior_findings: Findings from earlier engines (e.g. regex).
                When a KV-extracted value overlaps with a prior finding,
                the secret scanner uses the prior finding's detection_type
                and display_name instead of generic classification.
        """
        self._ensure_config()

        if not column.sample_values:
            return []

        min_value_length = self._config.get("min_value_length", 8)
        anti_indicators = self._config.get("anti_indicators", [])

        # Build lookup from prior regex findings: matched value → finding.
        # When KV parsing extracts a value that regex already identified,
        # we use the regex finding's detection_type/display_name directly.
        regex_value_index: dict[str, ClassificationFinding] = {}
        for pf in prior_findings or []:
            if pf.sample_analysis and pf.sample_analysis.sample_matches:
                for mv in pf.sample_analysis.sample_matches:
                    regex_value_index[mv] = pf

        matched_evidence: list[str] = []
        matched_sample_indices: set[int] = set()
        best_confidence = 0.0
        best_evidence = ""
        best_subtype = _DEFAULT_SUBTYPE
        best_detection_type = ""
        best_display_name = ""
        samples_scanned = 0

        # ── Pre-score column name once (Path 1 gate) ─────────────────
        col_name = column.column_name or ""
        col_key_score, col_tier, col_subtype = 0.0, "", _DEFAULT_SUBTYPE
        if col_name and not _is_compound_non_secret(col_name):
            col_key_score, col_tier, col_subtype = _score_key_name(col_name, self._key_entries)

        # Collect unmatched values for Path 3 (population analysis)
        entropy_candidates: list[str] = []

        for idx, sample in enumerate(column.sample_values):
            if not sample:
                continue
            samples_scanned += 1
            value = sample.strip()

            if len(value) < min_value_length:
                continue

            # ── Prior regex match — skip analysis, adopt classification ─
            # If the regex engine already identified this value, use its
            # detection_type and display_name directly. No need for KV
            # parsing or entropy analysis.
            prior = regex_value_index.get(value)
            if prior is not None:
                matched_sample_indices.add(idx)
                if prior.confidence > best_confidence:
                    best_confidence = prior.confidence
                    best_subtype = prior.entity_type
                    best_detection_type = prior.detection_type
                    best_display_name = prior.display_name
                    best_evidence = (
                        f"Secret scanner: regex-identified {prior.detection_type or prior.entity_type} "
                        f"(confidence={prior.confidence:.2f})"
                    )
                if len(matched_evidence) < max_evidence_samples:
                    display = _mask_value(value) if mask_samples else value
                    matched_evidence.append(display)
                continue

            # ── Path 1: Column name as key ───────────────────────────
            if col_key_score > 0 and not self._value_is_suppressed(col_name, value, anti_indicators):
                composite = self._compute_tiered_score(col_key_score, col_tier, value)
                if composite > 0 and composite >= min_confidence:
                    matched_sample_indices.add(idx)
                    if composite > best_confidence:
                        best_confidence = composite
                        best_subtype = col_subtype
                        rel_ent = _compute_relative_entropy(value)
                        charset = _detect_charset(value)
                        best_evidence = (
                            f"Secret scanner: column '{col_name}' "
                            f"(score={col_key_score:.2f}, tier={col_tier}, "
                            f"subtype={col_subtype}) with {charset} "
                            f"relative_entropy={rel_ent:.2f} composite={composite:.2f}"
                        )
                    if len(matched_evidence) < max_evidence_samples:
                        display = _mask_value(value) if mask_samples else value
                        matched_evidence.append(f"{col_name}={display}")
                    continue

            # ── Path 2: KV parsing ───────────────────────────────────
            kv_parsed = False
            if _has_secret_indicators(sample):
                kv_pairs = list(dict.fromkeys(parse_key_values(sample)))
                if kv_pairs:
                    kv_parsed = True
                for key, kv_value in kv_pairs:
                    if len(kv_value) < min_value_length:
                        continue
                    if _is_compound_non_secret(key):
                        continue
                    if self._value_is_suppressed(key, kv_value, anti_indicators):
                        continue

                    # Check if regex already identified this KV value
                    kv_prior = regex_value_index.get(kv_value)
                    if kv_prior is not None:
                        matched_sample_indices.add(idx)
                        if kv_prior.confidence > best_confidence:
                            best_confidence = kv_prior.confidence
                            best_subtype = kv_prior.entity_type
                            best_detection_type = kv_prior.detection_type
                            best_display_name = kv_prior.display_name
                            best_evidence = (
                                f"Secret scanner: key '{key}' with regex-identified "
                                f"{kv_prior.detection_type or kv_prior.entity_type}"
                            )
                        if len(matched_evidence) < max_evidence_samples:
                            display_value = _mask_value(kv_value) if mask_samples else kv_value
                            matched_evidence.append(f"{key}={display_value}")
                        continue

                    key_score, tier, subtype = _score_key_name(key, self._key_entries)

                    composite = 0.0
                    if key_score > 0:
                        composite = self._compute_tiered_score(key_score, tier, kv_value)

                    if composite <= 0.0:
                        continue

                    if composite >= min_confidence:
                        matched_sample_indices.add(idx)
                        if composite > best_confidence:
                            best_confidence = composite
                            best_subtype = subtype
                            rel_entropy = _compute_relative_entropy(kv_value)
                            charset = _detect_charset(kv_value)
                            best_evidence = (
                                f"Secret scanner: key '{key}' (score={key_score:.2f}, tier={tier}, "
                                f"subtype={subtype}) with {charset} "
                                f"relative_entropy={rel_entropy:.2f} composite={composite:.2f}"
                            )
                        if len(matched_evidence) < max_evidence_samples:
                            display_value = _mask_value(kv_value) if mask_samples else kv_value
                            matched_evidence.append(f"{key}={display_value}")

            # Collect for Path 3: only unmatched, non-KV samples.
            # Samples with KV structure (even if suppressed) are structured
            # data, not bare opaque tokens — exclude from population analysis.
            if idx not in matched_sample_indices and not kv_parsed:
                entropy_candidates.append(value)

        # ── Path 3: Population-level entropy analysis ────────────────
        # No per-value signal from paths 1-3, but the column's values
        # collectively look like secrets: high entropy, consistent
        # length, high char-class diversity.
        if best_confidence < min_confidence and len(entropy_candidates) >= _MIN_STATISTICAL_SAMPLES:
            stat_result = self._analyze_population(entropy_candidates)
            if stat_result:
                conf, evidence = stat_result
                if conf >= min_confidence:
                    best_confidence = conf
                    best_subtype = _DEFAULT_SUBTYPE
                    best_evidence = evidence
                    for i, s in enumerate(column.sample_values):
                        if s and s.strip():
                            matched_sample_indices.add(i)
                    for s in entropy_candidates[:max_evidence_samples]:
                        matched_evidence.append(_mask_value(s) if mask_samples else s)

        # ── Structural parsers (Layer 3) ─────────────────────────────
        structural_findings: list[ClassificationFinding] = []
        for idx, sample in enumerate(column.sample_values):
            if not sample or idx in matched_sample_indices:
                continue
            s_findings = detect_structural_secrets(sample, column_id=column.column_id)
            for sf in s_findings:
                if sf.confidence >= min_confidence:
                    structural_findings.append(sf)
                    matched_sample_indices.add(idx)
                    if sf.confidence > best_confidence:
                        best_confidence = sf.confidence
                        best_subtype = sf.entity_type
                        best_evidence = sf.evidence
                    break

        if best_confidence <= 0.0 or best_confidence < min_confidence:
            return structural_findings if structural_findings else []

        if structural_findings and not matched_evidence:
            return structural_findings

        samples_matched = len(matched_sample_indices)
        sample_analysis = SampleAnalysis(
            samples_scanned=samples_scanned,
            samples_matched=samples_matched,
            samples_validated=samples_matched,
            match_ratio=samples_matched / max(samples_scanned, 1),
            sample_matches=matched_evidence,
        )

        return [
            ClassificationFinding(
                column_id=column.column_id,
                entity_type=best_subtype,
                category="Credential",
                sensitivity="CRITICAL",
                confidence=round(best_confidence, 4),
                regulatory=["SOC2", "ISO27001"],
                engine=self.name,
                evidence=best_evidence,
                detection_type=best_detection_type,
                display_name=best_display_name,
                sample_analysis=sample_analysis,
            )
        ]

    def _value_is_suppressed(self, key: str, value: str, anti_indicators: list[str]) -> bool:
        """Shared suppression checks for paths 2 and 3."""
        if self._has_anti_indicator(key, value, anti_indicators):
            return True
        if value.lower() in self._placeholder_values:
            return True
        if _is_placeholder_value(value):
            return True
        return False

    def _analyze_population(self, samples: list[str]) -> tuple[float, str] | None:
        """Path 3: Detect secret-like patterns at the population level.

        Fires when unmatched sample values collectively exhibit high entropy,
        high char-class diversity, and consistent length — even without any
        key name or prefix signal.

        Returns (confidence, evidence) or None.
        """
        # Exclude if majority are UUIDs (high entropy but not secrets)
        uuid_count = sum(1 for s in samples if _UUID_RE.fullmatch(s))
        if uuid_count > len(samples) * 0.5:
            return None

        entropies = [_compute_relative_entropy(s) for s in samples]
        diversities = [compute_char_class_diversity(s) for s in samples]
        lengths = [len(s) for s in samples]

        mean_entropy = sum(entropies) / len(entropies)
        mean_diversity = sum(diversities) / len(diversities)

        if mean_entropy < _STATISTICAL_ENTROPY_THRESHOLD:
            return None
        if mean_diversity < _STATISTICAL_DIVERSITY_THRESHOLD:
            return None

        # Length consistency (coefficient of variation)
        mean_len = sum(lengths) / len(lengths)
        len_std = (sum((ln - mean_len) ** 2 for ln in lengths) / len(lengths)) ** 0.5
        len_cv = len_std / mean_len if mean_len > 0 else 1.0

        confidence = _STATISTICAL_BASE_CONFIDENCE
        if len_cv < 0.1:
            confidence += 0.10
        if mean_entropy > 0.85:
            confidence += 0.10
        confidence = min(_STATISTICAL_MAX_CONFIDENCE, confidence)

        evidence = (
            f"Secret scanner: population analysis — "
            f"mean_rel_entropy={mean_entropy:.2f}, "
            f"mean_diversity={mean_diversity:.1f}, "
            f"length_cv={len_cv:.2f}, n={len(samples)}"
        )
        return confidence, evidence

    def _compute_tiered_score(self, key_score: float, tier: str, value: str) -> float:
        """Compute composite score based on the tier of the key-name match.

        All thresholds are loaded from ``engine_defaults.yaml`` scoring section.

        - ``"definitive"``: Key name alone is sufficient, but value must pass a
          plausibility check — prose, dates, URLs, and config values are rejected.
        - ``"strong"``: Needs moderate value signal — relative entropy or diversity.
        - ``"contextual"``: Needs strong value signal — relative entropy AND diversity.

        Args:
            key_score: The key-name match score (0.0-1.0).
            tier: One of ``"definitive"``, ``"strong"``, ``"contextual"``.
            value: The value string to analyze.

        Returns:
            Composite confidence score (0.0-1.0), or 0.0 if the value
            does not meet the tier's evidence requirements.
        """
        scoring = self._config.get("scoring", {})
        rel_thresholds = scoring.get("relative_entropy_thresholds", {})
        definitive_mult = scoring.get("definitive_multiplier", 0.95)
        strong_min = scoring.get("strong_min_entropy_score", 0.6)
        strong_rel = rel_thresholds.get("strong", 0.5)
        contextual_rel = rel_thresholds.get("contextual", 0.7)
        diversity_min = scoring.get("diversity_threshold", 3)
        prose_threshold = scoring.get("prose_alpha_threshold", 0.6)

        # Pre-filter: reject values that are obviously not credentials,
        # regardless of tier. Code expressions, file paths, constants, etc.
        # should never fire even with a definitive key name.
        if _value_is_obviously_not_secret(value, prose_threshold=prose_threshold):
            return 0.0

        if tier == "definitive":
            return key_score * definitive_mult

        if tier == "strong":
            rel_entropy = _compute_relative_entropy(value)
            diversity = compute_char_class_diversity(value)
            if rel_entropy >= strong_rel or diversity >= diversity_min:
                base_score = key_score * max(strong_min, _score_relative_entropy(rel_entropy))
                evenness_bonus = compute_char_class_evenness(value) * 0.15
                return min(base_score + evenness_bonus, 1.0)
            return 0.0

        # contextual tier — need strong value signal
        rel_entropy = _compute_relative_entropy(value)
        diversity = compute_char_class_diversity(value)
        if rel_entropy >= contextual_rel and diversity >= diversity_min:
            base_score = key_score * _score_relative_entropy(rel_entropy)
            evenness_bonus = compute_char_class_evenness(value) * 0.15
            return min(base_score + evenness_bonus, 1.0)
        return 0.0

    @staticmethod
    def _has_anti_indicator(key: str, value: str, anti_indicators: list[str]) -> bool:
        """Check if key or value contains any anti-indicator substring.

        Args:
            key: The key name.
            value: The value string.
            anti_indicators: List of substrings that suppress findings.

        Returns:
            True if any anti-indicator is found in key or value.
        """
        key_lower = key.lower()
        value_lower = value.lower()
        for indicator in anti_indicators:
            indicator_lower = indicator.lower()
            if indicator_lower in key_lower or indicator_lower in value_lower:
                return True
        return False


def _mask_value(value: str) -> str:
    """Mask a value for evidence display, showing only first/last 2 chars.

    Args:
        value: The value to mask.

    Returns:
        Masked string like ``"kJ***q!"``.
    """
    if len(value) <= 4:
        return "***"
    return value[:2] + "***" + value[-2:]


def _load_key_names() -> list[dict]:
    """Load secret key-name patterns from JSON file.

    Returns:
        List of dicts with ``pattern``, ``score``, ``category``,
        ``match_type``, and ``tier`` keys.

    Raises:
        FileNotFoundError: If the key-name dictionary file is missing.
        ValueError: If the file is malformed or missing the ``key_names`` key.
    """
    if not _SECRET_KEY_NAMES_FILE.exists():
        raise FileNotFoundError(f"Secret key-name dictionary not found: {_SECRET_KEY_NAMES_FILE}")
    with open(_SECRET_KEY_NAMES_FILE) as fh:
        raw = json.load(fh)
    if "key_names" not in raw:
        raise ValueError(f"Missing 'key_names' key in {_SECRET_KEY_NAMES_FILE}")
    return raw["key_names"]


def _load_placeholder_values() -> frozenset[str]:
    """Load known placeholder values from JSON file.

    Returns:
        Frozenset of lowercased placeholder value strings.

    Raises:
        FileNotFoundError: If the placeholder values file is missing.
        ValueError: If the file is malformed or missing the ``placeholder_values`` key.
    """
    if not _PLACEHOLDER_VALUES_FILE.exists():
        raise FileNotFoundError(f"Placeholder values file not found: {_PLACEHOLDER_VALUES_FILE}")
    with open(_PLACEHOLDER_VALUES_FILE) as fh:
        raw = json.load(fh)
    if "placeholder_values" not in raw:
        raise ValueError(f"Missing 'placeholder_values' key in {_PLACEHOLDER_VALUES_FILE}")
    return frozenset(v.lower() for v in raw["placeholder_values"])
