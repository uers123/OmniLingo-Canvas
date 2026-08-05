"""图像预分类器（启发式 v0.1）。

类别: manga_bw | manga_color | illustration | game_ui | document | unknown
接口预留 ML 模型挂载（classify.engine: ml）。
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..models import Page

KINDS = ("manga_bw", "manga_color", "illustration", "game_ui", "document", "unknown")


def classify_page(page: Page, threshold_color: float = 0.08) -> str:
    """基于彩度占比 / 边缘密度 / 亮度标准差 / 长宽比的启发式分类。"""
    img = page.image
    if img is None:
        return "unknown"
    try:
        small = img.convert("RGB").resize((160, 160))
        a = np.asarray(small).astype(np.int16)
    except Exception:
        return "unknown"

    mx = a.max(axis=2)
    mn = a.min(axis=2)
    color_ratio = float((mx - mn > 24).mean())

    gray = a.mean(axis=2)
    gy, gx = np.gradient(gray)
    edge = np.hypot(gx, gy)
    edge_ratio = float((edge > 30).mean())
    std = float(gray.std())

    portrait = page.height > page.width

    if color_ratio < threshold_color:
        # 低彩度：黑白漫画 vs 文档/扫描件
        if edge_ratio > 0.05 or std > 60:
            return "manga_bw" if portrait else "document"
        return "document"

    # 高彩度
    if edge_ratio > 0.08:
        # 大量锐利边缘（文字/UI 元素密集）
        return "game_ui"
    if std < 45:
        return "illustration"  # 柔和渐变的大面积插画
    return "manga_color"


class HeuristicClassifier:
    name = "heuristic"

    def __init__(self, threshold_color: float = 0.08, **kwargs):
        self.threshold_color = threshold_color

    def classify(self, page: Page) -> str:
        return classify_page(page, self.threshold_color)
