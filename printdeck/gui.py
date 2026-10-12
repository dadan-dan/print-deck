"""图形界面（PySide6）。

队列内核跑在后台线程，通过 Qt 信号回传状态，界面不会卡死。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .channels.registry import SUPPORTED, collect
from .queue import CANCELLED, DONE, FAILED, PENDING, PrintQueue
from .settings import COLOR_MODES, DUPLEX_MODES, PAPER_SIZES, PrintSettings
from .util.printers import default_printer, get_printers

APP_NAME = "PrintDeck 批量打印"

DUPLEX_LABEL = {
    "simplex": "单面",
    "duplex": "双面（长边翻转）",
    "duplexlong": "双面（长边翻转）",
    "duplexshort": "双面（短边翻转）",
}
COLOR_LABEL = {"auto": "跟随文档", "color": "彩色", "mono": "黑白"}
PAPER_LABEL = {"auto": "跟随文档", "A4": "A4", "A5": "A5", "A3": "A3", "letter": "Letter", "legal": "Legal"}

STATUS_COLOR = {
    PENDING: "#6b7280",
    "转换中": "#2563eb",
    "打印中": "#2563eb",
    DONE: "#059669",
    FAILED: "#dc2626",
    CANCELLED: "#6b7280",
}


class _Bridge(QObject):
    """跨线程信号桥：队列内核在后台线程，界面只能在主线程更新。"""

    changed = Signal()


class SettingsDialog(QDialog):
    """单文件覆盖设置。"""

    def __init__(self, title: str, current: PrintSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.cleared = False

        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.copies.setValue(current.copies)

        self.duplex = QComboBox()
        self.duplex.addItems([DUPLEX_LABEL.get(m, m) for m in DUPLEX_MODES])
        self.duplex.setCurrentIndex(DUPLEX_MODES.index(current.duplex) if current.duplex in DUPLEX_MODES else 0)

        self.color = QComboBox()
        self.color.addItems([COLOR_LABEL.get(m, m) for m in COLOR_MODES])
        self.color.setCurrentIndex(COLOR_MODES.index(current.color) if current.color in COLOR_MODES else 0)

        self.paper = QComboBox()
        self.paper.addItems([PAPER_LABEL.get(m, m) for m in PAPER_SIZES])
        self.paper.setCurrentIndex(PAPER_SIZES.index(current.paper) if current.paper in PAPER_SIZES else 0)

        self.pages = QLineEdit(current.page_range)
        self.pages.setPlaceholderText("留空打印全部，例如 1-3,5,8-")

        form = QFormLayout()
        form.addRow("份数", self.copies)
        form.addRow("单双面", self.duplex)
        form.addRow("色彩", self.color)
        form.addRow("纸张", self.paper)
        form.addRow("页码范围", self.pages)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        clear = QPushButton("清除覆盖（跟随全局）")
        clear.clicked.connect(self._clear)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(clear)
        layout.addWidget(buttons)

    def _clear(self) -> None:
        """清除覆盖，让该文件跟随全局设置。"""
        self.cleared = True
        self.accept()

    def get_override(self) -> PrintSettings:
        return PrintSettings(
            copies=self.copies.value(),
            duplex=DUPLEX_MODES[self.duplex.currentIndex()],
            color=COLOR_MODES[self.color.currentIndex()],
            paper=PAPER_SIZES[self.paper.currentIndex()],
            page_range=self.pages.text().strip(),
        )


class MainWindow(QMainWindow):
    def __init__(self, initial_paths=None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 720)
        self.setAcceptDrops(True)

        self.queue = PrintQueue(PrintSettings(printer=default_printer()))
        self.bridge = _Bridge()
        self.queue.on_change = self.bridge.changed.emit
        self.bridge.changed.connect(self._refresh)

        self._row_by_id: dict[int, int] = {}
        self._build_ui()
        self._reload_printers()

        if initial_paths:
            self._add_paths(initial_paths)

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()

    # ---------- 界面搭建 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 打印机选择
        printer_row = QHBoxLayout()
        printer_row.addWidget(QLabel("打印机"))
        self.printer_combo = QComboBox()
        self.printer_combo.setMinimumWidth(320)
        self.printer_combo.currentIndexChanged.connect(self._on_printer_changed)
        printer_row.addWidget(self.printer_combo, 1)
        self.printer_info = QLabel("")
        self.printer_info.setStyleSheet("color:#6b7280")
        printer_row.addWidget(self.printer_info)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._reload_printers)
        printer_row.addWidget(refresh)
        root.addLayout(printer_row)

        splitter = QSplitter(Qt.Horizontal)

        # 左：全局设置
        settings_box = QGroupBox("全局设置（对所有文件生效）")
        form = QFormLayout(settings_box)
        self.g_copies = QSpinBox()
        self.g_copies.setRange(1, 999)
        self.g_copies.setValue(1)
        self.g_duplex = QComboBox()
        self.g_duplex.addItems([DUPLEX_LABEL.get(m, m) for m in DUPLEX_MODES])
        self.g_color = QComboBox()
        self.g_color.addItems([COLOR_LABEL.get(m, m) for m in COLOR_MODES])
        self.g_paper = QComboBox()
        self.g_paper.addItems([PAPER_LABEL.get(m, m) for m in PAPER_SIZES])
        self.g_pages = QLineEdit()
        self.g_pages.setPlaceholderText("留空打印全部，例如 1-3,5,8-")
        form.addRow("份数", self.g_copies)
        form.addRow("单双面", self.g_duplex)
        form.addRow("色彩", self.g_color)
        form.addRow("纸张", self.g_paper)
        form.addRow("页码范围", self.g_pages)

        tip = QLabel(
            "提示：双击列表中的某一行，可以单独为该文件设置参数。\n"
            "Office 文档会先转为 PDF 再打印，本机需安装 Office、WPS 或 LibreOffice 之一。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#6b7280")
        form.addRow(tip)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(settings_box)
        left_layout.addStretch(1)
        splitter.addWidget(left)

        # 右：队列
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["文件名", "状态", "页数", "耗时", "单独设置", "备注"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self._edit_selected)
        right_layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        for text, slot in (
            ("添加文件", self._pick_files),
            ("添加文件夹", self._pick_dir),
            ("移除选中", self._remove_selected),
            ("清空已完成", self._clear_finished),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        self.start_btn = QPushButton("开始打印")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        right_layout.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 860])
        root.addWidget(splitter, 1)

        # 底部状态
        status_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        status_row.addWidget(self.progress, 1)
        self.stats_label = QLabel("就绪")
        status_row.addWidget(self.stats_label)
        root.addLayout(status_row)

        self.setCentralWidget(central)

    # ---------- 打印机 ----------

    def _reload_printers(self) -> None:
        self.printers = get_printers()
        current = self.queue.global_settings.printer
        self.printer_combo.blockSignals(True)
        self.printer_combo.clear()
        for p in self.printers:
            mark = "* " if p.is_default else ""
            self.printer_combo.addItem(f"{mark}{p.name}（{p.state_text}）", p.name)
        self.printer_combo.blockSignals(False)

        if not self.printers:
            self.printer_info.setText("未检测到打印机")
            return
        idx = 0
        if current:
            found = self.printer_combo.findData(current)
            idx = found if found >= 0 else 0
        self.printer_combo.setCurrentIndex(idx)
        self._on_printer_changed()

    def _on_printer_changed(self) -> None:
        name = self.printer_combo.currentData()
        if not name:
            return
        self.queue.global_settings.printer = name
        info = next((p for p in self.printers if p.name == name), None)
        if info is None:
            return
        caps = []
        caps.append("支持双面" if info.duplex else "不支持双面")
        caps.append("支持彩色" if info.color else "仅黑白")
        if info.offline:
            caps.append("离线，打印可能堆积在队列")
        if info.interactive:
            caps.append("交互式虚拟打印机：每个文件都会弹一次保存对话框")
            self.printer_info.setStyleSheet("color:#dc2626")
        else:
            self.printer_info.setStyleSheet("color:#6b7280")
        self.printer_info.setText(" · ".join(caps))

    # ---------- 文件 ----------

    def _add_paths(self, paths) -> None:
        files = collect(paths)
        if not files:
            QMessageBox.information(self, "没有可用文件", f"受支持的格式：\n{', '.join(sorted(SUPPORTED))}")
            return
        self.queue.add(files)
        self._refresh()

    def _pick_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED))
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", f"可打印文件 ({exts});;所有文件 (*.*)")
        if files:
            self.queue.add([Path(f) for f in files])
            self._refresh()

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d:
            self._add_paths([d])

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if paths:
            self._add_paths(paths)

    # ---------- 操作 ----------

    def _selected_ids(self) -> list[int]:
        ids: list[int] = []
        for row in {idx.row() for idx in self.table.selectedIndexes()}:
            item = self.table.item(row, 0)
            if item is None:
                continue
            job_id = item.data(Qt.UserRole)
            if job_id is not None:
                ids.append(job_id)
        return ids

    def _remove_selected(self) -> None:
        ids = self._selected_ids()
        if ids:
            self.queue.remove(ids)
            self._refresh()

    def _clear_finished(self) -> None:
        self.queue.clear_finished()
        self._refresh()

    def _edit_selected(self, _index=None) -> None:
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        job = next((j for j in self.queue.jobs if j.id == ids[0]), None)
        if job is None:
            return
        base = job.override or PrintSettings()
        dlg = SettingsDialog(f"单独设置 —— {job.name}", base, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.queue.set_override(job.id, None if dlg.cleared else dlg.get_override())
        self._refresh()

    def _apply_global(self) -> None:
        self.queue.global_settings.copies = self.g_copies.value()
        self.queue.global_settings.duplex = DUPLEX_MODES[self.g_duplex.currentIndex()]
        self.queue.global_settings.color = COLOR_MODES[self.g_color.currentIndex()]
        self.queue.global_settings.paper = PAPER_SIZES[self.g_paper.currentIndex()]
        self.queue.global_settings.page_range = self.g_pages.text().strip()
        self.queue.global_settings.printer = self.printer_combo.currentData()

    def _start(self) -> None:
        self._apply_global()
        if not self.queue.global_settings.printer:
            QMessageBox.warning(self, "未选择打印机", "请先在顶部选择一台打印机。")
            return
        pending = [j.id for j in self.queue.jobs if j.status in (PENDING, FAILED)]
        if not pending:
            QMessageBox.information(self, "没有待打印任务", "队列为空或全部已完成。")
            return

        printer = self.queue.global_settings.printer
        info = next((p for p in getattr(self, "printers", []) if p.name == printer), None)
        if info is not None and info.interactive and len(pending) > 1:
            answer = QMessageBox.warning(
                self,
                "选择的是虚拟打印机",
                f"「{printer}」端口为 {info.port}，每打印一个文件都会弹出一次保存对话框。\n"
                f"本次有 {len(pending)} 个文件，界面会逐个等待，容易卡死。\n\n确定继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.queue.start(pending)
        self._refresh()

    def _stop(self) -> None:
        for job in self.queue.jobs:
            if job.status not in (DONE, FAILED, CANCELLED):
                self.queue.cancel(job.id)
        QMessageBox.information(
            self, "已请求停止", "已停止后续任务；已经送进打印机后台的页面无法撤回，可在打印机面板里取消。"
        )
        self._refresh()

    # ---------- 刷新 ----------

    def _refresh(self) -> None:
        jobs = self.queue.jobs
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self._set_row(row, job)

        stats = self.queue.stats()
        finished = stats.finished
        self.progress.setMaximum(max(1, stats.total))
        self.progress.setValue(finished)
        self.progress.setFormat(f"{finished} / {stats.total}")

        busy = self.queue.running
        self.start_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        self.stats_label.setText(
            f"完成 {stats.done} · 失败 {stats.failed} · 取消 {stats.cancelled} · 累计 {stats.pages} 页"
        )

    def _set_row(self, row: int, job) -> None:
        name_item = QTableWidgetItem(job.name)
        name_item.setData(Qt.UserRole, job.id)
        name_item.setToolTip(str(job.path))
        self.table.setItem(row, 0, name_item)

        status_item = QTableWidgetItem(job.status)
        color = STATUS_COLOR.get(job.status)
        if color:
            status_item.setForeground(QColor(color))
        self.table.setItem(row, 1, status_item)

        self.table.setItem(row, 2, QTableWidgetItem(str(job.pages) if job.pages else ""))
        self.table.setItem(row, 3, QTableWidgetItem(f"{job.elapsed:.1f}s" if job.started_at else ""))
        self.table.setItem(row, 4, QTableWidgetItem(job.override.describe() if job.override else ""))

        note = job.message
        if job.status == DONE and job.pages:
            note = (note + " " if note else "") + f"{job.pages} 页已送出"
        self.table.setItem(row, 5, QTableWidgetItem(note))


def run_gui(initial_paths=None) -> int:
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

    app = QApplication.instance() or QApplication(sys.argv)
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    app.setStyle("Fusion")

    win = MainWindow(initial_paths)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui(sys.argv[1:]))
