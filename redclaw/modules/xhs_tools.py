"""小红书工具模块 — XHSClient 统一入口 + 搜索抓取 + 工具注册

v2: 使用 redclaw.xhs.client.XHSClient (API 优先 + CDP 回退)
    替代旧的 BridgePage + bridge_server 方案
"""

_xhs_client = None


def _ensure_xhs_client():
    """懒初始化 XHS 统一客户端"""
    global _xhs_client
    if _xhs_client is None:
        from redclaw.xhs.client import XHSClient
        _xhs_client = XHSClient()
    return _xhs_client


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
    """搜索小红书并抓取笔记详情 (v2: XHSClient API 优先)"""
    keywords = args.get("keywords", [])
    max_per_keyword = args.get("max_per_keyword", 0)
    output_dir = args.get("output_dir", "")

    if not keywords:
        return {"error": "No keywords provided"}

    client = _ensure_xhs_client()

    import time
    import random
    import requests
    from redclaw.modules.xhs_search_and_save import (
        build_note_json, save_note_json, set_output_dir,
        save_visited_note, load_visited_notes,
    )

    if output_dir:
        set_output_dir(output_dir)

    visited = load_visited_notes()
    results = []
    total_found = 0
    anti_crawl_hits = 0

    for keyword in keywords:
        try:
            feeds = client.search_feeds(keyword=keyword)
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
                detail = client.get_feed_detail(note_id, xsec_token, load_all_comments=False)
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
    """检查 XHS 服务状态 (v2: XHSClient)"""
    client = _ensure_xhs_client()
    logged_in = client.check_login()

    info = {
        "success": True,
        "api_available": client.has_api(),
        "logged_in": logged_in,
    }

    return info


def xhs_login_handler(args: dict) -> dict:
    """XHS 登录/登出/状态检查 (v2: XHSClient Playwright)

    Actions: status, qr, wait, send_code, submit_code, logout
    """
    client = _ensure_xhs_client()
    action = args.get("action", "status")

    if action == "status":
        logged_in = client.check_login()
        return {"success": True, "logged_in": logged_in}

    if action == "logout":
        ok = client.logout()
        return {"success": True, "logged_out": ok}

    if action == "qr":
        return client.login_qrcode()

    if action == "wait":
        timeout = args.get("timeout", 120)
        return client.login_wait(timeout=timeout)

    if action == "send_code":
        phone = args.get("phone", "")
        if not phone:
            return {"error": "phone required"}
        return client.login_phone_send_code(phone)

    if action == "submit_code":
        code = args.get("code", "")
        if not code:
            return {"error": "code required"}
        return client.login_phone_submit_code(code)

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
        description="从小红书搜索并抓取内容，支持多关键词 (API优先,自动回退CDP)", emoji="📕",
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
        description="用单个关键词搜索小红书 (API优先)", emoji="🔍",
    )

    registry.register(
        name="xhs_status", toolset="xiaohongshu",
        schema={"type": "object", "properties": {"auto_start": {"type": "boolean", "description": "是否自动启动（默认 false）"}}},
        handler=xhs_status_handler,
        description="检查小红书服务状态 (API可用性 + 登录态)", emoji="📡",
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
        description="小红书登录/登出/状态检查 (Playwright QR + 手机验证码)", emoji="🔑",
    )
