"""Structured content parsers — extract key-value pairs from text.

Parses JSON, YAML, env files, and code string literals to extract
(key, value) pairs for secret detection.  Used by the SecretScannerEngine
to find credentials embedded in structured content.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_key_values(text: str) -> list[tuple[str, str]]:
    """Extract key-value pairs from structured text.

    Tries parsers in order: JSON, YAML, env, code literals.
    Returns the results from the first parser that succeeds, or
    aggregates results if multiple formats are present.

    Args:
        text: Raw text that may contain structured key-value content.

    Returns:
        List of (key, value) tuples extracted from the text.
    """
    if not text or not text.strip():
        return []

    results: list[tuple[str, str]] = []

    # Try JSON first (most structured)
    json_results = _parse_json(text)
    if json_results:
        return json_results

    # Try YAML (superset of JSON, but only if JSON failed)
    yaml_results = _parse_yaml(text)
    if yaml_results:
        return yaml_results

    # Try env format
    env_results = _parse_env(text)
    results.extend(env_results)

    # Try code literals
    code_results = _parse_code_literals(text)
    results.extend(code_results)

    return results


def _parse_json(text: str) -> list[tuple[str, str]]:
    """Parse JSON text and extract key-value pairs with flattened keys.

    Handles nested dicts by joining keys with dots.  Only extracts
    string values (non-string leaf values are converted to str).

    Args:
        text: Text that may be valid JSON.

    Returns:
        List of (dotted_key_path, value) tuples.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(data, dict):
        return []

    return _flatten_dict(data)


def _parse_yaml(text: str) -> list[tuple[str, str]]:
    """Parse YAML text and extract key-value pairs with flattened keys.

    Args:
        text: Text that may be valid YAML.

    Returns:
        List of (dotted_key_path, value) tuples.
    """
    try:
        import yaml

        data = yaml.safe_load(text)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    return _flatten_dict(data)


# Regex for env file lines: KEY=VALUE, export KEY=VALUE, KEY="VALUE", KEY='VALUE'
_ENV_PATTERN = re.compile(
    r"""
    ^                           # start of line
    \s*                         # optional leading whitespace
    (?:export\s+)?              # optional 'export' keyword
    ([A-Za-z_][A-Za-z0-9_]*)   # key: identifier
    \s*=\s*                     # equals sign with optional whitespace
    (?:                         # value alternatives
        "([^"]*)"               # double-quoted value
        |'([^']*)'              # single-quoted value
        |([^\s()\[\]{},]+)      # unquoted value (no spaces, no code-expression chars, no trailing comma)
    )
    \s*$                        # optional trailing whitespace + end of line
    """,
    re.MULTILINE | re.VERBOSE,
)


def _parse_env(text: str) -> list[tuple[str, str]]:
    """Parse env-file format: KEY=VALUE, export KEY=VALUE, quoted values.

    Args:
        text: Text that may contain env-style key=value lines.

    Returns:
        List of (key, value) tuples.
    """
    results: list[tuple[str, str]] = []
    for match in _ENV_PATTERN.finditer(text):
        key = match.group(1)
        # Value is in one of the three capture groups
        value = match.group(2) or match.group(3) or match.group(4) or ""
        if value:
            results.append((key, value))
    return results


# Regex for code literals: identifier = "value" or identifier = 'value'
# Supports various assignment operators and language styles
_CODE_LITERAL_PATTERN = re.compile(
    r"""
    ([A-Za-z_][A-Za-z0-9_]*)   # identifier (key)
    \s*                         # optional whitespace
    (?::=|:|\s*=)               # assignment: =, :=, or : (for YAML-like inline)
    \s*                         # optional whitespace
    (?:                         # value alternatives
        "([^"]{1,500})"         # double-quoted value (limit length for safety)
        |'([^']{1,500})'        # single-quoted value
    )
    """,
    re.VERBOSE,
)


def _parse_code_literals(text: str) -> list[tuple[str, str]]:
    """Parse code-style string literal assignments.

    Matches patterns like:
      - password = "secret123"
      - api_key := 'abc-def'
      - DB_PASS = "mypass"

    Args:
        text: Text that may contain code-style assignments.

    Returns:
        List of (key, value) tuples.
    """
    results: list[tuple[str, str]] = []
    for match in _CODE_LITERAL_PATTERN.finditer(text):
        key = match.group(1)
        value = match.group(2) or match.group(3) or ""
        if value:
            results.append((key, value))
    return results


def _flatten_dict(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Recursively flatten a nested dict into (dotted_key, str_value) pairs.

    Args:
        data: Dictionary to flatten.
        prefix: Key prefix for nested keys (joined with dots).

    Returns:
        List of (key_path, string_value) tuples.
    """
    results: list[tuple[str, str]] = []
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            results.extend(_flatten_dict(value, full_key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    results.extend(_flatten_dict(item, f"{full_key}[{i}]"))
                elif item is not None:
                    results.append((full_key, str(item)))
        elif value is not None:
            results.append((full_key, str(value)))
    return results
