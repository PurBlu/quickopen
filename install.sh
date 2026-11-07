#!/bin/bash
# 秒开门 · 一键安装为 macOS 后台服务（launchd LaunchAgent）
# 用法： ./install.sh        可用 QO_PORT / QO_PYTHON / QO_TOUCH_INTERVAL 覆盖默认值
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${QO_PORT:-8787}"
TOUCH="${QO_TOUCH_INTERVAL:-900}"
LABEL="cn.quickopen.door"
BAR_LABEL="cn.quickopen.menubar"
CONF="$HOME/.quickopen"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="$AGENTS/$LABEL.plist"
BAR_PLIST="$AGENTS/$BAR_LABEL.plist"
APP="$DIR/menubar/QuickOpenBar.app"

if [[ -n "${QO_PYTHON:-}" ]]; then
  PY="$QO_PYTHON"
elif [[ -x /usr/bin/python3 ]] && /usr/bin/python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)' 2>/dev/null; then
  PY="/usr/bin/python3"
else
  PY="$(command -v python3)"
fi

echo "==> 自检协议层"
"$PY" "$DIR/selftest.py" >/dev/null 2>&1 || { echo "自检未通过，请先手动运行： $PY $DIR/selftest.py"; exit 1; }
echo "    通过（${PY}）"

mkdir -p "$CONF/logs" "$AGENTS"
if [[ ! -f "$CONF/access_key" ]]; then
  "$PY" -c 'import os,secrets,pathlib;p=pathlib.Path.home()/".quickopen"/"access_key";p.write_text(secrets.token_hex(24));os.chmod(p,0o600)'
fi
chmod 600 "$CONF/access_key"
KEY="$(cat "$CONF/access_key")"

echo "==> 写入后台服务配置"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>$DIR/door_service.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>QO_PORT</key><string>$PORT</string>
    <key>QO_BIND</key><string>0.0.0.0</string>
    <key>QO_TOUCH_INTERVAL</key><string>$TOUCH</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>$CONF/logs/service.log</string>
  <key>StandardErrorPath</key><string>$CONF/logs/service.log</string>
</dict></plist>
EOF
plutil -lint "$PLIST" >/dev/null

echo "==> 编译菜单栏小工具"
if command -v swiftc >/dev/null 2>&1; then
  if bash "$DIR/menubar/build.sh" >/dev/null 2>&1; then
    BIN="$APP/Contents/MacOS/QuickOpenBar"
    cat > "$BAR_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$BAR_LABEL</string>
  <key>ProgramArguments</key><array><string>$BIN</string></array>
  <key>EnvironmentVariables</key><dict><key>QO_PORT</key><string>$PORT</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
</dict></plist>
EOF
    plutil -lint "$BAR_PLIST" >/dev/null
    echo "    已生成 ${APP}"
  else
    echo "    编译失败，服务本身不受影响；稍后可运行 bash ${DIR}/menubar/build.sh"
  fi
else
  echo "    未安装 swiftc，跳过（xcode-select --install 后重跑本脚本即可）"
fi

echo "==> 注册到 launchd"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)/$BAR_LABEL" >/dev/null 2>&1 || true
REG=0
if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then REG=1; else
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  launchctl load -w "$PLIST" >/dev/null 2>&1 && REG=1 || true
fi
if [[ -f "$BAR_PLIST" ]]; then
  if ! launchctl bootstrap "gui/$(id -u)" "$BAR_PLIST" 2>/dev/null; then
    launchctl load -w "$BAR_PLIST" >/dev/null 2>&1 || open -a "$APP" >/dev/null 2>&1 || true
  fi
fi

echo "==> 等待服务就绪"
OK=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if /usr/bin/curl --noproxy '*' -fsS --max-time 1 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then OK=1; break; fi
  sleep 0.3
done

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)"

echo
echo "=================================================================="
if [[ "$OK" == 1 ]]; then
  echo "  安装完成 · 后台服务已常驻，菜单栏小锁图标已出现"
else
  echo "  配置文件已写好，但当前会话无法立即注册 launchd"
  echo "  （从 IDE / 自动化终端执行时会遇到 Input/output error）"
  echo
  echo "  → 双击同目录的「一键安装.command」即可立刻生效；"
  echo "    或者注销 / 重启一次，LaunchAgents 会在登录时自动加载。"
fi
echo "------------------------------------------------------------------"
echo "  本机控制面板：  http://127.0.0.1:$PORT"
echo "  手机配网链接：  http://$IP:$PORT/#k=$KEY"
echo
echo "  在 iPhone / Android 浏览器打开上面这条【配网链接】，"
echo "  再用「添加到主屏幕」，即可获得和 Mac 完全一样的一键开门界面。"
echo "  首次登录：在官方「亲邻开门」App 点「获取验证码」，"
echo "            把收到的码填进本服务的「设置」页即可（只需一次）。"
echo "------------------------------------------------------------------"
echo "  查看状态：  ./status.sh   或双击「查看状态.command」"
echo "  协议体检：  双击「协议体检.command」（官方改协议时用它定位）"
echo "  查看日志：  tail -f $CONF/logs/service.log"
echo "  卸载：      ./uninstall.sh"
echo "=================================================================="
