"""打印队列：状态机 + 后台执行，失败隔离不中断整批。

不依赖 Qt，命令行与图形界面共用同一套内核。
"""

from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .channels.base import ConvertError, UnsupportedFormat
from .channels.registry import normalize
from .engine import PrintError, pdf_page_count, print_pdf
from .settings import PrintSettings

PENDING = "待打印"
CONVERTING = "转换中"
PRINTING = "打印中"
DONE = "已完成"
FAILED = "失败"
CANCELLED = "已取消"

FINISHED = (DONE, FAILED, CANCELLED)


@dataclass
class Job:
    id: int
    path: Path
    status: str = PENDING
    override: PrintSettings | None = None
    pages: int = 0
    message: str = ""
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    @property
    def active(self) -> bool:
        return self.status in (CONVERTING, PRINTING)


@dataclass
class QueueStats:
    total: int = 0
    done: int = 0
    failed: int = 0
    cancelled: int = 0
    pages: int = 0

    @property
    def finished(self) -> int:
        return self.done + self.failed + self.cancelled


class PrintQueue:
    def __init__(self, global_settings: PrintSettings | None = None):
        self.global_settings = global_settings or PrintSettings()
        self.jobs: list[Job] = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._cancel: set[int] = set()
        self._running = False
        self._thread: threading.Thread | None = None
        self.on_change = None  # 可选回调，GUI 用来刷新界面
        self.prefer_sumatra = False

    # ---------- 队列管理 ----------

    def add(self, paths) -> list[Job]:
        created: list[Job] = []
        existing = {j.path for j in self.jobs}
        for p in paths:
            path = Path(p).resolve()
            if path in existing:
                continue
            job = Job(id=self._next_id, path=path)
            self._next_id += 1
            self.jobs.append(job)
            existing.add(path)
            created.append(job)
        self._notify()
        return created

    def remove(self, job_ids) -> None:
        ids = set(job_ids)
        self.jobs = [j for j in self.jobs if j.id not in ids and not j.active]
        self._notify()

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if j.status not in FINISHED]
        self._notify()

    def set_override(self, job_id: int, override: PrintSettings | None) -> None:
        for j in self.jobs:
            if j.id == job_id:
                j.override = override
                break
        self._notify()

    def effective_settings(self, job: Job) -> PrintSettings:
        merged = self.global_settings.merged(job.override)
        if not merged.printer:
            from .util.printers import default_printer

            merged.printer = default_printer()
        return merged

    def stats(self) -> QueueStats:
        s = QueueStats(total=len(self.jobs))
        for j in self.jobs:
            if j.status == DONE:
                s.done += 1
                s.pages += j.pages
            elif j.status == FAILED:
                s.failed += 1
            elif j.status == CANCELLED:
                s.cancelled += 1
        return s

    def cancel(self, job_id: int) -> None:
        self._cancel.add(job_id)
        for j in self.jobs:
            if j.id == job_id and j.status == PENDING:
                j.status = CANCELLED
                j.finished_at = time.time()
        self._notify()

    @property
    def running(self) -> bool:
        return self._running

    # ---------- 执行 ----------

    def start(self, job_ids=None) -> None:
        if self._running:
            return
        targets = [j for j in self.jobs if j.status in (PENDING, FAILED)]
        if job_ids is not None:
            wanted = set(job_ids)
            targets = [j for j in targets if j.id in wanted]
            for j in targets:
                if j.status == FAILED:
                    j.status = PENDING
                    j.message = ""
        if not targets:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, args=(targets,), daemon=True)
        self._thread.start()

    def _run(self, targets: list[Job]) -> None:
        try:
            for job in targets:
                if job.id in self._cancel:
                    job.status = CANCELLED
                    job.finished_at = time.time()
                    self._notify()
                    continue
                self._run_one(job)
        finally:
            self._running = False
            self._notify()

    def _run_one(self, job: Job) -> None:
        settings = self.effective_settings(job)
        printer = settings.printer or ""

        job.status = CONVERTING
        job.started_at = time.time()
        job.finished_at = None
        job.message = ""
        self._notify()

        try:
            with tempfile.TemporaryDirectory(prefix="printdeck_") as workdir:
                converted = normalize(job.path, Path(workdir))
                if converted.note:
                    job.message = converted.note

                job.status = PRINTING
                self._notify()

                copies = max(1, int(settings.copies or 1))
                total_pages = 0
                for _ in range(copies):
                    if job.id in self._cancel:
                        raise InterruptedError("已取消")
                    outcome = print_pdf(
                        converted.pdf_path, settings, printer, prefer_sumatra=self.prefer_sumatra
                    )
                    total_pages += outcome.pages_printed

                job.pages = total_pages
                job.status = DONE
        except InterruptedError:
            job.status = CANCELLED
            job.message = "已取消"
        except UnsupportedFormat as exc:
            job.status = FAILED
            job.message = str(exc)
        except ConvertError as exc:
            job.status = FAILED
            job.message = str(exc)
        except PrintError as exc:
            job.status = FAILED
            job.message = f"打印失败：{exc}"
        except Exception as exc:  # noqa: BLE001 - 保证单文件失败不影响整批
            job.status = FAILED
            job.message = f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = time.time()
            self._record(job, printer)
            self._notify()

    def _record(self, job: Job, printer: str) -> None:
        """落一条历史；记录失败绝不能影响打印流程。"""
        try:
            from .config import record

            record(job.name, job.path, printer, job.pages, job.status, job.message)
        except Exception:
            pass

    def _notify(self) -> None:
        cb = self.on_change
        if cb is not None:
            try:
                cb()
            except Exception:
                pass


def preview_pages(path: Path) -> int:
    """读取页数用于界面展示；失败返回 0。"""
    try:
        return pdf_page_count(path)
    except Exception:
        return 0
