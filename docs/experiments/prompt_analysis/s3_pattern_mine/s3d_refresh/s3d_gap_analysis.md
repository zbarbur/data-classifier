# S3-D Gap Analysis — Upstream Mine Refresh

**Date:** 2026-04-16
**Analyst:** S3-D automated refresh task

## Summary

All three upstream sources (gitleaks, Kingfisher, Nosey Parker) are at exactly the Sprint 10 pinned commit. Zero commits ahead across all sources. No new credential detection rules to evaluate.

## Per-Source Results

### gitleaks (MIT) — `gitleaks/gitleaks`

| Field | Value |
|---|---|
| Sprint 10 SHA | `8863af47d64c3681422523e36837957c74d4af4b` |
| Current HEAD (master) | `8863af47d64c3681422523e36837957c74d4af4b` |
| Commits ahead | **0** |
| New rules | **0** |

At the pinned commit, `config/gitleaks.toml` contains **222 `[[rules]]` blocks**. This is the same count as Sprint 10. No new patterns to propose.

### MongoDB Kingfisher (Apache-2.0) — `mongodb/kingfisher`

| Field | Value |
|---|---|
| Sprint 10 SHA | `be0ce3bae0b14240bb2781ab6ee2b5c65e02144b` |
| Current HEAD (main) | `be0ce3bae0b14240bb2781ab6ee2b5c65e02144b` |
| Commits ahead | **0** |
| New rules | **0** |

No changes. The 90 key-name patterns mined from Kingfisher in Sprint 10 remain the complete harvest.

### Praetorian Nosey Parker (Apache-2.0) — `praetorian-inc/noseyparker`

| Field | Value |
|---|---|
| Sprint 10 SHA | `2e6e7f36ce36619852532bbe698d8cb7a26d2da7` |
| Current HEAD (main) | `2e6e7f36ce36619852532bbe698d8cb7a26d2da7` |
| Commits ahead | **0** |
| New rules | **0** |

No changes. The patterns mined from Nosey Parker in Sprint 10 remain the complete harvest.

## Existing Coverage Context

At time of this refresh:
- `secret_key_names.json`: **178 patterns** (88 pre-Sprint-10, +90 net-new from Sprint 10 Kingfisher/gitleaks/NP harvest)
- S3-A (secretlint): **9 proposed** new patterns
- S3-B (detect-secrets): **5 proposed** new patterns
- S3-C (provider docs/RFCs): **5 proposed** new patterns
- S3-D (this refresh): **0 proposed** new patterns

## Conclusion

S3-D yields no new patterns. The Sprint 10 mines were exhaustive at time of execution and upstream sources have not advanced since. The combined S3 pipeline net-new is entirely from S3-A + S3-B + S3-C = 19 patterns.

**Next trigger for re-running S3-D:** at next sprint boundary, check if any source has advanced beyond its pinned SHA before closing sprint.
