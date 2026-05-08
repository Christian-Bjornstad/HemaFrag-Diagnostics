"""
HemaFrag Diagnostics — Ladder Review Web Tab
"""
from __future__ import annotations

import copy
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import panel as pn
import pandas as pd
import plotly.graph_objects as go

from core.analysis import (
    apply_manual_ladder_mapping,
    compute_ladder_qc_metrics,
    get_ladder_candidates,
    save_ladder_adjustment,
)
from gui.components import make_card, section_header, VSpace
from gui_qt.ladder_utils import load_adjustable_fsa


@dataclass
class ReviewState:
    bundle_dir: Path | None = None
    case_rows: list[dict] | None = None
    current_case: dict | None = None
    current_file: Path | None = None
    current_fsa: object | None = None
    current_candidates: pd.DataFrame | None = None
    current_mapping: dict[int, int] | None = None
    current_manual_candidates: list[float] | None = None
    current_auto_mapping: dict[int, int] | None = None


def make_ladder_review_tab() -> pn.Column:
    state = ReviewState(case_rows=[], current_mapping={}, current_manual_candidates=[], current_auto_mapping={})

    bundle_dir = pn.widgets.TextInput(
        name="Review Bundle",
        value="/Users/christian/Desktop/HemaFrag/review_bundle_overnight_soft_fail_2026-05-05",
        placeholder="/path/to/review_bundle_xxx",
        sizing_mode="stretch_width",
    )
    load_btn = pn.widgets.Button(name="Load Bundle", button_type="primary", width=140)
    save_btn = pn.widgets.Button(name="Save Adjustment + Note", button_type="primary", width=190)
    note_btn = pn.widgets.Button(name="Save Note Only", button_type="default", width=140)
    prev_btn = pn.widgets.Button(name="Previous", button_type="default", width=100)
    next_btn = pn.widgets.Button(name="Next", button_type="default", width=90)
    next_unreviewed_btn = pn.widgets.Button(name="Next Unreviewed", button_type="success", width=150)
    reset_btn = pn.widgets.Button(name="Reset Auto", button_type="default", width=110)
    clear_btn = pn.widgets.Button(name="Clear Step", button_type="warning", width=100)

    case_select = pn.widgets.Select(name="Case", options={}, sizing_mode="stretch_width")
    step_select = pn.widgets.Select(name="Target Ladder Step", options={}, sizing_mode="stretch_width")
    comment = pn.widgets.TextAreaInput(
        name="Comment",
        placeholder="Write note about missing ladder, chosen peaks, or why the fit is acceptable.",
        height=140,
        sizing_mode="stretch_width",
    )
    status = pn.pane.HTML(
        '<div style="color:var(--text-muted); font-size:13px;">Load a review bundle to start.</div>',
        sizing_mode="stretch_width",
    )
    metrics = pn.pane.HTML(
        '<div style="color:var(--text-muted); font-size:13px;">No case loaded.</div>',
        sizing_mode="stretch_width",
    )
    case_meta = pn.pane.HTML("", sizing_mode="stretch_width")
    assignment_table = pn.widgets.Tabulator(
        pd.DataFrame(columns=["step_idx", "expected_bp", "candidate_idx", "candidate_time", "candidate_intensity"]),
        sizing_mode="stretch_width",
        height=260,
        disabled=True,
        show_index=False,
    )
    candidate_table = pn.widgets.Tabulator(
        pd.DataFrame(columns=["candidate_idx", "time", "intensity", "source", "assigned_bp", "rust_selected"]),
        sizing_mode="stretch_width",
        height=280,
        disabled=True,
        show_index=False,
    )
    figure_pane = pn.pane.Plotly(height=520, sizing_mode="stretch_width", config={"scrollZoom": True})

    def _set_status(text: str, color: str = "var(--text-muted)") -> None:
        status.object = f'<div style="color:{color}; font-size:13px; font-weight:600;">{text}</div>'

    def _load_bundle_rows(path: Path) -> list[dict]:
        cases_path = path / "ladder_review_cases.csv"
        if not cases_path.exists():
            raise FileNotFoundError(f"Missing {cases_path}")
        rows: list[dict] = []
        with cases_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                full_path = Path(str(row.get("full_path", "") or "")).expanduser()
                if full_path.exists():
                    row["full_path"] = str(full_path)
                    rows.append(row)
        return rows

    def _label_for_case(row: dict) -> str:
        parts = [Path(row["full_path"]).name]
        existing_label = str(row.get("label", "") or "").strip()
        if existing_label:
            parts.append(f"[{existing_label}]")
        for key in ("assay", "well", "ladder"):
            value = str(row.get(key, "") or "").strip()
            if value:
                parts.append(value)
        for key, label in (("linear_max", "max"), ("linear_r2", "r2")):
            value = row.get(key)
            if value not in (None, ""):
                try:
                    num = float(value)
                    parts.append(f"{label} {num:.2f}" if key != "linear_r2" else f"{label} {num:.5f}")
                except Exception:
                    parts.append(f"{label} {value}")
        return " · ".join(parts)

    def _mapping_from_fsa(fsa, candidates: pd.DataFrame) -> dict[int, int]:
        mapping: dict[int, int] = {}
        best = list(np.asarray(getattr(fsa, "best_size_standard", []), dtype=float))
        fitted_steps = np.asarray(getattr(fsa, "ladder_steps", []), dtype=float)
        expected_steps = np.asarray(getattr(fsa, "expected_ladder_steps", fitted_steps), dtype=float)
        if not best or candidates.empty or fitted_steps.size == 0:
            return mapping
        for fitted_idx, peak_time in enumerate(best):
            if peak_time <= 0:
                continue
            matches = np.where(np.isclose(expected_steps, fitted_steps[fitted_idx], atol=1e-6))[0]
            if matches.size == 0:
                continue
            candidate_matches = np.where(np.isclose(candidates["time"].astype(float).to_numpy(), peak_time, atol=1e-6))[0]
            if candidate_matches.size == 0:
                continue
            mapping[int(matches[0])] = int(candidate_matches[0])
        return mapping

    def _candidate_used_by(cand_idx: int) -> int | None:
        for step_idx, mapped_idx in (state.current_mapping or {}).items():
            if mapped_idx == cand_idx:
                return step_idx
        return None

    def _next_step_index(current_step: int | None) -> int | None:
        fsa = state.current_fsa
        if fsa is None:
            return None
        expected_steps = np.asarray(getattr(fsa, "expected_ladder_steps", getattr(fsa, "ladder_steps", [])), dtype=float)
        if expected_steps.size == 0:
            return None
        mapping = state.current_mapping or {}
        if current_step is None:
            for idx in range(len(expected_steps)):
                if idx not in mapping:
                    return idx
            return 0
        for idx in range(current_step + 1, len(expected_steps)):
            if idx not in mapping:
                return idx
        for idx in range(len(expected_steps)):
            if idx not in mapping:
                return idx
        if current_step + 1 < len(expected_steps):
            return current_step + 1
        return min(current_step, len(expected_steps) - 1)

    def _review_progress_text() -> str:
        rows = state.case_rows or []
        if not rows:
            return "No bundle loaded."
        reviewed = sum(1 for row in rows if str(row.get("label", "") or "").strip())
        current = ""
        if case_select.value is not None:
            current = f" | Current {int(case_select.value) + 1}/{len(rows)}"
        return f"Reviewed {reviewed}/{len(rows)}{current}"

    def _refresh_case_options() -> None:
        rows = state.case_rows or []
        current_value = case_select.value
        case_select.options = {_label_for_case(row): idx for idx, row in enumerate(rows)}
        if rows and current_value is not None:
            case_select.value = min(int(current_value), len(rows) - 1)

    def _set_case_index(case_idx: int) -> None:
        rows = state.case_rows or []
        if not rows:
            return
        bounded = max(0, min(int(case_idx), len(rows) - 1))
        if case_select.value == bounded:
            _load_case(bounded)
        else:
            case_select.value = bounded

    def _find_next_unreviewed(start_after: int | None = None) -> int | None:
        rows = state.case_rows or []
        if not rows:
            return None
        start = int(start_after if start_after is not None else (case_select.value or -1))
        order = list(range(start + 1, len(rows))) + list(range(0, start + 1))
        for idx in order:
            if not str(rows[idx].get("label", "") or "").strip():
                return idx
        return None

    def _rebuild_tables() -> None:
        fsa = state.current_fsa
        candidates = state.current_candidates
        mapping = state.current_mapping or {}
        if fsa is None or candidates is None:
            assignment_table.value = pd.DataFrame()
            candidate_table.value = pd.DataFrame()
            step_select.options = {}
            return

        expected_steps = np.asarray(getattr(fsa, "expected_ladder_steps", getattr(fsa, "ladder_steps", [])), dtype=float)
        step_options = {f"{bp:.0f} bp": idx for idx, bp in enumerate(expected_steps)}
        step_select.options = step_options

        assignment_rows = []
        for idx, bp in enumerate(expected_steps):
            cand_idx = mapping.get(idx)
            if cand_idx is None or cand_idx >= len(candidates):
                assignment_rows.append(
                    {"step_idx": idx, "expected_bp": float(bp), "candidate_idx": "", "candidate_time": "", "candidate_intensity": ""}
                )
                continue
            cand = candidates.iloc[cand_idx]
            assignment_rows.append(
                {
                    "step_idx": idx,
                    "expected_bp": float(bp),
                    "candidate_idx": int(cand_idx),
                    "candidate_time": float(cand["time"]),
                    "candidate_intensity": float(cand["intensity"]),
                }
            )
        assignment_table.value = pd.DataFrame(assignment_rows)

        candidate_rows = []
        for row_idx, cand in candidates.reset_index(drop=True).iterrows():
            used_by = _candidate_used_by(int(row_idx))
            is_rust_selected = int(row_idx) in set((state.current_auto_mapping or {}).values())
            candidate_rows.append(
                {
                    "candidate_idx": int(row_idx),
                    "time": float(cand["time"]),
                    "intensity": float(cand["intensity"]),
                    "source": str(cand.get("source", "auto")),
                    "assigned_bp": f"{expected_steps[used_by]:.0f}" if used_by is not None else "",
                    "rust_selected": "yes" if is_rust_selected else "",
                }
            )
        candidate_table.value = pd.DataFrame(candidate_rows)

    def _nearest_peak_time(trace: np.ndarray, x_value: float, search_radius: int = 18) -> tuple[float, float]:
        center = int(round(float(x_value)))
        lo = max(center - search_radius, 0)
        hi = min(center + search_radius + 1, trace.size)
        if lo >= hi:
            raise ValueError("Could not inspect local ladder region.")
        window = trace[lo:hi]
        local_index = int(np.argmax(window))
        peak_index = lo + local_index
        return float(peak_index), float(trace[peak_index])

    def _insert_manual_candidate(peak_time: float, intensity: float) -> int:
        candidates = state.current_candidates
        if candidates is None:
            raise ValueError("No candidates loaded.")
        diff = (candidates["time"].astype(float) - peak_time).abs()
        matches = diff[diff <= 1.0]
        if not matches.empty:
            return int(matches.index[0])
        row = pd.DataFrame([{"index": len(candidates), "time": peak_time, "intensity": intensity, "source": "manual"}])
        state.current_candidates = pd.concat([candidates, row], ignore_index=True)
        state.current_manual_candidates.append(float(peak_time))
        return int(state.current_candidates.index[-1])

    def _assign_candidate_to_step(step_idx: int, cand_idx: int) -> None:
        mapping = dict(state.current_mapping or {})
        for other_step, other_cand in list(mapping.items()):
            if other_step != step_idx and other_cand == cand_idx:
                del mapping[other_step]
        mapping[int(step_idx)] = int(cand_idx)
        state.current_mapping = mapping
        _refresh_preview()

    def _current_adjustment_payload() -> dict:
        candidates = state.current_candidates
        mapping_times = {}
        if candidates is not None:
            for step_idx, cand_idx in (state.current_mapping or {}).items():
                if 0 <= cand_idx < len(candidates):
                    mapping_times[int(step_idx)] = float(candidates.iloc[cand_idx]["time"])
        return {
            "mapping": dict(state.current_mapping or {}),
            "mapping_times": mapping_times,
            "manual_candidates": list(state.current_manual_candidates or []),
        }

    def _preview_trial():
        if state.current_fsa is None:
            return None, None
        payload = _current_adjustment_payload()
        expected_steps = np.asarray(getattr(state.current_fsa, "expected_ladder_steps", getattr(state.current_fsa, "ladder_steps", [])), dtype=float)
        if len(payload["mapping_times"]) < max(3, len(expected_steps)):
            return None, None
        try:
            trial = apply_manual_ladder_mapping(copy.deepcopy(state.current_fsa), payload)
            qc = compute_ladder_qc_metrics(trial)
            return trial, qc
        except Exception:
            return None, None

    def _figure_object() -> go.Figure:
        fig = go.Figure()
        if state.current_fsa is None:
            fig.update_layout(
                template="plotly_white",
                height=520,
                title="Load a review bundle and choose a case",
                margin=dict(l=40, r=20, t=60, b=40),
            )
            return fig

        trace = np.asarray(state.current_fsa.size_standard, dtype=float)
        fig.add_trace(go.Scatter(x=np.arange(trace.size), y=trace, mode="lines", line=dict(color="black", width=1), name="Trace"))

        candidates = state.current_candidates
        if candidates is not None and not candidates.empty:
            fig.add_trace(
                go.Scatter(
                    x=candidates["time"],
                    y=candidates["intensity"],
                    mode="markers",
                    marker=dict(color="lightgray", size=7),
                    name="Possible peaks",
                    customdata=np.stack([candidates.index.to_numpy()], axis=-1),
                    hovertemplate="candidate %{customdata[0]}<br>x=%{x}<br>y=%{y}<extra></extra>",
                )
            )
            auto_mapping = state.current_auto_mapping or {}
            if auto_mapping:
                auto_xs, auto_ys, auto_texts = [], [], []
                expected_steps = np.asarray(getattr(state.current_fsa, "expected_ladder_steps", getattr(state.current_fsa, "ladder_steps", [])), dtype=float)
                for step_idx, cand_idx in auto_mapping.items():
                    if cand_idx >= len(candidates):
                        continue
                    cand = candidates.iloc[cand_idx]
                    auto_xs.append(float(cand["time"]))
                    auto_ys.append(float(cand["intensity"]))
                    auto_texts.append(f"{expected_steps[step_idx]:.0f} bp")
                fig.add_trace(
                    go.Scatter(
                        x=auto_xs,
                        y=auto_ys,
                        mode="markers",
                        marker=dict(color="#f59e0b", size=10, symbol="circle-open", line=dict(width=2)),
                        name="Rust selected peaks",
                        text=auto_texts,
                        hovertemplate="%{text}<br>rust x=%{x}<br>y=%{y}<extra></extra>",
                    )
                )
            manual = candidates[candidates.get("source", pd.Series([], dtype=str)).astype(str) == "manual"]
            if not manual.empty:
                fig.add_trace(
                    go.Scatter(
                        x=manual["time"],
                        y=manual["intensity"],
                        mode="markers",
                        marker=dict(color="#0f766e", size=9, symbol="diamond"),
                        name="Manual candidates",
                        hovertemplate="manual x=%{x}<br>y=%{y}<extra></extra>",
                    )
                )

        mapping = state.current_mapping or {}
        if candidates is not None and mapping:
            expected_steps = np.asarray(getattr(state.current_fsa, "expected_ladder_steps", getattr(state.current_fsa, "ladder_steps", [])), dtype=float)
            xs, ys, texts = [], [], []
            for step_idx, cand_idx in mapping.items():
                if cand_idx >= len(candidates):
                    continue
                cand = candidates.iloc[cand_idx]
                xs.append(float(cand["time"]))
                ys.append(float(cand["intensity"]))
                texts.append(f"{expected_steps[step_idx]:.0f} bp")
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="markers+text",
                    marker=dict(color="#2563eb", size=11),
                    text=texts,
                    textposition="top center",
                    name="Selected peaks",
                    hovertemplate="%{text}<br>x=%{x}<br>y=%{y}<extra></extra>",
                )
            )

        title = state.current_file.name if state.current_file else "Ladder review"
        fig.update_layout(
            template="plotly_white",
            height=520,
            title=title,
            margin=dict(l=40, r=20, t=60, b=40),
            xaxis_title="Scan index",
            yaxis_title="Signal",
            dragmode="pan",
            legend=dict(orientation="h"),
        )
        return fig

    def _refresh_preview() -> None:
        trial, qc = _preview_trial()
        state_preview = []
        case = state.current_case or {}
        if case:
            assay = str(case.get("assay", "") or "")
            ladder = str(case.get("ladder", "") or "")
            qc_state = str(case.get("ladder_qc", "") or "")
            label = str(case.get("label", "") or "")
            note = str(case.get("label_note", "") or "")
            meta_parts = [part for part in (assay, ladder, qc_state, label) if part]
            case_meta.object = f"<div style='font-weight:700; color:var(--text)'>{' · '.join(meta_parts)}</div>"
            if qc_state == "review_required":
                why = "This case is in the review bundle because it tripped the original triage rule, not necessarily because the fit is actually bad."
                if label or note:
                    why += " Existing review note/label is preserved below."
                case_meta.object += f"<div style='margin-top:4px; color:var(--text-muted); font-size:12px;'>{why}</div>"
        else:
            case_meta.object = ""
        progress = f"<div style='margin-top:4px; font-size:13px; font-weight:700; color:var(--text-muted)'>{_review_progress_text()}</div>"
        case_meta.object = f"{case_meta.object}{progress}"

        if qc is None:
            state_preview.append("Preview pending or incomplete mapping.")
        else:
            state_preview.append(
                f"Linear max {float(qc['linear_trend_max_abs_error_bp']):.2f} bp | "
                f"Linear mean {float(qc['linear_trend_mean_abs_error_bp']):.2f} bp | "
                f"Linear R² {float(qc['linear_trend_r2']):.6f}"
            )
            state_preview.append(
                f"Spline R² {float(qc['r2']):.6f} | Mean {float(qc['mean_abs_error_bp']):.2f} bp | Max {float(qc['max_abs_error_bp']):.2f} bp"
            )
        metrics.object = "<br>".join(f"<div style='color:var(--text-muted); font-size:13px; font-weight:600'>{line}</div>" for line in state_preview)
        _rebuild_tables()
        figure_pane.object = _figure_object()

    def _load_case(case_idx: int) -> None:
        if not state.case_rows or case_idx < 0 or case_idx >= len(state.case_rows):
            return
        row = state.case_rows[case_idx]
        file_path = Path(str(row["full_path"]))
        fsa, _meta = load_adjustable_fsa(file_path, preferred_analysis="clonality")
        candidates = get_ladder_candidates(fsa).copy().reset_index(drop=True)

        state.current_case = row
        state.current_file = file_path
        state.current_fsa = fsa
        state.current_candidates = candidates
        state.current_mapping = _mapping_from_fsa(fsa, candidates)
        state.current_auto_mapping = dict(state.current_mapping)
        state.current_manual_candidates = [float(v) for v in getattr(fsa, "manual_ladder_candidates", []) or []]
        comment.value = str(row.get("label_note", "") or "")
        _refresh_preview()
        next_step = _next_step_index(None)
        if next_step is not None:
            step_select.value = next_step
        _set_status(f"Loaded {file_path.name}")

    def _save_annotation(note_only: bool) -> None:
        if state.bundle_dir is None or state.current_case is None or state.current_file is None:
            _set_status("No case loaded.", "var(--red)")
            return
        action = "reviewed_no_change" if note_only else "manual_adjusted"
        reviewed_at = datetime.now(timezone.utc).isoformat()
        cases_path = state.bundle_dir / "ladder_review_cases.csv"
        rows = []
        with cases_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        for row in rows:
            if str(row.get("full_path", "") or "") != str(state.current_file):
                continue
            row["label"] = action
            row["label_note"] = comment.value.strip()
            row["reviewed_at_utc"] = reviewed_at
            state.current_case.update(row)
            if state.case_rows is not None and case_select.value is not None:
                state.case_rows[int(case_select.value)] = dict(row)
            break
        with cases_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        annotations_path = state.bundle_dir / "ladder_review_annotations.json"
        current = {}
        if annotations_path.exists():
            try:
                current = json.loads(annotations_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        current[str(state.current_file)] = {
            "label": action,
            "label_note": comment.value.strip(),
            "reviewed_at_utc": reviewed_at,
        }
        annotations_path.write_text(json.dumps(current, indent=2, ensure_ascii=True), encoding="utf-8")
        _refresh_case_options()
        case_meta.object = f"{case_meta.object}<div style='margin-top:4px; font-size:13px; font-weight:700; color:var(--text-muted)'>{_review_progress_text()}</div>"

    def _go_relative(delta: int) -> None:
        if case_select.value is None:
            return
        _set_case_index(int(case_select.value) + delta)

    def _go_next_unreviewed() -> bool:
        next_idx = _find_next_unreviewed(int(case_select.value) if case_select.value is not None else None)
        if next_idx is None:
            _set_status("All cases are reviewed.", "var(--green)")
            return False
        _set_case_index(next_idx)
        return True

    def _on_load_bundle(_event=None) -> None:
        try:
            bundle = Path(bundle_dir.value).expanduser()
            rows = _load_bundle_rows(bundle)
        except Exception as exc:
            _set_status(f"Could not load bundle: {exc}", "var(--red)")
            return
        state.bundle_dir = bundle
        state.case_rows = rows
        case_select.options = {_label_for_case(row): idx for idx, row in enumerate(rows)}
        if rows:
            first_idx = next(iter(case_select.options.values()))
            case_select.value = first_idx
            _load_case(first_idx)
        _set_status(f"Loaded {len(rows)} review case(s) from {bundle.name}.", "var(--green)")

    def _on_case_change(event) -> None:
        if event.new is None:
            return
        _load_case(int(event.new))

    def _on_plot_click(event) -> None:
        click_data = event.new
        if not click_data or state.current_fsa is None or state.current_candidates is None:
            return
        step_idx = step_select.value
        if step_idx is None:
            _set_status("Choose a target ladder step first.", "var(--amber)")
            return
        try:
            point = click_data["points"][0]
            x_value = float(point.get("x"))
            trace = np.asarray(state.current_fsa.size_standard, dtype=float)
            peak_time, intensity = _nearest_peak_time(trace, x_value)
            cand_idx = _insert_manual_candidate(peak_time, intensity)
            _assign_candidate_to_step(int(step_idx), int(cand_idx))
            next_step = _next_step_index(int(step_idx))
            if next_step is not None:
                step_select.value = next_step
                expected_steps = np.asarray(
                    getattr(state.current_fsa, "expected_ladder_steps", getattr(state.current_fsa, "ladder_steps", [])),
                    dtype=float,
                )
                next_bp = f"{expected_steps[next_step]:.0f} bp" if next_step < len(expected_steps) else str(next_step)
                _set_status(
                    f"Assigned local peak {peak_time:.0f}. Advanced to {next_bp}.",
                    "var(--green)",
                )
            else:
                _set_status(f"Assigned local peak {peak_time:.0f}.", "var(--green)")
        except Exception as exc:
            _set_status(f"Could not assign peak: {exc}", "var(--red)")

    def _on_reset(_event=None) -> None:
        if state.current_case is None:
            return
        current_idx = int(case_select.value)
        _load_case(current_idx)

    def _on_clear(_event=None) -> None:
        if step_select.value is None:
            return
        mapping = dict(state.current_mapping or {})
        mapping.pop(int(step_select.value), None)
        state.current_mapping = mapping
        _refresh_preview()

    def _on_save_note(_event=None) -> None:
        try:
            _save_annotation(note_only=True)
            if _go_next_unreviewed():
                _set_status("Saved review note. Moved to next unreviewed case.", "var(--green)")
            else:
                _set_status("Saved review note. All cases reviewed.", "var(--green)")
        except Exception as exc:
            _set_status(f"Could not save note: {exc}", "var(--red)")

    def _on_save_adjustment(_event=None) -> None:
        if state.current_fsa is None or state.current_file is None:
            _set_status("No case loaded.", "var(--red)")
            return
        payload = _current_adjustment_payload()
        try:
            save_ladder_adjustment(state.current_fsa, payload)
            _save_annotation(note_only=False)
            filename = state.current_file.name
            if _go_next_unreviewed():
                _set_status(f"Saved adjustment for {filename}. Moved to next unreviewed case.", "var(--green)")
            else:
                _set_status(f"Saved adjustment for {filename}. All cases reviewed.", "var(--green)")
        except Exception as exc:
            _set_status(f"Could not save adjustment: {exc}", "var(--red)")

    def _on_previous(_event=None) -> None:
        _go_relative(-1)

    def _on_next(_event=None) -> None:
        _go_relative(1)

    def _on_next_unreviewed(_event=None) -> None:
        _go_next_unreviewed()

    load_btn.on_click(_on_load_bundle)
    reset_btn.on_click(_on_reset)
    clear_btn.on_click(_on_clear)
    note_btn.on_click(_on_save_note)
    save_btn.on_click(_on_save_adjustment)
    prev_btn.on_click(_on_previous)
    next_btn.on_click(_on_next)
    next_unreviewed_btn.on_click(_on_next_unreviewed)
    case_select.param.watch(_on_case_change, "value")
    figure_pane.param.watch(_on_plot_click, "click_data")

    controls = pn.Row(bundle_dir, load_btn, sizing_mode="stretch_width")
    case_controls = pn.Row(case_select, step_select, sizing_mode="stretch_width")
    nav_row = pn.Row(prev_btn, next_btn, next_unreviewed_btn, sizing_mode="stretch_width")
    action_row = pn.Row(reset_btn, clear_btn, note_btn, save_btn, sizing_mode="stretch_width")

    left = pn.Column(
        make_card(
            "Review Controls",
            controls,
            VSpace(6),
            case_controls,
            VSpace(6),
            nav_row,
            VSpace(6),
            action_row,
            VSpace(6),
            case_meta,
            metrics,
            status,
        ),
        make_card("Comment", comment),
        sizing_mode="stretch_both",
        min_width=430,
    )
    right = pn.Column(
        make_card("Interactive Ladder Trace", figure_pane),
        make_card("Assigned Ladder Steps", assignment_table),
        make_card("Candidate Peaks", candidate_table),
        sizing_mode="stretch_both",
    )

    return pn.Column(
        section_header(
            "Ladder Review",
            "Load a review bundle, click near peaks in the trace, assign ladder steps, and save comments or manual ladder adjustments.",
        ),
        pn.Row(left, right, sizing_mode="stretch_both"),
        sizing_mode="stretch_both",
        styles={"padding": "24px 28px", "gap": "0", "max-width": "1600px"},
    )
