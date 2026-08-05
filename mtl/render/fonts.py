"""字体库：按语种/风格加载字体，自动探测系统字体兜底。"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from PIL import ImageFont

# Windows / macOS / Linux 常见中英文字体候选（按优先级）
_SYSTEM_FONTS: Dict[str, Tuple[str, ...]] = {
    "zh": (
        r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",    # 微软雅黑 Bold
        r"C:\Windows\Fonts\simhei.ttf",    # 黑体
        r"C:\Windows\Fonts\simsun.ttc",    # 宋体
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ),
    "en": (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
}

_STYLE_HINTS: Dict[str, Tuple[str, ...]] = {
    "bold": ("msyhbd", "simhei", "arialbd", "Bold", "PingFang Bold"),
    "handwriting": ("simkai", "楷体", "kaiti", "Comic", "hand"),
}


def _find_system_font(script: str, style: str) -> Optional[str]:
    hints = _STYLE_HINTS.get(style, ())
    candidates = _SYSTEM_FONTS.get(script, ()) + _SYSTEM_FONTS.get("zh", ())
    for c in candidates:
        if not os.path.exists(c):
            continue
        low = os.path.basename(c).lower()
        if style == "bold" and not any(h.lower() in low for h in hints):
            continue
        return c
    # 无风格约束时返回第一个存在的
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


class FontRegistry:
    """按 (script, style) -> 字体路径 的注册表；未配置时探测系统字体。"""

    def __init__(self, fonts_cfg: Optional[Dict] = None):
        self._configured: Dict[str, Dict[str, str]] = fonts_cfg or {}
        self._cache: Dict[Tuple[str, str, int], ImageFont.FreeTypeFont] = {}

    def resolve_path(self, script: str, style: str = "regular") -> Optional[str]:
        script_cfg = self._configured.get(script) or self._configured.get(
            "zh"
        ) or {}
        p = script_cfg.get(style) or script_cfg.get("regular")
        if p and os.path.exists(p):
            return p
        return _find_system_font(script, style)

    def load(self, script: str, style: str, size: int) -> ImageFont.FreeTypeFont:
        key = (script, style, size)
        if key in self._cache:
            return self._cache[key]
        path = self.resolve_path(script, style)
        if path:
            font = ImageFont.truetype(path, size=size)
        else:
            # Pillow >= 10 支持 load_default(size=)
            try:
                font = ImageFont.load_default(size=size)
            except TypeError:
                font = ImageFont.load_default()
        self._cache[key] = font
        return font
