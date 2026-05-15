"""Playwright 浏览器管理器 — 登录态持久化

使用 Playwright sync_api + launch_persistent_context，
Cookie / LocalStorage 自动持久化到磁盘，重启后无需重新登录。

参考: MediaCrawler media_platform/xhs/core.py launch_browser()
"""

import os
from pathlib import Path
from typing import Optional


# 默认浏览器用户数据目录
def _default_user_data_dir() -> str:
    project_root = Path(__file__).parent.parent.parent.parent
    return str(project_root / "browser_data" / "xhs")


class XHSBrowser:
    """小红书 Playwright 浏览器，带登录态持久化"""

    def __init__(self, user_data_dir: Optional[str] = None,
                 headless: bool = False):
        self.user_data_dir = user_data_dir or os.environ.get(
            "XHS_BROWSER_DATA_DIR", _default_user_data_dir()
        )
        self.headless = headless
        self._playwright = None
        self._context = None
        self._page = None

    def start(self) -> "XHSBrowser":
        """启动持久化浏览器上下文"""
        from playwright.sync_api import sync_playwright

        os.makedirs(self.user_data_dir, exist_ok=True)

        pw = sync_playwright().start()
        self._playwright = pw

        self._context = pw.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        if not self._context.pages:
            self._page = self._context.new_page()
        else:
            self._page = self._context.pages[0]

        self._page.goto("https://www.xiaohongshu.com")
        return self

    @property
    def page(self):
        """返回 Playwright Page 对象"""
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    def get_cookies(self) -> str:
        """提取所有 Cookie 为请求头字符串"""
        if not self._context:
            return ""
        cookies = self._context.cookies()
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    def get_cookie_dict(self) -> dict:
        """提取 Cookie 为 name->value 字典"""
        if not self._context:
            return {}
        return {c["name"]: c["value"] for c in self._context.cookies()}

    def get_a1(self) -> str:
        """获取签名用 a1 cookie 值"""
        d = self.get_cookie_dict()
        return d.get("a1", "")

    def get_web_session(self) -> str:
        """获取 web_session cookie 值"""
        d = self.get_cookie_dict()
        return d.get("web_session", "")

    def save_storage_state(self) -> None:
        """显式保存浏览器状态（实际上 launch_persistent_context 自动保存）"""
        pass  # persistent context handles this automatically

    def close(self) -> None:
        """关闭浏览器"""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
