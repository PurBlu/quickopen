#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 PWA / 主屏幕图标（透明背景、纯单色、高对比度）。

    python3 make_icons.py

设计来源：Tabler Icons 的 `door-exit`（MIT，https://github.com/tabler/tabler-icons），
做了安全区内缩与加粗处理。刻意只用纯黑 / 纯白两色、无渐变、无细碎元素，
保证灰度化或缩到 48px 时门框与箭头依然分明。

浅色版（深色字形）用于 Android maskable / 浅色启动器；
深色版（白色字形 + 深色描边光晕）用于 iOS 主屏幕与深色背景 —— 光晕让它在
「透明被填成黑色」或「填成白色」两种系统行为下都保持可读。

栅格化用 macOS 自带的 sips，无需 Pillow / cairosvg / ImageMagick。
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TMP = Path("/tmp/qo_icon_build")
if not TMP.exists():
    TMP.mkdir(parents=True)

# 24x24 网格；相对官方路径做了轻微内缩，留出 maskable 安全区
PATHS = [
    "M4 21h16",                          # 地面线
    "M6 21V5a2 2 0 0 1 2-2h6.5",        # 门框（左 + 顶）
    "M14.5 12.5V21",                     # 右侧门框，留出通行缺口
    "M14 7h6",                           # 箭头杆
    "M17.5 4.5L20 7l-2.5 2.5",          # 箭头尖
]
SAFE = '<g transform="translate(2.64 2.64) scale(0.78)">'


def paths_svg(color, width):
    body = "".join('<path d="%s"/>' % p for p in PATHS)
    return (SAFE + '<g fill="none" stroke="%s" stroke-width="%s" '
            'stroke-linecap="round" stroke-linejoin="round">%s</g></g>'
            % (color, width, body))


def svg_doc(size, inner, extra_style=""):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 24 24">%s%s</svg>'
            % (size, size, "<style>%s</style>" % extra_style if extra_style else "", inner))


def write(name, content):
    (ROOT / name).write_text(content, "utf-8")
    print("  %-26s %5d B" % (name, len(content.encode("utf-8"))))


def png_from_svg(svg_text, size, out_name):
    src = TMP / ("src_%d.svg" % size)
    out = ROOT / out_name
    src.write_text(svg_text, "utf-8")
    r = subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise SystemExit("sips 栅格化失败：%s\n%s" % (out_name, r.stderr))
    print("  %-26s %5d B  (%dx%d, 透明通道)" % (out_name, out.stat().st_size, size, size))


def main():
    print("生成图标（来源：Tabler Icons door-exit, MIT）")

    # 1. 浏览器 favicon：跟随系统深浅色自动切换，背景透明
    favicon_style = (
        ".g{fill:none;stroke:#FFFFFF;stroke-width:2.4;stroke-linecap:round;"
        "stroke-linejoin:round}"
        "@media (prefers-color-scheme: light){.g{stroke:#0B1120}}"
    )
    favicon_inner = SAFE + '<g class="g">' + "".join('<path d="%s"/>' % p for p in PATHS) + "</g></g>"
    write("icon.svg", svg_doc(512, favicon_inner, favicon_style))

    # 2. 浅色启动器：纯深色单色字形，透明背景
    dark_svg = lambda s: svg_doc(s, paths_svg("#0B1120", "2.4"))
    write("icon-dark.svg", dark_svg(512))

    # 3. 深色 / iOS：白色字形 + 深色光晕，透明背景，任何底色都可读
    def light_inner():
        return paths_svg("#0B1120", "4.0") + paths_svg("#FFFFFF", "2.4")
    light_svg = lambda s: svg_doc(s, light_inner())
    write("icon-light.svg", light_svg(512))

    for size in (192, 512):
        png_from_svg(dark_svg(size), size, "icon-%d.png" % size)
        png_from_svg(light_svg(size), size, "icon-light-%d.png" % size)
    png_from_svg(dark_svg(512), 512, "icon-mono-512.png")  # Android 主题单色图标
    png_from_svg(light_svg(180), 180, "apple-touch-icon.png")

    print("完成。全部为透明背景、纯黑白、无渐变。")


if __name__ == "__main__":
    main()
