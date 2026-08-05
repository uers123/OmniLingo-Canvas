"""自适应排版：自动换行 + 字号搜索，保证译文不溢出原文框。"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .fonts import FontRegistry


def wrap_text(text: str, font, max_width: float, vertical: bool = False) -> List[str]:
    """按宽度换行。

    - 竖排（vertical=True）：逐字成行（日韩竖排习惯）
    - 横排：CJK 逐字累积，拉丁文本按词断行（以空格为断点）
    """
    if vertical:
        return [ch for ch in text if ch.strip()] or [text]
    lines: List[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        if font.getlength(trial) <= max_width or not cur:
            cur = trial
        else:
            # 拉丁文本回退到最后一个空格断行
            sp = cur.rfind(" ")
            if sp > 0:
                lines.append(cur[:sp])
                cur = cur[sp + 1:] + ch
            else:
                lines.append(cur)
                cur = ch
    if cur:
        lines.append(cur)
    return lines


def fit_font_size(
    text: str,
    box: Tuple[float, float, float, float],
    registry: FontRegistry,
    script: str,
    style: str = "regular",
    min_size: int = 8,
    max_size: int = 200,
    line_ratio: float = 1.35,
    max_fill_ratio: float = 0.95,
    vertical: bool = False,
) -> Tuple[Optional[int], List[str]]:
    """二分搜索最大可用字号，返回 (font_size, lines)。

    约束：每行宽度 <= box 宽，总行高 <= box 高（受 max_fill_ratio 控制）。
    """
    x0, y0, x1, y1 = box
    box_w = (x1 - x0) * max_fill_ratio
    box_h = (y1 - y0) * max_fill_ratio
    if box_w <= 0 or box_h <= 0:
        return None, []

    lo, hi = min_size, max_size
    best_size, best_lines = None, []
    while lo <= hi:
        mid = (lo + hi) // 2
        font = registry.load(script, style, mid)
        lines = wrap_text(text, font, box_w, vertical=vertical)
        total_h = len(lines) * mid * line_ratio
        if total_h <= box_h:
            best_size, best_lines = mid, lines
            lo = mid + 1
        else:
            hi = mid - 1
    if best_size is None:
        # 最小字号也放不下：用最小字号并截断到框内能放的行数
        font = registry.load(script, style, min_size)
        lines = wrap_text(text, font, box_w, vertical=vertical)
        max_lines = max(1, int(box_h // (min_size * line_ratio)))
        return min_size, lines[:max_lines]
    return best_size, best_lines
