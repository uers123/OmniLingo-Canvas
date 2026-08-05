"""核心逻辑测试（无第三方重依赖）。

运行: python tests/test_core.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtl import config as cfgmod
from mtl.inpaint.mask import build_mask
from mtl.models import TextRegion
from mtl.ocr.reading_order import compute_reading_order
from mtl.render.fonts import FontRegistry
from mtl.render.layout import fit_font_size, wrap_text
from mtl.translate.glossary import Glossary

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def t_config_merge_and_env():
    print("config: 深合并 + 环境变量展开")
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "base.yaml")
        overlay = os.path.join(td, "overlay.yaml")
        with open(base, "w", encoding="utf-8") as f:
            f.write(
                "pipeline:\n  stages:\n    ocr: true\n"
                "ocr:\n  engine: paddle\n  engines:\n    paddle:\n      module: m\n      kwargs: {lang: jp}\n    manga_ocr:\n      module: m\n      kwargs: {}\n"
                "translate:\n  engine: local_llm\n  engines:\n    local_llm:\n      module: m\n      kwargs: {model: x}\n"
                "inpaint:\n  engine: lama\n  engines:\n    lama:\n      module: m\n      kwargs: {}\n"
                "render:\n  target_lang: zh-CN\n"
                "export:\n  out_dir: ./o\n"
                "key: ${TEST_MTL_VAR}\n"
            )
        with open(overlay, "w", encoding="utf-8") as f:
            f.write("ocr:\n  engine: manga_ocr\nrender:\n  target_lang: en-US\n")
        os.environ["TEST_MTL_VAR"] = "hello"
        cfg = cfgmod.load_config(base, overlay)
        check("字典深合并(ocr.engine 被覆盖)", cfg["ocr"]["engine"] == "manga_ocr")
        check("字典深合并(未覆盖键保留)", cfg["ocr"]["engines"]["paddle"]["kwargs"]["lang"] == "jp")
        check("标量覆盖", cfg["render"]["target_lang"] == "en-US")
        check("环境变量展开", cfg["key"] == "hello")
        del os.environ["TEST_MTL_VAR"]
        try:
            cfgmod.load_config(base)
            check("缺失环境变量报错", False)
        except cfgmod.ConfigError:
            check("缺失环境变量报错", True)


def t_reading_order():
    print("reading_order: LTR / RTL")
    r1 = TextRegion(polygon=[(0, 0), (50, 0), (50, 20), (0, 20)], text="A")
    r2 = TextRegion(polygon=[(60, 0), (110, 0), (110, 20), (60, 20)], text="B")
    r3 = TextRegion(polygon=[(0, 40), (50, 40), (50, 60), (0, 60)], text="C")
    ordered = compute_reading_order([r3, r2, r1], mode="ltr_horizontal")
    check("LTR 行内从左到右", [r.index for r in ordered] == [0, 1, 2]
          and ordered[0].text == "A" and ordered[1].text == "B")
    check("LTR 行间自上而下", ordered[2].text == "C")

    # RTL: 右侧一列先读
    left = TextRegion(polygon=[(0, 0), (40, 0), (40, 60), (0, 60)], text="左")
    right = TextRegion(polygon=[(80, 0), (120, 0), (120, 60), (80, 60)], text="右")
    ordered = compute_reading_order([left, right], mode="rtl_vertical")
    check("RTL 右列优先", ordered[0].text == "右" and ordered[1].text == "左")

    ordered = compute_reading_order([left, right], mode="auto", source_lang="jp")
    check("auto 日文走 RTL", ordered[0].text == "右")


def t_mask():
    print("mask: 生成/膨胀/羽化")
    from PIL import Image
    r = TextRegion(polygon=[(10, 10), (30, 10), (30, 30), (10, 30)])
    mask = build_mask((50, 50), [r], dilation_px=0, feather=0)
    px = mask.load()
    check("多边形内部为白", px[20, 20] == 255)
    check("多边形外部为黑", px[45, 45] == 0)
    mask_d = build_mask((50, 50), [r], dilation_px=2, feather=0)
    pd = mask_d.load()
    check("膨胀后覆盖到边缘外", pd[8, 8] == 255 and pd[4, 4] == 0)
    mask_f = build_mask((50, 50), [r], dilation_px=0, feather=2)
    check("羽化产生中间灰度", mask_f.getpixel((20, 6)) not in (0, 255))


def t_glossary():
    print("glossary: 加载/命中/长词优先替换")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "g.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("英雄,ヒーロー\n英雄王,キング\n")
        g = Glossary.load(p)
        check("命中收集", set(g.lookup("英雄王の物語")) == {"ヒーロー", "キング"})
        out = g.apply("英雄王と英雄")
        check("长词优先替换", out == "キングとヒーロー")
        check("未命中原样", g.apply("普通の文") == "普通の文")


def t_layout():
    print("layout: 换行 + 字号适配")
    reg = FontRegistry()
    box = (0, 0, 120, 60)
    size, lines = fit_font_size("这是一个比较长的中文测试文本", box, reg,
                                script="zh", style="regular", min_size=8, max_size=40)
    check("字号适配成功", size is not None and size > 0)
    font = reg.load("zh", "regular", size)
    w = max(font.getlength(l) for l in lines)
    check("每行不超框宽", w <= 120 * 0.95 + 1)
    check("总行高不超框高", len(lines) * size * 1.35 <= 60 * 0.95 + 1)
    words = wrap_text("hello world foo bar baz", font, 60)
    check("拉丁按词断行", all(len(x.split()) <= 2 for x in words) and
          "".join(words).replace(" ", "") == "helloworldfoobarbaz")


def t_classifier():
    print("classifier: 启发式分类")
    from PIL import Image, ImageDraw
    from mtl.models import Page
    # 黑白页: 白底 + 黑块
    img = Image.new("RGB", (400, 600), "white")
    d = ImageDraw.Draw(img)
    for i in range(20):
        d.rectangle([i * 15, 50, i * 15 + 8, 70], fill="black")
    from mtl.preprocess.classifier import classify_page
    page = Page(page_index=0, image=img, width=400, height=600)
    kind = classify_page(page)
    check("黑白文档页分类", kind in ("manga_bw", "document"))
    # 全彩柔和渐变
    img2 = Image.new("RGB", (400, 600))
    for y in range(600):
        for x in range(400):
            img2.putpixel((x, y), (x % 256, (x + y) % 256, y % 256))
    page2 = Page(page_index=1, image=img2, width=400, height=600)
    kind2 = classify_page(page2)
    check("彩图分类为彩色类", kind2 in ("manga_color", "illustration"))


def main():
    print("== mtl core tests ==")
    t_config_merge_and_env()
    t_reading_order()
    t_mask()
    t_glossary()
    t_layout()
    t_classifier()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
