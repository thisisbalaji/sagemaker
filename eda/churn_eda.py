"""Exploratory data analysis for the churn dataset.

Writes charts, summary.json and report.md to --output. Paths default to the
SageMaker Processing locations so the same script runs locally or as a job:

    python eda/churn_eda.py --input data/raw/churn.csv --output eda/output
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import roc_auc_score

TARGET = "Churn?"
ID_COLUMNS = ["Phone"]
CATEGORICAL = ["State", "Area Code", "Int'l Plan", "VMail Plan"]


def load(input_path):
    path = Path(input_path)
    if path.is_dir():
        files = sorted(path.glob("*.csv"))
        if not files:
            raise FileNotFoundError(f"No CSV files in {path}")
        path = files[0]
    df = pd.read_csv(path)
    df[TARGET] = df[TARGET].astype(str).str.strip(".").map({"True": 1, "False": 0})
    return df


def overview(df):
    return {
        "rows": len(df),
        "columns": df.shape[1],
        "duplicate_rows": int(df.duplicated().sum()),
        "missing_values": {c: int(n) for c, n in df.isna().sum().items() if n},
        "churn_rate": round(df[TARGET].mean(), 4),
        "churn_counts": {str(k): int(v) for k, v in df[TARGET].value_counts().items()},
    }


def numeric_columns(df):
    return [c for c in df.select_dtypes("number").columns if c not in CATEGORICAL + ID_COLUMNS + [TARGET]]


def feature_signal(df, numeric):
    """Univariate ROC AUC per numeric feature (0.5 = no signal; distance from 0.5 = strength)."""
    rows = []
    for col in numeric:
        auc = roc_auc_score(df[TARGET], df[col])
        rows.append({"feature": col, "auc": round(auc, 3), "strength": round(abs(auc - 0.5), 3),
                     "direction": "higher → more churn" if auc > 0.5 else "higher → less churn"})
    return sorted(rows, key=lambda r: r["strength"], reverse=True)


def churn_by_category(df):
    out = {}
    for col in CATEGORICAL:
        g = df.groupby(col)[TARGET].agg(["mean", "count"]).sort_values("mean", ascending=False)
        out[col] = {str(k): {"churn_rate": round(r["mean"], 3), "count": int(r["count"])} for k, r in g.iterrows()}
    return out


def high_correlations(df, numeric, threshold=0.8):
    corr = df[numeric].corr()
    pairs = []
    for i, a in enumerate(numeric):
        for b in numeric[i + 1:]:
            if abs(corr.loc[a, b]) >= threshold:
                pairs.append({"a": a, "b": b, "corr": round(corr.loc[a, b], 3)})
    return corr, pairs


def plot_all(df, numeric, corr, out):
    sns.set_theme(style="whitegrid")
    labels = df[TARGET].map({0: "Stayed", 1: "Churned"})

    fig, ax = plt.subplots(figsize=(5, 4))
    labels.value_counts().plot.bar(ax=ax, color=["#4C78A8", "#E45756"])
    ax.set(title="Target balance", xlabel="", ylabel="Customers")
    fig.tight_layout(); fig.savefig(out / "01_target_balance.png", dpi=120); plt.close(fig)

    cols = 4
    rows = int(np.ceil(len(numeric) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3))
    for ax, col in zip(axes.flat, numeric):
        sns.histplot(x=df[col], hue=labels, ax=ax, bins=30, stat="density", common_norm=False,
                     element="step", palette={"Stayed": "#4C78A8", "Churned": "#E45756"})
        ax.set(title=col, xlabel="", ylabel="")
    for ax in axes.flat[len(numeric):]:
        ax.remove()
    fig.tight_layout(); fig.savefig(out / "02_numeric_by_churn.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(corr, cmap="RdBu_r", center=0, vmin=-1, vmax=1, annot=True, fmt=".2f",
                annot_kws={"size": 7}, ax=ax)
    ax.set_title("Numeric feature correlation")
    fig.tight_layout(); fig.savefig(out / "03_correlation.png", dpi=110); plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for ax, col in zip(axes, ["Int'l Plan", "VMail Plan", "Area Code"]):
        df.groupby(col)[TARGET].mean().plot.bar(ax=ax, color="#E45756")
        ax.set(title=f"Churn rate by {col}", xlabel="", ylabel="Churn rate")
        ax.axhline(df[TARGET].mean(), ls="--", c="gray", lw=1)
    fig.tight_layout(); fig.savefig(out / "04_churn_by_category.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 4))
    df.groupby("State")[TARGET].mean().sort_values(ascending=False).plot.bar(ax=ax, color="#E45756")
    ax.axhline(df[TARGET].mean(), ls="--", c="gray", lw=1)
    ax.set(title="Churn rate by state (dashed = overall)", xlabel="", ylabel="Churn rate")
    fig.tight_layout(); fig.savefig(out / "05_churn_by_state.png", dpi=110); plt.close(fig)


def write_report(summary, out):
    o = summary["overview"]
    lines = [
        "# Churn EDA report", "",
        f"- Rows: {o['rows']}, columns: {o['columns']}",
        f"- Duplicate rows: {o['duplicate_rows']}",
        f"- Missing values: {o['missing_values'] or 'none'}",
        f"- Churn rate: {o['churn_rate']:.1%} ({o['churn_counts']})", "",
        "## Numeric feature signal (univariate AUC)", "",
        "| Feature | AUC | Direction |", "|---|---|---|",
        *[f"| {r['feature']} | {r['auc']} | {r['direction']} |" for r in summary["feature_signal"]], "",
        "## Highly correlated pairs (|r| ≥ 0.8)", "",
        *([f"- {p['a']} ↔ {p['b']}: {p['corr']}" for p in summary["high_correlations"]] or ["- none"]), "",
        "## Churn rate by category", "",
    ]
    for col in ["Int'l Plan", "VMail Plan", "Area Code"]:
        vals = ", ".join(f"{k}: {v['churn_rate']:.1%} (n={v['count']})" for k, v in summary["churn_by_category"][col].items())
        lines.append(f"- **{col}** — {vals}")
    states = summary["churn_by_category"]["State"]
    top = list(states.items())
    lines += [f"- **State** — highest: {', '.join(f'{k} {v['churn_rate']:.0%}' for k, v in top[:3])}; "
              f"lowest: {', '.join(f'{k} {v['churn_rate']:.0%}' for k, v in top[-3:])}", "",
              "## Charts", "",
              *[f"![{p.stem}]({p.name})" for p in sorted(out.glob("*.png"))]]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/opt/ml/processing/input")
    parser.add_argument("--output", default="/opt/ml/processing/output")
    args = parser.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    df = load(args.input)
    numeric = numeric_columns(df)
    corr, pairs = high_correlations(df, numeric)

    summary = {
        "overview": overview(df),
        "feature_signal": feature_signal(df, numeric),
        "high_correlations": pairs,
        "churn_by_category": churn_by_category(df),
        "numeric_describe": df[numeric].describe().round(3).to_dict(),
    }
    plot_all(df, numeric, corr, out)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    write_report(summary, out)
    print(f"Wrote EDA outputs to {out}")


if __name__ == "__main__":
    main()
