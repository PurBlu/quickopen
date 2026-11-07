#!/bin/bash
# 卸载后台服务与菜单栏工具。保留 ~/.quickopen 里的登录凭据与日志，方便重装后免登录。
set -u
for L in cn.quickopen.menubar cn.quickopen.door; do
  P="$HOME/Library/LaunchAgents/$L.plist"
  launchctl bootout "gui/$(id -u)/$L" >/dev/null 2>&1 || true
  launchctl unload -w "$P" >/dev/null 2>&1 || true
  rm -f "$P"
done
pkill -f "QuickOpenBar.app/Contents/MacOS/QuickOpenBar" 2>/dev/null || true
echo "已停止并卸载后台服务与菜单栏工具。"
echo "凭据与日志仍在 ~/.quickopen （如需彻底清除： rm -rf ~/.quickopen，此操作会要求重新登录）"
