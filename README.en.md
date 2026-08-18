# OmniLingo Canvas

> A multilingual image localization and translation pipeline: **OCR → Translation → Inpainting → Text Rendering → Automated Quality Checks**, delivering finished images in one command.

A general-purpose localization toolchain for four scenarios: manga (JP/KR/EN and more), illustrations and artbooks, game UI, and scanned documents. Every OCR / translation / inpainting engine is **pluggable** — route freely between local open-source models and cloud APIs — and the whole pipeline can run **fully offline** with data staying on your machine.

![Web UI](docs/screenshot.png)

## Features

- **End-to-end automation**: an 8-stage pipeline covering detection, translation, erasure, rendering and automated acceptance in a single command
- **Automated quality loop**: OCR re-check (is the translation actually rendered into the image) + SSIM structural similarity + residual detection (is the source text fully erased); failures re-run inpainting and rendering automatically (up to `max_retries` times)
- **Pluggable engines**: OCR (PaddleOCR / manga-ocr / Tesseract / Baidu / Google Vision), translation (local LLM / OpenAI-compatible API / DeepL / Tencent TMT), inpainting (lama-cleaner / SD WebUI)
- **Local-first**: Ollama / llama.cpp local LLM plus local OCR and inpainting services, works offline; `Uncensored_Mode` (`--nsfw`) routes to local uncensored models (self-hosted use only — content compliance is your responsibility)
- **Scene profiles**: `manga_jp2zh` (right-to-left vertical order), `game_ui` (short and precise, placeholders preserved), `document` (faithful), `illustration` (artistic tone)
- **Context & terminology**: cross-page context window (previous 5 pages by default) keeps names consistent; CSV/JSON glossaries with longest-match-first lookup and case-insensitive support
- **Batch parallelism & stage control**: multi-worker processing; stages toggleable, trimmed with `--until` / `--skip`
- **Web UI**: upload multiple images or pick a folder, live progress logs, original-vs-result gallery, batch monitor panel
- **Engineering-friendly output**: final images (PNG/JPEG) + transparent text layers (drop into Photoshop) + sidecar JSON with source/target text, coordinates and QC report

## Pipeline (8 stages)

`preprocess` (super-resolution, off by default) → `classify` (heuristic: manga_bw / manga_color / illustration / game_ui / document) → `ocr` (recognition + reading order rtl_vertical / ltr_horizontal / auto + noise filtering) → `translate` (task prompts + cross-page context + glossary) → `inpaint` (mask from text regions, dilation + feather, then erasure) → `render` (wrapping, font-size search, auto-vertical in tall boxes, stroke/shadow) → `quality` (checks, auto-retry on failure) → `export` (final image + text layer + sidecar JSON).

## Quick Start

Requirements: Python 3.10+; a GPU is recommended but not required (CPU works, slower).

```bash
pip install -r requirements.txt            # 1) Core dependencies
pip install -r requirements-optional.txt   # 2) Optional engine deps (OCR/PDF; missing engines give a clear hint)
pip install gradio                         # 3) Web UI dependency (required by webui.py)
pip install -e .                           # 4) (Optional) provides the `mtl` command, equivalent to python cli.py
```

Local services (required for the full pipeline):

```bash
ollama pull qwen2.5:7b                                     # Local LLM (default configured model)
lama-cleaner --model lama --device cuda --port 7860        # Inpainting service (use --device cpu without GPU)
```

> PaddleOCR downloads its model weights on first run; afterwards it works fully offline.

## Usage Examples

```bash
python cli.py --list-engines                    # List registered engines (no optional deps needed)
python cli.py --input ./input --dry-run         # Input parsing + page classification (no models)
python cli.py --input ./input --profile game_ui --until classify   # Run only up to classification
python cli.py --input ./input --profile game_ui --output ./output  # Full pipeline (needs PaddleOCR + Ollama + lama-cleaner)
python cli.py --input ./input --until translate # Run only up to translation (inspect intermediates)
python cli.py --input ./input --skip inpaint    # Skip inpainting
python cli.py --input ./input --workers 4       # 4 parallel workers (default 2)
python cli.py --input ./input --glossary ./glossary.csv  # Use your own glossary
python cli.py --input ./input --profile game_ui --nsfw   # Uncensored_Mode (compliance is on you)
```

`--input` accepts a single image, directory, ZIP (optionally password-protected), or PDF (requires PyMuPDF; rasterized at 300 DPI).

Web UI:

```bash
python webui.py        # open http://127.0.0.1:7861 (on Windows you can also double-click start_ui.bat)
```

> If lama-cleaner is not running, the Web UI automatically skips the inpainting stage and logs a warning.

## Engines & Configuration

| Category | Engine | Dependency / Service |
|---|---|---|
| OCR | `paddle` (default) | `pip install paddleocr`; supports both 2.x and 3.x APIs |
| OCR | `manga_ocr` | `pip install manga-ocr`; Japanese manga recognition (detection reuses paddle) |
| OCR | `tesseract` | `pip install pytesseract` + the Tesseract binary |
| OCR | `google_vision` / `baidu` | Env vars `GOOGLE_VISION_API_KEY` / `BAIDU_OCR_API_KEY`, `BAIDU_OCR_SECRET` |
| Translate | `local_llm` (default) | Ollama (127.0.0.1:11434) or llama.cpp server; `api_type: ollama / llama_cpp` |
| Translate | `openai` | Any OpenAI-compatible endpoint; `OPENAI_API_KEY` |
| Translate | `deepl` / `tencent` | `DEEPL_API_KEY` (a `:fx` suffix uses the free endpoint) / `TENCENT_SECRET_ID`, `TENCENT_SECRET_KEY` |
| Inpaint | `lama` (default) | lama-cleaner local service (default port 7860) |
| Inpaint | `sd` | AUTOMATIC1111 WebUI started with `--api` (default port 7861 — see the port-conflict note) |
| Super-res | `realesrgan` (off by default) | External local HTTP service; set its `base_url` in config |

Configuration is a three-layer YAML deep merge: `configs/default.yaml` → `configs/profiles/<scene>.yaml` → `configs/nsfw.yaml` (added by `--nsfw`), with `${ENV_VAR}` expansion — an unset variable aborts startup instead of failing silently. Key keys (all in `default.yaml`): `pipeline.stages.*` / `workers` / `context_pages`; `ocr.engine` / `lang` / `reading_order` / `min_confidence` / `noise_filter.*`; `translate.engine` / `task_type` / `target_lang` / `glossary` / `max_context_chars`; `inpaint.engine` / `mask.*`; `render.effects.*` / `style_map` / `fonts`; `quality.max_retries` / thresholds / `weights`; `export.out_dir` / `formats` (png/json/jpeg) / `save_layers` / `save_masks`. CLI flags (`--ocr-engine` / `--translate-engine` / `--inpaint-engine` / `--glossary` / `--workers`) override config values.

Glossary format (`--glossary` or `translate.glossary`):

```csv
source,target[,kind]      # kind=ci enables case-insensitive matching
英雄,ヒーロー
```

```json
[{"source": "英雄", "target": "ヒーロー", "kind": ""}]
```

**Uncensored_Mode**: `--nsfw` forces the translation engine to the local LLM (optional dedicated `uncensored_model`) and disables all cloud engines (DeepL / Tencent / OpenAI / Google Vision / Baidu); intended for self-hosted local use only.

**Port conflict note**: the SD inpainting engine defaults to port 7861, which collides with the Web UI (`webui.py`). Option A: start SD WebUI with `--port 7862` and override `inpaint.engines.sd.kwargs.base_url: http://127.0.0.1:7862` in config; Option B: change `server_port` in `webui.py`.

## Output Artifacts

Each page gets a `page_XXXX/` directory under `--output`: `<name>.final.png` / `.final.jpg` (finished image), `<name>.data.json` (source/target text, coordinates, confidence, QC report), `layers/<name>.text_layer.png` (transparent text layer), `<name>.mask.png` (mask, when `save_masks: true`).

## Project Layout

```
├── cli.py / webui.py         # CLI entry point / Gradio web UI (port 7861)
├── mtl/
│   ├── cli.py / config.py    # argument parsing / YAML deep merge + ${ENV} expansion + validation
│   ├── pipeline.py           # 8-stage orchestration: parallelism / retry / event callbacks
│   ├── registry.py           # engine registry (lazy loading + @register)
│   ├── ocr/ translate/ inpaint/ render/ quality/ preprocess/ io/
│   └── models.py             # data models
├── configs/                  # default.yaml + nsfw.yaml + profiles/ (four scene presets)
├── tests/test_core.py        # 22 core assertions
├── requirements.txt / requirements-optional.txt
└── docs/                     # commercialization evaluation and other docs
```

## Known Limitations

- The `manga_jp2zh` profile references a glossary file (`configs/glossary/imouto_hentai.csv`) that is **not shipped** with the repository, so using that profile as-is fails at the translate stage. Use the `game_ui` / `document` profiles instead, or provide your own glossary via `--glossary`.
- The Web UI depends on `gradio`, which is not declared in `requirements.txt` / `pyproject.toml` — install it manually (step 3 of Quick Start).
- The page classifier is heuristic (v0.1); the ML engine is a reserved interface. Complex layouts may be misclassified.
- Rendering is Pillow-based (stroke/shadow/adaptive font size), not yet at the level of commercial AI text rendering. Super-resolution is off by default; `realesrgan` needs an external local service.
- Parallel processing loads models per thread (PaddleOCR predictors are not concurrency-safe), costing roughly 1–2 GB RAM per worker.
- The OCR re-check and residual checks depend on an OCR engine being available; when the OCR stage is skipped these checks pass automatically.
- `inputs.pdf.first_page` / `last_page` are declared but not yet wired into the pipeline (v0.1); the SD adapter processes the whole image (tiled processing is planned for a later release).

## Tests

```bash
python tests/test_core.py    # 22 core assertions (config merge / reading order / mask / glossary / layout / classification)
```

## Compliance Statement

This project is a general-purpose image localization framework. You are responsible for ensuring you have the legal right or authorization to process the content you feed into it; self-hosted use with sensitive content is at your own responsibility. For commercial/SaaS scenarios, follow applicable local laws and regulations.

## License

[Apache License 2.0](LICENSE)

---

*PaddleOCR / manga-ocr / Tesseract / lama-cleaner / Ollama / Qwen / Gradio are open-source components; this project complies with their respective licenses.*
