"""逐步探测 GDI 打印管线，定位卡点。每步立即 flush 输出。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore


def step(msg: str) -> None:
    sys.stdout.write(f"  -> {msg}\n")
    sys.stdout.flush()


def main() -> int:
    from printdeck.util.printers import default_printer

    printer = default_printer()
    step(f"默认打印机 = {printer}")

    import win32ui

    step("已导入 win32ui")

    hdc = win32ui.CreateDC()
    step("CreateDC 完成")

    hdc.CreatePrinterDC(printer)
    step("CreatePrinterDC 完成")

    caps = (hdc.GetDeviceCaps(8), hdc.GetDeviceCaps(10))
    step(f"可打印区 = {caps}")

    pdf = ROOT / "samples" / "sample.pdf"
    doc = fitz.open(str(pdf))
    step(f"打开 PDF，{doc.page_count} 页")

    hdc.StartDoc("probe")
    step("StartDoc 完成")

    from PIL import Image, ImageWin

    page = doc[0]
    pix = page.get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    step(f"渲染第 1 页 = {img.size}")

    hdc.StartPage()
    step("StartPage 完成")

    ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (0, 0, min(caps[0], img.width), min(caps[1], img.height)))
    step("Dib.draw 完成")

    hdc.EndPage()
    step("EndPage 完成")

    doc.close()
    step("PDF 关闭")

    hdc.AbortDoc()
    step("AbortDoc 完成")

    hdc.DeleteDC()
    step("DeleteDC 完成 —— 管线无阻塞")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
