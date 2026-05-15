from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gs500rox_start_strategy_shadow_eval import (  # noqa: E402
    GS500ROX_SIZES,
    analyze_path,
    build_candidates,
    corrected_trace,
    evaluate_strategies,
    linear_metrics,
    raw_trace,
)

DEFAULT_REVIEW_CSV = (
    ROOT
    / "local_triage"
    / "flt3_rox500_residual6_all_3730_2024_2026_2026-05-14_214626"
    / "FLT3_ROX500_QC_REVIEW_Annotated.csv"
)
DEFAULT_PANEL_ROWS = ROOT / "local_triage" / "flt3_35_50_detector_annotate_html" / "rows.csv"
DEFAULT_ANNOTATIONS = ROOT / "local_triage" / "flt3_35_50_detector_annotate_html" / "annotations_imported.csv"
DEFAULT_DATA_ROOT = Path("/Volumes/T7 Shield/DATA/flt3")
DEFAULT_OUT_DIR = ROOT / "local_triage" / "flt3_gs500rox_start_proposal_html"


def _safe_name(value: object) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value or ""))[:180]


def _as_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _json_list(values: list[int]) -> str:
    return json.dumps([int(value) for value in values], separators=(",", ":"))


def _load_cases(review_csv: Path, panel_rows: Path, annotations: Path, labels: set[str]) -> list[dict[str, Any]]:
    review = pd.read_csv(review_csv).reset_index(drop=True)
    review["ordinal"] = np.arange(1, len(review) + 1)

    panel = pd.read_csv(panel_rows)
    ann = pd.read_csv(annotations)
    panel = panel.merge(ann[["ordinal", "label", "note"]], on="ordinal", how="left", suffixes=("", "_user"))
    if labels:
        panel = panel[panel["label_user"].fillna("").isin(labels)].copy()

    merged = panel.merge(
        review,
        on=["ordinal", "File"],
        how="left",
        suffixes=("_panel", ""),
    )
    rows: list[dict[str, Any]] = []
    for item in merged.sort_values(["ordinal"]).to_dict("records"):
        rows.append(item)
    return rows


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _resolve_case_path(case: dict[str, Any], data_root: Path) -> Path:
    file_name = _text(case.get("File") or case.get("file"))
    source = _text(case.get("SourceRunDir"))
    for prefix in ("2026", "2025", "2024"):
        if source:
            candidate = data_root / prefix / source / file_name
            if candidate.exists():
                return candidate
    if source:
        direct = data_root / source / file_name
        if direct.exists():
            return direct
    matches = list(data_root.rglob(file_name)) if file_name else []
    if source:
        for match in matches:
            if match.parent.name == source:
                return match
    return matches[0] if matches else data_root / source / file_name


def _render_image(
    row: dict[str, Any],
    trace: np.ndarray,
    current: list[int],
    proposed: list[int],
    strategy: str,
    out_dir: Path,
) -> str:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    ordinal = int(row.get("ordinal") or 0)
    file_name = str(row.get("File") or row.get("file") or "")
    out = image_dir / f"{ordinal:03d}_{_safe_name(Path(file_name).stem)}_{_safe_name(strategy)}.png"

    focus = current[:7] + proposed[:7]
    x_min = max(1200, min(focus + [1300]) - 180)
    x_max = min(trace.size - 1, max(focus + [2350]) + 260)
    window = trace[x_min:x_max] if x_max > x_min else trace
    y_max = max(260.0, float(np.nanpercentile(window, 99.6) * 1.22)) if window.size else 1500.0
    selected_heights = [float(trace[idx]) for idx in focus if 0 <= idx < trace.size]
    if selected_heights:
        y_max = max(y_max, max(selected_heights) * 1.20 + 40.0)
    y_max = min(y_max, 7000.0)

    fig, ax = plt.subplots(figsize=(15, 5.2), dpi=150)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.85, label="DATA4 corrected")

    visible_current = [scan for scan in current[:7] if x_min <= scan <= x_max and 0 <= scan < trace.size]
    visible_proposed = [scan for scan in proposed[:7] if x_min <= scan <= x_max and 0 <= scan < trace.size]
    ax.scatter(
        visible_current,
        [trace[scan] for scan in visible_current],
        marker="x",
        s=72,
        linewidth=1.5,
        color="#dc2626",
        label="current",
        zorder=4,
    )
    ax.scatter(
        visible_proposed,
        [trace[scan] for scan in visible_proposed],
        marker="o",
        s=48,
        facecolors="none",
        edgecolors="#2563eb",
        linewidth=1.5,
        label="proposal",
        zorder=5,
    )
    for idx, scan in enumerate(current[:7]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.text(scan, min(y_max * 0.92, trace[scan] + y_max * 0.035), str(GS500ROX_SIZES[idx]), ha="center", fontsize=7, color="#991b1b")
    for idx, scan in enumerate(proposed[:7]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.text(scan, min(y_max * 0.99, trace[scan] + y_max * 0.080), str(GS500ROX_SIZES[idx]), ha="center", fontsize=8, color="#1d4ed8", fontweight="bold")

    ax.set_title(
        f"{ordinal:03d} {file_name} | {row.get('label_user') or ''} | proposal {strategy}",
        fontsize=10,
    )
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-max(35.0, y_max * 0.04), y_max)
    ax.set_xlabel("scan")
    ax.set_ylabel("RFU")
    ax.grid(alpha=0.16)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out.relative_to(out_dir).as_posix()


def _local_maxima(trace: np.ndarray, start: int, end: int) -> list[tuple[int, float, float]]:
    start = max(2, int(start))
    end = min(trace.size - 3, int(end))
    peaks: list[tuple[int, float, float]] = []
    for idx in range(start, end + 1):
        value = float(trace[idx])
        if value < 8.0:
            continue
        if not (value >= trace[idx - 1] and value > trace[idx + 1] and value >= trace[idx - 2] and value >= trace[idx + 2]):
            continue
        left = float(np.min(trace[max(0, idx - 12) : idx + 1]))
        right = float(np.min(trace[idx : min(trace.size, idx + 13)]))
        prominence = value - max(left, right)
        if prominence >= 4.0:
            peaks.append((idx, value, prominence))
    peaks.sort(key=lambda item: -item[1])
    kept: list[tuple[int, float, float]] = []
    for peak in peaks:
        if all(abs(peak[0] - existing[0]) > 5 for existing in kept):
            kept.append(peak)
    return sorted(kept, key=lambda item: item[0])


def _insert_mid_50_proposal(current: list[int], trace: np.ndarray) -> list[int]:
    if len(current) != len(GS500ROX_SIZES) or trace.size == 0:
        return current
    proposed_35 = current[1]
    # In the reviewed cases, the true 50 bp peak is usually a real local peak
    # roughly one early-family gap after the selected 50/current true 35.
    expected_50 = proposed_35 + 72
    window_start = max(proposed_35 + 42, expected_50 - 26)
    window_end = min(current[2] - 10, expected_50 + 34)
    peaks = _local_maxima(trace, window_start, window_end)
    if not peaks:
        peaks = _local_maxima(trace, proposed_35 + 25, current[2] - 8)
    if not peaks:
        return [current[1]] + current[2:]

    def score(item: tuple[int, float, float]) -> tuple[float, float]:
        scan, height, prominence = item
        distance_penalty = abs(scan - expected_50) * 7.0
        return (-(height + prominence * 0.35 - distance_penalty), scan)

    chosen_50 = sorted(peaks, key=score)[0][0]
    return [proposed_35, chosen_50] + current[2:]


def _button(value: str, label: str) -> str:
    return f"<button type='button' data-value='{html.escape(value)}'>{html.escape(label)}</button>"


def _write_html(rows: list[dict[str, Any]], out_dir: Path) -> None:
    payload = {
        "review_class": "flt3_gs500rox_start_proposal",
        "rows": [
            {
                "ordinal": row["ordinal"],
                "file": row["File"],
                "raw_path": row["raw_path"],
                "current_selected": row["current_selected"],
                "proposed_selected": row["proposed_selected"],
                "proposal_strategy": row["proposal_strategy"],
                "user_label": row.get("label_user", ""),
            }
            for row in rows
        ],
    }
    cards: list[str] = []
    for row in rows:
        current = html.escape(str(row.get("current_start") or ""))
        proposed = html.escape(str(row.get("proposed_start") or ""))
        changed = html.escape(str(row.get("changed_steps") or ""))
        reason = html.escape(str(row.get("ReviewReason") or row.get("reason") or ""))
        metrics = (
            f"current {row.get('current_linear_max'):.2f}/{row.get('current_linear_mean'):.2f}/"
            f"{row.get('current_linear_r2'):.6f} -> proposal {row.get('proposal_linear_max'):.2f}/"
            f"{row.get('proposal_linear_mean'):.2f}/{row.get('proposal_linear_r2'):.6f}"
        )
        buttons = "".join(
            [
                _button("proposal_correct", "Proposal correct"),
                _button("current_correct", "Current correct"),
                _button("proposal_close", "Close/minor"),
                _button("weak_bad_ladder", "Weak/bad ladder"),
                _button("unclear", "Unclear"),
            ]
        )
        cards.append(
            f"""
<section class="case" data-key="{html.escape(str(row['raw_path']))}">
  <div class="case-head">
    <div>
      <div class="title">{int(row['ordinal']):03d}. {html.escape(str(row['File']))}</div>
      <div class="meta">{html.escape(str(row.get('label_user') or ''))} | {html.escape(str(row.get('DetectorCategory') or row.get('category') or ''))} | {html.escape(metrics)}</div>
      <div class="anchors">current start: {current}</div>
      <div class="anchors">proposal start: {proposed}</div>
      <div class="anchors">changed: {changed}</div>
      <div class="reason">{reason}</div>
    </div>
    <div class="buttons">{buttons}</div>
  </div>
  <img src="{html.escape(str(row['image']))}" alt="{html.escape(str(row['File']))}">
  <textarea placeholder="Kommentar...">{html.escape(str(row.get('note') or row.get('note_user') or ''))}</textarea>
</section>
"""
        )
    payload_json = json.dumps(payload).replace("</", "<\\/")
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FLT3 GS500ROX Start Proposals</title>
<style>
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f7f9; color:#111827; }}
header {{ position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid #d1d5db; padding:12px 18px; display:flex; justify-content:space-between; gap:16px; align-items:center; }}
h1 {{ margin:0; font-size:18px; }}
.sub {{ color:#4b5563; font-size:13px; }}
main {{ max-width:1500px; margin:0 auto; padding:16px; }}
.case {{ background:#fff; border:1px solid #d1d5db; border-radius:8px; margin:0 0 18px; padding:12px; }}
.case-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:10px; }}
.title {{ font-weight:700; font-size:15px; }}
.meta,.anchors,.reason {{ margin-top:4px; color:#374151; font-size:12px; }}
.reason {{ color:#6b7280; }}
img {{ display:block; width:100%; height:auto; border:1px solid #e5e7eb; border-radius:4px; background:white; }}
button {{ border:1px solid #9ca3af; background:#fff; border-radius:6px; padding:6px 9px; cursor:pointer; margin:0 0 5px 5px; }}
button.active {{ background:#111827; color:#fff; border-color:#111827; }}
textarea {{ width:100%; min-height:62px; margin-top:10px; box-sizing:border-box; border:1px solid #cbd5e1; border-radius:6px; padding:8px; font:14px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
#export {{ background:#111827; color:white; border-color:#111827; }}
</style>
</head>
<body>
<header>
  <div><h1>FLT3 GS500ROX Start Proposals</h1><div class="sub">{len(rows)} cases. Red x = current, blue circle = proposal.</div></div>
  <button id="export" type="button">Export annotations</button>
</header>
<main>
{''.join(cards)}
</main>
<script>
const payload = {payload_json};
const storageKey = "flt3_gs500rox_start_proposal_annotations";
const state = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
document.querySelectorAll(".case").forEach((card, idx) => {{
  const key = payload.rows[idx].raw_path;
  const saved = state[key] || {{}};
  if (saved.label) {{
    const btn = card.querySelector(`button[data-value="${{saved.label}}"]`);
    if (btn) btn.classList.add("active");
  }}
  const textarea = card.querySelector("textarea");
  if (saved.note) textarea.value = saved.note;
  card.querySelectorAll("button[data-value]").forEach(btn => {{
    btn.addEventListener("click", () => {{
      card.querySelectorAll("button[data-value]").forEach(item => item.classList.remove("active"));
      btn.classList.add("active");
      state[key] = {{...(state[key] || {{}}), label: btn.dataset.value, note: textarea.value}};
      localStorage.setItem(storageKey, JSON.stringify(state));
    }});
  }});
  textarea.addEventListener("input", () => {{
    state[key] = {{...(state[key] || {{}}), note: textarea.value}};
    localStorage.setItem(storageKey, JSON.stringify(state));
  }});
}});
document.getElementById("export").addEventListener("click", () => {{
  const rows = payload.rows.map(row => {{
    const saved = state[row.raw_path] || {{}};
    return {{...row, label: saved.label || "", note: saved.note || ""}};
  }});
  const blob = new Blob([JSON.stringify({{exported_at: new Date().toISOString(), rows}}, null, 2)], {{type:"application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "flt3_gs500rox_start_proposal_annotations.json";
  a.click();
  URL.revokeObjectURL(a.href);
}});
</script>
</body>
</html>
"""
    (out_dir / "review_panel.html").write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render FLT3 GS500ROX 35/50 start proposal annotation HTML.")
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    parser.add_argument("--panel-rows", type=Path, default=DEFAULT_PANEL_ROWS)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--labels", default="move_both_right,move_35_right", help="Comma-separated user labels to include; empty means all.")
    parser.add_argument(
        "--proposal-mode",
        choices=["score", "visual-label-shift", "insert-mid-50"],
        default="score",
        help="score uses ranked candidate trials; visual-label-shift relabels current 50/75/100... as 35/50/75...; insert-mid-50 keeps current 75+ and inserts a local 50 after current 50-as-35.",
    )
    args = parser.parse_args()

    labels = {part.strip() for part in args.labels.split(",") if part.strip()}
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cases = _load_cases(args.review_csv, args.panel_rows, args.annotations, labels)
    summary_rows: list[dict[str, Any]] = []
    trial_rows: list[dict[str, Any]] = []

    for idx, case in enumerate(cases, start=1):
        path = _resolve_case_path(case, args.data_root)
        case["raw_path"] = str(path)
        print(f"[{idx}/{len(cases)}] {case.get('File')} {case.get('label_user')}", flush=True)
        if not path.exists():
            summary_rows.append({**case, "ok": False, "error": "missing raw path"})
            continue
        analysis = analyze_path(path, args.timeout)
        if not analysis.get("ok"):
            summary_rows.append({**case, "ok": False, "error": analysis.get("error", "")})
            continue
        current = [int(value) for value in analysis.get("selected") or []]
        if len(current) != len(GS500ROX_SIZES):
            summary_rows.append({**case, "ok": False, "error": f"selected_count={len(current)}"})
            continue
        trace = corrected_trace(raw_trace(path, analysis.get("channel") or "DATA4"))
        candidates = build_candidates(analysis, trace, current)
        trials = evaluate_strategies(current, candidates)
        current_trial = next(trial for trial in trials if trial.strategy == "current")
        if args.proposal_mode == "visual-label-shift":
            proposal_strategy = "visual_label_shift_current_50_to_35"
            proposed_selected = current[1:] + [current[-1]]
            proposal_linear_max = float("nan")
            proposal_linear_mean = float("nan")
            proposal_linear_r2 = float("nan")
        elif args.proposal_mode == "insert-mid-50":
            proposal_strategy = "insert_mid_50_keep_75_plus"
            proposed_selected = _insert_mid_50_proposal(current, trace)
            proposal_linear_max, proposal_linear_mean, proposal_linear_r2 = linear_metrics(proposed_selected)
        else:
            proposal = next((trial for trial in trials if trial.strategy != "current"), current_trial)
            proposal_strategy = proposal.strategy
            proposed_selected = proposal.selected
            proposal_linear_max = proposal.linear_max
            proposal_linear_mean = proposal.linear_mean
            proposal_linear_r2 = proposal.linear_r2
        image = _render_image(case, trace, current, proposed_selected, proposal_strategy, args.out_dir)
        changed_steps = [
            GS500ROX_SIZES[pos]
            for pos, (left, right) in enumerate(zip(current, proposed_selected))
            if int(left) != int(right)
        ]
        row = {
            **case,
            "ok": True,
            "channel": analysis.get("channel", ""),
            "candidate_count": len(candidates),
            "current_selected": _json_list(current),
            "proposed_selected": _json_list(proposed_selected),
            "current_start": _json_list(current[:7]),
            "proposed_start": _json_list(proposed_selected[:7]),
            "proposal_strategy": proposal_strategy,
            "current_linear_max": current_trial.linear_max,
            "current_linear_mean": current_trial.linear_mean,
            "current_linear_r2": current_trial.linear_r2,
            "proposal_linear_max": proposal_linear_max,
            "proposal_linear_mean": proposal_linear_mean,
            "proposal_linear_r2": proposal_linear_r2,
            "delta_linear_max": proposal_linear_max - current_trial.linear_max,
            "delta_linear_mean": proposal_linear_mean - current_trial.linear_mean,
            "changed_steps": _json_list(changed_steps),
            "image": image,
        }
        summary_rows.append(row)
        for rank, trial in enumerate(trials[:16], start=1):
            trial_rows.append(
                {
                    "ordinal": case.get("ordinal", ""),
                    "File": case.get("File", ""),
                    "label": case.get("label_user", ""),
                    "rank": rank,
                    "strategy": trial.strategy,
                    "selected": _json_list(trial.selected),
                    "linear_max": trial.linear_max,
                    "linear_mean": trial.linear_mean,
                    "linear_r2": trial.linear_r2,
                    "score": trial.score,
                    "note": trial.note,
                }
            )

    for name, rows in [("proposal_rows.csv", summary_rows), ("proposal_trials.csv", trial_rows)]:
        with (args.out_dir / name).open("w", newline="", encoding="utf-8") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
    ok_rows = [row for row in summary_rows if row.get("ok")]
    _write_html(ok_rows, args.out_dir)
    summary = {
        "rows": len(summary_rows),
        "ok_rows": len(ok_rows),
        "html": str(args.out_dir / "review_panel.html"),
        "labels": sorted(labels),
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
