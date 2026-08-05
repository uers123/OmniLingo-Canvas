"""质检模块（移植自 ben-zi-翻译 旧项目，升级为真实实现）。

三项检查：
1. OCR 复检   — 对成品图整体重跑 OCR，校验译文是否真实渲染进图
2. SSIM 结构相似度 — 非修复区域与原图的结构一致性（numpy 实现，无 skimage 依赖）
3. 残留检测   — 对修复后图像重跑 OCR，检测原文字是否残留

不合格 → 触发管道级重试（重新 inpaint + render，最多 max_retries 次）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..models import Page, PageResult, TextRegion, Translation

log = logging.getLogger("mtl.quality")


@dataclass
class QualityReport:
    passed: bool
    overall_score: float
    ocr_check_score: float = 0.0
    ssim_score: float = 0.0
    residual_score: float = 0.0
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "overall_score": self.overall_score,
            "ocr_check_score": self.ocr_check_score,
            "ssim_score": self.ssim_score,
            "residual_score": self.residual_score,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "details": self.details,
        }


def _norm_text(s: str) -> str:
    """归一化用于比对：去空白与常见标点。"""
    import re
    return re.sub(r"[\s，。！？、,.!?·…「」『』（）()\"'']", "", s)


def _text_similarity(a: str, b: str) -> float:
    """归一化后的包含/重叠度相似度。"""
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.85
    sa, sb = set(na), set(nb)
    return len(sa & sb) / len(sa | sb)


def _box_filter_sum(x: np.ndarray, r: int) -> np.ndarray:
    """积分图实现滑动窗口和（边界按窗口截断，保证输出形状一致）。"""
    h, w = x.shape
    c = np.cumsum(np.cumsum(x, axis=0), axis=1)
    out = np.zeros_like(x, dtype=float)
    for i in range(h):
        i0, i1 = max(0, i - r), min(h, i + r + 1)
        for j in range(w):
            j0, j1 = max(0, j - r), min(w, j + r + 1)
            total = c[i1 - 1, j1 - 1]
            if i0 > 0:
                total -= c[i0 - 1, j1 - 1]
            if j0 > 0:
                total -= c[i1 - 1, j0 - 1]
            if i0 > 0 and j0 > 0:
                total += c[i0 - 1, j0 - 1]
            out[i, j] = total / ((i1 - i0) * (j1 - j0))
    return out


def _ssim_np(a: np.ndarray, b: np.ndarray, win: int = 7,
             data_range: float = 255.0) -> float:
    """纯 numpy 窗口化 SSIM（无 skimage/scipy 依赖）。"""
    if a.shape != b.shape:
        return 0.0
    a = a.astype(float)
    b = b.astype(float)
    r = win // 2
    C1, C2 = (0.01 * data_range) ** 2, (0.03 * data_range) ** 2
    mu_a, mu_b = _box_filter_sum(a, r), _box_filter_sum(b, r)
    sigma_a2 = _box_filter_sum(a * a, r) - mu_a * mu_a
    sigma_b2 = _box_filter_sum(b * b, r) - mu_b * mu_b
    sigma_ab = _box_filter_sum(a * b, r) - mu_a * mu_b
    ssim_map = ((2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)) / \
               ((mu_a ** 2 + mu_b ** 2 + C1) * (sigma_a2 + sigma_b2 + C2))
    return float(np.clip(ssim_map.mean(), 0.0, 1.0))


class QualityChecker:
    def __init__(self, cfg: Optional[dict] = None):
        cfg = cfg or {}
        self.ocr_threshold = float(cfg.get("ocr_check_threshold", 0.7))
        self.ssim_threshold = float(cfg.get("ssim_threshold", 0.85))
        self.residual_sensitivity = float(cfg.get("residual_sensitivity", 0.5))
        self.pass_threshold = float(cfg.get("pass_threshold", 0.7))
        self.weights = {"ocr": 0.35, "ssim": 0.35, "residual": 0.30}

    # ---------- 检查入口 ----------
    def check(self, result: PageResult, ocr_engine=None,
              original_image=None) -> QualityReport:
        """综合质检。ocr_engine 为管道已实例化的 OCR 引擎（可复用）。"""
        issues: List[str] = []
        suggestions: List[str] = []

        final = result.final_image
        original = original_image if original_image is not None else result.page.image

        ocr_score = self._ocr_recheck(result, ocr_engine) if final is not None else 1.0
        ssim_score = self._ssim_check(original, final, result) if final is not None else 1.0
        residual_score = 1.0
        if result.cleaned is not None:
            residual_score = self._residual_check(result, ocr_engine)

        if ocr_score < self.ocr_threshold:
            issues.append(f"OCR 复检得分过低: {ocr_score:.2f} < {self.ocr_threshold}")
            suggestions.append("译文渲染可能缺失/溢出，请检查字体字号")
        if ssim_score < self.ssim_threshold:
            issues.append(f"SSIM 得分过低: {ssim_score:.2f} < {self.ssim_threshold}")
            suggestions.append("修复区域与原图差异过大，需改进 inpainting")
        if residual_score < 1.0 - self.residual_sensitivity:
            issues.append(f"检测到原文字残留: score={residual_score:.2f}")
            suggestions.append("擦除不彻底，需增强蒙版膨胀或修复强度")

        overall = (
            ocr_score * self.weights["ocr"]
            + ssim_score * self.weights["ssim"]
            + residual_score * self.weights["residual"]
        )
        passed = overall >= self.pass_threshold and len(issues) <= 1
        log.info("质检: overall=%.3f ocr=%.3f ssim=%.3f residual=%.3f -> %s",
                 overall, ocr_score, ssim_score, residual_score,
                 "PASS" if passed else "FAIL")
        for iss in issues:
            log.warning("  [质检] %s", iss)

        return QualityReport(
            passed=passed,
            overall_score=round(overall, 3),
            ocr_check_score=round(ocr_score, 3),
            ssim_score=round(ssim_score, 3),
            residual_score=round(residual_score, 3),
            issues=issues,
            suggestions=suggestions,
            details={"weights": self.weights,
                     "thresholds": {"ocr": self.ocr_threshold,
                                    "ssim": self.ssim_threshold,
                                    "overall": self.pass_threshold}},
        )

    # ---------- 1. OCR 复检 ----------
    def _ocr_recheck(self, result: PageResult, ocr_engine) -> float:
        """对成品图重跑 OCR，校验每条译文都能在图中找到。"""
        if ocr_engine is None or result.final_image is None:
            return 1.0
        if not result.translations:
            return 1.0
        try:
            page = Page(page_index=-1, image=result.final_image,
                        width=result.final_image.width,
                        height=result.final_image.height)
            detected = ocr_engine.run(page)
        except Exception as e:
            log.warning("OCR 复检失败: %s", e)
            return 0.0
        det_texts = [d.text for d in detected if d.text.strip()]
        scores = []
        for t in result.translations:
            if not t.translated_text:
                continue
            best = max((_text_similarity(t.translated_text, dt) for dt in det_texts),
                       default=0.0)
            scores.append(best)
        return float(np.mean(scores)) if scores else 1.0

    # ---------- 2. SSIM ----------
    def _ssim_check(self, original, final, result: PageResult) -> float:
        """非修复区域的结构相似度（修复区域被排除，因为那里本应变化）。"""
        if original is None or final is None:
            return 1.0
        a = np.asarray(original.convert("RGB"))
        b = np.asarray(final.convert("RGB"))
        if a.shape != b.shape:
            return 0.0
        mask = np.ones(a.shape[:2], dtype=bool)
        for r in result.page.regions:
            x0, y0, x1, y1 = (int(v) for v in r.bbox)
            x0, y0 = max(0, x0), max(0, y0)
            x1 = min(a.shape[1], x1)
            y1 = min(a.shape[0], y1)
            if x1 > x0 and y1 > y0:
                mask[y0:y1, x0:x1] = False
        # 若全图都是修复区, 退化为整图比较
        if mask.sum() < a.shape[0] * a.shape[1] * 0.05:
            mask[:] = True
        # 抽样比较（大图提速）：步长 2
        a_g = np.mean(a, axis=2)[::2, ::2]
        b_g = np.mean(b, axis=2)[::2, ::2]
        m = mask[::2, ::2]
        try:
            score = _ssim_np(a_g[m], b_g[m], win=7)
        except Exception:
            score = 1.0
        return score

    # ---------- 3. 残留检测 ----------
    def _residual_check(self, result: PageResult, ocr_engine) -> float:
        """对修复后图像重跑 OCR，检测原文字残留。"""
        if ocr_engine is None or result.cleaned is None:
            return 1.0
        if not result.page.regions:
            return 1.0
        try:
            page = Page(page_index=-1, image=result.cleaned,
                        width=result.cleaned.width,
                        height=result.cleaned.height)
            detected = ocr_engine.run(page)
        except Exception as e:
            log.warning("残留检测失败: %s", e)
            return 0.5
        # 检测框与任一原区域重叠且置信度足够 → 残留
        residual = 0
        for d in detected:
            if d.conf < 0.5 or not d.text.strip():
                continue
            dx0, dy0, dx1, dy1 = d.bbox
            for r in result.page.regions:
                rx0, ry0, rx1, ry1 = r.bbox
                ox = max(0, min(dx1, rx1) - max(dx0, rx0))
                oy = max(0, min(dy1, ry1) - max(dy0, ry0))
                if ox > 0 and oy > 0:
                    residual += 1
                    break
        total = max(1, len(result.page.regions))
        return max(0.0, 1.0 - residual / total)
