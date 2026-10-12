"""通道抽象：所有非 PDF 格式先归一成 PDF，再由统一引擎打印。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class UnsupportedFormat(Exception):
    """不支持的文件格式。"""


class ConvertError(Exception):
    """格式转换失败。"""


@dataclass
class ConvertResult:
    pdf_path: Path
    temp_files: list[Path] = field(default_factory=list)
    note: str = ""  # 转换过程中产生的提示，例如「已回落 LibreOffice」


class Channel:
    name = "base"
    extensions: tuple[str, ...] = ()

    def handles(self, ext: str) -> bool:
        return ext.lower() in self.extensions

    def to_pdf(self, src: Path, workdir: Path) -> ConvertResult:
        raise NotImplementedError
