from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.evaluate_rust_apex_recenter_live as live_eval
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker


OUT_DIR = ROOT / "artifacts" / "current_review_soft_panel_2026-05-04"
IMAGE_DIR = OUT_DIR / "images"


def to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def load_227_rows() -> pd.DataFrame:
    path = ROOT / "artifacts" / "rust_apex_recenter_live_eval" / "summary.tsv"
    df = pd.read_csv(path, sep="\t")
    df["source_panel"] = "live_227"
    return df


def load_worst200_rows() -> pd.DataFrame:
    path = ROOT / "artifacts" / "broad_cli_live_worst200_2026-05-04" / "parsed_live_summary_liz_template_only.tsv"
    df = pd.read_csv(path, sep="\t")
    lookup_path = ROOT / "artifacts" / "historical_ladder_qc_overview_2026-05-04" / "all_rows.tsv"
    lookup = pd.read_csv(lookup_path, sep="\t", usecols=["raw_file", "raw_path", "source_group", "Assay"])
    lookup = lookup.drop_duplicates(subset=["raw_file"], keep="first")
    df = df.merge(lookup, left_on="file", right_on="raw_file", how="left")
    df["source_panel"] = "worst200"
    return df


def choose_rows(max_rows: int = 24) -> pd.DataFrame:
    rows = pd.concat([load_227_rows(), load_worst200_rows()], ignore_index=True, sort=False)
    for col in ["linear_max", "linear_mean", "linear_r2"]:
        rows[col] = pd.to_numeric(rows[col], errors="coerce")
    rows["review_bool"] = rows["review"].map(to_bool)
    rows["soft_review_like"] = (
        rows["review_bool"]
        | rows["linear_max"].gt(6.0)
        | rows["linear_mean"].gt(3.0)
        | rows["linear_r2"].lt(0.999)
    )
    rows = rows[rows["soft_review_like"] & rows["raw_path"].notna()].copy()
    rows = rows[rows["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
    rows["priority"] = (
        rows["review_bool"].astype(int) * 100.0
        + rows["linear_max"].fillna(0.0)
        + rows["linear_mean"].fillna(0.0) * 0.5
        + (0.999 - rows["linear_r2"].fillna(0.999)).clip(lower=0.0) * 1000.0
    )
    rows = rows.sort_values(["priority", "linear_max"], ascending=[False, False])
    rows = rows.drop_duplicates(subset=["raw_path"], keep="first")

    # Keep both ladders represented; fill remaining by priority.
    chosen_parts = []
    for ladder in ["LIZ500_250", "ROX400HD"]:
        ladder_rows = rows[rows["ladder"] == ladder].head(max_rows // 2)
        chosen_parts.append(ladder_rows)
    chosen = pd.concat(chosen_parts, ignore_index=True)
    if len(chosen) < max_rows:
        remaining = rows[~rows["raw_path"].isin(set(chosen["raw_path"]))].head(max_rows - len(chosen))
        chosen = pd.concat([chosen, remaining], ignore_index=True)
    return chosen.head(max_rows).copy()


def render_panel(rows: pd.DataFrame) -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    live_eval.IMAGE_DIR = IMAGE_DIR

    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker not available")

    rendered = []
    for row in rows.itertuples(index=False):
        raw_path = Path(str(row.raw_path))
        analysis = live_eval.analyze_path(worker, raw_path)
        if analysis.get("error", "").startswith("worker timeout"):
            _invalidate_rust_worker()
            worker = _get_rust_worker()
            if worker is None:
                raise SystemExit("Rust worker not available after timeout")
            analysis = live_eval.analyze_path(worker, raw_path)
        image = live_eval.render_image(analysis) if analysis.get("ok") else None
        rendered.append(
            {
                "file": raw_path.name,
                "raw_path": str(raw_path),
                "source_panel": getattr(row, "source_panel", ""),
                "ladder": analysis.get("ladder", getattr(row, "ladder", "")),
                "linear_max": analysis.get("linear_max", getattr(row, "linear_max", "")),
                "linear_mean": analysis.get("linear_mean", getattr(row, "linear_mean", "")),
                "linear_r2": analysis.get("linear_r2", getattr(row, "linear_r2", "")),
                "review": analysis.get("review", getattr(row, "review_bool", "")),
                "primary_reason": analysis.get("primary_reason", getattr(row, "primary_reason", "")),
                "reason_codes": analysis.get("reason_codes", getattr(row, "reason_codes", "")),
                "selected": analysis.get("selected", getattr(row, "selected", "")),
                "image": image or "",
            }
        )

    out_df = pd.DataFrame(rendered)
    out_df.to_csv(OUT_DIR / "panel_summary.tsv", sep="\t", index=False)
    with (OUT_DIR / "image_index.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "image"], delimiter="\t")
        writer.writeheader()
        for row in rendered:
            if row["image"]:
                writer.writerow({"file": row["file"], "image": row["image"]})
    return out_df


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = choose_rows(max_rows=24)
    rows.to_csv(OUT_DIR / "selected_for_panel.tsv", sep="\t", index=False)
    rendered = render_panel(rows)
    print(f"selected={len(rows)} rendered={rendered['image'].astype(bool).sum()} out={OUT_DIR}")
    print(
        rendered[["file", "ladder", "linear_max", "linear_mean", "linear_r2", "review", "primary_reason", "image"]]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
