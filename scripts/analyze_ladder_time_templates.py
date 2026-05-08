from __future__ import annotations

import ast
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "artifacts" / "rust_apex_recenter_live_eval" / "summary.tsv"
OUT_DIR = ROOT / "artifacts" / "ladder_time_templates_2026-05-04"

LADDER_SIZES = {
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
}


def parse_list(value: object) -> list[int]:
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    parsed = ast.literal_eval(text)
    if not isinstance(parsed, list):
        return []
    return [int(round(float(item))) for item in parsed]


def source_group(raw_path: str) -> str:
    path = str(raw_path)
    if "/29_04/" in path:
        return "2026_04_29"
    for token in path.split("/"):
        if token.startswith("2025_"):
            return token[:10]
    return "unknown"


def summarize(values: pd.Series) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {
        "count": int(arr.size),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "p01": float(np.percentile(arr, 1)),
        "p05": float(np.percentile(arr, 5)),
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "median": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(np.max(arr)),
    }


def trusted_mask(df: pd.DataFrame) -> pd.Series:
    expected = df["ladder"].map(lambda ladder: len(LADDER_SIZES.get(str(ladder), [])))
    selected_ok = df["selected_count"].astype(int) == expected
    return (
        df["ok"].astype(str).eq("True")
        & df["review"].astype(str).eq("False")
        & selected_ok
        & (pd.to_numeric(df["linear_max"], errors="coerce") <= 6.0)
        & (pd.to_numeric(df["linear_mean"], errors="coerce") <= 3.0)
        & (pd.to_numeric(df["linear_r2"], errors="coerce") >= 0.999)
    )


def build_detail_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    step_rows: list[dict] = []
    gap_rows: list[dict] = []
    for row in df.itertuples(index=False):
        sizes = LADDER_SIZES[str(row.ladder)]
        scans = list(row.selected_list)
        if len(scans) != len(sizes):
            continue
        for index, (bp, scan) in enumerate(zip(sizes, scans), start=1):
            step_rows.append(
                {
                    "file": row.file,
                    "raw_path": row.raw_path,
                    "source_group": row.source_group,
                    "ladder": row.ladder,
                    "step": index,
                    "bp": bp,
                    "scan": scan,
                    "linear_max": row.linear_max,
                    "linear_mean": row.linear_mean,
                    "linear_r2": row.linear_r2,
                }
            )
        for index in range(len(sizes) - 1):
            gap_rows.append(
                {
                    "file": row.file,
                    "raw_path": row.raw_path,
                    "source_group": row.source_group,
                    "ladder": row.ladder,
                    "step_from": index + 1,
                    "step_to": index + 2,
                    "bp_from": sizes[index],
                    "bp_to": sizes[index + 1],
                    "bp_delta": sizes[index + 1] - sizes[index],
                    "scan_from": scans[index],
                    "scan_to": scans[index + 1],
                    "gap_scan": scans[index + 1] - scans[index],
                }
            )
    return pd.DataFrame(step_rows), pd.DataFrame(gap_rows)


def aggregate_steps(step_df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for key, group in step_df.groupby(group_cols, sort=True):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key_tuple))
        row.update(summarize(group["scan"]))
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_gaps(gap_df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for key, group in gap_df.groupby(group_cols, sort=True):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key_tuple))
        row.update(summarize(group["gap_scan"]))
        rows.append(row)
    return pd.DataFrame(rows)


def plot_ladder_templates(step_stats: pd.DataFrame, gap_stats: pd.DataFrame, ladder: str) -> None:
    steps = step_stats[step_stats["ladder"] == ladder].sort_values("step")
    gaps = gap_stats[gap_stats["ladder"] == ladder].sort_values("step_from")
    if steps.empty or gaps.empty:
        return

    fig, axes = plt.subplots(2, 1, figsize=(13, 9), dpi=170)
    ax = axes[0]
    x = steps["bp"].to_numpy(dtype=float)
    ax.fill_between(x, steps["p10"], steps["p90"], color="#d8e6ef", alpha=0.9, label="p10-p90")
    ax.fill_between(x, steps["p05"], steps["p95"], color="#eff5f8", alpha=0.9, label="p05-p95")
    ax.plot(x, steps["median"], color="#16324f", linewidth=2.5, label="median")
    ax.scatter(x, steps["median"], color="#16324f", s=24)
    for _, row in steps.iterrows():
        ax.text(row["bp"], row["median"] + 18, str(int(row["bp"])), fontsize=7, ha="center")
    ax.set_title(f"{ladder} trusted scan template")
    ax.set_xlabel("bp")
    ax.set_ylabel("scan")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left")

    ax = axes[1]
    labels = [f"{int(a)}-{int(b)}" for a, b in zip(gaps["bp_from"], gaps["bp_to"])]
    pos = np.arange(len(labels))
    ax.fill_between(pos, gaps["p10"], gaps["p90"], color="#f3dec5", alpha=0.9, label="p10-p90")
    ax.plot(pos, gaps["median"], color="#8a4b08", linewidth=2.3, label="median gap")
    ax.set_xticks(pos)
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=8)
    ax.set_title(f"{ladder} trusted gap template")
    ax.set_xlabel("adjacent bp")
    ax.set_ylabel("scan gap")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(OUT_DIR / f"{ladder}_time_gap_template.png")
    plt.close(fig)


def review_deviation_rows(review_df: pd.DataFrame, step_stats: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    medians = {
        (row.ladder, int(row.step)): float(row.median)
        for row in step_stats.itertuples(index=False)
    }
    for row in review_df.itertuples(index=False):
        sizes = LADDER_SIZES.get(str(row.ladder), [])
        scans = list(row.selected_list)
        if len(scans) != len(sizes):
            continue
        deviations = [
            abs(float(scan) - medians.get((row.ladder, index), float(scan)))
            for index, scan in enumerate(scans, start=1)
        ]
        rows.append(
            {
                "file": row.file,
                "raw_path": row.raw_path,
                "ladder": row.ladder,
                "linear_max": row.linear_max,
                "linear_mean": row.linear_mean,
                "linear_r2": row.linear_r2,
                "max_template_deviation_scan": max(deviations) if deviations else np.nan,
                "mean_template_deviation_scan": float(np.mean(deviations)) if deviations else np.nan,
                "largest_deviation_step": int(np.argmax(deviations) + 1) if deviations else None,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SUMMARY_PATH, sep="\t")
    df = df[df["ladder"].isin(LADDER_SIZES)].copy()
    df["selected_list"] = df["selected"].map(parse_list)
    df["source_group"] = df["raw_path"].map(source_group)
    df["linear_max"] = pd.to_numeric(df["linear_max"], errors="coerce")
    df["linear_mean"] = pd.to_numeric(df["linear_mean"], errors="coerce")
    df["linear_r2"] = pd.to_numeric(df["linear_r2"], errors="coerce")
    df["selected_count"] = pd.to_numeric(df["selected_count"], errors="coerce").fillna(0).astype(int)

    trusted = df[trusted_mask(df)].copy()
    step_df, gap_df = build_detail_rows(trusted)
    step_stats = aggregate_steps(step_df, ["ladder", "step", "bp"])
    gap_stats = aggregate_gaps(gap_df, ["ladder", "step_from", "step_to", "bp_from", "bp_to", "bp_delta"])
    source_step_stats = aggregate_steps(step_df, ["source_group", "ladder", "step", "bp"])
    source_gap_stats = aggregate_gaps(gap_df, ["source_group", "ladder", "step_from", "step_to", "bp_from", "bp_to", "bp_delta"])

    review_df = df[df["review"].astype(str).eq("True")].copy()
    review_dev = review_deviation_rows(review_df, step_stats)

    trusted.to_csv(OUT_DIR / "trusted_cases.tsv", sep="\t", index=False)
    step_df.to_csv(OUT_DIR / "bp_scan_detail.tsv", sep="\t", index=False)
    gap_df.to_csv(OUT_DIR / "gap_detail.tsv", sep="\t", index=False)
    step_stats.to_csv(OUT_DIR / "bp_scan_stats.tsv", sep="\t", index=False)
    gap_stats.to_csv(OUT_DIR / "gap_stats.tsv", sep="\t", index=False)
    source_step_stats.to_csv(OUT_DIR / "source_bp_scan_stats.tsv", sep="\t", index=False)
    source_gap_stats.to_csv(OUT_DIR / "source_gap_stats.tsv", sep="\t", index=False)
    review_dev.to_csv(OUT_DIR / "review_template_deviation.tsv", sep="\t", index=False)

    for ladder in LADDER_SIZES:
        plot_ladder_templates(step_stats, gap_stats, ladder)

    manifest = {
        "input": str(SUMMARY_PATH),
        "total_cases": int(len(df)),
        "trusted_cases": int(len(trusted)),
        "trusted_by_ladder": trusted["ladder"].value_counts().to_dict(),
        "review_cases": int(len(review_df)),
        "criteria": {
            "ok": True,
            "review": False,
            "complete_selected_count": True,
            "linear_max_lte": 6.0,
            "linear_mean_lte": 3.0,
            "linear_r2_gte": 0.999,
        },
        "outputs": [
            "bp_scan_stats.tsv",
            "gap_stats.tsv",
            "source_bp_scan_stats.tsv",
            "source_gap_stats.tsv",
            "review_template_deviation.tsv",
            "LIZ500_250_time_gap_template.png",
            "ROX400HD_time_gap_template.png",
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
