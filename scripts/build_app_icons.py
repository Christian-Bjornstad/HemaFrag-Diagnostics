from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ICO_SIZES = (
    (16, 16),
    (20, 20),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)


def render_master(size: int = 1024) -> Image.Image:
    if size < 16:
        raise ValueError("HemaFrag icons must be at least 16 px")

    scale = size / 1024

    def px(value: int) -> int:
        return round(value * scale)

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (px(48), px(48), px(976), px(976)),
        radius=px(210),
        fill="#12395B",
        outline="#2563EB",
        width=max(1, px(30)),
    )
    draw.rounded_rectangle(
        (px(250), px(222), px(344), px(746)),
        radius=px(28),
        fill="#FFFFFF",
    )
    draw.rounded_rectangle(
        (px(680), px(222), px(774), px(746)),
        radius=px(28),
        fill="#FFFFFF",
    )
    draw.rounded_rectangle(
        (px(310), px(435), px(714), px(535)),
        radius=px(28),
        fill="#FFFFFF",
    )
    trace = [
        (150, 700),
        (258, 700),
        (310, 630),
        (346, 700),
        (470, 700),
        (520, 570),
        (558, 700),
        (675, 700),
        (720, 620),
        (755, 700),
        (874, 700),
    ]
    draw.line(
        [(px(x), px(y)) for x, y in trace],
        fill="#67E8F9",
        width=max(2, px(34)),
        joint="curve",
    )
    return image


def write_icon_assets(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    master = render_master()
    paths = {
        "png": output_dir / "app_icon.png",
        "ico": output_dir / "app_icon.ico",
        "icns": output_dir / "app_icon.icns",
    }
    master.save(paths["png"], format="PNG", optimize=True)
    master.save(paths["ico"], format="ICO", sizes=ICO_SIZES)
    master.save(paths["icns"], format="ICNS")
    return paths


if __name__ == "__main__":
    write_icon_assets(Path(__file__).resolve().parents[1] / "assets")
