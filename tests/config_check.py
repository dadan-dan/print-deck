"""验证设置持久化与打印历史（测完恢复现场）。

    python tests/config_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from printdeck.config import (  # noqa: E402
    data_dir_text,
    history_path,
    load_history,
    load_settings,
    record,
    save_settings,
)
from printdeck.settings import PrintSettings  # noqa: E402

FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED.append(label)


def main() -> int:
    print(f"数据目录：{data_dir_text()}")

    orig_settings = load_settings()
    orig_history = load_history()

    try:
        # 设置往返
        s = PrintSettings(printer="TestPrinter", copies=3, duplex="duplex",
                          color="mono", paper="A4", page_range="1-3")
        save_settings(s)
        back = load_settings()
        check("设置写入并读回", back.printer == "TestPrinter", f"printer={back.printer}")
        check("份数保持", back.copies == 3, f"copies={back.copies}")
        check("双面模式保持", back.duplex == "duplex", f"duplex={back.duplex}")
        check("色彩模式保持", back.color == "mono", f"color={back.color}")
        check("纸张保持", back.paper == "A4", f"paper={back.paper}")
        check("页码范围保持", back.page_range == "1-3", f"pages={back.page_range}")

        # 非法值应被忽略
        save_settings(PrintSettings(duplex="乱填", color="乱填", paper="乱填"))
        bad = load_settings()
        check("非法枚举值被忽略", bad.duplex == "simplex" and bad.color == "auto" and bad.paper == "auto",
              f"{bad.duplex}/{bad.color}/{bad.paper}")

        # 历史
        record("测试文件.pdf", Path("C:/tmp/测试文件.pdf"), "TestPrinter", 7, "已完成", "")
        record("失败文件.docx", Path("C:/tmp/失败文件.docx"), "TestPrinter", 0, "失败", "缺少 Office")
        hist = load_history()
        check("历史新增记录", len(hist) >= 2, f"共 {len(hist)} 条")
        check("历史最新一条在最前", hist[0]["name"] == "失败文件.docx", hist[0]["name"])
        check("历史记录了页数", hist[1]["pages"] == 7, str(hist[1]["pages"]))
        check("历史记录了失败原因", hist[0]["message"] == "缺少 Office", hist[0]["message"])
        check("历史带时间戳", bool(hist[0].get("time")), str(hist[0].get("time")))
    finally:
        save_settings(orig_settings)
        history_path().write_text(json.dumps(orig_history, ensure_ascii=False, indent=2), encoding="utf-8")

    print("-" * 60)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：{', '.join(FAILED)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
