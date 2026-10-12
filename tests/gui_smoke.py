"""GUI 冒烟测试：构建主窗口并加入样本文件，3 秒后自动退出。

    python tests/gui_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from printdeck.gui import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()

    samples = ROOT / "samples"
    if samples.is_dir():
        win.queue.add(sorted(samples.glob("sample.pdf")) + sorted(samples.glob("sample.png")))
        print(f"已载入 {len(win.queue.jobs)} 个样本文件")
    print(f"已检测到 {len(win.printers)} 台打印机，队列行数 {win.table.rowCount()}")

    QTimer.singleShot(3000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
