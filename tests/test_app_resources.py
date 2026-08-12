from pathlib import Path

from app_meta import APP_BUNDLE_ID
from app_resources import (
    load_application_icon,
    resolve_app_icon_path,
    set_windows_app_user_model_id,
)


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

    windows_icon = resolve_app_icon_path(platform_name="win32", search_roots=[tmp_path])
    linux_icon = resolve_app_icon_path(platform_name="linux", search_roots=[tmp_path])

    assert windows_icon is not None and windows_icon.suffix == ".ico"
    assert linux_icon is not None and linux_icon.suffix == ".png"


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
    assert (
        set_windows_app_user_model_id(
            platform_name="win32",
            setter=lambda value: calls.append(value),
        )
        is True
    )
    assert calls == [APP_BUNDLE_ID]


def test_windows_build_contract_uses_committed_ico(monkeypatch):
    import build_qt

    monkeypatch.setattr(build_qt.sys, "platform", "win32")
    monkeypatch.setattr(build_qt.Path, "exists", lambda self: True)

    args = build_qt._build_pyinstaller_args()

    assert build_qt.APP_BUNDLE_ID == APP_BUNDLE_ID
    assert "--icon=assets/app_icon.ico" in args


def test_qt_app_sets_windows_identity_before_qapplication():
    source = Path("qt_app.py").read_text(encoding="utf-8")

    identity_call = source.index("set_windows_app_user_model_id(log_message=log)")
    application_call = source.index("app = QApplication(sys.argv)")

    assert identity_call < application_call
