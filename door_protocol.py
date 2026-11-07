# -*- coding: utf-8 -*-
"""
Door access protocol layer, zero third-party runtime dependencies.

This module performs sign-in, key listing and open-door requests for an account
the user is authorised to use. The server still validates the session and the
door permission; nothing here bypasses authentication or authorisation.

Third-party attribution and the upstream MIT license notice live in
THIRD_PARTY_NOTICES.md.

NO protocol values are stored in this repository. Endpoints, client metadata,
application ids, secrets and keys are loaded from `protocol_config.py`
(gitignored, local only) or from QO_* environment variables, with environment
variables taking precedence. Copy `protocol_config.example.py` to
`protocol_config.py` and fill in the values before running the service.

AES-128-ECB is implemented in pure Python for the sign-in phone-number field
and is verified against the FIPS-197 test vector at start-up.
"""

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

_CONFIG_KEYS = (
    "BASE_URL", "SMS_URL", "APP_VERSION", "APP_VERSION_CODE", "APP_CHANNEL",
    "SIGNING_SALT", "HEX_AES_KEY", "SMS_APP_ID", "SMS_APP_SECRET", "TIMEOUT",
)


def _load_config() -> Dict[str, Any]:
    """Local file first, environment variables override it."""
    cfg: Dict[str, Any] = {}
    try:
        import protocol_config  # local, gitignored
        for key in _CONFIG_KEYS:
            value = getattr(protocol_config, key, None)
            if value is not None and value != "":
                cfg[key] = value
    except ImportError:
        pass
    for key in _CONFIG_KEYS:
        value = os.environ.get("QO_" + key)
        if value:
            cfg[key] = value
    return cfg


_CONFIG = _load_config()


def missing_config() -> List[str]:
    """Names of protocol settings that have not been provided locally."""
    return [k for k in _CONFIG_KEYS if _CONFIG.get(k) in (None, "")]


def require_config() -> None:
    missing = missing_config()
    if missing:
        raise ProtocolError(
            "Protocol configuration is incomplete (missing: %s). "
            "Copy protocol_config.example.py to protocol_config.py and fill in the values."
            % ", ".join(missing)
        )


BASE_URL = str(_CONFIG.get("BASE_URL", ""))
SMS_URL = str(_CONFIG.get("SMS_URL", ""))
APP_VERSION = str(_CONFIG.get("APP_VERSION", ""))
APP_VERSION_CODE = str(_CONFIG.get("APP_VERSION_CODE", ""))
APP_CHANNEL = int(_CONFIG.get("APP_CHANNEL", 1) or 1)
SIGNING_SALT = str(_CONFIG.get("SIGNING_SALT", ""))
HEX_AES_KEY = str(_CONFIG.get("HEX_AES_KEY", ""))
SMS_APP_ID = str(_CONFIG.get("SMS_APP_ID", ""))
SMS_APP_SECRET = str(_CONFIG.get("SMS_APP_SECRET", ""))
TIMEOUT = float(_CONFIG.get("TIMEOUT", 8) or 8)

# ---------------------------------------------------------------- AES-128
SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]
RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a & 0xFF


def _expand_key(key: bytes) -> List[bytes]:
    words = [list(key[i * 4:(i + 1) * 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(words[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // 4 - 1]
        words.append([words[i - 4][j] ^ t[j] for j in range(4)])
    return [bytes(sum(words[4 * r:4 * r + 4], [])) for r in range(11)]


def _encrypt_block(block: bytes, round_keys: List[bytes]) -> bytes:
    s = [block[i] ^ round_keys[0][i] for i in range(16)]
    for r in range(1, 11):
        s = [SBOX[b] for b in s]
        s = [s[4 * ((c + row) % 4) + row] for c in range(4) for row in range(4)]
        if r != 10:
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                s[4 * c + 0] = _xtime(a[0]) ^ (_xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3]
                s[4 * c + 1] = a[0] ^ _xtime(a[1]) ^ (_xtime(a[2]) ^ a[2]) ^ a[3]
                s[4 * c + 2] = a[0] ^ a[1] ^ _xtime(a[2]) ^ (_xtime(a[3]) ^ a[3])
                s[4 * c + 3] = (_xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _xtime(a[3])
        s = [s[i] ^ round_keys[r][i] for i in range(16)]
    return bytes(s)


def aes128_ecb_encrypt(plaintext: bytes, key: bytes, pad: bool = True) -> bytes:
    if len(key) != 16:
        raise ValueError("AES-128 需要 16 字节密钥")
    if pad:
        n = 16 - (len(plaintext) % 16)
        plaintext = plaintext + bytes([n]) * n
    if len(plaintext) % 16:
        raise ValueError("明文长度必须是 16 的倍数")
    rk = _expand_key(key)
    return b"".join(_encrypt_block(plaintext[i:i + 16], rk) for i in range(0, len(plaintext), 16))


def encrypt_phone(phone: str) -> str:
    if not HEX_AES_KEY:
        raise ProtocolError("Missing HEX_AES_KEY in protocol_config.py")
    key = bytes.fromhex(HEX_AES_KEY)
    return aes128_ecb_encrypt(phone.encode("utf-8"), key).hex().upper()


def aes_selftest() -> bool:
    """FIPS-197 官方向量，防止手写的 AES 实现出错。"""
    key = bytes(range(16))
    plain = bytes.fromhex("00112233445566778899aabbccddeeff")
    want = "69c4e0d86a7b0430d8cdb78070b4c55a"
    return aes128_ecb_encrypt(plain, key, pad=False).hex() == want


# ------------------------------------------------------- Java URLEncoder 复刻
_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-*_"
)


def java_encode(value: Any) -> str:
    """等价于 Java URLEncoder.encode(s, UTF-8).replace("%3A", ":")。"""
    out = []
    for b in str(value).encode("utf-8"):
        ch = chr(b)
        if ch in _SAFE:
            out.append(ch)
        elif ch == " ":
            out.append("+")
        else:
            out.append("%%%02X" % b)
    return "".join(out).replace("%3A", ":")


def encode_query(values: Dict[str, Any]) -> str:
    return "&".join("%s=%s" % (java_encode(k), java_encode(v)) for k, v in sorted(values.items()))


def _nonce(n: int) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(n))


def _md5_upper(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()


def numeric_or_string(v: Any) -> Any:
    s = str(v)
    try:
        return int(s) if s.lstrip("-").isdigit() else s
    except Exception:
        return s


# ------------------------------------------------------------- 签名 / 请求
def sign_fields(fields: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    if not SIGNING_SALT:
        raise ProtocolError("Missing SIGNING_SALT in protocol_config.py")
    timestamp = int(time.time() * 1000)
    nonce = _nonce(5)
    sign_values = dict(fields)
    sign_values.update({
        "nonce": nonce,
        "timestamp": timestamp,
        "token": session_id,
        "version": APP_VERSION,
    })
    sign = _md5_upper(encode_query(sign_values) + "&key=" + SIGNING_SALT)
    out = dict(fields)
    out.update({"timestamp": timestamp, "version": APP_VERSION, "nonce": nonce, "sign": sign})
    return out


class ProtocolError(Exception):
    def __init__(self, message: str, code: int = 0, detail: str = "", endpoint: str = ""):
        super().__init__(message)
        self.code = code
        self.detail = detail          # 脱敏后的上游响应，便于诊断协议变更
        self.endpoint = endpoint


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
_LAST_ENDPOINT = ""


def http_post_json(url: str, content_type: str, body: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    status = 0
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            status = resp.status
            text = resp.read(256 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        text = e.read(256 * 1024).decode("utf-8", "replace")
    except Exception as e:
        raise ProtocolError("网络请求失败：%s" % type(e).__name__, endpoint=url)
    if not text.strip():
        raise ProtocolError("服务端返回空响应", detail="HTTP %s" % status, endpoint=url)
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            out["_http_status"] = status
        return out
    except Exception:
        raise ProtocolError("服务端返回非 JSON：" + text[:120],
                            detail="HTTP %s" % status, endpoint=url)


def normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        t = value.strip()
        if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
            try:
                return json.loads(t)
            except Exception:
                pass
    return value


def require_success(response: Dict[str, Any], endpoint: str = "") -> Any:
    success = bool(response.get("success", False))
    try:
        code = int(response.get("code", -999999))
    except Exception:
        code = -999999
    if not success and code != 0 and not (200 <= code <= 299):
        clean = {k: v for k, v in response.items() if not k.startswith("_")}
        detail = "HTTP %s · %s" % (response.get("_http_status", 0),
                                   json.dumps(clean, ensure_ascii=False)[:300])
        raise ProtocolError(str(response.get("message") or "请求失败（code=%s）" % code),
                            code, detail=detail,
                            endpoint=endpoint or globals().get("_LAST_ENDPOINT", ""))
    return normalize_json(response.get("data"))


def find_string(root: Any, candidates: List[str]) -> Optional[str]:
    result = [None]

    def visit(v):
        if result[0] is not None:
            return
        v = normalize_json(v)
        if isinstance(v, dict):
            for k in candidates:
                val = v.get(k)
                if val is not None and str(val).strip() and str(val) != "null":
                    result[0] = str(val)
                    return
            for val in v.values():
                visit(val)
        elif isinstance(v, list):
            for item in v:
                visit(item)

    visit(root)
    return result[0]


def objects_containing(root: Any, key: str) -> List[dict]:
    found = []

    def visit(v):
        v = normalize_json(v)
        if isinstance(v, dict):
            if v.get(key) is not None:
                found.append(v)
            for val in v.values():
                visit(val)
        elif isinstance(v, list):
            for item in v:
                visit(item)

    visit(root)
    return found


def _first_string(obj: dict, keys: List[str], default: str = "") -> str:
    for k in keys:
        v = obj.get(k)
        if v is not None and str(v).strip() and str(v) != "null":
            return str(v)
    return default


# ------------------------------------------------------------------- Client
class ProtocolClient:
    """transport 可注入，便于离线自测：(url, content_type, body_bytes, headers) -> dict"""

    def __init__(self, openid: str = "", vendor: str = "samsung",
                 transport: Optional[Callable[..., Dict[str, Any]]] = None):
        self.openid = openid or secrets.token_hex(8)
        self.vendor = vendor
        self.transport = transport or http_post_json
        self.last_request: Dict[str, Any] = {}

    def common_headers(self) -> Dict[str, str]:
        return {
            "openid": self.openid,
            "User-Agent": "Dart/3.8 (dart:io)",
            "qversioncode": APP_VERSION_CODE,
            "qchannel": "google",
            "qplatform": "0",
            "qvendor": self.vendor,
        }

    def _request(self, url: str, content_type: str, body: bytes,
                 extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        global _LAST_ENDPOINT
        headers = self.common_headers()
        headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        _LAST_ENDPOINT = url.split("?")[0]
        self.last_request = {"url": url, "content_type": content_type,
                             "body": body.decode("utf-8", "replace"), "headers": headers}
        return self.transport(url, content_type, body, headers)

    def send_security_code(self, phone: str) -> None:
        if not SMS_APP_ID or not SMS_APP_SECRET:
            raise ProtocolError("Missing SMS_APP_ID or SMS_APP_SECRET in protocol_config.py")
        timestamp = int(time.time() * 1000)
        nonce = _nonce(4)
        raw = ("appid=%s&mobile=%s&nonce=%s&timestamp=%s&version=v2&appsecret=%s"
               % (SMS_APP_ID, phone, nonce, timestamp, SMS_APP_SECRET))
        sign = _md5_upper(raw)
        body = json.dumps({"mobile": phone}, separators=(",", ":")).encode("utf-8")
        headers = {"appid": SMS_APP_ID, "version": "v2", "timestamp": str(timestamp),
                   "nonce": nonce, "sign": sign}
        require_success(self._request(SMS_URL, "application/json; charset=utf-8", body, headers))

    def login(self, phone: str, security_code: str) -> Dict[str, str]:
        fields = {"mobile": encrypt_phone(phone), "smsCode": security_code,
                  "appChannel": APP_CHANNEL}
        signed = sign_fields(fields, "")
        url = "%s/app/v1/login?%s" % (BASE_URL, encode_query({"sessionId": ""}))
        body = json.dumps(signed, separators=(",", ":")).encode("utf-8")
        data = require_success(self._request(url, "application/json; charset=utf-8", body))
        session = find_string(data, ["sessionId", "sessionID", "token"])
        if not session:
            raise ProtocolError("登录成功，但响应里找不到 sessionId")
        return {"session_id": session,
                "user_id": find_string(data, ["userId", "uid"]) or ""}

    def _signed_json(self, endpoint: str, session_id: str, fields: Dict[str, Any]) -> Any:
        signed = sign_fields(fields, session_id)
        url = "%s/%s?%s" % (BASE_URL, endpoint, encode_query({"sessionId": session_id}))
        body = json.dumps(signed, separators=(",", ":")).encode("utf-8")
        return require_success(self._request(url, "application/json; charset=utf-8", body))

    def _signed_multipart(self, endpoint: str, session_id: str, fields: Dict[str, Any]) -> Any:
        signed = sign_fields(fields, session_id)
        boundary = "quickopen-" + _nonce(12)
        chunks = []
        for name, value in signed.items():
            chunks.append("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                          % (boundary, name, value))
        chunks.append("--%s--\r\n" % boundary)
        body = "".join(chunks).encode("utf-8")
        url = "%s/%s?%s" % (BASE_URL, endpoint, encode_query({"sessionId": session_id}))
        ctype = "multipart/form-data; boundary=%s" % boundary
        return require_success(self._request(url, ctype, body))

    def community_ids(self, session_id: str) -> List[Dict[str, str]]:
        data = self._signed_json("app/user/v2/communityInfo", session_id,
                                 {"method": "communityInfo"})
        out, seen = [], set()
        for obj in objects_containing(data, "communityId"):
            cid = str(obj.get("communityId"))
            if cid in seen:
                continue
            seen.add(cid)
            out.append({"id": cid, "name": _first_string(
                obj, ["communityName", "name", "communityShortName", "projectName"])})
        return out

    def load_door_keys(self, session_id: str) -> List[Dict[str, str]]:
        keys, seen = [], set()
        for community in self.community_ids(session_id):
            data = self._signed_multipart("app/user/v2/queryUserDoorByCacheNew", session_id,
                                          {"communityId": numeric_or_string(community["id"])})
            for obj in objects_containing(data, "doorControlId"):
                did = str(obj.get("doorControlId"))
                stable = "%s:%s" % (community["id"], did)
                if stable in seen:
                    continue
                seen.add(stable)
                cname = _first_string(obj, ["communityName", "projectName"], community["name"])
                dname = _first_string(obj, ["doorControlName", "doorName", "name",
                                            "deviceName", "remarkName"], "钥匙 " + did)
                keys.append({
                    "id": stable,
                    "community_id": community["id"],
                    "door_id": did,
                    "community_name": cname,
                    "door_name": dname,
                    "name": (cname + " " + dname).strip(),
                })
        keys.sort(key=lambda k: (k["community_name"], k["door_name"]))
        return keys

    def open_door(self, session_id: str, key: Dict[str, str]) -> str:
        fields = {"appChannel": APP_CHANNEL,
                  "doorControlId": numeric_or_string(key["door_id"]),
                  "communityId": numeric_or_string(key["community_id"])}
        signed = sign_fields(fields, session_id)
        query = {"sessionId": session_id}
        query.update(signed)
        url = "%s/open/doorcontrol/v2/open?%s" % (BASE_URL, encode_query(query))
        resp = self._request(url, "application/json; charset=utf-8", b"")
        require_success(resp)
        return str(resp.get("message") or "开门请求已发送")

    def touch(self, session_id: str) -> None:
        """轻量保活：只拉社区信息，不触发任何开门动作。"""
        self._signed_json("app/user/v2/communityInfo", session_id, {"method": "communityInfo"})
