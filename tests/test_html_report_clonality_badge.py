"""Tests for the clonality ML HTML badge helpers in core/html_reports/_legacy."""
from __future__ import annotations

import json

from core.html_reports._legacy import (
    _clonality_ml_confidence_for_entry,
    _clonality_ml_label_for_entry,
    _clonality_ml_threshold_for_entry,
    _render_clonality_ml_badge,
)


class _FakeFSA:
    def __init__(self, file_name: str):
        self.file_name = file_name


def _entry(
    *,
    label: str = "",
    confidence: float | str = 0.0,
    review_needed: bool = False,
    threshold: float | str = "",
    evidence: str = "",
    rule_label: str = "",
    file_name: str = "test_FR1.fsa",
    dit: str = "26OUM00005",
    assay: str = "FR1",
) -> dict:
    """Build a minimal entry dict suitable for the badge renderer."""
    e: dict = {
        "fsa": _FakeFSA(file_name),
        "file_name": file_name,
        "assay": assay,
        "dit": dit,
        "ClonalitySuggestion": rule_label,
    }
    if label:
        e["ClonalityMLSuggestion"] = label
    if confidence:
        e["ClonalityMLConfidence"] = confidence
    if review_needed:
        e["ClonalityMLReviewNeeded"] = True
    if threshold != "":
        e["ClonalityMLThreshold"] = threshold
    if evidence:
        e["ClonalityMLEvidence"] = evidence
    return e


def test_label_helper_returns_empty_when_absent():
    assert _clonality_ml_label_for_entry(_entry()) == ""


def test_label_helper_strips_whitespace():
    assert _clonality_ml_label_for_entry(_entry(label="  monoklonal  ")) == "monoklonal"


def test_confidence_helper_returns_empty_when_blank():
    assert _clonality_ml_confidence_for_entry(_entry(confidence="")) == ""
    assert _clonality_ml_confidence_for_entry(_entry(confidence=0)) == ""


def test_confidence_helper_formats_two_decimals():
    assert _clonality_ml_confidence_for_entry(_entry(confidence=0.93)) == "0.93"
    assert _clonality_ml_confidence_for_entry(_entry(confidence=0.867)) == "0.87"


def test_threshold_helper_formats_two_decimals():
    assert _clonality_ml_threshold_for_entry(_entry(threshold=0.85)) == "0.85"


def test_render_badge_emits_dml_div_when_label_present():
    out = []
    entry = _entry(label="monoklonal", confidence=0.84, rule_label="polyklonal")
    _render_clonality_ml_badge(entry, out)
    html = "\n".join(out)
    assert html.startswith("<div")
    assert html.endswith("</div>")
    assert "monoklonal" in html
    assert "0.84" in html
    assert "polyklonal" in html


def test_render_badge_emits_warning_when_review_needed():
    out = []
    entry = _entry(label="monoklonal", confidence=0.55, review_needed=True)
    _render_clonality_ml_badge(entry, out)
    html = "\n".join(out)
    assert "ml-review-flagged" in html


def test_render_badge_shows_threshold_and_review_reason():
    out = []
    entry = _entry(
        label="monoklonal",
        confidence=0.70,
        threshold=0.85,
        review_needed=True,
        evidence="rule_ml_disagreement",
    )
    _render_clonality_ml_badge(entry, out)
    html = "\n".join(out)
    assert "grense: 0.85" in html
    assert "rule_ml_disagreement" in html


def test_render_badge_noop_when_no_label():
    """Empty label → nothing appended (avoids blank badges in HTML)."""
    out: list[str] = []
    entry = _entry()  # no ClonalityMLSuggestion
    _render_clonality_ml_badge(entry, out)
    assert out == []


def test_render_badge_includes_stable_dataset_attrs():
    """Attributes the JS dismissal serialiser relies on."""
    out = []
    entry = _entry(label="monoklonal", file_name="foo.fsa", dit="26OUM00060")
    _render_clonality_ml_badge(entry, out)
    html = "\n".join(out)
    assert "data-file='foo.fsa'" in html
    assert "data-dit='26OUM00060'" in html
    assert "data-assay='FR1'" in html
    assert "data-ml-label='monoklonal'" in html
    assert "data-state='active'" in html


def test_render_badge_is_deterministic_for_same_input():
    """Same input ⇒ same id (re-runs land on same badge)."""
    out_a: list[str] = []
    out_b: list[str] = []
    entry = _entry(label="monoklonal", file_name="x.fsa", dit="Z")
    _render_clonality_ml_badge(entry, out_a)
    _render_clonality_ml_badge(entry, out_b)
    assert out_a == out_b


def test_render_badge_emits_both_buttons():
    """Both 'Skjul for patolog' and (initially hidden) 'Gjenopprett' present."""
    out = []
    entry = _entry(label="monoklonal")
    _render_clonality_ml_badge(entry, out)
    html = "\n".join(out)
    assert "Skjul for patolog" in html
    assert "Gjenopprett" in html
