param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath,

    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),

    [string]$Destination = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'HemaFrag Diagnostics.lnk')
)

$resolvedPython = (Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop).Path
$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
$entryPoint = Join-Path $resolvedProject 'qt_app.py'
$iconPath = Join-Path $resolvedProject 'assets\app_icon.ico'

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "HemaFrag entry point not found: $entryPoint"
}
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "HemaFrag icon not found: $iconPath"
}

$destinationParent = Split-Path -Parent $Destination
if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
    throw "Shortcut destination folder does not exist: $destinationParent"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($Destination)
$shortcut.TargetPath = $resolvedPython
$shortcut.Arguments = ('"{0}"' -f $entryPoint)
$shortcut.WorkingDirectory = $resolvedProject
$shortcut.IconLocation = ('{0},0' -f $iconPath)
$shortcut.Description = 'Start HemaFrag Diagnostics with the configured Python environment'
$shortcut.Save()

Write-Host "Created HemaFrag shortcut: $Destination"
Write-Host "Python: $resolvedPython"
Write-Host "Icon: $iconPath"
