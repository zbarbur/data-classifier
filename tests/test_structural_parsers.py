"""Tests for structural secret parsers — Layer 3 detection.

Covers SQL, HTTP header, CLI argument, and connection string parsers
with parameterized positive/negative cases and integration tests
through the SecretScannerEngine pipeline.
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.engines.structural_parsers import (
    CliArgumentParser,
    ConnectionStringParser,
    HttpHeaderParser,
    SqlSecretParser,
    detect_structural_secrets,
)

# ── SQL Secret Parser ──────────────────────────────────────────────────────


class TestSqlSecretParser:
    """Tests for SQL-embedded credential detection."""

    parser = SqlSecretParser()

    @pytest.mark.parametrize(
        "sql, description",
        [
            (
                "CREATE USER 'admin' IDENTIFIED BY 'Sup3rS3cr3t!'",
                "MySQL CREATE USER",
            ),
            (
                "ALTER USER admin WITH PASSWORD = 'MyP@ssw0rd123'",
                "ALTER USER WITH PASSWORD",
            ),
            (
                "GRANT ALL ON *.* TO 'root'@'localhost' IDENTIFIED BY 'r00tP@ss!'",
                "GRANT IDENTIFIED BY",
            ),
            (
                "SET PASSWORD = 'N3wP@ssw0rd!!'",
                "SET PASSWORD simple",
            ),
            (
                "SET PASSWORD FOR 'admin'@'%' = 'Ch@ng3M3N0w!'",
                "SET PASSWORD FOR user",
            ),
            (
                "mysql://appuser:xK9#mL2$wQ@dbhost:3306/production",
                "MySQL DSN string",
            ),
            (
                "postgresql://deploy:f8Gn2kLpR4@pg-prod.example.com/main_db",
                "PostgreSQL DSN in SQL context",
            ),
        ],
        ids=lambda x: x if len(x) < 40 else x[:37] + "...",
    )
    def test_positive_detection(self, sql: str, description: str) -> None:
        findings = self.parser.detect(sql)
        assert len(findings) >= 1, f"Expected detection for: {description}"
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"
        assert "structural_parser:sql" in findings[0].engine

    @pytest.mark.parametrize(
        "sql, description",
        [
            (
                "CREATE USER 'admin' IDENTIFIED BY 'pass'",
                "Password too short (4 chars)",
            ),
            (
                "SELECT * FROM users WHERE id = 1",
                "Plain SELECT — no credentials",
            ),
            (
                "CREATE TABLE users (id INT, password VARCHAR(255))",
                "DDL with password column name",
            ),
            (
                "-- CREATE USER admin IDENTIFIED BY '<your-password>'",
                "Comment with placeholder",
            ),
            (
                "ALTER USER admin WITH PASSWORD = 'changeme'",
                "Placeholder value changeme",
            ),
        ],
        ids=lambda x: x if len(x) < 40 else x[:37] + "...",
    )
    def test_negative_no_detection(self, sql: str, description: str) -> None:
        findings = self.parser.detect(sql)
        assert len(findings) == 0, f"Unexpected detection for: {description}"


# ── HTTP Header Parser ──────────────────────────────────────────────────────


class TestHttpHeaderParser:
    """Tests for HTTP header credential detection."""

    parser = HttpHeaderParser()

    @pytest.mark.parametrize(
        "header, expected_type, description",
        [
            (
                "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig",
                "API_KEY",
                "Bearer JWT token",
            ),
            (
                "Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==",
                "OPAQUE_SECRET",
                "Basic auth credentials",
            ),
            (
                "Authorization: Token tk_live_abc123def456ghi789",
                "API_KEY",
                "Token auth",
            ),
            (
                "X-API-Key: sk-proj-abc123def456ghi789jkl012",
                "API_KEY",
                "X-API-Key header",
            ),
            (
                "Cookie: session_id=a1b2c3d4e5f6g7h8i9j0; path=/",
                "OPAQUE_SECRET",
                "Cookie session token",
            ),
            (
                "Api-Key: live_key_9f8e7d6c5b4a3210",
                "API_KEY",
                "Custom Api-Key header",
            ),
            (
                "X-Auth-Token: xat_prod_mN4kL2jH9pQ8rS7w",
                "API_KEY",
                "Custom X-Auth-Token header",
            ),
        ],
        ids=lambda x: x if isinstance(x, str) and len(x) < 40 else str(x)[:37] + "...",
    )
    def test_positive_detection(self, header: str, expected_type: str, description: str) -> None:
        findings = self.parser.detect(header)
        assert len(findings) >= 1, f"Expected detection for: {description}"
        assert findings[0].entity_type == expected_type
        assert "structural_parser:http_header" in findings[0].engine

    @pytest.mark.parametrize(
        "header, description",
        [
            (
                "Content-Type: application/json",
                "Non-auth header",
            ),
            (
                "Accept: text/html",
                "Accept header",
            ),
            (
                "Authorization: Bearer <token>",
                "Placeholder token",
            ),
            (
                "Host: api.example.com",
                "Host header — no credential",
            ),
            (
                "no-colon-here-just-text",
                "Not a header at all",
            ),
        ],
        ids=lambda x: x if len(x) < 40 else x[:37] + "...",
    )
    def test_negative_no_detection(self, header: str, description: str) -> None:
        findings = self.parser.detect(header)
        assert len(findings) == 0, f"Unexpected detection for: {description}"


# ── CLI Argument Parser ─────────────────────────────────────────────────────


class TestCliArgumentParser:
    """Tests for CLI argument credential detection."""

    parser = CliArgumentParser()

    @pytest.mark.parametrize(
        "cli_text, description",
        [
            (
                "mysql -u admin --password=Sup3rS3cr3t!",
                "--password=value",
            ),
            (
                "curl -H 'Auth' --token tk_live_abc123def456",
                "--token value (space)",
            ),
            (
                "deploy --api-key=sk_prod_9f8e7d6c5b4a",
                "--api-key=value",
            ),
            (
                "ssh-agent --secret-key=priv_a1b2c3d4e5f6",
                "--secret-key=value",
            ),
            (
                "psql -h localhost -p Sup3rS3cr3t! -U admin",
                "-p password (short flag)",
            ),
            (
                "aws configure --access-token xK9mL2wQf8Gn",
                "--access-token value",
            ),
        ],
        ids=lambda x: x if len(x) < 40 else x[:37] + "...",
    )
    def test_positive_detection(self, cli_text: str, description: str) -> None:
        findings = self.parser.detect(cli_text)
        assert len(findings) >= 1, f"Expected detection for: {description}"
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert "structural_parser:cli_argument" in findings[0].engine

    @pytest.mark.parametrize(
        "cli_text, description",
        [
            (
                "ls -la /home/user",
                "Normal ls command",
            ),
            (
                "git commit -m 'fix password validation'",
                "Commit message mentioning password",
            ),
            (
                "--password=pass",
                "Password too short",
            ),
            (
                "tool --password=changeme",
                "Placeholder password",
            ),
        ],
        ids=lambda x: x if len(x) < 40 else x[:37] + "...",
    )
    def test_negative_no_detection(self, cli_text: str, description: str) -> None:
        findings = self.parser.detect(cli_text)
        assert len(findings) == 0, f"Unexpected detection for: {description}"


# ── Connection String Parser ────────────────────────────────────────────────


class TestConnectionStringParser:
    """Tests for connection string credential detection."""

    parser = ConnectionStringParser()

    @pytest.mark.parametrize(
        "connstr, description",
        [
            (
                "jdbc:mysql://dbhost:3306/mydb?user=admin&password=xK9mL2wQf8Gn",
                "JDBC MySQL with password param",
            ),
            (
                "Driver={SQL Server};Server=prod;Database=main;Uid=sa;Pwd=Str0ngP@ss!",
                "ODBC SQL Server",
            ),
            (
                "postgresql://deploy:f8Gn2kLpR4@pg-prod.example.com:5432/main_db",
                "PostgreSQL URI",
            ),
            (
                "mongodb://appuser:m0ng0S3cr3t@mongo-cluster.example.com:27017/appdb",
                "MongoDB URI",
            ),
            (
                "mongodb+srv://admin:Cl0udP@ss!@cluster0.mongodb.net/prod",
                "MongoDB+SRV URI",
            ),
            (
                "redis://:r3d1sP@ssw0rd@cache.example.com:6379/0",
                "Redis URI with password-only auth",
            ),
            (
                "Server=myserver;Database=mydb;password=xK9mL2wQ;Trusted_Connection=no",
                "Generic semicolon-delimited with password",
            ),
        ],
        ids=lambda x: x if len(x) < 40 else x[:37] + "...",
    )
    def test_positive_detection(self, connstr: str, description: str) -> None:
        findings = self.parser.detect(connstr)
        assert len(findings) >= 1, f"Expected detection for: {description}"
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert "structural_parser:connection_string" in findings[0].engine

    @pytest.mark.parametrize(
        "connstr, description",
        [
            (
                "jdbc:mysql://dbhost:3306/mydb?user=admin",
                "JDBC without password",
            ),
            (
                "postgresql://readonly@pg-prod.example.com:5432/analytics",
                "PostgreSQL URI without password",
            ),
            (
                "Server=myserver;Database=mydb;Trusted_Connection=yes",
                "ODBC without password field",
            ),
            (
                "https://api.example.com/v1/data",
                "Plain URL — not a connection string",
            ),
        ],
        ids=lambda x: x if len(x) < 40 else x[:37] + "...",
    )
    def test_negative_no_detection(self, connstr: str, description: str) -> None:
        findings = self.parser.detect(connstr)
        assert len(findings) == 0, f"Unexpected detection for: {description}"


# ── Combined detect_structural_secrets ──────────────────────────────────────


class TestDetectStructuralSecrets:
    """Tests for the combined structural detection entry point."""

    def test_sql_through_combined(self) -> None:
        findings = detect_structural_secrets(
            "CREATE USER 'admin' IDENTIFIED BY 'Sup3rS3cr3t!'",
        )
        assert len(findings) >= 1
        assert any("sql" in f.engine for f in findings)

    def test_http_through_combined(self) -> None:
        findings = detect_structural_secrets(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
        )
        assert len(findings) >= 1
        assert any("http_header" in f.engine for f in findings)

    def test_cli_through_combined(self) -> None:
        findings = detect_structural_secrets(
            "deploy --api-key=sk_prod_9f8e7d6c5b4a",
        )
        assert len(findings) >= 1
        assert any("cli_argument" in f.engine for f in findings)

    def test_connstr_through_combined(self) -> None:
        findings = detect_structural_secrets(
            "postgresql://deploy:f8Gn2kLpR4@pg-prod.example.com/main_db",
        )
        assert len(findings) >= 1
        assert any("connection_string" in f.engine for f in findings)

    def test_empty_value(self) -> None:
        assert detect_structural_secrets("") == []

    def test_short_value(self) -> None:
        assert detect_structural_secrets("hi") == []

    def test_no_structure(self) -> None:
        assert detect_structural_secrets("just some plain text without any credentials") == []


# ── Integration tests: structural parsers through SecretScannerEngine ──────


class TestStructuralParsersIntegration:
    """Integration tests: structural parsers fire through the scanner pipeline."""

    @pytest.fixture
    def engine(self) -> SecretScannerEngine:
        engine = SecretScannerEngine()
        engine.startup()
        return engine

    def test_sql_credential_through_scanner(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="audit_log",
            column_id="test_sql",
            sample_values=[
                "CREATE USER 'deploy' IDENTIFIED BY 'xK9#mL2$wQf8Gn2kLpR4'",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.5)
        assert len(findings) >= 1
        # Should detect the embedded credential
        found_structural = any(
            "structural_parser" in f.engine or f.entity_type in ("OPAQUE_SECRET", "API_KEY") for f in findings
        )
        assert found_structural, f"Expected structural detection, got: {findings}"

    def test_http_header_through_scanner(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="request_headers",
            column_id="test_http",
            sample_values=[
                "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jV",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.5)
        assert len(findings) >= 1

    def test_connection_string_through_scanner(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="config_value",
            column_id="test_connstr",
            sample_values=[
                "postgresql://appuser:f8Gn2kLpR4vX@db-prod.internal:5432/main",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.5)
        assert len(findings) >= 1

    def test_cli_argument_through_scanner(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="command_log",
            column_id="test_cli",
            sample_values=[
                "deploy-tool --api-key=sk_prod_9f8e7d6c5b4a3210 --region us-east-1",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.5)
        assert len(findings) >= 1

    def test_no_false_positive_on_plain_text(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="description",
            column_id="test_plain",
            sample_values=[
                "This is a normal description without any secrets",
                "Another plain text value with no credentials at all",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.5)
        assert len(findings) == 0

    def test_multiple_structural_types_in_column(self, engine: SecretScannerEngine) -> None:
        """Column with mixed structural credential types."""
        column = ColumnInput(
            column_name="mixed_config",
            column_id="test_mixed",
            sample_values=[
                "postgresql://admin:Str0ngP@ss123@db.prod:5432/app",
                "Authorization: Bearer tk_live_abc123def456ghi789jkl",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.5)
        assert len(findings) >= 1
