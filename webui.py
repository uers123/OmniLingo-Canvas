# -*- coding: utf-8 -*-
"""图像本地化翻译工作室 — 简洁 Web UI (Gradio)

启动: python webui.py   →   http://127.0.0.1:7861

功能:
- 上传多张图片 或 指定文件夹 批量翻译
- 场景预设 / 目标语言 / 阶段开关 / Uncensored 模式 / 术语词典
- 实时进度 + 日志 + 原图/成品对比画廊 + 质检汇总
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path

import gradio as gr

import mtl.config as cfgmod
from mtl.pipeline import Pipeline

APP_TITLE = "图像本地化翻译工作室"
APP_DESC = (
    "上传图片或指定文件夹 → 自动完成 OCR / 翻译 / 擦除修复 / 渲染 / 质检。\n"
    "模型: PaddleOCR (日文) + 本地 LLM (Ollama qwen2.5) + lama-cleaner 修复服务。"
)

_PROFILE_DIR = Path(__file__).parent / "configs" / "profiles"
_STAGES = ["preprocess", "classify", "ocr", "translate", "inpaint", "render", "quality", "export"]
_STAGE_LABELS = {
    "preprocess": "预处理(超分)", "classify": "页面分类", "ocr": "文字识别",
    "translate": "翻译", "inpaint": "擦除修复", "render": "文字渲染",
    "quality": "自动质检", "export": "导出成品",
}


def _list_profiles() -> list:
    return sorted(p.stem for p in _PROFILE_DIR.glob("*.yaml"))


def _lama_alive(base_url: str = "http://127.0.0.1:7860") -> bool:
    try:
        host, port = base_url.rstrip("/").split("//")[1].split(":")
        with socket.create_connection((host, int(port)), timeout=1.5):
            return True
    except Exception:
        return False


def monitor_batch(out_dir: str, log_file: str):
    """批跑监控: 统计输出目录进度 + 质检通过率 + 日志尾部。"""
    out_dir = out_dir.strip() or "output"
    if not os.path.isdir(out_dir):
        return "输出目录不存在", "-", "（等待任务…）"
    page_dirs = sorted(glob.glob(os.path.join(out_dir, "page_*")))
    done = 0
    qc_total = qc_pass = 0
    for pd_ in page_dirs:
        finals = glob.glob(os.path.join(pd_, "*.final.png")) + \
                 glob.glob(os.path.join(pd_, "*.final.jpg"))
        done += len(finals)
        for j in glob.glob(os.path.join(pd_, "*.data.json")):
            try:
                import json as _json
                d = _json.load(open(j, encoding="utf-8"))
                q = d.get("quality")
                if q:
                    qc_total += 1
                    if q.get("passed"):
                        qc_pass += 1
            except Exception:
                pass
    tail = ""
    if log_file and os.path.isfile(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail = "".join(lines[-12:])
        except Exception:
            tail = "(日志读取失败)"
    return (f"已完成 {done} 页 / 输出目录共 {len(page_dirs)} 组",
            f"质检 {qc_pass}/{qc_total} 页通过" if qc_total else "质检: 暂无数据",
            tail or "（暂无日志）")


def _as_path(x) -> str:
    """兼容 gr.Upload 返回 str 或 FileData。"""
    return getattr(x, "name", None) or getattr(x, "path", None) or str(x)


def _prepare_input(uploaded, folder: str, workdir: str) -> str:
    """把上传文件/文件夹整理成输入目录, 返回目录路径。"""
    src_files: list = []
    if uploaded:
        src_files = [_as_path(f) for f in uploaded if _as_path(f)]
    if folder and os.path.isdir(folder):
        src_files += [os.path.join(folder, f) for f in os.listdir(folder)
                      if not f.startswith(".")]

    if not src_files:
        return ""

    in_dir = os.path.join(workdir, "input")
    os.makedirs(in_dir, exist_ok=True)
    seen = set()
    for i, f in enumerate(src_files):
        if not os.path.isfile(f):
            continue
        name = os.path.basename(f)
        if name in seen:
            stem, ext = os.path.splitext(name)
            name = f"{stem}_{i}{ext}"
        seen.add(name)
        shutil.copy2(f, os.path.join(in_dir, name))
    return in_dir


def _collect_results(out_dir: str) -> tuple:
    """扫描输出目录 → (画廊 pairs, 每页 data.json 摘要)。"""
    pairs, summaries = [], []
    page_dirs = sorted(glob.glob(os.path.join(out_dir, "page_*")))
    for pd_ in page_dirs:
        finals = glob.glob(os.path.join(pd_, "*.final.png")) + \
                 glob.glob(os.path.join(pd_, "*.final.jpg"))
        jsons = glob.glob(os.path.join(pd_, "*.data.json"))
        for f in finals:
            base = os.path.basename(f)
            for suf in (".final.png", ".final.jpg"):
                if base.endswith(suf):
                    base = base[: -len(suf)]
                    break
            src = None
            for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                cand = os.path.join(pd_, base + ext)
                if os.path.exists(cand):
                    src = cand
                    break
            pairs.append((f, src))
        if jsons:
            summaries.append(jsons[0])
    return pairs, summaries


def run_job(uploaded, folder, profile, target_lang, stages,
            uncensored, glossary, out_name, progress=gr.Progress()):
    log_lines: list = []

    def log(msg: str):
        log_lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    progress(0.01, desc="准备输入…")
    workdir = tempfile.mkdtemp(prefix="mtl_ui_")
    in_dir = _prepare_input(uploaded, folder, workdir)
    if not in_dir:
        return (gr.Gallery(value=[], label="对比"), "\n".join(log_lines) or "未找到输入文件",
                "未找到输入文件", "")

    # ---- 配置 ----
    try:
        paths = [cfgmod.default_config_path(), cfgmod.profile_path(profile)]
        if uncensored:
            paths.append(cfgmod.nsfw_config_path())
        cfg = cfgmod.load_config(*paths)
    except Exception as e:
        return (gr.Gallery(value=[], label="对比"), "", f"配置错误: {e}", "")

    if target_lang:
        cfg["translate"]["target_lang"] = target_lang
    if glossary:
        cfg["translate"]["glossary"] = glossary
    if uncensored:
        cfg["translate"]["uncensored"] = True
    # 阶段开关
    stage_set = set(stages) if stages else set(_STAGES)
    for s in _STAGES:
        cfg["pipeline"]["stages"][s] = s in stage_set
    # inpaint 可用性检查
    lama_url = cfg.get("inpaint", {}).get("engines", {}).get("lama", {}).get("kwargs", {}).get("base_url", "http://127.0.0.1:7860")
    if cfg["pipeline"]["stages"].get("inpaint") and not _lama_alive(lama_url):
        log(f"⚠️ lama-cleaner 未运行({lama_url})，本次自动跳过擦除修复")
        cfg["pipeline"]["stages"]["inpaint"] = False

    out_dir = os.path.abspath(os.path.join("output", out_name or "ui_run"))
    os.makedirs(out_dir, exist_ok=True)

    # ---- 运行 ----
    log(f"输入: {in_dir}")
    log(f"预设: {profile} | 目标语言: {target_lang} | 输出: {out_dir}")
    if uncensored:
        log("🔞 Uncensored_Mode: 已启用本地无审查翻译")
    progress(0.02, desc="加载模型…")

    pipe = Pipeline(cfg)
    n_done = 0

    def cb(stage, page, payload):
        nonlocal n_done
        try:
            idx = page.page_index
            if stage == "ocr":
                n = len(payload) if payload else 0
                log(f"页 {idx}: OCR {n} 区域")
            elif stage == "translate":
                n = len(payload) if payload else 0
                log(f"页 {idx}: 翻译 {n} 条")
            elif stage == "inpaint":
                log(f"页 {idx}: 擦除修复完成")
            elif stage == "render":
                log(f"页 {idx}: 渲染完成")
                n_done += 1
                progress(min(0.98, 0.02 + 0.9 * n_done / max(1, n_total)), desc=f"处理中 页 {idx}…")
        except Exception:
            pass

    n_total = max(1, len([f for f in os.listdir(in_dir)
                          if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))]))

    try:
        pipe.on(cb)
        results = pipe.run(in_dir, out_dir)
    except Exception as e:
        log(f"❌ 运行失败: {e}")
        return (gr.Gallery(value=[], label="对比"), "\n".join(log_lines),
                f"运行失败: {e}", out_dir)

    # ---- 汇总 ----
    passed = sum(1 for r in results
                 if r.meta.get("quality", {}).get("passed"))
    qc = sum(1 for r in results if r.meta.get("quality"))
    lines = [f"完成 {len(results)} 页", f"质检: {passed}/{qc} 页通过"]
    for r in results:
        q = r.meta.get("quality")
        if q:
            lines.append(f"  页 {r.page.page_index}: 总分 {q['overall_score']} "
                         f"(ocr {q['ocr_check_score']} / ssim {q['ssim_score']} / "
                         f"残留 {q['residual_score']}) {'✅' if q['passed'] else '⚠️'}")
    summary = "\n".join(lines)
    log("✅ 全部完成: " + lines[0])

    pairs, _ = _collect_results(out_dir)
    # 画廊: 优先用 results 里的原始路径(原图), 成品在 page 目录
    gallery_val = []
    for r in results:
        src = getattr(r.page, "source", None)
        if src and os.path.exists(src):
            gallery_val.append((src, f"页{r.page.page_index} 原图"))
        base = os.path.basename(src) if src else f"page_{r.page.page_index:04d}"
        for suf in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            if base.lower().endswith(suf):
                base = base[: -len(suf)]
                break
        final_p = os.path.join(out_dir, f"page_{r.page.page_index:04d}", base + ".final.png")
        if os.path.exists(final_p):
            gallery_val.append((final_p, f"页{r.page.page_index} 成品"))
    return (gr.Gallery(value=gallery_val, label="原图 vs 成品"),
            "\n".join(log_lines), summary, out_dir)


def build_app() -> gr.Blocks:
    profiles = _list_profiles()
    with gr.Blocks(title=APP_TITLE) as demo:
        gr.Markdown(f"# 🖼️ {APP_TITLE}\n{APP_DESC}")

        with gr.Tabs():
            # ================= 标签1: 翻译工作台 =================
            with gr.Tab("🛠️ 翻译工作台"):
                with gr.Row():
                    # ============ 左: 设置 ============
                    with gr.Column(scale=5):
                        upload = gr.Files(
                            label="📤 上传图片（可多选）", file_count="multiple",
                            file_types=["image", ".pdf", ".zip"],
                        )
                        gr.Markdown("**或** 指定本地文件夹：")
                        folder = gr.Textbox(label="📁 文件夹路径", placeholder=r"D:\...\漫画目录", lines=1)
                        with gr.Row():
                            profile_dd = gr.Dropdown(choices=profiles, value=profiles[0] if profiles else None,
                                                     label="🎛️ 场景预设")
                            lang_dd = gr.Dropdown(choices=["zh-CN", "zh-TW", "en", "ja", "ko"],
                                                  value="zh-CN", label="🌐 目标语言")
                        with gr.Accordion("⚙️ 高级选项", open=False):
                            stage_cb = gr.CheckboxGroup(
                                choices=list(_STAGES), value=list(_STAGES),
                                label="处理阶段", info="取消勾选可跳过对应阶段",
                            )
                            uncensored_cb = gr.Checkbox(label="🔞 Uncensored_Mode（无审查翻译，强制本地模型）")
                            glossary_tb = gr.Textbox(label="📖 术语词典路径 (csv/json)",
                                                     placeholder="configs/glossary/示例.csv")
                            out_tb = gr.Textbox(label="输出目录名", value="ui_run",
                                                placeholder="输出到 output/<名字>/")
                        run_btn = gr.Button("🚀 开始翻译", variant="primary")

                    # ============ 右: 结果 ============
                    with gr.Column(scale=7):
                        log_box = gr.Textbox(label="📋 运行日志", lines=14, max_lines=30, autoscroll=True)
                        summary_box = gr.Textbox(label="📊 汇总", lines=4, interactive=False)
                        gallery = gr.Gallery(label="🖼️ 原图 vs 成品", columns=2, height=420)
                        out_path = gr.Textbox(label="📂 输出目录", interactive=False)

                run_btn.click(
                    run_job,
                    inputs=[upload, folder, profile_dd, lang_dd, stage_cb,
                            uncensored_cb, glossary_tb, out_tb],
                    outputs=[gallery, log_box, summary_box, out_path],
                )

            # ================= 标签2: 批跑监控 =================
            with gr.Tab("📡 批跑监控"):
                gr.Markdown("监控外部批量任务（如 CLI 批跑）的进度与质检结果，每 10 秒自动刷新。")
                with gr.Row():
                    mon_dir = gr.Textbox(label="输出目录", value="output", lines=1)
                    mon_log = gr.Textbox(label="日志文件路径", value="_batch.log", lines=1,
                                         placeholder="批跑日志文件(可选)")
                    refresh_btn = gr.Button("🔄 立即刷新", variant="secondary")
                mon_progress = gr.Textbox(label="进度", lines=1, interactive=False)
                mon_quality = gr.Textbox(label="质检", lines=1, interactive=False)
                mon_tail = gr.Textbox(label="最近日志", lines=12, interactive=False)

                mon_inputs = [mon_dir, mon_log]
                mon_outputs = [mon_progress, mon_quality, mon_tail]
                refresh_btn.click(monitor_batch, mon_inputs, mon_outputs)
                timer = gr.Timer(value=10)
                timer.tick(monitor_batch, mon_inputs, mon_outputs)
    return demo


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    demo = build_app()
    demo.queue()
    demo.launch(server_name="127.0.0.1", server_port=7861,
                show_error=True, theme=gr.themes.Soft())
