"""Excel formulas shared by the two persistent tracking dashboards.

Runs is the authoritative source. Helper formulas live beside each record, so
sorting the ledger and editing its QC/review fields update the dashboard in Excel.
The app rebuilds categories and extends formulas after every publication.
"""
from __future__ import annotations

from datetime import date, datetime

from openpyxl.chart import LineChart, Reference
from openpyxl.chart.axis import DateAxis
from openpyxl.chart.series import SeriesLabel
from openpyxl.chart.text import RichText
from openpyxl.drawing.text import CharacterProperties, Font as DrawingFont, Paragraph, ParagraphProperties
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.workbook.properties import CalcProperties

from core.tracking_workbook_io import _refresh_table


def _headers(ws):
    return {str(cell.value): cell.column for cell in ws[1] if cell.value}


def _column(ws, header):
    headers = _headers(ws)
    if header not in headers:
        ws.cell(1, ws.max_column + 1, header)
        headers = _headers(ws)
    return get_column_letter(headers[header])


def _range(ws, header):
    col = _column(ws, header)
    # The app rebuilds these bounds after every append; avoid scanning a million
    # rows per metric in large historical workbooks.
    return f"'{ws.title}'!${col}$2:${col}${max(ws.max_row, 2)}"


def _count(ws, *criteria):
    args = ",".join(f"{_range(ws, header)},{value}" for header, value in criteria)
    return f"COUNTIFS({args})"


def _average(ws, header, *criteria):
    args = ",".join(f"{_range(ws, key)},{value}" for key, value in criteria)
    return f'IFERROR(AVERAGEIFS({_range(ws, header)},{args}),"")'


def _install_run_helpers(ws, *, flt3):
    for header in ("ReviewStatus", "TrackingNote"):
        _column(ws, header)
    # Build every source reference before capturing helper-column positions.
    source_names = (
        "File", "Assay", "SampleKind", "Control", "SourceRunDir", "RunCode",
        "RunDate", "LadderQC", "LadderFitStrategy",
        "LadderExpectedStepCount", "LadderFittedStepCount",
        "LadderLinearR2", "LadderR2", "ReviewStatus",
    )
    if flt3:
        source_names += ("PeakQC", "PositiveCall", "Interpretation")
    source = {name: _column(ws, name) for name in source_names}
    names = (
        "Assay", "Run", "Patient", "Control", "Accepted", "Review", "Manual",
        "Positive", "Partial", "R2", "Date", "Month", "OpenReview",
        "FirstRun", "FirstAssay",
    )
    helpers = {name: _column(ws, f"Dashboard{name}") for name in names}
    for row in range(2, ws.max_row + 1):
        ref = {name: f"${col}{row}" for name, col in source.items()}
        h = {name: f"${col}{row}" for name, col in helpers.items()}
        ladder = f'LOWER(TRIM({ref["LadderQC"]}))'
        strategy = f'LOWER(TRIM({ref["LadderFitStrategy"]}))'
        accepted = f'OR({ladder}="ok",{ladder}="manual_adjustment")'
        review = f'AND({ref["LadderQC"]}<>"",NOT({accepted}))'
        if flt3:
            peak = f'LOWER(TRIM({ref["PeakQC"]}))'
            review = (f'OR({review},AND({ref["PeakQC"]}<>"",{peak}<>"ok",'
                      f'{peak}<>"negative_control",{peak}<>"not_evaluated_ladder_only"))')
        expressions = {
            "Assay": f'IF({ref["Assay"]}="","Unknown",{ref["Assay"]})',
            "Run": (f'IF({ref["SourceRunDir"]}<>"",{ref["SourceRunDir"]},'
                    f'IF({ref["RunCode"]}<>"",{ref["RunCode"]},'
                    f'IF({ref["RunDate"]}<>"",{ref["RunDate"]},{ref["File"]})))'),
            "Patient": f'--(LOWER(TRIM({ref["SampleKind"]}))="patient")',
            "Control": f'--OR(LOWER(TRIM({ref["SampleKind"]}))="control",{ref["Control"]}<>"")',
            "Accepted": f'--{accepted}',
            "Review": f'--{review}',
            "Manual": (f'--OR({ladder}="manual_adjustment",{ladder}="manual_partial_reviewed",'
                       f'{strategy}="manual_adjustment",{strategy}="manual_partial")'),
            "Positive": ((f'--OR({ref["PositiveCall"]}=TRUE,LOWER({ref["PositiveCall"]}&"")="true",'
                          f'LEFT(LOWER({ref["Interpretation"]}),8)="positiv ")') if flt3 else "0"),
            "Partial": (f'--AND(ISNUMBER({ref["LadderExpectedStepCount"]}),'
                        f'{ref["LadderExpectedStepCount"]}>0,ISNUMBER({ref["LadderFittedStepCount"]}),'
                        f'{ref["LadderFittedStepCount"]}<{ref["LadderExpectedStepCount"]})'),
            "R2": (f'IF(ISNUMBER({ref["LadderLinearR2"]}),{ref["LadderLinearR2"]},'
                   f'IF(ISNUMBER({ref["LadderR2"]}),{ref["LadderR2"]},""))'),
            "Date": (f'IF({ref["RunDate"]}="","",IF(ISNUMBER({ref["RunDate"]}),{ref["RunDate"]},'
                     f'IFERROR(DATE(VALUE(LEFT({ref["RunDate"]},4)),VALUE(MID({ref["RunDate"]},6,2)),'
                     f'VALUE(MID({ref["RunDate"]},9,2))),"")))'),
            "Month": f'IF({h["Date"]}="","",TEXT({h["Date"]},"yyyy-mm"))',
            "OpenReview": f'{h["Review"]}*--(LOWER(TRIM({ref["ReviewStatus"]}))<>"reviewed")',
            "FirstRun": f'--(COUNTIF(${helpers["Run"]}$2:{h["Run"]},{h["Run"]})=1)',
            "FirstAssay": f'--(COUNTIF(${helpers["Assay"]}$2:{h["Assay"]},{h["Assay"]})=1)',
        }
        for name, expression in expressions.items():
            ws[f"{helpers[name]}{row}"] = f'=IF({ref["File"]}="","",{expression})'
    for col in helpers.values():
        ws.column_dimensions[col].hidden = True
    # Own only this exact list validation; keep operator-defined validations.
    formula = '"Not reviewed,Reviewed,Follow-up"'
    for validation in list(ws.data_validations.dataValidation):
        if validation.type == "list" and validation.formula1 == formula:
            ws.data_validations.dataValidation.remove(validation)
    validation = DataValidation(type="list", formula1=formula, allow_blank=True)
    validation.errorTitle = "Choose a review status"
    validation.error = "Use Not reviewed, Reviewed, or Follow-up."
    validation.showErrorMessage = True
    ws.add_data_validation(validation)
    validation.add(f'{source["ReviewStatus"]}2:{source["ReviewStatus"]}1048576')
    _refresh_table(ws)


def _install_peak_helpers(ws):
    delta = _column(ws, "DeltaBP")
    absolute = _column(ws, "AbsDeltaBP")
    for row in range(2, ws.max_row + 1):
        ws[f"{absolute}{row}"] = f'=IF(ISNUMBER({delta}{row}),ABS({delta}{row}),"")'
        ws[f"{absolute}{row}"].number_format = "0.00"
    _refresh_table(ws)


def _live_status_styles(ws):
    headers = _headers(ws)
    for header, accepted in (
        ("LadderQC", ("ok", "manual_adjustment")),
        ("PeakQC", ("ok", "negative_control", "not_evaluated_ladder_only")),
        ("ReviewStatus", ("reviewed",)),
    ):
        if header not in headers or ws.max_row < 2:
            continue
        col = get_column_letter(headers[header])
        reference = f"${col}2"
        passed = "OR(" + ",".join(f'LOWER(TRIM({reference}))="{value}"' for value in accepted) + ")"
        formulas = [f'AND({reference}<>"",{passed})', f'AND({reference}<>"",NOT({passed}))']
        for group in ws.conditional_formatting:
            rules = ws.conditional_formatting[group]
            rules[:] = [rule for rule in rules if rule.formula not in [[formula] for formula in formulas]]
        for row in range(2, ws.max_row + 1):
            ws.cell(row, headers[header]).fill = PatternFill(fill_type=None)
        for formula, color in zip(formulas, ("E2F0D9", "FFF2CC")):
            ws.conditional_formatting.add(
                f"{col}2:{col}{ws.max_row}",
                FormulaRule(formula=[formula], fill=PatternFill("solid", fgColor="FF" + color, bgColor="FF" + color)),
            )
    for header in ("ReviewStatus", "TrackingNote"):
        if header in headers:
            ws.cell(1, headers[header]).fill = PatternFill("solid", fgColor="8A641B")


def _monthly_trends(dashboard, runs, *, start_row):
    headers = _headers(runs)
    dates = []
    for row in runs.iter_rows(min_row=2, max_col=headers["RunDate"], values_only=True):
        value = row[headers["RunDate"] - 1]
        try:
            dates.append(value if isinstance(value, date) else date.fromisoformat(str(value)[:10]))
        except (TypeError, ValueError):
            pass
    latest = max(dates) if dates else date.today()
    latest_month = latest.year * 12 + latest.month - 1
    dashboard.cell(start_row, 1, "Monthly trends").font = Font(size=13, bold=True)
    labels = ["Month", "Injections", "Patient", "Control", "QC review", "Accepted rate"]
    for col, label in enumerate(labels, 1):
        cell = dashboard.cell(start_row + 1, col, label)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="174A5B")
    for offset, month in enumerate(range(latest_month - 11, latest_month + 1), start_row + 2):
        year, zero_month = divmod(month, 12)
        dashboard.cell(offset, 1, datetime(year, zero_month + 1, 1)).number_format = "mmm yyyy"
        criterion = (("DashboardMonth", f'TEXT($A{offset},"yyyy-mm")'),)
        dashboard.cell(offset, 2, f'={_count(runs, *criterion)}')
        for col, name in ((3, "Patient"), (4, "Control"), (5, "Review")):
            dashboard.cell(offset, col, f'={_count(runs, *criterion, (f"Dashboard{name}", "1"))}')
        dashboard.cell(offset, 6, f'=IF(B{offset}=0,"",{_count(runs, *criterion, ("DashboardAccepted", "1"))}/B{offset})')
        dashboard.cell(offset, 6).number_format = "0.0%"
    chart = LineChart()
    chart.title = "Monthly volume and QC review"
    chart.y_axis.title = "Injections"
    chart.style = 13
    chart.height, chart.width = 8, 16
    chart.add_data(Reference(dashboard, min_col=2, max_col=5, min_row=start_row + 1, max_row=start_row + 13), titles_from_data=True)
    chart.set_categories(Reference(dashboard, min_col=1, min_row=start_row + 2, max_row=start_row + 13))
    chart.x_axis = DateAxis(axId=10, crossAx=100)
    chart.x_axis.number_format = "mmm yy"
    chart.x_axis.majorTimeUnit = "months"
    chart.legend.position = "b"
    for series, label, color in zip(chart.series, labels[1:5], ("174A5B", "4F81BD", "70AD8F", "C0504D")):
        series.tx = SeriesLabel(v=label)
        series.smooth = False
        series.graphicalProperties.line.solidFill = color
    dashboard.add_chart(chart, f"J{start_row}")


def _finish_dashboard_layout(dashboard, runs, *, flt3):
    assay_end = 16
    while dashboard.cell(assay_end + 1, 1).value and assay_end < 36:
        assay_end += 1
    content_end = max(assay_end, 19)
    header_rows = [9 if flt3 else 8, 16]
    if flt3:
        # Compact the control section below the actual assay list.
        control_end = 32
        while dashboard.cell(control_end + 1, 1).value and control_end < 45:
            control_end += 1
        target = max(23, assay_end + 3)
        dashboard.move_range(f"A31:I{control_end}", rows=target - 31, translate=True)
        header_rows.append(target + 1)
        content_end = max(content_end, control_end + target - 31)
    else:
        pk_end = 8
        while dashboard.cell(pk_end + 1, 10).value and pk_end < 20:
            pk_end += 1
        content_end = max(content_end, pk_end)
    chart_row = content_end + 3
    for index, chart in enumerate(dashboard._charts):
        chart.anchor = f'{"A" if index == 0 else "J"}{chart_row}'
    if not flt3 and len(dashboard._charts) < 2:
        dashboard.cell(chart_row, 10, "No measured PK marker deviations").font = Font(color="52666D", italic=True)
    monthly_row = chart_row + 17
    _monthly_trends(dashboard, runs, start_row=monthly_row)
    for chart in dashboard._charts:
        for axis in (chart.x_axis, chart.y_axis):
            axis.delete = False
            axis.tickLblPos = "nextTo"
            # Excel can otherwise inherit invisible tick-label text from the
            # local chart theme even though alternative renderers show labels.
            axis.txPr = RichText(p=[Paragraph(
                pPr=ParagraphProperties(defRPr=CharacterProperties(
                    latin=DrawingFont(typeface="Calibri"), sz=1000, solidFill="334155",
                )),
                endParaRPr=CharacterProperties(lang="en-US"),
            )])
    header_rows.append(monthly_row + 1)
    labels = {
        "RunDate": "Run date", "ReviewRequired": "QC review", "ManualAdjusted": "Manual adjusted",
        "PatientInjections": "Patients", "ControlInjections": "Controls", "PositiveCalls": "Positive calls",
        "MeanLadderR2": "Mean ladder R²", "PatientFiles": "Patients", "ControlFiles": "Controls",
        "ReviewFiles": "QC review", "AvgR2": "Mean R²", "PartialFits": "Partial fits",
        "ReviewRate": "QC review rate", "MarkerRows": "Markers", "MeanAbsDeltaBP": "Mean |delta| (bp)",
        "MaxAbsDeltaBP": "Max |delta| (bp)", "Over2bp": "Over 2 bp", "AvgHeight": "Mean height (RFU)",
        "MeanWTBP": "Mean WT (bp)", "MeanMutantBP": "Mean mutant (bp)", "MeanRatio": "Mean ratio",
    }
    for row in header_rows:
        dashboard.row_dimensions[row].height = 34
        for cell in dashboard[row]:
            if cell.value:
                cell.value = labels.get(cell.value, cell.value)
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    metric_row = 6 if flt3 else 5
    dashboard.row_dimensions[metric_row].height = 30
    dashboard.cell(metric_row, 8).font = Font(size=12, bold=True, color="174A5B")
    dashboard.column_dimensions["H"].width = 20
    dashboard.print_area = f"A1:Q{monthly_row + 18}"


def install_live_tracking_dashboard(workbook, *, analysis):
    """Replace generated dashboard snapshots with references to the live ledger."""
    flt3 = analysis == "flt3"
    runs, peaks, dashboard = (workbook[name] for name in ("Runs", "PK_Peaks", "Dashboard"))
    _install_run_helpers(runs, flt3=flt3)
    _install_peak_helpers(peaks)
    total = _count(runs, ("File", '"<>"'))
    summed = lambda name: f'SUM({_range(runs, "Dashboard" + name)})'
    latest = f'IF(COUNT({_range(runs, "DashboardDate")})=0,"",MAX({_range(runs, "DashboardDate")}))'
    metrics = (
        [total, summed("FirstRun"), summed("Patient"), summed("Control"), summed("Review"), summed("Manual"), summed("Positive"), latest]
        if flt3 else
        [total, summed("FirstAssay"), summed("Review"), summed("Manual"), f'IFERROR({summed("Accepted")}/{total},0)',
         _count(peaks, ("Kind", '"sample"'), ("Assay", '"<>SL"'), ("File", '"<>"')), summed("Partial"), latest]
    )
    metric_row = 6 if flt3 else 5
    for col, expression in enumerate(metrics, 1):
        dashboard.cell(metric_row, col, "=" + expression)
        dashboard.cell(metric_row, col).font = Font(size=18, bold=True, color="174A5B")
        dashboard.cell(metric_row - 1, col).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    dashboard.cell(metric_row, 8).number_format = "dd.mm.yyyy"
    dashboard.row_dimensions[metric_row - 1].height = 34
    dashboard.row_dimensions[metric_row].height = 30
    dashboard["J4" if not flt3 else "J5"] = "Awaiting review"
    dashboard["J5" if not flt3 else "J6"] = "=" + summed("OpenReview")
    dashboard["J5" if not flt3 else "J6"].font = Font(size=18, bold=True, color="A3472B")
    if not flt3:
        dashboard.merge_cells("A3:Q3")
    dashboard["A3"] = "Live formulas use Runs. Edit ReviewStatus / TrackingNote there. The app updates history after each run."
    dashboard["A3"].font = Font(size=10, color="52666D")
    dashboard["A3"].alignment = Alignment(horizontal="left")
    dashboard.sheet_properties.tabColor = "174A5B"
    dashboard.sheet_view.zoomScale = 80
    for name in ("Runs", "Patient_Runs", "Control_Runs", "PK_Peaks"):
        workbook[name].sheet_view.showGridLines = False
        _live_status_styles(workbook[name])
    # Assay summary: labels are rebuilt by the app; values remain live in Excel.
    for row in range(17, 37):
        if not dashboard.cell(row, 1).value:
            break
        criteria = (("DashboardAssay", f"$A{row}"),)
        expressions = [_count(runs, *criteria)]
        expressions += [_count(runs, *criteria, ("Dashboard" + name, "1")) for name in ("Patient", "Control", "Review", "Manual")]
        if flt3:
            expressions += [_count(runs, *criteria, ("DashboardPositive", "1")), _average(runs, "LadderR2", *criteria)]
        else:
            expressions += [_average(runs, "DashboardR2", *criteria), _count(runs, *criteria, ("DashboardPartial", "1")), f'IFERROR(E{row}/B{row},0)']
        for col, expression in enumerate(expressions, 2):
            dashboard.cell(row, col, "=" + expression)
    if flt3:
        for row in range(10, 20):
            if not dashboard.cell(row, 11).value:
                break
            criteria = (("DashboardRun", f"$K{row}"), ("RunDate", f"$J{row}"))
            for col, name in ((12, None), (13, "Patient"), (14, "Control"), (15, "Review"), (16, "Manual")):
                extra = (("Dashboard" + name, "1"),) if name else ()
                dashboard.cell(row, col, "=" + _count(runs, *criteria, *extra))
        for row in range(32, 46):
            if dashboard.cell(row, 1).value != "Control":
                continue
            for data_row in range(row + 1, 46):
                if not dashboard.cell(data_row, 1).value:
                    break
                criteria = (("Control", f"$A{data_row}"), ("DashboardAssay", f"$B{data_row}"))
                expressions = [_count(runs, *criteria)]
                expressions += [_count(runs, *criteria, ("Dashboard" + name, "1")) for name in ("Review", "Manual", "Positive")]
                expressions += [_average(runs, name, *criteria) for name in ("WT_BP", "MutantMain_BP", "Ratio")]
                for col, expression in enumerate(expressions, 3):
                    dashboard.cell(data_row, col, "=" + expression)
            break
    else:
        for row, scope in ((9, None), (10, "Patient"), (11, "Control")):
            criteria = (("Dashboard" + scope, "1"),) if scope else (("File", '"<>"'),)
            expressions = [_count(runs, *criteria)]
            expressions += [_count(runs, *criteria, ("Dashboard" + name, "1")) for name in ("Accepted", "Review", "Manual")]
            expressions += [f'IFERROR(C{row}/B{row},0)', _average(runs, "DashboardR2", *criteria), _count(runs, *criteria, ("DashboardPartial", "1"))]
            for col, expression in enumerate(expressions, 2):
                dashboard.cell(row, col, "=" + expression)
        for row in range(9, 21):
            if not dashboard.cell(row, 10).value:
                break
            criteria = (("Assay", f"$J{row}"), ("Kind", '"sample"'))
            abs_range = _range(peaks, "AbsDeltaBP")
            assay_range, kind_range = _range(peaks, "Assay"), _range(peaks, "Kind")
            measured = f'SUMPRODUCT(--({assay_range}=$J{row}),--({kind_range}="sample"),--ISNUMBER({abs_range}))'
            expressions = [
                _count(peaks, *criteria), _average(peaks, "AbsDeltaBP", *criteria),
                f'IF({measured}=0,"",_xlfn.MAXIFS({abs_range},{assay_range},$J{row},{kind_range},"sample"))',
                _count(peaks, *criteria, ("AbsDeltaBP", '">2"')), _average(peaks, "Height", *criteria),
            ]
            for col, expression in enumerate(expressions, 11):
                dashboard.cell(row, col, "=" + expression)
    dashboard.conditional_formatting.add(
        f'{"E" if flt3 else "C"}{metric_row}',
        CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor="FCE4D6")),
    )
    _finish_dashboard_layout(dashboard, runs, flt3=flt3)
    dashboard.print_options.horizontalCentered = True
    dashboard.sheet_properties.pageSetUpPr.fitToPage = True
    dashboard.page_setup.orientation = "landscape"
    dashboard.page_setup.paperSize = dashboard.PAPERSIZE_A3
    dashboard.page_setup.fitToWidth, dashboard.page_setup.fitToHeight = 1, 0
    workbook.calculation = CalcProperties(calcMode="auto", fullCalcOnLoad=True, forceFullCalc=True)
