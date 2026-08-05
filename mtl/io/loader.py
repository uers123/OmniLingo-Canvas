"""多格式输入流：PNG/JPG/WEBP/BMP/TIF、PDF（可选 PyMuPDF）、ZIP 包、目录。"""

from __future__ import annotations

import io
import os
import zipfile
from typing import List, Optional

from PIL import Image

from ..errors import UnsupportedInputError
from ..models import Page

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
    ".gif", ".tif", ".tiff",
}

Image.MAX_IMAGE_PIXELS = None  # 允许大图（画集/扫描件）


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def load_pages(
    path: str,
    pdf_dpi: int = 300,
    pdf_pages: Optional[List[int]] = None,
    zip_password: Optional[str] = None,
) -> List[Page]:
    """将任意受支持输入解析为 Page 列表（保持页序）。"""
    if os.path.isdir(path):
        names = sorted(
            f for f in os.listdir(path)
            if _ext(f) in IMAGE_EXTS and not f.startswith(".")
        )
        if not names:
            raise UnsupportedInputError(f"目录中没有支持的图片: {path}")
        return [_page_from_image(os.path.join(path, n), i) for i, n in enumerate(names)]

    ext = _ext(path)
    if ext == ".zip":
        return _load_zip(path, zip_password)
    if ext == ".pdf":
        return _load_pdf(path, pdf_dpi, pdf_pages)
    if ext in IMAGE_EXTS:
        return [_page_from_image(path, 0)]
    raise UnsupportedInputError(f"不支持的输入格式: {path} (支持 {sorted(IMAGE_EXTS)}、pdf、zip)")


def _page_from_image(path: str, idx: int) -> Page:
    img = Image.open(path)
    img.load()
    return Page(
        page_index=idx,
        path=path,
        image=img,
        width=img.width,
        height=img.height,
    )


def _load_zip(path: str, password: Optional[str]) -> List[Page]:
    pages: List[Page] = []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if _ext(n) in IMAGE_EXTS)
        if not names:
            raise UnsupportedInputError(f"ZIP 中没有支持的图片: {path}")
        pwd = password.encode("utf-8") if password else None
        for i, name in enumerate(names):
            try:
                raw = z.read(name, pwd=pwd)
            except RuntimeError as e:
                raise UnsupportedInputError(f"ZIP 解压失败(密码错误?): {name}") from e
            img = Image.open(io.BytesIO(raw))
            img.load()
            pages.append(
                Page(
                    page_index=i,
                    path=f"{path}::{name}",
                    image=img,
                    width=img.width,
                    height=img.height,
                )
            )
    return pages


def _load_pdf(
    path: str, dpi: int, pages: Optional[List[int]]
) -> List[Page]:
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise UnsupportedInputError(
            "PDF 支持需要 PyMuPDF: pip install pymupdf"
        ) from e
    out: List[Page] = []
    doc = fitz.open(path)
    indices = pages if pages else list(range(doc.page_count))
    for i in indices:
        if i >= doc.page_count:
            break
        pix = doc[i].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        out.append(
            Page(page_index=i, path=f"{path}::page{i}", image=img,
                 width=img.width, height=img.height)
        )
    doc.close()
    return out
