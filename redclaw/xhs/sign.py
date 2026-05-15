"""XHS API 签名生成 — 基于 xhshow 纯算法库

参考: MediaCrawler media_platform/xhs/playwright_sign.py
xhshow: https://github.com/Cloxl/xhshow (MIT License)

无需浏览器 JS 执行，纯 Python 算法生成:
  X-S, X-T, X-S-Common, X-B3-Traceid
"""

import hashlib
import json
import random
import time
from typing import Dict, Optional, Union
from urllib.parse import quote


def _patch_xhshow_a3_hash():
    """修复 xhshow build_payload_array 中 GET 请求 a3_hash 计算的 bug。

    xhshow 原实现对所有请求使用 MD5(extract_api_path(content_string)) 计算 a3_hash,
    其中 extract_api_path 会去掉 "?" 后的查询参数和 "{" 后的 JSON body。
    浏览器实际行为:
      - POST: a3 使用 MD5(api_path) — 原实现正确
      - GET:  a3 使用 MD5(完整 URL + 查询参数) — 原实现错误
    修复: GET 请求使用完整 content_string 的 MD5。
    ref: https://github.com/Cloxl/xhshow/issues/104
    """
    try:
        from xhshow.core.crypto import CryptoProcessor
    except ImportError:
        return

    _original_build = CryptoProcessor.build_payload_array

    def _patched_build(self, hex_parameter, a1_value, app_identifier="xhs-pc-web",
                       string_param="", timestamp=None, sign_state=None):
        payload = _original_build(self, hex_parameter, a1_value, app_identifier,
                                  string_param, timestamp, sign_state)
        if "{" not in string_param:
            correct_md5_hex = hashlib.md5(string_param.encode("utf-8")).hexdigest()
            correct_md5_bytes = [int(correct_md5_hex[i:i + 2], 16) for i in range(0, 32, 2)]
            seed_byte = payload[4]
            ts_bytes = payload[8:16]
            correct_a3_hash = self._custom_hash_v2(list(ts_bytes) + correct_md5_bytes)
            for i in range(16):
                payload[128 + i] = correct_a3_hash[i] ^ seed_byte
        return payload

    CryptoProcessor.build_payload_array = _patched_build


_patch_xhshow_a3_hash()


def get_trace_id() -> str:
    """生成 16 位 hex trace ID"""
    return "".join(random.choice("abcdef0123456789") for _ in range(16))


def get_search_id() -> str:
    """生成 XHS search_id"""
    e = int(time.time() * 1000) << 64
    t = int(random.uniform(0, 2147483646))
    return _base36encode(e + t)


def _base36encode(number: int, alphabet="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") -> str:
    if number < 0:
        raise ValueError("number must be non-negative")
    if number == 0:
        return alphabet[0]
    result = ""
    while number:
        number, i = divmod(number, len(alphabet))
        result = alphabet[i] + result
    return result


def _build_sign_string(uri: str, data: Optional[Union[Dict, str]] = None,
                       method: str = "POST") -> str:
    """构建签名用 content string

    POST: uri + JSON body
    GET:  uri?key=value...
    """
    if method.upper() == "POST":
        c = uri
        if data is not None:
            if isinstance(data, dict):
                c += json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            elif isinstance(data, str):
                c += data
        return c
    else:
        if not data or (isinstance(data, dict) and len(data) == 0):
            return uri
        if isinstance(data, dict):
            params = []
            for key in data.keys():
                value = data[key]
                if isinstance(value, list):
                    value_str = ",".join(str(v) for v in value)
                elif value is not None:
                    value_str = str(value)
                else:
                    value_str = ""
                value_str = quote(value_str, safe=",")
                params.append(f"{key}={value_str}")
            return f"{uri}?{'&'.join(params)}"
        elif isinstance(data, str):
            return f"{uri}?{data}"
        return uri


def sign_with_xhshow(
    uri: str,
    data: Optional[Union[Dict, str]] = None,
    cookie_str: str = "",
    method: str = "POST",
) -> Dict[str, str]:
    """使用 xhshow 纯算法生成 XHS API 签名请求头

    Args:
        uri: API path (e.g. "/api/sns/web/v1/search/notes")
        data: GET params dict or POST payload dict
        cookie_str: Cookie header string (需要含 a1 值)
        method: "GET" or "POST"

    Returns:
        {"x-s": ..., "x-t": ..., "x-s-common": ..., "x-b3-traceid": ...}
    """
    from xhshow import Xhshow

    xhshow_client = Xhshow()
    is_post = method.upper() == "POST"

    if is_post:
        headers = xhshow_client.sign_headers_post(
            uri=uri,
            cookies=cookie_str,
            payload=data if isinstance(data, dict) else {},
        )
    else:
        content_string = _build_sign_string(uri, data, method)
        cookie_dict = xhshow_client._parse_cookies(cookie_str)
        a1_value = cookie_dict.get("a1", "")

        ts = time.time()
        d_value = hashlib.md5(content_string.encode("utf-8")).hexdigest()

        payload_array = xhshow_client.crypto_processor.build_payload_array(
            d_value, a1_value, "xhs-pc-web", content_string, ts
        )
        xor_result = xhshow_client.crypto_processor.bit_ops.xor_transform_array(payload_array)
        config = xhshow_client.config
        x3_b64 = xhshow_client.crypto_processor.b64encoder.encode_x3(
            xor_result[:config.PAYLOAD_LENGTH]
        )
        sig_data = config.SIGNATURE_DATA_TEMPLATE.copy()
        sig_data["x3"] = config.X3_PREFIX + x3_b64
        x_s = config.XYS_PREFIX + xhshow_client.crypto_processor.b64encoder.encode(
            json.dumps(sig_data, separators=(",", ":"), ensure_ascii=False)
        )
        headers = {
            "x-s": x_s,
            "x-s-common": xhshow_client.sign_xs_common(cookie_dict),
            "x-t": str(xhshow_client.get_x_t(ts)),
            "x-b3-traceid": xhshow_client.get_b3_trace_id(),
        }

    return {
        "x-s": headers.get("x-s", ""),
        "x-t": headers.get("x-t", ""),
        "x-s-common": headers.get("x-s-common", ""),
        "x-b3-traceid": headers.get("x-b3-traceid", get_trace_id()),
    }
