"""设置持久化与打印历史。

数据放在 %APPDATA%\\PrintDeck\\ 下，与程序本体分离，
这样 exe 拷到别的机器上不会带走别人的设置，卸载也不会残留历史在程序目录。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from .settings import COLOR_MODES, DUPLEX_MODES, PAPER_SIZES, PrintSettings

APP_NAME = "PrintDeck"
HISTORY_LIMIT = 500

_lock = threading.Lock()


def app_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_dir() / "settings.json"


def history_path() -> Path:
    return app_dir() / "history.json"


# ---------------- 设置 ----------------

def load_settings() -> PrintSettings:
    """读取上次保存的设置；没有或损坏时返回默认值。"""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except Exception:
        return PrintSettings()

    s = PrintSettings()
    if isinstance(data.get("printer"), str):
        s.printer = data["printer"] or None
    if isinstance(data.get("copies"), int) and data["copies"] >= 1:
        s.copies = data["copies"]
    for field_name, allowed in (
        ("duplex", DUPLEX_MODES),
        ("color", COLOR_MODES),
        ("paper", PAPER_SIZES),
    ):
        value = data.get(field_name)
        if value in allowed:
            setattr(s, field_name, value)
    if isinstance(data.get("page_range"), str):
        s.page_range = data["page_range"]
    if isinstance(data.get("collate"), bool):
        s.collate = data["collate"]
    return s


def save_settings(settings: PrintSettings) -> None:
    try:
        settings_path().write_text(
            json.dumps(
                {
                    "printer": settings.printer or "",
                    "copies": settings.copies,
                    "duplex": settings.duplex,
                    "color": settings.color,
                    "paper": settings.paper,
                    "page_range": settings.page_range,
                    "collate": settings.collate,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass  # 设置存不下不影响打印


# ---------------- 历史 ----------------

def load_history() -> list[dict]:
    try:
        data = json.loads(history_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def record(job_name: str, job_path: Path, printer: str, pages: int,
           status: str, message: str = "") -> None:
    """追加一条打印记录。只保留最近 HISTORY_LIMIT 条。"""
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": job_name,
        "path": str(job_path),
        "printer": printer,
        "pages": pages,
        "status": status,
        "message": message,
    }
    with _lock:
        try:
            data = load_history()
            data.insert(0, entry)
            data = data[:HISTORY_LIMIT]
            history_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


def clear_history() -> None:
    try:
        history_path().write_text("[]", encoding="utf-8")
    except Exception:
        pass


def data_dir_text() -> str:
    return str(app_dir())
