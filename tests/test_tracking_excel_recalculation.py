"""Recalculate in desktop Excel when installed; other environments skip this check."""
import json
import shutil
import subprocess

import pytest
from openpyxl import load_workbook


EXCEL_CHECK = r'''
param([string]$WorkbookPath, [string]$Analysis)
$ErrorActionPreference = 'Stop'
if ($null -eq [type]::GetTypeFromProgID('Excel.Application')) {
    Write-Output '{"skip":"Desktop Excel is not installed"}'
    exit 0
}
$excel = $null
$book = $null
function Assert-Number($Actual, $Expected, $Label) {
    if ([math]::Abs([double]$Actual - [double]$Expected) -gt 0.0000001) {
        throw "$Label expected $Expected, got $Actual"
    }
}
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Open($WorkbookPath, 0, $false)
    $excel.CalculateFullRebuild()
    $runs = $book.Worksheets.Item('Runs')
    $dash = $book.Worksheets.Item('Dashboard')
    $runs.Activate()
    $headers = @{}
    for ($col = 1; $col -le $runs.UsedRange.Columns.Count; $col++) {
        $headers[[string]$runs.Cells.Item(1, $col).Value2] = $col
    }
    $metricRow = if ($Analysis -eq 'flt3') { 6 } else { 5 }
    $reviewCol = if ($Analysis -eq 'flt3') { 5 } else { 3 }
    $monthlyRow = 0
    for ($row = 1; $row -le $dash.UsedRange.Rows.Count; $row++) {
        if ($dash.Cells.Item($row, 1).Text -eq 'Monthly trends') { $monthlyRow = $row + 13; break }
    }
    if ($monthlyRow -eq 0) { throw 'Monthly trend table is missing' }
    if ($dash.Cells.Item($metricRow, 8).Text -match '#') { throw 'Latest date does not fit in its cell' }
    foreach ($chartObject in $dash.ChartObjects()) {
        Assert-Number $chartObject.Chart.Axes(1).TickLabels.Font.Size 10 'readable chart labels'
    }
    Assert-Number $dash.Cells.Item($metricRow, 1).Value2 2 'injections'
    Assert-Number $dash.Cells.Item($metricRow, $reviewCol).Value2 1 'QC review'
    Assert-Number $dash.Cells.Item($metricRow, 10).Value2 1 'awaiting review'
    Assert-Number $dash.Range('B17').Value2 2 'assay injections'
    Assert-Number $dash.Range('E17').Value2 1 'assay QC review'
    Assert-Number $dash.Cells.Item($monthlyRow, 2).Value2 2 'monthly injections'
    $warningColor = $runs.Cells.Item(3, $headers['LadderQC']).DisplayFormat.Interior.Color
    $runs.Cells.Item(3, $headers['ReviewStatus']).Value2 = 'Reviewed'
    $excel.CalculateFullRebuild()
    Assert-Number $dash.Cells.Item($metricRow, 10).Value2 0 'review completion'
    Assert-Number $dash.Cells.Item($metricRow, $reviewCol).Value2 1 'QC issue remains recorded'
    $runs.Cells.Item(3, $headers['LadderQC']).Value2 = 'ok'
    $excel.CalculateFullRebuild()
    Assert-Number $dash.Cells.Item($metricRow, $reviewCol).Value2 0 'live QC edit'
    Assert-Number $dash.Range('E17').Value2 0 'live assay QC edit'
    if ($warningColor -eq $runs.Cells.Item(3, $headers['LadderQC']).DisplayFormat.Interior.Color) {
        throw 'QC cell color did not react to the status edit'
    }
    if ($Analysis -eq 'clonality') {
        Assert-Number $dash.Range('E5').Value2 1 'accepted fit rate'
        Assert-Number $dash.Range('L9').Value2 1.5 'mean absolute marker delta'
        Assert-Number $dash.Range('M9').Value2 1.5 'maximum absolute marker delta'
        $pk = $book.Worksheets.Item('PK_Peaks')
        $deltaCol = 0
        for ($col = 1; $col -le $pk.UsedRange.Columns.Count; $col++) {
            if ($pk.Cells.Item(1, $col).Value2 -eq 'DeltaBP') { $deltaCol = $col }
        }
        $pk.Cells.Item(2, $deltaCol).Value2 = -3.25
        $excel.CalculateFullRebuild()
        Assert-Number $dash.Range('L9').Value2 3.25 'live marker mean'
        Assert-Number $dash.Range('M9').Value2 3.25 'live marker maximum'
        Assert-Number $dash.Range('N9').Value2 1 'live marker over 2 bp'
        $pk.Cells.Item(2, $deltaCol).Value2 = ''
        $excel.CalculateFullRebuild()
        if ([string]$dash.Range('L9').Value2 -ne '' -or [string]$dash.Range('M9').Value2 -ne '') {
            throw 'Missing marker deviation must remain blank'
        }
        $pk.Cells.Item(2, $deltaCol).Value2 = 0
        $excel.CalculateFullRebuild()
        Assert-Number $dash.Range('L9').Value2 0 'measured zero deviation'
        Assert-Number $dash.Range('M9').Value2 0 'measured maximum zero deviation'
    }
    $runs.Cells.Item(3, $headers['RunDate']).Value2 = '2026-04-26'
    $excel.CalculateFullRebuild()
    Assert-Number $dash.Cells.Item($monthlyRow, 2).Value2 1 'latest month after date edit'
    Assert-Number $dash.Cells.Item(($monthlyRow - 1), 2).Value2 1 'prior month after date edit'
    # Restore source inputs before leaving a reusable artifact.
    $runs.Cells.Item(3, $headers['RunDate']).Value2 = '2026-05-26'
    $runs.Cells.Item(3, $headers['LadderQC']).Value2 = 'warning'
    $runs.Cells.Item(3, $headers['ReviewStatus']).Value2 = ''
    if ($Analysis -eq 'clonality') { $pk.Cells.Item(2, $deltaCol).Value2 = -1.5 }
    $excel.CalculateFullRebuild()
    $book.Save()
    Write-Output '{"verified":true}'
} finally {
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $excel) { $excel.Quit() }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
'''


@pytest.mark.parametrize("analysis", ["flt3", "clonality"])
def test_native_excel_recalculates_after_edits(tmp_path, analysis):
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("Desktop Excel COM check requires Windows PowerShell")
    if analysis == "flt3":
        from test_flt3_tracking_output import _entry
        from core.analyses.flt3.qc_tracker import update_flt3_npm1_qc_tracker_workbook as update
        first = _entry("26OUM00001_ITD__260526_A01_H9TEST01.fsa")
        second = _entry("26OUM00002_ITD__260526_A02_H9TEST01.fsa", specimen_id="26OUM00002")
        second.update(dit="26OUM00002", well_id="A02")
    else:
        from test_clonality_tracking_output import _entry
        from core.analyses.clonality.tracking_excel import update_clonality_tracking_workbook as update
        first = _entry("PK_FR1__260526_A01_H9TEST01.fsa")
        second = _entry("26OUM00002_FR1__260526_A02_H9TEST01.fsa", dit="26OUM00002")
    for entry in (first, second):
        entry.update(source_run_dir="synthetic_run", run_date="2026-05-26")
    second["ladder_qc_status"] = "warning"
    path = tmp_path / "native.xlsx"
    update(path, [first, second])
    if analysis == "clonality":
        book = load_workbook(path)
        pk = book["PK_Peaks"]
        headers = {c.value: c.column for c in pk[1]}
        # A synthetic marker with a known deviation, independent of peak detection.
        for name, value in {"File": first["file_name"], "Assay": "FR1", "Kind": "sample", "DeltaBP": -1.5,
                            "IdentityKey": "synthetic-marker", "MarkerName": "known-peak"}.items():
            pk.cell(2, headers[name], value)
        book.save(path)
        book.close()
        from core.analyses.clonality.tracking_dashboard import refresh_clonality_tracking_dashboard
        refresh_clonality_tracking_dashboard(path)
    script = tmp_path / "verify.ps1"
    script.write_text(EXCEL_CHECK, encoding="utf-8-sig")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), str(path), analysis],
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = json.loads(result.stdout.strip())
    if "skip" in outcome:
        pytest.skip(outcome["skip"])
    assert outcome["verified"]
    book = load_workbook(path, data_only=True)
    assert not [(ws.title, c.coordinate, c.value) for ws in book for row in ws for c in row if c.data_type == "e"]
    book.close()
