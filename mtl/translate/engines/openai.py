"""OpenAI 兼容 API 翻译适配器（Chat Completions）。

支持任意 OpenAI 兼容端点（OpenAI / DeepSeek / 硅基流动 / vLLM 等）。
⚠️ 无审查模式下管道会自动切换至 local_llm（本引擎不接受 uncensored=True）。
"""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from ...errors import EngineLoadError, TranslationError
from ...models import TranslateItem, Translation
from ...registry import register
from ..base import BaseTranslator
from ..prompts import TASK_PROMPTS

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
# 逐对象提取: 容忍缺失闭合括号/尾部垃圾等 LLM 常见输出瑕疵
_OBJ_RE = re.compile(
    r'\{"id"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"'
)


def parse_translation_json(text: str) -> List[dict]:
    """鲁棒解析 LLM 输出的 JSON 数组。

    策略: 1) 完整数组 + 尾部容忍截断; 2) 失败则逐对象正则提取。
    """
    m = _JSON_ARRAY_RE.search(text)
    if m:
        s = m.group(0)
        # 尾部容忍: 最多裁掉 40 字符重试（处理 `]}` 之类多余/缺失括号）
        for end in range(len(s), max(len(s) - 40, 0) - 1, -1):
            try:
                data = json.loads(s[:end])
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue
            except (ValueError, TypeError):
                continue
    # 逐对象提取
    out = []
    for mo in _OBJ_RE.finditer(text):
        try:
            raw = mo.group(2)
            out.append({"id": int(mo.group(1)), "text": json.loads('"' + raw + '"')})
        except (ValueError, json.JSONDecodeError):
            out.append({"id": int(mo.group(1)), "text": raw})
    return out


@register("translate", "openai")
class OpenAITranslator(BaseTranslator):
    name = "openai"

    def __init__(self, base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY",
                 model: str = "gpt-4o-mini", target_lang: str = "zh-CN",
                 temperature: float = 0.3, uncensored: bool = False,
                 timeout: int = 120, **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.model = model
        self.target_lang = target_lang
        self.temperature = temperature
        self.uncensored = uncensored
        self.timeout = timeout

    def translate(self, items, context="", glossary=None, task_type="manga"):
        if self.uncensored:
            raise TranslationError(
                "OpenAI 引擎不适用于 Uncensored_Mode；"
                "管道已强制切换 local_llm，若仍走到此处请检查配置"
            )
        if not self.api_key:
            raise EngineLoadError(f"OpenAI 需要设置环境变量 OPENAI_API_KEY")
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e

        payload_list = [
            {"id": i.region_index, "text": i.text, "kind": i.kind}
            for i in items if i.text.strip()
        ]
        if not payload_list:
            return []
        prompt = TASK_PROMPTS.get(task_type, TASK_PROMPTS["manga"]).format(
            target_lang=self.target_lang
        )
        glossary_block = ""
        if glossary and glossary.entries:
            glossary_block = (
                "\n术语表（必须遵守，命中即用目标词替换）：\n"
                + "\n".join(f"{s} -> {t}" for s, t, _ in glossary.entries)
            )
        context_block = f"\n\n前文背景（保持人物/专有名词一致）：\n{context}" if context else ""
        user_msg = (
            f"{prompt}{glossary_block}{context_block}\n\n"
            f"待翻译文本：\n{json.dumps(payload_list, ensure_ascii=False)}"
        )
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": self.temperature,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise TranslationError(f"OpenAI 兼容 API 调用失败: {e}") from e

        parsed = parse_translation_json(content)
        by_id = {d["id"]: d["text"] for d in parsed if "id" in d}
        out: List[Translation] = []
        for item in items:
            if item.text.strip():
                out.append(Translation(
                    region_index=item.region_index,
                    source_text=item.text,
                    translated_text=by_id.get(item.region_index, ""),
                    glossary_hits=glossary.lookup(item.text) if glossary else [],
                ))
            else:
                out.append(Translation(
                    region_index=item.region_index, source_text=item.text,
                    translated_text="",
                ))
        return out
