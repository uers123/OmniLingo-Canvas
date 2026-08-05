"""术语词典（Glossary）：加载、命中检测与替换。

支持格式：
- CSV:  source,target[,kind]     kind=ci 表示忽略大小写
- JSON: [{"source": "...", "target": "...", "kind": "ci"}]
"""

from __future__ import annotations

import csv
import json
import os
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..errors import ConfigError


def _norm(text: str) -> str:
    """规范化：NFC + 去除首尾空白 + 折叠大小写用于 ci 匹配。"""
    return unicodedata.normalize("NFC", text.strip())


@dataclass
class Glossary:
    entries: List[Tuple[str, str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Optional[str]) -> Optional["Glossary"]:
        if not path:
            return None
        if not os.path.exists(path):
            raise ConfigError(f"术语词典不存在: {path}")
        entries: List[Tuple[str, str, str]] = []
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.reader(f):
                    if not row or not row[0].strip():
                        continue
                    src, tgt = row[0].strip(), (row[1] if len(row) > 1 else "").strip()
                    kind = (row[2] if len(row) > 2 else "").strip().lower()
                    if src and tgt:
                        entries.append((src, tgt, kind))
        elif ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                src = str(item.get("source", "")).strip()
                tgt = str(item.get("target", "")).strip()
                if src and tgt:
                    entries.append((src, tgt, str(item.get("kind", "")).lower()))
        else:
            raise ConfigError(f"不支持的术语词典格式: {ext} (支持 csv/json)")
        # 长词优先，避免短词先替换导致长词失效
        entries.sort(key=lambda e: len(e[0]), reverse=True)
        return cls(entries=entries)

    def lookup(self, text: str) -> List[str]:
        """返回命中的目标词列表。"""
        hits = []
        t = _norm(text)
        for src, tgt, kind in self.entries:
            needle = _norm(src)
            if kind == "ci":
                if needle.lower() in t.lower():
                    hits.append(tgt)
            else:
                if needle in t:
                    hits.append(tgt)
        return hits

    def apply(self, text: str) -> str:
        """按词典逐条替换（长词优先，ci 条目忽略大小写）。"""
        out = text
        for src, tgt, kind in self.entries:
            needle = _norm(src)
            if not needle:
                continue
            if kind == "ci":
                # 逐段忽略大小写替换
                lower, nlower = out, needle.lower()
                idx = lower.find(nlower)
                while idx != -1:
                    out = out[:idx] + tgt + out[idx + len(needle):]
                    lower = out.lower()
                    idx = lower.find(nlower, idx + len(tgt))
            else:
                out = out.replace(needle, tgt)
        return out
