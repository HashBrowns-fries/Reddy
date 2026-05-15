"""
小红书搜索脚本：输入搜索字段 → 开始搜索 → 保存文字+图片 → 图片OCR → LLM整合到md
"""

import os
import sys
import json
import time
import random
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent

from redclaw.xhs.client import XHSClient

# ============== 配置 ==============
SEARCH_KEYWORD = ""
OUTPUT_DIR = PROJECT_ROOT.parent / "经验"
IMAGE_SAVE_DIR = OUTPUT_DIR / "images"
VISITED_FILE = OUTPUT_DIR / "visited_notes.json"

# 当前搜索会话文件夹（每次搜索生成一个）
SESSION_DIR = None

# 反爬配置（browser-based, lighter than raw HTTP）
REQUEST_DELAY_MIN = 2
REQUEST_DELAY_MAX = 4
REQUEST_TIMEOUT = 30
MAX_RETRY = 2

# 可选：代理和Cookie配置（需要登录时使用）
PROXY_CONFIG = None    # e.g. {"http": "http://user:pass@host:port"}
COOKIE_CONFIG = None   # e.g. "cookie_token=xxx; session=yyy"

def load_visited_notes() -> dict:
    """加载已访问过的笔记ID及信息"""
    if VISITED_FILE.exists():
        with open(VISITED_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_visited_note(note_data: dict):
    """保存已访问的笔记ID及信息到JSON"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    visited = load_visited_notes()
    note_id = note_data.get("noteId", "")
    visited[note_id] = note_data
    with open(VISITED_FILE, 'w', encoding='utf-8') as f:
        json.dump(visited, f, ensure_ascii=False, indent=2)

def get_session_dir() -> Path:
    """获取当前会话文件夹路径"""
    return SESSION_DIR or OUTPUT_DIR

def get_note_folder(note_id: str) -> Path:
    """获取笔记专属文件夹路径"""
    folder = get_session_dir() / "images" / note_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder

# ============== 工具函数 ==============

def random_delay(min_sec=None, max_sec=None):
    """请求间隔随机延迟"""
    min_s = min_sec if min_sec is not None else REQUEST_DELAY_MIN
    max_s = max_sec if max_sec is not None else REQUEST_DELAY_MAX
    delay = random.uniform(min_s, max_s)
    print(f"  ⏳ 等待 {delay:.1f}s...")
    time.sleep(delay)

def init_client():
    """初始化 XHS 客户端"""
    return XHSClient()

def search_notes(keyword: str, client=None) -> list:
    """搜索笔记"""
    c = client or init_client()
    feeds = c.search_feeds(keyword=keyword)
    return feeds

def get_note_detail(feed_id: str, xsec_token: str, client=None) -> dict:
    """获取笔记详情"""
    c = client or init_client()
    result = c.get_feed_detail(
        feed_id=feed_id,
        xsec_token=xsec_token,
        load_all_comments=False,
    )
    random_delay()
    return result

def download_image(url: str, save_path: Path) -> bool:
    """下载图片（带反爬策略）"""
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.xiaohongshu.com/",
        "Origin": "https://www.xiaohongshu.com",
    }

    proxies = PROXY_CONFIG

    for attempt in range(MAX_RETRY):
        try:
            resp = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(resp.content)
                return True
            elif resp.status_code in (403, 401, 429):
                print(f"  ⚠️ 反爬触发 ({resp.status_code})，等待重试...")
                time.sleep(random.uniform(5, 10))
            else:
                print(f"  ❌ HTTP {resp.status_code}")
        except requests.exceptions.Timeout:
            print(f"  ⏰ 超时，等待重试 ({attempt+1}/{MAX_RETRY})...")
        except requests.exceptions.RequestException as e:
            print(f"  ❌ 请求异常: {e}")
        random_delay(1, 2)
    return False

def get_ocr_options() -> dict:
    """获取Umi-OCR可用参数"""
    import requests
    try:
        resp = requests.get("http://127.0.0.1:1224/api/ocr/get_options", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}

def run_ocr(image_path: str) -> str:
    """通过 Umi-OCR 提取图片文字（自动启动服务）"""
    import base64
    from redclaw.modules.ocr import ocr_base64

    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        result = ocr_base64(img_b64, {"data.format": "text", "tbpu.parser": "multi_line"})
        if result.get("success"):
            return result.get("text", "") or "[无文字内容]"
        return f"[OCR错误: {result.get('error', '未知')}]"
    except Exception as e:
        return f"[OCR错误: {e}]"

def format_note_for_llm(note: dict, ocr_contents: dict) -> str:
    """将笔记格式化为LLM输入"""
    note_id = note.get("noteId", "")
    title = note.get("title", "无标题")
    desc = note.get("desc", "")
    user = note.get("user", {})
    interact = note.get("interactInfo", {})
    ip = note.get("ipLocation", "")

    # 构建文本内容
    text_content = f"""### {title}

**作者**: {user.get('nickname', '未知')} | **IP**: {ip}
**点赞**: {interact.get('likedCount', '0')} | **收藏**: {interact.get('collectedCount', '0')} | **评论**: {interact.get('commentCount', '0')}

**笔记ID**: {note_id}

**正文内容**:
{desc if desc else "[无正文]"}

"""

    # 添加图片OCR内容
    if ocr_contents:
        text_content += "\n**图片内容（OCR提取）**:\n"
        for img_name, ocr_text in ocr_contents.items():
            if ocr_text and ocr_text != "[无内容]":
                text_content += f"\n--- 图片: {img_name} ---\n{ocr_text}\n"

    return text_content

def extract_note_info(note_data: dict) -> dict:
    """从笔记原始数据中提取核心信息

    Args:
        note_data: 原始笔记数据（来自API或JSON）

    Returns:
        提取后的核心信息字典
    """
    note_id = note_data.get("noteId", "")
    title = note_data.get("title", "")
    desc = note_data.get("desc", "")

    # 处理用户信息
    user = note_data.get("user", {})
    if isinstance(user, dict):
        nickname = user.get("nickname", user.get("nickName", ""))
        user_id = user.get("userId", "")
    else:
        nickname = ""
        user_id = ""

    # 处理互动数据
    interact = note_data.get("interactInfo", {})
    liked_count = interact.get("likedCount", "0") if isinstance(interact, dict) else "0"
    collected_count = interact.get("collectedCount", "0") if isinstance(interact, dict) else "0"
    comment_count = interact.get("commentCount", "0") if isinstance(interact, dict) else "0"

    # IP属地
    ip_location = note_data.get("ipLocation", "")

    # 时间戳转换
    time_stamp = note_data.get("time", 0)
    if time_stamp:
        publish_time = datetime.fromtimestamp(time_stamp).strftime("%Y-%m-%d %H:%M:%S") if isinstance(time_stamp, (int, float)) else ""
    else:
        publish_time = ""

    return {
        "noteId": note_id,
        "title": title,
        "desc": desc,
        "link": f"https://www.xiaohongshu.com/explore/{note_id}",
        "user": {
            "nickname": nickname,
            "userId": user_id,
        },
        "ipLocation": ip_location,
        "publishTime": publish_time,
        "interactInfo": {
            "likedCount": liked_count,
            "collectedCount": collected_count,
            "commentCount": comment_count,
        }
    }

def build_note_json(note: dict, ocr_contents: dict, comments: list) -> dict:
    """构建笔记JSON数据结构"""
    note_id = note.get("noteId", "")
    title = note.get("title", "无标题")
    desc = note.get("desc", "")
    user = note.get("user", {})
    interact = note.get("interactInfo", {})
    ip = note.get("ipLocation", "")

    # 图片路径列表（使用会话专属文件夹）
    note_folder = get_session_dir() / "images" / note_id
    image_paths = [
        str(note_folder / img_name)
        for img_name in ocr_contents.keys()
    ]

    # 构建评论列表
    comment_list = []
    for c in comments:
        if isinstance(c, dict):
            comment_list.append({
                "id": c.get("id", ""),
                "content": c.get("content", ""),
                "likeCount": c.get("likeCount", ""),
                "ipLocation": c.get("ipLocation", ""),
                "user": c.get("user", {}).get("nickname", ""),
                "createTime": c.get("createTime", 0),
            })
        else:
            comment_list.append({
                "id": c.id,
                "content": c.content,
                "likeCount": c.like_count,
                "ipLocation": c.ip_location,
                "user": c.user_info.nickname or c.user_info.nick_name,
                "createTime": c.create_time,
            })

    return {
        "noteId": note_id,
        "title": title,
        "link": f"https://www.xiaohongshu.com/explore/{note_id}",
        "desc": desc,
        "user": {
            "nickname": user.get("nickname", ""),
            "userId": user.get("userId", ""),
        },
        "ipLocation": ip,
        "interactInfo": {
            "likedCount": interact.get("likedCount", "0"),
            "collectedCount": interact.get("collectedCount", "0"),
            "commentCount": interact.get("commentCount", "0"),
        },
        "images": image_paths,
        "ocrContents": ocr_contents,
        "comments": comment_list,
        "fetchTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def save_note_json(note_data: dict, keyword: str):
    """保存笔记JSON文件到当前会话目录"""
    session_dir = get_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)

    note_id = note_data.get("noteId", "")
    title = note_data.get("title", "无标题")
    # 清理标题中的非法字符
    safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_', '·') else '_' for c in title)[:30]
    json_file = session_dir / f"{safe_title}_{note_id[:8]}.json"

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(note_data, f, ensure_ascii=False, indent=2)

    print(f"  💾 JSON已保存: {json_file.name}")
    return json_file

def save_batch_notes(all_notes: list, keyword: str):
    """保存所有笔记到单个JSON文件"""
    session_dir = get_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_file = session_dir / f"all_notes_{timestamp}.json"

    with open(batch_file, 'w', encoding='utf-8') as f:
        json.dump(all_notes, f, ensure_ascii=False, indent=2)

    print(f"💾 批量笔记已保存: {batch_file.name}")
    return batch_file

def save_to_md(content: str, keyword: str, note_id: str):
    """保存到md文件"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_SAVE_DIR.mkdir(parents=True, exist_ok=True)

    # 生成文件名
    safe_keyword = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in keyword)[:20]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_file = OUTPUT_DIR / f"{safe_keyword}_{note_id[:8]}_{timestamp}.md"

    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  💾 已保存: {md_file.name}")
    return md_file

# ============== 反爬策略 ==============

def _note_delay(notes_fetched: int):
    """Short delay between notes. Slight increase over time."""
    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX) + notes_fetched * 0.3
    time.sleep(delay)


def _backoff_delay(attempt: int):
    """Backoff on failure."""
    delay = 10 + attempt * 10 + random.uniform(0, 5)
    print(f"  backoff {delay:.0f}s", file=sys.stderr)
    time.sleep(delay)


def _is_anti_crawl_error(error: Exception) -> bool:
    msg = str(error).lower()
    keywords = ['验证', 'verify', '扫码', 'qrcode', '403', '429',
                'not accessible', '不可访问', 'captcha', 'blocked']
    return any(kw in msg for kw in keywords)


# ============== 主流程 ==============

def main(keyword: str, max_notes: int = 10, skip_images: bool = False):
    """主流程"""
    global SEARCH_KEYWORD, SESSION_DIR
    SEARCH_KEYWORD = keyword

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in keyword)[:20]
    SESSION_DIR = OUTPUT_DIR / f"{safe_keyword}_{timestamp}"
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_IMAGES_DIR = SESSION_DIR / "images"
    SESSION_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*50}")
    print(f"  Search: {keyword}")
    print(f"  Output: {SESSION_DIR.name}")
    print(f"{'='*50}\n")

    # 1. Search
    print("[1/2] Searching...", file=sys.stderr)
    notes = search_notes(keyword)
    print(f"  found {len(notes)} notes", file=sys.stderr)

    if not notes:
        print("  no results!")
        return

    notes = notes[:max_notes]

    # Shuffle order to avoid predictable sequential access patterns
    notes_with_idx = list(enumerate(notes))
    random.shuffle(notes_with_idx)

    # 2. Fetch details
    print(f"\n[2/2] Fetching details ({len(notes)} notes)...")
    random_delay(3, 6)

    all_content = []
    all_notes_json = []
    visited = load_visited_notes()
    new_count = 0
    fail_count = 0
    anti_crawl_hits = 0

    for seq, (orig_idx, note) in enumerate(notes_with_idx):
        note_id = getattr(note, 'id', '') or note.get('noteId', note.get('id', ''))
        xsec_token = getattr(note, 'xsec_token', '') or note.get('xsecToken', '')
        note_card = getattr(note, 'note_card', None)
        title = note_card.display_title if note_card else note.get('displayTitle', note.get('title', '?'))

        print(f"\n  [{seq+1}/{len(notes)}] {title[:40]}")

        if not note_id or not xsec_token:
            print(f"    skip (missing id/token)")
            continue

        if note_id in visited:
            print(f"    skip (visited)")
            continue

        # If anti-crawl was triggered multiple times, abort early
        if anti_crawl_hits >= 3:
            print(f"    abort: too many anti-crawl triggers ({anti_crawl_hits})")
            break

        # Fetch detail with retry
        detail = None
        for attempt in range(MAX_RETRY):
            try:
                _progressive_delay(new_count)
                detail = get_note_detail(note_id, xsec_token)
                break
            except Exception as e:
                err_msg = str(e)
                print(f"    error: {err_msg[:80]}")
                if _is_anti_crawl_error(e):
                    anti_crawl_hits += 1
                    print(f"    anti-crawl detected ({anti_crawl_hits}/3)")
                    _backoff_delay(attempt + anti_crawl_hits)
                else:
                    fail_count += 1
                    if attempt < MAX_RETRY - 1:
                        _backoff_delay(attempt)
                    else:
                        print(f"    giving up after {MAX_RETRY} attempts")

        if not detail:
            continue

        note_info = detail.note.to_dict()
        images = note_info.get("imageList", [])

        # Comments
        comments_data = []
        if detail.comments and detail.comments.list_:
            for c in detail.comments.list_:
                comments_data.append(c.to_dict())

        # Download images + OCR
        ocr_contents = {}
        if not skip_images and images:
            note_folder = get_note_folder(note_id)
            print(f"    images: {len(images)}")
            for j, img in enumerate(images):
                img_url = img.get("urlDefault", "")
                if not img_url:
                    continue

                img_ext = ".jpg" if "jpg" in img_url.lower() else ".png"
                img_name = f"{note_id}_{j+1}{img_ext}"
                img_path = note_folder / img_name

                if download_image(img_url, img_path):
                    ocr_text = run_ocr(img_path)
                    ocr_contents[img_name] = ocr_text
                else:
                    print(f"      download failed: {img_name}")

                random_delay(2, 4)

        # Save
        note_json = build_note_json(note_info, ocr_contents, comments_data)
        save_note_json(note_json, keyword)
        all_notes_json.append(note_json)

        note_text = format_note_for_llm(note_info, ocr_contents)
        all_content.append(note_text)
        save_visited_note(note_json)
        new_count += 1
        print(f"    ok ({new_count} saved)")

        # Batch cooldown every 3 notes
        if new_count > 0 and new_count % 3 == 0:
            _batch_cooldown(new_count)

    # Summary
    combined = "\n\n".join(all_content)

    combined_file = get_session_dir() / "raw_notes.txt"
    with open(combined_file, 'w', encoding='utf-8') as f:
        f.write(combined)

    if all_notes_json:
        save_batch_notes(all_notes_json, keyword)

    print(f"\n  Done: {new_count} notes saved, {fail_count} failed")
    if anti_crawl_hits:
        print(f"  Anti-crawl triggers: {anti_crawl_hits}")
    print(f"  Output: {get_session_dir()}")

    return combined, all_content

if __name__ == "__main__":
    if len(sys.argv) < 2:
        keyword = input("🔍 输入搜索关键词: ").strip()
        if not keyword:
            print("❌ 关键词不能为空！")
            sys.exit(1)
    else:
        keyword = sys.argv[1]

    max_notes = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    skip_images = "--skip-images" in sys.argv

    main(keyword, max_notes, skip_images)