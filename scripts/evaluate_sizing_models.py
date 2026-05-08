from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "artifacts" / "sizing_model_eval_2026-05-04"

LIZ_BPS = np.asarray([35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500], dtype=float)
ROX_BPS = np.asarray([50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400], dtype=float)


def load_live_rows() -> list[dict]:
    path = ROOT / "artifacts" / "rust_apex_recenter_live_eval" / "summary.tsv"
    rows: list[dict] = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("ok") != "True":
                continue
            ladder = row.get("ladder")
            scans = json.loads(row.get("selected") or "[]")
            expected = len(LIZ_BPS) if ladder == "LIZ500_250" else len(ROX_BPS) if ladder == "ROX400HD" else 0
            if expected and len(scans) == expected:
                row["scans"] = [float(x) for x in scans]
                rows.append(row)
    return rows


def residual_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    residuals = np.abs(actual - predicted)
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    ss_res = float(np.sum((actual - predicted) ** 2))
    return {
        "max_abs": float(np.max(residuals)),
        "mean_abs": float(np.mean(residuals)),
        "p95_abs": float(np.percentile(residuals, 95)),
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 1.0,
    }


def poly_predict(x: np.ndarray, y: np.ndarray, xq: np.ndarray, degree: int) -> np.ndarray:
    degree = min(degree, max(1, x.size - 1))
    coeff = np.polyfit(x, y, degree)
    return np.polyval(coeff, xq)


def southern_predict(x: np.ndarray, y: np.ndarray, xq: np.ndarray, degree: int) -> np.ndarray:
    log_y = np.log(np.maximum(y, 1e-6))
    pred_log = poly_predict(x, log_y, xq, degree)
    return np.exp(pred_log)


def interp_predict(x: np.ndarray, y: np.ndarray, xq: np.ndarray, method: str) -> np.ndarray:
    order = np.argsort(x)
    xs = x[order]
    ys = y[order]
    if method == "pchip":
        return PchipInterpolator(xs, ys, extrapolate=True)(xq)
    if method == "cubic_spline":
        if xs.size < 4:
            return poly_predict(xs, ys, xq, 2)
        return CubicSpline(xs, ys, bc_type="natural", extrapolate=True)(xq)
    raise ValueError(method)


def local_predict(x: np.ndarray, y: np.ndarray, xq: np.ndarray, k: int, degree: int, log_bp: bool = False) -> np.ndarray:
    out = []
    target_y = np.log(np.maximum(y, 1e-6)) if log_bp else y
    for value in xq:
        order = np.argsort(np.abs(x - value))[: min(k, x.size)]
        xs = x[order]
        ys = target_y[order]
        pred = poly_predict(xs, ys, np.asarray([value], dtype=float), min(degree, xs.size - 1))[0]
        out.append(float(math.exp(pred) if log_bp else pred))
    return np.asarray(out, dtype=float)


MODEL_SPECS = [
    ("linear_ls", lambda x, y, xq: poly_predict(x, y, xq, 1)),
    ("quadratic_ls", lambda x, y, xq: poly_predict(x, y, xq, 2)),
    ("cubic_ls", lambda x, y, xq: poly_predict(x, y, xq, 3)),
    ("global_southern_log_linear", lambda x, y, xq: southern_predict(x, y, xq, 1)),
    ("global_southern_log_quadratic", lambda x, y, xq: southern_predict(x, y, xq, 2)),
    ("pchip_monotone", lambda x, y, xq: interp_predict(x, y, xq, "pchip")),
    ("natural_cubic_spline", lambda x, y, xq: interp_predict(x, y, xq, "cubic_spline")),
    ("local_linear_k5", lambda x, y, xq: local_predict(x, y, xq, 5, 1)),
    ("local_quadratic_k7", lambda x, y, xq: local_predict(x, y, xq, 7, 2)),
    ("local_southern_k5", lambda x, y, xq: local_predict(x, y, xq, 5, 1, log_bp=True)),
]


def leave_one_out(x: np.ndarray, y: np.ndarray, predictor) -> dict:
    preds = []
    actual = []
    for idx in range(x.size):
        mask = np.ones(x.size, dtype=bool)
        mask[idx] = False
        try:
            pred = predictor(x[mask], y[mask], np.asarray([x[idx]], dtype=float))[0]
        except Exception:
            continue
        if np.isfinite(pred):
            preds.append(float(pred))
            actual.append(float(y[idx]))
    if len(preds) < max(3, x.size - 2):
        return {"loo_max_abs": "", "loo_mean_abs": "", "loo_p95_abs": "", "loo_r2": ""}
    metrics = residual_metrics(np.asarray(actual), np.asarray(preds))
    return {
        "loo_max_abs": metrics["max_abs"],
        "loo_mean_abs": metrics["mean_abs"],
        "loo_p95_abs": metrics["p95_abs"],
        "loo_r2": metrics["r2"],
    }


def row_group(row: dict) -> str:
    raw = row.get("raw_path", "")
    if "/29_04/" in raw:
        return "29_04"
    if "2025_10_29" in raw:
        return "2025_10_29"
    if "2025_01_16" in raw:
        return "2025_01_16"
    if "2026_03_27" in raw:
        return "2026_03_27"
    if "2026_04_09" in raw:
        return "2026_04_09"
    return row.get("ladder", "unknown")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    detail = []
    for row in load_live_rows():
        ladder = row["ladder"]
        bps = LIZ_BPS if ladder == "LIZ500_250" else ROX_BPS
        scans = np.asarray(row["scans"], dtype=float)
        if scans.size != bps.size:
            continue
        for model_name, predictor in MODEL_SPECS:
            try:
                pred = predictor(scans, bps, scans)
                metrics = residual_metrics(bps, pred)
                loo = leave_one_out(scans, bps, predictor)
            except Exception as exc:
                detail.append({
                    "file": row["file"],
                    "raw_path": row["raw_path"],
                    "ladder": ladder,
                    "source_group": row_group(row),
                    "model": model_name,
                    "ok": False,
                    "error": str(exc),
                })
                continue
            detail.append({
                "file": row["file"],
                "raw_path": row["raw_path"],
                "ladder": ladder,
                "source_group": row_group(row),
                "model": model_name,
                "ok": True,
                **metrics,
                **loo,
            })

    fieldnames = sorted({key for row in detail for key in row.keys()})
    with (OUT_DIR / "detail.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(detail)

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in detail:
        if row.get("ok") is True:
            groups[(row["ladder"], row["source_group"], row["model"])].append(row)
    aggregate = []
    for (ladder, source_group, model), rows in groups.items():
        agg = {"ladder": ladder, "source_group": source_group, "model": model, "n": len(rows)}
        for key in ["max_abs", "mean_abs", "p95_abs", "r2", "loo_max_abs", "loo_mean_abs", "loo_p95_abs", "loo_r2"]:
            vals = [float(row[key]) for row in rows if row.get(key) not in ("", None)]
            agg[f"{key}_mean"] = float(np.mean(vals)) if vals else ""
            agg[f"{key}_p95"] = float(np.percentile(vals, 95)) if vals else ""
        aggregate.append(agg)
    aggregate.sort(key=lambda row: (row["ladder"], row["source_group"], row.get("loo_mean_abs_mean") if row.get("loo_mean_abs_mean") != "" else 999.0))

    fieldnames = sorted({key for row in aggregate for key in row.keys()})
    with (OUT_DIR / "aggregate.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(aggregate)

    winners = []
    by_file: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in detail:
        if row.get("ok") is True and row.get("loo_mean_abs") not in ("", None):
            by_file[(row["raw_path"], row["ladder"])].append(row)
    for (_raw_path, _ladder), rows in by_file.items():
        winners.append(min(rows, key=lambda row: (float(row["loo_mean_abs"]), float(row["loo_max_abs"]), float(row["mean_abs"]))))
    fieldnames = sorted({key for row in winners for key in row.keys()})
    with (OUT_DIR / "winners.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(winners)

    print(OUT_DIR)
    print(f"detail_rows={len(detail)} winners={len(winners)}")


if __name__ == "__main__":
    main()
