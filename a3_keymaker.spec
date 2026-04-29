# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\a3_keymaker\\cli.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/a3_keymaker/data', 'a3_keymaker/data'), ('src/a3_keymaker/scripts', 'a3_keymaker/scripts')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='a3_keymaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
