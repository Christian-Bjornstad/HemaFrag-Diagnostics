from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "artifacts" / "historical_ladder_qc_overview_2026-05-04"
SAFE_2025_ROOT = Path("/Volumes/T7 Shield/HemaFrag_2025_safe_reruns_2026-04-28")
DATA_2025_ROOT = Path("/Volumes/T7 Shield/DATA/2025_data")
RUN_2026_WORKBOOKS = [
    Path("/Volumes/T7 Shield/29_04/reports_2026-04-29/Clonality_Tracking.xlsx"),
]
PREFIX_RE = re.compile(r"^\d+_[0-9a-f]+_")


def strip_stage_prefix(name: object) -> str:
    return PREFIX_RE.sub("", str(name or ""))


def infer_ladder(assay: object, file_name: object) -> str:
    assay_text = str(assay or "")
    lower = str(file_name or "").lower()
    if assay_text in {"TCRgA", "TCRgB", "IGK", "KDE"} or any(
        key in lower for key in ("tcrg", "trga", "trgb", "igk", "kde")
    ):
        return "LIZ500_250"
    return "ROX400HD"


def load_rows() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for workbook in sorted(SAFE_2025_ROOT.glob("2025_*/reports_2026-04-28/Clonality_Tracking.xlsx")):
        df = pd.read_excel(workbook)
        df["source_group"] = workbook.parts[-3]
        df["raw_file"] = df["File"].map(strip_stage_prefix)
        df["raw_path"] = [
            str(DATA_2025_ROOT / str(run_dir) / str(raw_file))
            for run_dir, raw_file in zip(df["SourceRunDir"], df["raw_file"])
        ]
        frames.append(df)
    for workbook in RUN_2026_WORKBOOKS:
        if not workbook.exists():
            continue
        df = pd.read_excel(workbook)
        run_root = workbook.parent.parent
        df["source_group"] = run_root.name
        df["raw_file"] = df["File"].map(strip_stage_prefix)
        df["raw_path"] = [
            str(run_root / str(run_dir) / str(raw_file))
            for run_dir, raw_file in zip(df["SourceRunDir"], df["raw_file"])
        ]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["ladder2"] = [infer_ladder(a, f) for a, f in zip(df["Assay"], df["raw_file"])]
    for col in ["LadderLinearMaxResidualBp", "LadderLinearMeanResidualBp", "LadderLinearR2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["exists"] = df["raw_path"].map(lambda path: Path(path).exists())
    df["review_like"] = (
        df["LadderQC"].astype(str).ne("ok")
        | df["LadderLinearMaxResidualBp"].gt(6.0)
        | df["LadderLinearMeanResidualBp"].gt(3.0)
        | df["LadderLinearR2"].lt(0.999)
    )
    df["trusted_like"] = (
        df["LadderQC"].astype(str).eq("ok")
        & df["LadderLinearMaxResidualBp"].le(6.0)
        & df["LadderLinearMeanResidualBp"].le(3.0)
        & df["LadderLinearR2"].ge(0.999)
        & df["exists"]
    )
    return df


def summarize_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for key, group in df.groupby(group_cols, sort=True):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key_tuple))
        row.update(
            {
                "n": int(len(group)),
                "exists": int(group["exists"].sum()),
                "ok_qc": int(group["LadderQC"].astype(str).eq("ok").sum()),
                "review_qc": int(group["LadderQC"].astype(str).eq("review_required").sum()),
                "missing_ladder": int(group["LadderQC"].astype(str).eq("missing_ladder").sum()),
                "review_like": int(group["review_like"].sum()),
                "trusted_like": int(group["trusted_like"].sum()),
                "median_linear_max": float(group["LadderLinearMaxResidualBp"].median()),
                "p95_linear_max": float(group["LadderLinearMaxResidualBp"].quantile(0.95)),
                "median_linear_mean": float(group["LadderLinearMeanResidualBp"].median()),
                "p95_linear_mean": float(group["LadderLinearMeanResidualBp"].quantile(0.95)),
                "median_linear_r2": float(group["LadderLinearR2"].median()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def balanced_pick(df: pd.DataFrame, mask: pd.Series, n: int) -> pd.DataFrame:
    sub = df[mask & df["exists"]].copy()
    if sub.empty:
        return sub
    picks: list[pd.DataFrame] = []
    group_count = max(1, sub.groupby(["source_group", "ladder2"]).ngroups)
    per_group = max(1, n // group_count)
    for _, group in sub.groupby(["source_group", "ladder2"], sort=True):
        group = group.sort_values(["LadderLinearMaxResidualBp", "raw_file"], ascending=[False, True], na_position="last")
        count = min(per_group, len(group))
        if count == len(group):
            picks.append(group)
        else:
            idx = np.linspace(0, len(group) - 1, count).round().astype(int)
            picks.append(group.iloc[idx])
    out = pd.concat(picks, ignore_index=True).drop_duplicates(subset=["raw_path"])
    if len(out) < n:
        remaining = sub[~sub["raw_path"].isin(set(out["raw_path"]))].sort_values(
            ["LadderLinearMaxResidualBp", "raw_file"], ascending=[False, True], na_position="last"
        )
        out = pd.concat([out, remaining.head(n - len(out))], ignore_index=True)
    return out.head(n).copy()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_rows()
    df.to_csv(OUT_DIR / "all_rows.tsv", sep="\t", index=False)
    summarize_group(df, ["ladder2"]).to_csv(OUT_DIR / "summary_by_ladder.tsv", sep="\t", index=False)
    summarize_group(df, ["source_group", "ladder2"]).to_csv(OUT_DIR / "summary_by_source_ladder.tsv", sep="\t", index=False)
    summarize_group(df, ["Assay", "ladder2"]).to_csv(OUT_DIR / "summary_by_assay_ladder.tsv", sep="\t", index=False)

    broad_live_seed = pd.concat(
        [
            balanced_pick(df, df["trusted_like"], 500),
            balanced_pick(df, df["review_like"], 500),
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["raw_path"])
    broad_live_seed.to_csv(OUT_DIR / "recommended_live_seed_1000.tsv", sep="\t", index=False)

    worst = df[df["exists"]].sort_values(
        ["review_like", "LadderLinearMaxResidualBp", "LadderLinearMeanResidualBp"],
        ascending=[False, False, False],
        na_position="last",
    )
    worst.head(200).to_csv(OUT_DIR / "worst_200_for_review_or_rerun.tsv", sep="\t", index=False)

    manifest = {
        "rows": int(len(df)),
        "existing_fsa_rows": int(df["exists"].sum()),
        "by_ladder": df["ladder2"].value_counts().to_dict(),
        "trusted_like": int(df["trusted_like"].sum()),
        "review_like": int(df["review_like"].sum()),
        "recommended_live_seed_rows": int(len(broad_live_seed)),
        "outputs": [
            "summary_by_ladder.tsv",
            "summary_by_source_ladder.tsv",
            "summary_by_assay_ladder.tsv",
            "recommended_live_seed_1000.tsv",
            "worst_200_for_review_or_rerun.tsv",
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
