"""OCR 噪声过滤：水印 / 页码 / 画面杂物启发式。"""

from __future__ import annotations

import re
from typing import Dict, List

from ..models import TextRegion

_LATIN_RE = re.compile(r"^[A-Za-z0-9]+$")
_VOWELS = set("aeiouAEIOU")


def filter_regions(
    regions: List[TextRegion],
    cfg: Dict,
) -> List[TextRegion]:
    """按配置过滤噪声区域。cfg 来自 ocr.noise_filter 段。"""
    min_len = int(cfg.get("min_len", 2))
    drop_pure_digits = bool(cfg.get("drop_pure_digits", True))
    drop_latin_short = bool(cfg.get("drop_latin_short", True))
    drop_vowelless = bool(cfg.get("drop_latin_vowelless", True))
    blacklist = set(str(x).lower() for x in cfg.get("blacklist", []))

    out: List[TextRegion] = []
    for r in regions:
        text = r.text.strip()
        if not text:
            continue
        low = text.lower()

        if low in blacklist:
            continue

        # 纯数字: 页码/编号
        if drop_pure_digits and text.isdigit():
            continue

        # 拉丁/ASCII 串
        if _LATIN_RE.match(text):
            if drop_latin_short and len(text) <= 3:
                continue
            if drop_vowelless and not any(c in _VOWELS for c in text):
                continue

        # 长度过滤(含假名/汉字)
        if len(text) < min_len:
            continue

        out.append(r)
    return out
