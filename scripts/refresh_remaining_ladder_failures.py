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

import scripts.evaluate_rust_apex_recenter_live as live_eval  # noqa: E402
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402
from scripts.known_ladder_cases import has_known_operator_or_bad_data_token  # noqa: E402
from scripts.rox_start_prefix_diagnostics import selected_scans, unwrap_response  # noqa: E402

DEFAULT_SUMMARIES = [
    ROOT / "artifacts" / "broad_live_ladder_learning_overnight_9000_2026-05-06" / "live_summary.tsv",
    ROOT / "artifacts" / "broad_live_ladder_learning_rox_feature_arbiter_smoke_1000_2026-05-06" / "live_summary.tsv",
]
DEFAULT_OUT_DIR = ROOT / "artifacts" / "remaining_ladder_failures_refresh_2026-05-06"
LADDER_COUNTS = {"LIZ500_250": 16, "ROX400HD": 21}


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_float(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")


def nonlinear_complete_ok(
    ladder: str,
    selected_count: int,
    expected_count: int,
    linear_max: float,
    linear_mean: float,
    linear_r2: float,
    quadratic_max: float,
    quadratic_mean: float,
    quadratic_r2: float,
) -> bool:
    if selected_count != expected_count or expected_count != LADDER_COUNTS.get(ladder, 0):
        return False
    if ladder == "ROX400HD":
        return bool(
            linear_max <= 13.0
            and linear_mean <= 5.7
            and linear_r2 >= 0.9963
            and quadratic_max <= 2.5
            and quadratic_mean <= 1.1
            and quadratic_r2 >= 0.99985
        )
    if ladder == "LIZ500_250":
        return bool(
            linear_max <= 7.2
            and linear_mean <= 3.6
            and linear_r2 >= 0.9993
            and quadratic_max <= 6.0
            and quadratic_mean <= 2.3
            and quadratic_r2 >= 0.9997
        )
    return False


def load_failure_inputs(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            continue
        df = pd.read_csv(path, sep="\t")
        df["source_summary"] = str(path)
        for col in ["ok", "review", "soft_fail", "severe_fail"]:
            if col in df.columns:
                df[col] = df[col].map(parse_bool)
        for col in ["linear_max", "linear_mean", "linear_r2"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    all_rows = pd.concat(frames, ignore_index=True, sort=False)
    for col in ["ok", "review", "soft_fail", "severe_fail"]:
        if col not in all_rows.columns:
            all_rows[col] = False
    failures = all_rows[
        (~all_rows["ok"])
        | all_rows["review"]
        | all_rows["soft_fail"]
        | all_rows["severe_fail"]
    ].copy()
    failures = failures[failures["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
    failures["rank_score"] = (
        failures["severe_fail"].astype(int) * 1000
        + failures["review"].astype(int) * 500
        + failures["soft_fail"].astype(int) * 100
        + pd.to_numeric(failures.get("linear_max"), errors="coerce").fillna(0)
    )
    failures = failures.sort_values(["rank_score", "file"], ascending=[False, True])
    return failures.drop_duplicates(subset=["raw_path"], keep="first").copy()


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
        return {"ok": False, "error": error, "result": {}}
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    selected = selected_scans(preview)
    ladder = str(result.get("ladder") or "")
    linear_max = parse_float(metrics.get("linear_trend_max_abs_error_bp"))
    linear_mean = parse_float(metrics.get("linear_trend_mean_abs_error_bp"))
    linear_r2 = parse_float(metrics.get("linear_trend_r2"))
    quadratic_max = parse_float(metrics.get("quadratic_trend_max_abs_error_bp"))
    quadratic_mean = parse_float(metrics.get("quadratic_trend_mean_abs_error_bp"))
    quadratic_r2 = parse_float(metrics.get("quadratic_trend_r2"))
    expected_count = LADDER_COUNTS.get(ladder, 0)
    nonlinear_ok = nonlinear_complete_ok(
        ladder,
        len(selected),
        expected_count,
        linear_max,
        linear_mean,
        linear_r2,
        quadratic_max,
        quadratic_mean,
        quadratic_r2,
    )
    soft_fail = bool(
        review.get("suggested_review")
        or (
            not nonlinear_ok
            and (linear_max > 6.0 or linear_mean > 3.0 or linear_r2 < 0.999)
        )
    )
    severe_fail = bool(
        review.get("suggested_review")
        or (
            not nonlinear_ok
            and (linear_max > 10.0 or linear_mean > 4.5 or linear_r2 < 0.9985)
        )
    )
    return {
        "ok": True,
        "error": "",
        "result": result,
        "ladder": ladder,
        "channel": result.get("size_standard_channel_guess") or "",
        "candidate_count": len(result.get("ladder_peak_preview") or []),
        "selected_count": len(selected),
        "expected_count": expected_count,
        "nonlinear_complete_ok": nonlinear_ok,
        "selected": selected,
        "linear_max": linear_max,
        "linear_mean": linear_mean,
        "linear_r2": linear_r2,
        "quadratic_max": quadratic_max,
        "quadratic_mean": quadratic_mean,
        "quadratic_r2": quadratic_r2,
        "review": bool(review.get("suggested_review")),
        "primary_reason": str(review.get("primary_reason") or ""),
        "reason_codes": review.get("reason_codes") or [],
        "soft_fail": soft_fail,
        "severe_fail": severe_fail,
    }


def has_known_bad_token(file_name: str) -> bool:
    return has_known_operator_or_bad_data_token(file_name)


def classify(row: dict[str, Any]) -> str:
    file_name = str(row.get("file") or "")
    ladder = str(row.get("ladder") or "")
    selected = row.get("selected") or []
    candidate_count = int(row.get("candidate_count") or 0)
    linear_max = parse_float(row.get("linear_max"))
    linear_mean = parse_float(row.get("linear_mean"))
    reason = " ".join([str(row.get("primary_reason") or ""), *[str(item) for item in row.get("reason_codes") or []]]).lower()

    if not row.get("ok"):
        return "run_error"
    if has_known_bad_token(file_name):
        return "known_operator_or_bad_data"
    if row.get("selected_count") != row.get("expected_count") or "missing" in reason:
        return f"{ladder.lower()}_incomplete_or_missing_ladder"
    if ladder == "LIZ500_250":
        first = selected[0] if selected else 0
        last = selected[-1] if selected else 0
        if first > 1650:
            return "liz_late_start_blob_or_shift"
        if last > 4400:
            return "liz_late_tail_490_500"
        if candidate_count > 45 and linear_mean > 3.0:
            return "liz_blob_baseline_many_candidates"
        if linear_max > 10.0 or linear_mean > 4.5:
            return "liz_major_sequence_or_baseline"
        return "liz_soft_residual_or_qc"
    if ladder == "ROX400HD":
        first = selected[0] if selected else 0
        last = selected[-1] if selected else 0
        if first < 1500 or (candidate_count > 38 and linear_mean > 2.5):
            return "rox_start_blob_or_prefix"
        if last < 3500 or last > 4300:
            return "rox_tail_span_or_false_complete"
        if linear_max > 10.0 or linear_mean > 4.5:
            return "rox_major_sequence_or_low_signal"
        return "rox_soft_residual_or_qc"
    return "unknown_ladder_failure"


def render_representatives(rows: list[dict[str, Any]], out_dir: Path, per_class: int) -> pd.DataFrame:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    previous_image_dir = live_eval.IMAGE_DIR
    live_eval.IMAGE_DIR = image_dir
    try:
        selected_rows: list[dict[str, Any]] = []
        df = pd.DataFrame([{key: value for key, value in row.items() if key != "result"} for row in rows])
        if df.empty:
            return pd.DataFrame()
        df["sort_score"] = (
            df["severe_fail"].astype(int) * 1000
            + df["review"].astype(int) * 500
            + df["soft_fail"].astype(int) * 100
            + pd.to_numeric(df["linear_max"], errors="coerce").fillna(0)
        )
        for _, group in df.sort_values("sort_score", ascending=False).groupby("failure_class", sort=True):
            selected_rows.extend(group.head(per_class).to_dict("records"))

        result_by_path = {row["raw_path"]: row.get("result") for row in rows}
        rendered = []
        for row in selected_rows:
            render_row = dict(row)
            render_row["result"] = result_by_path.get(row["raw_path"]) or {}
            image = live_eval.render_image(render_row)
            rendered.append({**{key: value for key, value in row.items() if key != "sort_score"}, "image": image or ""})
        return pd.DataFrame(rendered)
    finally:
        live_eval.IMAGE_DIR = previous_image_dir


def run(args: argparse.Namespace) -> None:
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_inputs = args.summary or DEFAULT_SUMMARIES
    summaries = [path if path.is_absolute() else ROOT / path for path in summary_inputs]
    inputs = load_failure_inputs(summaries)
    inputs.to_csv(out_dir / "input_failure_candidates.tsv", sep="\t", index=False)

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(inputs.itertuples(index=False), start=1):
        raw_path = Path(str(item.raw_path))
        analysis = analyze_path(raw_path, args.timeout)
        row = {
            "file": raw_path.name,
            "raw_path": str(raw_path),
            "source_group": getattr(item, "source_group", ""),
            "assay": getattr(item, "assay", ""),
            "previous_ladder": getattr(item, "ladder", ""),
            "previous_review": getattr(item, "review", ""),
            "previous_soft_fail": getattr(item, "soft_fail", ""),
            "previous_severe_fail": getattr(item, "severe_fail", ""),
            **analysis,
        }
        row["failure_class"] = classify(row)
        rows.append(row)
        print(f"{idx}/{len(inputs)} {raw_path.name}: {row['failure_class']} {row.get('linear_max')}/{row.get('linear_mean')}", flush=True)

    serializable = [{key: value for key, value in row.items() if key != "result"} for row in rows]
    df = pd.DataFrame(serializable)
    df.to_csv(out_dir / "current_failure_results.tsv", sep="\t", index=False)
    active = df[(~df["ok"]) | df["review"] | df["soft_fail"] | df["severe_fail"]].copy() if not df.empty else df
    active.to_csv(out_dir / "active_remaining_failures.tsv", sep="\t", index=False)
    class_summary = (
        active.groupby(["ladder", "failure_class"], dropna=False)
        .agg(
            n=("file", "size"),
            review=("review", "sum"),
            soft_fail=("soft_fail", "sum"),
            severe_fail=("severe_fail", "sum"),
            median_linear_max=("linear_max", "median"),
            max_linear_max=("linear_max", "max"),
            median_linear_mean=("linear_mean", "median"),
        )
        .reset_index()
        if not active.empty
        else pd.DataFrame()
    )
    class_summary.to_csv(out_dir / "failure_class_summary.tsv", sep="\t", index=False)
    images = render_representatives(rows, out_dir, args.images_per_class)
    images.to_csv(out_dir / "image_index.tsv", sep="\t", index=False)

    summary = {
        "input_candidates": int(len(inputs)),
        "active_remaining": int(len(active)),
        "ok_rerun": int(df["ok"].sum()) if not df.empty else 0,
        "review": int(df["review"].sum()) if not df.empty else 0,
        "soft_fail": int(df["soft_fail"].sum()) if not df.empty else 0,
        "severe_fail": int(df["severe_fail"].sum()) if not df.empty else 0,
        "by_class": class_summary.to_dict(orient="records") if not class_summary.empty else [],
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Remaining Ladder Failures Refresh", "", f"- input candidates: {summary['input_candidates']}", f"- active remaining: {summary['active_remaining']}", f"- review: {summary['review']}", f"- soft_fail: {summary['soft_fail']}", f"- severe_fail: {summary['severe_fail']}", "", "## Classes"]
    for item in summary["by_class"]:
        lines.append(
            f"- {item['ladder']} / {item['failure_class']}: n={item['n']}, review={item['review']}, soft={item['soft_fail']}, severe={item['severe_fail']}, median max={item['median_linear_max']:.2f}"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, action="append", default=[])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--images-per-class", type=int, default=2)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
