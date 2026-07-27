from core.html_reports import extract_dit_from_name


def test_extract_dit_normalizes_case():
    assert extract_dit_from_name("25oum12345_FR1_A01.fsa") == "25OUM12345"


def test_extract_dit_returns_none_when_identifier_is_absent():
    assert extract_dit_from_name("PK_FR1_A01.fsa") is None
