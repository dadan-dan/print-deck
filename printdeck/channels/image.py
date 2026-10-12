"""图片通道：JPG/PNG/BMP/TIFF/GIF/WEBP 等 → PDF。

多帧图片（TIFF、动态 GIF）按帧拆成多页。EXIF 方向会自动纠正。
"""

from __future__ import annotations

import io
from pathlib import Path

try:  # PyMuPDF 新版推荐用 pymupdf 入口
    import pymupdf as fitz
except ImportError:  # pragma: no cover - 旧版本兼容
    import fitz  # type: ignore[no-redef]

from PIL import Image, ImageFile, ImageOps, ImageSequence

from .base import Channel, ConvertError, ConvertResult

ImageFile.LOAD_TRUNCATED_IMAGES = True

# 默认按 A4 纵向（595 x 842 pt）建页，实际纸张由打印引擎再适配
PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 24.0

EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".bmp", ".dib",
    ".tif", ".tiff", ".gif", ".webp", ".ico", ".emf", ".wmf",
)


def _frame_to_rgb(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        src = img.convert("RGBA")
        bg.paste(src, mask=src.split()[-1])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _fit_rect(img_w: int, img_h: int) -> tuple[float, float, float, float]:
    """在 A4 页面内等比居中。"""
    box_w, box_h = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN
    scale = min(box_w / img_w, box_h / img_h)
    w, h = img_w * scale, img_h * scale
    x0 = (PAGE_W - w) / 2
    y0 = (PAGE_H - h) / 2
    return (x0, y0, x0 + w, y0 + h)


class ImageChannel(Channel):
    name = "image"
    extensions = EXTENSIONS

    def to_pdf(self, src: Path, workdir: Path) -> ConvertResult:
        try:
            img = Image.open(src)
        except Exception as exc:
            raise ConvertError(f"无法打开图片：{exc}") from exc

        out = workdir / f"{src.stem}.pdf"
        doc = fitz.open()
        try:
            for frame in ImageSequence.Iterator(img):
                rgb = _frame_to_rgb(frame)
                buf = io.BytesIO()
                rgb.save(buf, format="PNG")
                page = doc.new_page(width=PAGE_W, height=PAGE_H)
                page.insert_image(fitz.Rect(*_fit_rect(rgb.width, rgb.height)), stream=buf.getvalue())
            if doc.page_count == 0:
                raise ConvertError("图片没有可读帧")
            doc.save(str(out))
        except ConvertError:
            raise
        except Exception as exc:
            raise ConvertError(f"图片转 PDF 失败：{exc}") from exc
        finally:
            doc.close()
            img.close()

        return ConvertResult(pdf_path=out, temp_files=[out])
