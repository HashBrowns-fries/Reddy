"""XHS 统一客户端 — API 优先 + CDP 回退

协调 Playwright 浏览器 (登录)、API 客户端 (数据获取)、CDP (HTML 回退)。

参考: MediaCrawler media_platform/xhs/core.py XiaoHongShuCrawler
"""

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import List, Optional

from .api import XHSApiClient, CaptchaError, IPBlockError, DataFetchError
from .api_adapters import adapt_search_items, adapt_feed_detail, adapt_comments
from .models import Feed, FeedDetailResponse, CommentList

logger = logging.getLogger(__name__)

# Cookie 持久化路径
_COOKIE_DIR = Path.home() / ".reddy" / "xhs"
_COOKIE_FILE = _COOKIE_DIR / "cookies.json"


class XHSClient:
    """XHS 统一客户端

    使用方式:
        with XHSClient() as client:
            client.login_qrcode()   # 首次登录
            feeds = client.search_feeds("产品经理")
            detail = client.get_feed_detail(feeds[0].id, feeds[0].xsec_token)
    """

    def __init__(self, cookie_path: Optional[str] = None,
                 browser_data_dir: Optional[str] = None):
        """
        Args:
            cookie_path: Cookie JSON 文件路径 (默认 ~/.reddy/xhs/cookies.json)
            browser_data_dir: Playwright 持久化用户目录 (默认 browser_data/xhs)
        """
        self._cookie_path = Path(cookie_path or str(_COOKIE_FILE))
        self._browser_data_dir = browser_data_dir

        self._browser = None          # XHSBrowser (Playwright)
        self._api: Optional[XHSApiClient] = None
        self._cdp_page = None         # CDP Page 回退

        # 从文件加载 Cookie
        self._load_cookies()

    # ---- Lifecycle ----

    def _ensure_api(self) -> XHSApiClient:
        if self._api is None:
            self._api = XHSApiClient(cookies=self._cookies or "")
        return self._api

    def _ensure_browser(self):
        from .browser import XHSBrowser
        if self._browser is None:
            self._browser = XHSBrowser(user_data_dir=self._browser_data_dir)
            self._browser.start()
        return self._browser

    def has_api(self) -> bool:
        """是否有可用 Cookie 用于 API 调用"""
        return bool(self._cookies and self._cookies.strip())

    # ---- Cookie ----

    def _load_cookies(self):
        self._cookies = ""
        self._cookie_dict = {}
        try:
            if self._cookie_path.exists():
                data = json.loads(self._cookie_path.read_text())
                self._cookies = data.get("cookie_str", "")
                self._cookie_dict = data.get("cookie_dict", {})
                if self._api:
                    self._api.update_cookies(self._cookies)
        except Exception:
            pass

    def _save_cookies(self):
        self._cookie_path.parent.mkdir(parents=True, exist_ok=True)
        self._cookie_path.write_text(
            json.dumps({
                "cookie_str": self._cookies,
                "cookie_dict": self._cookie_dict,
                "saved_at": time.time(),
            }, ensure_ascii=False, indent=2)
        )

    def _sync_cookies_from_browser(self):
        if self._browser:
            self._cookies = self._browser.get_cookies()
            self._cookie_dict = self._browser.get_cookie_dict()
            if self._api:
                self._api.update_cookies(self._cookies)
            self._save_cookies()

    # ---- Login ----

    def check_login(self) -> bool:
        """检查登录状态 (优先 API，回退 Browser)"""
        if self.has_api():
            api = self._ensure_api()
            if api.pong():
                return True
        try:
            browser = self._ensure_browser()
            from .login_pw import check_login_status
            return check_login_status(browser.page)
        except Exception:
            return False

    def login_qrcode(self) -> dict:
        """QR 码登录，返回二维码图片路径和状态

        Returns:
            {"success": True, "qr_path": ..., "qr_base64": ..., "already_logged_in": False}
        """
        import base64
        from .login_pw import fetch_qrcode, wait_for_login, get_current_user_nickname

        browser = self._ensure_browser()
        png_bytes, b64_str, already = fetch_qrcode(browser.page)

        if already:
            self._sync_cookies_from_browser()
            nickname = get_current_user_nickname(browser.page)
            return {"success": True, "already_logged_in": True, "nickname": nickname}

        # 保存二维码到文件
        from .login import save_qrcode_to_file
        path = save_qrcode_to_file(png_bytes)

        return {
            "success": True,
            "qr_path": path,
            "qr_base64": b64_str,
            "instruction": "Open XHS app to scan the QR code. Then call login_wait() to wait for completion.",
        }

    def login_wait(self, timeout: float = 120.0) -> dict:
        """等待 QR 码扫描完成

        Returns:
            {"success": True, "logged_in": True, "nickname": "..."}
        """
        from .login_pw import wait_for_login, get_current_user_nickname

        browser = self._ensure_browser()
        ok = wait_for_login(browser.page, timeout=timeout)
        if ok:
            self._sync_cookies_from_browser()
            nickname = get_current_user_nickname(browser.page)
            return {"success": True, "logged_in": True, "nickname": nickname}
        return {"error": "Login wait timed out"}

    def login_phone_send_code(self, phone: str) -> dict:
        """发送手机验证码"""
        from .login_pw import send_phone_code, get_current_user_nickname

        browser = self._ensure_browser()
        try:
            sent = send_phone_code(browser.page, phone)
            if sent is False:
                self._sync_cookies_from_browser()
                nickname = get_current_user_nickname(browser.page)
                return {"success": True, "already_logged_in": True, "nickname": nickname}
            return {"success": True, "code_sent": True}
        except Exception as e:
            return {"error": str(e)}

    def login_phone_submit_code(self, code: str) -> dict:
        """提交短信验证码完成登录"""
        from .login_pw import submit_phone_code, get_current_user_nickname

        browser = self._ensure_browser()
        try:
            ok = submit_phone_code(browser.page, code)
            if ok:
                self._sync_cookies_from_browser()
                nickname = get_current_user_nickname(browser.page)
                return {"success": True, "logged_in": True, "nickname": nickname}
            return {"error": "Login failed — wrong code or expired"}
        except Exception as e:
            return {"error": str(e)}

    def logout(self) -> bool:
        """退出登录"""
        from .login_pw import logout as pw_logout
        try:
            browser = self._ensure_browser()
            ok = pw_logout(browser.page)
            if ok:
                self._cookies = ""
                self._cookie_dict = {}
                if self._api:
                    self._api.update_cookies("")
                self._save_cookies()
            return ok
        except Exception:
            return False

    # ---- Search ----

    def search_feeds(self, keyword: str, filter_option=None,
                     use_api: bool = True) -> List[Feed]:
        """搜索笔记 — API 优先，CDP 回退

        Args:
            keyword: 搜索关键词
            filter_option: 筛选选项 (CDP 回退时使用)
            use_api: 是否优先使用 API
        """
        # API 路径
        if use_api and self.has_api():
            try:
                api = self._ensure_api()
                result = api.search_notes(keyword=keyword)
                items = result.get("items", [])
                if items:
                    logger.info("API search: %d items for '%s'", len(items), keyword)
                    return adapt_search_items(items)
            except (CaptchaError, IPBlockError) as e:
                logger.warning("API search failed: %s, falling back to CDP", e)
            except DataFetchError as e:
                logger.warning("API search data error: %s", e)

        # CDP 回退
        from .cdp import Browser, Page
        from .search import search_feeds as cdp_search_feeds

        page = self._get_cdp_page()
        return cdp_search_feeds(page, keyword=keyword, filter_option=filter_option)

    # ---- Feed Detail ----

    def get_feed_detail(self, note_id: str, xsec_token: str,
                        load_all_comments: bool = False,
                        config=None,
                        use_api: bool = True) -> FeedDetailResponse:
        """获取笔记详情 — API 优先，CDP 回退

        Args:
            note_id: 笔记 ID
            xsec_token: 安全 token (来自搜索结果)
            load_all_comments: 是否加载全部评论
            config: 评论加载配置 (CDP 回退时使用)
            use_api: 是否优先使用 API
        """
        # API 路径
        if use_api and self.has_api():
            try:
                api = self._ensure_api()
                note_card = api.get_note_by_id(note_id, xsec_token)
                if note_card:
                    feed_detail = adapt_feed_detail(note_card, note_id, xsec_token)
                    comment_list = CommentList()
                    if load_all_comments:
                        try:
                            comments_data = api.get_note_comments(note_id, xsec_token)
                            comment_list = adapt_comments(comments_data)
                        except Exception as e:
                            logger.warning("API comment fetch failed: %s", e)
                    return FeedDetailResponse(note=feed_detail, comments=comment_list)
            except (CaptchaError, IPBlockError) as e:
                logger.warning("API detail failed: %s, falling back to CDP", e)
            except DataFetchError as e:
                logger.warning("API detail data error: %s", e)

        # CDP 回退
        from .cdp import Browser, Page
        from .feed_detail import get_feed_detail as cdp_get_feed_detail

        page = self._get_cdp_page()
        return cdp_get_feed_detail(
            page, note_id, xsec_token,
            load_all_comments=load_all_comments, config=config,
        )

    # ---- CDP fallback ----

    def _get_cdp_page(self):
        """获取 CDP Page 回退 (懒初始化)"""
        if self._cdp_page is None:
            from .cdp import Browser, Page
            browser = Browser()
            self._cdp_page = browser.get_or_create_page()
        return self._cdp_page

    # ---- Close ----

    def close(self):
        if self._api:
            self._api.close()
            self._api = None
        if self._browser:
            self._browser.close()
            self._browser = None
        self._cdp_page = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
