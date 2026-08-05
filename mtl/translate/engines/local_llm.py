"""本地 LLM 翻译引擎：Ollama / llama.cpp server。

Uncensored_Mode 的核心引擎：
- 加载 UNCENSORED_SYSTEM 系统提示词，原汁原味直译受限内容
- uncensored=True 时可切换专用无审查模型（uncensored_model）
- 数据不出本机，不经过任何云端审查
"""

from __future__ import annotations

import json
from typing import List, Optional

from ...errors import EngineLoadError, TranslationError
from ...models import TranslateItem, Translation
from ...registry import register
from ..base import BaseTranslator
from ..prompts import TASK_PROMPTS, UNCENSORED_SYSTEM
from .openai import parse_translation_json


@register("translate", "local_llm")
class LocalLLMTranslator(BaseTranslator):
    name = "local_llm"

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen2.5:14b", target_lang: str = "zh-CN",
                 temperature: float = 0.3, api_type: str = "ollama",
                 uncensored: bool = False, uncensored_model: Optional[str] = None,
                 timeout: int = 120, **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.target_lang = target_lang
        self.temperature = temperature
        self.api_type = api_type
        self.uncensored = uncensored
        self.uncensored_model = uncensored_model
        self.timeout = timeout

    def _effective_model(self) -> str:
        if self.uncensored and self.uncensored_model:
            return self.uncensored_model
        return self.model

    def translate(self, items, context="", glossary=None, task_type="manga"):
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

        system = UNCENSORED_SYSTEM if self.uncensored else (
            "你是专业的本地化翻译引擎。仅输出结果，不解释。"
        )

        # ---- 请求 + 覆盖率重试（LLM 偶发合并/漏条时自动补译） ----
        by_id: dict = {}
        remaining = payload_list
        for attempt in range(2):
            if not remaining:
                break
            hint = (
                "\n\n注意：上次输出遗漏/合并了部分条目，请补译以下条目，"
                "每条独立对象，严禁合并：\n"
                if attempt > 0 else ""
            )
            user_msg2 = (
                f"{prompt}{glossary_block}{context_block}{hint}\n\n"
                f"待翻译文本：\n{json.dumps(remaining, ensure_ascii=False)}"
            )
            content = self._chat(system, user_msg2)
            parsed = parse_translation_json(content)
            for d in parsed:
                if "id" in d and d.get("text"):
                    by_id[d["id"]] = d["text"]
            # 复读检测: 译文与原文本相同视为未翻译(触发重试)
            for p in remaining:
                src = p["text"].strip()
                tgt = (by_id.get(p["id"]) or "").strip()
                if len(src) >= 2 and src == tgt:
                    by_id.pop(p["id"], None)
            remaining = [
                p for p in remaining if p["id"] not in by_id
            ]

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

    def _chat(self, system: str, user_msg: str) -> str:
        """调用 Ollama / llama.cpp 并返回回复文本。"""
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e
        try:
            if self.api_type == "llama_cpp":
                resp = requests.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self._effective_model(),
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": self.temperature,
                        "stream": False,
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            # ollama
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self._effective_model(),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "stream": False,
                    "options": {"temperature": self.temperature},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as e:
            raise TranslationError(
                f"本地 LLM 调用失败（{self.base_url}, model={self._effective_model()}）: {e}"
            ) from e
