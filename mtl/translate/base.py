"""翻译引擎抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import TranslateItem, Translation


class BaseTranslator(ABC):
    name = "base"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @abstractmethod
    def translate(
        self,
        items: List[TranslateItem],
        context: str = "",
        glossary: Optional["Glossary"] = None,
        task_type: str = "manga",
    ) -> List[Translation]:
        """批量翻译。返回与 items 一一对应的 Translation 列表。"""
