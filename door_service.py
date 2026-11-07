# -*- coding: utf-8 -*-
"""
秒开门 · 本地常驻服务（macOS / Linux 通用，仅 Python 标准库）

    python3 door_service.py              # 前台运行
    ./install.sh                        # 交给 launchd 后台常驻（推荐）

设计目标：Mac mini 上 7x24 常驻，空闲时几乎不占 CPU，内存十几 MB，
不装 pip 包、不装数据库、不装 Web 框架、不开网页里任何外部资源。

对外只暴露高层语义（登录 / 钥匙 / 开门 / 状态），手机端 PWA 不接触协议细节，
因此 iOS / Android / macOS 上看到的界面与操作完全一致。

凭据只写在本机 ~/.quickopen/state.json（权限 0600），不会发到任何第三方。
"""

import hmac
import json
import os
import re
import resource
import secrets
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import door_protocol
from door_protocol import ProtocolError, ProtocolClient, missing_config

VERSION = "2.0.0"
ROOT = Path(__file__).resolve().parent
HOME = Path.home() / ".quickopen"
STATE_FILE = HOME / "state.json"
KEY_FILE = HOME / "access_key"
EVENT_LOG = HOME / "events.log"

PORT = int(os.environ.get("QO_PORT", "8787"))
BIND = os.environ.get("QO_BIND", "0.0.0.0")
TOUCH_INTERVAL = max(120, int(os.environ.get("QO_TOUCH_INTERVAL", "900")))
TOUCH_STALE = max(120, int(os.environ.get("QO_TOUCH_STALE", "1200")))
OPEN_COOLDOWN = 1.2
# external = 官方 gateway2 已被新版 WAF 拦截，改由用户在官方 App 收码（默认，可直接用）
# legacy   = 仍尝试走旧网关（留给以后协议适配 / 官方放开时用）
SMS_PROVIDER = os.environ.get("QO_SMS_PROVIDER", "external")
STARTED_AT = time.time()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}

DEFAULT_STATE = {
    "session_id": "", "user_id": "", "phone": "", "openid": "", "vendor": "samsung",
    "keys": [], "default_key_id": "", "login_at": 0.0, "last_ok_at": 0.0,
    "session_invalid": False,
    "stats": {"open_ok": 0, "open_fail": 0, "last_open_at": 0.0, "last_error": ""},
    "last_upstream": "",
}

_state_lock = threading.RLock()
_events = []
_last_open_at = [0.0]
_last_touch_at = time.time()
_state = {}


# ------------------------------------------------------------------ 持久化
def _load_state():
    global _state
    _state = json.loads(json.dumps(DEFAULT_STATE))
    try:
        if STATE_FILE.exists():
            saved = json.loads(STATE_FILE.read_text("utf-8"))
            for k in DEFAULT_STATE:
                if k in saved:
                    _state[k] = saved[k]
    except Exception as e:
        print("[状态] 读取失败，使用空状态：%s" % e, flush=True)
    if not _state.get("openid"):
        _state["openid"] = secrets.token_hex(8)
        save_state()


def save_state():
    with _state_lock:
        try:
            if not HOME.exists():
                HOME.mkdir(parents=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=2), "utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            print("[状态] 写入失败：%s" % e, flush=True)


def access_key():
    k = os.environ.get("QO_ACCESS_KEY", "").strip()
    if k:
        return k
    try:
        if KEY_FILE.exists():
            return KEY_FILE.read_text("utf-8").strip()
        if not HOME.exists():
            HOME.mkdir(parents=True)
        k = secrets.token_hex(24)
        KEY_FILE.write_text(k, "utf-8")
        os.chmod(KEY_FILE, 0o600)
        print("[安全] 已生成访问密钥：%s" % KEY_FILE, flush=True)
        return k
    except Exception:
        return ""


def log_event(kind, message):
    line = "%s  %-6s  %s" % (time.strftime("%m-%d %H:%M:%S"), kind, message)
    _events.append(line)
    del _events[:-120]
    print(line, flush=True)
    try:
        if not HOME.exists():
            HOME.mkdir(parents=True)
        with EVENT_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def mask(s):
    s = str(s)
    s = re.sub(r"(sessionId[=:\"']+\s*)([A-Za-z0-9:._\-]{6,})", r"\1***", s, flags=re.I)
    s = re.sub(r"\b1[3-9]\d{9}\b", "***手机号***", s)
    return s


def client():
    return ProtocolClient(openid=_state["openid"], vendor=_state.get("vendor") or "samsung")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# -------------------------------------------------------------- 业务动作
def is_auth_error(exc):
    if getattr(exc, "code", 0) in (401, 403):
        return True
    return any(w in str(exc) for w in ("登录", "失效", "过期", "session", "token", "未授权", "重新"))


def handle_auth_failure(exc):
    if is_auth_error(exc):
        with _state_lock:
            _state["session_invalid"] = True
        save_state()
        log_event("警告", "会话已失效，需要在控制面板重新登录")
        return True
    return False


def record_error(exc, context=""):
    """把上游失败完整记下来（脱敏），状态页与日志都能看到，便于应对官方改协议。"""
    detail = mask(getattr(exc, "detail", "") or "")
    endpoint = getattr(exc, "endpoint", "") or ""
    with _state_lock:
        _state["stats"]["last_error"] = str(exc)
        _state["last_upstream"] = (endpoint + " · " + detail).strip(" ·")[:400]
    save_state()
    log_event("错误", "%s失败：%s" % (context or "请求", mask(exc)))
    if detail:
        log_event("上游", detail)


def do_send_code(phone):
    if not re.fullmatch(r"1[3-9]\d{9}", phone or ""):
        raise ProtocolError("手机号格式不正确")
    with _state_lock:
        _state["phone"] = phone
    save_state()
    if SMS_PROVIDER == "legacy":
        try:
            client().send_security_code(phone)
        except ProtocolError as e:
            record_error(e, "发送验证码")
            raise ProtocolError("%s（建议改用官方 App 收码）" % e, e.code, e.detail, e.endpoint)
        log_event("登录", "已向 ***手机号*** 发送短信验证码")
        return {"ok": True, "external": False, "message": "验证码已发送，请查收短信"}
    # 官方 gateway2 在 5.3.x 后加了 WAF 统一验签，旧 appid/appsecret 签名已不被识别。
    # 验证码是服务端按手机号下发的，与用哪个客户端无关，所以由官方 App 取码即可。
    log_event("登录", "使用外部取码：请在官方 App 获取验证码")
    return {"ok": True, "external": True,
            "message": "请在官方「亲邻开门」App 点「获取验证码」，把短信里的码填到下面"}


def do_login(phone, code):
    if not re.fullmatch(r"1[3-9]\d{9}", phone or ""):
        raise ProtocolError("手机号格式不正确")
    if not re.fullmatch(r"\d{4,8}", code or ""):
        raise ProtocolError("验证码应为 4-8 位数字")
    try:
        result = client().login(phone, code)
    except ProtocolError as e:
        record_error(e, "短信登录")
        raise
    with _state_lock:
        _state["session_id"] = result["session_id"]
        _state["user_id"] = result.get("user_id", "")
        _state["phone"] = phone
        _state["login_at"] = time.time()
        _state["last_ok_at"] = time.time()
        _state["session_invalid"] = False
    save_state()
    log_event("登录", "短信登录成功，正在拉取已授权的门禁钥匙")
    keys = do_refresh_keys()
    return {"ok": True, "message": "登录成功，已获取 %d 把钥匙" % len(keys), "keys": keys}


def do_refresh_keys():
    sid = _state.get("session_id")
    if not sid:
        raise ProtocolError("尚未登录")
    try:
        keys = client().load_door_keys(sid)
    except ProtocolError as e:
        record_error(e, "同步钥匙")
        raise
    with _state_lock:
        _state["keys"] = keys
        if keys and _state.get("default_key_id") not in [k["id"] for k in keys]:
            _state["default_key_id"] = keys[0]["id"]
        _state["last_ok_at"] = time.time()
        _state["session_invalid"] = False
    save_state()
    log_event("钥匙", "已同步 %d 把门禁钥匙" % len(keys))
    return keys


def do_touch(force=False):
    sid = _state.get("session_id")
    if not sid:
        return False
    age = time.time() - (_state.get("last_ok_at") or 0)
    if not force and age < TOUCH_STALE:
        return True
    try:
        client().touch(sid)
        with _state_lock:
            _state["last_ok_at"] = time.time()
            _state["session_invalid"] = False
        return True
    except ProtocolError as e:
        handle_auth_failure(e)
        record_error(e, "会话保活")
        return False


def find_key(key_id):
    keys = _state.get("keys") or []
    kid = key_id or _state.get("default_key_id") or (keys[0]["id"] if keys else "")
    for k in keys:
        if k["id"] == kid:
            return k
    return None


def do_open(key_id=None):
    global _last_open_at
    sid = _state.get("session_id")
    if not sid:
        raise ProtocolError("尚未登录，请先在控制面板完成短信登录")
    key = find_key(key_id)
    if not key:
        raise ProtocolError("没有找到可用的门禁钥匙，请点「重新同步钥匙」")

    now = time.time()
    if now - _last_open_at[0] < OPEN_COOLDOWN:
        raise ProtocolError("操作太快，请稍候再按")
    _last_open_at[0] = now

    do_touch(force=False)
    t0 = time.time()
    try:
        message = client().open_door(sid, key)
    except ProtocolError as e:
        with _state_lock:
            _state["stats"]["open_fail"] += 1
        record_error(e, "开门")
        handle_auth_failure(e)
        raise
    ms = int((time.time() - t0) * 1000)
    with _state_lock:
        _state["stats"]["open_ok"] += 1
        _state["stats"]["last_open_at"] = time.time()
        _state["stats"]["last_error"] = ""
        _state["last_ok_at"] = time.time()
        _state["session_invalid"] = False
    save_state()
    log_event("开门", "%s · %s · %dms" % (key["name"], message, ms))
    return {"ok": True, "message": message or "开门指令已发送", "ms": ms, "key": key["name"]}


def status_payload():
    with _state_lock:
        logged_in = bool(_state.get("session_id"))
        st = {
            "ok": True, "version": VERSION, "mode": "quickopen-local",
            "uptime_s": int(time.time() - STARTED_AT),
            "pid": os.getpid(),
            "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1),
            "cpu_pct": round(time.process_time() / max(0.001, time.time() - STARTED_AT) * 100, 2),
            "threads": threading.active_count(),
            "logged_in": logged_in,
            "session_invalid": bool(_state.get("session_invalid")),
            "login_at": _state.get("login_at", 0),
            "last_ok_at": _state.get("last_ok_at", 0),
            "phone_hint": ("***" + _state["phone"][-4:]) if _state.get("phone") else "",
            "keys": _state.get("keys", []),
            "default_key_id": _state.get("default_key_id", ""),
            "stats": dict(_state.get("stats", {})),
            "touch_interval": TOUCH_INTERVAL,
            "next_touch_s": max(0, int(TOUCH_INTERVAL - (time.time() - _last_touch_at))),
            "events": list(_events[-12:]),
            "last_upstream": _state.get("last_upstream", ""),
            "sms_provider": SMS_PROVIDER,
            "config_missing": missing_config(),
            "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    return st


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "QuickOpen/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        try:
            path = str(args[0]).split(" ")[1].split("?")[0] if args else ""
            print("[%s] %s %s" % (self.log_date_time_string(), self.command, path), flush=True)
        except Exception:
            pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authorized(self, query):
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return True
        supplied = self.headers.get("X-Key") or (query.get("k", [""])[0])
        key = access_key()
        return bool(key and supplied and hmac.compare_digest(str(supplied), key))

    def _body(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0:
            return {}
        if n > 64 * 1024:
            raise ValueError("请求体过大")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlsplit(self.path)
        path, query = u.path, parse_qs(u.query)
        if path == "/api/health":
            return self._send(200, {"ok": True, "version": VERSION, "logged_in": bool(_state.get("session_id"))})
        if path.startswith("/api/"):
            if not self._authorized(query):
                return self._send(401, {"ok": False, "message": "访问密钥无效，请用配网链接打开"})
            try:
                if path == "/api/status":
                    return self._send(200, status_payload())
                if path == "/api/keys":
                    return self._send(200, {"ok": True, "keys": _state.get("keys", []),
                                           "default_key_id": _state.get("default_key_id", "")})
                if path == "/api/logs":
                    return self._send(200, {"ok": True, "lines": list(_events[-60:])})
                if path == "/api/diagnose":
                    import diagnose
                    return self._send(200, diagnose.run())
                if path == "/api/onboard":
                    key = access_key()
                    return self._send(200, {"ok": True, "key": key,
                                           "link": "http://%s:%d/#k=%s" % (lan_ip(), PORT, key)})
                return self._send(404, {"ok": False, "message": "接口不存在"})
            except Exception as e:
                return self._send(500, {"ok": False, "message": str(e)})

        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (ROOT / rel).resolve()
        if ROOT not in target.parents and target != ROOT:
            return self._send(403, "forbidden", "text/plain; charset=utf-8")
        if not target.is_file():
            target = ROOT / "index.html"
        cache = "no-cache" if target.suffix in (".html", ".webmanifest") else "public, max-age=604800"
        self._send(200, target.read_bytes(), MIME.get(target.suffix.lower(), "application/octet-stream"), cache)

    def do_POST(self):
        u = urlsplit(self.path)
        path, query = u.path, parse_qs(u.query)
        if not path.startswith("/api/"):
            return self._send(404, {"ok": False, "message": "接口不存在"})
        if not self._authorized(query):
            return self._send(401, {"ok": False, "message": "访问密钥无效，请用配网链接打开"})
        try:
            payload = self._body()
        except Exception:
            return self._send(400, {"ok": False, "message": "请求体不是合法 JSON"})

        try:
            if path == "/api/send-code":
                return self._send(200, do_send_code(payload.get("phone", "")))
            if path == "/api/login":
                return self._send(200, do_login(payload.get("phone", ""), payload.get("code", "")))
            if path == "/api/refresh-keys":
                return self._send(200, {"ok": True, "keys": do_refresh_keys()})
            if path == "/api/open":
                return self._send(200, do_open(payload.get("key_id")))
            if path == "/api/touch":
                return self._send(200, {"ok": do_touch(force=True), "message": "已刷新会话"})
            if path == "/api/logout":
                with _state_lock:
                    _state["session_id"] = ""
                    _state["keys"] = []
                    _state["session_invalid"] = False
                save_state()
                log_event("登录", "已退出，凭据已清除")
                return self._send(200, {"ok": True, "message": "已退出登录"})
            if path == "/api/set-default":
                kid = payload.get("key_id", "")
                if not find_key(kid):
                    raise ProtocolError("钥匙不存在")
                with _state_lock:
                    _state["default_key_id"] = kid
                save_state()
                return self._send(200, {"ok": True, "message": "已设为默认门"})
            return self._send(404, {"ok": False, "message": "接口不存在"})
        except ProtocolError as e:
            return self._send(200, {"ok": False, "message": str(e), "code": e.code})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"ok": False, "message": "服务内部错误：%s" % type(e).__name__})


# -------------------------------------------------------------- 保活线程
def keepalive_loop():
    global _last_touch_at
    while True:
        time.sleep(TOUCH_INTERVAL)
        _last_touch_at = time.time()
        if not _state.get("session_id"):
            continue
        try:
            do_touch(force=True)
        except Exception as e:
            log_event("错误", "保活异常：%s" % mask(e))


def main():
    if not door_protocol.aes_selftest():
        print("致命错误：AES 自检未通过，服务拒绝启动（避免用错误的密文登录）", file=sys.stderr)
        sys.exit(2)
    _missing = missing_config()
    if _missing:
        print("[配置] 警告：以下协议配置缺失，开门功能将不可用：%s" % ", ".join(_missing), flush=True)
        print("[配置] 请复制 protocol_config.example.py 为 protocol_config.py 并填写。", flush=True)
    if not HOME.exists():
        HOME.mkdir(parents=True)
    _load_state()
    key = access_key()
    print("=" * 66, flush=True)
    print("  秒开门 · 本地常驻服务  v%s" % VERSION, flush=True)
    print("=" * 66, flush=True)
    print("  本机面板： http://127.0.0.1:%d" % PORT, flush=True)
    print("  手机配网： http://%s:%d/#k=%s" % (lan_ip(), PORT, key), flush=True)
    print("  登录状态： %s" % ("已登录（%d 把钥匙）" % len(_state.get("keys", []))
                             if _state.get("session_id") else "待登录"), flush=True)
    print("  保活间隔： %d 秒 · 后台线程（空闲不占 CPU）" % TOUCH_INTERVAL, flush=True)
    print("  凭据文件： %s (0600)" % STATE_FILE, flush=True)
    print("  停止服务： Ctrl+C  或  ./uninstall.sh", flush=True)
    print("=" * 66, flush=True)
    log_event("启动", "服务已启动 v%s" % VERSION)
    threading.Thread(target=keepalive_loop, daemon=True, name="keepalive").start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever(poll_interval=1.0)
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
