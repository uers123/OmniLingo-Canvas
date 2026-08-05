"""超分辨率预处理接口（可选）。

内置 NoopSR（不处理）。REAL-ESRGAN 通过本地 API 挂载时实现 UpscaleSR。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..errors import EngineLoadError


class BaseSR(ABC):
    name = "base"

    @abstractmethod
    def upscale(self, image, scale: int = 2):
        """返回放大后的 PIL.Image。"""


class NoopSR(BaseSR):
    name = "none"

    def upscale(self, image, scale: int = 2):
        return image


class RealESRGANSR(BaseSR):
    """REAL-ESRGAN 本地 API 适配（如 realesrgan-webui / stable-diffusion 同源服务）。

    依赖外部服务: pip install realesrgan 后以 webui 方式启动，
    或直接使用 `realesrgan-ncnn-vulkan` 命令行。
    """

    name = "realesrgan"

    def __init__(self, base_url: Optional[str] = None, **kwargs):
        self.base_url = base_url

    def upscale(self, image, scale: int = 2):
        if not self.base_url:
            raise EngineLoadError(
                "RealESRGAN 需要配置 base_url (本地服务地址)；"
                "或改用 none 引擎"
            )
        import base64
        import io

        import requests

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        resp = requests.post(
            f"{self.base_url.rstrip('/')}/upscale",
            json={"image": base64.b64encode(buf.getvalue()).decode(), "scale": scale},
            timeout=600,
        )
        resp.raise_for_status()
        from PIL import Image

        return Image.open(io.BytesIO(base64.b64decode(resp.json()["image"])))


def create_sr(cfg) -> BaseSR:
    engine = cfg.get("engine", "none")
    if engine == "none":
        return NoopSR()
    if engine == "realesrgan":
        return RealESRGANSR(**cfg.get("kwargs", {}))
    raise EngineLoadError(f"未支持的 superres 引擎: {engine}")
