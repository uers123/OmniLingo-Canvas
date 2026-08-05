"""统一异常体系。"""


class MTLError(Exception):
    """框架基类异常。"""


class ConfigError(MTLError):
    """配置加载/校验/环境变量解析失败。"""


class EngineLoadError(MTLError):
    """引擎未注册、依赖缺失或初始化失败。"""


class UnsupportedInputError(MTLError):
    """不支持的输入格式或输入读取失败。"""


class OCRError(MTLError):
    """OCR 阶段失败。"""


class TranslationError(MTLError):
    """翻译阶段失败。"""


class InpaintError(MTLError):
    """图像修复阶段失败。"""


class RenderError(MTLError):
    """渲染阶段失败。"""
