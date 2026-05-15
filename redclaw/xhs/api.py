"""XHS API 客户端 — 基于 httpx + xhshow 纯算法签名

参考: MediaCrawler media_platform/xhs/client.py

浏览器仅用于登录获取 Cookie，所有数据请求通过 httpx + 算法签名完成。
"""

import json
from typing import Dict, List, Optional, Union
from urllib.parse import quote

import httpx

from .errors import XHSError
from .sign import get_search_id, get_trace_id, sign_with_xhshow


class DataFetchError(XHSError):
    """API 数据获取错误"""


class IPBlockError(XHSError):
    """IP 被封"""


class CaptchaError(XHSError):
    """触发验证码"""


class NoteNotFoundError(XHSError):
    """笔记不存在或异常"""


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)


class XHSApiClient:
    """XHS REST API 客户端 — 同步，使用 httpx + xhshow 签名"""

    def __init__(self, cookies: str = "", proxy: Optional[str] = None,
                 timeout: int = 60):
        self._host = "https://edith.xiaohongshu.com"
        self._domain = "https://www.xiaohongshu.com"
        self.proxy = proxy
        self.timeout = timeout
        self.cookies = cookies
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/json;charset=UTF-8",
            "origin": self._domain,
            "pragma": "no-cache",
            "referer": f"{self._domain}/",
            "sec-ch-ua": '"Chromium";v="137", "Google Chrome";v="137", "Not.A/Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": USER_AGENT,
            "Cookie": cookies,
        }
        self._client = httpx.Client(proxy=proxy, timeout=timeout)

    # ---- Signature helpers ----

    def _pre_headers(self, uri: str, params: Optional[Dict] = None,
                     payload: Optional[Dict] = None, method: str = "GET") -> Dict:
        """为请求生成签名头"""
        if method == "GET":
            signs = sign_with_xhshow(uri=uri, data=params, cookie_str=self.cookies, method="GET")
        else:
            signs = sign_with_xhshow(uri=uri, data=payload, cookie_str=self.cookies, method="POST")

        self.headers.update({
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "X-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"],
        })
        return self.headers

    # ---- Request core ----

    @staticmethod
    def _build_query_string(params: Dict) -> str:
        """构建 URL query string，逗号不编码（匹配浏览器行为）"""
        parts = []
        for key, value in params.items():
            value_str = str(value) if value is not None else ""
            parts.append(f"{key}={quote(value_str, safe=',')}")
        return "&".join(parts)

    def _request(self, method: str, url: str, **kwargs) -> Dict:
        """执行请求并处理 XHS 错误码"""
        return_response = kwargs.pop("return_response", False)

        try:
            resp = self._client.request(method, url, timeout=self.timeout, **kwargs)
        except httpx.RequestError as e:
            raise DataFetchError(f"Request failed: {e}")

        if resp.status_code in (471, 461):
            raise CaptchaError(
                f"CAPTCHA appeared (status={resp.status_code}), "
                f"verify_type={resp.headers.get('Verifytype', '?')}, "
                f"verify_uuid={resp.headers.get('Verifyuuid', '?')}"
            )

        if return_response:
            return resp.text

        try:
            data: Dict = resp.json()
        except json.JSONDecodeError:
            raise DataFetchError(f"Invalid JSON response: {resp.text[:500]}")

        if data.get("success"):
            return data.get("data", data.get("success", {}))

        code = data.get("code", 0)
        if code == 300012:
            raise IPBlockError("IP blocked by XHS")
        if code in (-510000, -510001):
            raise NoteNotFoundError(f"Note not found or abnormal (code={code})")

        err_msg = data.get("msg") or resp.text[:200]
        raise DataFetchError(f"API error code={code}: {err_msg}")

    def get(self, uri: str, params: Optional[Dict] = None) -> Dict:
        headers = self._pre_headers(uri, params=params, method="GET")
        if params:
            full_url = f"{self._host}{uri}?{self._build_query_string(params)}"
        else:
            full_url = f"{self._host}{uri}"
        return self._request("GET", full_url, headers=headers)

    def post(self, uri: str, data: Dict, **kwargs) -> Dict:
        headers = self._pre_headers(uri, payload=data, method="POST")
        json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return self._request("POST", f"{self._host}{uri}", data=json_str, headers=headers, **kwargs)

    # ---- Cookie ----

    def update_cookies(self, cookie_str: str) -> None:
        self.cookies = cookie_str
        self.headers["Cookie"] = cookie_str

    def update_cookies_from_dict(self, cookie_dict: Dict[str, str]) -> None:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        self.update_cookies(cookie_str)

    # ---- Health check ----

    def query_self(self) -> Optional[Dict]:
        """查询当前用户信息，用于检查登录态"""
        uri = "/api/sns/web/v1/user/selfinfo"
        headers = self._pre_headers(uri, params={}, method="GET")
        try:
            resp = self._client.get(f"{self._host}{uri}", headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def pong(self) -> bool:
        """检查登录态是否有效"""
        try:
            info = self.query_self()
            if info and info.get("data", {}).get("result", {}).get("success"):
                return True
        except Exception:
            pass
        return False

    # ---- Search ----

    def search_notes(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        sort: str = "general",
        note_type: int = 0,
        search_id: Optional[str] = None,
    ) -> Dict:
        """搜索笔记

        Args:
            keyword: 搜索关键词
            page: 页码 (从 1 开始)
            page_size: 每页数量 (固定 20)
            sort: general|time_descending|popularity_descending
            note_type: 0=全部, 1=图文, 2=视频
            search_id: 搜索会话 ID
        """
        uri = "/api/sns/web/v1/search/notes"
        data = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": search_id or get_search_id(),
            "sort": sort,
            "note_type": note_type,
        }
        return self.post(uri, data)

    # ---- Feed detail ----

    def get_note_by_id(self, note_id: str, xsec_token: str,
                       xsec_source: str = "pc_search") -> Dict:
        """获取笔记详情 (API)

        Args:
            note_id: 笔记 ID
            xsec_token: 搜索结果中返回的 xsec_token
            xsec_source: 来源通道
        """
        if not xsec_source:
            xsec_source = "pc_search"

        uri = "/api/sns/web/v1/feed"
        data = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        res = self.post(uri, data)
        if res and res.get("items"):
            return res["items"][0].get("note_card", {})
        return {}

    # ---- Comments ----

    def get_note_comments(self, note_id: str, xsec_token: str,
                          cursor: str = "") -> Dict:
        """获取一级评论"""
        uri = "/api/sns/web/v2/comment/page"
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": "",
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        return self.get(uri, params)

    def get_note_sub_comments(self, note_id: str, root_comment_id: str,
                              xsec_token: str, num: int = 10,
                              cursor: str = "") -> Dict:
        """获取子评论"""
        uri = "/api/sns/web/v2/comment/sub/page"
        params = {
            "note_id": note_id,
            "root_comment_id": root_comment_id,
            "num": str(num),
            "cursor": cursor,
            "image_formats": "jpg,webp,avif",
            "top_comment_id": "",
            "xsec_token": xsec_token,
        }
        return self.get(uri, params)

    # ---- Creator ----

    def get_notes_by_creator(self, user_id: str, cursor: str = "",
                             page_size: int = 30, xsec_token: str = "",
                             xsec_source: str = "pc_feed") -> Dict:
        """获取创作者笔记列表"""
        uri = "/api/sns/web/v1/user_posted"
        params = {
            "num": page_size,
            "cursor": cursor,
            "user_id": user_id,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
        }
        return self.get(uri, params)

    def get_creator_info_html(self, user_id: str, xsec_token: str = "",
                               xsec_source: str = "") -> str:
        """获取创作者主页 HTML (用于解析 __INITIAL_STATE__)"""
        uri = f"/user/profile/{user_id}"
        if xsec_token and xsec_source:
            uri = f"{uri}?xsec_token={xsec_token}&xsec_source={xsec_source}"
        return self._request("GET", f"{self._domain}{uri}",
                             headers=self.headers, return_response=True)

    # ---- Media ----

    def get_media(self, url: str) -> Optional[bytes]:
        """下载图片/视频"""
        try:
            resp = self._client.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

    # ---- Cleanup ----

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
