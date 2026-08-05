"""云端 OCR 适配器：Google Vision / 百度 OCR。

⚠️ 无审查模式下管道会自动禁用本引擎（云端服务含内容审查）。
"""

from __future__ import annotations

import base64
import os
from typing import List

from ...errors import EngineLoadError, OCRError
from ...models import Page, TextRegion
from ...registry import register
from ..base import BaseOCR

_BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_BAIDU_OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"
_GOOGLE_URL = "https://vision.googleapis.com/v1/images:annotate"


@register("ocr", "google_vision")
class GoogleVisionOCR(BaseOCR):
    name = "google_vision"

    def __init__(self, api_key_env: str = "GOOGLE_VISION_API_KEY",
                 lang: str = "ja", **kwargs):
        super().__init__(**kwargs)
        self.api_key = os.environ.get(api_key_env, "")
        self.lang = lang

    def detect(self, page: Page) -> List[TextRegion]:
        if not self.api_key:
            raise EngineLoadError(
                f"Google Vision 需要设置环境变量 {self._key_name()}"
            )
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e

        import io
        buf = io.BytesIO()
        page.image.save(buf, format="PNG")
        body = {
            "requests": [{
                "image": {"content": base64.b64encode(buf.getvalue()).decode()},
                "features": [{"type": "TEXT_DETECTION"}],
                "imageContext": {"languageHints": [self.lang]},
            }]
        }
        try:
            resp = requests.post(
                f"{_GOOGLE_URL}?key={self.api_key}", json=body, timeout=60
            )
            resp.raise_for_status()
            annotations = resp.json()["responses"][0].get("textAnnotations", [])
        except Exception as e:
            raise OCRError(f"Google Vision 调用失败: {e}") from e

        regions: List[TextRegion] = []
        for ann in annotations[1:]:  # 第一条是全页聚合文本
            verts = ann["boundingPoly"]["vertices"]
            poly = [(float(v["x"]), float(v["y"])) for v in verts]
            regions.append(
                TextRegion(polygon=poly, text=ann["description"], conf=1.0, lang=self.lang)
            )
        return regions

    def _key_name(self):
        return "GOOGLE_VISION_API_KEY"


@register("ocr", "baidu")
class BaiduOCR(BaseOCR):
    name = "baidu"

    def __init__(self, api_key_env: str = "BAIDU_OCR_API_KEY",
                 secret_env: str = "BAIDU_OCR_SECRET",
                 lang: str = "JAP", **kwargs):
        super().__init__(**kwargs)
        self.api_key = os.environ.get(api_key_env, "")
        self.secret = os.environ.get(secret_env, "")
        self.lang = lang
        self._token = None

    def _get_token(self):
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e
        if not (self.api_key and self.secret):
            raise EngineLoadError("百度 OCR 需要设置 BAIDU_OCR_API_KEY 与 BAIDU_OCR_SECRET")
        if self._token is None:
            r = requests.post(
                _BAIDU_TOKEN_URL,
                params={
                    "grant_type": "client_credentials",
                    "client_id": self.api_key,
                    "client_secret": self.secret,
                },
                timeout=30,
            )
            r.raise_for_status()
            self._token = r.json().get("access_token")
        return self._token

    def detect(self, page: Page) -> List[TextRegion]:
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e
        import io
        buf = io.BytesIO()
        page.image.save(buf, format="PNG")
        try:
            resp = requests.post(
                f"{_BAIDU_OCR_URL}?access_token={self._get_token()}",
                data={"image": base64.b64encode(buf.getvalue()).decode(),
                      "language_type": self.lang},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("error_code"):
                raise OCRError(f"百度 OCR 错误: {data.get('error_msg')}")
            items = data.get("words_result", [])
        except OCRError:
            raise
        except Exception as e:
            raise OCRError(f"百度 OCR 调用失败: {e}") from e

        regions: List[TextRegion] = []
        for it in items:
            loc = it.get("location", {})
            x0, y0 = loc.get("left", 0), loc.get("top", 0)
            w, h = loc.get("width", 0), loc.get("height", 0)
            regions.append(
                TextRegion(
                    polygon=[(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)],
                    text=it.get("words", ""),
                    conf=1.0,
                    lang=self.lang,
                )
            )
        return regions
