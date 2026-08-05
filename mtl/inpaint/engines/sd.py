"""Stable Diffusion (AUTOMATIC1111 WebUI) img2img inpaint 适配器。

用于全彩插画/复杂背景的高质量补绘，配合 ControlNet 可对齐结构。

bypass_safety 说明：
- SD 推理本身不做内容审查；A1111 的 safety_checker 仅影响 NSFW 预览图。
- 如需彻底无审查，请启动时使用无审查社区模型（如 SD 1.5 的 unbound 系
  checkpoint / 指定 negative embedding），并关闭 WebUI 的 NSFW 过滤选项。
- 本适配器通过 bypass_safety 配置明确跳过任何过滤逻辑。

启动示例:
    webui.bat --api --medvram --no-half
"""

from __future__ import annotations

import base64
import io

from ...errors import EngineLoadError, InpaintError
from ...registry import register
from ..base import BaseInpainter


@register("inpaint", "sd")
class SDInpainter(BaseInpainter):
    name = "sd"

    def __init__(self, base_url: str = "http://127.0.0.1:7861",
                 bypass_safety: bool = True, steps: int = 28,
                 cfg_scale: float = 7.0, denoising: float = 1.0,
                 width: int = 512, height: int = 512, **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.bypass_safety = bypass_safety
        self.steps = steps
        self.cfg_scale = cfg_scale
        self.denoising = denoising
        self.width = width
        self.height = height

    def inpaint(self, image, mask, prompt: str = "", negative: str = ""):
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e

        def _b64(img) -> str:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

        # 分块处理: 将大图按 512/1024 块切片，逐块 inpaint 再拼接
        # （v0.1 先实现整图缩放处理；分块拼接后续版本补充）
        payload = {
            "init_images": [_b64(image)],
            "mask": _b64(mask.convert("L")),
            "inpaint_full_res": True,
            "inpaint_full_res_padding": 32,
            "denoising_strength": self.denoising,
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "prompt": prompt,
            "negative_prompt": negative,
            "width": min(self.width, image.width),
            "height": min(self.height, image.height),
            "sampler_name": "DPM++ 2M Karras",
            "send_images": True,
            "save_images": False,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/sdapi/v1/img2img",
                json=payload,
                timeout=1200,
            )
            resp.raise_for_status()
            data = resp.json()
            img_b64 = data["images"][0]
        except Exception as e:
            raise InpaintError(f"SD WebUI 调用失败（{self.base_url}）: {e}") from e

        from PIL import Image
        result = Image.open(io.BytesIO(base64.b64decode(img_b64.split(",", 1)[-1])))
        # 恢复原始尺寸（WebUI 输出可能与输入不同）
        if result.size != image.size:
            result = result.resize(image.size, Image.LANCZOS)
        return result.convert("RGB")
