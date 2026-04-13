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
from data_classifier.engines.heuristic_engine import compute_char_class_diversity, compute_shannon_entropy
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.engines.parsers import parse_key_values

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


# Regex for values that look like dates, versions, or numeric IDs
_DATE_LIKE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
_URL_LIKE = re.compile(r"^https?://", re.IGNORECASE)

# ── Fast-path rejection (item: secret-scanner-fast-path-rejection) ──────────
# Structural screen for "could this value plausibly contain a secret?".
# If neither a KV indicator NOR a known secret prefix is present, the value
# is almost certainly not a secret and we can skip expensive parsing.
_KV_CHARS: frozenset[str] = frozenset("=\"':")

_SECRET_PREFIXES: tuple[str, ...] = (
    # Known high-confidence token prefixes — these identify a raw token even
    # without surrounding KV structure, so their presence disables fast-path.
    "sk-",
    "ghp_",
    "github_pat_",
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
    "ssh-rsa",
    "ssh-ed25519",
    "-----BEGIN",
    "Bearer ",
    "Basic ",
    "Token ",
    "Authorization",
    "eyJ",  # JWT header (base64-encoded {"alg":... starts with eyJ)
)


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
    # YOUR_*_KEY / YOUR_*_TOKEN / YOUR_*_SECRET style
    re.compile(
        r"your[_\-\s]?(api|access|auth|secret|token|private|aws|gcp|azure)?"
        r"[_\-\s]?(key|token|secret|password|credential)",
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

    # Prose — contains spaces and is mostly alphabetic
    # Real credentials rarely have spaces; descriptions/policies always do
    if " " in value:
        alpha_chars = sum(1 for c in value if c.isalpha())
        if alpha_chars / max(len(value), 1) > prose_threshold:
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
    ) -> list[ClassificationFinding]:
        """Classify a column by scanning sample values for embedded secrets.

        For each sample value, parses key-value pairs and scores them
        using tiered key-name matching and relative entropy analysis.

        Returns findings for columns where embedded credentials are detected.
        """
        self._ensure_config()

        if not column.sample_values:
            return []

        min_value_length = self._config.get("min_value_length", 8)
        anti_indicators = self._config.get("anti_indicators", [])

        matched_evidence: list[str] = []
        matched_sample_indices: set[int] = set()
        best_confidence = 0.0
        best_evidence = ""
        best_subtype = _DEFAULT_SUBTYPE
        samples_scanned = 0

        for idx, sample in enumerate(column.sample_values):
            if not sample:
                continue
            samples_scanned += 1

            # Fast-path rejection: skip values with no KV structure and no
            # known secret prefix. Pure random strings (e.g. "R4nd0mSt1ng")
            # cannot produce a scanner finding, so we avoid the parser call.
            if not _has_secret_indicators(sample):
                continue

            # Deduplicate KV pairs (env + code parsers can overlap)
            kv_pairs = list(dict.fromkeys(parse_key_values(sample)))
            if not kv_pairs:
                continue

            for key, value in kv_pairs:
                # Skip short values
                if len(value) < min_value_length:
                    continue

                # Anti-indicator suppression on key and value
                if self._has_anti_indicator(key, value, anti_indicators):
                    continue

                # Known placeholder suppression (exact match of seeded list)
                if value.lower() in self._placeholder_values:
                    continue

                # Gitleaks placeholder pattern suppression (sprint 6):
                # e.g. "xxxxxxxxxxxx", "YOUR_API_KEY", "<your-token>".
                if _is_placeholder_value(value):
                    continue

                # Score the key name (returns score, tier, and credential subtype)
                key_score, tier, subtype = _score_key_name(key, self._key_entries)
                if key_score <= 0.0:
                    continue

                # Tiered scoring
                composite = self._compute_tiered_score(key_score, tier, value)
                if composite <= 0.0:
                    continue

                if composite >= min_confidence:
                    matched_sample_indices.add(idx)
                    if composite > best_confidence:
                        best_confidence = composite
                        best_subtype = subtype
                        rel_entropy = _compute_relative_entropy(value)
                        charset = _detect_charset(value)
                        best_evidence = (
                            f"Secret scanner: key '{key}' (score={key_score:.2f}, tier={tier}, "
                            f"subtype={subtype}) with {charset} "
                            f"relative_entropy={rel_entropy:.2f} composite={composite:.2f}"
                        )
                    if len(matched_evidence) < max_evidence_samples:
                        display_value = _mask_value(value) if mask_samples else value
                        matched_evidence.append(f"{key}={display_value}")

        if best_confidence <= 0.0 or best_confidence < min_confidence:
            return []

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
                sample_analysis=sample_analysis,
            )
        ]

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

        if tier == "definitive":
            # Key name is strong evidence, but reject values that are clearly not credentials
            if _value_is_obviously_not_secret(value, prose_threshold=prose_threshold):
                return 0.0
            return key_score * definitive_mult

        if tier == "strong":
            rel_entropy = _compute_relative_entropy(value)
            diversity = compute_char_class_diversity(value)
            if rel_entropy >= strong_rel or diversity >= diversity_min:
                return key_score * max(strong_min, _score_relative_entropy(rel_entropy))
            return 0.0

        # contextual tier — need strong value signal
        rel_entropy = _compute_relative_entropy(value)
        diversity = compute_char_class_diversity(value)
        if rel_entropy >= contextual_rel and diversity >= diversity_min:
            return key_score * _score_relative_entropy(rel_entropy)
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
