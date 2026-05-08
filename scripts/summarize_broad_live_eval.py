from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.known_ladder_cases import has_known_operator_or_bad_data_token
from core.utils import is_water_file


def as_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def classify(row: pd.Series) -> str:
    if not as_bool(row.get("ok", True)):
        return "run_error"
    if has_known_operator_or_bad_data_token(str(row.get("file", ""))):
        return "known_operator_or_bad_data"
    if str(row.get("workbook_qc", "")) == "raw_2026" and as_bool(row.get("review", False)):
        return "raw_2026_review"
    if as_bool(row.get("review", False)):
        return "rust_review"
    if as_bool(row.get("nonlinear_complete_ok", False)):
        return "complete_qc_ok"
    if as_bool(row.get("severe_fail", False)):
        return "severe_qc_watch"
    if as_bool(row.get("soft_fail", False)):
        return "soft_qc_watch"
    return "ok"


def summarize(out_dir: Path) -> dict[str, object]:
    live_path = out_dir / "live_summary.tsv"
    if not live_path.exists():
        partial = out_dir / "live_summary.partial.tsv"
        if not partial.exists():
            raise FileNotFoundError(f"No live_summary.tsv or partial summary found in {out_dir}")
        live_path = partial
    df = pd.read_csv(live_path, sep="\t")
    if df.empty:
        raise ValueError(f"No rows in {live_path}")

    water_mask = df["file"].map(is_water_file) if "file" in df else pd.Series(False, index=df.index)
    water_excluded = df[water_mask].copy()
    water_excluded_path = out_dir / "water_excluded.tsv"
    water_excluded.to_csv(water_excluded_path, sep="\t", index=False)
    df = df[~water_mask].copy()

    for column in ["linear_max", "linear_mean", "linear_r2", "quadratic_max", "quadratic_mean", "quadratic_r2"]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df["morning_class"] = df.apply(classify, axis=1)

    out_dir.mkdir(parents=True, exist_ok=True)
    classified_path = out_dir / "live_summary_classified.tsv"
    df.to_csv(classified_path, sep="\t", index=False)

    active = df[~df["morning_class"].isin({"ok", "complete_qc_ok"})].copy()
    active = active.sort_values(["morning_class", "review", "severe_fail", "linear_max"], ascending=[True, False, False, False])
    active_path = out_dir / "morning_active_watchlist.tsv"
    active.to_csv(active_path, sep="\t", index=False)

    by_ladder = df.groupby("ladder", dropna=False).agg(
        n=("file", "size"),
        review=("review", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
        soft_fail=("soft_fail", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
        severe_fail=("severe_fail", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
        complete_qc_ok=("nonlinear_complete_ok", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
        p95_linear_max=("linear_max", lambda values: float(pd.to_numeric(values, errors="coerce").quantile(0.95))),
        max_linear_max=("linear_max", "max"),
        mean_linear_mean=("linear_mean", "mean"),
    )
    by_ladder_path = out_dir / "morning_summary_by_ladder.tsv"
    by_ladder.reset_index().to_csv(by_ladder_path, sep="\t", index=False)

    class_counts = df["morning_class"].value_counts().to_dict()
    summary = {
        "source": str(live_path),
        "rows": int(len(df)),
        "water_excluded": int(len(water_excluded)),
        "ok_rows": int(df["ok"].astype(str).str.lower().eq("true").sum()) if "ok" in df else int(len(df)),
        "review": int(df["review"].astype(str).str.lower().eq("true").sum()) if "review" in df else 0,
        "soft_fail": int(df["soft_fail"].astype(str).str.lower().eq("true").sum()) if "soft_fail" in df else 0,
        "severe_fail": int(df["severe_fail"].astype(str).str.lower().eq("true").sum()) if "severe_fail" in df else 0,
        "complete_qc_ok": int(df["nonlinear_complete_ok"].astype(str).str.lower().eq("true").sum())
        if "nonlinear_complete_ok" in df
        else 0,
        "morning_class_counts": class_counts,
        "classified": str(classified_path),
        "active_watchlist": str(active_path),
        "by_ladder": str(by_ladder_path),
        "water_excluded_path": str(water_excluded_path),
    }
    (out_dir / "morning_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Broad Live Eval Morning Summary",
        "",
        f"Source: `{live_path}`",
        f"Rows: `{summary['rows']}`",
        f"Water excluded: `{summary['water_excluded']}`",
        f"Review: `{summary['review']}`",
        f"Soft fail: `{summary['soft_fail']}`",
        f"Severe fail: `{summary['severe_fail']}`",
        f"Complete-QC-ok: `{summary['complete_qc_ok']}`",
        "",
        "## Morning Classes",
        "",
    ]
    for key, value in sorted(class_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Active Watchlist", ""])
    if active.empty:
        lines.append("- None.")
    else:
        for row in active.head(40).itertuples(index=False):
            lines.append(
                "- "
                f"{getattr(row, 'file')} ({getattr(row, 'ladder')}): {getattr(row, 'morning_class')}, "
                f"linear {as_float(getattr(row, 'linear_max', float('nan'))):.2f}/"
                f"{as_float(getattr(row, 'linear_mean', float('nan'))):.2f}/"
                f"{as_float(getattr(row, 'linear_r2', float('nan'))):.6f}, "
                f"reason `{getattr(row, 'primary_reason', '')}`."
            )
        if len(active) > 40:
            lines.append(f"- ... plus `{len(active) - 40}` more rows in `morning_active_watchlist.tsv`.")
    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- Classified rows: `{classified_path}`",
            f"- Active watchlist: `{active_path}`",
            f"- By-ladder summary: `{by_ladder_path}`",
            f"- Water excluded: `{water_excluded_path}`",
        ]
    )
    (out_dir / "morning_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a compact morning summary from a broad live ladder eval output.")
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.out_dir), indent=2))


if __name__ == "__main__":
    main()
