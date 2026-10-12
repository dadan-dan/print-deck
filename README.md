# PrintDeck 批量打印

把一堆 PDF / Word / Excel / PPT / 图片拖进窗口，设一次参数，批量打完，全程能看到打印队列。
免费、开源、离线可用，用来替代 Print Conductor 一类按次收费的批量打印软件。

---

## 为什么做成这样

市面上的批量打印工具要么收费，要么把文件传上云端。这个项目的目标是：**本机跑、不联网、单文件 exe、双击即用**。

### 核心设计：所有格式先归一成 PDF

```
Word/Excel/PPT ──► Office COM / LibreOffice ──► PDF ┐
图片 ────────────► PyMuPDF 建页 ───────────► PDF ┼──► 统一打印引擎 ──► 打印机
PDF ───────────────────────────────────────► PDF ┘
```

好处是**批量设置的口径只有一套**：双面、彩色、纸张、页码范围这些参数，
不用在每个格式上各实现一遍。代价是 Office 文档多一步转换，
换来的是「设置一定生效」——直接调 Word 的 `PrintOut()` 是无法精细控制双面和彩色的。

### 打印引擎

| 路径 | 说明 |
|---|---|
| 自研 GDI（默认） | PyMuPDF 按页光栅化 → Win32 GDI 直送打印机。零外部依赖，没装任何 PDF 软件的机器也能打 |
| SumatraPDF（可选增强） | 检测到系统里有就自动优先使用，支持纸盒选择、驱动级双面等高级能力；失败自动回落自研路径 |

DEVMODE（双面/彩色/纸张/方向）通过 `win32print` 直接改写，份数由队列层循环调用，
避免不同驱动的 `Copies` 字段行为不一致。

---

## 用法

### 图形界面

双击 `PrintDeck.exe`，拖入文件或文件夹 → 选打印机 → 设参数 → 开始打印。

- 双击列表里某一行，可以**单独给这个文件**设份数/双面/页码范围
- 队列实时显示状态、页数、耗时；失败的文件不会中断整批，可一键重试
- 支持拖拽、添加文件夹（递归子目录）

### 命令行

打包产物里有两个 exe：`PrintDeck.exe`（图形界面，双击打开）和
`PrintDeckCLI.exe`（命令行，保留控制台输出）。命令行一律用后者：

```bat
:: 列出打印机及能力
PrintDeckCLI.exe printers

:: 批量打印整个文件夹
PrintDeckCLI.exe print D:\合同 --printer "HP LaserJet" --copies 2 --duplex

:: 先看看会打哪些文件，不真打
PrintDeckCLI.exe print D:\合同 --dry-run

:: 指定页码、黑白、A4
PrintDeckCLI.exe print a.pdf b.docx --pages 1-3,5 --color mono --paper A4
```

把文件或文件夹**拖到 `PrintDeck.exe` 图标上**，会直接打开界面并载入这些文件。

---

## 从源码运行

```bat
pip install -r requirements.txt
python -m printdeck            :: 启动界面
python -m printdeck printers   :: 列出打印机
python tests\selftest.py       :: 三通道自检
```

打包成单文件 exe：

```bat
python -m PyInstaller build\PrintDeck.spec --distpath dist --workpath build\.tmp --noconfirm
```

产物在 `dist\PrintDeck.exe`，**目标机器不需要装 Python 或 Office 之外的任何东西**。

Office 文档需要目标机器装有 **Microsoft Office / WPS / LibreOffice 之一**；
三者都没有时，PDF 和图片仍可正常打印。

---

## 踩过的坑（也是这个项目的技术含量所在）

1. **虚拟打印机会把批量打印卡死**
   `Microsoft Print to PDF`、`Microsoft XPS Document Writer` 的端口是 `PORTPROMPT:`，
   每打印一个文件都会弹一次「另存为」并阻塞进程。打 50 个文件就弹 50 次。
   程序会识别这类端口并在界面上标红警告。

2. **`DeleteDC()` 会隐式提交作业**
   测试里想中途放弃打印，结果虚拟打印机照样弹出保存框。必须显式 `AbortDoc()`。

3. **Office COM 会残留进程**
   Word/Excel/PowerPoint 的 COM 对象必须显式 `Quit()`，否则打完一批后会留下一堆
   `WINWORD.EXE` 后台进程。代码中用 `try/finally` 兜住。

4. **PyMuPDF 的新入口**
   老写法 `import fitz` 已标记弃用，新版推荐 `import pymupdf`，代码做了兼容回落。

---

## 已知限制

- 单文件 exe 约 80–120 MB、启动 2–3 秒（PyInstaller 每次运行需解压临时目录）
- Office 转 PDF 依赖本机 Office/WPS/LibreOffice，首次调用会慢（COM 初始化）
- 已经送进打印机后台（spooler）的页面无法从程序里撤回，只能去打印机面板取消
- 图片按 A4 纵向排版，多帧 TIFF/动态 GIF 会拆成多页

## 许可

MIT
