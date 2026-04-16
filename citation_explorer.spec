# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Citation Explorer — produces a single self-contained .exe.
Build with:  pyinstaller citation_explorer.spec --clean
Output:      dist/CitationExplorer.exe
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# OCR is handled by Windows Runtime OCR (winsdk) — no Tesseract binaries needed.

# Collect scholarly + its data files (fake_useragent UA database, etc.)
scholarly_datas,   scholarly_bins,   scholarly_hidden   = collect_all('scholarly')
fua_datas,         fua_bins,         fua_hidden         = collect_all('fake_useragent')
bs4_datas,         bs4_bins,         bs4_hidden         = collect_all('bs4')
certifi_datas,     _,                _                  = collect_all('certifi')

all_datas    = scholarly_datas + fua_datas + bs4_datas + certifi_datas
all_binaries = scholarly_bins  + fua_bins  + bs4_bins
all_hidden   = (
    scholarly_hidden + fua_hidden + bs4_hidden
    + collect_submodules('PyQt6')
    + [
        'fetcher',
        'ocr_parser',
        'winsdk',
        'winsdk.windows.media.ocr',
        'winsdk.windows.graphics.imaging',
        'winsdk.windows.storage.streams',
        'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
        'httpx', 'httpcore', 'anyio', 'sniffio',
        'bs4', 'lxml', 'lxml.etree', 'lxml._elementpath',
        'bibtexparser',
        'selenium',
        'arrow',
        'free_proxy',
        'fake_useragent',
    ]
)

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'scipy', 'PIL', 'cv2',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,       # ← onefile: bundle everything into the .exe
    a.datas,
    [],
    name='CitationExplorer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,         # compress with UPX if available (reduces size ~30%)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,    # no black console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,        # set to 'app.ico' if you add an icon file
)
