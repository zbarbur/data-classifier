"""Q5 — Feature distribution audit (descriptive statistics).

Loads training_data.jsonl, computes per-corpus distribution statistics for
every meta-classifier feature, ranks features by inter-corpus divergence
(max pairwise KS), and emits histograms + a JSON summary used by result.md.

Run from repo root with the worktree venv:
    .venv/bin/python docs/experiments/meta_classifier/runs/\
2026-04-12-q5-feature-distribution-audit/analyze.py
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[5]
RUN_DIR = Path(__file__).resolve().parent
TRAINING_DATA = REPO / "tests/benchmarks/meta_classifier/training_data.jsonl"

# Mirrored from data_classifier/orchestrator/meta_classifier.py FEATURE_NAMES.
# Read-only copy — research sessions must not import from data_classifier
# in case the production schema is mid-edit on another branch.
FEATURE_NAMES: tuple[str, ...] = (
    "top_overall_confidence",
    "regex_confidence",
    "column_name_confidence",
    "heuristic_confidence",
    "secret_scanner_confidence",
    "engines_agreed",
    "engines_fired",
    "confidence_gap",
    "regex_match_ratio",
    "heuristic_distinct_ratio",
    "heuristic_avg_length",
    "has_column_name_hit",
    "has_secret_indicators",
    "primary_is_pii",
    "primary_is_credential",
)


def load() -> pd.DataFrame:
    rows = []
    with TRAINING_DATA.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    feats = pd.DataFrame(df["features"].tolist(), columns=list(FEATURE_NAMES))
    out = pd.concat([df.drop(columns=["features"]), feats], axis=1)
    return out


def per_corpus_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Long-form table: feature × corpus → mean/std/min/max/median/n."""
    rows = []
    for feat in FEATURE_NAMES:
        for corpus, group in df.groupby("corpus"):
            v = group[feat].to_numpy()
            rows.append(
                {
                    "feature": feat,
                    "corpus": corpus,
                    "n": len(v),
                    "mean": float(np.mean(v)),
                    "std": float(np.std(v, ddof=1)) if len(v) > 1 else 0.0,
                    "min": float(np.min(v)),
                    "p10": float(np.percentile(v, 10)),
                    "p25": float(np.percentile(v, 25)),
                    "median": float(np.median(v)),
                    "p75": float(np.percentile(v, 75)),
                    "p90": float(np.percentile(v, 90)),
                    "max": float(np.max(v)),
                }
            )
    return pd.DataFrame(rows)


def f_stat_for_feature(df: pd.DataFrame, feat: str) -> tuple[float, float]:
    groups = [g[feat].to_numpy() for _, g in df.groupby("corpus")]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return float("nan"), float("nan")
    f, p = stats.f_oneway(*groups)
    return float(f), float(p)


def pairwise_ks(df: pd.DataFrame, feat: str) -> list[dict]:
    corpora = sorted(df["corpus"].unique())
    out = []
    for a, b in itertools.combinations(corpora, 2):
        va = df.loc[df["corpus"] == a, feat].to_numpy()
        vb = df.loc[df["corpus"] == b, feat].to_numpy()
        if len(va) < 2 or len(vb) < 2:
            continue
        ks = stats.ks_2samp(va, vb)
        out.append(
            {
                "feature": feat,
                "corpus_a": a,
                "corpus_b": b,
                "ks": float(ks.statistic),
                "p_value": float(ks.pvalue),
            }
        )
    return out


def rank_features(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feat in FEATURE_NAMES:
        ks_records = pairwise_ks(df, feat)
        if not ks_records:
            continue
        max_rec = max(ks_records, key=lambda r: r["ks"])
        f_val, p_val = f_stat_for_feature(df, feat)
        rows.append(
            {
                "feature": feat,
                "max_ks": max_rec["ks"],
                "max_ks_pair": f"{max_rec['corpus_a']} vs {max_rec['corpus_b']}",
                "f_statistic": f_val,
                "f_pvalue": p_val,
            }
        )
    return pd.DataFrame(rows).sort_values("max_ks", ascending=False).reset_index(drop=True)


def plot_top_features(df: pd.DataFrame, top_features: list[str]) -> None:
    corpora = sorted(df["corpus"].unique())
    palette = plt.get_cmap("tab10").colors
    for feat in top_features:
        fig, ax = plt.subplots(figsize=(8, 5))
        # Common bins across all corpora so the overlay is comparable.
        all_vals = df[feat].to_numpy()
        lo, hi = float(np.min(all_vals)), float(np.max(all_vals))
        if lo == hi:
            hi = lo + 1.0
        bins = np.linspace(lo, hi, 31)
        for i, corpus in enumerate(corpora):
            vals = df.loc[df["corpus"] == corpus, feat].to_numpy()
            ax.hist(
                vals,
                bins=bins,
                alpha=0.45,
                label=f"{corpus} (n={len(vals)})",
                color=palette[i % len(palette)],
                density=True,
            )
        ax.set_title(f"{feat} — per-corpus density")
        ax.set_xlabel(feat)
        ax.set_ylabel("density")
        ax.legend(fontsize=8)
        fig.tight_layout()
        out = RUN_DIR / f"hist_{feat}.png"
        fig.savefig(out, dpi=120)
        plt.close(fig)


def main() -> None:
    df = load()
    print(f"loaded {len(df)} rows")
    print("corpora:", df["corpus"].value_counts().to_dict())

    stats_df = per_corpus_stats(df)
    stats_df.to_csv(RUN_DIR / "per_corpus_stats.csv", index=False)

    ranking = rank_features(df)
    ranking.to_csv(RUN_DIR / "feature_ranking.csv", index=False)
    print("\nFeature ranking by max pairwise KS:")
    print(ranking.to_string(index=False))

    # Full pairwise table for the appendix.
    all_pairs: list[dict] = []
    for feat in FEATURE_NAMES:
        all_pairs.extend(pairwise_ks(df, feat))
    pd.DataFrame(all_pairs).to_csv(RUN_DIR / "pairwise_ks.csv", index=False)

    top5 = ranking.head(5)["feature"].tolist()
    plot_top_features(df, top5)

    summary = {
        "n_rows": int(len(df)),
        "corpora": {k: int(v) for k, v in df["corpus"].value_counts().items()},
        "feature_ranking": ranking.to_dict(orient="records"),
        "top5_features": top5,
    }
    (RUN_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote outputs to {RUN_DIR}")


if __name__ == "__main__":
    main()
