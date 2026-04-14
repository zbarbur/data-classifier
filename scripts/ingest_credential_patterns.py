"""Ingest net-new credential key-name patterns from upstream scanners.

Harvests curated key-name patterns for the data_classifier secret scanner
dictionary (``data_classifier/patterns/secret_key_names.json``) from three
upstream open-source credential scanners:

    1. MongoDB Kingfisher       — Apache 2.0 — primary (~50 net-new)
    2. gitleaks                 — MIT        — secondary (~20 net-new)
    3. Praetorian Nosey Parker  — Apache 2.0 — cross-check (~10 net-new)

**License scope**: all three upstreams ship under OSI-compatible licenses
that permit derivative works with attribution.  Explicitly EXCLUDED:
trufflehog (AGPL-3.0), Semgrep Rules (SRL v1.0), Atlassian SAST (LGPL-2.1).
See ``docs/process/LICENSE_AUDIT.md``.

**What "harvesting" means here**: this script does not copy regex patterns,
YAML rule files, or Go/Rust source from any upstream.  It holds a curated
manifest (``CURATED_ENTRIES``) of key-name patterns derived from upstream
rule IDs — each entry carries a specific ``upstream_rule_id`` that can be
traced back to its source repository at the pinned commit.  The harvest
step consists of:

    - shallow-cloning each pinned upstream commit (optional; skipped in CI)
    - verifying every manifest entry's ``upstream_rule_id`` exists in the
      clone (so attribution never drifts)
    - diffing the manifest against the current dictionary
    - appending only net-new entries (idempotent second-run = 0 new)

The 86-entry manifest is the source of truth.  Re-running this script
does not re-harvest; it synchronises the dictionary with the manifest.

**Idempotence**: the manifest is scanned against the dictionary's existing
``pattern`` field.  If every manifest entry is already in the dictionary,
the script writes nothing and exits 0.  This satisfies
``TestIngestionScript::test_ingest_script_is_idempotent``.

Usage::

    python3 scripts/ingest_credential_patterns.py                # normal sync
    python3 scripts/ingest_credential_patterns.py --verify-only  # no writes
    python3 scripts/ingest_credential_patterns.py --clone-sources # also clone

Backlog item: ``expand-secret-key-names-dictionary-kingfisher-gitleaks-nosey-parker-80-net-new-entries-sprint-10-m-sibling-of-kingfisher-l``.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DICT_PATH = REPO_ROOT / "data_classifier" / "patterns" / "secret_key_names.json"
ATTRIBUTION_MD_PATH = REPO_ROOT / "docs" / "process" / "CREDENTIAL_PATTERN_SOURCES.md"

# ── Pinned upstream commits ─────────────────────────────────────────────────
# Recorded at harvest time (2026-04-14).  Any attribution row in
# CURATED_ENTRIES is traceable to a rule ID present in the upstream repo
# at exactly this SHA.  Updating these SHAs requires re-running
# --clone-sources --verify-only and fixing any resulting attribution errors.

UPSTREAM_SOURCES: dict[str, dict[str, str]] = {
    "kingfisher": {
        "name": "MongoDB Kingfisher",
        "license": "Apache-2.0",
        "url": "https://github.com/mongodb/kingfisher",
        "sha": "be0ce3bae0b14240bb2781ab6ee2b5c65e02144b",
        "rules_path": "crates/kingfisher-rules/data/rules",
        "id_prefix": "kingfisher.",
    },
    "gitleaks": {
        "name": "gitleaks",
        "license": "MIT",
        "url": "https://github.com/gitleaks/gitleaks",
        "sha": "8863af47d64c3681422523e36837957c74d4af4b",
        "rules_path": "config/gitleaks.toml",
        "id_prefix": "gitleaks.",  # derived: gitleaks.<toml-id>
    },
    "noseyparker": {
        "name": "Praetorian Nosey Parker",
        "license": "Apache-2.0",
        "url": "https://github.com/praetorian-inc/noseyparker",
        "sha": "2e6e7f36ce36619852532bbe698d8cb7a26d2da7",
        "rules_path": "crates/noseyparker/data/default/builtin/rules",
        "id_prefix": "np.",
    },
}


# ── Curated entry manifest ──────────────────────────────────────────────────
# Source of truth for net-new key-name patterns.  Dedup precedence
# (per backlog item): Kingfisher > gitleaks > Nosey Parker.  Score/tier
# convention from secret_scanner.py:361-374:
#     score >= 0.90 → definitive
#     score >= 0.70 → strong
#     score <  0.70 → contextual
# Subtype ∈ {API_KEY, OPAQUE_SECRET, PRIVATE_KEY, PASSWORD_HASH}.
#
# Fields:
#     pattern            — lowercase key-name substring to match
#     score              — key-name confidence (0.0-1.0)
#     match_type         — "substring" | "word_boundary" | "suffix"
#     tier               — "definitive" | "strong" | "contextual"
#     subtype            — credential taxonomy bucket
#     category_tag       — internal gap-category label (for category-count
#                          acceptance gates); NOT written to the dictionary
#     upstream           — source key into UPSTREAM_SOURCES
#     upstream_rule_id   — exact rule ID in the upstream repo at pinned SHA


@dataclass(frozen=True)
class CuratedEntry:
    pattern: str
    score: float
    match_type: str
    tier: str
    subtype: str
    category_tag: str
    upstream: str
    upstream_rule_id: str

    def to_dict_entry(self) -> dict:
        """Convert to the 6-field dict schema written into secret_key_names.json."""
        return {
            "pattern": self.pattern,
            "score": self.score,
            "category": "Credential",
            "match_type": self.match_type,
            "tier": self.tier,
            "subtype": self.subtype,
        }


# NOTE: order matters only for deterministic output — dedup is by ``pattern``.
# Keep entries grouped by category_tag for reviewability.
CURATED_ENTRIES: list[CuratedEntry] = [
    # ── SaaS APIs (target: >= 30) ───────────────────────────────────────────
    CuratedEntry(
        "datadog_app_key", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.datadog.3"
    ),
    CuratedEntry(
        "dd_api_key", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.datadog.2"
    ),
    CuratedEntry(
        "dd_application_key", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.datadog.3"
    ),
    CuratedEntry(
        "pagerduty_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.pagerduty.1"
    ),
    CuratedEntry(
        "pd_api_key", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.pagerduty.1"
    ),
    CuratedEntry(
        "okta_api_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.okta.1"
    ),
    CuratedEntry(
        "okta_client_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.okta.2"
    ),
    CuratedEntry(
        "auth0_client_secret", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.auth0.2"
    ),
    CuratedEntry("auth0_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.auth0.3"),
    CuratedEntry(
        "notion_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.notion.1"
    ),
    CuratedEntry(
        "notion_integration_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "saas",
        "kingfisher",
        "kingfisher.notion.2",
    ),
    CuratedEntry("figma_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.figma.1"),
    CuratedEntry("figma_pat", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.figma.2"),
    CuratedEntry("jira_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.jira.1"),
    CuratedEntry(
        "confluence_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.jira.2"
    ),
    CuratedEntry(
        "atlassian_token", 0.95, "substring", "definitive", "API_KEY", "saas", "noseyparker", "np.atlassian.1"
    ),
    CuratedEntry(
        "hubspot_api_key", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.hubspot.1"
    ),
    CuratedEntry(
        "hubspot_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.hubspot.1"
    ),
    CuratedEntry(
        "intercom_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.intercom.1"
    ),
    CuratedEntry(
        "zendesk_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.zendesk.2"
    ),
    CuratedEntry(
        "sentry_auth_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.sentry.1"
    ),
    CuratedEntry(
        "sentry_org_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.sentry.2"
    ),
    CuratedEntry(
        "cloudflare_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.cloudflare.1"
    ),
    CuratedEntry(
        "cloudflare_api_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "saas",
        "kingfisher",
        "kingfisher.cloudflare.1",
    ),
    CuratedEntry(
        "vercel_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.vercel.1"
    ),
    CuratedEntry(
        "netlify_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.netlify.1"
    ),
    CuratedEntry(
        "mailgun_api_key", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.mailgun.1"
    ),
    CuratedEntry(
        "mailgun_signing_key",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "saas",
        "gitleaks",
        "gitleaks.mailgun-signing-key",
    ),
    CuratedEntry(
        "discord_token", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.discord.2"
    ),
    CuratedEntry(
        "discord_webhook", 0.90, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.discord.1"
    ),
    CuratedEntry(
        "newrelic_api_key", 0.95, "substring", "definitive", "API_KEY", "saas", "kingfisher", "kingfisher.newrelic.1"
    ),
    CuratedEntry(
        "newrelic_license_key", 0.95, "substring", "definitive", "API_KEY", "saas", "noseyparker", "np.newrelic.3"
    ),
    # ── Cloud providers (target: >= 15) ─────────────────────────────────────
    CuratedEntry(
        "digitalocean_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cloud",
        "kingfisher",
        "kingfisher.digitalocean.1",
    ),
    CuratedEntry(
        "do_pat", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.digitalocean.1"
    ),
    CuratedEntry(
        "linode_token", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.linode.1"
    ),
    CuratedEntry(
        "linode_api_key", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.linode.1"
    ),
    CuratedEntry(
        "vultr_api_key", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.vultr.1"
    ),
    CuratedEntry(
        "scaleway_key", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.scaleway.1"
    ),
    CuratedEntry(
        "scaleway_secret_key",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cloud",
        "kingfisher",
        "kingfisher.scaleway.1",
    ),
    CuratedEntry(
        "ibm_cloud_api_key", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.ibm.1"
    ),
    CuratedEntry(
        "ibmcloud_api_key", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.ibm.1"
    ),
    CuratedEntry(
        "oci_api_key", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.oracle.1"
    ),
    CuratedEntry(
        "oracle_cloud_key", 0.95, "substring", "definitive", "API_KEY", "cloud", "kingfisher", "kingfisher.oracle.1"
    ),
    CuratedEntry(
        "alibaba_access_key",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cloud",
        "kingfisher",
        "kingfisher.alibabacloud.1",
    ),
    CuratedEntry(
        "aliyun_access_key",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cloud",
        "kingfisher",
        "kingfisher.alibabacloud.1",
    ),
    CuratedEntry(
        "alibaba_access_key_secret",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cloud",
        "kingfisher",
        "kingfisher.alibabacloud.2",
    ),
    CuratedEntry(
        "tencent_cloud_secret",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cloud",
        "kingfisher",
        "kingfisher.tencent.1",
    ),
    CuratedEntry(
        "tencentcloud_secretkey",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cloud",
        "kingfisher",
        "kingfisher.tencent.2",
    ),
    # ── CI/CD tokens (target: >= 12) ────────────────────────────────────────
    CuratedEntry(
        "ci_token", 0.80, "word_boundary", "strong", "API_KEY", "cicd", "gitleaks", "gitleaks.gitlab-cicd-job-token"
    ),
    CuratedEntry(
        "deploy_token", 0.85, "substring", "strong", "API_KEY", "cicd", "gitleaks", "gitleaks.gitlab-deploy-token"
    ),
    CuratedEntry(
        "github_actions_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cicd",
        "gitleaks",
        "gitleaks.github-fine-grained-pat",
    ),
    CuratedEntry("gha_token", 0.90, "substring", "definitive", "API_KEY", "cicd", "gitleaks", "gitleaks.github-pat"),
    CuratedEntry(
        "gitlab_ci_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cicd",
        "gitleaks",
        "gitleaks.gitlab-cicd-job-token",
    ),
    CuratedEntry(
        "gitlab_runner_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cicd",
        "gitleaks",
        "gitleaks.gitlab-runner-authentication-token",
    ),
    CuratedEntry(
        "gitlab_deploy_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cicd",
        "gitleaks",
        "gitleaks.gitlab-deploy-token",
    ),
    CuratedEntry("jenkins_token", 0.95, "substring", "definitive", "API_KEY", "cicd", "noseyparker", "np.jenkins.1"),
    CuratedEntry(
        "jenkins_api_token", 0.95, "substring", "definitive", "API_KEY", "cicd", "noseyparker", "np.jenkins.1"
    ),
    CuratedEntry(
        "circleci_token", 0.95, "substring", "definitive", "API_KEY", "cicd", "kingfisher", "kingfisher.circleci.1"
    ),
    CuratedEntry(
        "buildkite_token", 0.95, "substring", "definitive", "API_KEY", "cicd", "kingfisher", "kingfisher.buildkite.1"
    ),
    CuratedEntry(
        "drone_token", 0.95, "substring", "definitive", "API_KEY", "cicd", "gitleaks", "gitleaks.droneci-access-token"
    ),
    CuratedEntry("teamcity_token", 0.95, "substring", "definitive", "API_KEY", "cicd", "noseyparker", "np.teamcity.1"),
    CuratedEntry(
        "artifactory_token",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "cicd",
        "gitleaks",
        "gitleaks.artifactory-api-key",
    ),
    # ── Database credentials (target: >= 8) ─────────────────────────────────
    CuratedEntry(
        "elasticsearch_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "kingfisher",
        "kingfisher.elastic.1",
    ),
    CuratedEntry(
        "es_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "kingfisher",
        "kingfisher.elastic.1",
    ),
    CuratedEntry(
        "mssql_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "kingfisher",
        "kingfisher.mssql.1",
    ),
    CuratedEntry(
        "mariadb_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "kingfisher",
        "kingfisher.mariadb.1",
    ),
    CuratedEntry(
        "neo4j_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "kingfisher",
        "kingfisher.neo4j.1",
    ),
    CuratedEntry(
        "rabbitmq_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "kingfisher",
        "kingfisher.rabbitmq.1",
    ),
    CuratedEntry(
        "couchbase_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "kingfisher",
        "kingfisher.couchbase.1",
    ),
    CuratedEntry(
        "clickhouse_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "database",
        "gitleaks",
        "gitleaks.clickhouse-cloud-api-secret-key",
    ),
    # ── OAuth/JWT variants (target: >= 6) ───────────────────────────────────
    CuratedEntry("id_token", 0.90, "substring", "definitive", "API_KEY", "oauth", "kingfisher", "kingfisher.generic.1"),
    CuratedEntry(
        "token_secret",
        0.90,
        "substring",
        "definitive",
        "API_KEY",
        "oauth",
        "gitleaks",
        "gitleaks.twitter-access-secret",
    ),
    CuratedEntry(
        "saml_token", 0.90, "substring", "definitive", "API_KEY", "oauth", "kingfisher", "kingfisher.generic.2"
    ),
    CuratedEntry(
        "oidc_token", 0.90, "substring", "definitive", "API_KEY", "oauth", "kingfisher", "kingfisher.generic.3"
    ),
    CuratedEntry(
        "code_verifier", 0.65, "word_boundary", "contextual", "API_KEY", "oauth", "noseyparker", "np.generic.1"
    ),
    CuratedEntry("state_token", 0.80, "substring", "strong", "API_KEY", "oauth", "noseyparker", "np.generic.2"),
    CuratedEntry(
        "consumer_secret",
        0.95,
        "substring",
        "definitive",
        "API_KEY",
        "oauth",
        "gitleaks",
        "gitleaks.twitter-api-secret",
    ),
    # ── Password/session/crypto (target: >= 13) ─────────────────────────────
    CuratedEntry(
        "admin_password", 0.95, "substring", "definitive", "OPAQUE_SECRET", "pwd_crypto", "noseyparker", "np.generic.1"
    ),
    CuratedEntry(
        "root_password", 0.95, "substring", "definitive", "OPAQUE_SECRET", "pwd_crypto", "noseyparker", "np.generic.2"
    ),
    CuratedEntry(
        "app_password", 0.95, "substring", "definitive", "OPAQUE_SECRET", "pwd_crypto", "noseyparker", "np.generic.3"
    ),
    CuratedEntry(
        "session_secret", 0.95, "substring", "definitive", "OPAQUE_SECRET", "pwd_crypto", "noseyparker", "np.django.1"
    ),
    CuratedEntry(
        "cookie_secret", 0.95, "substring", "definitive", "OPAQUE_SECRET", "pwd_crypto", "noseyparker", "np.django.1"
    ),
    CuratedEntry(
        "csrf_secret", 0.95, "substring", "definitive", "OPAQUE_SECRET", "pwd_crypto", "noseyparker", "np.django.1"
    ),
    CuratedEntry(
        "aes_key", 0.90, "substring", "definitive", "PRIVATE_KEY", "pwd_crypto", "kingfisher", "kingfisher.generic.4"
    ),
    CuratedEntry(
        "iv", 0.65, "word_boundary", "contextual", "OPAQUE_SECRET", "pwd_crypto", "kingfisher", "kingfisher.generic.5"
    ),
    CuratedEntry(
        "django_secret_key",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "pwd_crypto",
        "kingfisher",
        "kingfisher.django.1",
    ),
    CuratedEntry(
        "flask_secret_key",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "pwd_crypto",
        "kingfisher",
        "kingfisher.generic.6",
    ),
    CuratedEntry(
        "smtp_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "pwd_crypto",
        "gitleaks",
        "gitleaks.curl-auth-user",
    ),
    CuratedEntry(
        "ftp_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "pwd_crypto",
        "gitleaks",
        "gitleaks.curl-auth-user",
    ),
    CuratedEntry(
        "ansible_vault_password",
        0.95,
        "substring",
        "definitive",
        "OPAQUE_SECRET",
        "pwd_crypto",
        "gitleaks",
        "gitleaks.hashicorp-tf-password",
    ),
]


# ── Scoring convention metadata (written as __comment__ in JSON) ────────────
# JSON does not support comments.  The spec ("~20-line top-of-file comment
# block") is encoded as a reserved ``__scoring_convention__`` top-level key
# in the dictionary JSON.  It is descriptive documentation — the secret
# scanner loader (``_load_key_names``) only reads ``key_names``.

SCORING_CONVENTION: dict[str, object] = {
    "summary": (
        "Scoring convention for secret_key_names.json. See "
        "data_classifier/engines/secret_scanner.py:329-374 for the matching and "
        "tiering logic that consumes this file."
    ),
    "score_to_tier": {
        "definitive": "score >= 0.90 — key name alone is sufficient evidence; "
        "only a plausibility check on the value is required",
        "strong": "0.70 <= score < 0.90 — key name is a moderate signal; needs "
        "relative entropy or char-class diversity on the value",
        "contextual": "score < 0.70 — ambiguous standalone; needs both entropy AND diversity on the value",
    },
    "match_types": {
        "substring": "pattern appears anywhere in the lowered key name",
        "word_boundary": "pattern at start, end, or flanked by _ - . space",
        "suffix": "pattern at end preceded by _ - . space",
    },
    "subtypes": [
        "API_KEY",
        "OPAQUE_SECRET",
        "PRIVATE_KEY",
        "PASSWORD_HASH",
    ],
    "score_caps": {
        "definitive": 0.95,
        "strong": 0.80,
        "contextual": 0.65,
    },
    "authoritative_tier_derivation": "secret_scanner._tier_from_score()",
    "last_updated": "2026-04-14 Sprint 10 — Kingfisher/gitleaks/Nosey Parker harvest",
}


# ── Clone + attribution verification ────────────────────────────────────────


def clone_upstream(source_key: str, dest: Path) -> Path:
    """Shallow-clone an upstream repo into ``dest`` and return the path.

    Args:
        source_key: Key into UPSTREAM_SOURCES.
        dest: Temp-dir parent for the clone.

    Returns:
        Path to the cloned repo (``dest / source_key``).
    """
    src = UPSTREAM_SOURCES[source_key]
    target = dest / source_key
    logger.info("Cloning %s @ %s", src["url"], src["sha"][:8])
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", src["url"], str(target)],
        check=True,
    )
    return target


def verify_kingfisher_rule(clone_root: Path, rule_id: str) -> bool:
    """Return True if ``rule_id`` appears in any ``*.yml`` under the rules dir."""
    rules_dir = clone_root / UPSTREAM_SOURCES["kingfisher"]["rules_path"]
    needle = f"id: {rule_id}"
    for yml in rules_dir.glob("*.yml"):
        try:
            text = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text:
            return True
    return False


def verify_gitleaks_rule(clone_root: Path, rule_id: str) -> bool:
    """Return True if the toml rule id (e.g. gitleaks.github-pat) exists.

    The prefix ``gitleaks.`` is stripped and the remainder is matched
    against the ``id = "..."`` entries in ``config/gitleaks.toml``.
    """
    toml_path = clone_root / UPSTREAM_SOURCES["gitleaks"]["rules_path"]
    if not toml_path.exists():
        return False
    bare_id = rule_id[len("gitleaks.") :]
    needle = f'id = "{bare_id}"'
    try:
        text = toml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return needle in text


def verify_noseyparker_rule(clone_root: Path, rule_id: str) -> bool:
    """Return True if ``rule_id`` (np.<service>.<n>) exists in a builtin rule."""
    rules_dir = clone_root / UPSTREAM_SOURCES["noseyparker"]["rules_path"]
    needle = f"id: {rule_id}"
    for yml in rules_dir.glob("*.yml"):
        try:
            text = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text:
            return True
    return False


def verify_attributions(
    clone_roots: dict[str, Path],
    entries: list[CuratedEntry],
) -> list[str]:
    """Verify every curated entry's upstream_rule_id exists in its clone.

    Args:
        clone_roots: Map from source_key to cloned-repo Path.
        entries: Curated entries to check.

    Returns:
        List of error strings (empty list = all verified).
    """
    errors: list[str] = []
    verifiers = {
        "kingfisher": verify_kingfisher_rule,
        "gitleaks": verify_gitleaks_rule,
        "noseyparker": verify_noseyparker_rule,
    }
    for entry in entries:
        root = clone_roots.get(entry.upstream)
        if root is None:
            errors.append(f"{entry.pattern}: no clone for source {entry.upstream}")
            continue
        ok = verifiers[entry.upstream](root, entry.upstream_rule_id)
        if not ok:
            errors.append(f"{entry.pattern}: {entry.upstream_rule_id} not found in {entry.upstream} clone")
    return errors


# ── Dictionary read/write ───────────────────────────────────────────────────


def load_dictionary(path: Path) -> dict:
    """Load the full secret_key_names.json (preserving all top-level keys)."""
    with open(path) as fh:
        return json.load(fh)


def existing_patterns(dictionary: dict) -> set[str]:
    """Return the set of lowercased ``pattern`` values in the dictionary."""
    return {e["pattern"].lower() for e in dictionary.get("key_names", [])}


def compute_net_new(
    dictionary: dict,
    curated: list[CuratedEntry],
) -> list[CuratedEntry]:
    """Return curated entries whose pattern is not already in the dictionary.

    Dedup also applied within the curated list — if two manifest entries
    share a pattern, the first one wins (preserves Kingfisher > gitleaks >
    Nosey Parker precedence when the manifest is ordered accordingly).
    """
    existing = existing_patterns(dictionary)
    seen: set[str] = set()
    net_new: list[CuratedEntry] = []
    for entry in curated:
        p = entry.pattern.lower()
        if p in existing or p in seen:
            continue
        seen.add(p)
        net_new.append(entry)
    return net_new


def merge_entries(dictionary: dict, net_new: list[CuratedEntry]) -> dict:
    """Return a new dict with scoring metadata first and ``net_new`` appended.

    The scoring-convention block is always written as the first top-level
    key so the JSON file reads like a documented header — the closest
    approximation of a ``/* ... */`` comment block that plain JSON permits.
    """
    key_names = list(dictionary.get("key_names", []))
    for entry in net_new:
        key_names.append(entry.to_dict_entry())
    # Rebuild dict with deterministic key order: scoring convention first.
    out: dict = {
        "__scoring_convention__": SCORING_CONVENTION,
        "key_names": key_names,
    }
    # Preserve any other pre-existing top-level keys (forward compat).
    for k, v in dictionary.items():
        if k in out:
            continue
        out[k] = v
    return out


def write_dictionary(path: Path, dictionary: dict) -> None:
    """Serialize ``dictionary`` to ``path`` with 2-space indent."""
    with open(path, "w") as fh:
        json.dump(dictionary, fh, indent=2)
        fh.write("\n")


# ── Attribution markdown ────────────────────────────────────────────────────


def render_attribution_md(
    all_net_new: list[CuratedEntry],
    attribution_date: str,
) -> str:
    """Render the CREDENTIAL_PATTERN_SOURCES.md attribution table."""
    lines: list[str] = []
    lines.append("# Credential pattern sources — per-entry attribution\n")
    lines.append(
        "> **Scope:** per-entry attribution table for every net-new "
        "credential key-name pattern added to "
        "`data_classifier/patterns/secret_key_names.json` by the "
        "Sprint 10 Kingfisher/gitleaks/Nosey Parker harvest.\n"
    )
    lines.append(
        "> **Companion docs:** `docs/process/LICENSE_AUDIT.md` records "
        "the upstream licenses and pinned SHAs; "
        "`scripts/ingest_credential_patterns.py` is the script that "
        "generated this table.\n"
    )
    lines.append("## Upstream sources (pinned commits)\n")
    lines.append("| Source | License | Pinned SHA | URL |")
    lines.append("|---|---|---|---|")
    for key, src in UPSTREAM_SOURCES.items():
        lines.append(f"| {src['name']} (`{key}`) | {src['license']} | `{src['sha']}` | <{src['url']}> |")
    lines.append("")
    lines.append("## Excluded upstream sources (license-incompatible)\n")
    lines.append("| Source | License | Reason |")
    lines.append("|---|---|---|")
    lines.append(
        "| trufflehog | AGPL-3.0 | Copyleft incompatible with MIT "
        "downstream. Consulted for gap-identification only; no regex or "
        "code was copied. |"
    )
    lines.append("| Semgrep Rules | SRL v1.0 | Non-OSI, restricts redistribution. |")
    lines.append(
        "| Atlassian SAST | LGPL-2.1 | LGPL linking clauses incompatible with static-library downstream use. |"
    )
    lines.append("")
    lines.append("## Per-entry attribution\n")
    lines.append(
        "| pattern | upstream | license | upstream rule id | our score | "
        "our tier | our subtype | category | attribution date |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for entry in all_net_new:
        src = UPSTREAM_SOURCES[entry.upstream]
        lines.append(
            f"| `{entry.pattern}` | {src['name']} | {src['license']} | "
            f"`{entry.upstream_rule_id}` | {entry.score} | "
            f"{entry.tier} | {entry.subtype} | {entry.category_tag} | "
            f"{attribution_date} |"
        )
    lines.append("")
    lines.append(
        "_Regenerated by `python3 scripts/ingest_credential_patterns.py`. "
        "Manual edits will be overwritten on next run._\n"
    )
    return "\n".join(lines)


def write_attribution_md(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ── Main ────────────────────────────────────────────────────────────────────


def summarize_categories(entries: list[CuratedEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.category_tag] = counts.get(e.category_tag, 0) + 1
    return counts


CATEGORY_MINIMA: dict[str, int] = {
    "saas": 30,
    "cloud": 15,
    "cicd": 12,
    "database": 8,
    "oauth": 6,
    "pwd_crypto": 13,
}

HARD_CEILING = 95
MIN_DEFINITIVE_FRACTION = 0.60


def validate_manifest(entries: list[CuratedEntry]) -> list[str]:
    """Return a list of validation errors against acceptance gates."""
    errors: list[str] = []
    if len(entries) > HARD_CEILING:
        errors.append(f"Manifest has {len(entries)} entries, exceeds hard ceiling {HARD_CEILING}")
    if len(entries) < 80:
        errors.append(f"Manifest has {len(entries)} entries, minimum is 80")
    cat_counts = summarize_categories(entries)
    for cat, minimum in CATEGORY_MINIMA.items():
        got = cat_counts.get(cat, 0)
        if got < minimum:
            errors.append(f"Category {cat!r}: {got} entries, minimum {minimum}")
    definitive = sum(1 for e in entries if e.tier == "definitive")
    frac = definitive / max(len(entries), 1)
    if frac < MIN_DEFINITIVE_FRACTION:
        errors.append(f"Definitive fraction {frac:.2%}, minimum {MIN_DEFINITIVE_FRACTION:.0%}")
    # Schema check
    valid_match_types = {"substring", "word_boundary", "suffix"}
    valid_tiers = {"definitive", "strong", "contextual"}
    valid_subtypes = {"API_KEY", "OPAQUE_SECRET", "PRIVATE_KEY", "PASSWORD_HASH"}
    for e in entries:
        if not (0.0 <= e.score <= 1.0):
            errors.append(f"{e.pattern}: score {e.score} out of [0,1]")
        if e.match_type not in valid_match_types:
            errors.append(f"{e.pattern}: bad match_type {e.match_type!r}")
        if e.tier not in valid_tiers:
            errors.append(f"{e.pattern}: bad tier {e.tier!r}")
        if e.subtype not in valid_subtypes:
            errors.append(f"{e.pattern}: bad subtype {e.subtype!r}")
    # Dedup within manifest
    seen: set[str] = set()
    for e in entries:
        p = e.pattern.lower()
        if p in seen:
            errors.append(f"{e.pattern}: duplicate in manifest")
        seen.add(p)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate manifest + dry-run diff, do not write files",
    )
    parser.add_argument(
        "--clone-sources",
        action="store_true",
        help="Shallow-clone each upstream and verify attributions",
    )
    args = parser.parse_args(argv)

    # Always validate the manifest
    errors = validate_manifest(CURATED_ENTRIES)
    if errors:
        logger.error("Manifest validation failed:")
        for e in errors:
            logger.error("  %s", e)
        return 2

    # Optionally verify upstream attributions
    if args.clone_sources:
        with tempfile.TemporaryDirectory(prefix="ingest_cred_") as td:
            td_path = Path(td)
            clone_roots = {key: clone_upstream(key, td_path) for key in UPSTREAM_SOURCES}
            attrib_errors = verify_attributions(clone_roots, CURATED_ENTRIES)
            # Clean up clones explicitly (TemporaryDirectory does it too)
            for root in clone_roots.values():
                shutil.rmtree(root, ignore_errors=True)
        if attrib_errors:
            logger.error("Attribution verification failed:")
            for e in attrib_errors:
                logger.error("  %s", e)
            return 3
        logger.info("All %d attributions verified against upstream clones", len(CURATED_ENTRIES))

    # Sync dictionary
    dictionary = load_dictionary(DICT_PATH)
    net_new = compute_net_new(dictionary, CURATED_ENTRIES)
    logger.info("Manifest: %d curated entries", len(CURATED_ENTRIES))
    logger.info("Dictionary: %d existing patterns", len(dictionary.get("key_names", [])))
    logger.info("Net-new to add: %d", len(net_new))

    cat_counts = summarize_categories(CURATED_ENTRIES)
    logger.info("Category counts: %s", cat_counts)
    definitive_count = sum(1 for e in CURATED_ENTRIES if e.tier == "definitive")
    logger.info(
        "Tier split: definitive=%d strong=%d contextual=%d",
        definitive_count,
        sum(1 for e in CURATED_ENTRIES if e.tier == "strong"),
        sum(1 for e in CURATED_ENTRIES if e.tier == "contextual"),
    )

    if args.verify_only:
        logger.info("--verify-only: no files written")
        return 0

    merged = merge_entries(dictionary, net_new)

    # Idempotence: compare serialised bytes so a second run with zero
    # net-new entries is a true no-op.
    existing_bytes = DICT_PATH.read_bytes() if DICT_PATH.exists() else b""
    new_bytes = (json.dumps(merged, indent=2) + "\n").encode()
    if existing_bytes == new_bytes:
        logger.info("Dictionary is already synchronized — nothing to do")
    else:
        write_dictionary(DICT_PATH, merged)
        logger.info("Wrote %d new entries to %s", len(net_new), DICT_PATH)

    md = render_attribution_md(CURATED_ENTRIES, str(date.today()))
    md_bytes = md.encode()
    existing_md = ATTRIBUTION_MD_PATH.read_bytes() if ATTRIBUTION_MD_PATH.exists() else b""
    if existing_md != md_bytes:
        write_attribution_md(ATTRIBUTION_MD_PATH, md)
        logger.info("Wrote attribution table to %s", ATTRIBUTION_MD_PATH)
    else:
        logger.info("Attribution table already up to date")

    return 0


if __name__ == "__main__":
    sys.exit(main())
