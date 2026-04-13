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
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tests.benchmarks.accuracy_benchmark import run_benchmark
from tests.benchmarks.benchmark_history_io import (
    compute_delta,
    history_dir,
    load_recent_sprints,
    save_sprint_benchmark,
)
from tests.benchmarks.corpus_loader import load_corpus
from tests.benchmarks.schema.benchmark_history import (
    CorpusResult,
    SprintBenchmark,
    from_dict,
)


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


def _git_short_sha() -> str:
    """Return the short SHA of HEAD, or 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _run_to_corpus_result(r: RunResult) -> CorpusResult:
    """Convert an in-memory RunResult to a persistable CorpusResult."""
    return CorpusResult(
        corpus=r.corpus,
        mode="blind" if r.blind else "named",
        macro_f1=round(r.macro_f1, 4),
        micro_f1=round(r.micro_f1, 4),
        precision=round(r.precision, 4),
        recall=round(r.recall, 4),
        tp_count=r.total_tp,
        fp_count=r.total_fp,
        fn_count=r.total_fn,
        primary_label_pct=round(r.primary_label_accuracy, 4),
    )


def build_sprint_benchmark(sprint: int, runs: list[RunResult], *, git_sha: str | None = None) -> SprintBenchmark:
    """Construct a persistable SprintBenchmark from live benchmark runs.

    Performance is left unset — the consolidated report does not run the
    perf benchmark inline. Run ``perf_quick`` separately and merge into the
    history JSON if/when needed.
    """
    return SprintBenchmark(
        sprint=sprint,
        date=datetime.now(timezone.utc).date().isoformat(),
        git_sha=git_sha or _git_short_sha(),
        accuracy=[_run_to_corpus_result(r) for r in runs],
        perf=None,
    )


def _runs_from_snapshot(snapshot: SprintBenchmark) -> list[RunResult]:
    """Synthesize RunResult objects from a persisted snapshot.

    Used when the live benchmark phases are skipped (e.g. a historical
    sprint whose ad-hoc logs were committed after-the-fact). Per-entity
    metrics, FPs, and FNs are left empty because they were not captured
    in the history artifact — the report surfaces aggregate numbers
    instead and links the raw logs from the sidecar directory.
    """
    runs: list[RunResult] = []
    for acc in snapshot.accuracy:
        primary = acc.primary_label_pct if acc.primary_label_pct is not None else acc.macro_f1
        micro = acc.micro_f1 if acc.micro_f1 is not None else acc.macro_f1
        runs.append(
            RunResult(
                corpus=acc.corpus,
                blind=(acc.mode == "blind"),
                samples_per_col=0,
                num_columns=acc.tp_count + acc.fn_count,
                macro_f1=acc.macro_f1,
                micro_f1=micro,
                primary_label_accuracy=primary,
                precision=acc.precision,
                recall=acc.recall,
                total_tp=acc.tp_count,
                total_fp=acc.fp_count,
                total_fn=acc.fn_count,
                per_entity={},
                false_positives=[],
                false_negatives=[],
            )
        )
    return runs


def _load_history_snapshot(sprint: int, *, history: Path | None = None) -> tuple[SprintBenchmark, dict]:
    """Load ``sprint_N.json`` directly and return (snapshot, raw_dict).

    The raw dict is kept alongside the parsed snapshot because the
    ad-hoc Sprint 8 perf schema carries per-engine breakdowns that are
    not modelled in ``PerfResult`` — the perf section renderer walks
    the raw dict to display them.
    """
    directory = history or history_dir()
    path = directory / f"sprint_{sprint}.json"
    if not path.exists():
        raise FileNotFoundError(f"No history snapshot for sprint {sprint}: {path}")
    raw = json.loads(path.read_text())
    snapshot = from_dict(raw)
    return snapshot, raw


def _render_sprint8_perf_section(raw: dict, sprint: int) -> str:
    """Render a perf summary from the raw ``sprint_N.json`` dict.

    Handles both the canonical ``PerfResult`` shape (used from Sprint 5
    onward for accuracy+perf runs) and the Sprint 8 ad-hoc shape
    (``full_cascade_p50_ms`` + ``per_engine: {engine: {total_ms, ...}}``).
    Returns an empty string when no perf section is present.
    """
    perf = raw.get("perf")
    if not perf:
        return ""

    method = perf.get("method") or "perf_benchmark (automated)"
    notes = raw.get("note") or ""

    # Normalize the top-line latency across the two known shapes.
    total_p50 = perf.get("full_cascade_p50_ms") or perf.get("total_p50_ms") or 0.0
    per_col_p50 = perf.get("ms_per_col_p50") or perf.get("per_column_p50_ms") or 0.0
    n_columns = perf.get("n_columns") or "—"
    samples_per_col = perf.get("samples_per_col") or "—"
    iters = perf.get("iterations") or "—"
    warmup = perf.get("warmup_s")
    warmup_label = f"{warmup:.2f} s" if isinstance(warmup, (int, float)) else "—"

    # Per-engine rows: handle both dict-of-dict and dict-of-float shapes.
    raw_engines = perf.get("per_engine") or perf.get("per_engine_times_ms") or {}
    engine_rows = ""
    if isinstance(raw_engines, dict):
        items: list[tuple[str, dict]] = []
        for name, val in raw_engines.items():
            if isinstance(val, dict):
                items.append((name, val))
            else:
                items.append((name, {"total_ms": float(val)}))
        items.sort(key=lambda kv: -(kv[1].get("total_ms") or 0.0))
        for name, data in items:
            total_ms = data.get("total_ms", 0.0) or 0.0
            calls = data.get("calls", "—")
            mean_ms = data.get("mean_ms", "—")
            max_ms = data.get("max_ms", "—")
            pct = data.get("pct_of_pipeline")
            mean_str = f"{mean_ms:.2f}" if isinstance(mean_ms, (int, float)) else str(mean_ms)
            max_str = f"{max_ms:.2f}" if isinstance(max_ms, (int, float)) else str(max_ms)
            pct_str = f"{pct:.1f}%" if isinstance(pct, (int, float)) else "—"
            engine_rows += f"""
<tr>
  <td><strong>{name}</strong></td>
  <td class='num'>{calls}</td>
  <td class='num'>{total_ms:.2f} ms</td>
  <td class='num'>{mean_str}</td>
  <td class='num'>{max_str}</td>
  <td class='num'>{pct_str}</td>
</tr>
"""

    raw_log_refs = ""
    sidecar = Path(f"docs/benchmarks/sprint{sprint}")
    if sidecar.exists():
        log_files = sorted(sidecar.glob("*.log"))
        if log_files:
            items_html = "".join(f"<li><code>{p.relative_to(sidecar.parent.parent)}</code></li>" for p in log_files)
            raw_log_refs = (
                "<p style='margin-top:0.6rem;font-size:0.8rem;color:var(--text-muted)'>"
                "<strong>Raw audit logs:</strong></p>"
                f"<ul style='font-size:0.8rem;color:var(--text-muted);margin-left:1.2rem'>{items_html}</ul>"
            )

    notes_block = ""
    if notes:
        notes_block = (
            f"<p style='margin-top:0.6rem;font-size:0.8rem;color:var(--text-muted);font-style:italic'>Note: {notes}</p>"
        )

    return f"""
<div class="section">
  <div class="section-header">
    <h2>Performance</h2>
    <span class="section-badge">{method}</span>
  </div>
  <div class="aggregate">
    <div class="aggregate-metrics">
      <div class="aggregate-metric">
        <div class="label">Per-col p50</div>
        <div class="value">{per_col_p50:.1f} ms</div>
      </div>
      <div class="aggregate-metric">
        <div class="label">Cascade p50</div>
        <div class="value">{total_p50:.0f} ms</div>
      </div>
      <div class="aggregate-metric">
        <div class="label">Columns &times; samples</div>
        <div class="value" style="font-size:1.1rem">{n_columns} &times; {samples_per_col}</div>
      </div>
      <div class="aggregate-metric">
        <div class="label">Warmup / Iter</div>
        <div class="value" style="font-size:1.1rem">{warmup_label} / {iters}</div>
      </div>
    </div>
  </div>
  <table>
  <thead><tr>
    <th>Engine</th>
    <th class='num'>Calls</th>
    <th class='num'>Total</th>
    <th class='num'>Mean (ms)</th>
    <th class='num'>Max (ms)</th>
    <th class='num'>% of pipeline</th>
  </tr></thead>
  <tbody>
    {engine_rows}
  </tbody>
  </table>
  {raw_log_refs}
  {notes_block}
</div>
"""


def _render_svg_line_chart(
    series: list[tuple[int, float]],
    *,
    width: int = 420,
    height: int = 140,
    color: str = "#2e7d32",
    y_label: str = "",
    title: str = "",
) -> str:
    """Render an inline SVG line chart. Returns a placeholder if <2 points."""
    points = [(int(x), float(y)) for x, y in series if y is not None]
    if len(points) < 2:
        return f"<div class='trend-placeholder'><em>{title}: need &ge;2 sprints for trend</em></div>"
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    y_range = (y_max - y_min) or max(abs(y_max), 1.0) * 0.1 or 1.0
    x_range = (x_max - x_min) or 1
    pad_left, pad_right, pad_top, pad_bottom = 42, 14, 24, 26
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    def _px(x: int) -> float:
        return pad_left + (x - x_min) / x_range * plot_w

    def _py(y: float) -> float:
        return pad_top + plot_h - (y - y_min) / y_range * plot_h

    path = "M " + " L ".join(f"{_px(x):.1f},{_py(y):.1f}" for x, y in points)
    dots = "".join(f"<circle cx='{_px(x):.1f}' cy='{_py(y):.1f}' r='3' fill='{color}'/>" for x, y in points)
    x_ticks = "".join(
        f"<text x='{_px(x):.1f}' y='{height - 8}' font-size='9' text-anchor='middle' fill='#64748b'>S{x}</text>"
        for x, _ in points
    )
    y_top_label = f"{y_max:.3f}" if y_max < 10 else f"{y_max:.0f}"
    y_bot_label = f"{y_min:.3f}" if y_min < 10 else f"{y_min:.0f}"
    axis = (
        f"<line x1='{pad_left}' y1='{pad_top}' x2='{pad_left}' "
        f"y2='{height - pad_bottom}' stroke='#cbd5e1' stroke-width='1'/>"
        f"<line x1='{pad_left}' y1='{height - pad_bottom}' x2='{width - pad_right}' "
        f"y2='{height - pad_bottom}' stroke='#cbd5e1' stroke-width='1'/>"
    )
    y_labels = (
        f"<text x='{pad_left - 4}' y='{pad_top + 4}' font-size='9' "
        f"text-anchor='end' fill='#64748b'>{y_top_label}</text>"
        f"<text x='{pad_left - 4}' y='{height - pad_bottom + 2}' font-size='9' "
        f"text-anchor='end' fill='#64748b'>{y_bot_label}</text>"
    )
    title_el = (
        f"<text x='{width / 2:.0f}' y='14' font-size='11' font-weight='600' "
        f"text-anchor='middle' fill='#1e293b'>{title}</text>"
        if title
        else ""
    )
    y_label_el = (
        f"<text x='8' y='{(pad_top + height - pad_bottom) / 2:.0f}' "
        f"font-size='9' fill='#94a3b8' "
        f"transform='rotate(-90 8 {(pad_top + height - pad_bottom) / 2:.0f})'>"
        f"{y_label}</text>"
        if y_label
        else ""
    )
    return (
        f"<svg class='trend-chart' width='{width}' height='{height}' "
        f"xmlns='http://www.w3.org/2000/svg'>"
        f"{title_el}{axis}{y_labels}{y_label_el}{x_ticks}"
        f"<path d='{path}' stroke='{color}' stroke-width='2' fill='none'/>"
        f"{dots}</svg>"
    )


def _render_trend_section(history: list[SprintBenchmark]) -> str:
    """Render trend charts for macro F1 and per-column p50 across sprints."""
    if len(history) < 2:
        return (
            "<div class='section'>"
            "<div class='section-header'><h2>Sprint-over-Sprint Trend</h2>"
            "<span class='section-badge'>history</span></div>"
            "<p style='color:var(--text-muted);font-size:0.85rem'>"
            "Need at least 2 sprints of history to render a trend chart. "
            "Currently have "
            f"<strong>{len(history)}</strong> recorded.</p></div>"
        )

    # One chart per (corpus, mode) for macro_f1
    charts_html = ""
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sb in history:
        for r in sb.accuracy:
            k = (r.corpus, r.mode)
            if k not in seen:
                seen.add(k)
                keys.append(k)

    for corpus, mode in keys:
        series: list[tuple[int, float]] = []
        for sb in history:
            match = next(
                (r for r in sb.accuracy if r.corpus == corpus and r.mode == mode),
                None,
            )
            if match is not None:
                series.append((sb.sprint, match.macro_f1))
        color = "#a855f7" if mode == "blind" else "#3b82f6"
        charts_html += (
            "<div class='trend-cell'>"
            + _render_svg_line_chart(
                series,
                color=color,
                y_label="Macro F1",
                title=f"{corpus.title()} · {mode.upper()}",
            )
            + "</div>"
        )

    # Perf trend: per_column_p50_ms
    perf_series: list[tuple[int, float]] = [
        (sb.sprint, sb.perf.per_column_p50_ms) for sb in history if sb.perf is not None
    ]
    perf_chart = _render_svg_line_chart(
        perf_series,
        color="#ef4444",
        y_label="ms/col",
        title="Per-column p50 latency",
    )

    return f"""
<div class="section">
  <div class="section-header">
    <h2>Sprint-over-Sprint Trend</h2>
    <span class="section-badge">{len(history)} sprints</span>
  </div>
  <div class="trend-grid">
    {charts_html}
  </div>
  <div class="trend-row">
    <div class="trend-cell">{perf_chart}</div>
  </div>
</div>
"""


def _fmt_delta(val: float, *, is_count: bool = False, invert: bool = False) -> str:
    """Format a delta value with color: green=improvement, red=regression."""
    if val == 0:
        return "<span class='delta-neutral'>0</span>"
    better = (val < 0) if invert else (val > 0)
    cls = "delta-good" if better else "delta-bad"
    sign = "+" if val > 0 else ""
    if is_count:
        return f"<span class='{cls}'>{sign}{int(val)}</span>"
    return f"<span class='{cls}'>{sign}{val:.4f}</span>"


def _render_delta_section(current: SprintBenchmark, delta: dict) -> str:
    """Render the delta table: per (corpus, mode) current values and deltas."""
    if not delta or not delta.get("accuracy"):
        return (
            "<div class='section'>"
            "<div class='section-header'><h2>Delta vs Previous Sprint</h2>"
            "<span class='section-badge'>no prior data</span></div>"
            "<p style='color:var(--text-muted);font-size:0.85rem'>"
            "No previous sprint snapshot found — deltas will appear once "
            "two sprints are recorded.</p></div>"
        )

    acc_deltas = delta["accuracy"]
    perf_delta = delta.get("perf", {})

    rows = ""
    for cur in current.accuracy:
        key = (cur.corpus, cur.mode)
        if key not in acc_deltas:
            continue
        d = acc_deltas[key]
        rows += f"""
<tr>
  <td><strong>{cur.corpus.title()}</strong></td>
  <td><span class='mode-tag mode-{cur.mode}'>{cur.mode.upper()}</span></td>
  <td class='num'>{cur.macro_f1:.4f}</td>
  <td class='num'>{_fmt_delta(d["macro_f1"])}</td>
  <td class='num'>{cur.precision:.4f}</td>
  <td class='num'>{_fmt_delta(d["precision"])}</td>
  <td class='num'>{cur.recall:.4f}</td>
  <td class='num'>{_fmt_delta(d["recall"])}</td>
  <td class='num'>{cur.fp_count}</td>
  <td class='num'>{_fmt_delta(d["fp_count"], is_count=True, invert=True)}</td>
  <td class='num'>{cur.fn_count}</td>
  <td class='num'>{_fmt_delta(d["fn_count"], is_count=True, invert=True)}</td>
</tr>
"""

    perf_row = ""
    if perf_delta and current.perf is not None:
        pc = current.perf.per_column_p50_ms
        pd = perf_delta.get("per_column_p50_ms", 0)
        tp = current.perf.total_p50_ms
        td = perf_delta.get("total_p50_ms", 0)
        perf_row = f"""
<tr class='perf-row'>
  <td colspan='2'><strong>Performance</strong></td>
  <td class='num'>{pc:.1f} ms/col</td>
  <td class='num'>{_fmt_delta(pd, invert=True)}</td>
  <td class='num' colspan='4'>total p50 {tp:.0f} ms</td>
  <td class='num' colspan='4'>{_fmt_delta(td, invert=True)}</td>
</tr>
"""

    return f"""
<div class="section">
  <div class="section-header">
    <h2>Delta vs Previous Sprint</h2>
    <span class="section-badge">auto-computed</span>
  </div>
  <table class='delta-table'>
  <thead><tr>
    <th>Corpus</th>
    <th>Mode</th>
    <th class='num'>Macro F1</th>
    <th class='num'>&Delta; F1</th>
    <th class='num'>Precision</th>
    <th class='num'>&Delta; P</th>
    <th class='num'>Recall</th>
    <th class='num'>&Delta; R</th>
    <th class='num'>FP</th>
    <th class='num'>&Delta; FP</th>
    <th class='num'>FN</th>
    <th class='num'>&Delta; FN</th>
  </tr></thead>
  <tbody>
    {rows}
    {perf_row}
  </tbody>
  </table>
  <p style='margin-top:0.6rem;font-size:0.75rem;color:var(--text-muted)'>
    Green = improvement, red = regression, neutral = no change.
    For FP/FN and latency, lower is better.
  </p>
</div>
"""


def generate_consolidated_html(
    sprint: int,
    runs: list[RunResult],
    *,
    history: list[SprintBenchmark] | None = None,
    current_snapshot: SprintBenchmark | None = None,
    delta: dict | None = None,
    perf_section_html: str = "",
    subtitle: str | None = None,
) -> str:
    """Generate consolidated HTML report from all benchmark runs.

    ``perf_section_html``: optional pre-rendered performance section to
    splice in after the executive summary. Supplied by the from-history
    code path so the Sprint 8 perf snapshot is surfaced in the HTML.
    ``subtitle``: override the header subtitle (used by from-history
    mode to flag that the report was assembled from a history artifact
    rather than live benchmark runs).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    history = history or []
    delta = delta or {}
    trend_section = _render_trend_section(history)
    delta_section = _render_delta_section(current_snapshot, delta) if current_snapshot is not None else ""
    header_subtitle = subtitle or "data_classifier &mdash; Accuracy across all corpora and modes"

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

  /* Trend chart + delta table */
  .trend-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:0.8rem;margin-top:0.8rem}}
  .trend-row{{display:grid;grid-template-columns:1fr;gap:0.8rem;margin-top:0.8rem}}
  .trend-cell{{background:var(--surface);border:1px solid var(--border-light);
              border-radius:8px;padding:0.6rem;display:flex;justify-content:center}}
  .trend-chart{{display:block;max-width:100%}}
  .trend-placeholder{{color:var(--text-faint);font-size:0.8rem;padding:1rem}}
  .delta-good{{color:var(--green);font-weight:700}}
  .delta-bad{{color:var(--red);font-weight:700}}
  .delta-neutral{{color:var(--text-faint)}}
  .delta-table tr.perf-row td{{background:var(--border-light);font-size:0.8rem}}

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
  <div class="subtitle">{header_subtitle}</div>
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

{perf_section_html}

{delta_section}

{trend_section}

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


def _run_presidio_comparison(
    runs: list[RunResult],
    sprint: int,
    samples_per_col: int,
    mapping_mode: str,
) -> None:
    """Run Presidio on the same 4 configurations and print a side-by-side
    comparison plus a disagreements JSONL file under ``docs/benchmarks/``.

    Fails loudly with an actionable error if ``presidio-analyzer`` is not
    installed — this mode is explicitly opt-in via ``--compare presidio``.
    """
    import json

    from tests.benchmarks.comparators.presidio_comparator import (
        compute_corpus_metrics,
        format_side_by_side_table,
        run_presidio_on_corpus,
    )

    configs = [
        ("nemotron", False),
        ("nemotron", True),
        ("ai4privacy", False),
        ("ai4privacy", True),
    ]

    print(f"\nRunning Presidio comparator ({mapping_mode} mapping)...", file=sys.stderr)

    dc_rows: list[tuple[str, str, float, float, float]] = []
    pr_rows: list[tuple[str, str, float, float, float]] = []
    all_disagreements: list[dict] = []

    for run, (corpus_name, blind) in zip(runs, configs, strict=True):
        mode = "blind" if blind else "named"
        corpus = load_corpus(corpus_name, max_rows=samples_per_col, blind=blind)

        # Build data_classifier predictions from the existing RunResult
        # by replaying ground truth alignment.
        from tests.benchmarks.accuracy_benchmark import run_benchmark as _rb

        dc_column_results, _ = _rb(corpus, corpus_source=corpus_name)
        dc_predictions: dict[str, list[str]] = {
            cr.column_id: list(cr.predicted_entity_types) for cr in dc_column_results
        }

        # Run Presidio on the same corpus
        presidio_predictions = run_presidio_on_corpus(corpus, mode=mapping_mode)

        comparator_result = compute_corpus_metrics(
            corpus,
            dc_predictions,
            presidio_predictions,
            corpus_name=corpus_name,
            blind=blind,
            mapping_mode=mapping_mode,
        )

        dc_rows.append((corpus_name, mode, run.precision, run.recall, run.macro_f1))
        pr_rows.append(
            (
                corpus_name,
                mode,
                comparator_result.precision,
                comparator_result.recall,
                comparator_result.macro_f1,
            )
        )
        for d in comparator_result.disagreements:
            all_disagreements.append(
                {
                    "corpus": corpus_name,
                    "mode": mode,
                    "column_id": d.column_id,
                    "expected": d.expected,
                    "data_classifier": d.data_classifier_types,
                    "presidio": d.presidio_types,
                    "agreement": d.agreement,
                }
            )

    table = format_side_by_side_table(dc_rows, pr_rows, comparator_name="Presidio")
    print(f"\n{table}", file=sys.stderr)

    # Write disagreement JSONL
    out_path = Path(f"docs/benchmarks/SPRINT{sprint}_PRESIDIO_DISAGREEMENTS.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for record in all_disagreements:
            fh.write(json.dumps(record) + "\n")
    print(
        f"Disagreements: {out_path} ({len(all_disagreements)} records)",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate consolidated sprint benchmark report")
    parser.add_argument("--sprint", type=int, required=True, help="Sprint number")
    parser.add_argument("--samples", type=int, default=50, help="Samples per column (default: 50)")
    parser.add_argument("--output", type=str, default=None, help="Output HTML path")
    parser.add_argument(
        "--from-history",
        action="store_true",
        help="Skip live benchmark runs and assemble the report directly from "
        "docs/benchmarks/history/sprint_N.json. Used to retro-fit sprints "
        "whose raw logs were committed after-the-fact (e.g. Sprint 8).",
    )
    parser.add_argument(
        "--compare",
        choices=["presidio"],
        default=None,
        help="Run an external comparator side-by-side (requires the corresponding optional extra)",
    )
    parser.add_argument(
        "--compare-mode",
        choices=["strict", "aggressive"],
        default="strict",
        help="Entity mapping mode for the comparator (default: strict)",
    )
    args = parser.parse_args()

    perf_section_html = ""
    subtitle: str | None = None
    if args.from_history:
        snapshot, raw = _load_history_snapshot(args.sprint)
        runs = _runs_from_snapshot(snapshot)
        print(
            f"Loaded sprint {args.sprint} from history ({len(runs)} configs, "
            f"perf={'present' if raw.get('perf') else 'absent'})",
            file=sys.stderr,
        )
        perf_section_html = _render_sprint8_perf_section(raw, args.sprint)
        subtitle = "Retro-fit from history artifact (accuracy + perf snapshot) &mdash; no live benchmark runs"
        # DO NOT overwrite the history file when loading from it — this path is
        # read-only, otherwise we'd clobber the ad-hoc schema with a canonical
        # round-trip that loses the per-engine breakdowns.
    else:
        runs = run_all(args.sprint, samples_per_col=args.samples)

        # Build + persist versioned history snapshot
        snapshot = build_sprint_benchmark(args.sprint, runs)
        saved_path = save_sprint_benchmark(snapshot)
        print(f"History snapshot: {saved_path}", file=sys.stderr)

    # Load prior sprints + compute deltas (always, for trend charts)
    history = load_recent_sprints(max_count=5)
    previous = None
    for sb in reversed(history):
        if sb.sprint != snapshot.sprint:
            previous = sb
            break
    delta = compute_delta(snapshot, previous)

    html = generate_consolidated_html(
        args.sprint,
        runs,
        history=history,
        current_snapshot=snapshot,
        delta=delta,
        perf_section_html=perf_section_html,
        subtitle=subtitle,
    )

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

    # External comparator (Sprint 7 --compare flag)
    if args.compare == "presidio":
        if args.from_history:
            print(
                "Skipping --compare presidio: incompatible with --from-history (needs live corpus access).",
                file=sys.stderr,
            )
        else:
            _run_presidio_comparison(
                runs,
                args.sprint,
                samples_per_col=args.samples,
                mapping_mode=args.compare_mode,
            )


if __name__ == "__main__":
    main()
