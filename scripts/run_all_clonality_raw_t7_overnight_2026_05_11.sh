#!/usr/bin/env bash
set -uo pipefail

ROOT="/Users/christian/Desktop/HemaFrag"
OUT_DIR="/Volumes/T7 Shield/HemaFrag_all_clonality_raw_t7_overnight_2026-05-11"

mkdir -p "$OUT_DIR"
cd "$ROOT" || exit 1

echo "started_at=$(date -Iseconds)"
echo "out_dir=$OUT_DIR"

python3 scripts/run_all_clonality_raw_t7_overnight.py \
  --root "/Volumes/T7 Shield/DATA/2024_DATA" \
  --root "/Volumes/T7 Shield/DATA/2025_data" \
  --root "/Volumes/T7 Shield/DATA/2026" \
  --workers 5 \
  --progress-every 100 \
  --out-dir "$OUT_DIR"
status=$?

python3 scripts/summarize_broad_live_eval.py "$OUT_DIR" || true
echo "finished_at=$(date -Iseconds) status=$status"
exit "$status"
