from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.evaluate_rust_apex_recenter_live as live_eval
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker


def safe_name(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or ""))[:180]


def render_rows(rows: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    live_eval.IMAGE_DIR = image_dir

    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker not available")

    rendered: list[dict[str, object]] = []
    for row in rows.itertuples(index=False):
        raw_path = Path(str(row.raw_path))
        analysis = live_eval.analyze_path(worker, raw_path)
        if str(analysis.get("error", "")).startswith("worker timeout"):
            _invalidate_rust_worker()
            worker = _get_rust_worker()
            if worker is None:
                raise SystemExit("Rust worker not available after timeout")
            analysis = live_eval.analyze_path(worker, raw_path)
        image = live_eval.render_image(analysis) if analysis.get("ok") else None
        rendered.append(
            {
                "file": raw_path.name,
                "raw_path": str(raw_path),
                "source_group": getattr(row, "source_group", ""),
                "morning_class": getattr(row, "morning_class", ""),
                "ladder": analysis.get("ladder", getattr(row, "ladder", "")),
                "linear_max": analysis.get("linear_max", getattr(row, "linear_max", "")),
                "linear_mean": analysis.get("linear_mean", getattr(row, "linear_mean", "")),
                "linear_r2": analysis.get("linear_r2", getattr(row, "linear_r2", "")),
                "review": analysis.get("review", getattr(row, "review", "")),
                "primary_reason": analysis.get("primary_reason", getattr(row, "primary_reason", "")),
                "image": image or "",
                "ok": bool(analysis.get("ok")),
                "error": analysis.get("error", ""),
            }
        )
    out = pd.DataFrame(rendered)
    out.to_csv(out_dir / "image_index.tsv", sep="\t", index=False)
    return out


def make_contact_sheet(index: pd.DataFrame, out_path: Path) -> None:
    rows = index[index["image"].astype(str).str.len() > 0].copy()
    if rows.empty:
        return
    thumb_w, thumb_h = 620, 260
    label_h = 86
    cols = 2
    sheet_rows = (len(rows) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, sheet_rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 14)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 12)
    except OSError:
        font = small = None

    for i, row in enumerate(rows.itertuples(index=False)):
        path = Path(str(row.image))
        if not path.is_absolute():
            path = ROOT / path
        img = Image.open(path).convert("RGB")
        img.thumbnail((thumb_w, thumb_h), Image.LANCZOS)
        x = (i % cols) * thumb_w
        y = (i // cols) * (thumb_h + label_h)
        sheet.paste(img, (x + (thumb_w - img.width) // 2, y + label_h + (thumb_h - img.height) // 2))
        draw.text((x + 8, y + 5), f"{row.morning_class} | {row.ladder}", fill=(0, 0, 0), font=font)
        draw.text((x + 8, y + 29), str(row.file)[:76], fill=(60, 60, 60), font=small)
        draw.text(
            (x + 8, y + 50),
            f"linear {float(row.linear_max):.2f}/{float(row.linear_mean):.2f}/{float(row.linear_r2):.6f}",
            fill=(80, 80, 80),
            font=small,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render images for broad eval watchlist rows.")
    parser.add_argument("watchlist", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--classes", default="")
    parser.add_argument("--max-rows", type=int, default=24)
    args = parser.parse_args()

    rows = pd.read_csv(args.watchlist, sep="\t")
    if args.classes:
        classes = {item.strip() for item in args.classes.split(",") if item.strip()}
        rows = rows[rows["morning_class"].isin(classes)].copy()
    rows = rows.head(args.max_rows).copy()

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out_dir / "selected_rows.tsv", sep="\t", index=False)
    rendered = render_rows(rows, out_dir)
    make_contact_sheet(rendered, out_dir / "contact_sheet.png")
    summary = {
        "selected": int(len(rows)),
        "rendered": int(rendered["image"].astype(bool).sum()) if not rendered.empty else 0,
        "out_dir": str(out_dir),
        "contact_sheet": str(out_dir / "contact_sheet.png"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
