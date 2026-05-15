"""
Redclaw CLI - 命令行入口
"""

import sys
import json
import click
from pathlib import Path
from datetime import datetime
from tabulate import tabulate

# 导入核心模块
from redclaw.core import RadarAgent


# ============== 配置 ==============

DEFAULT_DB = "redclaw.db"
DEFAULT_DATA_DIR = "./data"


# ============== CLI 命令 ==============

@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Redclaw - 垂直情报Agent CLI"""
    pass


@cli.command()
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def init(db):
    """初始化Agent数据库"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)
    click.echo("✅ 数据库初始化完成")
    agent.close()


@cli.command()
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def list_radars(db):
    """列出所有雷达"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)
    radars = agent.list_radars()

    if not radars:
        click.echo("📭 暂无雷达配置")
        return

    table_data = []
    for r in radars:
        table_data.append([
            r['id'][:8],
            r['name'],
            ', '.join(r['keywords'][:2]) + ('...' if len(r['keywords']) > 2 else ''),
            ', '.join(r['platforms']),
            r['description'][:30] + '...' if len(r['description']) > 30 else r['description'],
        ])

    click.echo(tabulate(table_data, headers=['ID', '名称', '关键词', '平台', '描述']))
    agent.close()


@cli.command()
@click.argument('radar_id')
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def radar_info(radar_id, db):
    """查看雷达详情"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)
    radar = agent.get_radar(radar_id)

    if not radar:
        click.echo(f"❌ 雷达 {radar_id} 不存在")
        return

    click.echo(f"""
📡 雷达详情: {radar['name']}

ID: {radar['id']}
关键词: {', '.join(radar['keywords'])}
平台: {', '.join(radar['platforms'])}
描述: {radar['description']}
质量阈值: {radar['quality_threshold']}
自动扩展: {'是' if radar['enable_auto_expand'] else '否'}
创建时间: {datetime.fromtimestamp(radar['created_at']).strftime('%Y-%m-%d %H:%M:%S')}
""")
    agent.close()


@cli.command()
@click.argument('name')
@click.argument('keywords', nargs=-1)
@click.option('--user-id', default='default', help='用户ID')
@click.option('--platforms', default='xiaohongshu', help='平台列表，逗号分隔')
@click.option('--desc', default='', help='雷达描述')
@click.option('--threshold', default=0.7, type=float, help='质量阈值')
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def create_radar(name, keywords, user_id, platforms, desc, threshold, db):
    """创建新的情报雷达"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)

    radar_id = f"radar_{datetime.now().timestamp()}"
    platforms_list = [p.strip() for p in platforms.split(',')]
    keywords_list = list(keywords) if keywords else ['AI产品经理']

    try:
        agent.create_radar(
            radar_id=radar_id,
            user_id=user_id,
            name=name,
            keywords=keywords_list,
            platforms=platforms_list,
            description=desc or name,
            quality_threshold=threshold,
        )
        click.echo(f"✅ 雷达创建成功: {radar_id}")
    except Exception as e:
        click.echo(f"❌ 创建失败: {e}")

    agent.close()


@cli.command()
@click.argument('radar_id')
@click.option('--keywords', help='关键词列表，逗号分隔（覆盖雷达配置）')
@click.option('--max-per', default=10, help='每个关键词最大采集数')
@click.option('--skip-images', is_flag=True, help='跳过图片下载')
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def fetch(radar_id, keywords, max_per, skip_images, db):
    """执行数据采集"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)
    radar = agent.get_radar(radar_id)

    if not radar:
        click.echo(f"❌ 雷达 {radar_id} 不存在")
        return

    click.echo(f"🔍 开始采集: {radar['name']}")

    # 导入采集器
    from redclaw.modules.fetcher import create_fetcher

    all_posts = []
    for platform in radar['platforms']:
        fetcher = create_fetcher(platform, DEFAULT_DATA_DIR)
        if not fetcher:
            click.echo(f"⚠️ 平台 {platform} 采集器不存在")
            continue

        kw = keywords.split(',') if keywords else radar['keywords']
        try:
            posts = fetcher.fetch_by_keywords(kw, max_per, skip_images)
            for p in posts:
                p['radar_id'] = radar_id
            all_posts.extend(posts)
            click.echo(f"  ✅ {platform}: 采集 {len(posts)} 条")
        except Exception as e:
            click.echo(f"  ❌ {platform} 采集失败: {e}")

    # 过滤
    click.echo(f"\n📊 相关性过滤...")
    filtered = agent.filter_by_relevance(all_posts, radar)
    click.echo(f"  ✅ 保留 {len(filtered)} 条（阈值={radar['quality_threshold']}）")

    # 聚类
    click.echo(f"\n📂 事件聚类...")
    events = agent.cluster_events(filtered, radar_id)
    click.echo(f"  ✅ 生成 {len(events)} 个事件")

    click.echo(f"\n✅ 采集完成！共处理 {len(all_posts)} 条，保留 {len(filtered)} 条，生成 {len(events)} 个事件")

    agent.close()


@cli.command()
@click.argument('radar_id')
@click.option('--date', default=None, help='日期 (YYYY-MM-DD)')
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def daily_brief(radar_id, date, db):
    """生成并显示日报"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    brief = agent.generate_daily_brief(radar_id, date)
    click.echo(brief)

    agent.close()


@cli.command()
@click.argument('radar_id')
@click.option('--limit', default=20, help='历史消息数量')
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def chat_history(radar_id, limit, db):
    """查看对话历史"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)
    history = agent.get_chat_history(radar_id, limit)

    if not history:
        click.echo("📭 暂无对话历史")
        return

    for msg in reversed(history):
        role = "👤 用户" if msg['role'] == 'user' else "🤖 Agent"
        time_str = datetime.fromtimestamp(msg['created_at']).strftime('%H:%M:%S')
        click.echo(f"\n{role} [{time_str}]")
        click.echo(f"  {msg['content'][:200]}...")

    agent.close()


@cli.command()
@click.argument('radar_id')
@click.argument('question')
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def ask(radar_id, question, db):
    """向Agent提问"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)

    click.echo(f"\n👤 您: {question}")
    answer = agent.handle_user_query(radar_id, question)
    click.echo(f"\n🤖 Agent: {answer}")

    agent.close()


@cli.command()
@click.argument('radar_id')
@click.option('--hours', default=24, help='时间范围（小时）')
@click.option('--db', default=DEFAULT_DB, help='数据库路径')
def posts(radar_id, hours, db):
    """列出雷达收录的帖子"""
    agent = RadarAgent(db_path=db, data_dir=DEFAULT_DATA_DIR)

    since = datetime.now().timestamp() - hours * 3600
    posts = agent.get_posts(radar_id, since=since)

    if not posts:
        click.echo("📭 暂无收录的帖子")
        return

    click.echo(f"📝 共 {len(posts)} 条帖子（近 {hours} 小时）\n")

    table_data = []
    for p in posts[:50]:
        title = p.get('title', '')[:40] + ('...' if len(p.get('title', '')) > 40 else '')
        score = f"{p.get('relevance_score', 0):.2f}" if p.get('relevance_score') else "N/A"
        time_str = datetime.fromtimestamp(p['timestamp']).strftime('%m-%d %H:%M') if p.get('timestamp') else ''
        table_data.append([
            p.get('platform', ''),
            title,
            p.get('author', '')[:15],
            score,
            time_str,
        ])

    click.echo(tabulate(table_data, headers=['平台', '标题', '作者', '相关分', '时间']))

    agent.close()


# ============== 主入口 ==============

def main():
    cli()


if __name__ == "__main__":
    main()