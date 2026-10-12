"""图标定位：兼容源码运行与 PyInstaller 单文件两种形态。

打包后资源被解压到 sys._MEIPASS 指向的临时目录，源码运行时在仓库 assets/ 下。
"""

from __future__ import annotations

import sys
from pathlib import Path


def icon_path() -> Path | None:
    candidates: list[Path] = []

    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(Path(base) / "printdeck.ico")

    # util/icon.py -> util -> printdeck -> 项目根
    candidates.append(Path(__file__).resolve().parents[2] / "assets" / "printdeck.ico")

    for c in candidates:
        if c.is_file():
            return c
    return None
