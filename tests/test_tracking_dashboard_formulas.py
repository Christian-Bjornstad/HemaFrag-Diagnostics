"""Live dashboards must survive appends, reruns, and operator edits."""
import pytest
from openpyxl import load_workbook


@pytest.fixture(params=["flt3", "clonality"])
def tracking_case(request):
    if request.param == "flt3":
        from test_flt3_tracking_output import _entry
        from core.analyses.flt3.qc_tracker import update_flt3_npm1_qc_tracker_workbook as update
        return request.param, _entry, update, 6
    from test_clonality_tracking_output import _entry
    from core.analyses.clonality.tracking_excel import update_clonality_tracking_workbook as update
    return request.param, _entry, update, 5


def test_dashboard_formulas_and_history_extend(tmp_path, tracking_case):
    analysis, entry, update, metric_row = tracking_case
    path = tmp_path / "history.xlsx"
    first = entry("26OUM00001_FR1_A01.fsa")
    first["source_run_dir"] = "synthetic_run"
    update(path, [first])
    book = load_workbook(path)
    sheet = book["Runs"]
    sheet.cell(1, sheet.max_column + 1, "OperatorCalculation")
    sheet.cell(2, sheet.max_column, "=LEN(D2)")
    book.create_sheet("Lab notes")["A1"] = "Keep this note"
    book.save(path)
    book.close()
    second = entry("26OUM00002_FR1_A02.fsa")
    second["source_run_dir"] = "synthetic_run"
    second["ladder_qc_status"] = "warning"
    update(path, [first, second])
    update(path, [first])

    book = load_workbook(path)
    sheet = book["Runs"]
    headers = {c.value: c.column for c in sheet[1]}
    assert sheet.max_row == 3
    assert book["Lab notes"]["A1"].value == "Keep this note"
    assert sheet.cell(3, headers["OperatorCalculation"]).value == "=LEN(D3)"
    for name in ("DashboardReview", "DashboardMonth", "DashboardAccepted", "DashboardOpenReview"):
        assert sheet.cell(2, headers[name]).data_type == "f"
        assert sheet.cell(3, headers[name]).data_type == "f"
    dashboard = book["Dashboard"]
    assert dashboard.cell(metric_row, 1).data_type == "f"
    assert dashboard["B17"].data_type == "f"
    monthly_row = next(c.row for row in dashboard for c in row if c.value == "Monthly trends")
    assert any(c.data_type == "f" for row in dashboard.iter_rows(min_row=monthly_row + 2) for c in row)
    assert len(dashboard._charts) >= 2
    assert book.calculation.calcMode == "auto"
    assert book.calculation.fullCalcOnLoad
    assert not any(cell.data_type == "e" for ws in book for row in ws for cell in row)
    book.close()


def test_empty_dashboard_is_valid(tmp_path, tracking_case):
    _, _, update, metric_row = tracking_case
    path = tmp_path / "empty.xlsx"
    update(path, [])
    book = load_workbook(path)
    assert book["Dashboard"].cell(metric_row, 1).data_type == "f"
    monthly_row = next(c.row for row in book["Dashboard"] for c in row if c.value == "Monthly trends")
    assert book["Dashboard"].cell(monthly_row + 2, 2).data_type == "f"
    book.close()
