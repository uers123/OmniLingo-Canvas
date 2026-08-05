"""特效渲染：描边、阴影、半透明度、文字图层导出。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from ..models import PageResult, TextRegion, Translation


def render_text_effects(
    base: Image.Image,
    box: Tuple[float, float, float, float],
    lines: List[str],
    font,
    fill: Tuple[int, int, int, int] = (0, 0, 0, 255),
    stroke: Tuple[int, int, int, int] = (255, 255, 255, 255),
    stroke_width: int = 0,
    shadow: Optional[Dict] = None,
    alpha: float = 1.0,
    line_ratio: float = 1.35,
) -> Image.Image:
    """在 base 上绘制带特效的文字（RGBA 合成）。

    shadow: {"enabled": bool, "offset": [dx, dy], "alpha": float}
    """
    base = base.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    x, y = int(box[0]), int(box[1])
    line_h = int(font.size * line_ratio)
    text_block = "\n".join(lines)

    if shadow and shadow.get("enabled"):
        dx, dy = shadow.get("offset", (2, 2))
        sh_alpha = int(255 * float(shadow.get("alpha", 0.5)))
        d.text(
            (x + int(dx), y + int(dy)), text_block, font=font,
            fill=(0, 0, 0, sh_alpha),
            stroke_width=stroke_width, stroke_fill=(0, 0, 0, sh_alpha),
        )

    fill_a = (fill[0], fill[1], fill[2], int(255 * alpha))
    d.text((x, y), text_block, font=font, fill=fill_a,
           stroke_width=stroke_width, stroke_fill=stroke)
    return Image.alpha_composite(base, overlay)


def render_text_layer(
    size: Tuple[int, int], result: PageResult, registry=None
) -> Optional[Image.Image]:
    """生成透明背景文字图层（可拖入 Photoshop 精修）。"""
    if not result.translations:
        return None
    if registry is None:
        from .fonts import FontRegistry
        registry = FontRegistry()

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    tmap: Dict[int, Translation] = {t.region_index: t for t in result.translations}
    for r in result.page.regions:
        tr = tmap.get(r.index)
        if tr is None or not tr.translated_text:
            continue
        from .layout import fit_font_size
        size_fit, lines = fit_font_size(
            tr.translated_text, r.bbox, registry,
            script="zh", style="regular",
        )
        if size_fit is None:
            continue
        font = registry.load("zh", "regular", size_fit)
        layer = render_text_effects(
            layer, r.bbox, lines, font,
            fill=(0, 0, 0, 255), stroke=(255, 255, 255, 255),
            stroke_width=max(1, size_fit // 12),
            shadow={"enabled": False}, alpha=1.0,
        )
    return layer
