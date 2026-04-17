"""Structural secret parsers — Layer 3 detection for embedded credentials.

Detects credentials that regex alone misses because the secret is only
identifiable by its structural context: SQL statements, HTTP headers,
CLI arguments, and connection strings.

Each parser exposes a ``detect(value: str) -> list[ClassificationFinding]``
method that returns findings only when a genuine credential is embedded.

Integrated into the ``SecretScannerEngine`` as an additional detection layer.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

from data_classifier.core.types import ClassificationFinding, SampleAnalysis

logger = logging.getLogger(__name__)

# ── Shared helpers ──────────────────────────────────────────────────────────

# Minimum credential length to avoid firing on trivially short values
_MIN_CREDENTIAL_LEN = 6

# Placeholder patterns — suppress findings on template/example values
_PLACEHOLDER_RE = re.compile(
    r"<[^>]{1,80}>|"  # <your-password>
    r"\{\{.*?\}\}|"  # {{PASSWORD}}
    r"\$\{[A-Z_]+\}|"  # ${PASSWORD}
    r"x{5,}|"  # xxxxxxx
    r"your[_\- ]?(password|token|key|secret)|"  # your_password
    r"\bchangeme\b|"
    r"\bplaceholder\b|"
    r"\bredacted\b|"
    r"\bexample\b|"
    r"\bpassword\b$|"  # literal word "password" as the value
    r"\*{3,}",  # ***
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    """Return True if value looks like a placeholder, not a real credential."""
    return bool(_PLACEHOLDER_RE.search(value))


def _is_viable_credential(value: str) -> bool:
    """Return True if value is long enough and not a placeholder."""
    if len(value) < _MIN_CREDENTIAL_LEN:
        return False
    if _is_placeholder(value):
        return False
    return True


def _make_finding(
    column_id: str,
    entity_type: str,
    confidence: float,
    evidence: str,
    source: str,
    *,
    sample_value: str = "",
    samples_scanned: int = 1,
) -> ClassificationFinding:
    """Build a ClassificationFinding for a structural parser detection."""
    return ClassificationFinding(
        column_id=column_id,
        entity_type=entity_type,
        category="Credential",
        sensitivity="CRITICAL",
        confidence=round(confidence, 4),
        regulatory=["SOC2", "ISO27001"],
        engine=f"structural_parser:{source}",
        evidence=evidence,
        sample_analysis=SampleAnalysis(
            samples_scanned=samples_scanned,
            samples_matched=1,
            samples_validated=1,
            match_ratio=1.0 / max(samples_scanned, 1),
            sample_matches=[sample_value] if sample_value else [],
        ),
    )


# ── SQL Secret Parser ──────────────────────────────────────────────────────


# Patterns for SQL credential contexts
_SQL_PATTERNS: list[tuple[re.Pattern[str], str, int]] = [
    # CREATE USER ... IDENTIFIED BY 'password'
    (
        re.compile(
            r"(?:CREATE|ALTER)\s+(?:USER|LOGIN|ROLE)\s+\S+\s+"
            r"(?:IDENTIFIED\s+BY|WITH\s+PASSWORD\s*=?\s*)"
            r"\s*['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        "SQL CREATE/ALTER USER IDENTIFIED BY",
        1,
    ),
    # GRANT ... IDENTIFIED BY 'password'
    (
        re.compile(
            r"GRANT\s+.+?IDENTIFIED\s+BY\s+['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        "SQL GRANT IDENTIFIED BY",
        1,
    ),
    # SET PASSWORD = 'xxx' or SET PASSWORD FOR ... = 'xxx'
    (
        re.compile(
            r"SET\s+PASSWORD\s+(?:FOR\s+\S+\s+)?=\s*(?:PASSWORD\s*\(\s*)?['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        "SQL SET PASSWORD",
        1,
    ),
    # DSN-style in SQL context: mysql://user:pass@host/db, postgresql://...
    (
        re.compile(
            r"(?:mysql|postgresql|postgres|mariadb|mssql)://"
            r"([^:]+):([^@]+)@",
            re.IGNORECASE,
        ),
        "SQL DSN connection string",
        2,  # group 2 is the password
    ),
]


class SqlSecretParser:
    """Detect credentials embedded in SQL statements.

    Covers: CREATE USER ... IDENTIFIED BY, GRANT ... IDENTIFIED BY,
    SET PASSWORD, and DSN strings in SQL context.
    """

    source = "sql"

    def detect(self, value: str, column_id: str = "") -> list[ClassificationFinding]:
        """Scan a text value for SQL-embedded credentials.

        Args:
            value: The text to scan.
            column_id: Column identifier for the finding.

        Returns:
            List of findings for detected credentials.
        """
        if not value:
            return []

        findings: list[ClassificationFinding] = []
        value_upper = value.upper()

        # Quick structural check — must look like SQL
        has_sql_keyword = any(
            kw in value_upper for kw in ("CREATE ", "ALTER ", "GRANT ", "SET PASSWORD", "IDENTIFIED BY", "://")
        )
        if not has_sql_keyword:
            return []

        for pattern, description, group_idx in _SQL_PATTERNS:
            match = pattern.search(value)
            if match:
                credential = match.group(group_idx)
                if _is_viable_credential(credential):
                    findings.append(
                        _make_finding(
                            column_id=column_id,
                            entity_type="OPAQUE_SECRET",
                            confidence=0.90,
                            evidence=f"Structural parser (SQL): {description}",
                            source=self.source,
                            sample_value=value[:120],
                        )
                    )

        return findings


# ── HTTP Header Parser ──────────────────────────────────────────────────────

_HTTP_HEADER_PATTERNS: list[tuple[re.Pattern[str], str, str, int]] = [
    # Authorization: Bearer <token>
    (
        re.compile(r"Authorization\s*:\s*Bearer\s+(\S+)", re.IGNORECASE),
        "Authorization Bearer token",
        "API_KEY",
        1,
    ),
    # Authorization: Basic <base64>
    (
        re.compile(r"Authorization\s*:\s*Basic\s+([A-Za-z0-9+/=]+)", re.IGNORECASE),
        "Authorization Basic credentials",
        "OPAQUE_SECRET",
        1,
    ),
    # Authorization: Token <token>
    (
        re.compile(r"Authorization\s*:\s*Token\s+(\S+)", re.IGNORECASE),
        "Authorization Token",
        "API_KEY",
        1,
    ),
    # X-API-Key / X-Api-Key header
    (
        re.compile(r"X-API-Key\s*:\s*(\S+)", re.IGNORECASE),
        "X-API-Key header",
        "API_KEY",
        1,
    ),
    # Cookie with session token
    (
        re.compile(r"Cookie\s*:\s*(?:.*?;?\s*)?session[_-]?(?:id|token)?\s*=\s*([^\s;]+)", re.IGNORECASE),
        "Cookie session token",
        "OPAQUE_SECRET",
        1,
    ),
    # Generic auth headers: Api-Key, Access-Token, etc.
    (
        re.compile(
            r"(?:Api-Key|Access-Token|Auth-Token|X-Auth-Token|X-Access-Token)\s*:\s*(\S+)",
            re.IGNORECASE,
        ),
        "Custom auth header",
        "API_KEY",
        1,
    ),
]


class HttpHeaderParser:
    """Detect credentials in HTTP header values.

    Covers: Authorization Bearer/Basic/Token, X-API-Key,
    Cookie session tokens, custom auth headers.
    """

    source = "http_header"

    def detect(self, value: str, column_id: str = "") -> list[ClassificationFinding]:
        """Scan a text value for HTTP header credentials.

        Args:
            value: The text to scan.
            column_id: Column identifier for the finding.

        Returns:
            List of findings for detected credentials.
        """
        if not value:
            return []

        findings: list[ClassificationFinding] = []

        # Quick structural check — must contain a colon (header separator)
        if ":" not in value:
            return []

        for pattern, description, entity_type, group_idx in _HTTP_HEADER_PATTERNS:
            match = pattern.search(value)
            if match:
                credential = match.group(group_idx)
                if _is_viable_credential(credential):
                    findings.append(
                        _make_finding(
                            column_id=column_id,
                            entity_type=entity_type,
                            confidence=0.90,
                            evidence=f"Structural parser (HTTP): {description}",
                            source=self.source,
                            sample_value=value[:120],
                        )
                    )

        return findings


# ── CLI Argument Parser ─────────────────────────────────────────────────────

# Credential flag names (lowered) that indicate the next token is a credential
_CLI_CREDENTIAL_FLAGS: frozenset[str] = frozenset(
    {
        "--password",
        "--passwd",
        "--pass",
        "--token",
        "--api-key",
        "--api_key",
        "--apikey",
        "--secret",
        "--secret-key",
        "--auth-token",
        "--access-token",
        "--private-key",
        "--client-secret",
        "-p",
    }
)

# Pattern for --flag=value style
_CLI_FLAG_EQUALS_RE = re.compile(
    r"(?:--|-)(?:password|passwd|pass|token|api[_-]?key|secret(?:[_-]key)?|"
    r"auth[_-]token|access[_-]token|private[_-]key|client[_-]secret)"
    r"\s*=\s*['\"]?([^'\"\s]+)['\"]?",
    re.IGNORECASE,
)

# Pattern for --flag value (space-separated) style
_CLI_FLAG_SPACE_RE = re.compile(
    r"(?:--|-)(?:password|passwd|pass|token|api[_-]?key|secret(?:[_-]key)?|"
    r"auth[_-]token|access[_-]token|private[_-]key|client[_-]secret)"
    r"\s+['\"]?([^'\"\s]+)['\"]?",
    re.IGNORECASE,
)

# Short form: -p password
_CLI_SHORT_P_RE = re.compile(
    r"\s-p\s+['\"]?([^'\"\s]+)['\"]?",
    re.IGNORECASE,
)


class CliArgumentParser:
    """Detect credentials in CLI argument strings.

    Covers: --password=xxx, --token xxx, --api-key=xxx, -p password.
    """

    source = "cli_argument"

    def detect(self, value: str, column_id: str = "") -> list[ClassificationFinding]:
        """Scan a text value for CLI-embedded credentials.

        Args:
            value: The text to scan.
            column_id: Column identifier for the finding.

        Returns:
            List of findings for detected credentials.
        """
        if not value:
            return []

        # Quick structural check — must contain a dash (CLI flag indicator)
        if "-" not in value:
            return []

        findings: list[ClassificationFinding] = []
        seen_credentials: set[str] = set()

        for pattern in (_CLI_FLAG_EQUALS_RE, _CLI_FLAG_SPACE_RE, _CLI_SHORT_P_RE):
            for match in pattern.finditer(value):
                credential = match.group(1)
                if credential in seen_credentials:
                    continue
                seen_credentials.add(credential)
                if _is_viable_credential(credential):
                    findings.append(
                        _make_finding(
                            column_id=column_id,
                            entity_type="OPAQUE_SECRET",
                            confidence=0.85,
                            evidence="Structural parser (CLI): credential in CLI argument",
                            source=self.source,
                            sample_value=value[:120],
                        )
                    )

        return findings


# ── Connection String Parser ────────────────────────────────────────────────

# JDBC: jdbc:mysql://host?password=xxx or jdbc:mysql://host;password=xxx
_JDBC_PASSWORD_RE = re.compile(
    r"jdbc:[a-z]+://[^?;]*[?;].*?(?:password|pwd)\s*=\s*([^&;]+)",
    re.IGNORECASE,
)

# ODBC: Driver={...};Pwd=xxx or Password=xxx
_ODBC_PASSWORD_RE = re.compile(
    r"(?:Driver|DSN)\s*=.*?(?:Pwd|Password)\s*=\s*([^;]+)",
    re.IGNORECASE,
)

# URI-style: scheme://user:password@host
# Uses a greedy match up to the LAST @ before host (handles @ in passwords)
_URI_USERINFO_RE = re.compile(
    r"(?:postgresql|postgres|mysql|mariadb|mongodb(?:\+srv)?|amqp|rabbitmq|mssql)"
    r"://([^:]+):(.+)@[A-Za-z0-9._-]+",
    re.IGNORECASE,
)

# Redis URI: redis://:password@host (empty username, password-only auth)
_REDIS_URI_RE = re.compile(
    r"redis://(?::(.+)@|([^:]+):(.+)@)[A-Za-z0-9._-]+",
    re.IGNORECASE,
)

# Generic key=value in connection strings: password=xxx, pwd=xxx
_CONNSTR_KV_RE = re.compile(
    r"(?:^|;)\s*(?:password|pwd)\s*=\s*([^;]+)",
    re.IGNORECASE,
)


class ConnectionStringParser:
    """Detect credentials in database connection strings.

    Covers: JDBC, ODBC, PostgreSQL/MySQL/MongoDB/Redis URIs,
    and generic password= fields in connection strings.
    """

    source = "connection_string"

    def detect(self, value: str, column_id: str = "") -> list[ClassificationFinding]:
        """Scan a text value for connection string credentials.

        Args:
            value: The text to scan.
            column_id: Column identifier for the finding.

        Returns:
            List of findings for detected credentials.
        """
        if not value:
            return []

        findings: list[ClassificationFinding] = []
        found_credential = False

        # JDBC connection strings
        match = _JDBC_PASSWORD_RE.search(value)
        if match:
            credential = match.group(1).strip()
            if _is_viable_credential(credential):
                findings.append(
                    _make_finding(
                        column_id=column_id,
                        entity_type="OPAQUE_SECRET",
                        confidence=0.90,
                        evidence="Structural parser (connection string): JDBC password field",
                        source=self.source,
                        sample_value=value[:120],
                    )
                )
                found_credential = True

        # ODBC connection strings
        if not found_credential:
            match = _ODBC_PASSWORD_RE.search(value)
            if match:
                credential = match.group(1).strip()
                if _is_viable_credential(credential):
                    findings.append(
                        _make_finding(
                            column_id=column_id,
                            entity_type="OPAQUE_SECRET",
                            confidence=0.90,
                            evidence="Structural parser (connection string): ODBC password field",
                            source=self.source,
                            sample_value=value[:120],
                        )
                    )
                    found_credential = True

        # Redis URI: redis://:password@host (password-only, no username)
        if not found_credential:
            match = _REDIS_URI_RE.search(value)
            if match:
                # group 1 = password-only (:pass@), group 3 = user:pass@ style
                credential = match.group(1) or match.group(3)
                if credential:
                    try:
                        credential = unquote(credential)
                    except Exception:
                        pass
                    if _is_viable_credential(credential):
                        findings.append(
                            _make_finding(
                                column_id=column_id,
                                entity_type="OPAQUE_SECRET",
                                confidence=0.90,
                                evidence="Structural parser (connection string): Redis URI password",
                                source=self.source,
                                sample_value=value[:120],
                            )
                        )
                        found_credential = True

        # URI-style with userinfo (user:password@host)
        if not found_credential:
            match = _URI_USERINFO_RE.search(value)
            if match:
                credential = match.group(2)
                # URL-decode the password (may be percent-encoded)
                try:
                    credential = unquote(credential)
                except Exception:
                    pass
                if _is_viable_credential(credential):
                    findings.append(
                        _make_finding(
                            column_id=column_id,
                            entity_type="OPAQUE_SECRET",
                            confidence=0.90,
                            evidence="Structural parser (connection string): URI userinfo password",
                            source=self.source,
                            sample_value=value[:120],
                        )
                    )
                    found_credential = True

        # Generic password=xxx in semicolon-delimited strings
        if not found_credential:
            match = _CONNSTR_KV_RE.search(value)
            if match:
                credential = match.group(1).strip()
                if _is_viable_credential(credential):
                    # Only fire if there's other connection-string structure
                    # (at least one other key=value pair with semicolon)
                    if ";" in value and "=" in value:
                        findings.append(
                            _make_finding(
                                column_id=column_id,
                                entity_type="OPAQUE_SECRET",
                                confidence=0.85,
                                evidence="Structural parser (connection string): generic password field",
                                source=self.source,
                                sample_value=value[:120],
                            )
                        )

        return findings


# ── Registry of all parsers ─────────────────────────────────────────────────

ALL_STRUCTURAL_PARSERS: list[SqlSecretParser | HttpHeaderParser | CliArgumentParser | ConnectionStringParser] = [
    SqlSecretParser(),
    HttpHeaderParser(),
    CliArgumentParser(),
    ConnectionStringParser(),
]


def detect_structural_secrets(value: str, column_id: str = "") -> list[ClassificationFinding]:
    """Run all structural parsers against a value.

    This is the main entry point used by SecretScannerEngine to invoke
    structural detection as an additional layer.

    Args:
        value: The text to scan.
        column_id: Column identifier for findings.

    Returns:
        All findings from all structural parsers combined.
    """
    if not value or len(value) < _MIN_CREDENTIAL_LEN:
        return []

    findings: list[ClassificationFinding] = []
    for parser in ALL_STRUCTURAL_PARSERS:
        try:
            parser_findings = parser.detect(value, column_id=column_id)
            findings.extend(parser_findings)
        except Exception:
            logger.debug("Structural parser %s failed on value", parser.source, exc_info=True)

    return findings
