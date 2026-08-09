# OmniLingo Canvas · 图像本地化与翻译工作台

> 多语种、多场景的自动化图像本地化框架：**OCR → 翻译 → 擦除修复 → 文字渲染 → 自动质检** 全链路，一键交付成品图。

支持漫画（日/韩/英等多语种）、插画、同人志、游戏截图、扫描文档等图像类型。OCR / 翻译 / 修复引擎全部**可插拔**，可在本地开源模型与云端 API 之间自由路由；全链路可在**完全离线**环境下运行，数据不出内网。

![Web UI](docs/screenshot.png)

## ✨ 功能特性

- **全链路自动化**：文字识别 → 翻译 → 背景擦除修复 → 译文渲染 → 自动质检（OCR 复检 + SSIM + 残留检测），质检失败自动重试
- **多引擎路由**：OCR（PaddleOCR / Manga-OCR / Tesseract / 百度 / Google Vision）、翻译（本地 LLM / DeepL / 腾讯 / OpenAI 兼容 API）、修复（lama-cleaner / Stable Diffusion）
- **本地优先**：Ollama + Qwen/Llama 全本地推理，断网可用；支持 `Uncensored_Mode` 切换本地无审查模型（自托管场景，用户自担内容合规责任）
- **场景预设**：漫画（右→左竖排阅读序）、游戏 UI（简短精准）、文档（严谨直译）、插画（艺术感）
- **上下文与术语**：跨页上下文窗口保持专有名词统一；CSV/JSON 术语词典
- **批量并行**：多 worker 并行处理，批跑断点续跑
- **简洁 Web UI**：上传/文件夹输入、实时进度日志、原图/成品对比画廊、批跑监控面板
- **工程化输出**：成品图 + 透明文字图层（PSD 工作流友好）+ 原文/译文/坐标 JSON

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 推荐 GPU（无 GPU 也可运行，速度较慢）

### 安装

> ⚠️ 注意：当前仓库**未包含** `requirements.txt` / `requirements-optional.txt` / `webui.py` / `tests/`。
> 请根据 `mtl/` 各模块的 import 自行安装依赖（如 `paddleocr`、`pytesseract`、`Pillow`、`PyYAML` 等），
> 或等待作者补全工程化文件。当前唯一可用入口为命令行 `python cli.py`。

可选本地服务：

```bash
# 1) 本地 LLM (Ollama + Qwen)
ollama pull qwen2.5:7b

# 2) 擦除修复服务 (lama-cleaner)
lama-cleaner --model lama --device cuda --port 7860
```

### 命令行

```bash
# 单张/整个目录
python cli.py --input ./漫画目录 --profile manga_jp2zh --output output

# 并行 4 worker
python cli.py --input ./漫画目录 --profile manga_jp2zh --workers 4

# 跳过修复阶段 / 只看 OCR 结果
python cli.py --input ./漫画目录 --skip inpaint
python cli.py --input ./漫画目录 --until ocr
```

### Web UI

> ⚠️ Web UI（`webui.py` / `start_ui.bat`）尚未包含在当前仓库中，请使用命令行入口。

## 🗂️ 项目结构

```
mtl/
├── ocr/          # 文字检测与识别（PaddleOCR/Manga-OCR/Tesseract/云端）+ 阅读顺序 + 噪声过滤
├── translate/    # 翻译引擎（本地LLM/DeepL/腾讯/OpenAI兼容）+ 术语词典 + 上下文
├── inpaint/      # 蒙版生成与背景修复（lama-cleaner/SD）
├── render/       # 自适应排版（字号/竖排/描边/阴影）与字体库
├── quality/      # 自动质检（OCR复检/SSIM/残留检测）+ 重试
├── preprocess/   # 页面分类与超分
├── io/           # 多格式输入与工程化导出
└── pipeline.py   # 全链路编排（阶段开关/并行/事件回调）
configs/          # 默认配置 + 场景预设 + 术语词典
webui.py          # Gradio Web 界面
```

## 🎛️ 配置

配置为 YAML 深合并：`configs/default.yaml` → `configs/profiles/<场景>.yaml` → `configs/nsfw.yaml`，支持 `${环境变量}` 引用。

```yaml
# configs/profiles/manga_jp2zh.yaml 示例
ocr:
  engine: paddle
  lang: jp
  reading_order: rtl_vertical   # 日漫从右到左竖排
translate:
  engine: local_llm
  task_type: manga
  target_lang: zh-CN
  glossary: configs/glossary/示例.csv
inpaint:
  engine: lama
render:
  target_lang: zh-CN
  vertical: auto
```

## 📄 文档

- [商业化评估](docs/商业化评估.md)
- [测试](tests/test_core.py) — 核心单元测试

## 🔒 合规声明

本项目是通用图像本地化工程框架。使用者应确保处理内容拥有合法权利或已获授权；涉及敏感内容的本地自托管使用，责任由使用者自行承担。商业/SaaS 场景请遵循当地法律法规。

## 📜 License

[Apache License 2.0](LICENSE)

---

*PaddleOCR / lama / Ollama / Qwen / Gradio 均为开源组件，本项目遵循各自许可证要求。*
