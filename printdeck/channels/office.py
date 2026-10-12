"""Office 通道：Word / Excel / PowerPoint → PDF。

引擎优先级：
  1. Microsoft Office COM（保真最好，能保留分节方向、工作表布局、幻灯片比例）
  2. WPS Office COM（ProgID 与 Office 不同，单独尝试）
  3. LibreOffice headless（没装 Office 时的兜底）

COM 调用必须显式 Quit，否则会残留 winword/excel/powerpnt 进程。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import Channel, ConvertError, ConvertResult

WORD_EXT = (".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt")
EXCEL_EXT = (".xls", ".xlsx", ".xlsm", ".xlsb", ".csv", ".ods")
PPT_EXT = (".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".odp")

# Word: 17 = wdFormatPDF; Excel: 0 = xlTypePDF; PowerPoint: 32 = ppSaveAsPDF
WORD_FORMAT_PDF = 17
PPT_FORMAT_PDF = 32

COM_CANDIDATES = {
    "word": ("Word.Application", "KWps.Application"),
    "excel": ("Excel.Application", "KET.Application"),
    "ppt": ("PowerPoint.Application", "KWPP.Application"),
}


def _libreoffice_exe() -> str | None:
    for candidate in ("soffice", "soffice.exe"):
        found = shutil.which(candidate)
        if found:
            return found
    for base in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(base).is_file():
            return base
    return None


def _convert_via_libreoffice(src: Path, workdir: Path) -> Path | None:
    exe = _libreoffice_exe()
    if not exe:
        return None
    proc = subprocess.run(
        [exe, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(workdir), str(src)],
        capture_output=True,
        timeout=300,
    )
    produced = workdir / f"{src.stem}.pdf"
    if proc.returncode == 0 and produced.is_file():
        return produced
    return None


def _dispatch(prog_ids: tuple[str, ...]):
    """按候选 ProgID 依次尝试创建 COM 对象。"""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    last_err: Exception | None = None
    for prog_id in prog_ids:
        try:
            return win32com.client.DispatchEx(prog_id), prog_id
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise ConvertError(f"无法创建 Office COM 对象（{', '.join(prog_ids)}）：{last_err}")


class WordChannel(Channel):
    name = "word"
    extensions = WORD_EXT

    def to_pdf(self, src: Path, workdir: Path) -> ConvertResult:
        out = workdir / f"{src.stem}.pdf"
        app, prog = _dispatch(COM_CANDIDATES["word"])
        doc = None
        try:
            app.Visible = False
            try:
                app.DisplayAlerts = 0
            except Exception:
                pass
            doc = app.Documents.Open(str(src), ReadOnly=True)
            doc.SaveAs(str(out), FileFormat=WORD_FORMAT_PDF)
        except Exception as exc:
            raise ConvertError(f"Word 转 PDF 失败：{exc}") from exc
        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass
            try:
                app.Quit()
            except Exception:
                pass

        note = "" if prog == "Word.Application" else f"由 {prog} 转换"
        return ConvertResult(pdf_path=out, temp_files=[out], note=note)


class ExcelChannel(Channel):
    name = "excel"
    extensions = EXCEL_EXT

    def to_pdf(self, src: Path, workdir: Path) -> ConvertResult:
        out = workdir / f"{src.stem}.pdf"
        app, prog = _dispatch(COM_CANDIDATES["excel"])
        wb = None
        try:
            app.Visible = False
            app.DisplayAlerts = False
            wb = app.Workbooks.Open(str(src), ReadOnly=True)
            wb.ExportAsFixedFormat(0, str(out))
        except Exception as exc:
            raise ConvertError(f"Excel 转 PDF 失败：{exc}") from exc
        finally:
            if wb is not None:
                try:
                    wb.Close(False)
                except Exception:
                    pass
            try:
                app.Quit()
            except Exception:
                pass

        note = "" if prog == "Excel.Application" else f"由 {prog} 转换"
        return ConvertResult(pdf_path=out, temp_files=[out], note=note)


class PowerPointChannel(Channel):
    name = "ppt"
    extensions = PPT_EXT

    def to_pdf(self, src: Path, workdir: Path) -> ConvertResult:
        out = workdir / f"{src.stem}.pdf"
        app, prog = _dispatch(COM_CANDIDATES["ppt"])
        pres = None
        try:
            pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
            pres.SaveAs(str(out), PPT_FORMAT_PDF)
        except Exception as exc:
            raise ConvertError(f"PowerPoint 转 PDF 失败：{exc}") from exc
        finally:
            if pres is not None:
                try:
                    pres.Close()
                except Exception:
                    pass
            try:
                app.Quit()
            except Exception:
                pass

        note = "" if prog == "PowerPoint.Application" else f"由 {prog} 转换"
        return ConvertResult(pdf_path=out, temp_files=[out], note=note)


def convert_office(src: Path, workdir: Path) -> ConvertResult:
    """按扩展名选择 Office 通道；COM 全不可用时回落 LibreOffice。"""
    ext = src.suffix.lower()
    if ext in WORD_EXT:
        channel: Channel = WordChannel()
    elif ext in EXCEL_EXT:
        channel = ExcelChannel()
    elif ext in PPT_EXT:
        channel = PowerPointChannel()
    else:
        raise ConvertError(f"不是 Office 文档：{src.name}")

    try:
        return channel.to_pdf(src, workdir)
    except ConvertError as com_err:
        produced = _convert_via_libreoffice(src, workdir)
        if produced is None:
            raise ConvertError(f"{com_err}；且未找到可用的 LibreOffice 兜底") from com_err
        return ConvertResult(pdf_path=produced, temp_files=[produced], note="由 LibreOffice 转换")
