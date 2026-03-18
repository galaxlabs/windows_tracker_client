# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_dir = Path.cwd()

hiddenimports = [
    "PIL._tkinter_finder",
    "win32timezone",
]

a = Analysis(
    ["agent.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        ("config.example.json", "."),
    ],
    hiddenimports=hiddenimports,
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
    name="cclms-tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
