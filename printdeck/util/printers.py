"""打印机枚举与能力探测（Windows Win32 Spooler API）。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass, field

# Win32 常量
PRINTER_ENUM_LOCAL = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004

PRINTER_STATUS_PAUSED = 0x00000001
PRINTER_STATUS_ERROR = 0x00000002
PRINTER_STATUS_PENDING_DELETION = 0x00000004
PRINTER_STATUS_PAPER_JAM = 0x00000008
PRINTER_STATUS_PAPER_OUT = 0x00000010
PRINTER_STATUS_OUTPUT_BIN_FULL = 0x00000800
PRINTER_STATUS_NOT_AVAILABLE = 0x00001000
PRINTER_STATUS_NO_TONER = 0x00040000
PRINTER_STATUS_OFFLINE = 0x00000080

DC_FIELDS = 1
DC_PAPERS = 2
DC_PAPERNAMES = 16
DC_DUPLEX = 7
DC_COLORDEVICE = 11


@dataclass
class PrinterInfo:
    name: str
    is_default: bool = False
    status: int = 0
    duplex: bool = False
    color: bool = False
    papers: list[str] = field(default_factory=list)
    port: str = ""

    @property
    def interactive(self) -> bool:
        """端口为 PORTPROMPT: 的虚拟打印机每打印一个文件都会弹出保存对话框，
        批量打印时会导致进程逐个阻塞，必须提前识别并提示。
        """
        return self.port.upper().startswith("PORTPROMPT")

    @property
    def offline(self) -> bool:
        return bool(self.status & (PRINTER_STATUS_OFFLINE | PRINTER_STATUS_NOT_AVAILABLE))

    @property
    def state_text(self) -> str:
        if self.offline:
            return "离线"
        if self.status & PRINTER_STATUS_PAUSED:
            return "已暂停"
        if self.status & PRINTER_STATUS_PAPER_OUT:
            return "缺纸"
        if self.status & PRINTER_STATUS_PAPER_JAM:
            return "卡纸"
        if self.status & PRINTER_STATUS_ERROR:
            return "错误"
        return "就绪"


def _winspool():
    return ctypes.WinDLL("winspool.drv", use_last_error=True)


def list_printer_names() -> list[str]:
    """枚举本机所有本地与网络打印机名。"""
    try:
        import win32print

        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return [item[2] for item in win32print.EnumPrinters(flags)]
    except Exception:
        return _list_printer_names_fallback()


def _list_printer_names_fallback() -> list[str]:
    """pywin32 不可用时的 ctypes 兜底实现。"""
    dll = _winspool()
    needed = wt.DWORD()
    returned = wt.DWORD()
    dll.EnumPrintersW(
        PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS,
        None,
        4,  # PRINTER_INFO_4
        None,
        0,
        ctypes.byref(needed),
        ctypes.byref(returned),
    )

    class PRINTER_INFO_4(ctypes.Structure):
        _fields_ = [("pPrinterName", wt.LPWSTR), ("pServerName", wt.LPWSTR), ("Attributes", wt.DWORD)]

    buf = ctypes.create_string_buffer(needed.value)
    if not dll.EnumPrintersW(
        PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS,
        None,
        4,
        buf,
        needed,
        ctypes.byref(needed),
        ctypes.byref(returned),
    ):
        return []
    arr = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4))
    return [arr[i].pPrinterName for i in range(returned.value)]


def default_printer() -> str:
    try:
        import win32print

        return win32print.GetDefaultPrinter()
    except Exception:
        dll = _winspool()
        size = wt.DWORD(0)
        dll.GetDefaultPrinterW(None, ctypes.byref(size))
        buf = ctypes.create_unicode_buffer(size.value)
        if dll.GetDefaultPrinterW(buf, ctypes.byref(size)):
            return buf.value
        return ""


def printer_detail(name: str) -> tuple[int, str]:
    """返回 (状态位, 端口名)。"""
    try:
        import win32print

        handle = win32print.OpenPrinter(name)
        try:
            info = win32print.GetPrinter(handle, 2)
            return int(info.get("Status", 0)), str(info.get("pPortName", "") or "")
        finally:
            win32print.ClosePrinter(handle)
    except Exception:
        return 0, ""


def device_capabilities(name: str) -> dict:
    """读取打印机能力：是否支持双面、是否彩色、可用纸张名。"""
    out = {"duplex": False, "color": False, "papers": []}
    try:
        import win32print

        out["duplex"] = bool(win32print.DeviceCapabilities(name, None, DC_DUPLEX))
        out["color"] = bool(win32print.DeviceCapabilities(name, None, DC_COLORDEVICE))
        papers = win32print.DeviceCapabilities(name, None, DC_PAPERNAMES)
        out["papers"] = [str(p) for p in (papers or [])]
    except Exception:
        pass
    return out


def get_printers() -> list[PrinterInfo]:
    """返回带能力与状态的打印机列表。"""
    dflt = default_printer()
    result: list[PrinterInfo] = []
    for name in list_printer_names():
        caps = device_capabilities(name)
        status, port = printer_detail(name)
        result.append(
            PrinterInfo(
                name=name,
                is_default=(name == dflt),
                status=status,
                duplex=caps["duplex"],
                color=caps["color"],
                papers=caps["papers"],
                port=port,
            )
        )
    result.sort(key=lambda p: (not p.is_default, p.name))
    return result


def find_printer(name: str) -> PrinterInfo | None:
    for p in get_printers():
        if p.name == name:
            return p
    return None
