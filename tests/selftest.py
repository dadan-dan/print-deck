"""自检脚本：生成样本文件，验证三个通道的转换与打印渲染管线。

    python tests/selftest.py

注意：本脚本不会真正把作业提交到打印机（不调用 EndDoc），
否则虚拟打印机（Microsoft Print to PDF）会弹出保存对话框把进程卡住。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore

from printdeck.channels.registry import normalize
from printdeck.engine import resolve_pages

SAMPLES = ROOT / "samples"
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED.append(label)


def make_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), f"PrintDeck 自检第 {i + 1} 页", fontsize=24)
        page.insert_text((72, 180), "selftest page", fontsize=14)
    doc.save(str(path))
    doc.close()


def make_image(path: Path) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1200, 800), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([100, 100, 1100, 700], outline="black", width=6)
    d.text((140, 380), "PrintDeck image sample", fill="black")
    img.save(path)


def make_office_samples(folder: Path) -> dict[str, Path]:
    """用 Office COM 造 docx / xlsx / pptx 样本。没有 Office 时返回空。"""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    out: dict[str, Path] = {}

    # Word
    try:
        docx = folder / "sample.docx"
        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        try:
            doc = app.Documents.Add()
            doc.Content.Text = "PrintDeck Word 样本\n第二行内容"
            doc.SaveAs2(str(docx))
            doc.Close(False)
            out["word"] = docx
        finally:
            app.Quit()
    except Exception as exc:
        print(f"  [warn] Word 样本失败：{exc}")

    # Excel
    try:
        xlsx = folder / "sample.xlsx"
        app = win32com.client.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        try:
            wb = app.Workbooks.Add()
            wb.Worksheets(1).Range("A1:C5").Value = [[f"r{r}c{c}" for c in range(3)] for r in range(5)]
            wb.SaveAs(str(xlsx))
            wb.Close(False)
            out["excel"] = xlsx
        finally:
            app.Quit()
    except Exception as exc:
        print(f"  [warn] Excel 样本失败：{exc}")

    # PowerPoint：用 ppLayoutText(2)，空白版式没有默认形状
    try:
        pptx = folder / "sample.pptx"
        app = win32com.client.DispatchEx("PowerPoint.Application")
        try:
            pres = app.Presentations.Add()
            slide = pres.Slides.Add(1, 2)  # ppLayoutText
            slide.Shapes(1).TextFrame.TextRange.Text = "PrintDeck PPT 样本"
            pres.SaveAs(str(pptx))
            pres.Close()
            out["ppt"] = pptx
        finally:
            app.Quit()
    except Exception as exc:
        print(f"  [warn] PPT 样本失败：{exc}")

    return out


def test_page_range() -> None:
    check("页码解析 1-3,5 / 共10页", resolve_pages("1-3,5", 10) == [0, 1, 2, 4])
    check("页码解析 8- / 共10页", resolve_pages("8-", 10) == [7, 8, 9])
    check("页码解析 空 = 全部", resolve_pages("", 4) == [0, 1, 2, 3])
    check("页码解析 逆序 5-3", resolve_pages("5-3", 6) == [2, 3, 4])
    try:
        resolve_pages("99", 3)
        check("页码越界应报错", False)
    except Exception:
        check("页码越界应报错", True)


def test_render_pipeline(pdf_path: Path, printer: str, interactive: bool) -> None:
    """验证 GDI 打印管线：建 DC → 光栅化 →（可选）提交绘制。

    交互式虚拟打印机（端口 PORTPROMPT:）会在 StartDoc 弹出保存对话框并一直等待，
    因此这类打印机只验证到光栅化为止，不提交作业。
    """
    from PIL import Image, ImageWin

    try:
        import win32ui

        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer)
        dev_w, dev_h = hdc.GetDeviceCaps(8), hdc.GetDeviceCaps(10)

        doc = fitz.open(str(pdf_path))
        frames = []
        for page in doc:
            pix = page.get_pixmap(dpi=150, alpha=False)
            frames.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        pages = len(frames)
        doc.close()

        if interactive:
            hdc.DeleteDC()
            check(
                f"GDI 渲染管线（{printer}）",
                pages > 0,
                f"光栅化 {pages} 页 OK，可打印区 {dev_w}x{dev_h}；跳过提交（该打印机会弹保存框）",
            )
            return

        hdc.StartDoc("PrintDeck 自检")
        drawn = 0
        for img in frames:
            w = min(dev_w, img.width)
            h = min(dev_h, img.height)
            hdc.StartPage()
            ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (0, 0, w, h))
            hdc.EndPage()
            drawn += 1
        hdc.EndDoc()
        hdc.DeleteDC()
        check(f"GDI 渲染管线（{printer}）", drawn == pages, f"已提交 {drawn}/{pages} 页，可打印区 {dev_w}x{dev_h}")
    except Exception as exc:
        check(f"GDI 渲染管线（{printer}）", False, f"{type(exc).__name__}: {exc}")


def main() -> int:
    SAMPLES.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="printdeck_selftest_"))

    pdf = SAMPLES / "sample.pdf"
    img = SAMPLES / "sample.png"
    make_pdf(pdf, 3)
    make_image(img)
    print(f"样本目录：{SAMPLES}")

    test_page_range()

    with fitz.open(str(pdf)) as d:
        check("生成 PDF 样本", d.page_count == 3, f"{d.page_count} 页")

    # 图片通道
    try:
        res = normalize(img, work)
        with fitz.open(str(res.pdf_path)) as d:
            check("图片 → PDF", d.page_count == 1, f"{d.page_count} 页")
    except Exception as exc:
        check("图片 → PDF", False, f"{type(exc).__name__}: {exc}")

    # Office 通道
    try:
        office = make_office_samples(SAMPLES)
    except Exception as exc:
        office = {}
        print(f"[SKIP] 生成 Office 样本失败：{type(exc).__name__}: {exc}")

    if not office:
        print("[SKIP] 未安装 Office，跳过 Word/Excel/PPT 转换测试")
    for key in ("word", "excel", "ppt"):
        if key not in office:
            continue
        try:
            res = normalize(office[key], work)
            with fitz.open(str(res.pdf_path)) as d:
                check(f"{key} → PDF", d.page_count >= 1, f"{d.page_count} 页 {res.note}")
        except Exception as exc:
            check(f"{key} → PDF", False, f"{type(exc).__name__}: {exc}")

    # GDI 管线
    from printdeck.util.printers import default_printer, find_printer

    printer = default_printer()
    info = find_printer(printer)
    test_render_pipeline(pdf, printer, bool(info and info.interactive))

    print("-" * 60)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：{', '.join(FAILED)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
