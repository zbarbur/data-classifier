#!/usr/bin/env python3
"""Generate HTML documentation from the pattern library.

Usage:
    python scripts/generate_pattern_docs.py

Outputs: docs/pattern-library.html
"""

import json
from pathlib import Path

PATTERNS_FILE = Path(__file__).parent.parent / "data_classifier" / "patterns" / "default_patterns.json"
OUTPUT_FILE = Path(__file__).parent.parent / "docs" / "pattern-library.html"


def generate_html(patterns_data: dict) -> str:
    meta = patterns_data["_metadata"]
    patterns = patterns_data["patterns"]

    # Group by category
    by_category: dict[str, list] = {}
    for p in patterns:
        by_category.setdefault(p["category"], []).append(p)

    category_order = ["PII", "Financial", "Credential", "Health"]

    rows = []
    for cat in category_order:
        cat_patterns = by_category.get(cat, [])
        if not cat_patterns:
            continue
        rows.append(f'<tr class="category-header"><td colspan="8">{cat}</td></tr>')
        for p in sorted(cat_patterns, key=lambda x: x["entity_type"]):
            # Mask credential examples in HTML to avoid push protection
            if cat == "Credential":
                examples_match = "<em>(encoded — run tests to verify)</em>" if p.get("examples_match") else "&mdash;"
                examples_no = "<em>(encoded)</em>" if p.get("examples_no_match") else "&mdash;"
            else:
                examples_match = ", ".join(f"<code>{e}</code>" for e in p.get("examples_match", []))
                examples_no = ", ".join(f"<code>{e}</code>" for e in p.get("examples_no_match", []))
            validator = p.get("validator", "") or "&mdash;"
            rows.append(
                f"<tr>"
                f'<td class="name">{p["name"]}</td>'
                f"<td>{p['entity_type']}</td>"
                f'<td class="sensitivity {p["sensitivity"].lower()}">{p["sensitivity"]}</td>'
                f'<td class="conf">{p["confidence"]:.2f}</td>'
                f'<td class="regex"><code>{_escape(p["regex"])}</code></td>'
                f"<td>{validator}</td>"
                f"<td>{examples_match}</td>"
                f"<td>{examples_no}</td>"
                f"</tr>"
                f'<tr class="desc"><td colspan="8">{p.get("description", "")}</td></tr>'
            )

    table_rows = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>data_classifier — Pattern Library Reference</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.5rem; }}
  .meta {{ color: #666; margin-bottom: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th {{ background: #f5f5f5; padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; position: sticky; top: 0; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #eee; vertical-align: top; }}
  tr:hover {{ background: #fafafa; }}
  tr.category-header td {{ background: #e8f0fe; font-weight: bold; font-size: 1rem; padding: 12px; border-bottom: 2px solid #4285f4; }}
  tr.desc td {{ color: #666; font-style: italic; font-size: 0.85rem; padding: 2px 12px 10px; border-bottom: 1px solid #ddd; }}
  .name {{ font-weight: 600; white-space: nowrap; }}
  .regex code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 3px; font-size: 0.85rem; word-break: break-all; }}
  .conf {{ text-align: center; }}
  .sensitivity {{ font-weight: bold; text-transform: uppercase; font-size: 0.8rem; }}
  .critical {{ color: #d32f2f; }}
  .high {{ color: #e65100; }}
  .medium {{ color: #f9a825; }}
  .low {{ color: #388e3c; }}
  code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 2px; font-size: 0.85rem; }}
  .stats {{ display: flex; gap: 2rem; margin-bottom: 1rem; }}
  .stat {{ background: #f5f5f5; padding: 0.5rem 1rem; border-radius: 4px; }}
  .stat strong {{ display: block; font-size: 1.5rem; }}
</style>
</head>
<body>
<h1>data_classifier — Pattern Library Reference</h1>
<div class="meta">
  Version {meta["version"]} &middot; Last updated {meta["last_updated"]} &middot; RE2-compatible
</div>
<div class="stats">
  <div class="stat"><strong>{meta["pattern_count"]}</strong> patterns</div>
  <div class="stat"><strong>{len(by_category)}</strong> categories</div>
  <div class="stat"><strong>{len(set(p["entity_type"] for p in patterns))}</strong> entity types</div>
</div>
<table>
<thead>
<tr>
  <th>Pattern Name</th>
  <th>Entity Type</th>
  <th>Sensitivity</th>
  <th>Confidence</th>
  <th>Regex</th>
  <th>Validator</th>
  <th>Matches</th>
  <th>Non-matches</th>
</tr>
</thead>
<tbody>
{table_rows}
</tbody>
</table>
<footer style="margin-top: 2rem; color: #999; font-size: 0.8rem;">
  Generated from <code>data_classifier/patterns/default_patterns.json</code>.
  All patterns use Google RE2 (linear-time, no backtracking).
</footer>
</body>
</html>"""


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    with open(PATTERNS_FILE) as f:
        data = json.load(f)

    html = generate_html(data)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html)
    print(f"Generated {OUTPUT_FILE} ({len(data['patterns'])} patterns)")


if __name__ == "__main__":
    main()
