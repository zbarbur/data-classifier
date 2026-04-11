"""Generate a sprint benchmark report in Markdown.

Runs both pattern-level and column-level benchmarks, writes a formatted
Markdown report to docs/sprints/SPRINT{N}_BENCHMARK.md.

Usage:
    python -m tests.benchmarks.generate_report --sprint 2 [--samples 500]
"""

from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from tests.benchmarks.accuracy_benchmark import BenchmarkResult, run_benchmark
from tests.benchmarks.corpus_generator import generate_corpus, generate_raw_samples
from tests.benchmarks.pattern_benchmark import run_pattern_benchmark
from tests.benchmarks.perf_benchmark import run_perf_benchmark


def _capture_pattern_report(samples: list[tuple[str, str | None]]) -> tuple[dict, str]:
    """Run pattern benchmark and capture results."""
    from tests.benchmarks.pattern_benchmark import print_report

    entity_results, pattern_stats, collision_matrix = run_pattern_benchmark(samples)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_report(samples, entity_results, pattern_stats, collision_matrix)

    return {"entity_results": entity_results, "collision_matrix": collision_matrix}, buf.getvalue()


def _capture_column_report(corpus: list[tuple], corpus_source: str = "synthetic") -> tuple[dict, str]:
    """Run column-level benchmark and capture results."""
    from tests.benchmarks.accuracy_benchmark import print_report

    results, metrics = run_benchmark(corpus, corpus_source=corpus_source)

    # Retrieve the BenchmarkResult with aggregate metrics
    last_result: BenchmarkResult | None = getattr(run_benchmark, "_last_result", None)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_report(corpus, results, metrics)

    return {
        "metrics": metrics,
        "macro_f1": last_result.macro_f1 if last_result else 0.0,
        "micro_f1": last_result.micro_f1 if last_result else 0.0,
        "primary_label_accuracy": last_result.primary_label_accuracy if last_result else 0.0,
        "corpus_source": corpus_source,
    }, buf.getvalue()


def _capture_perf_report(corpus: list[tuple], iterations: int = 5) -> tuple[dict, str]:
    """Run performance benchmark and capture results."""
    from tests.benchmarks.perf_benchmark import print_report

    perf_results = run_perf_benchmark(corpus, iterations=iterations)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_report(perf_results)

    return perf_results, buf.getvalue()


def _capture_secret_report() -> tuple[dict, str]:
    """Run secret detection benchmark and capture results."""
    from tests.benchmarks.secret_benchmark import print_report as secret_print_report
    from tests.benchmarks.secret_benchmark import run_benchmark as secret_run_benchmark

    metrics = secret_run_benchmark()

    buf = io.StringIO()
    with redirect_stdout(buf):
        secret_print_report(metrics)

    # Compute overall metrics
    tp_layers = [layer for layer in metrics if not layer.startswith("tn_") and layer != "known_limitation"]
    overall_tp = sum(metrics[layer].tp for layer in tp_layers)
    overall_fp = sum(m.fp for m in metrics.values())
    overall_fn = sum(metrics[layer].fn for layer in tp_layers)
    overall_p = overall_tp / (overall_tp + overall_fp) if (overall_tp + overall_fp) > 0 else 0.0
    overall_r = overall_tp / (overall_tp + overall_fn) if (overall_tp + overall_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    return {
        "metrics": metrics,
        "overall_f1": overall_f1,
        "overall_precision": overall_p,
        "overall_recall": overall_r,
    }, buf.getvalue()


def generate_report(
    sprint: int,
    samples_per_type: int = 500,
    corpus_source: str = "synthetic",
    *,
    blind: bool = False,
    include_perf: bool = False,
    perf_iterations: int = 5,
) -> tuple[str, dict]:
    """Generate the full benchmark report as a Markdown string.

    Returns:
        Tuple of (markdown_report, data_dict) where data_dict contains
        the raw metrics for HTML report generation.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    from data_classifier.patterns import load_default_patterns

    patterns = load_default_patterns()
    pattern_count = len(patterns)
    entity_types_in_patterns = len({p.entity_type for p in patterns})

    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w(f"# Sprint {sprint} — Benchmark Report")
    w()
    w(f"> **Generated:** {now}")
    w(f"> **Samples per type:** {samples_per_type}")
    w(f"> **Patterns:** {pattern_count}")
    w(f"> **Entity types (patterns):** {entity_types_in_patterns}")
    w(f"> **Corpus source:** {corpus_source}")
    w()

    # ── Pattern-level benchmark ──────────────────────────────────────────
    print(f"Running pattern benchmark ({samples_per_type} samples/type)...", file=sys.stderr)
    raw_samples = generate_raw_samples(count_per_type=samples_per_type)
    pattern_data, pattern_text = _capture_pattern_report(raw_samples)

    positive_samples = sum(1 for _, e in raw_samples if e is not None)
    negative_samples = len(raw_samples) - positive_samples

    entity_results = pattern_data["entity_results"]
    total_tp = sum(r.tp for r in entity_results.values())
    total_fp = sum(r.fp for r in entity_results.values())
    total_fn = sum(r.fn for r in entity_results.values())
    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    w("## Summary")
    w()
    w("| Metric | Pattern-Level (regex only) | Column-Level (full pipeline) |")
    w("|---|---|---|")

    # ── Column-level benchmark ───────────────────────────────────────────
    print(f"Running column benchmark ({corpus_source}, {samples_per_type} samples/type)...", file=sys.stderr)
    if corpus_source == "synthetic":
        corpus = generate_corpus(samples_per_type=samples_per_type)
    else:
        from tests.benchmarks.corpus_loader import load_corpus

        corpus = load_corpus(corpus_source, samples_per_type=samples_per_type, blind=blind)
    col_data, col_text = _capture_column_report(corpus, corpus_source=corpus_source)
    total_col_samples = sum(len(c.sample_values) for c, _ in corpus)
    col_metrics = col_data["metrics"]
    col_tp = sum(m.tp for m in col_metrics.values())
    col_fp = sum(m.fp for m in col_metrics.values())
    col_fn = sum(m.fn for m in col_metrics.values())
    col_p = col_tp / (col_tp + col_fp) if (col_tp + col_fp) > 0 else 0.0
    col_r = col_tp / (col_tp + col_fn) if (col_tp + col_fn) > 0 else 0.0
    col_f1 = 2 * col_p * col_r / (col_p + col_r) if (col_p + col_r) > 0 else 0.0
    col_macro_f1 = col_data.get("macro_f1", 0.0)
    col_primary_acc = col_data.get("primary_label_accuracy", 0.0)

    # ── Secret detection benchmark ──────────────────────────────────────
    print("Running secret detection benchmark...", file=sys.stderr)
    secret_data, secret_text = _capture_secret_report()
    secret_f1 = secret_data.get("overall_f1", 0.0)
    secret_p = secret_data.get("overall_precision", 0.0)
    secret_r = secret_data.get("overall_recall", 0.0)

    w(f"| Total samples | {len(raw_samples):,} | {total_col_samples:,} |")
    w(
        f"| Positive / Negative | {positive_samples:,} / {negative_samples:,}"
        f" | {sum(1 for _, e in corpus if e is not None)} cols"
        f" / {sum(1 for _, e in corpus if e is None)} cols |"
    )
    w(f"| Precision | {overall_p:.3f} | {col_p:.3f} |")
    w(f"| Recall | {overall_r:.3f} | {col_r:.3f} |")
    w(f"| **Micro F1** | **{overall_f1:.3f}** | **{col_f1:.3f}** |")
    w(f"| **Macro F1** | — | **{col_macro_f1:.3f}** |")
    w(f"| **Primary-Label Accuracy** | — | **{col_primary_acc:.1%}** |")
    w(f"| TP / FP / FN | {total_tp:,} / {total_fp:,} / {total_fn:,} | {col_tp} / {col_fp} / {col_fn} |")
    w()

    # ── Secret detection summary ────────────────────────────────────────
    w("### Secret Detection")
    w()
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| Precision | {secret_p:.3f} |")
    w(f"| Recall | {secret_r:.3f} |")
    w(f"| **F1** | **{secret_f1:.3f}** |")
    w()

    # ── Per-entity F1 breakdown ─────────────────────────────────────────
    w("### Per-Entity F1 Breakdown (Column-Level)")
    w()
    w("| Entity Type | Precision | Recall | F1 | TP | FP | FN |")
    w("|---|---|---|---|---|---|---|")
    for entity_type in sorted(col_metrics.keys()):
        m = col_metrics[entity_type]
        w(f"| {entity_type} | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} | {m.tp} | {m.fp} | {m.fn} |")
    w()

    # ── Corpus source metadata ──────────────────────────────────────────
    w("### Corpus Metadata")
    w()
    w("| Property | Value |")
    w("|---|---|")
    w(f"| Source | {corpus_source} |")
    w(f"| Pattern samples | {len(raw_samples):,} ({positive_samples:,} positive, {negative_samples:,} negative) |")
    w(f"| Column corpus | {len(corpus)} columns ({total_col_samples:,} total samples) |")
    w(f"| Entity types tested | {len({e for _, e in corpus if e is not None})} |")
    w()

    # ── Performance (opt-in) ───────────────────────────────────────────
    if include_perf:
        print(f"Running performance benchmark ({perf_iterations} iterations)...", file=sys.stderr)
        perf_data, perf_text = _capture_perf_report(corpus, iterations=perf_iterations)
    else:
        print("Skipping performance benchmark (use --perf to include).", file=sys.stderr)
        perf_data, perf_text = {}, ""
    fp = perf_data.get("full_pipeline", {})

    w("## Performance")
    w()
    w("| Metric | Value |")
    w("|---|---|")
    w(
        f"| Throughput | {fp.get('columns_per_sec', 0):,.0f} columns/sec"
        f" \\| {fp.get('samples_per_sec', 0):,.0f} samples/sec |"
    )
    w(f"| Per column (p50) | {fp.get('per_column_p50_ms', 0):.3f} ms |")
    w(f"| Per sample (p50) | {fp.get('per_sample_p50_us', 0):.1f} us |")
    w(f"| Warmup (RE2 compile) | {perf_data.get('warmup_ms', 0):.1f} ms |")
    w()

    # Scaling
    w("### Scaling")
    w()
    scaling_samples = perf_data.get("scaling_samples", [])
    if scaling_samples:
        w("**Sample count scaling (per-column latency):**")
        w()
        w("| Samples/col | Latency (p50) |")
        w("|---|---|")
        for s in scaling_samples:
            w(f"| {s['samples_per_col']} | {s['per_column_p50_ms']:.3f} ms |")
        w()

    scaling_length = perf_data.get("scaling_length", [])
    if scaling_length:
        base_us = scaling_length[0]["p50_us"]
        w("**Input length scaling (RE2 linearity):**")
        w()
        w("| Input bytes | p50 (us) | Ratio |")
        w("|---|---|---|")
        for s in scaling_length:
            ratio = s["p50_us"] / base_us if base_us > 0 else 0
            w(f"| {s['input_bytes']:,} | {s['p50_us']:.1f} | {ratio:.1f}x |")
        w()

    # ── Detailed reports ─────────────────────────────────────────────────
    w("## Pattern-Level Detail")
    w()
    w("```")
    w(pattern_text.strip())
    w("```")
    w()

    w("## Column-Level Detail")
    w()
    w("```")
    w(col_text.strip())
    w("```")
    w()

    w("## Secret Detection Detail")
    w()
    w("```")
    w(secret_text.strip())
    w("```")
    w()

    w("## Performance Detail")
    w()
    w("```")
    w(perf_text.strip())
    w("```")

    report_data = {
        "col_metrics": col_metrics,
        "col_macro_f1": col_macro_f1,
        "col_primary_acc": col_primary_acc,
        "col_micro_f1": col_f1,
        "perf_data": perf_data,
        "secret_data": secret_data,
        "corpus_source": corpus_source,
    }

    return "\n".join(lines), report_data


def generate_html_report(  # noqa: C901
    sprint: int,
    *,
    col_metrics: dict | None = None,
    col_macro_f1: float = 0.0,
    col_primary_acc: float = 0.0,
    col_micro_f1: float = 0.0,
    perf_data: dict | None = None,
    secret_data: dict | None = None,
    corpus_source: str = "synthetic",
) -> str:
    """Generate a self-contained HTML benchmark report with executive summary and detailed drill-downs."""
    col_metrics = col_metrics or {}
    perf_data = perf_data or {}
    secret_data = secret_data or {}
    report_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Compute aggregate metrics ──────────────────────────────────────
    col_tp = sum(m.tp for m in col_metrics.values())
    col_fp = sum(m.fp for m in col_metrics.values())
    col_fn = sum(m.fn for m in col_metrics.values())
    col_p = col_tp / (col_tp + col_fp) if (col_tp + col_fp) > 0 else 0.0
    col_r = col_tp / (col_tp + col_fn) if (col_tp + col_fn) > 0 else 0.0
    total_entities = len(col_metrics)

    fp = perf_data.get("full_pipeline", {})
    secret_f1 = secret_data.get("overall_f1", 0.0)
    secret_p = secret_data.get("overall_precision", 0.0)
    secret_r = secret_data.get("overall_recall", 0.0)
    warmup_ms = perf_data.get("warmup_ms", 0)

    good_entities = sum(1 for m in col_metrics.values() if m.f1 >= 0.9)
    warn_entities = sum(1 for m in col_metrics.values() if 0.7 <= m.f1 < 0.9)
    bad_entities = total_entities - good_entities - warn_entities

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

    # ── Build entity table rows with F1 bar ────────────────────────────
    entity_rows = ""
    for et, m in sorted(col_metrics.items(), key=lambda x: x[1].f1, reverse=True):
        f1_color = _color(m.f1)
        bar_w = max(m.f1 * 100, 2)
        entity_rows += (
            f"<tr><td><strong>{et}</strong></td>"
            f"<td class='num'>{m.tp}</td><td class='num'>{m.fp}</td><td class='num'>{m.fn}</td>"
            f"<td class='num'>{m.precision:.3f}</td><td class='num'>{m.recall:.3f}</td>"
            f"<td class='num' style='color:{f1_color};font-weight:700'>{m.f1:.3f}</td>"
            f"<td><div class='bar-bg'>"
            f"<div class='bar' style='width:{bar_w}%;background:{f1_color}'></div>"
            f"</div></td></tr>\n"
        )

    # ── Build secret detection rows ────────────────────────────────────
    secret_metrics = secret_data.get("metrics", {})
    secret_rows = ""
    for source, m in sorted(secret_metrics.items()):
        if hasattr(m, "tp"):
            s_p = m.tp / (m.tp + m.fp) if (m.tp + m.fp) > 0 else 0.0
            s_r = m.tp / (m.tp + m.fn) if (m.tp + m.fn) > 0 else 0.0
            s_f1 = 2 * s_p * s_r / (s_p + s_r) if (s_p + s_r) > 0 else 0.0
            f1c = _color(s_f1, good=0.8, warn=0.5)
            secret_rows += (
                f"<tr><td><strong>{source}</strong></td>"
                f"<td class='num'>{m.tp + m.fp + m.fn}</td>"
                f"<td class='num'>{m.tp}</td><td class='num'>{m.fp}</td>"
                f"<td class='num'>{m.fn}</td>"
                f"<td class='num'>{s_p:.3f}</td><td class='num'>{s_r:.3f}</td>"
                f"<td class='num' style='color:{f1c};font-weight:700'>"
                f"{s_f1:.3f}</td></tr>\n"
            )

    # ── Scaling tables ─────────────────────────────────────────────────
    scaling_rows = ""
    for s in perf_data.get("scaling_samples", []):
        scaling_rows += (
            f"<tr><td class='num'>{s['samples_per_col']}</td>"
            f"<td class='num'>{s['per_column_p50_ms']:.3f} ms</td></tr>\n"
        )

    length_rows = ""
    length_data = perf_data.get("scaling_length", [])
    if length_data:
        base_us = length_data[0]["p50_us"]
        for s in length_data:
            ratio = s["p50_us"] / base_us if base_us > 0 else 0
            rc = _color(1.0 / max(ratio, 0.01), good=0.3, warn=0.1)
            length_rows += (
                f"<tr><td class='num'>{s['input_bytes']:,}</td>"
                f"<td class='num'>{s['p50_us']:.1f} us</td>"
                f"<td class='num' style='color:{rc}'>{ratio:.1f}x</td></tr>\n"
            )

    # ── Per-engine breakdown ───────────────────────────────────────────
    engine_rows = ""
    engine_keys = sorted([k for k in perf_data if k.startswith("engine_") and k != "engine_events"])
    for key in engine_keys:
        eng = perf_data[key]
        name = key.replace("engine_", "").replace("_", " ").title()
        pct = eng["pct_of_pipeline"]
        bc = "#3b82f6" if pct < 50 else "#f59e0b" if pct < 80 else "#ef4444"
        engine_rows += (
            f"<tr><td><strong>{name}</strong></td>"
            f"<td class='num'>{eng['total_p50_ms']:.2f} ms</td>"
            f"<td class='num'>{eng['per_column_p50_ms']:.3f} ms</td>"
            f"<td><div class='bar-bg'>"
            f"<div class='bar' style='width:{pct}%;background:{bc}'></div>"
            f"</div><span class='bar-label'>{pct:.0f}%</span></td></tr>\n"
        )

    # ── Assemble HTML ──────────────────────────────────────────────────
    html_parts: list[str] = []

    def h(s: str) -> None:
        html_parts.append(s)

    h(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sprint {sprint} Benchmark Report</title>
<style>
  :root {{
    --bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--border-light:#f1f5f9;
    --text:#1e293b;--text-muted:#64748b;--text-faint:#94a3b8;
    --green:#22c55e;--green-bg:#dcfce7;--green-text:#166534;
    --amber:#f59e0b;--amber-bg:#fef3c7;--amber-text:#92400e;
    --red:#ef4444;--red-bg:#fee2e2;--red-text:#991b1b;
    --blue:#3b82f6;--blue-light:#dbeafe;
  }}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:var(--bg);color:var(--text);max-width:1280px;margin:0 auto;padding:2rem}}
  .header{{margin-bottom:2.5rem}}
  .header h1{{font-size:2rem;font-weight:800;letter-spacing:-0.02em}}
  .header .subtitle{{color:var(--text-muted);font-size:1rem;margin-top:0.3rem}}
  .header .meta{{display:flex;gap:1.5rem;margin-top:0.8rem;flex-wrap:wrap}}
  .header .meta span{{font-size:0.85rem;color:var(--text-faint)}}
  .header .meta strong{{color:var(--text-muted)}}
  .section{{margin-top:3rem}}
  .section-header{{display:flex;align-items:baseline;gap:0.8rem;margin-bottom:1.2rem;
                   border-bottom:2px solid var(--border);padding-bottom:0.6rem}}
  .section-header h2{{font-size:1.35rem;font-weight:700}}
  .section-badge{{font-size:0.75rem;background:var(--blue-light);color:var(--blue);
                  padding:0.2rem 0.6rem;border-radius:10px;font-weight:600}}
  .summary-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin:1.5rem 0}}
  .summary-card{{background:var(--surface);border-radius:12px;padding:1.5rem;
                 box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid var(--border-light);
                 transition:box-shadow .15s}}
  .summary-card:hover{{box-shadow:0 4px 12px rgba(0,0,0,.08)}}
  .summary-card .card-label{{font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;
                             letter-spacing:0.06em;font-weight:600}}
  .summary-card .card-value{{font-size:2.4rem;font-weight:800;margin:0.3rem 0 0.15rem;
                             letter-spacing:-0.02em;line-height:1.1}}
  .summary-card .card-sub{{font-size:0.8rem;color:var(--text-faint)}}
  .summary-card.highlight{{border-left:4px solid var(--blue)}}
  .metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:0.8rem;margin:1rem 0}}
  .metric-card{{background:var(--surface);border-radius:8px;padding:1rem;
                box-shadow:0 1px 2px rgba(0,0,0,.05);border:1px solid var(--border-light)}}
  .metric-card .card-label{{font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;
                            letter-spacing:0.05em;font-weight:600}}
  .metric-card .card-value{{font-size:1.6rem;font-weight:700;margin-top:0.2rem}}
  .metric-card .card-sub{{font-size:0.75rem;color:var(--text-faint);margin-top:0.1rem}}
  table{{width:100%;border-collapse:collapse;background:var(--surface);border-radius:10px;
         overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid var(--border-light)}}
  th{{background:var(--border-light);text-align:left;padding:0.7rem 1rem;font-size:0.75rem;
      color:var(--text-muted);text-transform:uppercase;letter-spacing:0.04em;font-weight:700}}
  td{{padding:0.6rem 1rem;border-top:1px solid var(--border-light);font-size:0.88rem}}
  td.num{{font-variant-numeric:tabular-nums;text-align:right}}
  tr:hover td{{background:#f8fafc}}
  .bar-bg{{width:80px;height:8px;background:var(--border-light);border-radius:4px;
           overflow:hidden;display:inline-block;vertical-align:middle}}
  .bar{{height:100%;border-radius:4px}}
  .bar-label{{font-size:0.75rem;color:var(--text-muted);margin-left:0.3rem}}
  .tag{{display:inline-block;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.7rem;
        font-weight:700;letter-spacing:0.03em}}
  .tag-good{{background:var(--green-bg);color:var(--green-text)}}
  .tag-warn{{background:var(--amber-bg);color:var(--amber-text)}}
  .tag-bad{{background:var(--red-bg);color:var(--red-text)}}
  details{{margin:1.2rem 0}}
  summary{{cursor:pointer;font-weight:600;font-size:0.95rem;padding:0.6rem 0;
          color:var(--blue);user-select:none}}
  summary:hover{{color:#2563eb}}
  details[open] summary{{margin-bottom:0.8rem}}
  .entity-health{{display:flex;gap:1rem;margin-bottom:1rem;align-items:center}}
  .health-pill{{display:flex;align-items:center;gap:0.4rem;font-size:0.85rem;font-weight:600}}
  .health-dot{{width:10px;height:10px;border-radius:50%}}
  footer{{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--border);
         color:var(--text-faint);font-size:0.8rem;display:flex;justify-content:space-between}}
  @media(max-width:768px){{
    .summary-grid{{grid-template-columns:1fr}}
    .metric-grid{{grid-template-columns:repeat(2,1fr)}}
    body{{padding:1rem}}
  }}
</style>
</head>
<body>""")

    # ── Header ─────────────────────────────────────────────────────────
    h(f"""
<div class="header">
  <h1>Sprint {sprint} — Benchmark Report</h1>
  <div class="subtitle">data_classifier — Consolidated Accuracy + Performance</div>
  <div class="meta">
    <span>Corpus: <strong>{corpus_source}</strong></span>
    <span>Entities: <strong>{total_entities}</strong></span>
    <span>Generated: <strong>{report_time}</strong></span>
  </div>
</div>""")

    # ── Executive Summary ──────────────────────────────────────────────
    h(f"""
<div class="section">
  <div class="section-header">
    <h2>Executive Summary</h2>
    <span class="section-badge">At a Glance</span>
  </div>
  <div class="summary-grid">
    <div class="summary-card highlight">
      <div class="card-label">Macro F1 {_tag(col_macro_f1)}</div>
      <div class="card-value" style="color:{_color(col_macro_f1)}">{col_macro_f1:.3f}</div>
      <div class="card-sub">Average per-entity F1</div>
    </div>
    <div class="summary-card highlight">
      <div class="card-label">Primary-Label {_tag(col_primary_acc)}</div>
      <div class="card-value" style="color:{_color(col_primary_acc)}">{col_primary_acc:.1%}</div>
      <div class="card-sub">Top-1 prediction correct</div>
    </div>
    <div class="summary-card">
      <div class="card-label">Throughput</div>
      <div class="card-value">{fp.get("columns_per_sec", 0):,.0f}</div>
      <div class="card-sub">columns/sec (p50={fp.get("per_column_p50_ms", 0):.2f}ms)</div>
    </div>
  </div>
  <div class="metric-grid">
    <div class="metric-card">
      <div class="card-label">Micro F1</div>
      <div class="card-value" style="color:{_color(col_micro_f1)}">{col_micro_f1:.3f}</div>
      <div class="card-sub">TP={col_tp} FP={col_fp} FN={col_fn}</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Precision</div>
      <div class="card-value" style="color:{_color(col_p)}">{col_p:.3f}</div>
      <div class="card-sub">Low FPs = trust</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Recall</div>
      <div class="card-value" style="color:{_color(col_r)}">{col_r:.3f}</div>
      <div class="card-sub">Low FNs = coverage</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Secret Detection F1</div>
      <div class="card-value" style="color:{_color(secret_f1)}">{secret_f1:.3f}</div>
      <div class="card-sub">P={secret_p:.3f} R={secret_r:.3f}</div>
    </div>
  </div>
</div>""")

    # ── Accuracy Detail ────────────────────────────────────────────────
    h(f"""
<div class="section">
  <div class="section-header">
    <h2>Accuracy — Per-Entity Breakdown</h2>
    <span class="section-badge">{total_entities} entities</span>
  </div>
  <div class="entity-health">
    <div class="health-pill">
      <div class="health-dot" style="background:var(--green)"></div>
      {good_entities} good (F1 &ge; 0.9)</div>
    <div class="health-pill">
      <div class="health-dot" style="background:var(--amber)"></div>
      {warn_entities} warning (0.7&ndash;0.9)</div>
    <div class="health-pill">
      <div class="health-dot" style="background:var(--red)"></div>
      {bad_entities} low (&lt; 0.7)</div>
  </div>
  <table>
  <thead><tr>
    <th>Entity Type</th><th style="text-align:right">TP</th>
    <th style="text-align:right">FP</th><th style="text-align:right">FN</th>
    <th style="text-align:right">Prec</th><th style="text-align:right">Recall</th>
    <th style="text-align:right">F1</th><th>F1 Bar</th>
  </tr></thead>
  <tbody>
{entity_rows}
  </tbody>
  </table>
</div>""")

    # ── Performance ────────────────────────────────────────────────────
    h(f"""
<div class="section">
  <div class="section-header">
    <h2>Performance</h2>
    <span class="section-badge">Latency &amp; Throughput</span>
  </div>
  <div class="metric-grid">
    <div class="metric-card">
      <div class="card-label">Throughput</div>
      <div class="card-value">{fp.get("columns_per_sec", 0):,.0f}</div>
      <div class="card-sub">columns/sec</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Per Column (p50)</div>
      <div class="card-value">{fp.get("per_column_p50_ms", 0):.2f}</div>
      <div class="card-sub">ms</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Per Sample (p50)</div>
      <div class="card-value">{fp.get("per_sample_p50_us", 0):.1f}</div>
      <div class="card-sub">us</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Warmup (RE2)</div>
      <div class="card-value">{warmup_ms:.1f}</div>
      <div class="card-sub">ms (compile)</div>
    </div>
  </div>
  <details>
  <summary>Per-Engine Latency Breakdown</summary>
  <table>
  <thead><tr><th>Engine</th><th style="text-align:right">Total (p50)</th>
    <th style="text-align:right">Per Column</th><th>% of Pipeline</th></tr></thead>
  <tbody>{engine_rows}</tbody>
  </table>
  </details>
  <details>
  <summary>Sample Count Scaling</summary>
  <table>
  <thead><tr><th style="text-align:right">Samples/col</th>
    <th style="text-align:right">Latency (p50)</th></tr></thead>
  <tbody>{scaling_rows}</tbody>
  </table>
  </details>
  <details>
  <summary>Input Length Scaling (RE2 Linearity)</summary>
  <table>
  <thead><tr><th style="text-align:right">Input Bytes</th>
    <th style="text-align:right">p50</th>
    <th style="text-align:right">Ratio</th></tr></thead>
  <tbody>{length_rows}</tbody>
  </table>
  </details>
</div>""")

    # ── Secret Detection ───────────────────────────────────────────────
    h(f"""
<div class="section">
  <div class="section-header">
    <h2>Secret Detection</h2>
    <span class="section-badge">By Source</span>
  </div>
  <div class="metric-grid">
    <div class="metric-card">
      <div class="card-label">Overall F1</div>
      <div class="card-value" style="color:{_color(secret_f1)}">{secret_f1:.3f}</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Precision</div>
      <div class="card-value" style="color:{_color(secret_p)}">{secret_p:.3f}</div>
    </div>
    <div class="metric-card">
      <div class="card-label">Recall</div>
      <div class="card-value" style="color:{_color(secret_r)}">{secret_r:.3f}</div>
    </div>
  </div>
  <details open>
  <summary>Per-Source Breakdown</summary>
  <table>
  <thead><tr><th>Source</th><th style="text-align:right">Total</th>
    <th style="text-align:right">TP</th><th style="text-align:right">FP</th>
    <th style="text-align:right">FN</th><th style="text-align:right">Prec</th>
    <th style="text-align:right">Recall</th>
    <th style="text-align:right">F1</th></tr></thead>
  <tbody>{secret_rows}</tbody>
  </table>
  </details>
</div>""")

    # ── Footer ─────────────────────────────────────────────────────────
    h(f"""
<footer>
  <span>data_classifier Sprint {sprint} — consolidated benchmark report</span>
  <span>Generated by tests.benchmarks.generate_report</span>
</footer>
</body>
</html>""")

    return "\n".join(html_parts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate sprint benchmark report")
    parser.add_argument("--sprint", type=int, required=True, help="Sprint number")
    parser.add_argument("--samples", type=int, default=500, help="Samples per entity type")
    parser.add_argument("--output", type=str, default=None, help="Output file (default: docs/sprints/)")
    parser.add_argument(
        "--corpus",
        type=str,
        default="synthetic",
        choices=["synthetic", "ai4privacy", "nemotron", "all"],
        help="Corpus source (default: synthetic)",
    )
    parser.add_argument(
        "--blind",
        action="store_true",
        help="Use generic column names (col_0, col_1, ...) to test sample-value-only classification",
    )
    parser.add_argument("--perf", action="store_true", help="Include performance benchmark (slow, off by default)")
    parser.add_argument("--perf-iterations", type=int, default=5, help="Performance benchmark iterations (default: 5)")
    args = parser.parse_args()

    report, report_data = generate_report(
        sprint=args.sprint,
        samples_per_type=args.samples,
        corpus_source=args.corpus,
        blind=args.blind,
        include_perf=args.perf,
        perf_iterations=args.perf_iterations,
    )

    # Markdown report in docs/sprints/ (legacy location)
    md_path = args.output or f"docs/sprints/SPRINT{args.sprint}_BENCHMARK.md"
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    Path(md_path).write_text(report + "\n")
    print(f"Markdown report: {md_path}", file=sys.stderr)

    # HTML report in docs/benchmarks/ (primary artifact, committed per sprint)
    html = generate_html_report(sprint=args.sprint, **report_data)
    html_dir = Path("docs/benchmarks")
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / f"SPRINT{args.sprint}_REPORT.html"
    html_path.write_text(html)
    print(f"HTML report:     {html_path} ({len(html):,} chars)", file=sys.stderr)
