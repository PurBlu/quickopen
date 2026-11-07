#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
协议体检 · 一键判断「哪一段协议还能用、哪一段被官方改了」

    python3 diagnose.py        或双击「协议体检.command」

全部使用不存在的手机号 / 假验证码 / 假会话，不会发短信、不会开门、不会登录。
只做 4 个只读探测，几秒内出结果，用于官方升级后快速定位问题。
"""
import json
import sys
import urllib.error
import urllib.request

import door_protocol as proto
from door_protocol import ProtocolError, ProtocolClient

FAKE_PHONE = "10000000000"
FAKE_SESSION = "DIAGNOSTIC_INVALID_SESSION"
_client = ProtocolClient(openid="0011223344556677")


def _post(url, ctype, body, extra_headers=None):
    """直连（忽略环境代理），返回 (http状态, 解析后的 JSON 或原文)。"""
    h = dict(_client.common_headers())
    h["Content-Type"] = ctype
    if extra_headers:
        h.update(extra_headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=proto.TIMEOUT) as r:
            text, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        text, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:
        return 0, {"message": "%s: %s" % (type(e).__name__, e)}
    try:
        return status, json.loads(text)
    except Exception:
        return status, {"message": text[:160]}


def _signed(endpoint, fields, session=""):
    signed = proto.sign_fields(dict(fields), session)
    url = "%s/%s?%s" % (proto.BASE_URL, endpoint, proto.encode_query({"sessionId": session}))
    return _post(url, "application/json; charset=utf-8",
                 json.dumps(signed, separators=(",", ":")).encode())


def classify(status, resp):
    msg = str(resp.get("message") or resp.get("msg") or "")
    if "验签失败" in msg or "签名" in msg and "缺少" in msg:
        return "blocked", "被网关 WAF 拦截：%s" % msg
    if "验证码" in msg:
        return "ok", "签名通过（服务端返回：%s）" % msg
    if "登录" in msg or "token" in msg.lower() or status == 401:
        return "ok", "签名通过（服务端返回：%s）" % msg
    if status == 404:
        return "gone", "接口已不存在（404）"
    return "unknown", "HTTP %s · %s" % (status, msg or str(resp)[:120])


def run():
    out = {"ok": True, "checks": [], "config": {
        "base_url": proto.BASE_URL, "sms_url": proto.SMS_URL,
        "app_version": proto.APP_VERSION, "version_code": proto.APP_VERSION_CODE,
        "sms_app_id": proto.SMS_APP_ID[:4] + "***",
        "signing_salt": proto.SIGNING_SALT[:2] + "***",
    }}

    def add(name, state, note):
        out["checks"].append({"name": name, "state": state, "note": note})

    add("本地 AES / 签名算法自检", "ok" if proto.aes_selftest() else "blocked",
        "FIPS-197 官方向量" + ("通过" if proto.aes_selftest() else "未通过"))

    # 1. 短信网关
    import time
    ts = str(int(time.time() * 1000))
    nonce = proto._nonce(4)
    raw = ("appid=%s&mobile=%s&nonce=%s&timestamp=%s&version=v2&appsecret=%s"
           % (proto.SMS_APP_ID, FAKE_PHONE, nonce, ts, proto.SMS_APP_SECRET))
    sign = proto._md5_upper(raw)
    body = json.dumps({"mobile": FAKE_PHONE}, separators=(",", ":")).encode()
    hdr = {"appid": proto.SMS_APP_ID, "version": "v2", "timestamp": ts,
           "nonce": nonce, "sign": sign}
    st, resp = _post(proto.SMS_URL, "application/json; charset=utf-8", body, hdr)
    state, note = classify(st, resp)
    if state == "ok":
        state, note = "unknown", "未复现验签失败：%s" % note
    add("发送短信验证码（gateway2 网关）", state, note)

    # 2. 登录接口签名
    st, resp = _signed("app/v1/login", {
        "mobile": proto.encrypt_phone(FAKE_PHONE),
        "smsCode": "000000", "appChannel": proto.APP_CHANNEL})
    state, note = classify(st, resp)
    add("短信验证码登录（app/v1/login）", state, note)

    # 3. 社区信息签名
    st, resp = _signed("app/user/v2/communityInfo", {"method": "communityInfo"}, FAKE_SESSION)
    state, note = classify(st, resp)
    add("钥匙列表 / 会话保活", state, note)

    # 4. 开门接口签名
    try:
        key = {"door_id": "1", "community_id": "1"}
        fields = {"appChannel": proto.APP_CHANNEL,
                  "doorControlId": 1, "communityId": 1}
        signed = proto.sign_fields(fields, FAKE_SESSION)
        q = {"sessionId": FAKE_SESSION}
        q.update(signed)
        url = "%s/open/doorcontrol/v2/open?%s" % (proto.BASE_URL, proto.encode_query(q))
        st, resp = _post(url, "application/json; charset=utf-8", b"")
        state, note = classify(st, resp)
    except Exception as e:
        state, note = "unknown", type(e).__name__
    add("开门指令（open/doorcontrol/v2/open）", state, note)

    sms = out["checks"][1]["state"]
    biz = [c["state"] for c in out["checks"][2:]]
    if sms in ("blocked", "gone") and all(s == "ok" for s in biz):
        out["conclusion"] = ("只有发短信的网关被官方 WAF 拦了，登录/钥匙/开门协议仍然有效。"
                             "请在官方 App 里点一次「获取验证码」，把收到的码填到本服务登录即可，"
                             "之后开门全程走本地秒开。")
        out["workaround"] = True
    elif all(s == "ok" for s in biz) and sms == "ok":
        out["conclusion"] = "全部接口可用，可以在控制台直接点「发验证码」。"
        out["workaround"] = False
    else:
        out["conclusion"] = ("业务接口签名也出现异常，官方可能已升级协议。"
                             "请把体检结果发出来，并按新版 App 抓包更新 proto.py 顶部常量"
                             "（也可用 QO_* 环境变量覆盖）。")
        out["workaround"] = False
    return out


def main():
    r = run()
    print("=" * 74)
    print("  秒开门 · 协议体检")
    print("=" * 74)
    print("  当前配置： %s  (App %s / %s)" % (r["config"]["base_url"],
                                          r["config"]["app_version"], r["config"]["version_code"]))
    print("-" * 74)
    icon = {"ok": "可用  ", "blocked": "被拦  ", "gone": "已下线", "unknown": "待确认"}
    for c in r["checks"]:
        print("  [%s] %-32s %s" % (icon.get(c["state"], "?"), c["name"], c["note"]))
    print("-" * 74)
    print("  结论：" + r["conclusion"])
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
