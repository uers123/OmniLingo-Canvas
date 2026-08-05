"""核心数据模型：文本区域 / 页面 / 翻译结果 / 页面结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

Point = Tuple[float, float]


@dataclass
class TextRegion:
    """一个被检测出的文本区域。

    polygon 为闭合多边形顶点列表（>=3 个点），支持任意四边形/倾斜框。
    """

    polygon: List[Point]
    text: str = ""
    conf: float = 0.0
    lang: str = ""
    kind: str = "unknown"  # bubble | caption | sfx | background | unknown
    index: int = -1        # 阅读顺序位次（由 reading_order 算法赋值）
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """轴对齐包围盒 (x0, y0, x1, y1)。"""
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return (min(xs), min(ys), max(xs), max(ys))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "polygon": [[float(x), float(y)] for x, y in self.polygon],
            "text": self.text,
            "conf": round(float(self.conf), 4),
            "lang": self.lang,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TextRegion":
        return cls(
            polygon=[(float(p[0]), float(p[1])) for p in d.get("polygon", [])],
            text=d.get("text", ""),
            conf=d.get("conf", 0.0),
            lang=d.get("lang", ""),
            kind=d.get("kind", "unknown"),
            index=d.get("index", -1),
        )


@dataclass
class Page:
    """一个待处理的页面（单张图 / PDF 一页 / ZIP 内一张）。"""

    page_index: int
    path: str = ""
    image: Any = None       # PIL.Image, 延迟加载
    width: int = 0
    height: int = 0
    source_lang: str = ""
    kind: str = "unknown"   # 预分类结果
    regions: List[TextRegion] = field(default_factory=list)


@dataclass
class TranslateItem:
    """翻译单元（由 OCR 区域生成）。"""

    region_index: int
    text: str
    kind: str = "unknown"


@dataclass
class Translation:
    """一条翻译结果。"""

    region_index: int
    source_text: str
    translated_text: str
    glossary_hits: List[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_index": self.region_index,
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "glossary_hits": self.glossary_hits,
            "note": self.note,
        }


@dataclass
class PageResult:
    """单页全链路处理结果。"""

    page: Page
    translations: List[Translation] = field(default_factory=list)
    mask: Any = None            # PIL.Image (L 模式)
    cleaned: Any = None         # PIL.Image 擦除后
    final_image: Any = None     # PIL.Image 成品
    meta: Dict[str, Any] = field(default_factory=dict)
