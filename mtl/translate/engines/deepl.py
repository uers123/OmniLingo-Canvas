"""DeepL API 适配器（云端常规翻译）。

⚠️ 无审查模式下管道会自动切换至 local_llm。
依赖: pip install requests；环境变量 DEEPL_API_KEY（:fx 结尾为免费版）。
"""

from __future__ import annotations

import os
from typing import List, Optional

from ...errors import EngineLoadError, TranslationError
from ...models import TranslateItem, Translation
from ...registry import register
from ..base import BaseTranslator

_FREE_URL = "https://api-free.deepl.com/v2/translate"
_PRO_URL = "https://api.deepl.com/v2/translate"


@register("translate", "deepl")
class DeepLTranslator(BaseTranslator):
    name = "deepl"

    def __init__(self, api_key_env: str = "DEEPL_API_KEY",
                 target_lang: str = "ZH", **kwargs):
        super().__init__(**kwargs)
        self.api_key = os.environ.get(api_key_env, "")
        self.target_lang = target_lang

    def translate(self, items, context="", glossary=None, task_type="manga"):
        if not self.api_key:
            raise EngineLoadError("DeepL 需要设置环境变量 DEEPL_API_KEY")
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e

        texts = [i.text for i in items if i.text.strip()]
        if not texts:
            return []
        url = _FREE_URL if self.api_key.endswith(":fx") else _PRO_URL
        try:
            resp = requests.post(
                url,
                data={
                    "auth_key": self.api_key,
                    "target_lang": self.target_lang,
                    "text": texts,  # 列表 -> 重复表单键, DeepL 批量
                },
                timeout=60,
            )
            resp.raise_for_status()
            translated = [t["text"] for t in resp.json()["translations"]]
        except Exception as e:
            raise TranslationError(f"DeepL 调用失败: {e}") from e

        out: List[Translation] = []
        ti = 0
        for item in items:
            if item.text.strip():
                out.append(Translation(
                    region_index=item.region_index,
                    source_text=item.text,
                    translated_text=translated[ti],
                    glossary_hits=glossary.lookup(item.text) if glossary else [],
                ))
                ti += 1
            else:
                out.append(Translation(
                    region_index=item.region_index,
                    source_text=item.text,
                    translated_text="",
                ))
        return out
