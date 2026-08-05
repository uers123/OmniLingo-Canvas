"""文字阅读顺序算法。

支持两种排版规则（启发式，v0.1）：
- rtl_vertical     日韩漫画：从右到左分栏，栏内自上而下
- ltr_horizontal   美漫/韩版Webtoon/游戏UI/文档：自上而下分行，行内从左到右
- auto             根据源语言自动选择（日/韩 -> rtl_vertical，其余 -> ltr）

原理：按中心点聚类分栏/分行（容差取中位尺寸的 60%），
对每栏/行内按主轴排序。对常规漫画分镜足够稳健。
"""

from __future__ import annotations

from typing import List

from ..models import TextRegion

_RTL_LANGS = {"jp", "ja", "ko", "kr"}


def _median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _assign_indices(ordered: List[TextRegion]) -> List[TextRegion]:
    for i, r in enumerate(ordered):
        r.index = i
    return ordered


def _ltr_horizontal(regions: List[TextRegion]) -> List[TextRegion]:
    """自上而下分行（按中心Y聚类），行内从左到右。"""
    if not regions:
        return []
    med_h = _median([r.bbox[3] - r.bbox[1] for r in regions])
    tol = max(med_h * 0.6, 6.0)

    ordered = sorted(regions, key=lambda r: (r.bbox[1] + r.bbox[3]) / 2)
    lines: List[List[TextRegion]] = []
    for r in ordered:
        cy = (r.bbox[1] + r.bbox[3]) / 2
        for line in lines:
            ly = sum((b.bbox[1] + b.bbox[3]) / 2 for b in line) / len(line)
            if abs(cy - ly) <= tol:
                line.append(r)
                break
        else:
            lines.append([r])
    out: List[TextRegion] = []
    for line in lines:
        line.sort(key=lambda r: r.bbox[0])
        out.extend(line)
    return _assign_indices(out)


def _rtl_vertical(regions: List[TextRegion]) -> List[TextRegion]:
    """从右到左分栏（按中心X聚类，右优先），栏内自上而下。"""
    if not regions:
        return []
    med_w = _median([r.bbox[2] - r.bbox[0] for r in regions])
    tol = max(med_w * 0.6, 6.0)

    ordered = sorted(regions, key=lambda r: (r.bbox[0] + r.bbox[2]) / 2, reverse=True)
    cols: List[List[TextRegion]] = []
    for r in ordered:
        cx = (r.bbox[0] + r.bbox[2]) / 2
        for col in cols:
            lx = sum((b.bbox[0] + b.bbox[2]) / 2 for b in col) / len(col)
            if abs(cx - lx) <= tol:
                col.append(r)
                break
        else:
            cols.append([r])
    out: List[TextRegion] = []
    for col in cols:
        col.sort(key=lambda r: r.bbox[1])
        out.extend(col)
    return _assign_indices(out)


def compute_reading_order(
    regions: List[TextRegion],
    mode: str = "auto",
    source_lang: str = "",
) -> List[TextRegion]:
    """计算阅读顺序并就地写入 region.index。"""
    if mode not in ("auto", "rtl_vertical", "ltr_horizontal"):
        mode = "auto"
    if mode == "auto":
        mode = "rtl_vertical" if source_lang.lower() in _RTL_LANGS else "ltr_horizontal"
    if mode == "rtl_vertical":
        return _rtl_vertical(regions)
    return _ltr_horizontal(regions)
