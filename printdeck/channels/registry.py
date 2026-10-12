"""格式路由：把任意受支持文件归一成 PDF。"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ConvertResult, UnsupportedFormat
from .image import ImageChannel
from .office import EXCEL_EXT, PPT_EXT, WORD_EXT, convert_office

PDF_EXT = (".pdf",)

SUPPORTED = set(PDF_EXT) | set(ImageChannel.extensions) | set(WORD_EXT) | set(EXCEL_EXT) | set(PPT_EXT)

_NUM_SPLIT = re.compile(r"(\d+)")


def natural_key(text: str):
    """文件名自然排序：a2 排在 a10 前面。"""
    return [int(part) if part.isdigit() else part.lower() for part in _NUM_SPLIT.split(text)]


def normalize(src: Path, workdir: Path) -> ConvertResult:
    ext = src.suffix.lower()
    if ext in PDF_EXT:
        return ConvertResult(pdf_path=src, temp_files=[])
    if ext in ImageChannel.extensions:
        return ImageChannel().to_pdf(src, workdir)
    if ext in WORD_EXT or ext in EXCEL_EXT or ext in PPT_EXT:
        return convert_office(src, workdir)
    raise UnsupportedFormat(f"不支持的格式：{src.name}")


def collect(paths, recursive: bool = True) -> list[Path]:
    """把命令行传入的文件/文件夹展开成受支持文件列表，按自然序排列。"""
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            found.extend(f for f in it if f.is_file() and f.suffix.lower() in SUPPORTED)
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED:
                found.append(p)
        else:
            # 允许传通配符字符串
            for f in Path(".").glob(str(raw)):
                if f.is_file() and f.suffix.lower() in SUPPORTED:
                    found.append(f)
    return sorted({f.resolve() for f in found}, key=lambda f: natural_key(f.name))
