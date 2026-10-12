"""打印设置模型：全局默认值 + 单文件覆盖。"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field, replace

DUPLEX_MODES = ("simplex", "duplex", "duplexlong", "duplexshort")
COLOR_MODES = ("auto", "color", "mono")
PAPER_SIZES = ("auto", "A4", "A5", "A3", "letter", "legal")
ORIENTATIONS = ("auto", "portrait", "landscape")
SCALES = ("fit", "noscale", "shrink", "stretch")


@dataclass
class PrintSettings:
    """一份打印参数。字段为 None 表示「跟随全局」。"""

    printer: str | None = None
    copies: int = 1
    duplex: str = "simplex"
    color: str = "auto"
    paper: str = "auto"
    orientation: str = "auto"
    scale: str = "fit"
    collate: bool = True
    page_range: str = ""  # 形如 "1-3,5,8-"；空串表示全部

    def merged(self, override: "PrintSettings | None") -> "PrintSettings":
        """用单文件覆盖值合成最终设置。"""
        if override is None:
            return replace(self)
        base = asdict(self)
        for key, value in asdict(override).items():
            if value is not None and value != "" and value != 0:
                base[key] = value
        return PrintSettings(**base)

    def to_sumatra(self) -> str:
        """转成 SumatraPDF 的 -print-settings 字符串。"""
        parts: list[str] = []
        if self.page_range.strip():
            parts.append(self.page_range.strip().replace(" ", ""))
        if self.duplex != "simplex":
            parts.append(self.duplex)
        if self.color in ("color", "mono"):
            parts.append("color" if self.color == "color" else "monochrome")
        if self.orientation in ("portrait", "landscape"):
            parts.append(self.orientation)
        if self.scale in SCALES:
            parts.append(self.scale)
        if self.paper != "auto":
            parts.append(f"paper={self.paper}")
        parts.append("collate" if self.collate else "nocollate")
        if self.copies > 1:
            parts.append(f"{self.copies}x")
        return ",".join(parts)

    def describe(self) -> str:
        bits = [f"{self.copies}份"]
        if self.duplex != "simplex":
            bits.append("双面")
        if self.color != "auto":
            bits.append("彩色" if self.color == "color" else "黑白")
        if self.paper != "auto":
            bits.append(self.paper)
        if self.page_range.strip():
            bits.append(f"页 {self.page_range}")
        return " / ".join(bits)


@dataclass
class JobOverride:
    """单个文件的覆盖设置。"""

    path: str
    settings: PrintSettings = field(default_factory=PrintSettings)


def default_settings(printer: str | None = None) -> PrintSettings:
    return PrintSettings(printer=printer)
