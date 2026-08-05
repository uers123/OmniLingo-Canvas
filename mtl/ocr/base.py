"""OCR 引擎抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Page, TextRegion


class BaseOCR(ABC):
    name = "base"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @abstractmethod
    def detect(self, page: Page) -> List[TextRegion]:
        """检测文本区域（多边形 + 文本 + 置信度）。

        一体化引擎（如 PaddleOCR）可直接在 detect 中完成识别。
        """

    def recognize(self, page: Page, regions: List[TextRegion]) -> List[TextRegion]:
        """对已有区域做识别（识别专用引擎如 manga-ocr 重写此方法）。"""
        return regions

    def run(self, page: Page) -> List[TextRegion]:
        regions = self.detect(page)
        return self.recognize(page, regions)
