"""Playwright 版登录 — 替代 CDP 浏览器交互

与 redclaw.xhs.login 功能对等，但使用 Playwright Page (sync API)。
复用 selectors.py 中所有 CSS 选择器。

参考: MediaCrawler media_platform/xhs/login.py
"""

from __future__ import annotations

import json
import logging
import time

from playwright.sync_api import Page as PlaywrightPage

from .errors import RateLimitError
from .human import sleep_random
from .selectors import (
    AGREE_CHECKBOX,
    AGREE_CHECKBOX_CHECKED,
    CODE_INPUT,
    GET_CODE_BUTTON,
    LOGIN_CONTAINER,
    LOGIN_ERR_MSG,
    LOGIN_STATUS,
    LOGOUT_MENU_ITEM,
    LOGOUT_MORE_BUTTON,
    PHONE_INPUT,
    PHONE_LOGIN_SUBMIT,
    QRCODE_IMG,
    USER_NICKNAME,
    USER_PROFILE_NAV_LINK,
)
from .urls import EXPLORE_URL

logger = logging.getLogger(__name__)


def check_login_status(page: PlaywrightPage) -> bool:
    """检查登录状态"""
    current_url = page.evaluate("location.href") or ""
    if "explore" not in current_url:
        page.goto(EXPLORE_URL, wait_until="domcontentloaded")

    try:
        page.wait_for_selector(LOGIN_STATUS, timeout=5000)
        return True
    except Exception:
        return False


def fetch_qrcode(page: PlaywrightPage) -> tuple[bytes, str, bool]:
    """获取登录二维码图片 (Playwright)

    Returns:
        (png_bytes, b64_str, already_logged_in)
    """
    import base64

    current_url = page.evaluate("location.href") or ""
    if "explore" not in current_url:
        page.goto(EXPLORE_URL, wait_until="domcontentloaded")

    # 快速检查已登录
    if page.query_selector(LOGIN_STATUS):
        return b"", "", True

    try:
        page.wait_for_selector(QRCODE_IMG, timeout=15000)
    except Exception:
        # 可能已登录，再次检查
        if page.query_selector(LOGIN_STATUS):
            return b"", "", True
        raise RuntimeError("二维码图片未出现")

    src = page.evaluate(
        f"document.querySelector({json.dumps(QRCODE_IMG)})?.src || ''"
    )
    if not src or "base64," not in src:
        raise RuntimeError("二维码图片 src 读取失败")

    b64_str = src.split("base64,", 1)[1]
    png_bytes = base64.b64decode(b64_str)
    return png_bytes, b64_str, False


def wait_for_login(page: PlaywrightPage, timeout: float = 120.0) -> bool:
    """等待扫码登录完成"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.query_selector(LOGIN_STATUS):
            logger.info("登录成功")
            return True
        time.sleep(0.3)
    return False


def send_phone_code(page: PlaywrightPage, phone: str) -> bool:
    """填写手机号并发送短信验证码 (Playwright)"""
    current_url = page.evaluate("location.href") or ""
    if "explore" not in current_url:
        page.goto(EXPLORE_URL, wait_until="domcontentloaded")

    try:
        page.wait_for_selector(LOGIN_CONTAINER, timeout=10000)
    except Exception:
        if page.query_selector(LOGIN_STATUS):
            return False
        raise RuntimeError("找不到登录表单")

    if page.query_selector(LOGIN_STATUS):
        return False

    sleep_random(200, 400)

    # 填写手机号
    page.click(PHONE_INPUT)
    sleep_random(200, 400)
    page.fill(PHONE_INPUT, phone)
    sleep_random(200, 400)

    # 勾选用户协议
    if not page.query_selector(AGREE_CHECKBOX_CHECKED):
        page.click(AGREE_CHECKBOX)
        sleep_random(300, 600)

    # 点击获取验证码
    page.click(GET_CODE_BUTTON)
    sleep_random(800, 1500)

    logger.info("验证码已发送至 %s", phone[:3] + "****" + phone[-4:])
    return True


def submit_phone_code(page: PlaywrightPage, code: str) -> bool:
    """填写短信验证码并提交登录 (Playwright)"""
    page.click(CODE_INPUT)
    sleep_random(100, 200)

    # 清空 + 填写
    page.evaluate(
        f"""(() => {{
            const el = document.querySelector({json.dumps(CODE_INPUT)});
            if (el) {{
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(el, '');
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
        }})()"""
    )
    page.fill(CODE_INPUT, code)
    sleep_random(100, 200)

    page.click(PHONE_LOGIN_SUBMIT)
    sleep_random(500, 1000)

    try:
        err_el = page.query_selector(LOGIN_ERR_MSG)
        if err_el:
            err_text = err_el.inner_text().strip()
            if err_text:
                logger.warning("登录失败: %s", err_text)
                return False
    except Exception:
        pass

    return wait_for_login(page, timeout=30.0)


def logout(page: PlaywrightPage) -> bool:
    """通过页面 UI 退出登录 (Playwright)"""
    page.goto(EXPLORE_URL, wait_until="domcontentloaded")
    sleep_random(800, 1500)

    if not page.query_selector(LOGIN_STATUS):
        logger.info("当前未登录，无需退出")
        return False

    page.click(LOGOUT_MORE_BUTTON)
    sleep_random(500, 800)

    page.wait_for_selector(LOGOUT_MENU_ITEM, timeout=5000)
    page.click(LOGOUT_MENU_ITEM)
    sleep_random(1000, 1500)

    logger.info("已退出登录")
    return True


def get_current_user_nickname(page: PlaywrightPage) -> str:
    """获取当前登录用户的真实昵称 (Playwright)"""
    try:
        page.goto(EXPLORE_URL, wait_until="domcontentloaded")
        if not check_login_status(page):
            return ""

        profile_href = page.evaluate(
            f"document.querySelector({json.dumps(USER_PROFILE_NAV_LINK)})?.getAttribute('href') || ''"
        )
        if not profile_href:
            return ""

        profile_url = f"https://www.xiaohongshu.com{profile_href}"
        page.goto(profile_url, wait_until="domcontentloaded")

        el = page.query_selector(USER_NICKNAME)
        if el:
            return el.inner_text().strip()
        return ""
    except Exception:
        logger.warning("获取用户昵称失败")
        return ""
