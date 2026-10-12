"""命令行入口。

    printdeck print D:\\合同 --printer "HP LaserJet" --copies 2 --duplex
    printdeck printers
    printdeck            # 不带参数时启动图形界面
"""

from __future__ import annotations

import argparse
import sys
import time

from .channels.registry import SUPPORTED, collect
from .engine import PrintError
from .queue import CANCELLED, DONE, FAILED, PrintQueue
from .settings import COLOR_MODES, DUPLEX_MODES, PAPER_SIZES, PrintSettings
from .util.printers import default_printer, find_printer, get_printers


def _ensure_utf8_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass


STATUS_ICON = {DONE: "√", FAILED: "x", CANCELLED: "-"}


def cmd_printers(_args: argparse.Namespace) -> int:
    printers = get_printers()
    if not printers:
        print("未检测到任何打印机。")
        return 1
    print(f"{'':2}{'打印机':<40}{'状态':<8}{'双面':<6}{'彩色':<6}{'备注'}")
    print("-" * 88)
    for p in printers:
        mark = "*" if p.is_default else " "
        note = "交互式：每个文件都要选保存位置，不适合批量" if p.interactive else ""
        print(
            f"{mark:2}{p.name:<40}{p.state_text:<8}{'是' if p.duplex else '否':<6}{'是' if p.color else '否':<6}{note}"
        )
    print("-" * 88)
    print("* = 系统默认打印机")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printdeck",
        description="PrintDeck —— 批量文件打印工具（PDF / Word / Excel / PPT / 图片）",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("printers", help="列出本机打印机及能力")
    p_list.set_defaults(func=cmd_printers)

    p = sub.add_parser("print", help="批量打印文件或文件夹")
    p.add_argument("paths", nargs="+", help="文件、文件夹或通配符")
    p.add_argument("--printer", "-P", default=None, help="目标打印机名，默认使用系统默认打印机")
    p.add_argument("--copies", "-n", type=int, default=1, help="每份文件打印份数，默认 1")
    p.add_argument("--duplex", default="simplex", choices=DUPLEX_MODES, help="单双面，默认 simplex")
    p.add_argument("--color", default="auto", choices=COLOR_MODES, help="色彩模式，默认 auto")
    p.add_argument("--paper", default="auto", choices=PAPER_SIZES, help="纸张大小，默认 auto")
    p.add_argument("--pages", default="", help="页码范围，如 1-3,5,8- ；默认全部")
    p.add_argument("--no-recursive", action="store_true", help="不递归子文件夹")
    p.add_argument("--sumatra", action="store_true", help="优先调用 SumatraPDF（如已安装）")
    p.add_argument("--dry-run", action="store_true", help="只列出将要打印的文件，不实际打印")
    p.add_argument("--yes", "-y", action="store_true", help="跳过交互确认（用于脚本调用）")
    p.set_defaults(func=cmd_print)

    sub.add_parser("gui", help="启动图形界面").set_defaults(func=lambda a: cmd_gui(a))

    return parser


def cmd_print(args: argparse.Namespace) -> int:
    files = collect(args.paths, recursive=not args.no_recursive)
    if not files:
        print(f"没有找到受支持的文件。支持：{', '.join(sorted(SUPPORTED))}")
        return 1

    printer = args.printer or default_printer()
    if not printer:
        print("未指定打印机，且系统没有默认打印机。")
        return 1

    info = find_printer(printer)
    if info is not None and info.interactive and not args.yes and not args.dry_run:
        print(f"警告：「{printer}」是交互式虚拟打印机（端口 {info.port}）。")
        if len(files) > 1:
            print(f"批量打印 {len(files)} 个文件时，它会为每个文件弹一次保存对话框并逐个等待，很容易卡死。")
        try:
            ans = input("仍要继续？[y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("已取消。建议改用实体打印机，或加 --dry-run 先确认文件列表。")
            return 1

    settings = PrintSettings(
        printer=printer,
        copies=args.copies,
        duplex=args.duplex,
        color=args.color,
        paper=args.paper,
        page_range=args.pages,
    )

    print(f"共 {len(files)} 个文件 → {printer}   [{settings.describe()}]")
    if args.dry_run:
        for f in files:
            print(f"  {f}")
        return 0

    queue = PrintQueue(settings)
    queue.prefer_sumatra = args.sumatra
    queue.add(files)

    states: dict[int, str] = {}
    queue.on_change = lambda: None

    queue.start()
    while queue.running:
        for job in queue.jobs:
            if states.get(job.id) != job.status:
                states[job.id] = job.status
                print(f"  [{job.status}] {job.name}")
        time.sleep(0.1)

    for job in queue.jobs:
        if states.get(job.id) != job.status:
            print(f"  [{job.status}] {job.name}")

    stats = queue.stats()
    print("-" * 60)
    print(f"完成 {stats.done} / 失败 {stats.failed} / 取消 {stats.cancelled}，共输出 {stats.pages} 页")
    for job in queue.jobs:
        if job.status == FAILED:
            print(f"  ! {job.name}: {job.message}")
    return 0 if stats.failed == 0 else 2


def cmd_gui(_args: argparse.Namespace | None = None, paths: list[str] | None = None) -> int:
    try:
        from .gui import run_gui
    except Exception as exc:
        print(f"图形界面不可用（{exc}）。请确认已安装 PySide6。")
        return 1
    return run_gui(paths)


SUBCOMMANDS = ("print", "printers", "gui")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)

    # 不是子命令时，一律当作「把文件/文件夹拖到了 exe 上」：启动界面并载入
    if not argv or argv[0] not in SUBCOMMANDS:
        return cmd_gui(None, [a for a in argv if not a.startswith("-")])

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PrintError as exc:
        print(f"错误：{exc}")
        return 1
    except KeyboardInterrupt:
        print("\n已中止。")
        return 130
