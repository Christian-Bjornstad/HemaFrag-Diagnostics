from pathlib import Path
from types import SimpleNamespace


def test_liz_size_standard_channel_uses_available_abi_channel(monkeypatch):
    from core.analysis import _constants

    def fake_read(_path, _format):
        return SimpleNamespace(
            annotations={
                "abif_raw": {
                    "DATA1": [1],
                    "DATA2": [2],
                    "DATA3": [3],
                    "DATA4": [4],
                    "DATA5": [5],
                }
            }
        )

    monkeypatch.setattr(_constants.SeqIO, "read", fake_read)

    assert (
        _constants._preferred_size_standard_channel_for_file(
            Path("sample.fsa"),
            "LIZ500_250",
        )
        == "DATA5"
    )


def test_liz_size_standard_channel_prefers_data105(monkeypatch):
    from core.analysis import _constants

    def fake_read(_path, _format):
        return SimpleNamespace(
            annotations={
                "abif_raw": {
                    "DATA1": [1],
                    "DATA5": [5],
                    "DATA105": [105],
                }
            }
        )

    monkeypatch.setattr(_constants.SeqIO, "read", fake_read)

    assert (
        _constants._preferred_size_standard_channel_for_file(
            Path("sample.fsa"),
            "LIZ500_250",
        )
        == "DATA105"
    )
