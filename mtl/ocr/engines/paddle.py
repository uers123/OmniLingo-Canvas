"""PaddleOCR 适配器：多语种检测 + 识别一体。

依赖: pip install paddleocr（首次运行自动下载模型权重）
兼容 PaddleOCR 2.x (ocr.ocr) 与 3.x (ocr.predict) 两代 API。
"""

from __future__ import annotations

from typing import List

import numpy as np

from ...errors import EngineLoadError, OCRError
from ...models import Page, TextRegion
from ...registry import register
from ..base import BaseOCR

# 语言码归一化: 兼容 jp/ja/jap/japan 等写法 -> PaddleOCR 官方码
_LANG_MAP = {
    "jp": "japan", "ja": "japan", "jap": "japan", "japanese": "japan",
    "zh": "ch", "zh-cn": "ch", "chinese": "ch", "chs": "ch",
    "zh-hant": "chinese_cht", "cht": "chinese_cht", "tc": "chinese_cht",
    "en": "en", "english": "en",
    "ko": "korean", "kr": "korean", "korean": "korean",
}


@register("ocr", "paddle")
class PaddleOCR(BaseOCR):
    name = "paddle"

    def __init__(self, lang: str = "jp", use_angle_cls: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.lang = _LANG_MAP.get(lang.lower(), lang)
        self.use_angle_cls = use_angle_cls
        self._ocr = None

    def _get(self):
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR as _PaddleOCR
            except ImportError as e:
                raise EngineLoadError(
                    "PaddleOCR 未安装: pip install paddleocr"
                ) from e
            try:
                # PaddleOCR 2.x 风格参数
                self._ocr = _PaddleOCR(
                    use_angle_cls=self.use_angle_cls,
                    lang=self.lang,
                    show_log=False,
                )
            except (TypeError, ValueError):
                # PaddleOCR 3.x: 移除 show_log/use_angle_cls
                # 关闭 MKLDNN(paddlepaddle 3.3.x oneDNN bug) + 文档矫正/展平
                # (这两个预处理会返回变换后坐标, 破坏蒙版/渲染对齐)
                self._ocr = _PaddleOCR(
                    lang=self.lang,
                    enable_mkldnn=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                )
        return self._ocr

    def run(self, page: Page) -> List[TextRegion]:
        ocr = self._get()
        # PaddleOCR 只接受 3 通道 RGB（RGBA/灰度/调色板图一律转 RGB）
        img = page.image
        if img.mode != "RGB":
            img = img.convert("RGB")
        arr = np.asarray(img)
        try:
            if hasattr(ocr, "predict"):
                # ---- PaddleOCR 3.x: predict() ----
                results = ocr.predict(arr)
                regions = self._parse_v3(results)
            else:
                # ---- PaddleOCR 2.x: ocr() ----
                result = ocr.ocr(arr, cls=self.use_angle_cls)
                regions = self._parse_v2(result)
        except OCRError:
            raise
        except Exception as e:
            raise OCRError(f"PaddleOCR 识别失败: {e}") from e
        return regions

    @staticmethod
    def _parse_v2(result) -> List[TextRegion]:
        """2.x: result[0] = [[poly, (text, conf)], ...]"""
        regions: List[TextRegion] = []
        lines = (result[0] or []) if result else []
        for line in lines:
            poly, (text, conf) = line
            regions.append(
                TextRegion(
                    polygon=[(float(p[0]), float(p[1])) for p in poly],
                    text=str(text),
                    conf=float(conf),
                )
            )
        return regions

    @staticmethod
    def _parse_v3(results) -> List[TextRegion]:
        """3.x: OCRResult 是 dict 子类（键名跨版本略有差异），防御性读取。"""
        regions: List[TextRegion] = []
        for res in results:
            if isinstance(res, dict):
                texts = res.get("texts") or res.get("rec_texts") or []
                scores = res.get("scores") or res.get("rec_scores") or res.get("dt_scores") or []
                boxes = res.get("boxes") or res.get("dt_polys")
            else:
                texts = getattr(res, "texts", None) or getattr(res, "rec_texts", None) or []
                scores = getattr(res, "scores", None) or getattr(res, "rec_scores", None) or getattr(res, "dt_scores", None) or []
                boxes = getattr(res, "boxes", None) or getattr(res, "dt_polys", None)
            if boxes is None:
                continue
            polys = boxes.tolist() if hasattr(boxes, "tolist") else boxes
            for i, poly in enumerate(polys):
                conf = float(scores[i]) if i < len(scores) else 0.0
                regions.append(
                    TextRegion(
                        polygon=[(float(p[0]), float(p[1])) for p in poly],
                        text=str(texts[i]) if i < len(texts) else "",
                        conf=conf,
                    )
                )
        return regions

    # 一体化引擎：detect == run
    def detect(self, page: Page) -> List[TextRegion]:
        return self.run(page)
