# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['qt_app.py'],
    pathex=[],
    binaries=[('/Users/christian/Desktop/HemaFrag/fraggler-v2/target/release/fraggler-cli', '.')],
    datas=[('assets', 'assets'), ('app.py', '.')],
    hiddenimports=['PyQt6', 'pandas', 'plotly', 'core.analyses.general.config', 'core.analyses.general.classification', 'core.analyses.general.pipeline', 'core.analyses.clonality.config', 'core.analyses.clonality.classification', 'core.analyses.clonality.pipeline', 'core.analyses.flt3.config', 'core.analyses.flt3.classification', 'core.analyses.flt3.pipeline'],
    hookspath=['/Users/christian/Desktop/HemaFrag/packaging/hooks'],
    hooksconfig={},
    runtime_hooks=['/Users/christian/Desktop/HemaFrag/packaging/hooks/runtime_desktop.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HemaFrag',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app_icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HemaFrag',
)
app = BUNDLE(
    coll,
    name='HemaFrag.app',
    icon='assets/app_icon.icns',
    bundle_identifier='no.ous.hemafrag',
)
