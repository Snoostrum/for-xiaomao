# -*- mode: python ; coding: utf-8 -*-
"""小灶 Windows 单文件打包配置。

用法(仓库根目录):
    pip install pyinstaller
    pyinstaller xiaozhao.spec --noconfirm
产物:dist/小灶.exe —— 双击即用;数据目录认 exe 旁边的 data/(整个文件夹挪走,Key 跟着走)。
"""

from pathlib import Path

root = Path(SPECPATH)  # PyInstaller 运行时注入:spec 文件所在目录(即仓库根)

a = Analysis(
    [str(root / "app" / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "app" / "web"), "app/web")],  # 网页资源必须打进包里(自检会守着这一点)
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
    name="小灶",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 不用 upx:杀毒软件对压缩壳更敏感
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 黑窗口就是聊天界面
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
