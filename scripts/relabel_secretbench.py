"""Auto-flag high-confidence mislabels in secretbench_sample.json.

Produces three outputs:

  * ``<out-dir>/confident_relabels.jsonl`` — entries where a conservative
    structural rule confidently disagrees with the upstream ``is_secret``
    label. One rule + one direction per row so we can audit later.

  * ``<out-dir>/review_queue.jsonl`` — ambiguous rows the heuristics
    cannot classify with confidence. Human eyeballs decide.

  * ``<out-dir>/summary.json`` — per-rule counts + label-flip tallies.

Philosophy: prefer precision over recall. We only flip a label when the
structural signal is unambiguous. Everything else goes to review.

Run from the repo root::

    .venv/bin/python scripts/relabel_secretbench.py \
        --input tests/fixtures/corpora/secretbench_sample.json \
        --out-dir docs/experiments/meta_classifier/runs/20260417-secretbench-relabel

Research-only tool. NOT imported by ``data_classifier/`` anywhere.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# --------------------------------------------------------------------- #
# Confident "NOT a secret" patterns — applied to is_secret=True entries.
# --------------------------------------------------------------------- #

PROSE_SENTENCE = re.compile(
    r"\b(?:Have you heard|It has been proven|fe fi fo fum|It is important to|"
    r"Antidisestablishmentarianism|froderick|papageorgio|woopwoopnotarealsite)",
    re.IGNORECASE,
)

# Empty or whitespace-only value between brackets/quotes near a keyword.
EMPTY_CRED_VALUE = re.compile(
    r"""(?ix)
    (?:password|passwd|pswd|pswrd|pwd|secret|token|api[_-]?key)
    \s*[:=]\s*
    (?:["'][\s]*["']|<[^>]+></[^>]+>|\s*[,;]?\s*$)
    """,
)

# Empty XML/HTML credential tag: <Password></Password>
EMPTY_TAG = re.compile(r"<(Password|password|Secret|Token|ApiKey|api_key)>\s*</\1>")

# Value is *only* a variable reference — no literal secret present.
VAR_REF_ONLY = re.compile(
    r"""(?ix)
    ^\s*                                                # start
    (?:[A-Za-z_][A-Za-z0-9_]*\s*[:=]\s*)?               # optional KEY=
    ["']?                                               # optional quote
    (?:\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)           # $VAR or ${VAR}
       |\#\{[^}]+\}                                     # #{VAR}
       |\{\{[^}]+\}\}                                   # {{VAR}}
    )
    ["']?[\s;,]*$                                       # optional quote + trailing
    """,
)

# Path-fragment ending in credential keyword with no trailing value.
PATH_TRAILING_KEY = re.compile(
    r"^[A-Za-z][\w./-]*/(?:password|secret|token|api[_-]?key)"
    r"\s*[:=]\s*(?:[\"']?\s*[\"']?)?\s*$",
    re.IGNORECASE,
)

# Value-part is a single space / empty quotes near a keyword.
SINGLE_SPACE_VALUE = re.compile(
    r"""(?ix)
    (?:password|passwd|pswd|pwd|secret|token|api[_-]?key)
    \s*[:=]\s*
    ["']\s["']
    \s*[,;]?\s*$
    """,
)

# Scanner matched obviously literal "EXAMPLE"/"REPLACE"/"YOUR" placeholders.
EXAMPLE_LITERAL = re.compile(
    r"\b(?:AKIA\w*EXAMPLE\b|EXAMPLE(?:_KEY|_TOKEN|_SECRET)?"
    r"|YOUR[_-](?:KEY|TOKEN|SECRET|PASSWORD|API_?KEY)"
    r"|REPLACE[_-]?(?:ME|WITH))",
    re.IGNORECASE,
)

# Function-call reference — value is a getter call, not the secret.
FUNC_CALL_GETTER = re.compile(
    r"(?:credentials\.|config\.|env\.|process\.env\.)"
    r"get(?:Password|Secret|Token|ApiKey)\s*\(",
)

# Value is literally the key name — e.g. ``password = "password"`` or
# ``access_key: accesskey``. High-confidence not-a-secret.
KEY_EQUALS_SELF = re.compile(
    r"""(?ix)
    (?:password|passwd|pswd|pwd|secret|token|api[_-]?key|access[_-]?key)
    \s*[:=]\s*                                              # sep
    \{?["']?
    (?:password|passwd|pswd|pwd|secret|token|api[_-]?key|access[_-]?key)
    ["']?\}?\s*[;,]?\s*$
    """,
)

# Value is a trivial repeat like ``"password": "a"`` or ``"password": ""``.
TRIVIAL_SHORT_VALUE = re.compile(
    r"""(?ix)
    ["'](?:password|passwd|pswd|secret|token)["']
    \s*:\s*
    ["'](?:|.{1,2})["']                                     # 0-2 chars
    \s*,?\s*$
    """,
)

# Value is a PEM header line only — no key body.
PEM_HEADER_ONLY = re.compile(
    r"""^\s*-{3,}\s*                                         # leading dashes
    beg[iI]n                                                 # BEGIN (any case)
    \s+[A-Z0-9\s]+\s+                                        # key type
    (?:KEY|CERTIFICATE)
    \s*-{3,}\s*$                                             # trailing dashes
    """,
    re.IGNORECASE | re.VERBOSE,
)

# XML fragment — opening or closing credential tag only.
XML_TAG_FRAGMENT = re.compile(
    r"""^\s*
    </?(?:password|pwd|pswd|secret|token|api_?key)>
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Java/C switch-case or method-signature reference — not the secret itself.
CODE_SYNTAX_REF = re.compile(
    r'^\s*case\s+["\'](?:[Pp]assword|[Ss]ecret|[Tt]oken|[Kk]ey)["\']\s*:\s*$',
)


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def shannon(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


@dataclass
class Decision:
    entity_type: str
    value: str
    upstream_is_secret: bool
    # One of: 'confident_neg' (flip True->False), 'confident_pos' (flip False->True), 'review'
    action: str
    rule: str
    notes: str = ""
    features: dict = field(default_factory=dict)


def classify_true_side(value: str) -> tuple[str | None, str]:
    """Return (rule_name, notes) if we can confidently flip is_secret=True to False."""
    v = value

    if PROSE_SENTENCE.search(v):
        return "prose_sentence", "English prose mentioning credentials"

    if EMPTY_TAG.search(v):
        return "empty_xml_tag", "empty <Password></Password>-style tag"

    if SINGLE_SPACE_VALUE.search(v):
        return "single_space_value", "key=\" \" — value is whitespace"

    if EMPTY_CRED_VALUE.search(v):
        return "empty_cred_value", "credential keyword with empty RHS"

    if VAR_REF_ONLY.match(v):
        return "var_ref_only", "value is only a $VAR/${VAR}/#{VAR} reference"

    if PATH_TRAILING_KEY.match(v):
        return "path_trailing_key", "filesystem path ending in keyword, no value"

    if EXAMPLE_LITERAL.search(v):
        return "example_literal", "literal EXAMPLE/YOUR_KEY/REPLACE placeholder"

    if FUNC_CALL_GETTER.search(v):
        return "func_call_getter", "value is a credentials.getX() call, not a secret"

    if KEY_EQUALS_SELF.search(v):
        return "key_equals_self", 'value is literally the key word (e.g. password="password")'

    if TRIVIAL_SHORT_VALUE.search(v):
        return "trivial_short_value", '"password": "" or "password": "a" — value too short to be real'

    if PEM_HEADER_ONLY.match(v):
        return "pem_header_only", "PEM header line with no key body"

    if XML_TAG_FRAGMENT.match(v):
        return "xml_tag_fragment", "opening or closing XML cred tag only"

    if CODE_SYNTAX_REF.match(v):
        return "code_syntax_ref", 'switch/case reference like case "Password":'

    return None, ""


# --------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    with args.input.open() as f:
        data = json.load(f)

    print(f"Loaded {len(data)} rows from {args.input}")

    decisions: list[Decision] = []

    # Pass 1 — is_secret=True entries → hunt for confident "NOT a secret"
    for row in data:
        if row.get("is_secret") is not True:
            continue
        value = str(row["value"])
        rule, notes = classify_true_side(value)
        d = Decision(
            entity_type=row.get("entity_type", ""),
            value=value,
            upstream_is_secret=True,
            action="confident_neg" if rule else "review",
            rule=rule or "unmatched",
            notes=notes,
            features={
                "length": len(value),
                "entropy": round(shannon(value), 3),
            },
        )
        decisions.append(d)

    # Pass 2 skipped — we only flip True → False here. "What isn't a secret"
    # is the in-scope relabel. Adding new positives from the False side would
    # require different evidence than what upstream saw, and our first
    # attempt produced 8/9 spurious hits where ``\bEXAMPLE\b`` missed
    # digit-glued suffixes like ``123456789EXAMPLE``. Out of scope for now.

    # Split outputs. Review queue only contains rows that disagreed with the
    # upstream label AND didn't match a confident rule — i.e., everything is
    # still ambiguous. To keep the queue tractable we additionally skip rows
    # where the upstream label is plausible on its face (short values that
    # look like obvious passwords/tokens stay True; high-entropy long ones
    # that are labeled False are fine). The queue is: rows the upstream
    # labeler didn't flag but my heuristic is uncertain about.

    # Simpler definition: review queue = rows where the upstream label is
    # is_secret=True AND the value is structurally suspicious on any of the
    # softer signals below. User can spot-check these.

    confident = [d for d in decisions if d.action in ("confident_neg", "confident_pos")]
    review = []

    # Softer signals — flag remaining True-side rows for review.
    for d in decisions:
        if d.action != "review":
            continue
        if not d.upstream_is_secret:
            continue  # we're not flipping False-side rows
        v = d.value
        flags = []
        # Softer prose check
        if len(v) > 60 and shannon(v) < 4.3 and v.count(" ") >= 6:
            flags.append("maybe_prose")
        # Very short value with credential keyword but low entropy
        if (
            len(v) < 40
            and shannon(v) < 3.5
            and re.search(r"password|passwd|pwd|secret|token|key", v, re.I)
        ):
            flags.append("maybe_trivial_value")
        # Contains "fe fi" pattern but didn't match the stricter regex
        if "fe fi" in v.lower() or "fee fi" in v.lower():
            flags.append("nursery_rhyme_prose")

        if flags:
            review.append((d, flags))

    # Write outputs
    confident_path = args.out_dir / "confident_relabels.jsonl"
    with confident_path.open("w") as f:
        for d in confident:
            f.write(
                json.dumps(
                    {
                        "entity_type": d.entity_type,
                        "value": d.value,
                        "upstream_is_secret": d.upstream_is_secret,
                        "proposed_is_secret": d.action == "confident_pos",
                        "rule": d.rule,
                        "notes": d.notes,
                        "features": d.features,
                    }
                )
                + "\n"
            )

    review_path = args.out_dir / "review_queue.jsonl"
    with review_path.open("w") as f:
        for d, flags in review:
            f.write(
                json.dumps(
                    {
                        "entity_type": d.entity_type,
                        "value": d.value,
                        "upstream_is_secret": d.upstream_is_secret,
                        "review_flags": flags,
                        "features": d.features,
                    }
                )
                + "\n"
            )

    # Summary
    rule_counts_neg = Counter(d.rule for d in confident if d.action == "confident_neg")
    rule_counts_pos = Counter(d.rule for d in confident if d.action == "confident_pos")
    review_flag_counts: Counter[str] = Counter()
    for _, flags in review:
        review_flag_counts.update(flags)

    summary = {
        "input_rows": len(data),
        "upstream_true": sum(1 for r in data if r.get("is_secret") is True),
        "upstream_false": sum(1 for r in data if r.get("is_secret") is False),
        "confident_flips_true_to_false": sum(
            1 for d in confident if d.action == "confident_neg"
        ),
        "confident_flips_false_to_true": sum(
            1 for d in confident if d.action == "confident_pos"
        ),
        "review_queue_size": len(review),
        "rule_breakdown_true_to_false": dict(rule_counts_neg.most_common()),
        "rule_breakdown_false_to_true": dict(rule_counts_pos.most_common()),
        "review_flag_breakdown": dict(review_flag_counts.most_common()),
    }
    summary_path = args.out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    print()
    print(f"Confident relabels:   {confident_path} ({len(confident)} rows)")
    print(f"  True -> False:      {summary['confident_flips_true_to_false']}")
    for rule, n in rule_counts_neg.most_common():
        print(f"    {n:4d}  {rule}")
    print(f"  False -> True:      {summary['confident_flips_false_to_true']}")
    for rule, n in rule_counts_pos.most_common():
        print(f"    {n:4d}  {rule}")
    print()
    print(f"Review queue:         {review_path} ({len(review)} rows)")
    for flag, n in review_flag_counts.most_common():
        print(f"    {n:4d}  {flag}")
    print()
    print(f"Summary:              {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
