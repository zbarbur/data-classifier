"""Consolidated sprint report — runs all accuracy benchmarks side-by-side.

Generates a single HTML report containing:
- Nemotron × named vs blind
- Ai4Privacy × named vs blind
- Executive summary comparing all 4 configurations
- Per-entity matrix showing precision/recall/F1 per corpus/mode
- Failure analysis (FPs, FNs grouped by root cause)
- Blind vs Named delta (showing ML impact)

Usage:
    python -m tests.benchmarks.consolidated_report --sprint 5
    python -m tests.benchmarks.consolidated_report --sprint 5 --samples 100

No performance benchmark — run perf separately when needed.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tests.benchmarks.accuracy_benchmark import run_benchmark
from tests.benchmarks.corpus_loader import load_corpus


@dataclass
class RunResult:
    """Single benchmark run result."""

    corpus: str
    blind: bool
    samples_per_col: int
    num_columns: int
    macro_f1: float
    micro_f1: float
    primary_label_accuracy: float
    precision: float
    recall: float
    total_tp: int
    total_fp: int
    total_fn: int
    per_entity: dict  # entity_type → EntityMetrics
    false_positives: list[tuple[str, str, str]]  # (column_id, predicted, expected)
    false_negatives: list[tuple[str, str, list[str]]]  # (column_id, expected, got)


def _run_single(corpus_name: str, blind: bool, samples_per_col: int) -> RunResult:
    """Run one accuracy benchmark configuration."""
    label = f"{corpus_name}{' (BLIND)' if blind else ' (named)'}"
    print(f"Running {label}, {samples_per_col} samples/col...", file=sys.stderr)

    corpus = load_corpus(corpus_name, max_rows=samples_per_col, blind=blind)
    results, metrics = run_benchmark(corpus, corpus_source=corpus_name)

    # Aggregate
    tp = sum(m.tp for m in metrics.values())
    fp = sum(m.fp for m in metrics.values())
    fn = sum(m.fn for m in metrics.values())
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    micro_f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    macro_f1_values = [m.f1 for m in metrics.values() if m.tp + m.fn > 0]
    macro_f1 = sum(macro_f1_values) / len(macro_f1_values) if macro_f1_values else 0.0

    # Primary-label accuracy
    from tests.benchmarks.accuracy_benchmark import BenchmarkResult

    last = getattr(run_benchmark, "_last_result", None)
    primary_acc = last.primary_label_accuracy if isinstance(last, BenchmarkResult) else 0.0

    # Collect failures
    fps: list[tuple[str, str, str]] = []
    fns: list[tuple[str, str, list[str]]] = []
    for r in results:
        if r.expected_entity_type is None:
            continue
        predicted_set = set(r.predicted_entity_types)
        expected = r.expected_entity_type
        if expected not in predicted_set:
            fns.append((r.column_id, expected, r.predicted_entity_types))
        for pred in predicted_set:
            if pred != expected:
                fps.append((r.column_id, pred, expected))

    return RunResult(
        corpus=corpus_name,
        blind=blind,
        samples_per_col=samples_per_col,
        num_columns=len(corpus),
        macro_f1=macro_f1,
        micro_f1=micro_f1,
        primary_label_accuracy=primary_acc,
        precision=precision,
        recall=recall,
        total_tp=tp,
        total_fp=fp,
        total_fn=fn,
        per_entity=dict(metrics),
        false_positives=fps,
        false_negatives=fns,
    )


def run_all(sprint: int, samples_per_col: int = 50) -> list[RunResult]:
    """Run all 4 configurations (2 corpora × 2 modes)."""
    configs = [
        ("nemotron", False),
        ("nemotron", True),
        ("ai4privacy", False),
        ("ai4privacy", True),
    ]
    return [_run_single(corpus, blind, samples_per_col) for corpus, blind in configs]


def _color(val: float, good: float = 0.9, warn: float = 0.7) -> str:
    if val >= good:
        return "#22c55e"
    if val >= warn:
        return "#f59e0b"
    return "#ef4444"


def _tag(val: float, good: float = 0.9, warn: float = 0.7) -> str:
    if val >= good:
        return '<span class="tag tag-good">GOOD</span>'
    if val >= warn:
        return '<span class="tag tag-warn">WARN</span>'
    return '<span class="tag tag-bad">LOW</span>'


def _summary_card(r: RunResult) -> str:
    """Build an executive summary card for one run."""
    corpus_label = r.corpus.title()
    mode = "BLIND" if r.blind else "NAMED"
    mode_class = "blind" if r.blind else "named"
    return f"""
<div class="run-card run-card-{mode_class}">
  <div class="run-header">
    <span class="run-title">{corpus_label}</span>
    <span class="run-mode run-mode-{mode_class}">{mode}</span>
  </div>
  <div class="run-primary">
    <div class="metric-big">
      <div class="metric-label">Macro F1</div>
      <div class="metric-value" style="color:{_color(r.macro_f1)}">{r.macro_f1:.3f}</div>
    </div>
    <div class="metric-big">
      <div class="metric-label">Primary-Label</div>
      <div class="metric-value" style="color:{_color(r.primary_label_accuracy)}">{r.primary_label_accuracy:.1%}</div>
    </div>
  </div>
  <div class="run-secondary">
    <div class="metric-small">
      <span class="metric-label">Precision</span>
      <span class="metric-value-sm" style="color:{_color(r.precision)}">{r.precision:.3f}</span>
    </div>
    <div class="metric-small">
      <span class="metric-label">Recall</span>
      <span class="metric-value-sm" style="color:{_color(r.recall)}">{r.recall:.3f}</span>
    </div>
    <div class="metric-small">
      <span class="metric-label">Micro F1</span>
      <span class="metric-value-sm" style="color:{_color(r.micro_f1)}">{r.micro_f1:.3f}</span>
    </div>
  </div>
  <div class="run-footer">
    TP={r.total_tp} &middot; FP={r.total_fp} &middot; FN={r.total_fn}
    &middot; {r.num_columns} cols &middot; {r.samples_per_col} samples
  </div>
</div>
"""


def _per_entity_matrix(runs: list[RunResult]) -> str:
    """Build per-entity comparison matrix across all runs."""
    # Collect all entity types from all runs
    all_entities: set[str] = set()
    for r in runs:
        all_entities.update(r.per_entity.keys())

    rows = ""
    for entity in sorted(all_entities):
        row = f"<tr><td><strong>{entity}</strong></td>"
        for r in runs:
            m = r.per_entity.get(entity)
            if m is None or (m.tp + m.fn == 0 and m.fp == 0):
                row += "<td class='num missing'>&mdash;</td>"
            else:
                f1 = m.f1
                color = _color(f1)
                row += (
                    f"<td class='num' style='color:{color};font-weight:600'>"
                    f"{f1:.2f}"
                    f"<span class='sub'>P={m.precision:.2f} R={m.recall:.2f}</span>"
                    f"</td>"
                )
        row += "</tr>\n"
        rows += row
    return rows


def _delta_analysis(runs: list[RunResult]) -> str:
    """Compare blind vs named per corpus."""
    by_corpus: dict[str, dict[str, RunResult]] = {}
    for r in runs:
        by_corpus.setdefault(r.corpus, {})["blind" if r.blind else "named"] = r

    rows = ""
    for corpus in sorted(by_corpus.keys()):
        named = by_corpus[corpus].get("named")
        blind = by_corpus[corpus].get("blind")
        if not named or not blind:
            continue

        delta_macro = named.macro_f1 - blind.macro_f1
        delta_primary = named.primary_label_accuracy - blind.primary_label_accuracy
        ml_impact_macro = 1.0 - blind.macro_f1  # How much headroom the ML engine has

        rows += f"""
<tr>
  <td><strong>{corpus.title()}</strong></td>
  <td class='num'>{named.macro_f1:.3f}</td>
  <td class='num'>{blind.macro_f1:.3f}</td>
  <td class='num delta'>-{delta_macro:.3f}</td>
  <td class='num'>{named.primary_label_accuracy:.1%}</td>
  <td class='num'>{blind.primary_label_accuracy:.1%}</td>
  <td class='num delta'>-{delta_primary:.1%}</td>
  <td class='num'>{ml_impact_macro:.3f}</td>
</tr>
"""
    return rows


def _failure_section(runs: list[RunResult]) -> str:
    """List all FPs and FNs grouped by run."""
    sections = ""
    for r in runs:
        mode = "blind" if r.blind else "named"
        if not r.false_positives and not r.false_negatives:
            continue
        sections += f"<details><summary>{r.corpus.title()} ({mode}) &mdash; "
        sections += f"{len(r.false_positives)} FPs, {len(r.false_negatives)} FNs</summary>\n"
        if r.false_positives:
            sections += "<p><strong>False Positives:</strong></p><ul>"
            for col_id, pred, exp in r.false_positives:
                sections += (
                    f"<li><code>{col_id}</code>: predicted <strong>{pred}</strong>, "
                    f"expected <strong>{exp}</strong></li>"
                )
            sections += "</ul>"
        if r.false_negatives:
            sections += "<p><strong>False Negatives:</strong></p><ul>"
            for col_id, exp, got in r.false_negatives:
                got_str = ", ".join(got) if got else "<em>nothing</em>"
                sections += f"<li><code>{col_id}</code>: expected <strong>{exp}</strong>, got {got_str}</li>"
            sections += "</ul>"
        sections += "</details>\n"
    return sections


def generate_consolidated_html(sprint: int, runs: list[RunResult]) -> str:
    """Generate consolidated HTML report from all benchmark runs."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build table header for per-entity matrix
    run_headers = "".join(
        f"<th>{r.corpus.title()}<br><span class='mode-tag mode-{'blind' if r.blind else 'named'}'>"
        f"{'BLIND' if r.blind else 'NAMED'}</span></th>"
        for r in runs
    )

    summary_cards = "".join(_summary_card(r) for r in runs)
    entity_rows = _per_entity_matrix(runs)
    delta_rows = _delta_analysis(runs)
    failure_sections = _failure_section(runs)

    # Aggregate cross-corpus numbers (blind only — named is always 1.0)
    blind_runs = [r for r in runs if r.blind]
    if blind_runs:
        total_tp = sum(r.total_tp for r in blind_runs)
        total_fp = sum(r.total_fp for r in blind_runs)
        total_fn = sum(r.total_fn for r in blind_runs)
        agg_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        agg_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        agg_f1 = 2 * agg_p * agg_r / (agg_p + agg_r) if (agg_p + agg_r) > 0 else 0.0
        agg_macro = sum(r.macro_f1 for r in blind_runs) / len(blind_runs)
    else:
        total_tp = total_fp = total_fn = 0
        agg_p = agg_r = agg_f1 = agg_macro = 0.0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sprint {sprint} Consolidated Benchmark Report</title>
<style>
  :root {{
    --bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--border-light:#f1f5f9;
    --text:#1e293b;--text-muted:#64748b;--text-faint:#94a3b8;
    --green:#22c55e;--green-bg:#dcfce7;--green-text:#166534;
    --amber:#f59e0b;--amber-bg:#fef3c7;--amber-text:#92400e;
    --red:#ef4444;--red-bg:#fee2e2;--red-text:#991b1b;
    --blue:#3b82f6;--blue-light:#dbeafe;
    --purple:#a855f7;--purple-light:#f3e8ff;
  }}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:var(--bg);color:var(--text);max-width:1400px;margin:0 auto;padding:2rem}}
  .header{{margin-bottom:2.5rem}}
  .header h1{{font-size:2rem;font-weight:800;letter-spacing:-0.02em}}
  .header .subtitle{{color:var(--text-muted);font-size:1rem;margin-top:0.3rem}}
  .header .meta{{display:flex;gap:1.5rem;margin-top:0.8rem;flex-wrap:wrap;font-size:0.85rem;color:var(--text-faint)}}
  .section{{margin-top:2.5rem}}
  .section-header{{display:flex;align-items:baseline;gap:0.8rem;margin-bottom:1.2rem;
                   border-bottom:2px solid var(--border);padding-bottom:0.6rem}}
  .section-header h2{{font-size:1.35rem;font-weight:700}}
  .section-badge{{font-size:0.75rem;background:var(--blue-light);color:var(--blue);
                  padding:0.2rem 0.6rem;border-radius:10px;font-weight:600}}

  /* Run cards grid */
  .runs-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin:1rem 0}}
  .run-card{{background:var(--surface);border-radius:10px;padding:1.2rem;
             border:1px solid var(--border-light);box-shadow:0 1px 3px rgba(0,0,0,.05)}}
  .run-card-blind{{border-top:4px solid var(--purple)}}
  .run-card-named{{border-top:4px solid var(--blue)}}
  .run-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:0.8rem}}
  .run-title{{font-weight:700;font-size:1rem}}
  .run-mode{{font-size:0.65rem;font-weight:700;padding:0.15rem 0.5rem;border-radius:4px;letter-spacing:0.05em}}
  .run-mode-blind{{background:var(--purple-light);color:var(--purple)}}
  .run-mode-named{{background:var(--blue-light);color:var(--blue)}}
  .run-primary{{display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-bottom:0.8rem}}
  .metric-big{{}}
  .metric-big .metric-label{{font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;
                             letter-spacing:0.05em;font-weight:600}}
  .metric-big .metric-value{{font-size:1.6rem;font-weight:800;line-height:1.1;margin-top:0.2rem}}
  .run-secondary{{display:flex;gap:0.8rem;padding:0.6rem 0;border-top:1px solid var(--border-light);
                  border-bottom:1px solid var(--border-light)}}
  .metric-small{{display:flex;flex-direction:column;gap:0.1rem;flex:1}}
  .metric-small .metric-label{{font-size:0.65rem;color:var(--text-muted);font-weight:600}}
  .metric-small .metric-value-sm{{font-size:0.9rem;font-weight:700}}
  .run-footer{{margin-top:0.6rem;font-size:0.75rem;color:var(--text-faint)}}

  /* Tables */
  table{{width:100%;border-collapse:collapse;background:var(--surface);border-radius:10px;
         overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid var(--border-light);
         font-size:0.85rem}}
  th{{background:var(--border-light);text-align:left;padding:0.7rem 1rem;font-size:0.7rem;
      color:var(--text-muted);text-transform:uppercase;letter-spacing:0.04em;font-weight:700}}
  td{{padding:0.6rem 1rem;border-top:1px solid var(--border-light)}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  td.num.missing{{color:var(--text-faint)}}
  td.num.delta{{color:var(--amber)}}
  td .sub{{display:block;font-size:0.65rem;color:var(--text-faint);font-weight:400;margin-top:0.1rem}}
  tr:hover td{{background:#f8fafc}}
  .mode-tag{{font-size:0.6rem;font-weight:700;padding:0.1rem 0.35rem;border-radius:3px;
            letter-spacing:0.05em;display:inline-block;margin-top:0.2rem}}
  .mode-blind{{background:var(--purple-light);color:var(--purple)}}
  .mode-named{{background:var(--blue-light);color:var(--blue)}}

  /* Aggregate card */
  .aggregate{{background:linear-gradient(135deg,var(--blue-light),var(--purple-light));
              border-radius:12px;padding:1.5rem;margin:1.5rem 0;
              border:1px solid var(--border)}}
  .aggregate h3{{font-size:1rem;font-weight:700;margin-bottom:0.8rem}}
  .aggregate-metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}}
  .aggregate-metric .label{{font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;
                            letter-spacing:0.05em;font-weight:600}}
  .aggregate-metric .value{{font-size:1.8rem;font-weight:800;margin-top:0.2rem}}

  /* Tags */
  .tag{{display:inline-block;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.7rem;
        font-weight:700;letter-spacing:0.03em}}
  .tag-good{{background:var(--green-bg);color:var(--green-text)}}
  .tag-warn{{background:var(--amber-bg);color:var(--amber-text)}}
  .tag-bad{{background:var(--red-bg);color:var(--red-text)}}

  /* Details */
  details{{background:var(--surface);border:1px solid var(--border-light);
          border-radius:8px;padding:0.8rem 1rem;margin:0.5rem 0}}
  summary{{cursor:pointer;font-weight:600;font-size:0.9rem;color:var(--blue)}}
  details[open] summary{{margin-bottom:0.5rem}}
  details ul{{margin-left:1.5rem;font-size:0.85rem}}
  details code{{background:var(--border-light);padding:0.1rem 0.3rem;border-radius:3px;
               font-size:0.8rem}}

  footer{{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--border);
         color:var(--text-faint);font-size:0.8rem}}

  @media(max-width:1200px){{
    .runs-grid{{grid-template-columns:repeat(2,1fr)}}
    .aggregate-metrics{{grid-template-columns:repeat(2,1fr)}}
  }}
  @media(max-width:768px){{
    .runs-grid{{grid-template-columns:1fr}}
    body{{padding:1rem}}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Sprint {sprint} &mdash; Consolidated Benchmark Report</h1>
  <div class="subtitle">data_classifier &mdash; Accuracy across all corpora and modes</div>
  <div class="meta">
    <span>Generated: <strong>{now}</strong></span>
    <span>Configurations: <strong>{len(runs)}</strong></span>
    <span>Mode: <strong>blind + named</strong></span>
  </div>
</div>

<div class="section">
  <div class="section-header">
    <h2>Executive Summary</h2>
    <span class="section-badge">{len(runs)} runs</span>
  </div>

  <div class="aggregate">
    <h3>Blind Mode Aggregate (value-only detection, no column name hints)</h3>
    <div class="aggregate-metrics">
      <div class="aggregate-metric">
        <div class="label">Macro F1 (avg) {_tag(agg_macro)}</div>
        <div class="value" style="color:{_color(agg_macro)}">{agg_macro:.3f}</div>
      </div>
      <div class="aggregate-metric">
        <div class="label">Micro F1</div>
        <div class="value" style="color:{_color(agg_f1)}">{agg_f1:.3f}</div>
      </div>
      <div class="aggregate-metric">
        <div class="label">Precision</div>
        <div class="value" style="color:{_color(agg_p)}">{agg_p:.3f}</div>
      </div>
      <div class="aggregate-metric">
        <div class="label">Recall</div>
        <div class="value" style="color:{_color(agg_r)}">{agg_r:.3f}</div>
      </div>
    </div>
    <div style="margin-top:0.8rem;font-size:0.8rem;color:var(--text-muted)">
      TP={total_tp} &middot; FP={total_fp} &middot; FN={total_fn} across blind runs
    </div>
  </div>

  <div class="runs-grid">
    {summary_cards}
  </div>
</div>

<div class="section">
  <div class="section-header">
    <h2>Blind vs Named Delta</h2>
    <span class="section-badge">ML headroom</span>
  </div>
  <table>
  <thead><tr>
    <th>Corpus</th>
    <th style="text-align:right">Named Macro F1</th>
    <th style="text-align:right">Blind Macro F1</th>
    <th style="text-align:right">Delta</th>
    <th style="text-align:right">Named Primary</th>
    <th style="text-align:right">Blind Primary</th>
    <th style="text-align:right">Delta</th>
    <th style="text-align:right">ML Headroom</th>
  </tr></thead>
  <tbody>
{delta_rows}
  </tbody>
  </table>
  <p style="margin-top:0.6rem;font-size:0.8rem;color:var(--text-muted)">
    <strong>ML Headroom</strong> = 1.0 &minus; Blind Macro F1. The potential gain from
    improving value-only detection (the hardest case, where column names provide no signal).
  </p>
</div>

<div class="section">
  <div class="section-header">
    <h2>Per-Entity Matrix</h2>
    <span class="section-badge">F1 &middot; P &middot; R</span>
  </div>
  <table>
  <thead><tr>
    <th>Entity Type</th>
    {run_headers}
  </tr></thead>
  <tbody>
{entity_rows}
  </tbody>
  </table>
</div>

<div class="section">
  <div class="section-header">
    <h2>Failure Analysis</h2>
    <span class="section-badge">FPs &amp; FNs</span>
  </div>
{failure_sections}
</div>

<footer>
  data_classifier Sprint {sprint} &mdash; consolidated benchmark report (accuracy only, no perf)
</footer>

</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate consolidated sprint benchmark report")
    parser.add_argument("--sprint", type=int, required=True, help="Sprint number")
    parser.add_argument("--samples", type=int, default=50, help="Samples per column (default: 50)")
    parser.add_argument("--output", type=str, default=None, help="Output HTML path")
    args = parser.parse_args()

    runs = run_all(args.sprint, samples_per_col=args.samples)
    html = generate_consolidated_html(args.sprint, runs)

    output_path = Path(args.output) if args.output else Path(f"docs/benchmarks/SPRINT{args.sprint}_CONSOLIDATED.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    print(f"Consolidated report: {output_path} ({len(html):,} chars)", file=sys.stderr)

    # Also print a brief stdout summary
    print(f"\nSprint {args.sprint} consolidated results:", file=sys.stderr)
    for r in runs:
        mode = "blind" if r.blind else "named"
        print(
            f"  {r.corpus:12s} {mode:6s}  Macro F1 {r.macro_f1:.3f}  "
            f"Primary {r.primary_label_accuracy:.1%}  "
            f"TP={r.total_tp:3d} FP={r.total_fp:3d} FN={r.total_fn:3d}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
