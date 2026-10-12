# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件 Windows 可执行程序。"""

import os

# SPECPATH 由 PyInstaller 注入，指向 spec 文件所在目录（build/），项目根在其上级
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "printdeck.ico")

# 用不到的 Qt 大模块，排除后可显著缩小体积
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtSql",
    "PySide6.QtNetworkAuth",
    "PySide6.QtRemoteObjects",
    "PySide6.QtWebSockets",
    "PySide6.QtHttpServer",
    "PySide6.QtStateMachine",
    "PySide6.QtUiTools",
    "PySide6.QtXml",
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "pytest",
]

HIDDEN = [
    "pymupdf",
    "PIL.ImageWin",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32con",
    "win32print",
    "win32ui",
]

a = Analysis(
    [os.path.join(ROOT, "printdeck_launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(ICON, ".")],  # 图标随包带走，供窗口标题栏与资源管理器显示
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(
    icon=ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 图形界面版：双击打开，无控制台窗口
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PrintDeck",
    console=False,
    disable_windowed_traceback=False,
    **common,
)

# 命令行版：保留控制台，供脚本/批处理调用
cli = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PrintDeckCLI",
    console=True,
    disable_windowed_traceback=False,
    **common,
)
