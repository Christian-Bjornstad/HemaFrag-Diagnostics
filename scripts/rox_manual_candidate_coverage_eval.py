from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.evaluate_rust_apex_recenter_live as live_eval
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker


OUT_DIR = ROOT / "artifacts" / "rox_manual_candidate_coverage_2026-05-05"
LEARNING_CASES = ROOT / "artifacts" / "overnight_manual_review_learning_2026-05-05" / "manual_review_learning_cases.tsv"

ROX_SIZES = [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400]
EXCLUDED_CATEGORIES = {"operator_or_bad_ladder", "accepted_current_fit", "accepted_or_cosmetic_manual_save"}


def manual_adjustment_path(raw_path: Path) -> Path:
    return raw_path.with_suffix(".ladder_adj.json")


def load_manual_times(raw_path: Path) -> list[int]:
    path = manual_adjustment_path(raw_path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    mapping_times = payload.get("mapping_times") or {}
    rows: list[tuple[int, int]] = []
    for key, value in mapping_times.items():
        try:
            rows.append((int(key), int(round(float(value)))))
        except (TypeError, ValueError):
            continue
    return [scan for _step, scan in sorted(rows)]


def safe_analyze(worker, path: Path) -> dict:
    response = worker.request(path, "clonality", 45)
    if not response or not response.get("ok"):
        error = (response or {}).get("error", "no response")
        if str(error).startswith("worker timeout") or error == "no response":
            _invalidate_rust_worker()
            worker = _get_rust_worker()
            if worker is not None:
                response = worker.request(path, "clonality", 120)
    if not response or not response.get("ok"):
        return {"ok": False, "error": (response or {}).get("error", "no response")}
    result = response.get("result") if isinstance(response.get("result"), dict) else response
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    return {
        "ok": True,
        "result": result,
        "selected": live_eval.selected_scans(preview),
        "linear_max": metrics.get("linear_trend_max_abs_error_bp"),
        "linear_mean": metrics.get("linear_trend_mean_abs_error_bp"),
        "linear_r2": metrics.get("linear_trend_r2"),
        "review": bool(review.get("suggested_review")),
        "reason_codes": review.get("reason_codes") or [],
    }


def nearest_candidate(candidates: list[int], target: int) -> tuple[int | None, int | None]:
    if not candidates:
        return None, None
    nearest = min(candidates, key=lambda value: abs(value - target))
    return nearest, abs(nearest - target)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = pd.read_csv(LEARNING_CASES, sep="\t")
    cases = cases[
        (cases["ladder"].astype(str).str.upper() == "ROX")
        & (cases["label"].astype(str) == "manual_adjusted")
        & (~cases["learning_category"].astype(str).isin(EXCLUDED_CATEGORIES))
    ].copy()
    cases = cases[cases["manual_count"].fillna(0).astype(int) == len(ROX_SIZES)].copy()

    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker unavailable")

    case_rows: list[dict] = []
    step_rows: list[dict] = []

    for row in cases.itertuples(index=False):
        raw_path = Path(str(row.full_path))
        manual = load_manual_times(raw_path)
        analysis = safe_analyze(worker, raw_path)
        if not analysis.get("ok"):
            case_rows.append(
                {
                    "file": raw_path.name,
                    "raw_path": str(raw_path),
                    "ok": False,
                    "error": analysis.get("error", ""),
                    "category": row.learning_category,
                    "tags": row.tags,
                    "note": row.note,
                }
            )
            continue
        result = analysis["result"]
        candidates = sorted({int(peak.get("index")) for peak in result.get("ladder_peak_preview") or [] if peak.get("index") is not None})
        selected = [int(value) for value in analysis.get("selected") or []]
        selected_changed = sum(1 for idx, value in enumerate(manual) if idx >= len(selected) or int(value) != int(selected[idx]))
        cover2 = cover5 = cover10 = cover20 = 0
        auto_match = 0
        max_nearest_delta = 0
        for idx, target in enumerate(manual[: len(ROX_SIZES)]):
            nearest, delta = nearest_candidate(candidates, int(target))
            delta_value = int(delta) if delta is not None else 999999
            max_nearest_delta = max(max_nearest_delta, delta_value)
            cover2 += int(delta_value <= 2)
            cover5 += int(delta_value <= 5)
            cover10 += int(delta_value <= 10)
            cover20 += int(delta_value <= 20)
            auto_delta = abs(selected[idx] - int(target)) if idx < len(selected) else 999999
            auto_match += int(auto_delta <= 2)
            step_rows.append(
                {
                    "file": raw_path.name,
                    "step": idx + 1,
                    "bp": ROX_SIZES[idx],
                    "manual_scan": int(target),
                    "auto_scan": selected[idx] if idx < len(selected) else "",
                    "auto_delta": auto_delta,
                    "nearest_candidate": nearest if nearest is not None else "",
                    "nearest_candidate_delta": delta_value,
                    "covered_2": delta_value <= 2,
                    "covered_5": delta_value <= 5,
                    "covered_10": delta_value <= 10,
                    "covered_20": delta_value <= 20,
                    "manual_diff_from_auto": idx >= len(selected) or selected[idx] != int(target),
                }
            )
        case_rows.append(
            {
                "file": raw_path.name,
                "raw_path": str(raw_path),
                "ok": True,
                "category": row.learning_category,
                "tags": row.tags,
                "note": row.note,
                "candidate_count": len(candidates),
                "selected_changed_vs_manual": selected_changed,
                "manual_candidate_coverage_2": cover2,
                "manual_candidate_coverage_5": cover5,
                "manual_candidate_coverage_10": cover10,
                "manual_candidate_coverage_20": cover20,
                "auto_match_2": auto_match,
                "max_nearest_candidate_delta": max_nearest_delta,
                "auto_first": selected[0] if selected else "",
                "manual_first": manual[0] if manual else "",
                "auto_last": selected[-1] if selected else "",
                "manual_last": manual[-1] if manual else "",
                "linear_max": analysis.get("linear_max"),
                "linear_mean": analysis.get("linear_mean"),
                "linear_r2": analysis.get("linear_r2"),
                "review": analysis.get("review"),
                "reason_codes": json.dumps(analysis.get("reason_codes") or []),
                "selected": json.dumps(selected),
                "manual": json.dumps(manual),
            }
        )

    case_df = pd.DataFrame(case_rows)
    step_df = pd.DataFrame(step_rows)
    case_df.to_csv(OUT_DIR / "case_summary.tsv", sep="\t", index=False)
    step_df.to_csv(OUT_DIR / "step_coverage.tsv", sep="\t", index=False)

    if not case_df.empty:
        ok = case_df[case_df["ok"] == True]  # noqa: E712
        lines = [
            "# ROX Manual Candidate Coverage",
            "",
            f"- evaluated cases: {len(ok)}",
            f"- median coverage <=2 scans: {ok['manual_candidate_coverage_2'].median():.1f}/21",
            f"- median coverage <=5 scans: {ok['manual_candidate_coverage_5'].median():.1f}/21",
            f"- median coverage <=10 scans: {ok['manual_candidate_coverage_10'].median():.1f}/21",
            f"- median auto match <=2 scans: {ok['auto_match_2'].median():.1f}/21",
            "",
            "## Cases",
        ]
        for item in ok.sort_values(["manual_candidate_coverage_5", "linear_max"], ascending=[True, False]).itertuples(index=False):
            lines.append(
                f"- {item.file}: cand5={item.manual_candidate_coverage_5}/21, "
                f"cand10={item.manual_candidate_coverage_10}/21, auto2={item.auto_match_2}/21, "
                f"changed={item.selected_changed_vs_manual}, max/mean/r2={float(item.linear_max):.2f}/{float(item.linear_mean):.2f}/{float(item.linear_r2):.6f}"
            )
        (OUT_DIR / "report.md").write_text("\n".join(lines) + "\n")
        print("\n".join(lines[:10]))
        print(f"out={OUT_DIR}")


if __name__ == "__main__":
    main()
