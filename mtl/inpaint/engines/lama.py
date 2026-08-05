"""Lama-cleaner 适配器（HTTP API, multipart/form-data）。

lama-cleaner 是本地部署的图像修复服务，适合大面积背景补全与
黑白漫画网点纹理对齐。依赖外部服务:
    pip install lama-cleaner
    lama-cleaner --model lama --device cuda --port 7860

⚠️ 无审查模式下自动切换至 local_llm（本引擎不接受 uncensored=True）。
"""

from __future__ import annotations

import io

from ...errors import EngineLoadError, InpaintError
from ...registry import register
from ..base import BaseInpainter

# lama-cleaner /inpaint 接口要求的全部表单字段(Config 全量, 取安全默认值)
_FORM_DEFAULTS = {
    "ldmSteps": "20",
    "ldmSampler": "plms",
    "hdStrategy": "Original",       # 全分辨率修复; 大图可用 Resize
    "zitsWireframe": "false",
    "hdStrategyCropMargin": "128",
    "hdStrategyCropTrigerSize": "2048",
    "hdStrategyResizeLimit": "2048",
    "prompt": "",
    "negativePrompt": "",
    "useCroper": "false",
    "croperX": "0",
    "croperY": "0",
    "croperHeight": "0",
    "croperWidth": "0",
    "sdScale": "1.0",
    "sdMaskBlur": "0",
    "sdStrength": "0.75",
    "sdSteps": "30",
    "sdGuidanceScale": "7.5",
    "sdSampler": "uni_pc",
    "sdSeed": "-1",
    "sdMatchHistograms": "false",
    "cv2Flag": "INPAINT_NS",
    "cv2Radius": "4",
    "paintByExampleSteps": "50",
    "paintByExampleGuidanceScale": "7.5",
    "paintByExampleMaskBlur": "0",
    "paintByExampleSeed": "-1",
    "paintByExampleMatchHistograms": "false",
    "p2pSteps": "50",
    "p2pImageGuidanceScale": "1.5",
    "p2pGuidanceScale": "7.5",
    "controlnet_conditioning_scale": "0.4",
    "controlnet_method": "control_v11p_sd15_canny",
}


@register("inpaint", "lama")
class LamaCleaner(BaseInpainter):
    name = "lama"

    def __init__(self, base_url: str = "http://127.0.0.1:7860",
                 model: str = "lama", hd_strategy: str = "Original",
                 resize_limit: int = 2048, **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.hd_strategy = hd_strategy
        self.resize_limit = int(resize_limit)

    def inpaint(self, image, mask, prompt: str = "", negative: str = ""):
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e

        def _png_bytes(img) -> bytes:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        form = dict(_FORM_DEFAULTS)
        form["prompt"] = prompt
        form["negativePrompt"] = negative
        form["hdStrategy"] = self.hd_strategy
        if self.hd_strategy == "Resize":
            form["hdStrategyResizeLimit"] = str(self.resize_limit)

        files = {
            "image": ("image.png", _png_bytes(image.convert("RGB")), "image/png"),
            "mask": ("mask.png", _png_bytes(mask.convert("L")), "image/png"),
        }
        try:
            resp = requests.post(
                f"{self.base_url}/inpaint", data=form, files=files, timeout=600,
            )
            resp.raise_for_status()
            from PIL import Image
            return Image.open(io.BytesIO(resp.content)).convert(
                image.mode if image.mode != "P" else "RGB"
            )
        except Exception as e:
            raise InpaintError(f"Lama-cleaner 调用失败（{self.base_url}）: {e}") from e
