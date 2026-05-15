"""小红书工具模块 — bridge 自动启动 + 搜索抓取 + 工具注册"""

import os
import sys
from pathlib import Path

_bridge_process = None


def _open_chrome():
    import subprocess
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            subprocess.Popen([path])
            return
    for cmd in [["open", "-a", "Google Chrome"], ["google-chrome"], ["chromium-browser"]]:
        try:
            subprocess.Popen(cmd)
            return
        except FileNotFoundError:
            continue


def _find_bridge_server() -> str:
    candidates = [
        Path(__file__).parent.parent / "xhs" / "bridge_server.py",  # redclaw/xhs/bridge_server.py
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def _ensure_xhs_bridge() -> dict:
    global _bridge_process
    import subprocess, time

    from redclaw.xhs.bridge import BridgePage
    page = BridgePage()

    if page.is_extension_connected():
        return {"ok": True}

    if not page.is_server_running():
        bridge_script = _find_bridge_server()
        if not bridge_script:
            return {"error": "未找到 bridge_server.py"}

        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        _bridge_process = subprocess.Popen(
            [sys.executable, bridge_script], **kwargs,
        )
        for _ in range(10):
            time.sleep(1)
            if page.is_server_running():
                break
        else:
            return {"error": "Bridge server 启动超时 (10s)"}

    if not page.is_extension_connected():
        _open_chrome()
        for _ in range(30):
            time.sleep(1)
            if page.is_extension_connected():
                return {"ok": True, "auto_started": True}
        return {"error": "Chrome 扩展连接超时 (30s)，请确认已安装 XHS Bridge 扩展"}

    return {"ok": True}


def _save_to_db(note_id, title, content, author, url, likes, keyword):
    """Save note to SQLite posts table."""
    try:
        from redclaw.agent import _db_conn
        import json
        from datetime import datetime
        db = _db_conn()
        db.execute(
            "INSERT OR REPLACE INTO posts (id, radar_id, title, content, author, platform, url, tags, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (note_id, "default", title, content, author, "xiaohongshu", url,
             json.dumps([keyword], ensure_ascii=False), datetime.now().timestamp()),
        )
        db.commit()
    except Exception:
        pass


def fetch_xhs_handler(args: dict) -> dict:
    keywords = args.get("keywords", [])
    max_per_keyword = args.get("max_per_keyword", 0)

    if not keywords:
        return {"error": "No keywords provided"}

    bridge_status = _ensure_xhs_bridge()
    if "error" in bridge_status:
        return bridge_status

    import time
    import random
    import requests
    from redclaw.xhs.bridge import BridgePage
    from redclaw.xhs.search import search_feeds
    from redclaw.xhs.feed_detail import get_feed_detail
    from redclaw.modules.xhs_search_and_save import (
        build_note_json, save_note_json,
        save_visited_note, load_visited_notes,
    )

    page = BridgePage()
    visited = load_visited_notes()
    results = []
    total_found = 0
    anti_crawl_hits = 0

    for keyword in keywords:
        try:
            feeds = search_feeds(page, keyword=keyword, filter_option=None)
        except Exception as e:
            results.append({"error": f"search failed: {e}"})
            continue

        if not feeds:
            results.append({"error": f"no results for '{keyword}'"})
            continue

        total_found += len(feeds)
        to_fetch = feeds if max_per_keyword <= 0 else feeds[:max_per_keyword]

        for i, feed in enumerate(to_fetch):
            note_id = getattr(feed, 'id', '') or ''
            xsec_token = getattr(feed, 'xsec_token', '') or ''
            note_card = getattr(feed, 'note_card', None)
            title = note_card.display_title if note_card else '?'

            if not note_id or not xsec_token:
                continue

            if note_id in visited:
                results.append({"noteId": note_id, "title": title, "status": "visited"})
                continue

            if anti_crawl_hits >= 3:
                results.append({"noteId": note_id, "title": title, "status": "skipped (anti-crawl limit)"})
                continue

            time.sleep(random.uniform(2, 4) + i * 0.3)

            try:
                detail = get_feed_detail(page, note_id, xsec_token, load_all_comments=False)
                note_info = detail.note.to_dict()

                comments_data = []
                if detail.comments and detail.comments.list_:
                    for c in detail.comments.list_:
                        comments_data.append(c.to_dict())

                # Auto OCR on images
                ocr_contents = {}
                images = note_info.get("imageList", [])
                if images:
                    import base64
                    from redclaw.modules.ocr import ocr_base64
                    for j, img in enumerate(images):
                        img_url = img.get("urlDefault", "") or img.get("url", "")
                        if not img_url:
                            continue
                        try:
                            resp = requests.get(img_url, timeout=30, headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                "Referer": "https://www.xiaohongshu.com/",
                            })
                            if resp.status_code == 200:
                                img_b64 = base64.b64encode(resp.content).decode("utf-8")
                                ocr_res = ocr_base64(img_b64)
                                if ocr_res.get("success") and ocr_res.get("text"):
                                    ocr_contents[f"img_{j+1}"] = ocr_res["text"]
                        except Exception:
                            pass

                note_json = build_note_json(note_info, ocr_contents, comments_data)
                save_note_json(note_json, keyword)
                save_visited_note(note_json)

                desc = note_info.get("desc", "") or ""
                note_title = note_info.get("title", title)
                author = note_info.get("user", {}).get("nickname", "")
                likes = note_info.get("interactInfo", {}).get("likedCount", "0")
                link = f"https://www.xiaohongshu.com/explore/{note_id}"

                # Merge OCR text into content for full-text search
                full_content = desc
                if ocr_contents:
                    full_content += "\n\n[OCR]\n" + "\n".join(f"{k}: {v}" for k, v in ocr_contents.items())
                _save_to_db(note_id, note_title, full_content, author, link, likes, keyword)

                results.append({
                    "noteId": note_id,
                    "title": note_title,
                    "author": author,
                    "likes": likes,
                    "desc": desc[:200],
                    "link": link,
                    "comments": len(comments_data),
                    "ocr_count": len(ocr_contents),
                    "status": "ok",
                })
            except Exception as e:
                err = str(e)
                if any(k in err.lower() for k in ['验证', 'verify', '扫码', 'qrcode', 'not accessible']):
                    anti_crawl_hits += 1
                results.append({"noteId": note_id, "title": title, "status": f"error: {err[:80]}"})

            # Batch cooldown every 5 notes
            ok_count = sum(1 for r in results if r.get("status") == "ok")
            if ok_count > 0 and ok_count % 5 == 0:
                time.sleep(random.uniform(8, 15))

    ok_notes = [r for r in results if r.get("status") == "ok"]
    return {
        "success": True,
        "keyword": keywords[0] if len(keywords) == 1 else keywords,
        "total_search_results": total_found,
        "fetched": len(ok_notes),
        "notes": results,
    }


def xhs_status_handler(args: dict) -> dict:
    from redclaw.xhs.bridge import BridgePage
    page = BridgePage()

    server_running = page.is_server_running()
    ext_connected = page.is_extension_connected() if server_running else False
    bridge_script = _find_bridge_server()

    info = {
        "success": True,
        "bridge_server": "running" if server_running else "offline",
        "extension": "connected" if ext_connected else "disconnected",
        "bridge_script_found": bool(bridge_script),
    }

    auto_start = args.get("auto_start", False)
    if auto_start and not ext_connected:
        result = _ensure_xhs_bridge()
        if result.get("ok"):
            info["bridge_server"] = "running"
            info["extension"] = "connected"
            info["message"] = "已自动启动"
        else:
            info["error"] = result.get("error", "启动失败")

    return info


def xhs_login_handler(args: dict) -> dict:
    """Handle XHS login: QR scan, phone code, status check, or logout."""
    from redclaw.xhs.bridge import BridgePage
    from redclaw.xhs.login import (
        fetch_qrcode, save_qrcode_to_file, wait_for_login,
        check_login_status, send_phone_code, submit_phone_code,
        logout as xhs_logout, get_current_user_nickname,
    )
    import base64

    action = args.get("action", "status")

    bridge_status = _ensure_xhs_bridge()
    if "error" in bridge_status:
        return bridge_status

    page = BridgePage()

    if action == "status":
        logged_in = check_login_status(page)
        nickname = get_current_user_nickname(page) if logged_in else ""
        return {"success": True, "logged_in": logged_in, "nickname": nickname}

    if action == "logout":
        ok = xhs_logout(page)
        return {"success": True, "logged_out": ok}

    if action == "qr":
        try:
            png_bytes, b64_str, already = fetch_qrcode(page)
            if already:
                nickname = get_current_user_nickname(page)
                return {"success": True, "already_logged_in": True, "nickname": nickname}
            path = save_qrcode_to_file(png_bytes)
            return {
                "success": True,
                "qr_path": path,
                "qr_base64": b64_str,
                "instruction": "Open XHS app to scan the QR code. Call xhs_login with action='wait' after scanning.",
            }
        except Exception as e:
            return {"error": f"QR fetch failed: {e}"}

    if action == "wait":
        timeout = args.get("timeout", 120)
        ok = wait_for_login(page, timeout=timeout)
        if ok:
            nickname = get_current_user_nickname(page)
            return {"success": True, "logged_in": True, "nickname": nickname}
        return {"error": "Login wait timed out"}

    if action == "send_code":
        phone = args.get("phone", "")
        if not phone:
            return {"error": "phone required"}
        try:
            sent = send_phone_code(page, phone)
            if sent is False:
                nickname = get_current_user_nickname(page)
                return {"success": True, "already_logged_in": True, "nickname": nickname}
            return {"success": True, "code_sent": True, "instruction": "Call xhs_login with action='submit_code' and the code received."}
        except Exception as e:
            return {"error": str(e)}

    if action == "submit_code":
        code = args.get("code", "")
        if not code:
            return {"error": "code required"}
        try:
            ok = submit_phone_code(page, code)
            if ok:
                nickname = get_current_user_nickname(page)
                return {"success": True, "logged_in": True, "nickname": nickname}
            return {"error": "Login failed — wrong code or expired"}
        except Exception as e:
            return {"error": str(e)}

    return {"error": f"unknown action: {action}. Use: status, qr, wait, send_code, submit_code, logout"}


# ============== Registration ==============

def register_xhs_tools(registry):
    registry.register(
        name="fetch_xhs", toolset="xiaohongshu",
        schema={
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "搜索关键词列表"},
                "max_per_keyword": {"type": "integer", "default": 0, "description": "每个关键词最大抓取数量 (0=全部)"},
                "radar_id": {"type": "string", "description": "关联的雷达ID"},
            },
            "required": ["keywords"],
        },
        handler=fetch_xhs_handler,
        description="从小红书搜索并抓取内容，支持多关键词", emoji="📕",
    )

    registry.register(
        name="fetch_xhs_by_keyword", toolset="xiaohongshu",
        schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "max_notes": {"type": "integer", "default": 0, "description": "最大抓取数量 (0=全部)"},
            },
            "required": ["keyword"],
        },
        handler=lambda args: fetch_xhs_handler({
            "keywords": [args.get("keyword", "")],
            "max_per_keyword": args.get("max_notes", 0),
        }),
        description="用单个关键词搜索小红书", emoji="🔍",
    )

    registry.register(
        name="xhs_status", toolset="xiaohongshu",
        schema={"type": "object", "properties": {"auto_start": {"type": "boolean", "description": "是否自动启动（默认 false）"}}},
        handler=xhs_status_handler,
        description="检查小红书 Bridge 服务状态", emoji="📡",
    )

    registry.register(
        name="xhs_login", toolset="xiaohongshu",
        schema={"type": "object", "properties": {
            "action": {"type": "string", "description": "status | qr (扫码) | wait (等待扫码) | send_code (手机验证码) | submit_code (提交验证码) | logout"},
            "phone": {"type": "string", "description": "手机号（send_code 时必填）"},
            "code": {"type": "string", "description": "短信验证码（submit_code 时必填）"},
            "timeout": {"type": "integer", "default": 120, "description": "等待扫码超时（秒）"},
        }},
        handler=xhs_login_handler,
        description="小红书登录/登出/状态检查 (支持扫码和手机验证码)", emoji="🔑",
    )
