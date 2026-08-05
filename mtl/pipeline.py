"""全链路管道编排：预处理 → 分类 → OCR → 翻译 → 修复 → 渲染 → 导出。

- 阶段级开关（pipeline.stages.*）
- Uncensored_Mode 强制本地引擎路由
- 前 N 页翻译上下文（pipeline.context_pages）
- 节点回调（审查中间产物）
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from . import config as cfgmod
from .errors import MTLError
from .inpaint.mask import build_mask
from .io.exporter import export_result
from .io.loader import load_pages
from .models import Page, PageResult, TranslateItem, Translation
from .preprocess.classifier import classify_page
from .quality.checker import QualityChecker
from .registry import create
from .render.fonts import FontRegistry
from .translate.context import build_context
from .translate.glossary import Glossary

log = logging.getLogger("mtl.pipeline")


class Pipeline:
    def __init__(self, cfg: Dict):
        self.cfg = cfg
        self._callbacks: List[Callable[[str, Page, object], None]] = []
        self._history: deque = deque(maxlen=int(cfgmod.get(cfg, "pipeline.context_pages", 5)))

    # ---------- 事件 ----------
    def on(self, cb: Callable[[str, Page, object], None]) -> None:
        """注册节点回调 cb(stage, page, payload)。

        stage: preprocess|classify|ocr|translate|inpaint|render|export
        payload: 分类串 / regions / translations / mask / image 等
        """
        self._callbacks.append(cb)

    def _notify(self, stage: str, page: Page, payload: object) -> None:
        for cb in self._callbacks:
            try:
                cb(stage, page, payload)
            except Exception:
                log.exception("节点回调失败: %s", stage)

    # ---------- 引擎工厂 ----------
    def _make_engine(self, kind: str, section_key: str):
        section = self.cfg.get(section_key, {})
        name = section.get("engine")
        engines_cfg = section.get("engines") or {}

        extra = None
        if kind == "translate":
            uncensored = bool(cfgmod.get(self.cfg, "translate.uncensored", False))
            if uncensored and name != "local_llm":
                log.warning(
                    "Uncensored_Mode 已开启：强制切换翻译引擎 local_llm"
                    "（云端 API 不适用于受限内容）"
                )
                name = "local_llm"
            extra = {"uncensored": uncensored}
        return create(kind, name, engines_cfg, extra_kwargs=extra)

    # ---------- 引擎缓存（按线程隔离: PaddleOCR 预测器不支持并发）----------
    _thread_local = threading.local()

    def _engine(self, kind: str, section_key: str):
        """带缓存的引擎获取：同一线程内模型只加载一次。

        多 worker 并行时每个线程持有一份引擎实例（PaddleOCR 预测器
        不支持并发 predict，线程隔离避免竞争；内存约 +1~2GB/线程）。
        """
        cache = getattr(self._thread_local, "cache", None)
        if cache is None:
            cache = self._thread_local.cache = {}
        key = (kind, section_key)
        if key not in cache:
            cache[key] = self._make_engine(kind, section_key)
        return cache[key]

    # ---------- 主流程 ----------
    def run(self, input_path: str, out_dir: Optional[str] = None,
            dry_run: bool = False) -> List[PageResult]:
        cfg = self.cfg
        out_dir = out_dir or cfgmod.get(cfg, "export.out_dir", "./output")

        inp = cfg.get("inputs", {})
        pdf_cfg = inp.get("pdf", {})
        pages = load_pages(
            input_path,
            pdf_dpi=pdf_cfg.get("dpi", 300),
            zip_password=inp.get("zip_password"),
        )
        log.info("载入 %d 页: %s", len(pages), input_path)

        results: List[PageResult] = []
        workers = int(cfgmod.get(cfg, "pipeline.workers", 2))
        if workers <= 1 or dry_run:
            for page in pages:
                page.source_lang = cfgmod.get(cfg, "ocr.lang", "")
                result = self._process_page(page, out_dir, dry_run=dry_run)
                results.append(result)
                if not dry_run:
                    # 维护翻译上下文（仅存文本，供后续页使用）
                    texts = [r.text for r in page.regions if r.text.strip()]
                    self._history.append(texts)
        else:
            log.info("并行处理: %d workers", workers)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                fut_map = {}
                for page in pages:
                    page.source_lang = cfgmod.get(cfg, "ocr.lang", "")
                    fut = ex.submit(self._process_page, page, out_dir, False)
                    fut_map[fut] = page
                for fut in as_completed(fut_map):
                    page = fut_map[fut]
                    try:
                        result = fut.result()
                    except Exception:
                        log.exception("页 %d 处理异常", page.page_index)
                        continue
                    results.append(result)
                    texts = [r.text for r in page.regions if r.text.strip()]
                    self._history.append(texts)
        results.sort(key=lambda r: r.page.page_index)
        return results

    def _process_page(self, page: Page, out_dir: str, dry_run: bool) -> PageResult:
        cfg = self.cfg
        result = PageResult(page=page)

        # ---- Stage 1: 预处理（超分） ----
        if cfgmod.stage_enabled(cfg, "preprocess") and not dry_run:
            sr_cfg = cfgmod.get(cfg, "preprocess.superres", {})
            if sr_cfg.get("enabled"):
                from .preprocess.superres import create_sr
                sr = create_sr(sr_cfg)
                page.image = sr.upscale(page.image, sr_cfg.get("scale", 2))
                page.width, page.height = page.image.size
            self._notify("preprocess", page, page.image)

        # ---- Stage 2: 预分类 ----
        if cfgmod.stage_enabled(cfg, "classify"):
            page.kind = classify_page(
                page,
                threshold_color=cfgmod.get(cfg, "classify.threshold_color", 0.08),
            )
            self._notify("classify", page, page.kind)
            log.info("页 %d 分类: %s", page.page_index, page.kind)

        if dry_run:
            result.meta["dry_run"] = True
            return result

        # ---- Stage 3: OCR ----
        ocr_engine = None
        if cfgmod.stage_enabled(cfg, "ocr"):
            ocr_engine = self._engine("ocr", "ocr")
            regions = ocr_engine.run(page)
            min_conf = float(cfgmod.get(cfg, "ocr.min_confidence", 0.0))
            page.regions = [r for r in regions if r.conf >= min_conf]
            from .ocr.reading_order import compute_reading_order
            from .ocr.noise_filter import filter_regions
            page.regions = filter_regions(
                page.regions, cfgmod.get(cfg, "ocr.noise_filter", {})
            )
            page.regions = compute_reading_order(
                page.regions,
                mode=cfgmod.get(cfg, "ocr.reading_order", "auto"),
                source_lang=page.source_lang,
            )
            self._notify("ocr", page, page.regions)
            log.info("页 %d OCR: %d 区域", page.page_index, len(page.regions))

        # ---- Stage 4: 翻译 ----
        if cfgmod.stage_enabled(cfg, "translate"):
            translator = self._engine("translate", "translate")
            items = [
                TranslateItem(region_index=r.index, text=r.text, kind=r.kind)
                for r in page.regions if r.text.strip()
            ]
            glossary = Glossary.load(cfgmod.get(cfg, "translate.glossary"))
            context = build_context(
                list(self._history),
                max_chars=int(cfgmod.get(cfg, "translate.max_context_chars", 6000)),
            )
            result.translations = translator.translate(
                items,
                context=context,
                glossary=glossary,
                task_type=cfgmod.get(cfg, "translate.task_type", "manga"),
            )
            self._notify("translate", page, result.translations)
            log.info("页 %d 翻译: %d 条", page.page_index, len(result.translations))

        # ---- Stage 5/6/8: 修复 + 渲染 + 质检（带重试环）----
        quality_enabled = cfgmod.stage_enabled(cfg, "quality")
        render_enabled = cfgmod.stage_enabled(cfg, "render")
        inpaint_enabled = cfgmod.stage_enabled(cfg, "inpaint")
        max_retries = int(cfgmod.get(cfg, "quality.max_retries", 1))

        inpainter = None
        if inpaint_enabled and page.regions:
            inpainter = self._engine("inpaint", "inpaint")
        checker = QualityChecker(cfg.get("quality", {})) if quality_enabled else None

        for attempt in range(max_retries + 1):
            # Stage 5: 蒙版 + 修复
            if inpaint_enabled and page.regions:
                mask_cfg = cfgmod.get(cfg, "inpaint.mask", {})
                result.mask = build_mask(
                    page.image.size,
                    page.regions,
                    dilation_px=mask_cfg.get("dilation_px", 4),
                    feather=mask_cfg.get("feather", 2),
                )
                result.cleaned = inpainter.inpaint(page.image, result.mask)
                self._notify("inpaint", page, result.cleaned)

            # Stage 6: 渲染
            if render_enabled:
                base_img = result.cleaned if result.cleaned is not None else page.image
                result.final_image = self._render(base_img, result)
                self._notify("render", page, result.final_image)

            # Stage 8(前): 质检
            if checker is not None:
                report = checker.check(
                    result, ocr_engine=ocr_engine,
                    original_image=page.image,
                )
                result.meta["quality"] = report.to_dict()
                if report.passed:
                    break
                if attempt < max_retries:
                    log.warning(
                        "页 %d 质检未通过(%.3f)，重试 %d/%d",
                        page.page_index, report.overall_score,
                        attempt + 1, max_retries,
                    )
                else:
                    log.warning(
                        "页 %d 质检最终未通过(%.3f): %s",
                        page.page_index, report.overall_score,
                        "; ".join(report.issues) or "无",
                    )
            else:
                break

        # ---- Stage 7: 导出 ----
        if cfgmod.stage_enabled(cfg, "export"):
            exp = cfg.get("export", {})
            written = export_result(
                result,
                out_dir,
                formats=tuple(exp.get("formats", ["png", "json"])),
                save_layers=bool(exp.get("save_layers", True)),
                save_masks=bool(exp.get("save_masks", False)),
                quality=int(exp.get("quality", 95)),
            )
            result.meta["exported"] = written
            log.info("页 %d 导出 %d 个文件", page.page_index, len(written))

        return result

    def _render(self, base_img, result: PageResult):
        render_cfg = self.cfg.get("render", {})
        registry = FontRegistry(render_cfg.get("fonts"))
        from .render.effects import render_text_effects
        from .render.layout import fit_font_size

        tmap: Dict[int, Translation] = {
            t.region_index: t for t in result.translations
        }
        effects = render_cfg.get("effects", {})
        stroke_ratio = float(effects.get("stroke_ratio", 0.08))
        shadow_cfg = effects.get("shadow", {"enabled": False})
        alpha = float(effects.get("text_alpha", 1.0))
        style_map = render_cfg.get("style_map", {})
        max_fill = float(render_cfg.get("max_fill_ratio", 0.95))
        min_size = int(render_cfg.get("min_font_size", 8))

        target_lang = render_cfg.get("target_lang", "zh-CN")
        script = "zh" if target_lang.lower().startswith("zh") else "en"

        for r in result.page.regions:
            tr = tmap.get(r.index)
            if tr is None or not tr.translated_text:
                continue
            style = style_map.get(r.kind, "regular")
            # 窄高框(竖排文本)自动竖排渲染
            x0, y0, x1, y1 = r.bbox
            vertical = (y1 - y0) > (x1 - x0) * 1.5
            size, lines = fit_font_size(
                tr.translated_text, r.bbox, registry,
                script=script, style=style,
                min_size=min_size, max_fill_ratio=max_fill,
                vertical=vertical,
            )
            if size is None:
                continue
            font = registry.load(script, style, size)
            stroke_w = max(1, int(size * stroke_ratio))
            base_img = render_text_effects(
                base_img, r.bbox, lines, font,
                stroke=(255, 255, 255, 255),
                stroke_width=stroke_w,
                shadow=shadow_cfg, alpha=alpha,
            )
        return base_img
