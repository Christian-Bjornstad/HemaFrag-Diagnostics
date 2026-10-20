from types import SimpleNamespace

import pytest

from gui_qt.tabs.tab_ladder import TabLadder
from gui_qt.tabs.tab_ladder import _legacy as module


@pytest.mark.parametrize(
    "before,labels,expected",
    [
        (2, ["manual_adjusted", ""], False),
        (1, ["manual_adjusted", "reviewed_no_change"], True),
        (1, ["manual_adjusted", "manual_partial_draft"], False),
        (1, ["manual_adjusted", "excluded_unusable_ladder"], True),
        (0, ["manual_adjusted"], False),
    ],
)
def test_return_prompt_only_when_last_unresolved_case_is_saved(
    monkeypatch, before, labels, expected
):
    messages = []
    returned = []

    class Message:
        Icon = module.QMessageBox.Icon
        ButtonRole = module.QMessageBox.ButtonRole

        def __init__(self, parent):
            messages.append(self)

        def setIcon(self, value):
            pass

        def setWindowTitle(self, value):
            pass

        def setText(self, value):
            pass

        def setInformativeText(self, value):
            pass

        def addButton(self, text, role):
            return text

        def exec(self):
            pass

        def clickedButton(self):
            return "Back To Run"

    tab = SimpleNamespace(
        _review_bundle_cases=[{"label": label} for label in labels],
        _return_to_run_tab_for_review=lambda: returned.append(True),
    )
    tab._review_bundle_counts = lambda: TabLadder._review_bundle_counts(tab)
    monkeypatch.setattr(module, "QMessageBox", Message)
    TabLadder._offer_return_after_review_complete(tab, before)
    assert bool(messages) is expected
    assert bool(returned) is expected
