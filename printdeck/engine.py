"""PDF 打印引擎。

两条路径：
  1. SumatraPDF 外部进程（可选增强）：支持纸盒选择、驱动级双面等高级能力；
  2. 自研 GDI 路径（默认）：PyMuPDF 光栅化 + Win32 GDI 直出，零外部依赖，
     保证分发到没装任何 PDF 软件的机器上也能工作。

copies 由上层循环调用处理，引擎每次只输出一份，避免驱动行为差异。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:  # PyMuPDF 新版推荐用 pymupdf 入口
    import pymupdf as fitz
except ImportError:  # pragma: no cover - 旧版本兼容
    import fitz  # type: ignore[no-redef]

from PIL import Image, ImageWin

from .settings import PrintSettings

# DEVMODE 字段掩码
DM_ORIENTATION = 0x00000001
DM_PAPERSIZE = 0x00000002
DM_COLOR = 0x00000800
DM_DUPLEX = 0x00001000

DMORIENT_PORTRAIT = 1
DMORIENT_LANDSCAPE = 2
DMCOLOR_MONOCHROME = 1
DMCOLOR_COLOR = 2
DMDUP_SIMPLEX = 1
DMDUP_VERTICAL = 2
DMDUP_HORIZONTAL = 3

PAPER_IDS = {"A3": 8, "A4": 9, "A5": 11, "letter": 1, "legal": 5}

# GDI 设备能力
HORZRES = 8
VERTRES = 10
LOGPIXELSX = 88
LOGPIXELSY = 90
PHYSICALWIDTH = 110
PHYSICALHEIGHT = 111
PHYSICALOFFSETX = 112
PHYSICALOFFSETY = 113

MIN_DPI, MAX_DPI = 96, 600


class PrintError(Exception):
    """打印失败。"""


@dataclass
class PrintOutcome:
    ok: bool
    pages_printed: int = 0
    message: str = ""
    method: str = ""


def resolve_pages(page_range: str, total: int) -> list[int]:
    """把 "1-3,5,8-" 这样的页码表达式解析成 0 基页号列表。"""
    if not page_range or not page_range.strip():
        return list(range(total))

    pages: list[int] = []
    for chunk in page_range.replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            start_s, _, end_s = chunk.partition("-")
            start = 1 if start_s == "" else int(start_s)
            end = total if end_s == "" else int(end_s)
            if start > end:
                start, end = end, start
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(chunk))

    result = sorted({p - 1 for p in pages if 1 <= p <= total})
    if not result:
        raise PrintError(f"页码范围 {page_range!r} 与文档（共 {total} 页）无交集")
    return result


_TOTAL_PAGES_CACHE: dict[str, int] = {}


def pdf_page_count(path: str | Path) -> int:
    key = str(path)
    if key in _TOTAL_PAGES_CACHE:
        return _TOTAL_PAGES_CACHE[key]
    with fitz.open(str(path)) as doc:
        count = doc.page_count
    _TOTAL_PAGES_CACHE[key] = count
    return count


def render_page(page: "fitz.Page", dpi: float) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _apply_devmode(printer: str, settings: PrintSettings) -> bool:
    """把双面/彩色/纸张/方向写进打印机 DEVMODE。返回是否成功。"""
    try:
        import win32con  # noqa: F401
        import win32print

        handle = win32print.OpenPrinter(printer)
    except Exception:
        return False

    try:
        props = win32print.GetPrinter(handle, 2)
        devmode = props.get("pDevMode")
        if devmode is None:
            return False

        if settings.duplex in ("duplex", "duplexlong"):
            devmode.Duplex = DMDUP_VERTICAL
            devmode.Fields |= DM_DUPLEX
        elif settings.duplex == "duplexshort":
            devmode.Duplex = DMDUP_HORIZONTAL
            devmode.Fields |= DM_DUPLEX

        if settings.color == "color":
            devmode.Color = DMCOLOR_COLOR
            devmode.Fields |= DM_COLOR
        elif settings.color == "mono":
            devmode.Color = DMCOLOR_MONOCHROME
            devmode.Fields |= DM_COLOR

        if settings.paper in PAPER_IDS:
            devmode.PaperSize = PAPER_IDS[settings.paper]
            devmode.Fields |= DM_PAPERSIZE

        if settings.orientation == "portrait":
            devmode.Orientation = DMORIENT_PORTRAIT
            devmode.Fields |= DM_ORIENTATION
        elif settings.orientation == "landscape":
            devmode.Orientation = DMORIENT_LANDSCAPE
            devmode.Fields |= DM_ORIENTATION

        win32print.SetPrinter(handle, 2, {"pDevMode": devmode}, 0)
        return True
    except Exception:
        return False
    finally:
        try:
            import win32print

            win32print.ClosePrinter(handle)
        except Exception:
            pass


def _target_rect(page_w_pt: float, page_h_pt: float, dev_w: int, dev_h: int, scale: str):
    """按缩放策略算出页面在可打印区中的像素矩形（居中）。"""
    if scale == "noscale":
        zoom = 72.0 / 72.0
        w = int(page_w_pt)
        h = int(page_h_pt)
    elif scale == "stretch":
        zx, zy = dev_w / page_w_pt, dev_h / page_h_pt
        w, h = dev_w, dev_h
        return (0, 0, w, h), (zx * 72.0, zy * 72.0)
    else:
        zoom = min(dev_w / page_w_pt, dev_h / page_h_pt)
        if scale == "shrink":
            zoom = min(zoom, 1.0)
        w = int(page_w_pt * zoom)
        h = int(page_h_pt * zoom)

    x0 = max(0, (dev_w - w) // 2)
    y0 = max(0, (dev_h - h) // 2)
    return (x0, y0, x0 + w, y0 + h), (zoom * 72.0, zoom * 72.0)


def print_pdf_gdi(path: str | Path, settings: PrintSettings, printer: str) -> PrintOutcome:
    """自研路径：光栅化后经 GDI 直送打印机。"""
    try:
        import win32ui
    except Exception as exc:  # pragma: no cover
        raise PrintError(f"无法加载 Win32 打印接口：{exc}") from exc

    _apply_devmode(printer, settings)

    doc = fitz.open(str(path))
    hdc = None
    printed = 0
    try:
        pages = resolve_pages(settings.page_range, doc.page_count)
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer)

        dev_w = hdc.GetDeviceCaps(HORZRES)
        dev_h = hdc.GetDeviceCaps(VERTRES)

        hdc.StartDoc(os.path.basename(str(path)))
        try:
            for pno in pages:
                page = doc[pno]
                rect, (dpi_x, dpi_y) = _target_rect(
                    page.rect.width, page.rect.height, dev_w, dev_h, settings.scale
                )
                dpi = max(MIN_DPI, min(MAX_DPI, (dpi_x + dpi_y) / 2))
                img = render_page(page, dpi)
                if img.size[0] != (rect[2] - rect[0]) or img.size[1] != (rect[3] - rect[1]):
                    img = img.resize((max(1, rect[2] - rect[0]), max(1, rect[3] - rect[1])), Image.LANCZOS)

                hdc.StartPage()
                try:
                    ImageWin.Dib(img).draw(hdc.GetHandleOutput(), rect)
                finally:
                    hdc.EndPage()
                printed += 1
        finally:
            hdc.EndDoc()
    except Exception as exc:
        raise PrintError(str(exc)) from exc
    finally:
        doc.close()
        if hdc is not None:
            try:
                hdc.DeleteDC()
            except Exception:
                pass

    return PrintOutcome(ok=True, pages_printed=printed, method="gdi")


def find_sumatra() -> str | None:
    """查找可用的 SumatraPDF：优先随包目录，其次常见安装位置。"""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "tools" / "SumatraPDF" / "SumatraPDF.exe",
        here.parent / "SumatraPDF.exe",
        Path(os.environ.get("ProgramFiles", "")) / "SumatraPDF" / "SumatraPDF.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "SumatraPDF" / "SumatraPDF.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def print_pdf_sumatra(
    path: str | Path, settings: PrintSettings, printer: str, exe: str
) -> PrintOutcome:
    """SumatraPDF 路径：交给成熟实现，支持纸盒与驱动级双面。"""
    cmd = [exe, "-print-to", printer, "-silent"]
    opts = settings.to_sumatra()
    if opts:
        cmd += ["-print-settings", opts]
    cmd.append(str(path))

    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise PrintError(
            f"SumatraPDF 退出码 {proc.returncode}"
            + (f": {proc.stderr.decode('utf-8', 'ignore').strip()}" if proc.stderr else "")
        )

    pages = len(resolve_pages(settings.page_range, pdf_page_count(path)))
    return PrintOutcome(ok=True, pages_printed=pages, method="sumatra")


def print_pdf(path: str | Path, settings: PrintSettings, printer: str,
              prefer_sumatra: bool = True) -> PrintOutcome:
    """打印 PDF：优先 SumatraPDF，失败自动回落到自研 GDI 路径。"""
    if prefer_sumatra:
        exe = find_sumatra()
        if exe:
            try:
                return print_pdf_sumatra(path, settings, printer, exe)
            except PrintError:
                pass
    return print_pdf_gdi(path, settings, printer)
