"""Manga-OCR 适配器：日文漫画专用识别（仅识别，检测复用其他引擎）。

依赖: pip install manga-ocr
"""

from __future__ import annotations

from typing import List

from ...errors import EngineLoadError, OCRError
from ...models import Page, TextRegion
from ...registry import register
from ..base import BaseOCR


@register("ocr", "manga_ocr")
class MangaOCR(BaseOCR):
    name = "manga_ocr"

    def __init__(self, detector: str = "paddle", lang: str = "jp", **kwargs):
        super().__init__(**kwargs)
        self.detector_name = detector
        self.lang = lang
        self._ocr = None
        self._detector = None

    def _get(self):
        if self._ocr is None:
            try:
                from manga_ocr import MangaOcr
            except ImportError as e:
                raise EngineLoadError(
                    "manga-ocr 未安装: pip install manga-ocr"
                ) from e
            try:
                self._ocr = MangaOcr()
            except Exception as e:
                raise EngineLoadError(f"manga-ocr 初始化失败: {e}") from e
        return self._ocr

    def detect(self, page: Page) -> List[TextRegion]:
        # 复用 paddle 做文本区域检测（若可用）
        if self._detector is None:
            try:
                from .paddle import PaddleOCR
                self._detector = PaddleOCR(lang=self.lang)
            except Exception:
                raise EngineLoadError(
                    "manga_ocr 引擎需要检测器: 请安装 paddleocr 或改用其他 OCR 引擎"
                )
        return self._detector.detect(page)

    def recognize(self, page: Page, regions: List[TextRegion]) -> List[TextRegion]:
        ocr = self._get()
        for r in regions:
            x0, y0, x1, y1 = (int(v) for v in r.bbox)
            if x1 <= x0 or y1 <= y0:
                continue
            crop = page.image.crop((x0, y0, x1, y1))
            try:
                r.text = str(ocr(crop))
                r.conf = 1.0
            except Exception as e:
                raise OCRError(f"manga-ocr 识别失败: {e}") from e
        return regions
