from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _RustPrimitiveWorker, _resolve_cli_bin, _rust_timeout_seconds
from core.utils import is_water_file
from scripts.broad_live_ladder_learning_eval import (
    LADDER_SIZES,
    analyze_one,
    infer_assay_from_file,
    infer_ladder,
)


CLONALITY_FILE_RE = re.compile(
    r"(tcrg|trga|trgb|tcrb|trb|fr1|fr2|fr3|dhjh|sl|igk|kde|ikzf)",
    re.IGNORECASE,
)


def scan_roots(roots: list[Path]) -> pd.DataFrame:
    rows: list[dict] = []
    for root in roots:
        for path in sorted(root.rglob("*.fsa")):
            if not path.is_file():
                continue
            try:
                if path.stat().st_size <= 0:
                    continue
            except OSError:
                continue
            name = path.name
            if is_water_file(name) or not CLONALITY_FILE_RE.search(name):
                continue
            assay = infer_assay_from_file(name)
            ladder = infer_ladder(assay, name)
            rows.append(
                {
                    "File": name,
                    "SourceRunDir": path.parent.name,
                    "Assay": assay,
                    "LadderQC": "raw_t7",
                    "LadderLinearMaxResidualBp": "",
                    "LadderLinearMeanResidualBp": "",
                    "LadderLinearR2": "",
                    "source_group": path.parent.name,
                    "source_root": str(root),
                    "raw_file": name,
                    "raw_path": str(path),
                    "ladder": ladder,
                    "bucket": "raw",
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates(subset=["raw_path"], keep="first").sort_values(
        ["source_root", "source_group", "ladder", "raw_file"]
    )


def worker_for(cli_bin: Path) -> _RustPrimitiveWorker:
    return _RustPrimitiveWorker(cli_bin)


def run_all(cases: pd.DataFrame, *, out_dir: Path, workers: int, progress_every: int) -> pd.DataFrame:
    cli_bin = _resolve_cli_bin()
    if cli_bin is None or not cli_bin.exists():
        raise RuntimeError("Could not resolve fraggler-cli")

    rows = [row for _, row in cases.iterrows()]
    shards = [[] for _ in range(max(1, workers))]
    for index, row in enumerate(rows):
        shards[index % len(shards)].append(row)

    out: list[dict] = []
    lock = threading.Lock()
    total = len(rows)
    timeout = max(_rust_timeout_seconds("clonality"), 8)
    start = time.time()

    def record(result: dict) -> None:
        with lock:
            out.append(result)
            done = len(out)
            if done == total or done % max(1, progress_every) == 0:
                elapsed = max(time.time() - start, 1.0)
                rate = done / elapsed
                print(f"completed rows {done}/{total} ({rate:.2f}/s)", flush=True)
                pd.DataFrame(out).to_csv(out_dir / "live_summary.partial.tsv", sep="\t", index=False)

    def run_shard(worker_index: int, shard: list[pd.Series]) -> int:
        worker = worker_for(cli_bin)
        completed = 0
        try:
            for row in shard:
                try:
                    result = analyze_one(worker, row, timeout)
                    if str(result.get("error", "")).startswith("worker timeout"):
                        worker.close()
                        worker = worker_for(cli_bin)
                except Exception as exc:
                    result = {
                        "file": row.get("raw_file", ""),
                        "raw_path": row.get("raw_path", ""),
                        "source_group": row.get("source_group", ""),
                        "assay": row.get("Assay", ""),
                        "workbook_ladder": row.get("ladder", ""),
                        "ladder": row.get("ladder", ""),
                        "workbook_bucket": row.get("bucket", ""),
                        "workbook_qc": row.get("LadderQC", ""),
                        "ok": False,
                        "error": repr(exc),
                        "review": "",
                        "primary_reason": "",
                        "reason_codes": json.dumps([]),
                        "soft_fail": "",
                        "severe_fail": "",
                        "candidate_count": "",
                        "selected_count": "",
                        "expected_count": len(LADDER_SIZES.get(str(row.get("ladder", "")), [])),
                        "nonlinear_complete_ok": "",
                        "linear_max": "",
                        "linear_mean": "",
                        "linear_r2": "",
                        "quadratic_max": "",
                        "quadratic_mean": "",
                        "quadratic_r2": "",
                        "selected": json.dumps([]),
                    }
                    worker.close()
                    worker = worker_for(cli_bin)
                record(result)
                completed += 1
        finally:
            worker.close()
        print(f"completed shard {worker_index + 1}/{workers} -> shard rows {completed}", flush=True)
        return completed

    with ThreadPoolExecutor(max_workers=len(shards)) as executor:
        futures = [executor.submit(run_shard, index, shard) for index, shard in enumerate(shards) if shard]
        for future in as_completed(futures):
            future.result()
    return pd.DataFrame(out)


def write_basic_summary(live: pd.DataFrame, out_dir: Path) -> None:
    numeric = live.copy()
    for column in ["linear_max", "linear_mean", "linear_r2", "quadratic_max", "quadratic_mean", "quadratic_r2"]:
        numeric[column] = pd.to_numeric(numeric.get(column), errors="coerce")
    summary = (
        numeric.groupby("ladder", dropna=False)
        .agg(
            n=("file", "size"),
            ok=("ok", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
            errors=("ok", lambda values: int(values.astype(str).str.lower().ne("true").sum())),
            review=("review", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
            soft_fail=("soft_fail", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
            severe_fail=("severe_fail", lambda values: int(values.astype(str).str.lower().eq("true").sum())),
            mean_max=("linear_max", "mean"),
            p95_max=("linear_max", lambda values: float(values.quantile(0.95))),
            max_max=("linear_max", "max"),
            mean_mean=("linear_mean", "mean"),
        )
        .reset_index()
    )
    summary.to_csv(out_dir / "live_failure_summary_by_ladder.tsv", sep="\t", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = scan_roots(args.root)
    cases.to_csv(out_dir / "selected_cases.tsv", sep="\t", index=False)
    print(f"selected cases: {len(cases)}", flush=True)
    if cases.empty:
        return
    print(cases.groupby(["source_root", "ladder"]).size().to_string(), flush=True)

    live = run_all(cases, out_dir=out_dir, workers=args.workers, progress_every=args.progress_every)
    live.to_csv(out_dir / "live_summary.tsv", sep="\t", index=False)
    write_basic_summary(live, out_dir)
    print(f"finished rows: {len(live)}", flush=True)


if __name__ == "__main__":
    main()
