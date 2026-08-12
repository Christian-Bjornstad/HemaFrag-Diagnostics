from pathlib import Path

from PIL import Image

from scripts.build_app_icons import render_master, write_icon_assets


def test_master_icon_has_transparency_and_strong_small_size_contrast():
    icon = render_master(1024)
    assert icon.mode == "RGBA"
    small = icon.resize((16, 16), Image.Resampling.LANCZOS).convert("RGB")
    luminance = [sum(pixel) / 3 for pixel in small.get_flattened_data()]
    assert max(luminance) - min(luminance) >= 150


def test_generator_writes_all_desktop_formats(tmp_path: Path):
    paths = write_icon_assets(tmp_path)
    assert set(paths) == {"png", "ico", "icns"}
    assert all(path.is_file() and path.stat().st_size > 0 for path in paths.values())
    with Image.open(paths["png"]) as png:
        assert png.size == (1024, 1024)
    with Image.open(paths["ico"]) as ico:
        assert {(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)} <= ico.ico.sizes()
