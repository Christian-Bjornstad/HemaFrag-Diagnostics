from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker
from scripts import evaluate_rust_apex_recenter_live as live_eval
from scripts import render_clonality_review_html as review_html


SOURCE_FILES = [
    ("ok_182_latest", ROOT / "local_triage" / "ok_182_after_liz_weak_anchor_eval.tsv"),
    ("review_190_live", ROOT / "local_triage" / "review_190_current_live.tsv"),
    ("review_190_groups", ROOT / "local_triage" / "review_190_learning_groups.tsv"),
    ("review_candidates", ROOT / "local_triage" / "review_learning_candidates_live.tsv"),
    ("liz_17_labels", ROOT / "local_triage" / "liz_17_annotated_summary_latest.tsv"),
    ("next_learning_labels", ROOT / "local_triage" / "next_learning_filtered_non_operator.tsv"),
    ("next_rox_review", ROOT / "local_triage" / "next_rox_review_annotation_summary.tsv"),
]

EXCLUDED_RUN_MARKERS = [
    "2024_05_24_FR123_tmt_C990JXOA_2024-05-27_1320",
    "2024_05_24_SL_TCRb_tmt_C9R0HJZ6_2024-05-27_1318",
]
ACTIVE_2024_DATA_ROOT = Path("/Volumes/T7 Shield/DATA/2024_DATA")
EXCLUDED_RUN_ROOT = Path("/Volumes/T7 Shield/EXCLUDED_BAD_RUNS/2024_05_24_wrong_ladder_operator")


def to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    return str(value).strip()


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def row_path(row: dict[str, str]) -> str:
    for key in ("resolved_raw_path", "raw_path"):
        value = clean(row.get(key))
        if value:
            return value
    return ""


def resolve_raw_path(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    if Path(value).exists():
        return value, ""
    for marker in EXCLUDED_RUN_MARKERS:
        old_prefix = str(ACTIVE_2024_DATA_ROOT / marker) + "/"
        if value.startswith(old_prefix):
            candidate = str(EXCLUDED_RUN_ROOT / marker / value[len(old_prefix):])
            if Path(candidate).exists():
                return candidate, "resolved_24_05_excluded_operator_run"
    return value, ""


def row_label(row: dict[str, str]) -> str:
    for key in ("latest_label", "label", "prior_label"):
        value = clean(row.get(key)).lower()
        if value:
            return value
    return ""


def row_ladder(row: dict[str, str]) -> str:
    return clean(row.get("rerun_ladder")) or clean(row.get("ladder")) or clean(row.get("workbook_ladder"))


def should_include(source: str, row: dict[str, str]) -> tuple[bool, str, float]:
    label = row_label(row)
    if label == "operator":
        return False, "operator_label", 0.0

    path = row_path(row)
    if not path:
        return False, "missing_path", 0.0

    review = any(
        to_bool(row.get(key))
        for key in ("review", "rerun_review", "live_review")
    )
    reason_codes = " ".join(
        clean(row.get(key))
        for key in ("reasons", "reason_codes", "rerun_reasons", "live_reasons", "primary_reason")
    ).lower()
    learning_group = clean(row.get("learning_group")).lower()

    linear_max = 0.0
    for key in ("rerun_linear_max", "live_linear_max", "linear_max"):
        try:
            linear_max = max(linear_max, float(clean(row.get(key)) or "0"))
        except ValueError:
            pass

    if source == "ok_182_latest":
        if label in {"wrong", "minor", "unclear", ""} or review:
            return True, f"ok182_{label or 'blank'}", 100.0 + linear_max
        return False, "ok182_good_or_operator", 0.0

    if source in {"liz_17_labels", "next_learning_labels"}:
        if label in {"wrong", "minor", "unclear"}:
            return True, f"{source}_{label}", 90.0 + linear_max
        return False, "non_learning_label", 0.0

    if source in {"review_190_live", "review_190_groups", "review_candidates", "next_rox_review"}:
        if review or "poor_linear" in reason_codes or "selected_" in reason_codes:
            if "low_signal" in learning_group or "do_not_train" in learning_group:
                return True, f"{source}_{learning_group or 'low_signal_do_not_train'}", 50.0 + linear_max
            return True, f"{source}_{learning_group or 'review'}", 70.0 + linear_max
        return False, "not_review_like", 0.0

    return False, "unknown_source", 0.0


def build_manifest() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_path: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []

    for source, path in SOURCE_FILES:
        for row in read_tsv(path):
            include, reason, priority = should_include(source, row)
            raw_path = row_path(row)
            if not include:
                if raw_path:
                    skipped.append({"source": source, "raw_path": raw_path, "reason": reason})
                continue
            resolved_path, path_resolution = resolve_raw_path(raw_path)

            entry = by_path.setdefault(
                resolved_path,
                {
                    "raw_path": resolved_path,
                    "original_raw_path": raw_path if raw_path != resolved_path else "",
                    "path_resolution": path_resolution,
                    "file": Path(resolved_path).name,
                    "source_tags": [],
                    "include_reasons": [],
                    "labels": [],
                    "notes": [],
                    "priority": 0.0,
                    "assay": "",
                    "ladder": "",
                    "linear_max": "",
                    "linear_mean": "",
                    "linear_r2": "",
                    "review": "",
                    "primary_reason": "",
                    "reason_codes": "",
                    "morning_class": "bad_uncertain",
                },
            )
            if path_resolution and path_resolution not in entry["include_reasons"]:
                entry["include_reasons"].append(path_resolution)
            if raw_path != resolved_path and raw_path and raw_path not in entry["notes"]:
                entry["notes"].append(f"original path: {raw_path}")
            entry["source_tags"].append(source)
            entry["include_reasons"].append(reason)
            label = row_label(row)
            if label:
                entry["labels"].append(label)
            note = clean(row.get("note")) or clean(row.get("latest_note")) or clean(row.get("prior_note"))
            if note:
                entry["notes"].append(note)
            entry["priority"] = max(float(entry["priority"]), priority)
            entry["assay"] = entry["assay"] or clean(row.get("assay")) or clean(row.get("Assay"))
            entry["ladder"] = entry["ladder"] or row_ladder(row)
            for key in ("linear_max", "linear_mean", "linear_r2", "review", "primary_reason", "reason_codes"):
                if not entry.get(key) and clean(row.get(key)):
                    entry[key] = clean(row.get(key))

    manifest = []
    missing = []
    for entry in by_path.values():
        exists = Path(entry["raw_path"]).exists()
        entry["exists"] = exists
        entry["source_tags"] = ";".join(sorted(set(entry["source_tags"])))
        entry["include_reasons"] = ";".join(sorted(set(entry["include_reasons"])))
        entry["labels"] = ";".join(sorted(set(entry["labels"])))
        entry["notes"] = " | ".join(dict.fromkeys(entry["notes"]))
        if exists:
            manifest.append(entry)
        else:
            missing.append({**entry, "skip_reason": "raw_path_not_found"})

    manifest.sort(key=lambda row: (-float(row["priority"]), row["ladder"], row["file"]))
    return manifest, missing + skipped


def analyze_with_retry(worker: Any, raw_path: Path) -> tuple[Any, dict[str, Any]]:
    try:
        analysis = live_eval.analyze_path(worker, raw_path)
    except Exception as exc:  # noqa: BLE001
        analysis = {"ok": False, "raw_path": str(raw_path), "file": raw_path.name, "error": repr(exc)}
    error = str(analysis.get("error", ""))
    if error.startswith("worker timeout") or error == "no response":
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is None:
            return worker, {"ok": False, "raw_path": str(raw_path), "file": raw_path.name, "error": "worker unavailable after timeout"}
        try:
            analysis = live_eval.analyze_path(worker, raw_path)
        except Exception as exc:  # noqa: BLE001
            analysis = {"ok": False, "raw_path": str(raw_path), "file": raw_path.name, "error": repr(exc)}
    return worker, analysis


def run(out_dir: Path, limit: int | None, render: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    live_eval.IMAGE_DIR = image_dir

    manifest, skipped = build_manifest()
    if limit:
        manifest = manifest[:limit]

    manifest_path = out_dir / "bad_uncertain_manifest.tsv"
    pd.DataFrame(manifest).to_csv(manifest_path, sep="\t", index=False)
    pd.DataFrame(skipped).to_csv(out_dir / "skipped_or_missing.tsv", sep="\t", index=False)

    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker unavailable")

    rendered_rows: list[dict[str, Any]] = []
    live_rows: list[dict[str, Any]] = []
    for ordinal, entry in enumerate(manifest, start=1):
        raw_path = Path(str(entry["raw_path"]))
        worker, analysis = analyze_with_retry(worker, raw_path)
        row = {**entry, "ordinal": ordinal}
        if analysis.get("ok"):
            row.update(
                {
                    "ok": True,
                    "error": "",
                    "ladder": analysis.get("ladder") or row.get("ladder", ""),
                    "linear_max": analysis.get("linear_max"),
                    "linear_mean": analysis.get("linear_mean"),
                    "linear_r2": analysis.get("linear_r2"),
                    "review": analysis.get("review"),
                    "primary_reason": analysis.get("primary_reason", ""),
                    "reason_codes": analysis.get("reason_codes", ""),
                    "selected": analysis.get("selected", ""),
                    "candidate_count": analysis.get("candidate_count", ""),
                    "selected_count": analysis.get("selected_count", ""),
                }
            )
            image = ""
            if render:
                try:
                    image = review_html.plot_case(analysis, pd.Series(row), image_dir, ordinal) or ""
                except Exception as exc:  # noqa: BLE001
                    row["render_error"] = repr(exc)
            row["image"] = image
            row["render_ok"] = bool(image)
        else:
            row.update(
                {
                    "ok": False,
                    "error": analysis.get("error", "unknown error"),
                    "image": "",
                    "render_ok": False,
                }
            )
        live_rows.append(row)
        rendered_rows.append(row)
        if ordinal % 25 == 0 or ordinal == len(manifest):
            pd.DataFrame(live_rows).to_csv(out_dir / "bad_uncertain_live_results.tsv", sep="\t", index=False)
            print(f"processed {ordinal}/{len(manifest)}", flush=True)

    out = pd.DataFrame(rendered_rows)
    out.to_csv(out_dir / "review_rows.tsv", sep="\t", index=False)
    if render:
        html = review_html.html_doc(out, out_dir, "bad_uncertain", "HemaFrag bad/uncertain overnight review")
        (out_dir / "review_panel.html").write_text(html, encoding="utf-8")

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_rows": len(manifest),
        "processed": len(live_rows),
        "ok": int(sum(bool(row.get("ok")) for row in live_rows)),
        "review": int(sum(to_bool(row.get("review")) for row in live_rows)),
        "rendered": int(sum(bool(row.get("render_ok")) for row in live_rows)),
        "missing_or_skipped": len(skipped),
        "out_dir": str(out_dir),
        "manifest": str(manifest_path),
        "results": str(out_dir / "bad_uncertain_live_results.tsv"),
        "html": str(out_dir / "review_panel.html"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ROOT / "local_triage" / "bad_uncertain_overnight_2026-05-12")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    run(out_dir=out_dir, limit=args.limit or None, render=not args.no_render)


if __name__ == "__main__":
    main()
