#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/christian/Desktop/HemaFrag"
OUT_DIR="$ROOT/artifacts/broad_live_evening_2026_05_06_raw2026_10000"
LOG="$OUT_DIR/run.log"

mkdir -p "$OUT_DIR"
cd "$ROOT"

{
  echo "started_at=$(date -Iseconds)"
  echo "out_dir=$OUT_DIR"
  echo "step=compile_check"
  python3 -m py_compile \
    scripts/broad_live_ladder_learning_eval.py \
    scripts/summarize_broad_live_eval.py \
    scripts/known_ladder_cases.py

  echo "step=broad_live_eval"
  python3 scripts/broad_live_ladder_learning_eval.py \
    --max-cases 10000 \
    --workers 6 \
    --include-raw-2026 \
    --out-dir "$OUT_DIR"

  echo "step=morning_summary"
  python3 scripts/summarize_broad_live_eval.py "$OUT_DIR"
  echo "finished_at=$(date -Iseconds)"
} 2>&1 | tee "$LOG"
