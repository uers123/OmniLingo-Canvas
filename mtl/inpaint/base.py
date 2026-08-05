"""图像修复引擎抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseInpainter(ABC):
    name = "base"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @abstractmethod
    def inpaint(self, image, mask, prompt: str = "", negative: str = ""):
        """image/mask 为 PIL.Image，返回修复后的 PIL.Image。"""
