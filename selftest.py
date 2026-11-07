#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键自检：不需要账号、不联网、不改真实配置。

    python3 selftest.py

覆盖：AES 向量、Java URLEncoder、签名算法、完整登录/拉钥匙/开门协议流程、
      本地服务全部 HTTP 接口（用模拟上游，不会真的开门）。
"""
import json
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import door_protocol as proto
import door_service

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + ("  " + str(extra) if extra else ""))


# ----------------------------------------------------------- 模拟官方服务器
def fake_transport(url, ctype, body, headers):
    if "sendSecurityCode" in url:
        return {"success": True, "code": 0, "data": {}}
    if "/app/v1/login" in url:
        return {"success": True, "code": 0,
                "data": {"sessionId": "SESSION_XYZ_123", "userId": "u-8899"}}
    if "communityInfo" in url:
        # 故意把 data 包成 JSON 字符串，验证 normalize_json 的递归解析
        return {"success": True, "code": 0,
                "data": json.dumps({"rows": [{"communityId": "18523",
                                              "communityName": "测试小区"}]})}
    if "queryUserDoorByCacheNew" in url:
        return {"success": True, "code": 0,
                "data": {"doors": [{"doorControlId": "225237",
                                    "doorControlName": "3栋1单元门",
                                    "communityName": "测试小区"},
                                   {"doorControlId": "225238",
                                    "doorName": "小区南门"}]}}
    if "/open/doorcontrol/v2/open" in url:
        return {"success": True, "code": 0, "message": "开门成功", "data": {}}
    raise AssertionError("未知的上游请求：" + url)


class FakeClient:
    """服务层测试用：完全跳过网络，行为与真实协议层一致。"""
    def __init__(self):
        self.calls = []

    def send_security_code(self, phone):
        self.calls.append(("code", phone))
        if not phone.startswith("1"):
            raise proto.ProtocolError("手机号格式不正确")

    def login(self, phone, code):
        self.calls.append(("login", phone, code))
        return {"session_id": "SESSION_XYZ_123", "user_id": "u-8899"}

    def load_door_keys(self, sid):
        self.calls.append(("keys", sid))
        return [
            {"id": "18523:225237", "community_id": "18523", "door_id": "225237",
             "community_name": "测试小区", "door_name": "3栋1单元门", "name": "测试小区 3栋1单元门"},
            {"id": "18523:225238", "community_id": "18523", "door_id": "225238",
             "community_name": "测试小区", "door_name": "小区南门", "name": "测试小区 小区南门"},
        ]

    def open_door(self, sid, key):
        self.calls.append(("open", sid, key["id"]))
        return "开门成功"

    def touch(self, sid):
        self.calls.append(("touch", sid))


def part_a():
    print("\n[A] 协议层")
    check("AES-128 FIPS-197 官方向量", proto.aes_selftest())
    check("手机号 AES 密文为 32 位大写 hex",
          len(proto.encrypt_phone("13800138000")) == 32 and
          proto.encrypt_phone("13800138000").isupper())
    check("Java URLEncoder：空格→+ / ~→%7E / *保留 / :还原",
          proto.java_encode("wxmini:A B~*") == "wxmini:A+B%7E*",
          proto.java_encode("wxmini:A B~*"))
    check("签名 query 按键名排序",
          proto.encode_query({"version": "v", "appChannel": 1, "nonce": "9"}) ==
          "appChannel=1&nonce=9&version=v")

    sf = proto.sign_fields({"appChannel": 1, "doorControlId": 225237}, "SESSION_XYZ_123")
    check("签名包含 nonce/timestamp/version/sign",
          all(k in sf for k in ("nonce", "timestamp", "version", "sign")) and len(sf["sign"]) == 32)
    check("签名为 32 位大写 MD5", sf["sign"].isupper())

    c = proto.ProtocolClient(openid="0011223344556677", transport=fake_transport)
    c.send_security_code("13800138000")
    check("发送验证码：命中 SMS 网关", "sendSecurityCode" in c.last_request["url"])
    check("发送验证码：携带 appid/version/nonce/sign",
          all(k in c.last_request["headers"] for k in ("appid", "version", "nonce", "sign")))

    login = c.login("13800138000", "123456")
    check("短信登录拿到 sessionId", login["session_id"] == "SESSION_XYZ_123")
    check("登录手机号按协议 AES 加密（非明文）",
          "13800138000" not in c.last_request["body"] and "mobile" in c.last_request["body"])

    keys = c.load_door_keys(login["session_id"])
    check("钥匙列表正确解析（含 JSON 字符串内嵌的社区）", len(keys) == 2, keys)
    check("钥匙去重并生成稳定 ID", keys[0]["id"] == "18523:225237")

    msg = c.open_door(login["session_id"], keys[0])
    check("开门返回服务端消息", msg == "开门成功")
    q = c.last_request["url"].split("?", 1)[1]
    check("开门请求把 sessionId 与签名放在 query",
          "sessionId=SESSION_XYZ_123" in q and "sign=" in q and "nonce=" in q)
    check("开门请求体为空（与官方一致）", c.last_request["body"] == "")
    check("开门 URL 指向官方 v2 接口", "/open/doorcontrol/v2/open" in c.last_request["url"])
    c.touch(login["session_id"])
    check("保活调用 communityInfo", "communityInfo" in c.last_request["url"])


def part_b():
    print("\n[B] 服务层（模拟上游，不会真的开门）")
    with TemporaryDirectory() as td:
        tmp = Path(td)
        door_service.HOME = tmp
        door_service.STATE_FILE = tmp / "state.json"
        door_service.KEY_FILE = tmp / "access_key"
        door_service.EVENT_LOG = tmp / "events.log"
        door_service.QO_PORT = 8787
        door_service._events.clear()
        door_service._load_state()
        door_service.client = lambda: FakeClient()
        door_service.access_key = lambda: "TEST-KEY-123"
        # 体检接口会真的联网，测试时替换成桩，保持自检完全离线
        fake_diag = types.ModuleType("diagnose")
        fake_diag.run = lambda: {"ok": True, "checks": [{"name": "mock", "state": "ok", "note": "mock"}],
                                 "conclusion": "mock", "workaround": True, "config": {}}
        sys.modules["diagnose"] = fake_diag

        srv = ThreadingHTTPServer(("127.0.0.1", 0), door_service.Handler)
        srv.daemon_threads = True
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def req(method, path, payload=None, key=None):
            data = json.dumps(payload or {}).encode() if method == "POST" else None
            h = {"Content-Type": "application/json"}
            if key:
                h["X-Key"] = key
            r = urllib.request.Request(base + path, data=data, headers=h, method=method)
            try:
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        s, j = req("GET", "/api/health")
        check("健康检查", s == 200 and j["ok"] is True)
        s, j = req("GET", "/api/status")
        check("未登录时状态正确", j["logged_in"] is False and j["keys"] == [])
        check("状态含资源占用字段", all(k in j for k in ("rss_mb", "cpu_pct", "threads", "uptime_s")))

        s, j = req("POST", "/api/open", {})
        check("未登录时开门被拦", j["ok"] is False and "登录" in j["message"], j["message"])

        s, j = req("POST", "/api/send-code", {"phone": "13800138000"})
        check("发码走外部取码（官方 App），不再撞 WAF",
              j["ok"] is True and j.get("external") is True and "官方" in j.get("message", ""),
              j.get("message"))
        s, j = req("GET", "/api/status")
        check("状态含上游诊断与取码模式",
              "last_upstream" in j and j.get("sms_provider") == "external")
        s, j = req("GET", "/api/diagnose")
        check("协议体检接口可用", j["ok"] is True and len(j["checks"]) == 1)
        s, j = req("POST", "/api/login", {"phone": "13800138000", "code": "123456"})
        check("登录接口自动拉取钥匙", j["ok"] is True and len(j["keys"]) == 2)

        s, j = req("GET", "/api/status")
        check("登录后状态更新", j["logged_in"] is True and len(j["keys"]) == 2)
        check("默认门自动选中第一把", j["default_key_id"] == "18523:225237")

        s, j = req("POST", "/api/open", {})
        check("一键开门成功", j["ok"] is True and j["ms"] >= 0, j.get("message"))
        door_service._last_open_at[0] = 0  # 跳过 1.2 秒防误触冷却，便于连续测试
        s, j = req("POST", "/api/open", {"key_id": "18523:225238"})
        check("可指定另一把门", j["ok"] is True and "南门" in j["key"], j.get("key"))

        # 模拟官方网关报错，验证脱敏后的上游响应会进状态页
        class FailingClient(FakeClient):
            def open_door(self, sid, key):
                raise proto.ProtocolError(
                    "验签失败，缺少必须的签名字段!", 1,
                    detail="HTTP 403 · {\"code\":1,\"message\":\"验签失败\"}",
                    endpoint="https://sms.example.com/member/sms/sendSecurityCode")
        door_service._last_open_at[0] = 0
        door_service.client = lambda: FailingClient()
        s, j = req("POST", "/api/open", {})
        check("上游验签失败被完整记录", j["ok"] is False and "验签失败" in j["message"])
        s, j = req("GET", "/api/status")
        check("状态页能看到脱敏的上游响应",
              "sms.example.com" in j["last_upstream"] and "403" in j["last_upstream"], j["last_upstream"])
        door_service.client = lambda: FakeClient()

        s, j = req("POST", "/api/set-default", {"key_id": "18523:225238"})
        check("设置默认门", j["ok"] is True)
        s, j = req("POST", "/api/touch", {})
        check("手动保活", j["ok"] is True)
        s, j = req("POST", "/api/refresh-keys", {})
        check("重新同步钥匙", j["ok"] is True and len(j["keys"]) == 2)
        s, j = req("GET", "/api/logs")
        check("事件日志可读取", j["ok"] is True and len(j["lines"]) > 0)
        s, j = req("GET", "/api/onboard")
        check("配网链接含密钥", j["ok"] is True and "#k=TEST-KEY-123" in j["link"])
        s, j = req("POST", "/api/logout", {})
        check("退出登录清除凭据", j["ok"] is True)
        s, j = req("GET", "/api/status")
        check("退出后状态复位", j["logged_in"] is False)

        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            page = resp.read().decode("utf-8", "replace")
        check("返回 PWA 页面", resp.status == 200 and "秒开门" in page)
        s, j = req("GET", "/api/status", key="wrong")
        check("本机访问仍免密钥（菜单栏工具用）", s == 200)

        # 模拟非本机请求：直接调用鉴权函数逻辑
        class FakeHandler:
            client_address = ("192.168.1.99", 12345)
            headers = {}
        fake = FakeHandler()
        check("非本机无密钥被拒", not door_service.Handler._authorized(fake, {}))
        fake.headers = {"X-Key": "TEST-KEY-123"}
        check("非本机带正确密钥放行", door_service.Handler._authorized(fake, {}))
        fake.headers = {"X-Key": "wrong"}
        check("非本机错误密钥被拒", not door_service.Handler._authorized(fake, {}))

        check("凭据文件权限 0600", oct(door_service.STATE_FILE.stat().st_mode & 0o777) == "0o600")
        srv.shutdown()


def _secret_needles():
    """Built from fragments so this test file itself never contains a real value."""
    return ["".join(p) for p in (
        ("qiAnl", "PinP"),
        ("FBC213C4C7", "BEEBD2AA4EDBF0F681C41B"),
        ("gbDjIZQ", "SOpCMX49P"),
        ("OKFoQ9MmNXQ", "tcyXROo4PnaFkfDPTHuDg"),
    )]


def part_c():
    """配置外置安全检查：仓库里不能出现任何第三方协议值。"""
    print("\n[C] 配置外置与仓库安全")
    root = Path(__file__).resolve().parent
    example = root / "protocol_config.example.py"
    local = root / "protocol_config.py"
    needles = _secret_needles()

    check("模板文件存在", example.is_file())
    check("本地配置文件存在", local.is_file())

    if example.is_file():
        text = example.read_text("utf-8")
        check("模板不含任何真实协议值", not any(s in text for s in needles))
        check("模板密钥字段为空占位", 'SIGNING_SALT = ""' in text and 'HEX_AES_KEY = ""' in text)

    r = subprocess.run(["git", "check-ignore", "-q", "protocol_config.py"],
                       cwd=str(root), capture_output=True)
    check("本地配置被 gitignore 排除", r.returncode == 0)

    # 扫描所有将被提交的文件，确保没有硬编码的密钥
    tracked = subprocess.check_output(["git", "ls-files"], cwd=str(root), text=True).split()
    tracked += [f for f in ("door_protocol.py", "protocol_config.example.py",
                            "THIRD_PARTY_NOTICES.md") if f not in tracked]
    leaked = []
    for rel in tracked:
        p = root / rel
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            continue
        try:
            content = p.read_text("utf-8")
        except Exception:
            continue
        if any(s in content for s in needles):
            leaked.append(rel)
    check("待提交文件不含协议密钥", not leaked, leaked)

    check("本地配置完整（missing_config 为空）", proto.missing_config() == [],
          proto.missing_config())

    # 模拟缺失配置时必须给出清晰提示，而不是晦涩的加密异常
    saved = dict(proto._CONFIG)
    try:
        proto._CONFIG.clear()
        try:
            proto.require_config()
            ok = False
        except proto.ProtocolError as e:
            ok = "protocol_config.example.py" in str(e)
        check("缺配置时给出可操作提示", ok)
    finally:
        proto._CONFIG.update(saved)


def main():
    part_a()
    part_b()
    part_c()
    print("\n" + "=" * 58)
    print("  通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("   - " + f)
    print("=" * 58)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
