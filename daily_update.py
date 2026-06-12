"""
套利渠道每日更新脚本
功能：
1. 从数据库读取现有渠道
2. 搜索各平台最新套利相关内容
3. 更新快照表
4. 生成HTML报告
5. 同步到 github-pages/index.html（用于 GitHub Pages 部署）
"""
import sqlite3
import json
import os
import sys
import io
import shutil
import subprocess
from datetime import datetime

# Fix Windows GBK encoding for emojis
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "arbitrage_channels.db")
PAGES_DIR = os.path.join(BASE_DIR, "github-pages")


def add_daily_snapshot():
    """为所有活跃渠道添加每日快照"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    # 获取所有活跃渠道
    c.execute("SELECT id, name, popularity FROM arbitrage_channels WHERE status='active'")
    channels = c.fetchall()

    for ch_id, name, pop in channels:
        # 检查今天是否已有快照
        c.execute("SELECT id FROM daily_snapshots WHERE channel_id=? AND snapshot_date=?", (ch_id, today))
        if not c.fetchone():
            c.execute("""
                INSERT INTO daily_snapshots (channel_id, snapshot_date, popularity, opportunity_score)
                VALUES (?, ?, ?, ?)
            """, (ch_id, today, pop, None))

    conn.commit()

    # 统计
    c.execute("SELECT COUNT(*) FROM daily_snapshots WHERE snapshot_date=?", (today,))
    count = c.fetchone()[0]

    conn.close()
    print(f"[OK] Added {count} daily snapshots for {today}")
    return count


def get_stats():
    """获取统计信息"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM arbitrage_channels WHERE status='active'")
    total_channels = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM sources")
    total_sources = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT snapshot_date) FROM daily_snapshots")
    days_tracked = c.fetchone()[0]

    c.execute("""
        SELECT category, COUNT(*) as cnt FROM arbitrage_channels 
        WHERE status='active' GROUP BY category ORDER BY cnt DESC
    """)
    cats = c.fetchall()

    conn.close()
    return {
        "total_channels": total_channels,
        "total_sources": total_sources,
        "days_tracked": days_tracked,
        "categories": dict(cats)
    }


def run_daily_update():
    """执行每日更新"""
    print(f"\n{'='*60}")
    print(f"  套利渠道每日更新 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. 添加快照
    snapshot_count = add_daily_snapshot()

    # 2. 统计
    stats = get_stats()
    print(f"\n📊 统计概览:")
    print(f"   活跃渠道: {stats['total_channels']}")
    print(f"   推荐来源: {stats['total_sources']}")
    print(f"   追踪天数: {stats['days_tracked']}")
    print(f"   今日快照: {snapshot_count}")
    print(f"\n   分类分布:")
    for cat, cnt in stats["categories"].items():
        print(f"     {cat}: {cnt}")

    # 3. 生成报告（带日期）
    from report_generator import save_report
    report_path = save_report()
    today = datetime.now().strftime("%Y-%m-%d")
    dated_report_name = f"arbitrage_report_{today}.html"
    dated_report_path = os.path.join(BASE_DIR, dated_report_name)

    # 4. 同步到 GitHub Pages 目录
    # 4.1 同步到 github-pages/（备用）
    if os.path.exists(PAGES_DIR):
        # 套利报告 → 带日期的版本（用于历史对比）
        dated_pages_path = os.path.join(PAGES_DIR, dated_report_name)
        if os.path.exists(dated_report_path):
            shutil.copy2(dated_report_path, dated_pages_path)
            print(f"\n📤 已同步 dated 报告 (github-pages/): {dated_pages_path}")
        
        # 套利报告 → arbitrage.html（最新版本，用于首页访问）
        arbitrage_path = os.path.join(PAGES_DIR, "arbitrage.html")
        if os.path.exists(report_path):
            shutil.copy2(report_path, arbitrage_path)
            print(f"📤 已同步最新报告 (github-pages/): {arbitrage_path}")
    
    # 4.2 同步到根目录（GitHub Pages / (root) 模式）
    # 套利报告 → 带日期的版本
    if os.path.exists(dated_report_path):
        root_dated_path = os.path.join(BASE_DIR, dated_report_name)
        shutil.copy2(dated_report_path, root_dated_path)
        print(f"📤 已同步 dated 报告 (根目录): {root_dated_path}")
    
    # 套利报告 → arbitrage.html（最新版本）
    if os.path.exists(report_path):
        root_arbitrage_path = os.path.join(BASE_DIR, "arbitrage.html")
        shutil.copy2(report_path, root_arbitrage_path)
        print(f"📤 已同步最新报告 (根目录): {root_arbitrage_path}")

    print(f"\n✅ 更新完成！报告路径: {report_path}")
    return report_path


if __name__ == "__main__":
    # 先确保数据库存在并已seed
    if not os.path.exists(DB_PATH):
        print("[!] Database not found. Running seed first...")
        from db_schema import create_database
        from seed_data import seed_database
        create_database()
        seed_database()

    run_daily_update()
