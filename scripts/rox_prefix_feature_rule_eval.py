from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402
from scripts.rox_start_prefix_diagnostics import (  # noqa: E402
    ROX_SIZES,
    linear_metrics,
    manual_adjustment_times,
    pair_rows_for_case,
    peak_by_index,
    selected_scans,
    unwrap_response,
)


DEFAULT_BROAD_DIR = ROOT / "artifacts" / "broad_live_ladder_learning_overnight_9000_2026-05-06"
DEFAULT_MANIFEST = ROOT / "artifacts" / "ladder_learning_manifest" / "current_manifest.tsv"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "rox_prefix_feature_rule_eval_2026-05-06"


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_float(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def parse_pair(value: object) -> tuple[int, int] | None:
    raw = str(value or "").strip()
    if not raw or "," not in raw:
        return None
    try:
        left, right = raw.split(",", 1)
        return int(left), int(right)
    except ValueError:
        return None


def pair_distance(pair: tuple[int, int] | None, manual: list[int]) -> float:
    if pair is None or len(manual) < 2:
        return float("nan")
    return float(abs(pair[0] - manual[0]) + abs(pair[1] - manual[1]))


def load_manifest(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    keep = [
        "file",
        "full_path",
        "assay",
        "ladder",
        "source_group",
        "expected_use",
        "learning_category",
        "review_label",
        "tags",
        "review_note",
        "has_manual_adjustment",
    ]
    df = pd.read_csv(path, sep="\t")
    keep = [col for col in keep if col in df.columns]
    return df[keep].drop_duplicates(subset=["file"], keep="first")


def choose_cases(broad_dir: Path, manifest_path: Path, controls: int) -> pd.DataFrame:
    live = pd.read_csv(broad_dir / "live_summary.tsv", sep="\t")
    for col in ["linear_max", "linear_mean", "linear_r2"]:
        live[col] = pd.to_numeric(live[col], errors="coerce")
    for col in ["review", "soft_fail", "severe_fail"]:
        live[col] = live[col].map(parse_bool)
    live = live[live["ladder"].eq("ROX400HD")].copy()
    live["eval_role"] = "broad_target"
    targets = live[live["review"] | live["soft_fail"] | live["severe_fail"]].copy()

    trusted = live[(~live["review"]) & (~live["soft_fail"]) & (live["linear_max"] <= 5.0)].copy()
    trusted = trusted.sort_values(["source_group", "linear_max", "file"])
    if len(trusted) > controls:
        positions = pd.Series(range(controls)).map(
            lambda idx: round(idx * (len(trusted) - 1) / max(controls - 1, 1))
        )
        trusted = trusted.iloc[positions.to_numpy(dtype=int)].copy()
    trusted["eval_role"] = "trusted_control"

    manifest = load_manifest(manifest_path)
    manual = pd.DataFrame()
    if not manifest.empty:
        manual = manifest[
            manifest.get("ladder", "ROX400HD").eq("ROX400HD")
            if "ladder" in manifest.columns
            else manifest["file"].astype(str).str.contains("FR|TRB|TCRb|SL|DHJH", case=False, regex=True)
        ].copy()
        manual = manual[manual["expected_use"].eq("training_pair") & manual["has_manual_adjustment"].astype(str).str.lower().isin(["true", "1"])]
        if "full_path" in manual.columns:
            manual = manual.rename(columns={"full_path": "raw_path"})
            manual = manual[manual["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
            manual["eval_role"] = "manual_training_pair"
            manual["ladder"] = "ROX400HD"
            manual["source_group"] = manual.get("source_group", "")
            manual["assay"] = manual.get("assay", "")
            manual["review"] = ""
            manual["soft_fail"] = ""
            manual["severe_fail"] = ""
            manual["linear_max"] = ""
            manual["linear_mean"] = ""
            manual["linear_r2"] = ""

    rows = pd.concat([targets, trusted, manual], ignore_index=True, sort=False)
    rows = rows[rows["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
    rows = rows.drop_duplicates(subset=["raw_path", "eval_role"], keep="first")
    if not manifest.empty:
        rows = rows.merge(manifest.drop(columns=[col for col in ["full_path"] if col in manifest.columns]), on="file", how="left", suffixes=("", "_manifest"))
    return rows


def analyze_path(raw_path: Path, timeout: int) -> dict[str, Any]:
    worker = _get_rust_worker()
    if worker is None:
        return {"ok": False, "error": "Rust worker unavailable"}
    response = worker.request(raw_path, "clonality", timeout)
    result, error = unwrap_response(response)
    if error and "timeout" in error.lower():
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is not None:
            response = worker.request(raw_path, "clonality", max(timeout * 2, 120))
            result, error = unwrap_response(response)
    if error:
        return {"ok": False, "error": error}
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    return {
        "ok": True,
        "result": result,
        "selected": selected_scans(preview),
        "linear_max": parse_float(metrics.get("linear_trend_max_abs_error_bp")),
        "linear_mean": parse_float(metrics.get("linear_trend_mean_abs_error_bp")),
        "linear_r2": parse_float(metrics.get("linear_trend_r2")),
        "review": bool(review.get("suggested_review")),
        "primary_reason": str(review.get("primary_reason") or ""),
    }


def choose_feature_pair(pair_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pair_rows:
        return None
    df = pd.DataFrame(pair_rows)
    for col in ["linear_max", "linear_mean", "linear_r2", "feature_penalty", "rank_by_feature"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    acceptable = df[
        df["linear_max"].le(7.20)
        & df["linear_mean"].le(3.35)
        & df["linear_r2"].ge(0.99875)
        & df["feature_penalty"].le(1.20)
    ].copy()
    if acceptable.empty:
        return None
    acceptable = acceptable.sort_values(["rank_by_feature", "linear_max", "linear_mean", "feature_penalty"])
    return acceptable.iloc[0].to_dict()


def evaluate_case(row: pd.Series, timeout: int) -> dict[str, Any]:
    raw_path = Path(str(row.raw_path))
    analysis = analyze_path(raw_path, timeout)
    base: dict[str, Any] = {
        "file": raw_path.name,
        "raw_path": str(raw_path),
        "eval_role": row.eval_role,
        "expected_use": getattr(row, "expected_use", getattr(row, "expected_use_manifest", "")),
        "learning_category": getattr(row, "learning_category", getattr(row, "learning_category_manifest", "")),
        "review_label": getattr(row, "review_label", getattr(row, "review_label_manifest", "")),
        "tags": getattr(row, "tags", getattr(row, "tags_manifest", "")),
        "review_note": getattr(row, "review_note", getattr(row, "review_note_manifest", "")),
    }
    if not analysis.get("ok"):
        base.update({"status": "rust_error", "error": analysis.get("error", "")})
        return base
    result = analysis["result"]
    if str(result.get("ladder") or "") != "ROX400HD":
        base.update({"status": "not_rox", "detected_ladder": result.get("ladder", "")})
        return base

    selected = analysis["selected"]
    peaks = peak_by_index(result.get("ladder_peak_preview") or [])
    manual = manual_adjustment_times(raw_path)
    pair_rows = pair_rows_for_case(raw_path.name, selected, manual, peaks)
    feature = choose_feature_pair(pair_rows)
    current_pair = tuple(selected[:2]) if len(selected) >= 2 else None
    feature_pair = None
    if feature:
        feature_pair = (int(feature["first_scan"]), int(feature["second_scan"]))
    changed = bool(feature_pair and current_pair and feature_pair != current_pair)
    current_dist = pair_distance(current_pair, manual)
    feature_dist = pair_distance(feature_pair, manual)
    manual_available = len(manual) >= 2
    manual_closer = bool(manual_available and math.isfinite(feature_dist) and feature_dist < current_dist)
    current_problem = bool(
        analysis["review"]
        or analysis["linear_max"] > 6.0
        or analysis["linear_mean"] > 3.0
        or (manual_available and current_dist > 8)
    )
    if feature is None:
        status = "no_acceptable_feature_pair"
    elif not changed:
        status = "same_as_current"
    elif row.eval_role == "trusted_control" and not current_problem:
        status = "control_would_change"
    elif manual_available and manual_closer:
        status = "manual_closer_feature_pair"
    elif current_problem:
        status = "would_change_problem_case"
    else:
        status = "not_triggered"

    lmax, lmean, r2 = linear_metrics(list(feature_pair) + selected[2:], ROX_SIZES) if feature_pair and len(selected) == len(ROX_SIZES) else (float("nan"), float("nan"), float("nan"))
    base.update(
        {
            "status": status,
            "current_problem": current_problem,
            "current_review": analysis["review"],
            "current_primary_reason": analysis["primary_reason"],
            "current_linear_max": analysis["linear_max"],
            "current_linear_mean": analysis["linear_mean"],
            "current_linear_r2": analysis["linear_r2"],
            "candidate_count": len(peaks),
            "pair_candidate_count": len(pair_rows),
            "current_pair": "" if current_pair is None else f"{current_pair[0]},{current_pair[1]}",
            "feature_pair": "" if feature_pair is None else f"{feature_pair[0]},{feature_pair[1]}",
            "manual_pair": "" if len(manual) < 2 else f"{manual[0]},{manual[1]}",
            "feature_pair_label": "" if feature is None else feature.get("pair_label", ""),
            "feature_pair_qc": "" if feature is None else f"{lmax:.3f}/{lmean:.3f}/{r2:.6f}",
            "feature_pair_rank": "" if feature is None else feature.get("rank_by_feature", ""),
            "feature_pair_linear_rank": "" if feature is None else feature.get("rank_by_linear", ""),
            "current_manual_pair_delta": current_dist,
            "feature_manual_pair_delta": feature_dist,
            "manual_closer": manual_closer,
            "selected": json.dumps(selected, separators=(",", ":")),
            "manual": json.dumps(manual, separators=(",", ":")) if manual else "",
        }
    )
    return base


def run(args: argparse.Namespace) -> None:
    broad_dir = args.broad_dir if args.broad_dir.is_absolute() else ROOT / args.broad_dir
    manifest = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = choose_cases(broad_dir, manifest, args.controls)
    cases.to_csv(out_dir / "selected_cases.tsv", sep="\t", index=False)
    rows = []
    for idx, row in enumerate(cases.itertuples(index=False), start=1):
        result = evaluate_case(row, args.timeout)
        rows.append(result)
        print(f"{idx}/{len(cases)} {result.get('file')}: {result.get('status')}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "prefix_feature_eval.tsv", sep="\t", index=False)
    summary = {
        "cases": int(len(df)),
        "status_counts": df["status"].value_counts(dropna=False).to_dict(),
        "manual_cases": int(df["manual_pair"].astype(str).ne("").sum()) if "manual_pair" in df else 0,
        "manual_closer": int(df.get("manual_closer", pd.Series(dtype=bool)).eq(True).sum()),
        "control_would_change": int(df["status"].eq("control_would_change").sum()),
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# ROX Prefix Feature Rule Eval", "", f"- cases: {summary['cases']}"]
    lines.append(f"- manual cases: {summary['manual_cases']}")
    lines.append(f"- manual-closer feature pairs: {summary['manual_closer']}")
    lines.append(f"- trusted controls that would change without trigger: {summary['control_would_change']}")
    lines.extend(["", "## Status Counts"])
    for key, count in summary["status_counts"].items():
        lines.append(f"- {key}: {count}")
    focus = df[df["status"].isin(["manual_closer_feature_pair", "control_would_change", "would_change_problem_case"])]
    if not focus.empty:
        lines.extend(["", "## Focus Rows"])
        for item in focus.itertuples(index=False):
            lines.append(
                f"- {item.file}: {item.status}; current {item.current_pair}; feature {item.feature_pair}; "
                f"manual {item.manual_pair}; qc {item.feature_pair_qc}"
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "- Feature-rank is promising for ROX prefix, but must be gated to problem/manual-learning cases.",
            "- Do not use it as a global start-pair replacement.",
        ]
    )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broad-dir", type=Path, default=DEFAULT_BROAD_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--controls", type=int, default=220)
    parser.add_argument("--timeout", type=int, default=90)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
