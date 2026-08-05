"""插件注册表：引擎按 (kind, name) 注册，按需懒加载模块触发注册。

新增引擎三步：
1. 实现对应 Base 接口（ocr.BaseOCR / translate.BaseTranslator / inpaint.BaseInpainter）
2. 模块内用 @register("ocr", "my_engine") 装饰类
3. 在 YAML engines 段声明 module 路径与 kwargs
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional, Type

from .errors import EngineLoadError, MTLError

_KIND_MODULES: Dict[str, list] = {
    "ocr": [
        "mtl.ocr.engines.paddle",
        "mtl.ocr.engines.manga_ocr",
        "mtl.ocr.engines.tesseract",
        "mtl.ocr.engines.cloud",
    ],
    "translate": [
        "mtl.translate.engines.deepl",
        "mtl.translate.engines.tencent",
        "mtl.translate.engines.openai",
        "mtl.translate.engines.local_llm",
    ],
    "inpaint": [
        "mtl.inpaint.engines.lama",
        "mtl.inpaint.engines.sd",
    ],
    "classify": [],
    "superres": [],
}


class _Registry:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: Dict[str, Type] = {}

    def register(self, name: str, cls: Type) -> None:
        self._items[name] = cls

    def get(self, name: str) -> Type:
        if name not in self._items:
            raise EngineLoadError(
                f"未注册的 {self.kind} 引擎: {name!r} (可用: {', '.join(self.names()) or '无'})"
            )
        return self._items[name]

    def names(self) -> list:
        return sorted(self._items)


REGISTRIES: Dict[str, _Registry] = {
    "ocr": _Registry("ocr"),
    "translate": _Registry("translate"),
    "inpaint": _Registry("inpaint"),
    "classify": _Registry("classify"),
    "superres": _Registry("superres"),
}


def register(kind: str, name: str):
    """类装饰器：注册引擎。"""

    def deco(cls: Type) -> Type:
        REGISTRIES[kind].register(name, cls)
        return cls

    return deco


def load_module(module_path: str) -> None:
    """导入模块以触发模块内的 @register 注册。缺依赖时静默跳过。"""
    try:
        importlib.import_module(module_path)
    except ImportError:
        pass
    except Exception:
        # 引擎模块自身逻辑错误不应拖垮注册流程
        pass


def load_all(kind: str) -> None:
    """导入某 kind 的全部内置引擎模块（用于 --list-engines）。"""
    for mod in _KIND_MODULES.get(kind, []):
        load_module(mod)


def create(
    kind: str,
    name: str,
    engines_cfg: Optional[Dict[str, Any]] = None,
    extra_kwargs: Optional[Dict[str, Any]] = None,
):
    """按名称创建引擎实例。

    engines_cfg: 对应配置段下的 engines 映射，形如
        {name: {module: ..., kwargs: {...}}}
    extra_kwargs: 管道级注入的额外参数（如 uncensored 标志），优先于配置。
    """
    entry = {}
    if isinstance(engines_cfg, dict):
        entry = engines_cfg.get(name) or {}
    module_path = entry.get("module")
    if module_path:
        load_module(module_path)
    cls = REGISTRIES[kind].get(name)
    kwargs: Dict[str, Any] = dict(entry.get("kwargs") or {})
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    try:
        return cls(**kwargs)
    except MTLError:
        raise
    except Exception as e:
        raise EngineLoadError(f"初始化 {kind}:{name} 失败: {e}") from e
