"""智能蒙版生成：多边形填充 + 像素膨胀 + 羽化。"""

from __future__ import annotations

from typing import Iterable, Tuple

from PIL import Image, ImageDraw, ImageFilter

from ..models import TextRegion


def build_mask(
    size: Tuple[int, int],
    regions: Iterable[TextRegion],
    dilation_px: int = 4,
    feather: int = 2,
) -> Image.Image:
    """根据文本区域生成 L 模式蒙版。

    dilation_px: 膨胀半径（像素），避免擦除后边缘残留文本像素
    feather: 羽化半径（高斯模糊），让修复边界自然过渡
    """
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for r in regions:
        if len(r.polygon) < 3:
            continue
        pts = [(int(x), int(y)) for x, y in r.polygon]
        draw.polygon(pts, fill=255)

    if dilation_px > 0:
        k = max(3, dilation_px * 2 + 1)
        mask = mask.filter(ImageFilter.MaxFilter(k))
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask


def composite_mask(
    size: Tuple[int, int], masks: Iterable[Image.Image]
) -> Image.Image:
    """合并多张蒙版（取并集）。"""
    base = Image.new("L", size, 0)
    for m in masks:
        base = Image.composite(m, base, m)
    return base
