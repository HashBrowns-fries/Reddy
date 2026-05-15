"""
核心Agent引擎 - 垂直情报Agent
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# 配置 - 支持多种LLM API
# MiniMax (主要使用 - Anthropic兼容接口)
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"  # OpenAI兼容端点
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")  # MiniMax-M2.7 模型

# DeepSeek (备用)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-key")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

# 当前使用的API
CURRENT_API = os.getenv("LLM_API", "minimax")  # deepseek 或 minimax

# 获取当前模型名
def get_model_name():
    if CURRENT_API == "minimax" and MINIMAX_API_KEY:
        return MINIMAX_MODEL
    if CURRENT_API == "deepseek" and DEEPSEEK_API_KEY:
        return DEEPSEEK_MODEL
    # 默认使用 MiniMax
    return MINIMAX_MODEL

try:
    from openai import OpenAI

    if CURRENT_API == "deepseek" and DEEPSEEK_API_KEY:
        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        print(f"✅ DeepSeek API 已配置 (model: {DEEPSEEK_MODEL})")
    elif CURRENT_API == "minimax" and MINIMAX_API_KEY:
        _client = OpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL)
        print(f"✅ MiniMax API 已配置 (model: {MINIMAX_MODEL})")
    else:
        # 默认使用 DeepSeek
        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        print(f"✅ DeepSeek API 已配置 (model: {DEEPSEEK_MODEL})")
    HAS_LLM = True
except ImportError:
    HAS_LLM = False
    print("❌ 未安装 openai 库")


class RadarAgent:
    """垂直情报Agent核心引擎"""

    def __init__(self, db_path: str = "redclaw.db", data_dir: str = "./data"):
        self.db_path = db_path
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS radars (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                name TEXT,
                keywords TEXT,
                platforms TEXT,
                description TEXT,
                frequency TEXT DEFAULT 'hourly',
                quality_threshold REAL DEFAULT 0.7,
                enable_auto_expand INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                radar_id TEXT,
                platform TEXT,
                title TEXT,
                content TEXT,
                author TEXT,
                url TEXT,
                timestamp REAL,
                relevance_score REAL,
                event_id TEXT,
                is_read INTEGER DEFAULT 0,
                created_at REAL,
                FOREIGN KEY (radar_id) REFERENCES radars(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                radar_id TEXT,
                title TEXT,
                sample_post TEXT,
                summary TEXT,
                source_count INTEGER DEFAULT 1,
                last_updated REAL,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS daily_briefs (
                id TEXT PRIMARY KEY,
                radar_id TEXT,
                date TEXT,
                content TEXT,
                event_count INTEGER,
                created_at REAL,
                FOREIGN KEY (radar_id) REFERENCES radars(id)
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                radar_id TEXT,
                role TEXT,
                content TEXT,
                created_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_posts_radar ON posts(radar_id);
            CREATE INDEX IF NOT EXISTS idx_posts_event ON posts(event_id);
            CREATE INDEX IF NOT EXISTS idx_events_radar ON events(radar_id);
        """)
        self.conn.commit()

    # ============== 雷达配置管理 ==============

    def create_radar(
        self,
        radar_id: str,
        user_id: str,
        name: str,
        keywords: List[str],
        platforms: List[str],
        description: str,
        quality_threshold: float = 0.7,
        frequency: str = "hourly",
        enable_auto_expand: bool = False
    ) -> str:
        """创建新的情报雷达"""
        now = datetime.now().timestamp()
        self.conn.execute("""
            INSERT INTO radars (id, user_id, name, keywords, platforms, description,
                               frequency, quality_threshold, enable_auto_expand, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (radar_id, user_id, name, json.dumps(keywords), json.dumps(platforms),
              description, frequency, quality_threshold, 1 if enable_auto_expand else 0, now, now))
        self.conn.commit()
        return radar_id

    def get_radar(self, radar_id: str) -> Optional[Dict]:
        """获取雷达配置"""
        row = self.conn.execute("SELECT * FROM radars WHERE id = ?", (radar_id,)).fetchone()
        if not row:
            return None
        return self._row_to_radar(row)

    def list_radars(self, user_id: str = None) -> List[Dict]:
        """列出用户的雷达"""
        if user_id:
            rows = self.conn.execute("SELECT * FROM radars WHERE user_id = ?", (user_id,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM radars").fetchall()
        return [self._row_to_radar(row) for row in rows]

    def _row_to_radar(self, row: tuple) -> Dict:
        cols = ['id', 'user_id', 'name', 'keywords', 'platforms', 'description',
                'frequency', 'quality_threshold', 'enable_auto_expand', 'created_at', 'updated_at']
        d = dict(zip(cols, row))
        d['keywords'] = json.loads(d['keywords'])
        d['platforms'] = json.loads(d['platforms'])
        d['enable_auto_expand'] = bool(d['enable_auto_expand'])
        return d

    # ============== 帖子管理 ==============

    def save_post(self, post: Dict) -> bool:
        """保存帖子到数据库"""
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO posts
                (id, radar_id, platform, title, content, author, url, timestamp,
                 relevance_score, event_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                post.get('id'),
                post.get('radar_id'),
                post.get('platform'),
                post.get('title', ''),
                post.get('content', ''),
                post.get('author', ''),
                post.get('url', ''),
                post.get('timestamp', datetime.now().timestamp()),
                post.get('relevance_score', 0.0),
                post.get('event_id'),
                datetime.now().timestamp()
            ))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"保存帖子失败: {e}")
            return False

    def get_posts(self, radar_id: str, since: float = None, limit: int = 100) -> List[Dict]:
        """获取雷达的相关帖子"""
        query = "SELECT * FROM posts WHERE radar_id = ?"
        params = [radar_id]
        if since:
            query += " AND timestamp > ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_post(row) for row in rows]

    def _row_to_post(self, row: tuple) -> Dict:
        cols = ['id', 'radar_id', 'platform', 'title', 'content', 'author', 'url',
                'timestamp', 'relevance_score', 'event_id', 'is_read', 'created_at']
        return dict(zip(cols, row))

    # ============== LLM相关功能 ==============

    def filter_by_relevance(self, posts: List[Dict], radar: Dict) -> List[Dict]:
        """使用 LLM 计算相关性分数，过滤低分帖子"""
        if not HAS_LLM:
            # 无API时返回所有帖子
            return posts

        threshold = radar.get('quality_threshold', 0.7)
        filtered = []

        for post in posts:
            score, reason = self._llm_judge_relevance(post, radar)
            if score >= threshold:
                post['relevance_score'] = score
                post['relevance_reason'] = reason
                filtered.append(post)
            else:
                print(f"  过滤: {post.get('title', '')[:30]}... (分数={score})")

        return filtered

    def _llm_judge_relevance(self, post: Dict, radar: Dict) -> Tuple[float, str]:
        """让LLM判断帖子与雷达需求的相关性"""
        prompt = f"""用户需求：{radar.get('description', '')}

帖子内容：
标题：{post.get('title', '')}
内容：{post.get('content', '')[:1500]}

请判断这篇帖子与用户需求的相关度，返回0-1的分数和简短原因。
格式：分数|原因
分数只返回数字，如0.85|原因描述"""
        try:
            response = _client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            result = response.choices[0].message.content.strip()
            parts = result.split("|", 1)
            if len(parts) == 2:
                score = float(parts[0].strip())
                reason = parts[1].strip()
                return score, reason
        except Exception as e:
            print(f"LLM判断失败: {e}")

        return 0.5, "API错误，使用默认分数"

    def cluster_events(self, posts: List[Dict], radar_id: str) -> Dict[str, List[Dict]]:
        """将帖子按事件聚类"""
        events = {}
        recent_events = self._get_recent_events(radar_id)

        for post in posts:
            matched_event_id = None

            # 与已有事件比对
            for event in recent_events:
                if self._is_same_event(post, event['sample_post']):
                    matched_event_id = event['id']
                    # 更新事件样本（取最新的）
                    self.conn.execute(
                        "UPDATE events SET last_updated = ?, source_count = source_count + 1 WHERE id = ?",
                        (datetime.now().timestamp(), matched_event_id)
                    )
                    break

            if not matched_event_id:
                # 创建新事件
                matched_event_id = f"evt_{datetime.now().timestamp()}"
                self.conn.execute("""
                    INSERT INTO events (id, radar_id, title, sample_post, last_updated, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    matched_event_id,
                    radar_id,
                    post.get('title', '')[:100],
                    json.dumps(post),
                    datetime.now().timestamp(),
                    datetime.now().timestamp()
                ))
                self.conn.commit()

            post['event_id'] = matched_event_id
            self.save_post(post)

            if matched_event_id not in events:
                events[matched_event_id] = []
            events[matched_event_id].append(post)

        return events

    def _get_recent_events(self, radar_id: str, hours: int = 24) -> List[Dict]:
        """获取最近的事件"""
        since = datetime.now().timestamp() - hours * 3600
        rows = self.conn.execute("""
            SELECT id, title, sample_post, last_updated FROM events
            WHERE radar_id = ? AND last_updated > ?
            ORDER BY last_updated DESC
        """, (radar_id, since)).fetchall()
        return [{'id': r[0], 'title': r[1], 'sample_post': json.loads(r[2]), 'last_updated': r[3]}
                for r in rows]

    def _is_same_event(self, post1: Dict, post2: Dict) -> bool:
        """判断两帖子是否同一事件"""
        if not HAS_LLM:
            # 无API时用简单标题比对
            return post1.get('title', '')[:50] == post2.get('title', '')[:50]

        prompt = f"""判断以下两篇帖子是否在报道同一事件（如同一公司招聘、同一产品发布等）。
只需回答"是"或"否"。

帖子1：标题={post1.get('title', '')} 内容={post1.get('content', '')[:500]}
帖子2：标题={post2.get('title', '')} 内容={post2.get('content', '')[:500]}"""
        try:
            response = _client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            result = response.choices[0].message.content.strip()
            return "是" in result
        except Exception:
            return False

    # ============== 摘要生成 ==============

    def generate_daily_brief(self, radar_id: str, date: str = None) -> str:
        """生成日报"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        radar = self.get_radar(radar_id)
        if not radar:
            return "雷达不存在"

        # 获取今日帖子
        since = datetime.now().timestamp() - 86400  # 24小时内
        posts = self.get_posts(radar_id, since=since)

        if not posts:
            return f"## {radar['name']} 日报 - {date}\n\n今日无新内容"

        # 按事件分组
        events = {}
        for post in posts:
            evt_id = post.get('event_id', 'unknown')
            if evt_id not in events:
                events[evt_id] = []
            events[evt_id].append(post)

        # 构建日报内容
        brief = f"""# {radar['name']} 日报

**日期**: {date}
**雷达**: {radar['description']}
**收录**: {len(posts)} 条相关内容，{len(events)} 个事件

---

"""
        for evt_id, evt_posts in events.items():
            first = evt_posts[0]
            brief += f"""## {first.get('title', '未知事件')}

**来源**: {first.get('platform', '未知')} | **作者**: {first.get('author', '未知')}
**相似内容**: {len(evt_posts)} 条

"""
            if len(evt_posts) > 1:
                brief += "**多来源整合**:\n"
                for p in evt_posts[:3]:
                    brief += f"- [{p.get('title', '')}]({p.get('url', '')}) - {p.get('author', '')}\n"
                brief += "\n"

            brief += f"**内容摘要**: {first.get('content', '')[:300]}...\n\n"

        # 保存日报
        brief_id = f"brief_{radar_id}_{date}"
        self.conn.execute("""
            INSERT OR REPLACE INTO daily_briefs (id, radar_id, date, content, event_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (brief_id, radar_id, date, brief, len(events), datetime.now().timestamp()))
        self.conn.commit()

        return brief

    def generate_event_summary(self, event_id: str) -> str:
        """生成事件摘要"""
        rows = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchall()
        if not rows:
            return "事件不存在"
        evt = {'id': rows[0][0], 'title': rows[0][2], 'sample_post': json.loads(rows[0][3])}
        posts = self.conn.execute(
            "SELECT * FROM posts WHERE event_id = ?", (event_id,)
        ).fetchall()
        posts = [self._row_to_post(row) for row in posts]

        summary = f"""# 事件: {evt['title']}

**收录来源**: {len(posts)} 条

"""
        for p in posts[:5]:
            summary += f"""### {p.get('title', '')}

{p.get('content', '')[:500]}...

来源: [{p.get('platform', '')}]({p.get('url', '')})

---
"""
        return summary

    # ============== 对话问答 ==============

    def handle_user_query(self, radar_id: str, query: str) -> str:
        """处理用户追问"""
        # 记录用户问题
        self.conn.execute("""
            INSERT INTO chat_history (radar_id, role, content, created_at)
            VALUES (?, 'user', ?, ?)
        """, (radar_id, query, datetime.now().timestamp()))

        # 获取相关帖子
        since = datetime.now().timestamp() - 86400 * 7  # 7天内
        posts = self.get_posts(radar_id, since=since)

        if not posts:
            answer = "暂无相关内容，无法回答您的问题。"
        elif not HAS_LLM:
            # 无API时用简单搜索
            answer = self._simple_search(query, posts)
        else:
            try:
                answer = self._llm_answer(query, posts)
            except Exception as e:
                # LLM失败时降级到简单搜索
                print(f"   ⚠️ LLM调用失败，降级到简单搜索: {e}")
                answer = self._simple_search(query, posts)

        # 记录回答
        self.conn.execute("""
            INSERT INTO chat_history (radar_id, role, content, created_at)
            VALUES (?, 'assistant', ?, ?)
        """, (radar_id, answer, datetime.now().timestamp()))
        self.conn.commit()

        return answer

    def _simple_search(self, query: str, posts: List[Dict]) -> str:
        """简单关键词搜索"""
        keywords = query.lower().split()
        results = []
        for p in posts:
            text = (p.get('title', '') + ' ' + p.get('content', '')).lower()
            if any(k in text for k in keywords):
                results.append(p)
        if not results:
            return "未找到相关内容"
        resp = f"找到 {len(results)} 条相关内容：\n\n"
        for r in results[:5]:
            resp += f"- {r.get('title', '')}\n  {r.get('content', '')[:100]}...\n\n"
        return resp

    def _llm_answer(self, query: str, posts: List[Dict]) -> str:
        """使用LLM回答"""
        context = ""
        for p in posts[:10]:
            context += f"""标题: {p.get('title', '')}
内容: {p.get('content', '')[:500]}
来源: {p.get('platform', '')} | {p.get('author', '')}

---
"""
        prompt = f"""基于以下收集到的内容，回答用户的问题。如果内容不足以回答，请说明。

用户问题: {query}

相关内容的帖子：
{context}

请给出有用的回答。"""

        try:
            response = _client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"生成回答失败: {e}"

    def get_chat_history(self, radar_id: str, limit: int = 20) -> List[Dict]:
        """获取对话历史"""
        rows = self.conn.execute("""
            SELECT role, content, created_at FROM chat_history
            WHERE radar_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (radar_id, limit)).fetchall()
        return [{'role': r[0], 'content': r[1], 'created_at': r[2]} for r in rows]

    def close(self):
        """关闭数据库连接"""
        self.conn.close()