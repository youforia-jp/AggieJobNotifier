# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys, os, glob

datas = [('icon.ico', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Explicitly bundle python3XX.dll and vcruntime DLLs so the exe works
# on any machine without Python installed (fixes 'Failed to load Python DLL').
_python_dir = os.path.dirname(sys.executable)
for _dll in glob.glob(os.path.join(_python_dir, 'python3*.dll')):
    binaries.append((_dll, '.'))
for _dll in glob.glob(os.path.join(_python_dir, 'vcruntime*.dll')):
    binaries.append((_dll, '.'))


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
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
    name='AggieJobNotifier',
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
    icon='icon.ico',
)
