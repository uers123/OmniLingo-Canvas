"""全链路输出：成品图、对照 JSON、透明文字图层、蒙版。"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from ..models import PageResult, TextRegion, Translation


def build_sidecar(result: PageResult) -> Dict:
    """生成中英/中日对照 + 区域坐标 + 置信度的 JSON 结构。"""
    tmap: Dict[int, Translation] = {
        t.region_index: t for t in result.translations
    }
    regions: List[Dict] = []
    for r in result.page.regions:
        d = r.to_dict()
        tr = tmap.get(r.index)
        d["translated"] = tr.translated_text if tr else ""
        d["glossary_hits"] = tr.glossary_hits if tr else []
        regions.append(d)
    return {
        "page_index": result.page.page_index,
        "source": result.page.path,
        "kind": result.page.kind,
        "width": result.page.width,
        "height": result.page.height,
        "source_lang": result.page.source_lang,
        "regions": regions,
        "meta": result.meta,
    }


def export_result(
    result: PageResult,
    out_dir: str,
    formats=("png", "json"),
    save_layers: bool = True,
    save_masks: bool = False,
    quality: int = 95,
) -> List[str]:
    """导出单页产物，返回写出文件路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    page_dir = os.path.join(out_dir, f"page_{result.page.page_index:04d}")
    os.makedirs(page_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(result.page.path) or "page")[0]

    final = result.final_image
    if final is not None:
        for fmt in formats:
            if fmt == "png":
                p = os.path.join(page_dir, f"{base}.final.png")
                final.save(p)
            elif fmt == "jpeg":
                p = os.path.join(page_dir, f"{base}.final.jpg")
                final.convert("RGB").save(p, quality=quality)
            elif fmt == "json":
                continue
            else:
                continue
            written.append(p)

    if "json" in formats:
        p = os.path.join(page_dir, f"{base}.data.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(build_sidecar(result), f, ensure_ascii=False, indent=2)
        written.append(p)

    if save_layers and final is not None and result.translations:
        layers_dir = os.path.join(page_dir, "layers")
        os.makedirs(layers_dir, exist_ok=True)
        from ..render.effects import render_text_layer
        layer = render_text_layer(final.size, result)
        if layer is not None:
            p = os.path.join(layers_dir, f"{base}.text_layer.png")
            layer.save(p)
            written.append(p)

    if save_masks and result.mask is not None:
        p = os.path.join(page_dir, f"{base}.mask.png")
        result.mask.save(p)
        written.append(p)

    return written
