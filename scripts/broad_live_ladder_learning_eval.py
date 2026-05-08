from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _RustPrimitiveWorker, _get_rust_worker_pool, _invalidate_rust_worker_pool, _rust_timeout_seconds
from core.utils import is_water_file


OUT_DIR = ROOT / "artifacts" / "broad_live_ladder_learning_2026-05-04"
DATA_2025_ROOT = Path("/Volumes/T7 Shield/DATA/2025_data")
DATA_2026_ROOT = Path("/Volumes/T7 Shield/DATA/2026")
SAFE_2025_ROOT = Path("/Volumes/T7 Shield/HemaFrag_2025_safe_reruns_2026-04-28")
RUN_2026_WORKBOOKS = [
    Path("/Volumes/T7 Shield/29_04/reports_2026-04-29/Clonality_Tracking.xlsx"),
]
PREFIX_RE = re.compile(r"^\d+_[0-9a-f]+_")
CLONALITY_FILE_RE = re.compile(
    r"(tcrg|trga|trgb|tcrb|trb|fr1|fr2|fr3|dhjh|sl|igk|kde|ikzf)",
    re.IGNORECASE,
)

LADDER_SIZES = {
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
}


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


def infer_assay_from_file(file_name: object) -> str:
    lower = str(file_name or "").lower()
    if any(key in lower for key in ("tcrg", "trga", "trgb", "trg_a", "trg_b")):
        return "TCRgA" if any(key in lower for key in ("tcra", "trga", "trg_a")) else "TCRgB"
    if "igk" in lower:
        return "IGK"
    if "kde" in lower or "kde" in lower:
        return "KDE"
    if "tcrb" in lower or "trb" in lower:
        return "TCRbA" if any(key in lower for key in ("_a", "mixa", "tcrb_a")) else "TCRbB"
    if "fr1" in lower:
        return "FR1"
    if "fr2" in lower:
        return "FR2"
    if "fr3" in lower:
        return "FR3"
    if "dhjh" in lower:
        return "DHJH"
    if re.search(r"(^|[_-])sl([_-]|$)", lower):
        return "SL"
    if "ikzf" in lower:
        return "IKZF1"
    return "unknown"


def bucket(qc: object, lmax: object, r2: object) -> str:
    qc_text = str(qc or "")
    max_value = float(pd.to_numeric(lmax, errors="coerce")) if pd.notna(lmax) else float("nan")
    r2_value = float(pd.to_numeric(r2, errors="coerce")) if pd.notna(r2) else float("nan")
    if qc_text == "ok" and max_value < 5.0 and r2_value >= 0.999:
        return "good"
    if qc_text != "ok" or max_value > 10.0 or r2_value < 0.998:
        return "bad"
    return "mid"


def load_2025_rows() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for workbook in sorted(SAFE_2025_ROOT.glob("2025_*/reports_2026-04-28/Clonality_Tracking.xlsx")):
        df = pd.read_excel(workbook)
        df["source_group"] = workbook.parts[-3]
        df["source_root"] = str(DATA_2025_ROOT)
        df["raw_file"] = df["File"].map(strip_stage_prefix)
        df["raw_path"] = [
            str(DATA_2025_ROOT / str(run_dir) / str(raw_file))
            for run_dir, raw_file in zip(df["SourceRunDir"], df["raw_file"])
        ]
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_2026_rows() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for workbook in RUN_2026_WORKBOOKS:
        if not workbook.exists():
            continue
        df = pd.read_excel(workbook)
        if "File" not in df.columns or "SourceRunDir" not in df.columns:
            continue
        run_root = workbook.parent.parent
        df["source_group"] = run_root.name
        df["source_root"] = str(run_root)
        df["raw_file"] = df["File"].map(strip_stage_prefix)
        df["raw_path"] = [
            str(run_root / str(run_dir) / str(raw_file))
            for run_dir, raw_file in zip(df["SourceRunDir"], df["raw_file"])
        ]
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_2026_raw_rows(raw_root: Path = DATA_2026_ROOT) -> pd.DataFrame:
    rows: list[dict] = []
    if not raw_root.exists():
        return pd.DataFrame()
    for path in sorted(raw_root.glob("2026_*/*.fsa")):
        name = path.name
        if is_water_file(name):
            continue
        if not CLONALITY_FILE_RE.search(name):
            continue
        assay = infer_assay_from_file(name)
        rows.append(
            {
                "File": name,
                "SourceRunDir": path.parent.name,
                "Assay": assay,
                "LadderQC": "raw_2026",
                "LadderLinearMaxResidualBp": np.nan,
                "LadderLinearMeanResidualBp": np.nan,
                "LadderLinearR2": np.nan,
                "source_group": path.parent.name,
                "source_root": str(raw_root),
                "raw_file": name,
                "raw_path": str(path),
            }
        )
    return pd.DataFrame(rows)


def load_cases(max_cases: int, include_raw_2026: bool = False, raw_2026_root: Path = DATA_2026_ROOT) -> pd.DataFrame:
    frames = [load_2025_rows(), load_2026_rows()]
    if include_raw_2026:
        frames.append(load_2026_raw_rows(raw_2026_root))
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df
    df["raw_file"] = df["raw_file"].astype(str)
    df = df[~df["raw_file"].map(is_water_file)].copy()
    df["raw_path"] = df["raw_path"].astype(str)
    df = df[df["raw_path"].map(lambda p: Path(p).exists())].copy()
    df["ladder"] = [infer_ladder(a, f) for a, f in zip(df["Assay"], df["raw_file"])]
    df["bucket"] = [
        bucket(qc, lmax, r2)
        for qc, lmax, r2 in zip(df["LadderQC"], df["LadderLinearMaxResidualBp"], df["LadderLinearR2"])
    ]
    df = df.drop_duplicates(subset=["raw_path"], keep="first").copy()
    if len(df) <= max_cases:
        return df.sort_values(["source_group", "ladder", "bucket", "raw_file"]).copy()

    per_group = max(1, max_cases // max(1, df.groupby(["source_group", "ladder", "bucket"]).ngroups))
    sampled: list[pd.DataFrame] = []
    for _, group in df.groupby(["source_group", "ladder", "bucket"], sort=True):
        group = group.sort_values(["LadderLinearMaxResidualBp", "raw_file"], na_position="last")
        n = min(per_group, len(group))
        if n == len(group):
            sampled.append(group)
            continue
        index = np.linspace(0, len(group) - 1, n).round().astype(int)
        sampled.append(group.iloc[index])
    out = pd.concat(sampled, ignore_index=True).drop_duplicates(subset=["raw_path"])
    if len(out) < max_cases:
        remaining = df[~df["raw_path"].isin(set(out["raw_path"]))].sort_values(["source_group", "ladder", "bucket", "raw_file"])
        out = pd.concat([out, remaining.head(max_cases - len(out))], ignore_index=True)
    return out.head(max_cases).copy()


def unwrap_result(response: dict | None) -> tuple[dict, str]:
    if not isinstance(response, dict):
        return {}, "empty response"
    if response.get("error"):
        return {}, str(response.get("error"))
    result = response.get("result")
    if isinstance(result, dict):
        return result, ""
    if isinstance(response.get("ladder_fit_preview"), dict):
        return response, ""
    return {}, "missing result"


def selected_scans(preview: dict) -> list[int]:
    refinement = preview.get("refinement") or {}
    scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
    return [int(round(float(value))) for value in scans]


def metrics_from_result(result: dict) -> tuple[dict, dict, list[int]]:
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    return preview, metrics, selected_scans(preview)


def parse_metric(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if np.isfinite(out) else float("nan")


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
    if selected_count != expected_count or expected_count != len(LADDER_SIZES.get(ladder, [])):
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


def analyze_one(worker: _RustPrimitiveWorker, row: pd.Series, timeout: int) -> dict:
    response = worker.request(Path(str(row["raw_path"])), "clonality", timeout)
    result, error = unwrap_result(response)
    preview, metrics, scans = metrics_from_result(result) if result else ({}, {}, [])
    review = result.get("ladder_review_assessment") if result else {}
    if not isinstance(review, dict):
        review = {}
    ladder = str(result.get("ladder") or preview.get("ladder_kind") or row["ladder"])
    expected = len(LADDER_SIZES.get(ladder, []))
    linear_max = metrics.get("linear_trend_max_abs_error_bp")
    linear_mean = metrics.get("linear_trend_mean_abs_error_bp")
    linear_r2 = metrics.get("linear_trend_r2")
    quadratic_max = metrics.get("quadratic_trend_max_abs_error_bp")
    quadratic_mean = metrics.get("quadratic_trend_mean_abs_error_bp")
    quadratic_r2 = metrics.get("quadratic_trend_r2")
    linear_max_value = parse_metric(linear_max)
    linear_mean_value = parse_metric(linear_mean)
    linear_r2_value = parse_metric(linear_r2)
    quadratic_max_value = parse_metric(quadratic_max)
    quadratic_mean_value = parse_metric(quadratic_mean)
    quadratic_r2_value = parse_metric(quadratic_r2)
    nonlinear_ok = nonlinear_complete_ok(
        ladder,
        len(scans),
        expected,
        linear_max_value,
        linear_mean_value,
        linear_r2_value,
        quadratic_max_value,
        quadratic_mean_value,
        quadratic_r2_value,
    )
    soft_fail = bool(
        not error
        and (
            bool(review.get("suggested_review"))
            or (
                not nonlinear_ok
                and (linear_max_value > 6.0 or linear_mean_value > 3.0 or linear_r2_value < 0.999)
            )
        )
    )
    severe_fail = bool(
        not error
        and (
            bool(review.get("suggested_review"))
            or (
                not nonlinear_ok
                and (linear_max_value > 10.0 or linear_mean_value > 4.5 or linear_r2_value < 0.9985)
            )
        )
    )
    return {
        "file": row["raw_file"],
        "raw_path": row["raw_path"],
        "source_group": row["source_group"],
        "assay": row["Assay"],
        "workbook_ladder": row["ladder"],
        "ladder": ladder,
        "workbook_bucket": row["bucket"],
        "workbook_qc": row["LadderQC"],
        "workbook_linear_max": row["LadderLinearMaxResidualBp"],
        "workbook_linear_mean": row["LadderLinearMeanResidualBp"],
        "workbook_linear_r2": row["LadderLinearR2"],
        "ok": not error,
        "error": error,
        "review": bool(review.get("suggested_review")) if result else "",
        "primary_reason": review.get("primary_reason") or "",
        "reason_codes": json.dumps(review.get("reason_codes") or []),
        "soft_fail": soft_fail,
        "severe_fail": severe_fail,
        "candidate_count": len(result.get("ladder_peak_preview") or []) if result else "",
        "selected_count": len(scans),
        "expected_count": expected,
        "nonlinear_complete_ok": nonlinear_ok,
        "linear_max": linear_max,
        "linear_mean": linear_mean,
        "linear_r2": linear_r2,
        "quadratic_max": quadratic_max,
        "quadratic_mean": quadratic_mean,
        "quadratic_r2": quadratic_r2,
        "selected": json.dumps(scans),
    }


def run_live(cases: pd.DataFrame, workers: int, progress_every: int = 25) -> pd.DataFrame:
    worker_pool = _get_rust_worker_pool(max(1, workers))
    if not worker_pool:
        raise RuntimeError("Could not start Rust worker pool")
    timeout = max(_rust_timeout_seconds("clonality"), 4)
    rows = [row for _, row in cases.iterrows()]
    shards = [[] for _ in worker_pool]
    for index, row in enumerate(rows):
        shards[index % len(worker_pool)].append(row)

    out: list[dict] = []
    out_lock = threading.Lock()
    total = len(rows)

    def record_progress(part: list[dict]) -> None:
        with out_lock:
            out.extend(part)
            done_count = len(out)
            if done_count == total or done_count % max(1, progress_every) == 0:
                print(f"completed rows {done_count}/{total}", flush=True)
                pd.DataFrame(out).to_csv(OUT_DIR / "live_summary.partial.tsv", sep="\t", index=False)

    def run_shard(worker_index: int, shard: list[pd.Series]) -> list[dict]:
        worker = worker_pool[worker_index]
        part: list[dict] = []
        for row in shard:
            result = analyze_one(worker, row, timeout)
            part.append(result)
            record_progress([result])
        return part

    with ThreadPoolExecutor(max_workers=len(worker_pool)) as executor:
        futures = [executor.submit(run_shard, index, shard) for index, shard in enumerate(shards) if shard]
        for done, future in enumerate(as_completed(futures), start=1):
            part = future.result()
            print(f"completed shard {done}/{len(futures)} -> shard rows {len(part)}")
    _invalidate_rust_worker_pool()
    return pd.DataFrame(out)


def trusted_rows(df: pd.DataFrame) -> pd.DataFrame:
    linear_max = pd.to_numeric(df["linear_max"], errors="coerce")
    linear_mean = pd.to_numeric(df["linear_mean"], errors="coerce")
    linear_r2 = pd.to_numeric(df["linear_r2"], errors="coerce")
    return df[
        (df["ok"] == True)
        & (df["review"] == False)
        & (df["selected_count"].astype(int) == df["expected_count"].astype(int))
        & (linear_max <= 6.0)
        & (linear_mean <= 3.0)
        & (linear_r2 >= 0.999)
    ].copy()


def build_templates(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    step_rows: list[dict] = []
    gap_rows: list[dict] = []
    for row in df.itertuples(index=False):
        sizes = LADDER_SIZES.get(str(row.ladder), [])
        scans = json.loads(row.selected or "[]")
        if len(scans) != len(sizes):
            continue
        for step, (bp, scan) in enumerate(zip(sizes, scans), start=1):
            step_rows.append(
                {
                    "source_group": row.source_group,
                    "ladder": row.ladder,
                    "step": step,
                    "bp": bp,
                    "scan": int(scan),
                }
            )
        for index in range(len(scans) - 1):
            gap_rows.append(
                {
                    "source_group": row.source_group,
                    "ladder": row.ladder,
                    "step_from": index + 1,
                    "step_to": index + 2,
                    "bp_from": sizes[index],
                    "bp_to": sizes[index + 1],
                    "gap_scan": int(scans[index + 1] - scans[index]),
                }
            )
    return pd.DataFrame(step_rows), pd.DataFrame(gap_rows)


def aggregate(values: pd.DataFrame, value_col: str, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for key, group in values.groupby(group_cols, sort=True):
        key_tuple = key if isinstance(key, tuple) else (key,)
        arr = group[value_col].to_numpy(dtype=float)
        row = dict(zip(group_cols, key_tuple))
        row.update(
            {
                "count": int(arr.size),
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "p05": float(np.percentile(arr, 5)),
                "p10": float(np.percentile(arr, 10)),
                "median": float(np.percentile(arr, 50)),
                "p90": float(np.percentile(arr, 90)),
                "p95": float(np.percentile(arr, 95)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    global OUT_DIR

    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cases", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--include-raw-2026", action="store_true", help="Include raw clonality-looking FSA files from DATA/2026.")
    parser.add_argument("--raw-2026-root", type=Path, default=DATA_2026_ROOT)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_DIR,
        help="Output directory for broad live eval artifacts.",
    )
    args = parser.parse_args()
    OUT_DIR = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_cases(args.max_cases, include_raw_2026=args.include_raw_2026, raw_2026_root=args.raw_2026_root)
    cases.to_csv(OUT_DIR / "selected_cases.tsv", sep="\t", index=False)
    print(f"selected cases: {len(cases)}")
    print(cases.groupby(["source_group", "ladder", "bucket"]).size().to_string())

    live = run_live(cases, args.workers)
    live.to_csv(OUT_DIR / "live_summary.tsv", sep="\t", index=False)

    numeric_live = live.copy()
    for column in ["linear_max", "linear_mean", "linear_r2", "quadratic_max", "quadratic_mean", "quadratic_r2"]:
        numeric_live[column] = pd.to_numeric(numeric_live[column], errors="coerce")
    failure_summary = (
        numeric_live.groupby("ladder", sort=True)
        .agg(
            n=("file", "size"),
            review=("review", lambda values: int(values.eq(True).sum())),
            soft_fail=("soft_fail", lambda values: int(values.eq(True).sum())),
            severe_fail=("severe_fail", lambda values: int(values.eq(True).sum())),
            mean_max=("linear_max", "mean"),
            p95_max=("linear_max", lambda values: float(values.quantile(0.95))),
            max_max=("linear_max", "max"),
            mean_mean=("linear_mean", "mean"),
        )
        .reset_index()
    )
    failure_summary.to_csv(OUT_DIR / "live_failure_summary_by_ladder.tsv", sep="\t", index=False)

    fail_columns = [
        "file",
        "raw_path",
        "source_group",
        "assay",
        "workbook_ladder",
        "ladder",
        "workbook_bucket",
        "workbook_qc",
        "review",
        "primary_reason",
        "reason_codes",
        "soft_fail",
        "severe_fail",
        "candidate_count",
        "selected_count",
        "expected_count",
        "nonlinear_complete_ok",
        "linear_max",
        "linear_mean",
        "linear_r2",
        "quadratic_max",
        "quadratic_mean",
        "quadratic_r2",
        "selected",
    ]
    fail_columns = [column for column in fail_columns if column in numeric_live.columns]
    soft_fail_cases = numeric_live[numeric_live["soft_fail"].eq(True)].sort_values(
        ["severe_fail", "review", "linear_max", "linear_mean"],
        ascending=False,
    )
    soft_fail_cases[fail_columns].to_csv(OUT_DIR / "soft_fail_cases.tsv", sep="\t", index=False)
    soft_fail_cases[soft_fail_cases["severe_fail"].eq(True)][fail_columns].to_csv(
        OUT_DIR / "severe_fail_cases.tsv",
        sep="\t",
        index=False,
    )
    wrong_ladder = numeric_live[numeric_live["workbook_ladder"].ne(numeric_live["ladder"])].copy()
    wrong_ladder[fail_columns].to_csv(OUT_DIR / "wrong_ladder_calls.tsv", sep="\t", index=False)

    trusted = trusted_rows(live)
    trusted.to_csv(OUT_DIR / "trusted_live_cases.tsv", sep="\t", index=False)
    step_detail, gap_detail = build_templates(trusted)
    step_detail.to_csv(OUT_DIR / "template_bp_scan_detail.tsv", sep="\t", index=False)
    gap_detail.to_csv(OUT_DIR / "template_gap_detail.tsv", sep="\t", index=False)
    step_stats = aggregate(step_detail, "scan", ["ladder", "step", "bp"])
    gap_stats = aggregate(gap_detail, "gap_scan", ["ladder", "step_from", "step_to", "bp_from", "bp_to"])
    source_step_stats = aggregate(step_detail, "scan", ["source_group", "ladder", "step", "bp"])
    step_stats.to_csv(OUT_DIR / "template_bp_scan_stats.tsv", sep="\t", index=False)
    gap_stats.to_csv(OUT_DIR / "template_gap_stats.tsv", sep="\t", index=False)
    source_step_stats.to_csv(OUT_DIR / "template_source_bp_scan_stats.tsv", sep="\t", index=False)

    summary = {
        "selected_cases": int(len(cases)),
        "live_rows": int(len(live)),
        "errors": int((live["ok"] == False).sum()) if not live.empty else 0,
        "review": int((live["review"] == True).sum()) if not live.empty else 0,
        "soft_fail": int((live["soft_fail"] == True).sum()) if "soft_fail" in live else 0,
        "severe_fail": int((live["severe_fail"] == True).sum()) if "severe_fail" in live else 0,
        "trusted": int(len(trusted)),
        "trusted_by_ladder": trusted["ladder"].value_counts().to_dict() if not trusted.empty else {},
        "live_by_ladder": live["ladder"].value_counts().to_dict() if not live.empty else {},
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
