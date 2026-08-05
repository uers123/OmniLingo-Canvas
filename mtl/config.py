"""配置加载：YAML 深合并、环境变量展开、基础校验。"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .errors import ConfigError

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"

REQUIRED_SECTIONS = ("pipeline", "ocr", "translate", "inpaint", "render", "export")


def default_config_path() -> str:
    return str(_CONFIGS_DIR / "default.yaml")


def nsfw_config_path() -> str:
    return str(_CONFIGS_DIR / "nsfw.yaml")


def profile_path(name: str) -> str:
    """按名称解析场景预设路径；若传入的是已存在文件路径则直接使用。"""
    p = Path(name)
    if p.exists():
        return str(p)
    cand = _CONFIGS_DIR / "profiles" / f"{name}.yaml"
    if not cand.exists():
        raise ConfigError(f"场景预设不存在: {name} (已尝试 {cand})")
    return str(cand)


def _expand(obj: Any) -> Any:
    """递归展开字符串中的 ${ENV_VAR}，未设置的变量直接报错（防静默失效）。"""
    if isinstance(obj, str):

        def repl(m: "re.Match[str]") -> str:
            key = m.group(1)
            if key not in os.environ:
                raise ConfigError(
                    f"配置引用了未设置的环境变量 ${{{key}}}；请设置后重试"
                )
            return os.environ[key]

        return _ENV_RE.sub(repl, obj)
    if isinstance(obj, dict):
        return {k: _expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand(v) for v in obj]
    return obj


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """深合并：字典逐层合并，列表/标量直接覆盖。"""
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def validate(cfg: Dict[str, Any]) -> None:
    missing = [s for s in REQUIRED_SECTIONS if s not in cfg]
    if missing:
        raise ConfigError(f"配置缺少必需段: {', '.join(missing)}")
    for section in ("ocr", "translate", "inpaint"):
        engines = cfg.get(section, {}).get("engines")
        if not isinstance(engines, dict) or not engines:
            raise ConfigError(f"配置段 [{section}].engines 必须声明至少一个引擎")
        if cfg[section].get("engine") not in engines:
            raise ConfigError(
                f"配置段 [{section}].engine={cfg[section].get('engine')!r} "
                f"未在 engines 中声明"
            )


def load_config(
    *paths: str, allow_missing: bool = False
) -> Dict[str, Any]:
    """按顺序加载 YAML 并深合并；最后做环境变量展开与校验。"""
    cfg: Dict[str, Any] = {}
    for p in paths:
        if not os.path.exists(p):
            if allow_missing:
                continue
            raise ConfigError(f"配置文件不存在: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"配置文件顶层必须是映射: {p}")
        cfg = deep_merge(cfg, data)
    cfg = _expand(cfg)
    validate(cfg)
    return cfg


def get(cfg: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    """点路径取值，如 get(cfg, 'translate.engines.local_llm.kwargs.model')。"""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def stage_enabled(cfg: Dict[str, Any], stage: str) -> bool:
    return bool(get(cfg, f"pipeline.stages.{stage}", True))


def enabled_engines(engines_cfg: Dict[str, Any]) -> List[str]:
    """返回 kwargs.enabled != False 的引擎名（无审查模式下云端引擎被禁用）。"""
    out = []
    for name, entry in (engines_cfg or {}).items():
        kwargs = (entry or {}).get("kwargs") or {}
        if kwargs.get("enabled") is False:
            continue
        out.append(name)
    return out
