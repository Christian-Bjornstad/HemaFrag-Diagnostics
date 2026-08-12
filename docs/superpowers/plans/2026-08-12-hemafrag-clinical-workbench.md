# HemaFrag Clinical Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved Clinical Workbench UI polish with reliable loading of the original HemaFrag identity, correct Clonality/FLT3/General navigation, a compact Ladder Editor, and a readable About page.

**Decision update (2026-08-12):** The user chose to retain the original neon DNA/electropherogram icon. Task 1's replacement-asset steps are superseded; the original PNG, ICO, and ICNS files were restored exactly from `origin/main`. Runtime identity hardening and the sidebar lockup remain in scope.

**Architecture:** Keep the existing PyQt6 application structure and introduce only two focused boundaries: a Qt-independent `app_resources.py` for portable desktop identity and a reusable `BrandLockup` widget for app branding. Main-window routing remains label-based, the Ladder Editor keeps all fitting behavior inside its existing dialog, and About keeps legal content in the existing content module while changing only its presentation.

**Tech Stack:** Python 3.11+, PyQt6, Pillow, pytest/pytest-qt, Matplotlib/pyqtgraph, PyInstaller.

## Global Constraints

- The visual direction is **Clinical Workbench**: restrained navy and blue branding, light data surfaces, high contrast, compact spacing, and clear primary actions.
- The UI must retain **Klonalitet / Clonality**, **FLT3 Analysis**, and **General** as first-class analysis workspaces.
- Clonality navigation is exactly: Run, Ladder, Archive Runner, Log, Labeling, Settings.
- FLT3 navigation is exactly: Run, Ladder, Archive Runner, Log, Settings.
- General navigation is exactly: Run, Ladder, Log, Settings.
- ML Training must not be imported, constructed, stacked, or routed by `MainWindow`; its implementation file and model artifacts remain untouched.
- Ladder fitting, candidate selection, saved-adjustment payloads, review notes, and keyboard behavior must not change.
- The Ladder Editor must remain usable at 1200×800 and 1024×700, with QC and actions reachable and no horizontal scrolling.
- The 35 bp ladder peak receives no special reporting or visual treatment.
- Use the existing palette values from the approved spec; add no animation or UI framework dependency.
- No Rust source, Rust wheel, patient data, controls, classifier, or report output may change.
- Preserve the original `assets/app_icon.png`, `assets/app_icon.ico`, and `assets/app_icon.icns` artwork unchanged.

---

## File Map

### New files

- `app_resources.py` — resolves packaged/source icon paths, validates `QIcon` creation, and sets the Windows AppUserModelID without importing Qt at module import time.
- `gui_qt/widgets/brand_lockup.py` — reusable icon, wordmark, and descriptor widget.
- `tests/test_app_resources.py` — resource resolution, icon validation, and Windows identity checks.
- `tests/test_main_window_navigation.py` — three-workspace routing, Labeling, semantic shortcuts, and brand-lockup checks.
- `tests/test_tab_about.py` — About structure, legal content, and readable browser hooks.
- `tests/test_ladder_editor_layout.py` — compact geometry and control-group structure checks.

### Modified files

- `app_meta.py` — adds the shared application bundle identifier.
- `qt_app.py` — uses the portable resource helper and sets Windows identity before `QApplication` construction.
- `build_qt.py` — imports the shared bundle identifier rather than duplicating it.
- `gui_qt/main_window.py` — removes ML Training, adds the brand lockup, and changes shortcuts to semantic labels.
- `gui_qt/styles.py` — adds Clinical Workbench selectors for the brand, navigation, About, text browsers, and action hierarchy.
- `gui_qt/tabs/tab_about.py` — replaces stacked legal cards with one three-tab legal card.
- `gui_qt/dialogs/ladder_dialog/_legacy.py` — groups controls, makes QC vertically scrollable, reduces the safe minimum geometry, and clarifies action hierarchy.
- `tests/test_clonality_interp_integration.py` — replaces the outdated ML Training sidebar regression with the Labeling/no-training expectation.

---

### Task 1: Generate the Adaptive HemaFrag Icon Set — Superseded

The steps in this task record the initially approved direction but are no longer part of the implementation. The user explicitly selected the original artwork after seeing the replacement. Commit `76962be` restores the three icon files and removes the generator and its tests.

**Files:**
- Create: `scripts/build_app_icons.py`
- Create: `tests/test_app_icon_assets.py`
- Modify: `assets/app_icon.png`
- Modify: `assets/app_icon.ico`
- Modify: `assets/app_icon.icns`

**Interfaces:**
- Produces: `render_master(size: int = 1024) -> PIL.Image.Image`
- Produces: `write_icon_assets(output_dir: Path) -> dict[str, Path]`
- Produces: committed files named `app_icon.png`, `app_icon.ico`, and `app_icon.icns`

- [ ] **Step 1: Write the failing asset-generation tests**

```python
# tests/test_app_icon_assets.py
from pathlib import Path

from PIL import Image

from scripts.build_app_icons import render_master, write_icon_assets


def test_master_icon_has_transparency_and_strong_small_size_contrast():
    icon = render_master(1024)
    assert icon.mode == "RGBA"
    small = icon.resize((16, 16), Image.Resampling.LANCZOS).convert("RGB")
    luminance = [sum(pixel) / 3 for pixel in small.getdata()]
    assert max(luminance) - min(luminance) >= 150


def test_generator_writes_all_desktop_formats(tmp_path: Path):
    paths = write_icon_assets(tmp_path)
    assert set(paths) == {"png", "ico", "icns"}
    assert all(path.is_file() and path.stat().st_size > 0 for path in paths.values())
    with Image.open(paths["png"]) as png:
        assert png.size == (1024, 1024)
    with Image.open(paths["ico"]) as ico:
        assert {(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)} <= ico.ico.sizes()
```

- [ ] **Step 2: Run the tests and verify the generator import fails**

Run: `python -m pytest tests/test_app_icon_assets.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.build_app_icons'`.

- [ ] **Step 3: Implement the deterministic Pillow icon generator**

```python
# scripts/build_app_icons.py
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ICO_SIZES = ((16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def render_master(size: int = 1024) -> Image.Image:
    if size < 16:
        raise ValueError("HemaFrag icons must be at least 16 px")
    scale = size / 1024
    px = lambda value: round(value * scale)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (px(48), px(48), px(976), px(976)),
        radius=px(210),
        fill="#12395B",
        outline="#2563EB",
        width=max(1, px(30)),
    )
    draw.rounded_rectangle((px(250), px(222), px(344), px(746)), radius=px(28), fill="#FFFFFF")
    draw.rounded_rectangle((px(680), px(222), px(774), px(746)), radius=px(28), fill="#FFFFFF")
    draw.rounded_rectangle((px(310), px(435), px(714), px(535)), radius=px(28), fill="#FFFFFF")
    trace = [(150, 700), (258, 700), (310, 630), (346, 700), (470, 700), (520, 570), (558, 700), (675, 700), (720, 620), (755, 700), (874, 700)]
    draw.line([(px(x), px(y)) for x, y in trace], fill="#67E8F9", width=max(2, px(34)), joint="curve")
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
```

- [ ] **Step 4: Generate the committed assets and run the tests**

Run: `python scripts/build_app_icons.py`

Run: `python -m pytest tests/test_app_icon_assets.py -q`

Expected: 2 tests pass, and `git status --short assets` lists the three modified icon files.

- [ ] **Step 5: Inspect the icon at desktop sizes**

Run:

```powershell
python -c "from PIL import Image; from scripts.build_app_icons import render_master; m=render_master(); sizes=(16,20,24,32,48,128,256); tiles=[m.resize((s,s),Image.Resampling.LANCZOS).resize((128,128),Image.Resampling.NEAREST) for s in sizes]; out=Image.new('RGBA',(128*len(tiles),160),'white'); [out.paste(tile,(i*128,0),tile) for i,tile in enumerate(tiles)]; out.save('app_icon_contact_sheet.png')"
```

Inspect `app_icon_contact_sheet.png`, confirm the H silhouette and cyan trace remain distinct at 16–32 px, then remove only that generated contact sheet after inspection.

Run: `Remove-Item -LiteralPath '.\app_icon_contact_sheet.png'`

- [ ] **Step 6: Commit the adaptive icon set**

```bash
git add scripts/build_app_icons.py tests/test_app_icon_assets.py assets/app_icon.png assets/app_icon.ico assets/app_icon.icns
git commit -m "feat: add adaptive HemaFrag application icons"
```

---

### Task 2: Harden Runtime and Packaged Application Identity

**Files:**
- Create: `app_resources.py`
- Create: `tests/test_app_resources.py`
- Modify: `app_meta.py`
- Modify: `qt_app.py`
- Modify: `build_qt.py`

**Interfaces:**
- Produces: `APP_BUNDLE_ID: str = "no.ous.hemafrag"`
- Produces: `application_resource_roots(bundle_dir=None) -> tuple[Path, ...]`
- Produces: `resolve_app_icon_path(platform_name=None, bundle_dir=None, search_roots=None) -> Path | None`
- Produces: `load_application_icon(platform_name=None, bundle_dir=None, search_roots=None, icon_factory=None, log_message=None)`
- Produces: `set_windows_app_user_model_id(platform_name=None, app_id=APP_BUNDLE_ID, setter=None, log_message=None) -> bool`
- Consumes: original icon files preserved from `origin/main`

- [ ] **Step 1: Write failing tests for resource lookup and Windows identity**

```python
# tests/test_app_resources.py
from pathlib import Path

from app_meta import APP_BUNDLE_ID
from app_resources import load_application_icon, resolve_app_icon_path, set_windows_app_user_model_id


class _FakeIcon:
    def __init__(self, path: str, *, null: bool = False):
        self.path = path
        self._null = null

    def isNull(self) -> bool:
        return self._null


def test_windows_prefers_ico_and_linux_prefers_png(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app_icon.ico").write_bytes(b"ico")
    (assets / "app_icon.png").write_bytes(b"png")
    assert resolve_app_icon_path(platform_name="win32", search_roots=[tmp_path]).suffix == ".ico"
    assert resolve_app_icon_path(platform_name="linux", search_roots=[tmp_path]).suffix == ".png"


def test_load_application_icon_rejects_null_icon(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app_icon.png").write_bytes(b"invalid")
    messages: list[str] = []
    icon = load_application_icon(
        platform_name="linux",
        search_roots=[tmp_path],
        icon_factory=lambda path: _FakeIcon(path, null=True),
        log_message=messages.append,
    )
    assert icon is None
    assert "invalid or unsupported" in messages[-1]


def test_windows_app_id_is_set_only_on_windows():
    calls: list[str] = []
    assert set_windows_app_user_model_id(platform_name="linux", setter=calls.append) is False
    assert calls == []
    assert set_windows_app_user_model_id(platform_name="win32", setter=lambda value: calls.append(value)) is True
    assert calls == [APP_BUNDLE_ID]


def test_windows_build_contract_uses_committed_ico(monkeypatch):
    import build_qt

    monkeypatch.setattr(build_qt.sys, "platform", "win32")
    monkeypatch.setattr(build_qt.Path, "exists", lambda self: True)
    args = build_qt._build_pyinstaller_args()
    assert "--icon=assets/app_icon.ico" in args
```

- [ ] **Step 2: Run the tests and verify `app_resources` is missing**

Run: `python -m pytest tests/test_app_resources.py -q`

Expected: collection fails because `app_resources.py` does not exist.

- [ ] **Step 3: Add shared metadata and the portable resource helper**

Add to `app_meta.py`:

```python
APP_BUNDLE_ID = "no.ous.hemafrag"
```

Implement `app_resources.py` with these platform preferences and failure behavior:

```python
_ICON_NAMES = {
    "win32": ("app_icon.ico", "app_icon.png"),
    "darwin": ("app_icon.icns", "app_icon.png"),
    "linux": ("app_icon.png", "app_icon.ico"),
}
```

The helper must search, in order: an explicit `bundle_dir`, `sys._MEIPASS`, `<executable>/_internal`, the executable directory, the repository/module directory, and `<sys.prefix>/share/hemafrag`. Deduplicate with resolved, case-normalized paths. `load_application_icon` imports `QIcon` only inside the function, returns `None` for a missing/invalid icon, and reports through the supplied logger. `set_windows_app_user_model_id` calls `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID` only when the effective platform is `win32` and treats return values `None` and `0` as success.

Use `git show 808e3a8:app_resources.py` as the read-only reference for the already-proven resolver implementation, then add that module through `apply_patch`. Keep its public signatures and platform ordering exactly as listed in this task; do not bring any other file from that historical commit into this branch.

- [ ] **Step 4: Wire the identity into application startup before Qt is created**

Update `qt_app.py` so the order inside `main()` is:

```python
set_windows_app_user_model_id(log_message=log)
app = QApplication(sys.argv)
app.setApplicationName(APP_NAME)
app.setOrganizationName("OUS")
app.setApplicationVersion(APP_VERSION)
app_icon = load_application_icon(bundle_dir=_BUNDLE_DIR, log_message=log)
if app_icon is not None:
    app.setWindowIcon(app_icon)
```

After constructing `MainWindow`, set the same non-null icon on the window. Remove direct construction from `_BUNDLE_DIR / "assets" / "app_icon.png"`.

- [ ] **Step 5: Make packaging consume the shared bundle identifier**

Change `build_qt.py` to import `APP_BUNDLE_ID` with `APP_VERSION`, delete its local `BUNDLE_ID`, and emit:

```python
args.append(f"--osx-bundle-identifier={APP_BUNDLE_ID}")
```

Keep the existing platform icon contract: ICNS on macOS and ICO on Windows.

- [ ] **Step 6: Run focused identity tests**

Run: `python -m pytest tests/test_app_resources.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit runtime identity hardening**

```bash
git add app_meta.py app_resources.py qt_app.py build_qt.py tests/test_app_resources.py
git commit -m "fix: stabilize HemaFrag desktop identity"
```

---

### Task 3: Refine the App Shell and Preserve Three-Workspace Navigation

**Files:**
- Create: `gui_qt/widgets/brand_lockup.py`
- Create: `tests/test_main_window_navigation.py`
- Modify: `gui_qt/main_window.py`
- Modify: `gui_qt/styles.py`
- Modify: `tests/test_clonality_interp_integration.py`

**Interfaces:**
- Produces: `BrandLockup(icon: QIcon | None = None, icon_size: QSize = QSize(30, 30), descriptor: str = "Diagnostics", parent=None)`
- Produces: `AnalysisGroup.button_for_label(label: str) -> AnalysisSubButton | None`
- Produces: `MainWindow._activate_sub_label(label: str) -> None`
- Consumes: `QApplication.windowIcon()` set in Task 2

- [ ] **Step 1: Replace the outdated ML Training regression and add shell tests**

Rename the existing regression to `test_clonality_sidebar_exposes_labeling_not_ml_training` and make it assert:

```python
assert "ML Training" not in sub_labels
assert "Labeling" in sub_labels
labeling_idx = sub_labels.index("Labeling")
w.on_sub_tab_clicked("clonality", labeling_idx)
from gui_qt.tabs.tab_labeling import TabLabeling
assert isinstance(w.stacked_widget.currentWidget().widget(), TabLabeling)
```

Create `tests/test_main_window_navigation.py`:

```python
from PyQt6.QtWidgets import QWidget

from gui_qt.main_window import MainWindow


def test_analysis_groups_keep_exact_navigation_contract(qapp):
    window = MainWindow()
    assert window.group_clonality.sub_button_labels == ["Run", "Ladder", "Archive Runner", "Log", "Labeling", "Settings"]
    assert window.group_flt3.sub_button_labels == ["Run", "Ladder", "Archive Runner", "Log", "Settings"]
    assert window.group_general.sub_button_labels == ["Run", "Ladder", "Log", "Settings"]
    assert not hasattr(window, "tab_ml_training")


def test_semantic_shortcuts_do_not_depend_on_clonality_positions(qapp, monkeypatch):
    from config import APP_SETTINGS

    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    monkeypatch.setattr("gui_qt.main_window.save_settings", lambda settings: None)
    window = MainWindow()
    window.on_group_clicked(window.group_clonality)
    window._activate_sub_label("Labeling")
    assert window.stacked_widget.currentIndex() == window.tab_labeling_idx
    window.on_group_clicked(window.group_flt3)
    window._activate_sub_label("Settings")
    assert window.stacked_widget.currentIndex() == window.tab_settings_flt3_idx
    window.on_group_clicked(window.group_general)
    window._activate_sub_label("Log")
    assert window.stacked_widget.currentIndex() == window.tab_log_idx


def test_sidebar_has_branded_lockup(qapp):
    window = MainWindow()
    lockup = window.findChild(QWidget, "SidebarBrandLockup")
    assert lockup is not None
    assert lockup.findChild(QWidget, "SidebarBrandMark") is not None
    assert lockup.findChild(QWidget, "SidebarBrandText") is not None
```

- [ ] **Step 2: Run the navigation tests and verify current behavior fails**

Run: `python -m pytest tests/test_main_window_navigation.py tests/test_clonality_interp_integration.py::test_clonality_sidebar_exposes_labeling_not_ml_training -q`

Expected: failures show ML Training is still present, `_activate_sub_label` is missing, and no brand lockup exists.

- [ ] **Step 3: Implement the reusable brand lockup**

Implement `BrandLockup` as a horizontal widget with these object names:

```python
self.setObjectName("SidebarBrandLockup")
self.mark.setObjectName("SidebarBrandMark")
self.wordmark.setObjectName("SidebarBrandText")
self.descriptor_label.setObjectName("SidebarBrandDescriptor")
```

Use the supplied icon when non-null; otherwise render `HF` in the mark label so tests and missing-asset launches still have a recognizable fallback. The text stack is exactly `HEMAFRAG` and the configurable descriptor.

- [ ] **Step 4: Remove ML Training and make navigation label-driven**

In `gui_qt/main_window.py`:

- Remove imports of `TabMlTraining` and the unused `TabClonalityInterpretation`.
- Replace the text-only brand with `BrandLockup(QApplication.instance().windowIcon())`.
- Set Clonality labels to `Run`, `Ladder`, `Archive Runner`, `Log`, `Labeling`, `Settings`.
- Do not construct or add `tab_ml_training` to the stack.
- Remove `ML Training` from `_sub_button_map`.
- Add `AnalysisGroup.button_for_label()` and use it to derive `btn_run`.
- Replace position-based Alt-letter handling with this exact semantic map:

```python
shortcut_labels = {
    "R": "Run",
    "L": "Ladder",
    "A": "Archive Runner",
    "G": "Log",
    "B": "Labeling",
    "S": "Settings",
}
```

`_activate_sub_label` must no-op when the active analysis lacks the requested label. Keep Alt+1/2/3 and Ctrl+, unchanged.

Implement the semantic lookup with these bodies:

```python
def button_for_label(self, label: str) -> AnalysisSubButton | None:
    try:
        return self.sub_buttons[self.sub_button_labels.index(label)]
    except ValueError:
        return None


def _activate_sub_label(self, label: str) -> None:
    active = APP_SETTINGS.get("active_analysis", "clonality")
    group = {
        "clonality": self.group_clonality,
        "flt3": self.group_flt3,
        "general": self.group_general,
    }.get(active, self.group_clonality)
    button = group.button_for_label(label)
    if button is None:
        return
    tab_idx = group.sub_button_labels.index(label)
    self.btn_about.setChecked(False)
    for other_group in self.groups:
        for other_button in other_group.sub_buttons:
            other_button.setChecked(other_button is button)
    self.on_sub_tab_clicked(group.internal_id, tab_idx)
```

- [ ] **Step 5: Add Clinical Workbench shell styles**

Update `gui_qt/styles.py` so the lockup has 20 px horizontal margins, a 30 px mark, white wordmark, muted blue-gray descriptor, and a subtle bottom divider. Tighten analysis header/sub-button vertical padding while preserving visible hover, checked, and focus states. Use only approved palette colors.

- [ ] **Step 6: Run navigation and shell tests**

Run: `python -m pytest tests/test_main_window_navigation.py tests/test_clonality_interp_integration.py -q`

Expected: all tests pass; legacy interpretation/model tests outside main-window navigation remain unchanged.

- [ ] **Step 7: Commit the app shell refinement**

```bash
git add gui_qt/widgets/brand_lockup.py gui_qt/main_window.py gui_qt/styles.py tests/test_main_window_navigation.py tests/test_clonality_interp_integration.py
git commit -m "feat: refine three-workspace app navigation"
```

---

### Task 4: Redesign About with Readable Legal Content

**Files:**
- Create: `tests/test_tab_about.py`
- Modify: `gui_qt/tabs/tab_about.py`
- Modify: `gui_qt/styles.py`

**Interfaces:**
- Produces: one `QWidget#AboutHero`
- Produces: one `QTabWidget#AboutLegalTabs` with tabs `Third-party`, `Repository notice`, and `MIT license`
- Produces: three `QTextBrowser#AboutTextBrowser` instances
- Consumes: `APP_OVERVIEW`, `THIRD_PARTY_SOFTWARE`, `THIRD_PARTY_NOTICE_PATH`, and `UPSTREAM_LICENSE_PATH` without changing their data format

- [ ] **Step 1: Write failing About structure and content tests**

```python
# tests/test_tab_about.py
from PyQt6.QtWidgets import QTabWidget, QTextBrowser, QWidget

from app_meta import APP_NAME, APP_VERSION
from gui_qt.tabs.tab_about import TabAbout


def test_about_uses_compact_hero_and_three_legal_tabs(qapp):
    tab = TabAbout()
    assert tab.findChild(QWidget, "AboutHero") is not None
    legal = tab.findChild(QTabWidget, "AboutLegalTabs")
    assert legal is not None
    assert [legal.tabText(index) for index in range(legal.count())] == ["Third-party", "Repository notice", "MIT license"]
    browsers = tab.findChildren(QTextBrowser, "AboutTextBrowser")
    assert len(browsers) == 3


def test_about_keeps_identity_and_full_legal_sources(qapp):
    tab = TabAbout()
    visible_text = " ".join(label.text() for label in tab.findChildren(QWidget) if hasattr(label, "text"))
    assert APP_NAME in visible_text
    assert APP_VERSION in visible_text
    documents = "\n".join(browser.toPlainText() for browser in tab.findChildren(QTextBrowser, "AboutTextBrowser"))
    assert "fraggler" in documents.lower()
    assert "MIT License" in documents
```

- [ ] **Step 2: Run the About tests and verify the old stacked layout fails**

Run: `python -m pytest tests/test_tab_about.py -q`

Expected: the hero and tab widget assertions fail.

- [ ] **Step 3: Build the compact About hierarchy**

Refactor `TabAbout` to create:

1. `QWidget#AboutHero` with `QApplication.instance().windowIcon().pixmap(QSize(56, 56))`, `About HemaFrag Diagnostics`, version, and the existing subtitle. Use the `HF` fallback mark when the application icon is null.
2. `QWidget#AboutSummaryCard` with separate version, maintenance-context, and repository-license rows.
3. `QWidget#AboutLegalCard` containing `QTabWidget#AboutLegalTabs`.
4. Three `QTextBrowser#AboutTextBrowser` widgets populated from the same markdown/plain-text sources used today.

Set each browser to read-only, external-link enabled where applicable, and a 260 px minimum height. Remove the three separate tall legal cards.

- [ ] **Step 4: Add explicit readable About styles**

Add selectors in `gui_qt/styles.py` for:

```css
QTextBrowser#AboutTextBrowser {
    background: #ffffff;
    color: #102235;
    border: 1px solid #d8e5ef;
    border-radius: 10px;
    padding: 10px;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
}
```

Also style `AboutHero`, `AboutSummaryCard`, and `AboutLegalCard` with the approved card/background palette and a readable `#2563EB` link color.

- [ ] **Step 5: Run About tests and inspect the page in the real app**

Run: `python -m pytest tests/test_tab_about.py -q`

Expected: 2 tests pass.

Launch: `python qt_app.py`

Open About and confirm all three legal tabs use dark text on a light background, version `1.2.0` is visible, and the page does not require three large stacked cards.

- [ ] **Step 6: Commit the About redesign**

```bash
git add gui_qt/tabs/tab_about.py gui_qt/styles.py tests/test_tab_about.py
git commit -m "feat: redesign the HemaFrag About page"
```

---

### Task 5: Make the Ladder Editor Compact and Hierarchical

**Files:**
- Create: `tests/test_ladder_editor_layout.py`
- Modify: `gui_qt/dialogs/ladder_dialog/_legacy.py`

**Interfaces:**
- Produces: `QWidget#TraceViewControls`
- Produces: `QWidget#TraceAssignControls`
- Produces: `QScrollArea#SizingQcScroll` containing `QWidget#SizingQcPanel`
- Produces: `QWidget#LadderActionBar`
- Preserves: `_build_adjustment_payload()`, `_suggest_auto()`, `_preview_fit()`, `_on_apply()`, `_on_save_note_only()`, candidate/match tables, and all existing shortcut bindings

- [ ] **Step 1: Write a compact-layout test around a lightweight fake FSA**

```python
# tests/test_ladder_editor_layout.py
from types import SimpleNamespace

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QScrollArea, QWidget

from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog


def _fake_fsa():
    steps = np.array([35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400], dtype=float)
    return SimpleNamespace(
        file_name="compact-layout.fsa",
        ladder="ROX400HD",
        analysis_id="clonality",
        ladder_steps=steps,
        expected_ladder_steps=steps,
        size_standard=np.zeros(1200, dtype=float),
        best_size_standard=np.array([], dtype=float),
    )


def test_ladder_editor_exposes_grouped_controls_and_scrollable_qc(qapp, monkeypatch):
    monkeypatch.setattr(LadderAdjustmentDialog, "_get_candidates", lambda self: pd.DataFrame(columns=["index", "time", "intensity", "source"]))
    monkeypatch.setattr(LadderAdjustmentDialog, "_suggest_auto", lambda self, store_initial: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_preview_state", lambda self, show_errors: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_all", lambda self: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)
    dialog = LadderAdjustmentDialog(_fake_fsa())
    dialog.resize(1024, 700)
    dialog.show()
    qapp.processEvents()
    assert dialog.minimumWidth() <= 1024
    assert dialog.minimumHeight() <= 700
    assert dialog.findChild(QWidget, "TraceViewControls") is not None
    assert dialog.findChild(QWidget, "TraceAssignControls") is not None
    qc_scroll = dialog.findChild(QScrollArea, "SizingQcScroll")
    assert qc_scroll is not None
    assert qc_scroll.horizontalScrollBarPolicy().name == "ScrollBarAlwaysOff"
    assert dialog.findChild(QWidget, "LadderActionBar") is not None
    dialog.close()
```

- [ ] **Step 2: Run the layout test and verify current geometry fails**

Run: `python -m pytest tests/test_ladder_editor_layout.py -q`

Expected: the dialog minimum size is 1180×780 and the named control/QC widgets are absent.

- [ ] **Step 3: Lower the safe minimum geometry without changing editor data**

Change the dialog fallback and screen-aware minimum from 1180×780 to 980×680. Keep the preferred maximum at 1700×1040. Keep the plot and editor rail in the existing horizontal splitter and do not change any mapping, preview, or save methods.

- [ ] **Step 4: Split the trace toolbar into View and Assign rows**

Keep the same nine buttons and signal connections. Replace the single horizontal row with a vertical toolbar containing:

- `QWidget#TraceViewControls`: Full Trace, Ladder Region, Zoom Selected, Y Auto, Y 300, Y 1000.
- `QWidget#TraceAssignControls`: Trace Assign, Next Missing, Order.

Each row begins with a fixed-width muted label (`VIEW` or `ASSIGN`). This is a layout-only change; button names, checkable state, tooltips, and handlers remain unchanged.

- [ ] **Step 5: Put QC in a vertical-only scroll area**

Rename the QC card object to `SizingQcPanel`, remove its 190 px maximum height, and wrap it in `QScrollArea#SizingQcScroll` configured with:

```python
qc_scroll.setWidgetResizable(True)
qc_scroll.setFrameShape(QFrame.Shape.NoFrame)
qc_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
qc_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
qc_scroll.setWidget(qc_card)
```

Add the scroll area—not the raw card—to the existing vertical splitter. Preserve the QC grade, summary, linear fit, reason, review notes, and residual canvas.

- [ ] **Step 6: Clarify action hierarchy and keep every action reachable**

Rename the action container object to `LadderActionBar`. Keep all existing buttons and order. Preserve `Save Adjustment` as `PrimaryButton`; set `Clear All` to `DangerButton`; set `Cancel`, `Reset To Initial`, and `Save Note Only` to `SecondaryButton`. Allow `stats_label` to shrink and wrap rather than forcing the action buttons outside the dialog.

Add local QSS for the new group labels, compact toolbar rows, `DangerButton`, and keyboard focus. Use the approved danger color `#DC2626` for the destructive outline/text, not as a filled primary action.

- [ ] **Step 7: Run the focused dialog test and existing ladder tests**

Run: `python -m pytest tests/test_ladder_editor_layout.py tests/test_ladder_review_gate.py tests/test_tab_ladder_submodules.py -q`

Expected: all selected tests pass; no saved-payload assertions change.

- [ ] **Step 8: Manually verify both target sizes with a representative ladder file**

Launch the worktree app, open Ladder Editor, and inspect 1200×800 and 1024×700. Confirm:

- View and Assign controls remain reachable.
- Matches and Candidates retain current behavior.
- QC can be fully read with vertical scrolling and never requires horizontal scrolling.
- `Save Adjustment` remains the only primary action.
- Review bundles still show `Save Note Only` and the comment box.
- No label, badge, or report gives 35 bp special treatment.

- [ ] **Step 9: Commit the Ladder Editor refinement**

```bash
git add gui_qt/dialogs/ladder_dialog/_legacy.py tests/test_ladder_editor_layout.py
git commit -m "feat: refine the compact Ladder Editor workspace"
```

---

### Task 6: Integrated Verification and Branch Review

**Files:**
- Review: all files changed by Tasks 1–5
- Test: full relevant Python test suite
- Verify: source launch and platform packaging arguments

**Interfaces:**
- Consumes: all deliverables from Tasks 1–5
- Produces: a clean, reviewed branch with passing tests and no Rust changes

- [ ] **Step 1: Run formatting and whitespace checks**

Run: `git diff --check origin/main...HEAD`

Expected: no whitespace errors.

- [ ] **Step 2: Run the focused UI and identity suite together**

Run:

```powershell
python -m pytest tests/test_app_resources.py tests/test_main_window_navigation.py tests/test_tab_about.py tests/test_ladder_editor_layout.py tests/test_clonality_interp_integration.py -q
```

Expected: all focused tests pass in one process.

- [ ] **Step 3: Run broader regression tests**

Run: `python -m pytest tests -q`

Expected: the suite passes. Any pre-existing environment-only failure must be reproduced on `origin/main` before it is classified as unrelated.

- [ ] **Step 4: Re-run the side-effect-free packaging contract test**

Run: `python -m pytest tests/test_app_resources.py::test_windows_build_contract_uses_committed_ico -q`

Expected: the test passes without building or modifying the Rust engine.

- [ ] **Step 5: Perform the final live-app acceptance pass**

Launch: `python qt_app.py`

Verify in the real app:

1. Small title-bar/taskbar icon is recognizable.
2. Sidebar shows the HemaFrag lockup and Clonality, FLT3, General.
3. ML Training is absent and Labeling opens.
4. Each analysis group opens Run, Ladder, Log, and its own Settings; Archive Runner remains available where specified.
5. About has readable light legal panes and all three tabs.
6. Ladder Editor passes both target-size checks.

- [ ] **Step 6: Confirm scope and inspect the final diff**

Run:

```powershell
git status --short
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD | Select-String -Pattern 'fraggler-v2|\.rs$|wheels'
```

Expected: the worktree is clean and the final command prints no Rust source or wheel paths.

- [ ] **Step 7: Review the completed branch before integration**

Use `agent-skills:code-review-and-quality` and `superpowers:verification-before-completion`. Review navigation correctness, Qt lifetime/ownership, resource fallbacks, accessibility, test coverage, and packaging behavior. Resolve review findings with focused tests and a separate correction commit before offering branch integration.
