from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker_pool, _invalidate_rust_worker_pool, _rust_timeout_seconds


OUT_DIR = ROOT / "artifacts" / "liz_time_template_2026-05-04"
DATA_2025_ROOT = Path("/Volumes/T7 Shield/DATA/2025_data")
WORKBOOK_2025_ROOT = Path("/Volumes/T7 Shield/HemaFrag_2025_safe_reruns_2026-04-28")
RUN_2026_ROOTS = [
    Path("/Volumes/T7 Shield/29_04/reports_2026-04-29/Clonality_Tracking.xlsx"),
]
PREFIX_RE = re.compile(r"^\d+_[0-9a-f]+_")
LIZ_SIZES = [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500]


@dataclass(frozen=True)
class Case:
    raw_path: str
    raw_file: str
    assay: str
    source_group: str
    source_month: str
    workbook_qc: str
    workbook_linear_max: float
    workbook_linear_mean: float
    workbook_linear_r2: float


def strip_stage_prefix(name: str) -> str:
    return PREFIX_RE.sub("", str(name or ""))


def is_liz_row(df: pd.DataFrame) -> pd.Series:
    assay = df["Assay"].astype(str)
    filecol = df["File"].astype(str).str.lower()
    return assay.isin(["TCRgA", "TCRgB", "IGK", "KDE"]) | filecol.str.contains(
        "tcrg|igk|kde|trga|trgb", regex=True
    )


def is_good_row(df: pd.DataFrame) -> pd.Series:
    qc = df["LadderQC"].astype(str)
    linear_max = pd.to_numeric(df["LadderLinearMaxResidualBp"], errors="coerce")
    linear_r2 = pd.to_numeric(df["LadderLinearR2"], errors="coerce")
    fitted = pd.to_numeric(df.get("LadderFittedStepCount"), errors="coerce")
    expected = pd.to_numeric(df.get("LadderExpectedStepCount"), errors="coerce")

    mask = (qc == "ok") & (linear_max < 5.0) & (linear_r2 >= 0.999)
    if "LadderFittedStepCount" in df.columns and "LadderExpectedStepCount" in df.columns:
        mask &= (fitted == 16) & (expected == 16)
    return mask


def load_2025_cases() -> list[Case]:
    frames = []
    for wb in sorted(WORKBOOK_2025_ROOT.glob("2025_*/reports_2026-04-28/Clonality_Tracking.xlsx")):
        df = pd.read_excel(wb)
        df["source_month"] = wb.parts[-3]
        frames.append(df)
    if not frames:
        return []

    df = pd.concat(frames, ignore_index=True)
    mask = is_liz_row(df) & is_good_row(df)
    df = df.loc[mask].copy()
    df["raw_file"] = df["File"].map(strip_stage_prefix)
    df["raw_path"] = [
        str(DATA_2025_ROOT / str(run_dir) / str(raw_file))
        for run_dir, raw_file in zip(df["SourceRunDir"], df["raw_file"])
    ]
    df = df[df["raw_path"].map(lambda p: Path(p).exists())].copy()

    return [
        Case(
            raw_path=str(row.raw_path),
            raw_file=str(row.raw_file),
            assay=str(row.Assay),
            source_group="2025",
            source_month=str(row.source_month),
            workbook_qc=str(row.LadderQC),
            workbook_linear_max=float(row.LadderLinearMaxResidualBp),
            workbook_linear_mean=float(row.LadderLinearMeanResidualBp),
            workbook_linear_r2=float(row.LadderLinearR2),
        )
        for row in df.itertuples(index=False)
    ]


def load_2026_cases() -> list[Case]:
    out: list[Case] = []
    for wb in RUN_2026_ROOTS:
        if not wb.exists():
            continue
        df = pd.read_excel(wb)
        mask = is_liz_row(df) & is_good_row(df)
        df = df.loc[mask].copy()
        df["raw_file"] = df["File"].map(strip_stage_prefix)
        run_root = wb.parent.parent
        df["raw_path"] = [
            str(run_root / str(run_dir) / str(raw_file))
            for run_dir, raw_file in zip(df["SourceRunDir"], df["raw_file"])
        ]
        df = df[df["raw_path"].map(lambda p: Path(p).exists())].copy()
        source_month = wb.parent.name.replace("reports_", "")
        out.extend(
            Case(
                raw_path=str(row.raw_path),
                raw_file=str(row.raw_file),
                assay=str(row.Assay),
                source_group="2026",
                source_month=source_month,
                workbook_qc=str(row.LadderQC),
                workbook_linear_max=float(row.LadderLinearMaxResidualBp),
                workbook_linear_mean=float(row.LadderLinearMeanResidualBp),
                workbook_linear_r2=float(row.LadderLinearR2),
            )
            for row in df.itertuples(index=False)
        )
    return out


def unwrap_result_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("result"), dict):
        return payload["result"]
    return payload


def fetch_liz_selected_peaks(cases: list[Case], worker_count: int = 1, chunk_size: int = 16) -> list[dict]:
    workers = _get_rust_worker_pool(max(1, min(worker_count, len(cases))))
    if not workers:
        raise RuntimeError("Could not create Rust worker pool")

    timeout = max(_rust_timeout_seconds("clonality"), 1)
    rows: list[dict] = []
    if len(workers) == 1:
        worker = workers[0]
        total_cases = len(cases)
        for idx, case in enumerate(cases, start=1):
            response = worker.request(Path(case.raw_path), "clonality", timeout)
            if not response or response.get("error"):
                err = response.get("error") if isinstance(response, dict) else "unknown worker error"
                print(f"skip {idx}/{total_cases}: {case.raw_file} -> {err}")
                continue
            result = unwrap_result_payload(response)
            preview = result.get("ladder_fit_preview") or {}
            scans = preview.get("best_scan_indices") or []
            model = preview.get("sizing_model") or {}
            qc = model.get("qc_metrics") or {}
            rows.append(
                {
                    "raw_path": case.raw_path,
                    "raw_file": case.raw_file,
                    "assay": case.assay,
                    "source_group": case.source_group,
                    "source_month": case.source_month,
                    "workbook_qc": case.workbook_qc,
                    "workbook_linear_max": case.workbook_linear_max,
                    "workbook_linear_mean": case.workbook_linear_mean,
                    "workbook_linear_r2": case.workbook_linear_r2,
                    "live_selected_peaks": scans,
                    "live_linear_max": qc.get("linear_trend_max_abs_error_bp"),
                    "live_linear_mean": qc.get("linear_trend_mean_abs_error_bp"),
                    "live_linear_r2": qc.get("linear_trend_r2"),
                }
            )
            if idx == 1 or idx % 100 == 0 or idx == total_cases:
                print(f"completed case {idx}/{total_cases} -> rows {len(rows)}")
                (OUT_DIR / "live_rows.partial.json").write_text(json.dumps(rows))
    else:
        shards: list[list[Case]] = [[] for _ in range(len(workers))]
        for index, case in enumerate(cases):
            shards[index % len(workers)].append(case)

        def run_shard(worker_idx: int, shard_cases: list[Case]) -> list[dict]:
            results: list[dict] = []
            worker = workers[worker_idx]
            for offset in range(0, len(shard_cases), chunk_size):
                chunk = shard_cases[offset: offset + chunk_size]
                paths = [Path(case.raw_path) for case in chunk]
                response = worker.request_many(paths, "clonality", timeout)
                if not response or not response.get("ok"):
                    err = response.get("error") if isinstance(response, dict) else "unknown worker error"
                    raise RuntimeError(f"Rust worker shard {worker_idx} failed: {err}")
                payload = response.get("results")
                if not isinstance(payload, list):
                    single = response.get("result")
                    payload = [single] if isinstance(single, dict) else []
                for case, result in zip(chunk, payload):
                    if not isinstance(result, dict):
                        continue
                    result_payload = unwrap_result_payload(result)
                    preview = result_payload.get("ladder_fit_preview") or {}
                    scans = preview.get("best_scan_indices") or []
                    model = preview.get("sizing_model") or {}
                    qc = model.get("qc_metrics") or {}
                    results.append(
                        {
                            "raw_path": case.raw_path,
                            "raw_file": case.raw_file,
                            "assay": case.assay,
                            "source_group": case.source_group,
                            "source_month": case.source_month,
                            "workbook_qc": case.workbook_qc,
                            "workbook_linear_max": case.workbook_linear_max,
                            "workbook_linear_mean": case.workbook_linear_mean,
                            "workbook_linear_r2": case.workbook_linear_r2,
                            "live_selected_peaks": scans,
                            "live_linear_max": qc.get("linear_trend_max_abs_error_bp"),
                            "live_linear_mean": qc.get("linear_trend_mean_abs_error_bp"),
                            "live_linear_r2": qc.get("linear_trend_r2"),
                        }
                    )
            return results

        with ThreadPoolExecutor(max_workers=len(workers)) as executor:
            futures = [
                executor.submit(run_shard, idx, shard)
                for idx, shard in enumerate(shards)
                if shard
            ]
            completed = 0
            total = len(futures)
            for future in as_completed(futures):
                shard_rows = future.result()
                rows.extend(shard_rows)
                completed += 1
                print(f"completed shard {completed}/{total} -> +{len(shard_rows)} rows")
                (OUT_DIR / "live_rows.partial.json").write_text(json.dumps(rows))

    _invalidate_rust_worker_pool()
    return rows


def summarize_numeric(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {
        "count": int(arr.size),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=0)),
        "min": float(arr.min()),
        "p05": float(np.percentile(arr, 5)),
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "median": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
    }


def build_step_and_gap_tables(rows: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail_rows = []
    gap_rows = []
    kept_rows = []
    for row in rows:
        scans = row["live_selected_peaks"] or []
        if len(scans) != len(LIZ_SIZES):
            continue
        kept_rows.append(row)
        for bp, scan in zip(LIZ_SIZES, scans):
            detail_rows.append(
                {
                    "raw_file": row["raw_file"],
                    "assay": row["assay"],
                    "source_group": row["source_group"],
                    "source_month": row["source_month"],
                    "bp": bp,
                    "scan": int(scan),
                    "live_linear_max": row["live_linear_max"],
                    "live_linear_mean": row["live_linear_mean"],
                    "live_linear_r2": row["live_linear_r2"],
                }
            )
        for idx in range(len(scans) - 1):
            gap_rows.append(
                {
                    "raw_file": row["raw_file"],
                    "assay": row["assay"],
                    "source_group": row["source_group"],
                    "source_month": row["source_month"],
                    "bp_from": LIZ_SIZES[idx],
                    "bp_to": LIZ_SIZES[idx + 1],
                    "scan_from": int(scans[idx]),
                    "scan_to": int(scans[idx + 1]),
                    "gap_scan": int(scans[idx + 1] - scans[idx]),
                }
            )

    detail_df = pd.DataFrame(detail_rows)
    gap_df = pd.DataFrame(gap_rows)
    kept_df = pd.DataFrame(kept_rows)
    return detail_df, gap_df, kept_df


def aggregate_step_stats(detail_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for bp, group in detail_df.groupby("bp", sort=True):
        stats = summarize_numeric(group["scan"].tolist())
        stats["bp"] = int(bp)
        rows.append(stats)
    return pd.DataFrame(rows)[
        ["bp", "count", "mean", "std", "min", "p05", "p10", "p25", "median", "p75", "p90", "p95", "max"]
    ]


def aggregate_gap_stats(gap_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (bp_from, bp_to), group in gap_df.groupby(["bp_from", "bp_to"], sort=True):
        stats = summarize_numeric(group["gap_scan"].tolist())
        stats["bp_from"] = int(bp_from)
        stats["bp_to"] = int(bp_to)
        stats["bp_delta"] = int(bp_to - bp_from)
        rows.append(stats)
    return pd.DataFrame(rows)[
        ["bp_from", "bp_to", "bp_delta", "count", "mean", "std", "min", "p05", "p10", "p25", "median", "p75", "p90", "p95", "max"]
    ]


def aggregate_assay_step_stats(detail_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (assay, bp), group in detail_df.groupby(["assay", "bp"], sort=True):
        stats = summarize_numeric(group["scan"].tolist())
        stats["assay"] = assay
        stats["bp"] = int(bp)
        rows.append(stats)
    return pd.DataFrame(rows)


def make_plots(step_stats: pd.DataFrame, gap_stats: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    x = step_stats["bp"].to_numpy(dtype=float)
    y = step_stats["median"].to_numpy(dtype=float)
    low = step_stats["p10"].to_numpy(dtype=float)
    high = step_stats["p90"].to_numpy(dtype=float)
    ax.fill_between(x, low, high, color="#c7d9f1", alpha=0.8, label="p10-p90")
    ax.plot(x, y, color="#0f4c81", linewidth=2.5, label="median scan")
    ax.scatter(x, y, color="#0f4c81", s=30)
    for _, row in step_stats.iterrows():
        ax.text(row["bp"], row["median"] + 12, str(int(row["bp"])), fontsize=8, ha="center")
    ax.set_title("LIZ Time Template From Good Files")
    ax.set_xlabel("Ladder step (bp)")
    ax.set_ylabel("Scan time")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "liz_step_time_template.png", dpi=180)
    plt.close(fig)

    labels = [f"{int(a)}-{int(b)}" for a, b in zip(gap_stats["bp_from"], gap_stats["bp_to"])]
    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(len(labels))
    ax.fill_between(
        x,
        gap_stats["p10"].to_numpy(dtype=float),
        gap_stats["p90"].to_numpy(dtype=float),
        color="#f3d8b6",
        alpha=0.8,
        label="p10-p90",
    )
    ax.plot(x, gap_stats["median"].to_numpy(dtype=float), color="#9a4d00", linewidth=2.5, label="median gap")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=8)
    ax.set_title("LIZ Gap Template From Good Files")
    ax.set_xlabel("Adjacent ladder steps (bp)")
    ax.set_ylabel("Gap in scan time")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "liz_gap_template.png", dpi=180)
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = load_2025_cases() + load_2026_cases()
    cases = sorted({case.raw_path: case for case in cases}.values(), key=lambda case: case.raw_path)
    print(f"selected good LIZ cases: {len(cases)}")

    rows = fetch_liz_selected_peaks(cases, worker_count=1, chunk_size=1)
    Path(OUT_DIR / "live_rows.json").write_text(json.dumps(rows, indent=2))

    detail_df, gap_df, kept_df = build_step_and_gap_tables(rows)
    step_stats = aggregate_step_stats(detail_df)
    gap_stats = aggregate_gap_stats(gap_df)
    assay_step_stats = aggregate_assay_step_stats(detail_df)

    kept_df.to_csv(OUT_DIR / "cases_used.tsv", sep="\t", index=False)
    detail_df.to_csv(OUT_DIR / "bp_scan_detail.tsv", sep="\t", index=False)
    gap_df.to_csv(OUT_DIR / "gap_detail.tsv", sep="\t", index=False)
    step_stats.to_csv(OUT_DIR / "bp_scan_stats.tsv", sep="\t", index=False)
    gap_stats.to_csv(OUT_DIR / "gap_stats.tsv", sep="\t", index=False)
    assay_step_stats.to_csv(OUT_DIR / "assay_bp_scan_stats.tsv", sep="\t", index=False)

    manifest = {
        "selected_case_count": len(cases),
        "used_case_count": int(len(kept_df)),
        "dropped_case_count": int(len(cases) - len(kept_df)),
        "source_groups": pd.Series([case.source_group for case in cases]).value_counts().to_dict(),
        "assays": pd.Series([case.assay for case in cases]).value_counts().to_dict(),
        "ladder_sizes": LIZ_SIZES,
        "criteria": {
            "ladder": "LIZ500_250",
            "workbook_qc": "ok",
            "max_linear_max": 5.0,
            "min_linear_r2": 0.999,
            "require_fitted_16_of_16": True,
        },
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    make_plots(step_stats, gap_stats)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
