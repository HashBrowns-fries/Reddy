"""
采集器模块 - 小红书数据采集
"""

import sys
import json
import time
import random
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

try:
    from redclaw.xhs.bridge import BridgePage
    from redclaw.xhs.search import search_feeds
    from redclaw.xhs.feed_detail import get_feed_detail
    HAS_XHS = True
except ImportError:
    HAS_XHS = False


class XiaohongshuFetcher:
    """小红书数据采集器"""

    def __init__(self, output_dir: str = "./data/xhs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.visited_file = self.output_dir / "visited_notes.json"
        self.request_delay_min = 1
        self.request_delay_max = 3
        self.max_retry = 3

    def _random_delay(self, min_sec: float = None, max_sec: float = None):
        """请求间隔随机延迟"""
        min_s = min_sec if min_sec is not None else self.request_delay_min
        max_s = max_sec if max_sec is not None else self.request_delay_max
        delay = random.uniform(min_s, max_s)
        time.sleep(delay)

    def _load_visited(self) -> Dict:
        """加载已访问笔记"""
        if self.visited_file.exists():
            with open(self.visited_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_visited(self, note_data: dict):
        """保存已访问笔记"""
        visited = self._load_visited()
        note_id = note_data.get('noteId', note_data.get('id', ''))
        if note_id:
            visited[note_id] = note_data
            with open(self.visited_file, 'w', encoding='utf-8') as f:
                json.dump(visited, f, ensure_ascii=False, indent=2)

    def fetch_by_keywords(
        self,
        keywords: List[str],
        max_per_keyword: int = 10,
        skip_images: bool = True
    ) -> List[Dict]:
        """根据关键词采集小红书内容"""
        if not HAS_XHS:
            print("警告: 小红书模块不可用，请确保 xiaohongshu-skills 依赖已安装")
            return []

        all_posts = []
        visited = self._load_visited()
        bridge = None

        for keyword in keywords:
            print(f"\n🔍 搜索: {keyword}")
            self._random_delay()

            try:
                if bridge is None:
                    bridge = BridgePage()
                feeds = search_feeds(bridge, keyword=keyword, filter_option=None)
                print(f"  ✅ 找到 {len(feeds)} 条笔记")
            except Exception as e:
                print(f"  ❌ 搜索失败: {e}")
                continue

            for i, feed in enumerate(feeds[:max_per_keyword]):
                note_id = getattr(feed, 'id', '') or feed.get('noteId', feed.get('id', ''))
                xsec_token = getattr(feed, 'xsec_token', '') or feed.get('xsecToken', '')

                if not note_id or not xsec_token:
                    continue

                # 检查是否已访问
                if note_id in visited:
                    print(f"  ⏭️ 已访问过，跳过: {note_id[:8]}...")
                    continue

                # 获取详情
                try:
                    self._random_delay()
                    detail = get_feed_detail(bridge, note_id, xsec_token, load_all_comments=False)
                    note_info = detail.note.to_dict()
                except Exception as e:
                    print(f"  ❌ 获取详情失败: {e}")
                    continue

                # 构建帖子数据
                post = self._build_post(note_info)
                all_posts.append(post)
                self._save_visited(post)

                print(f"  ✅ 已采集: {post.get('title', '')[:30]}...")

                self._random_delay(2, 4)

                # 每5条额外冷却
                if (i + 1) % 5 == 0:
                    time.sleep(10)

        return all_posts

    def _build_post(self, note_info: dict) -> dict:
        """构建帖子数据"""
        note_id = note_info.get('noteId', '')
        title = note_info.get('title', note_info.get('displayTitle', '无标题'))
        desc = note_info.get('desc', '')
        user = note_info.get('user', {})
        interact = note_info.get('interactInfo', {})

        return {
            'id': note_id,
            'platform': 'xiaohongshu',
            'title': title,
            'content': desc,
            'author': user.get('nickname', ''),
            'url': f"https://www.xiaohongshu.com/explore/{note_id}",
            'timestamp': datetime.now().timestamp(),
            'extra': {
                'ipLocation': note_info.get('ipLocation', ''),
                'likedCount': interact.get('likedCount', '0'),
                'collectedCount': interact.get('collectedCount', '0'),
                'commentCount': interact.get('commentCount', '0'),
            }
        }

    def fetch_from_json(self, json_path: str) -> List[Dict]:
        """从已有JSON文件导入帖子数据（离线模式）"""
        posts = []
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        items = data if isinstance(data, list) else data.get('notes', [])
        for item in items:
            post = {
                'id': item.get('noteId', item.get('id', '')),
                'platform': 'xiaohongshu',
                'title': item.get('title', ''),
                'content': item.get('desc', item.get('content', '')),
                'author': item.get('user', {}).get('nickname', ''),
                'url': item.get('link', item.get('url', '')),
                'timestamp': datetime.now().timestamp(),
            }
            posts.append(post)

        return posts


class TwitterFetcher:
    """X(Twitter)采集器（预留接口）"""

    def __init__(self, output_dir: str = "./data/twitter"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def fetch_by_keywords(self, keywords: List[str], max_per_keyword: int = 20) -> List[Dict]:
        """根据关键词采集Twitter内容

        TODO: 实现Twitter API调用
        - 使用官方API v2（免费额度）
        - 或通过Nitter RSS抓取
        """
        # 占位实现
        print("警告: Twitter采集器尚未实现")
        return []


def create_fetcher(platform: str, output_dir: str = "./data") -> Optional[object]:
    """工厂函数：创建采集器"""
    fetchers = {
        'xiaohongshu': XiaohongshuFetcher,
        'xhs': XiaohongshuFetcher,
        'twitter': TwitterFetcher,
    }
    fetcher_cls = fetchers.get(platform.lower())
    if fetcher_cls:
        return fetcher_cls(output_dir=f"{output_dir}/{platform}")
    return None