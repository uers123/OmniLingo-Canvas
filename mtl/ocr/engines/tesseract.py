"""Tesseract 适配器。

依赖: pip install pytesseract + tesseract 本体
（Windows 安装: https://github.com/UB-Mannheim/tesseract/wiki）
"""

from __future__ import annotations

from typing import List

from ...errors import EngineLoadError, OCRError
from ...models import Page, TextRegion
from ...registry import register
from ..base import BaseOCR


@register("ocr", "tesseract")
class TesseractOCR(BaseOCR):
    name = "tesseract"

    def __init__(self, cmd: str = "tesseract", lang: str = "jpn", **kwargs):
        super().__init__(**kwargs)
        self.cmd = cmd
        self.lang = lang

    def _get(self):
        try:
            import pytesseract
        except ImportError as e:
            raise EngineLoadError(
                "pytesseract 未安装: pip install pytesseract"
            ) from e
        if self.cmd:
            pytesseract.pytesseract.tesseract_cmd = self.cmd
        return pytesseract

    def detect(self, page: Page) -> List[TextRegion]:
        t = self._get()
        try:
            data = t.image_to_data(
                page.image, lang=self.lang, output_type=t.Output.DICT
            )
        except Exception as e:
            raise OCRError(f"Tesseract 识别失败: {e}") from e
        regions: List[TextRegion] = []
        n = len(data.get("text", []))
        i = 0
        while i < n:
            if data["text"][i].strip() and float(data["conf"][i] or 0) >= 0:
                # 合并同行（同一 block/par/line）的碎片
                xs, ys, ws, hs, parts = [], [], [], [], []
                line_no = data["line_num"][i]
                block_no = data["block_num"][i]
                par_no = data["par_num"][i]
                j = i
                while (
                    j < n
                    and data["block_num"][j] == block_no
                    and data["par_num"][j] == par_no
                    and data["line_num"][j] == line_no
                ):
                    txt = data["text"][j]
                    if txt.strip():
                        parts.append(txt)
                        xs.append(data["left"][j])
                        ys.append(data["top"][j])
                        ws.append(data["width"][j])
                        hs.append(data["height"][j])
                    j += 1
                if parts:
                    x0, y0 = min(xs), min(ys)
                    x1 = max(x + w for x, w in zip(xs, ws))
                    y1 = max(y + h for y, h in zip(ys, hs))
                    confs = [float(data["conf"][k]) for k in range(i, j)
                             if str(data["text"][k]).strip()]
                    regions.append(
                        TextRegion(
                            polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                            text=" ".join(parts),
                            conf=(sum(confs) / len(confs)) / 100.0 if confs else 0.0,
                            lang=self.lang,
                        )
                    )
                i = j
            else:
                i += 1
        return regions
