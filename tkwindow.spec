# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['src/tkwindow.py'],
    pathex=[],
    binaries=[
        ('.venv/lib/python3.14/site-packages/vosk/libvosk.so', 'vosk'),
    ],
    datas=[
        ('resources/bavardage.png', 'resources'),
    ],
    hiddenimports=[
        'vosk',
        'numpy',
        'loguru',
        'ttkbootstrap',
        'ttkbootstrap.style',
        'PIL',
        'PIL._tkinter_finder',
        'tkinter',
        'tkinter.font',
        'tkinter.messagebox',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'setuptools',
        'unittest',
        'xml.etree',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='bavardage',
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
)
