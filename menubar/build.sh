#!/bin/bash
# 编译 macOS 菜单栏小工具（零第三方依赖，只需要 Xcode 命令行工具里的 swiftc）
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/QuickOpenBar.app"

if ! command -v swiftc >/dev/null 2>&1; then
  echo "未找到 swiftc。请先运行： xcode-select --install"
  exit 1
fi

mkdir -p "$APP/Contents/MacOS"
echo "编译菜单栏工具…"
swiftc -O -o "$APP/Contents/MacOS/QuickOpenBar" "$DIR/QuickOpenBar.swift" -framework Cocoa
cp "$DIR/Info.plist" "$APP/Contents/Info.plist"
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "完成：$APP"
