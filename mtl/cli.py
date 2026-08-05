"""命令行入口。

用法示例:
    python cli.py --list-engines
    python cli.py --input ./input --output ./output
    python cli.py --input ./input --profile game_ui --nsfw --until translate
    python cli.py --input ./input --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from . import config as cfgmod
from .errors import MTLError
from .registry import load_all

KINDS = ("ocr", "translate", "inpaint")


def _list_engines() -> int:
    from .registry import REGISTRIES
    for kind in KINDS:
        load_all(kind)
        print(f"[{kind}] " + ", ".join(REGISTRIES[kind].names()) or f"[{kind}] (无)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mtl",
        description="凸显翻译: 泛用型跨语种多任务图像本地化与翻译框架",
    )
    ap.add_argument("--input", "-i", help="输入: 图片/目录/ZIP/PDF")
    ap.add_argument("--output", "-o", help="输出目录 (默认取配置 export.out_dir)")
    ap.add_argument("--config", default=None, help="基础配置文件 (默认 configs/default.yaml)")
    ap.add_argument("--profile", action="append", default=[],
                    help="场景预设: manga_jp2zh|illustration|game_ui|document (可多次)")
    ap.add_argument("--nsfw", action="store_true", help="开启 Uncensored_Mode (无审查模式)")
    ap.add_argument("--until", choices=["preprocess", "classify", "ocr", "translate",
                                        "inpaint", "render", "quality", "export"],
                    help="只运行到指定阶段为止 (审查中间产物)")
    ap.add_argument("--skip", action="append", default=[],
                    choices=["preprocess", "classify", "ocr", "translate",
                             "inpaint", "render", "quality", "export"],
                    help="跳过指定阶段 (可多次)，如 --skip inpaint")
    ap.add_argument("--ocr-engine", help="覆盖 OCR 引擎")
    ap.add_argument("--translate-engine", help="覆盖翻译引擎")
    ap.add_argument("--inpaint-engine", help="覆盖修复引擎")
    ap.add_argument("--glossary", help="术语词典路径 (csv/json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只做输入解析与预分类, 不执行重流程")
    ap.add_argument("--workers", type=int, default=None,
                    help="并行处理页数 (默认取配置 pipeline.workers)")
    ap.add_argument("--list-engines", action="store_true", help="列出全部可挂载引擎")
    ap.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    if args.list_engines:
        return _list_engines()
    if not args.input:
        ap.error("--input 必填 (或使用 --list-engines)")

    try:
        paths = [args.config or cfgmod.default_config_path()]
        for p in args.profile:
            paths.append(cfgmod.profile_path(p))
        if args.nsfw:
            paths.append(cfgmod.nsfw_config_path())
        cfg = cfgmod.load_config(*paths)
    except MTLError as e:
        print(f"[配置错误] {e}", file=sys.stderr)
        return 2

    # 命令行覆盖
    if args.ocr_engine:
        cfg["ocr"]["engine"] = args.ocr_engine
    if args.translate_engine:
        cfg["translate"]["engine"] = args.translate_engine
    if args.inpaint_engine:
        cfg["inpaint"]["engine"] = args.inpaint_engine
    if args.glossary:
        cfg["translate"]["glossary"] = args.glossary
    if args.workers:
        cfg["pipeline"]["workers"] = args.workers
    if args.nsfw:
        cfg["translate"]["uncensored"] = True

    if args.until:
        stages = cfg["pipeline"]["stages"]
        order = ["preprocess", "classify", "ocr", "translate",
                 "inpaint", "render", "quality", "export"]
        for s in stages:
            stages[s] = False
        for s in order:
            stages[s] = True
            if s == args.until:
                break
    for s in args.skip:
        cfg["pipeline"]["stages"][s] = False

    from .pipeline import Pipeline
    pipe = Pipeline(cfg)

    # 审查回调: 打印中间结果
    def _inspect(stage, page, payload):
        if stage == "ocr":
            for r in payload:
                print(f"  [OCR] #{r.index} conf={r.conf:.2f} {r.text!r} {r.bbox}")
        elif stage == "translate":
            for t in payload:
                print(f"  [译] {t.source_text!r} -> {t.translated_text!r}")

    pipe.on(_inspect)

    try:
        results = pipe.run(args.input, out_dir=args.output, dry_run=args.dry_run)
    except MTLError as e:
        print(f"[处理失败] {e}", file=sys.stderr)
        return 1

    print(f"完成: {len(results)} 页")
    for r in results:
        exported = r.meta.get("exported")
        if exported:
            print(f"  页 {r.page.page_index} ({r.page.kind}): {len(exported)} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
