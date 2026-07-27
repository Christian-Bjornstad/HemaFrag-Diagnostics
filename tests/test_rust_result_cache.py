from pathlib import Path
import sys


def test_cli_resolver_searches_from_repository_root(monkeypatch):
    from core.rust_bridge import _legacy as rust_bridge

    cli_name = "fraggler-cli.exe" if sys.platform == "win32" else "fraggler-cli"
    expected = (
        Path(rust_bridge.__file__).resolve().parents[2]
        / "fraggler-v2"
        / "target"
        / "release"
        / cli_name
    )
    monkeypatch.setattr(rust_bridge, "_CLI_BIN_CACHE", None)
    monkeypatch.setattr(Path, "exists", lambda path: path == expected)

    assert rust_bridge._resolve_cli_bin() == expected


def test_rust_subprocess_options_are_available_after_module_split():
    from core.rust_bridge import _legacy as rust_bridge

    assert isinstance(rust_bridge._windows_subprocess_kwargs(), dict)


def test_cached_rust_result_is_reusable(monkeypatch):
    from core.rust_bridge import _legacy as rust_bridge

    monkeypatch.setattr(rust_bridge, "_RUST_RESULT_CACHE_MAX", 8)
    with rust_bridge._RUST_RESULT_CACHE_LOCK:
        rust_bridge._RUST_RESULT_CACHE.clear()

    result = {"ok": True, "file": "a.fsa"}
    path = Path("/tmp/a.fsa")
    rust_bridge._store_cached_rust_result(path, "clonality", result)

    assert rust_bridge._get_cached_rust_result(path, "clonality") is result
    assert rust_bridge._get_cached_rust_result(path, "clonality") is result


def test_cached_rust_result_prunes_old_entries(monkeypatch):
    from core.rust_bridge import _legacy as legacy

    monkeypatch.setattr(legacy, "_RUST_RESULT_CACHE_MAX", 2)
    with legacy._RUST_RESULT_CACHE_LOCK:
        legacy._RUST_RESULT_CACHE.clear()

    legacy._store_cached_rust_result(Path("/tmp/a.fsa"), "clonality", {"file": "a"})
    legacy._store_cached_rust_result(Path("/tmp/b.fsa"), "clonality", {"file": "b"})
    legacy._store_cached_rust_result(Path("/tmp/c.fsa"), "clonality", {"file": "c"})

    assert legacy._get_cached_rust_result(Path("/tmp/a.fsa"), "clonality") is None
    assert legacy._get_cached_rust_result(Path("/tmp/b.fsa"), "clonality") == {"file": "b"}
    assert legacy._get_cached_rust_result(Path("/tmp/c.fsa"), "clonality") == {"file": "c"}


def test_cached_rust_result_invalidates_when_file_changes(tmp_path, monkeypatch):
    from core.rust_bridge import _legacy as rust_bridge

    monkeypatch.setattr(rust_bridge, "_RUST_RESULT_CACHE_MAX", 8)
    with rust_bridge._RUST_RESULT_CACHE_LOCK:
        rust_bridge._RUST_RESULT_CACHE.clear()

    path = tmp_path / "sample.fsa"
    path.write_text("old", encoding="utf-8")
    rust_bridge._store_cached_rust_result(path, "clonality", {"file": "old"})
    assert rust_bridge._get_cached_rust_result(path, "clonality") == {"file": "old"}

    path.write_text("new contents", encoding="utf-8")
    assert rust_bridge._get_cached_rust_result(path, "clonality") is None


def test_rust_worker_owner_pid_prevents_reusing_inherited_worker(monkeypatch):
    from core.rust_bridge import _legacy as rust_bridge

    created = []

    class DummyProc:
        def poll(self):
            return None

    class DummyWorker:
        def __init__(self, _cli_bin):
            self._proc = DummyProc()
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

    inherited = DummyWorker("old")
    monkeypatch.setattr(rust_bridge, "_persistent_rust_worker_supported", lambda: True)
    monkeypatch.setattr(rust_bridge, "_resolve_cli_bin", lambda: Path("/tmp/fraggler-cli"))
    monkeypatch.setattr(Path, "exists", lambda _self: True)
    monkeypatch.setattr(rust_bridge, "_RustPrimitiveWorker", DummyWorker)
    monkeypatch.setattr(rust_bridge, "_RUST_WORKER", inherited)
    monkeypatch.setattr(rust_bridge, "_RUST_WORKER_OWNER_PID", -1)

    worker = rust_bridge._get_rust_worker()

    assert worker is not inherited
    assert worker is created[-1]


def test_persistent_rust_worker_can_be_disabled_by_env(monkeypatch):
    from core.rust_bridge import _legacy as rust_bridge

    monkeypatch.setenv("HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER", "1")

    assert not rust_bridge._persistent_rust_worker_supported()


def test_rust_engine_stats_helpers():
    from core.rust_bridge import _legacy as rust_bridge

    rust_bridge.reset_rust_engine_stats()
    rust_bridge._increment_rust_engine_stat("cache_hits")
    rust_bridge._increment_rust_engine_stat("prewarm_cached", 3)

    stats = rust_bridge.rust_engine_stats_snapshot()

    assert stats["cache_hits"] == 1
    assert stats["prewarm_cached"] == 3
    assert "cache=1" in rust_bridge.format_rust_engine_stats(stats)
    assert "prewarm_cached=3" in rust_bridge.format_rust_engine_stats(stats)

    rust_bridge.merge_rust_engine_stats({"cache_hits": 2, "cli_hits": 1})
    merged = rust_bridge.rust_engine_stats_snapshot()
    assert merged["cache_hits"] == 3
    assert merged["cli_hits"] == 1
