#!/bin/bash
# 命令行快速检视状态（图形界面请看菜单栏图标，或打开网页控制面板）
PORT="${QO_PORT:-8787}"
/usr/bin/curl -fsS --max-time 3 "http://127.0.0.1:$PORT/api/status" | /usr/bin/python3 -c '
import json,sys,time
try: j=json.load(sys.stdin)
except Exception: print("服务未响应"); sys.exit(1)
def t(x): return time.strftime("%m-%d %H:%M",time.localtime(x)) if x else "—"
print("服务     :", "在线  v%s  PID %s"%(j.get("version"),j.get("pid")))
print("运行时长 :", "%d 分"%(j.get("uptime_s",0)//60))
print("资源占用 :", "%s MB 内存 / CPU %s%% / %s 线程"%(j.get("rss_mb"),j.get("cpu_pct"),j.get("threads")))
print("登录     :", ("已登录" if j.get("logged_in") else "未登录")+("（会话失效，请重新登录）" if j.get("session_invalid") else ""))
print("账号     :", j.get("phone_hint") or "—", " 登录于", t(j.get("login_at")))
print("钥匙     :", len(j.get("keys",[])), "把，默认", j.get("default_key_id") or "—")
s=j.get("stats",{})
print("开门统计 :", "成功 %s / 失败 %s，最近 %s"%(s.get("open_ok",0),s.get("open_fail",0),t(s.get("last_open_at"))))
print("最近事件 :")
for line in j.get("events",[])[-5:]: print("   ",line)
' || echo "服务未运行。查看日志： tail -50 ~/.quickopen/logs/service.log"
