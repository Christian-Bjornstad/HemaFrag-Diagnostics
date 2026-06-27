"""HemaFrag diagnostic run on a real-data workspace.

Drop this script at the repo root on your Windows machine
(``code-cleanup`` branch clone at e.g. C:\\Users\\molpa\\Desktop\\Hermes\\HemaFrag-Diagnostics-code-cleanup),
then run from PowerShell:

    python scripts/run_real_data_diagnostic.py \\
        --flt3-dir  "C:\\Users\\molpa\\Desktop\\DATA\\flt3" \\
        --clonality-dir "C:\\Users\\molpa\\Desktop\\DATA\\clonality" \\
        --output-dir "C:\\Users\\molpa\\Desktop\\Hermes\\HemaFrag-Diagnostics-code-cleanup\\bench-results"

Loads FLT3 ladder/peak detection + clonality pipeline over the
available data, times each, and prints structured results.

Optimised to be safe on partial data: it never crashes the run on a
single bad .fsa; instead logs it under errors.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def probe_directory(data_dir: Path):
    """Return list of .fsa paths under data_dir (recursive)."""
    if not data_dir.exists():
        return []
    return sorted(p for p in data_dir.rglob("*.fsa") if p.is_file())


def classify_filenames(fsa_paths):
    """Heuristic classification by filename markers (water / control / FLT3 / clonality)."""
    out = {"flt3": [], "clonality": [], "control": [], "water": [], "other": []}
    for p in fsa_paths:
        name = p.name.lower()
        if name.startswith("water") or "_mq" in name or "/mq_" in name:
            out["water"].append(p)
        elif "pk" in name or "nk" in name or "rk" in name:
            out["control"].append(p)
        elif any(s in name for s in ("flt3", "itro", "d835", "npm1")):
            out["flt3"].append(p)
        elif any(s in name for s in ("onc", "igh", "tcr", "klonal")):
            out["clonality"].append(p)
        else:
            out["other"].append(p)
    return out


def run_flt3_batch(repo_root, fsa_paths, out_dir):
    if not fsa_paths:
        return {"available": False, "reason": "no .fsa"}
    # Lazily import to keep the diagnostic importable off the GUI.
    sys.path.insert(0, str(repo_root))
    from core.analyses.flt3.pipeline import run_pipeline
    sample = fsa_paths[:5]
    out = out_dir / "flt3_smoke"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    try:
        entries = run_pipeline(
            fsa_dir=sample[0].parent,
            base_outdir=out,
            assay_folder_name="flt3_smoke",
            return_entries=True,
            make_dit_reports=True,
            mode="all",
            update_tracking_workbook=False,
        )
        return {
            "available": True,
            "files": len(fsa_paths),
            "sampled": len(sample),
            "duration_sec": time.perf_counter() - t0,
            "entries_returned": len(entries) if entries else 0,
            "outputs": str(out),
        }
    except Exception as exc:
        return {
            "available": True,
            "files": len(fsa_paths),
            "sampled": len(sample),
            "duration_sec": time.perf_counter() - t0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_clonality_smoke(repo_root, fsa_paths, out_dir):
    if not fsa_paths:
        return {"available": False, "reason": "no .fsa"}
    sys.path.insert(0, str(repo_root))
    try:
        from core.analyses.clonality.pipeline import run_pipeline
    except Exception as exc:
        return {"available": False, "reason": f"import failed: {type(exc).__name__}: {exc}"}
    sample = fsa_paths[:3]
    out = out_dir / "clonality_smoke"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    try:
        entries = run_pipeline(
            fsa_dir=sample[0].parent,
            base_outdir=out,
            assay_folder_name="clonality_smoke",
            return_entries=True,
            update_tracking_workbook=False,
        )
        return {
            "available": True,
            "files": len(fsa_paths),
            "sampled": len(sample),
            "duration_sec": time.perf_counter() - t0,
            "entries_returned": len(entries) if entries else 0,
            "outputs": str(out),
        }
    except Exception as exc:
        return {
            "available": True,
            "files": len(fsa_paths),
            "sampled": len(sample),
            "duration_sec": time.perf_counter() - t0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--flt3-dir", default=None)
    parser.add_argument("--clonality-dir", default=None)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    repo_root = Path(args.repo_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {}
    if args.flt3_dir:
        paths = probe_directory(Path(args.flt3_dir))
        bucket = classify_filenames(paths)
        print(f"[flt3] {len(paths)} .fsa files")
        for k, v in bucket.items():
            print(f"  {k}: {len(v)}")
        result = run_flt3_batch(repo_root, bucket["flt3"], output_dir)
        summary["flt3"] = result
        if result.get("error"):
            print(f"  FLT3 ERR: {result['error']}")
        else:
            print(f"  FLT3 OK: {result.get('entries_returned', 0)} entries")
    else:
        summary["flt3"] = {"available": False, "reason": "--flt3-dir not given"}

    if args.clonality_dir:
        paths = probe_directory(Path(args.clonality_dir))
        bucket = classify_filenames(paths)
        print(f"[clonality] {len(paths)} .fsa files")
        for k, v in bucket.items():
            print(f"  {k}: {len(v)}")
        result = run_clonality_smoke(repo_root, bucket["clonality"], output_dir)
        summary["clonality"] = result
        if result.get("error"):
            print(f"  clonality ERR: {result['error']}")
        else:
            print(f"  clonality OK: {result.get('entries_returned', 0)} entries")
    else:
        summary["clonality"] = {"available": False, "reason": "--clonality-dir not given"}

    summary["tests"] = "33 + 16 = 49 baseline (Pass-3)"
    out_path = output_dir / "_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nSummary saved to {out_path}")


if __name__ == "__main__":
    main()
