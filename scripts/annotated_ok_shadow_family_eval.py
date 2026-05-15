from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.evaluate_rust_apex_recenter_live as live_eval
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker


LADDER_SIZES = {
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
}


def linear_metrics(scans: list[int], bps: list[int]) -> tuple[float, float, float]:
    if len(scans) != len(bps) or len(scans) < 3:
        return (math.nan, math.nan, math.nan)
    x = np.asarray(scans, dtype=float)
    y = np.asarray(bps, dtype=float)
    slope, intercept = np.linalg.lstsq(np.vstack([x, np.ones_like(x)]).T, y, rcond=None)[0]
    pred = slope * x + intercept
    resid = y - pred
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return float(np.max(np.abs(resid))), float(np.mean(np.abs(resid))), float(1.0 - ss_res / ss_tot if ss_tot else 1.0)


def clean_candidates(peaks: list[dict], ladder: str, mode: str) -> list[dict]:
    if ladder == "ROX400HD":
        lo, hi = 1450, 4300
        min_prom = 55.0 if mode == "broad" else 140.0
        max_br = 0.45 if mode == "broad" else 0.25
        min_purity = 0.50 if mode == "broad" else 0.72
    else:
        lo, hi = 1250, 4700
        min_prom = 45.0 if mode == "broad" else 55.0
        max_br = 0.45 if mode == "broad" else 0.40
        min_purity = 0.48 if mode == "broad" else 0.55
    out = []
    for peak in peaks:
        idx = int(peak.get("index", -1))
        height = max(float(peak.get("height", 0.0) or 0.0), 1.0)
        prom = float(peak.get("prominence", 0.0) or 0.0)
        baseline = max(float(peak.get("local_baseline", 0.0) or 0.0), 0.0)
        br = baseline / height
        purity = prom / height
        if lo <= idx <= hi and height >= 80.0 and prom >= min_prom and br <= max_br and purity >= min_purity:
            out.append({**peak, "index": idx, "height_f": height, "prom_f": prom, "br": br, "purity": purity})
    out.sort(key=lambda p: p["index"])
    return out


def family_subset(peaks: list[dict], ladder: str, mode: str) -> list[int]:
    clean = clean_candidates(peaks, ladder, mode)
    sizes = LADDER_SIZES.get(ladder, [])
    if len(clean) < len(sizes):
        return []
    heights = np.asarray([p["height_f"] for p in clean], dtype=float)
    href = float(np.median(heights))
    if mode == "strict":
        max_log = 0.38 if ladder == "ROX400HD" else 0.95
        max_take = len(sizes)
    elif mode == "broad":
        max_log = 0.75 if ladder == "ROX400HD" else 1.05
        max_take = min(len(clean), len(sizes) + (8 if ladder == "ROX400HD" else 5))
    else:
        max_log = 0.55 if ladder == "ROX400HD" else 0.95
        max_take = min(len(clean), len(sizes) + 3)
    ranked = []
    for p in clean:
        d = abs(math.log(p["height_f"] / href))
        if d <= max_log:
            ranked.append((d + p["br"] * 0.25 + max(0.0, 1.0 - p["purity"]) * 0.20, p))
    ranked.sort(key=lambda item: (item[0], item[1]["index"]))
    chosen = sorted(p["index"] for _, p in ranked[:max_take])
    return chosen


def beam_family(peaks: list[dict], ladder: str, mode: str) -> list[int]:
    sizes = LADDER_SIZES.get(ladder, [])
    pool = family_subset(peaks, ladder, mode)
    if len(pool) < len(sizes):
        return []
    if len(pool) == len(sizes):
        return pool
    beam: list[list[int]] = [[]]
    for step in range(len(sizes)):
        next_states: list[list[int]] = []
        remaining_after = len(sizes) - step - 1
        for prefix in beam:
            last = prefix[-1] if prefix else -1
            for idx_pos, idx in enumerate(pool):
                if idx <= last:
                    continue
                if len(pool) - idx_pos - 1 < remaining_after:
                    continue
                if prefix and idx - last > (340 if ladder == "ROX400HD" else 420):
                    continue
                trial = prefix + [idx]
                next_states.append(trial)
        if not next_states:
            return []
        def rank(state: list[int]) -> tuple[float, float, float, list[int]]:
            part_sizes = sizes[: len(state)]
            if len(state) >= 3:
                mx, mean, r2 = linear_metrics(state, part_sizes)
            else:
                mx, mean, r2 = (0.0, 0.0, 1.0)
            gap_cost = 0.0
            if len(state) >= 2:
                gaps = np.diff(state)
                gap_cost = float(np.std(gaps)) / 200.0
            return (mx + mean * 0.8 + gap_cost + max(0.0, 0.999 - r2) * 500.0, mean, -r2, state)
        next_states.sort(key=rank)
        beam = next_states[:240]
    best = min(beam, key=lambda state: linear_metrics(state, sizes)[:2] + (-linear_metrics(state, sizes)[2],))
    return best


def main() -> None:
    annotations = json.loads((ROOT / "local_triage/ok_182_browser_annotations.json").read_text())
    rows = pd.read_csv(ROOT / "local_triage/ok_182_median_family_html/review_rows.tsv", sep="\t")
    rows["label"] = rows["raw_path"].map(lambda p: (annotations.get(p) or {}).get("label", ""))
    rows = rows[(rows["label"] != "") & (rows["label"] != "operator")].copy().reset_index(drop=True)
    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker unavailable")
    out = []
    for i, row in rows.iterrows():
        analysis = live_eval.analyze_path(worker, Path(row.raw_path))
        if str(analysis.get("error", "")).startswith("worker timeout") or analysis.get("error") == "no response":
            _invalidate_rust_worker()
            worker = _get_rust_worker()
            analysis = live_eval.analyze_path(worker, Path(row.raw_path))
        result = analysis.get("result") or {}
        preview = result.get("ladder_fit_preview") or {}
        selected = live_eval.selected_scans(preview)
        ladder = str(analysis.get("ladder") or row.ladder)
        sizes = LADDER_SIZES.get(ladder, [])
        cur = linear_metrics(selected, sizes)
        peaks = result.get("ladder_peak_preview") or []
        record = {"ordinal": int(row.ordinal), "file": row.file, "raw_path": row.raw_path, "label": row.label, "ladder": ladder, "current_selected": json.dumps(selected), "current_max": cur[0], "current_mean": cur[1], "current_r2": cur[2]}
        for mode in ["strict", "medium", "broad"]:
            proposal = beam_family(peaks, ladder, mode)
            metrics = linear_metrics(proposal, sizes) if proposal else (math.nan, math.nan, math.nan)
            record[f"{mode}_selected"] = json.dumps(proposal)
            record[f"{mode}_max"] = metrics[0]
            record[f"{mode}_mean"] = metrics[1]
            record[f"{mode}_r2"] = metrics[2]
            record[f"{mode}_changed"] = bool(proposal and proposal != selected)
        out.append(record)
        if (i + 1) % 50 == 0:
            print(f"shadow {i+1}/{len(rows)}", flush=True)
    out_df = pd.DataFrame(out)
    out_path = ROOT / "local_triage/ok_182_shadow_family_eval.tsv"
    out_df.to_csv(out_path, sep="\t", index=False)
    print(json.dumps({"rows": len(out_df), "out": str(out_path)}, indent=2))


if __name__ == "__main__":
    main()
