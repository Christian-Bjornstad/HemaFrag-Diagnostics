from core.analyses.clonality import pipeline


def test_clonality_uses_rust_worker_mode_instead_of_python_pool(monkeypatch):
    from config import APP_SETTINGS

    monkeypatch.delenv("HEMAFRAG_CLONALITY_ALLOW_PYTHON_POOL_WITH_RUST", raising=False)
    monkeypatch.delenv("FRAGGLER_DISABLE_MULTIPROCESSING", raising=False)
    monkeypatch.setattr(pipeline, "_rust_worker_batch_mode_available", lambda: True)
    APP_SETTINGS.setdefault("engine", {})["use_rust"] = True

    assert not pipeline._should_use_multiprocessing()


def test_clonality_python_pool_can_be_explicitly_restored(monkeypatch, tmp_path):
    from config import APP_SETTINGS

    main_file = tmp_path / "runner.py"
    main_file.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setenv("HEMAFRAG_CLONALITY_ALLOW_PYTHON_POOL_WITH_RUST", "1")
    monkeypatch.setattr(pipeline.__main__, "__file__", str(main_file), raising=False)
    monkeypatch.setattr(pipeline, "_rust_worker_batch_mode_available", lambda: True)
    APP_SETTINGS.setdefault("engine", {})["use_rust"] = True

    assert pipeline._should_use_multiprocessing()


def test_clonality_python_pool_stays_available_when_rust_worker_missing(monkeypatch, tmp_path):
    from config import APP_SETTINGS

    main_file = tmp_path / "runner.py"
    main_file.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.delenv("HEMAFRAG_CLONALITY_ALLOW_PYTHON_POOL_WITH_RUST", raising=False)
    monkeypatch.delenv("FRAGGLER_DISABLE_MULTIPROCESSING", raising=False)
    monkeypatch.setattr(pipeline.__main__, "__file__", str(main_file), raising=False)
    monkeypatch.setattr(pipeline, "_rust_worker_batch_mode_available", lambda: False)
    APP_SETTINGS.setdefault("engine", {})["use_rust"] = True

    assert pipeline._should_use_multiprocessing()
