"""
套利渠道 HTML 报告生成器
按难易度、额度、知名度排名展示，支持交互式排序和筛选
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arbitrage_channels.db")


def get_channels(sort_by="popularity"):
    """获取所有活跃渠道，支持不同排序方式"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    order_map = {
        "popularity": "popularity DESC",
        "difficulty": "CASE difficulty WHEN '极低' THEN 1 WHEN '低' THEN 2 WHEN '中' THEN 3 WHEN '高' THEN 4 WHEN '极高' THEN 5 END ASC",
        "quota": "CASE WHEN quota_min IS NULL THEN 99999999 ELSE quota_min END ASC",
        "return": "annual_return_max DESC NULLS LAST"
    }
    order = order_map.get(sort_by, "popularity DESC")

    c.execute(f"""
        SELECT * FROM arbitrage_channels 
        WHERE status='active' 
        ORDER BY {order}
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sources():
    """获取推荐博主/来源"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM sources ORDER BY reliability DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def difficulty_color(d):
    colors = {"极低": "#22c55e", "低": "#84cc16", "中": "#f59e0b", "高": "#f97316", "极高": "#ef4444"}
    return colors.get(d, "#64748b")


def risk_color(r):
    colors = {"极低": "#22c55e", "低": "#84cc16", "中": "#f59e0b", "高": "#f97316", "极高": "#ef4444"}
    return colors.get(r, "#64748b")


def generate_html(sort_by="popularity"):
    """生成交互式HTML报告"""
    channels = get_channels(sort_by)
    sources = get_sources()

    # 识别新增渠道（7天内添加）
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id FROM arbitrage_channels WHERE date(created_at) >= date('now', '-7 days')")
    new_channel_ids = {row["id"] for row in c.fetchall()}
    conn.close()

    # 统计
    cats = {}
    for ch in channels:
        cats[ch["category"]] = cats.get(ch["category"], 0) + 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>套利渠道全景报告 - {now}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f8fafc; color: #1e293b; line-height: 1.6; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
.header {{ background: linear-gradient(135deg, #1e293b 0%, #334155 100%); color: white; padding: 40px 20px; text-align: center; border-radius: 16px; margin-bottom: 24px; }}
.header h1 {{ font-size: 2em; margin-bottom: 8px; }}
.header p {{ opacity: 0.8; font-size: 0.95em; }}
.stats-row {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
.stat-card {{ flex: 1; min-width: 160px; background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); text-align: center; }}
.stat-card .num {{ font-size: 2em; font-weight: 700; color: #1e293b; }}
.stat-card .label {{ font-size: 0.85em; color: #64748b; margin-top: 4px; }}
.controls {{ display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; align-items: center; }}
.controls select, .controls input {{ padding: 10px 16px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.9em; background: white; }}
.controls select {{ min-width: 160px; }}
.controls input {{ flex: 1; min-width: 200px; }}
.sort-btns {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.sort-btns button {{ padding: 8px 16px; border: 1px solid #e2e8f0; border-radius: 8px; background: white; cursor: pointer; font-size: 0.85em; transition: all 0.2s; }}
.sort-btns button:hover {{ background: #f1f5f9; }}
.sort-btns button.active {{ background: #1e293b; color: white; border-color: #1e293b; }}
.table-wrapper {{ background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; min-width: 1200px; }}
th {{ background: #f8fafc; padding: 14px 12px; text-align: left; font-size: 0.8em; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 2px solid #e2e8f0; white-space: nowrap; cursor: pointer; }}
th:hover {{ color: #1e293b; }}
td {{ padding: 14px 12px; border-bottom: 1px solid #f1f5f9; font-size: 0.88em; vertical-align: top; }}
tr:hover {{ background: #f8fafc; }}
.badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.78em; font-weight: 600; }}
.badge-diff {{ background: #fef3c7; color: #92400e; }}
.badge-risk {{ background: #fce7f3; color: #9d174d; }}
.badge-pop {{ background: #dbeafe; color: #1e40af; }}
.pop-stars {{ color: #f59e0b; font-size: 0.9em; letter-spacing: 1px; }}
.ch-name {{ font-weight: 600; color: #1e293b; white-space: nowrap; }}
.ch-cat {{ font-size: 0.8em; color: #64748b; }}
.quota-info {{ font-size: 0.8em; color: #64748b; }}
.desc-preview {{ max-width: 280px; font-size: 0.85em; color: #475569; }}
.howto-preview {{ max-width: 280px; font-size: 0.82em; color: #64748b; }}
.ret-info {{ font-weight: 600; color: #059669; font-size: 0.9em; white-space: nowrap; }}
.risk-badge {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }}
.sources-section {{ margin-top: 40px; }}
.sources-section h2 {{ font-size: 1.5em; margin-bottom: 16px; color: #1e293b; }}
.source-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}
.source-card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.source-card h3 {{ font-size: 1.05em; margin-bottom: 6px; }}
.source-card .platform-tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; background: #f1f5f9; color: #475569; margin-bottom: 8px; }}
.source-card .desc {{ font-size: 0.85em; color: #64748b; margin-bottom: 8px; }}
.source-card .meta {{ font-size: 0.8em; color: #94a3b8; }}
.source-card a {{ color: #2563eb; text-decoration: none; }}
.source-card a:hover {{ text-decoration: underline; }}
.expand-btn {{ cursor: pointer; color: #2563eb; font-size: 0.82em; white-space: nowrap; }}
.detail-row {{ display: none; }}
.detail-row.open {{ display: table-row; }}
.detail-cell {{ background: #f8fafc; padding: 20px 16px; font-size: 0.85em; }}
.detail-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.detail-item {{ }}
.detail-item strong {{ color: #475569; font-size: 0.85em; }}
.detail-item div {{ color: #1e293b; margin-top: 2px; }}
.footer {{ text-align: center; padding: 40px 20px; color: #94a3b8; font-size: 0.85em; }}
.new-badge {{ display: inline-block; background: #ef4444; color: white; font-size: 0.7em; font-weight: 700; padding: 2px 8px; border-radius: 10px; margin-left: 8px; vertical-align: middle; animation: pulse 2s infinite; }}
@keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.6; }}
}}
.new-row {{ background: #fef2f2 !important; }}
tr.new-row:hover {{ background: #fee2e2 !important; }}
@media (max-width: 768px) {{
    .stats-row {{ flex-direction: column; }}
    .source-cards {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>📊 套利渠道全景报告</h1>
    <p>数据来源：集思录 · 雪球 · 知乎 · 微信公众号 · 同花顺 · 小红书 &nbsp;|&nbsp; 更新：{now}</p>
</div>

<div class="stats-row">
    <div class="stat-card"><div class="num">{len(channels)}</div><div class="label">活跃套利渠道</div></div>
    <div class="stat-card"><div class="num">{len(cats)}</div><div class="label">渠道大类</div></div>
    <div class="stat-card"><div class="num">{len(sources)}</div><div class="label">推荐博主/来源</div></div>
    <div class="stat-card"><div class="num">{sum(1 for ch in channels if ch['difficulty'] in ('极低','低'))}</div><div class="label">低门槛渠道</div></div>
</div>

<div class="controls">
    <input type="text" id="searchBox" placeholder="🔍 搜索渠道名称、分类、描述..." onkeyup="filterTable()">
    <select id="diffFilter" onchange="filterTable()">
        <option value="">全部难度</option>
        <option value="极低">★ 极低</option>
        <option value="低">★★ 低</option>
        <option value="中">★★★ 中</option>
        <option value="高">★★★★ 高</option>
        <option value="极高">★★★★★ 极高</option>
    </select>
    <select id="catFilter" onchange="filterTable()">
        <option value="">全部分类</option>
"""
    for cat in sorted(cats.keys()):
        html += f'        <option value="{cat}">{cat} ({cats[cat]})</option>\n'

    html += """    </select>
    <div class="sort-btns">
        <button class="active" onclick="sortTable('popularity', this)">📈 知名度</button>
        <button onclick="sortTable('difficulty', this)">🎯 难易度</button>
        <button onclick="sortTable('quota', this)">💰 额度低→高</button>
        <button onclick="sortTable('return', this)">📊 收益率</button>
    </div>
</div>

<div class="table-wrapper">
<table id="channelTable">
<thead>
<tr>
    <th>排名</th>
    <th>渠道名称</th>
    <th>分类</th>
    <th>难度</th>
    <th>额度</th>
    <th>知名度</th>
    <th>年化收益</th>
    <th>风险</th>
    <th>频率</th>
    <th>简介</th>
    <th>操作</th>
</tr>
</thead>
<tbody>
"""
    for i, ch in enumerate(channels, 1):
        is_new = ch["id"] in new_channel_ids
        row_class = "channel-row" + (" new-row" if is_new else "")
        new_badge = ' <span class="new-badge">NEW</span>' if is_new else ""
        diff_color = difficulty_color(ch["difficulty"])
        r_color = risk_color(ch["risk_level"])
        stars = "★" * min(ch["popularity"] // 2, 5) + "☆" * (5 - min(ch["popularity"] // 2, 5))
        ret_str = f'{ch["annual_return_min"]}%~{ch["annual_return_max"]}%' if ch["annual_return_max"] else f'~{ch["annual_return_min"]}%'
        quota_str = ch["quota_desc"] or (f'{ch["quota_min"]:,.0f}' if ch["quota_min"] else "不限")

        html += f"""
<tr class="{row_class}" data-diff="{ch['difficulty']}" data-cat="{ch['category']}" data-name="{ch['name']}">
    <td>{i}</td>
    <td><div class="ch-name">{ch['name']}{new_badge}</div></td>
    <td><div class="ch-cat">{ch['category']}</div></td>
    <td><span class="badge badge-diff" style="border-left:3px solid {diff_color}">{ch['difficulty']}</span></td>
    <td><div class="quota-info">{quota_str}</div></td>
    <td><span class="pop-stars">{stars}</span> <small>{ch['popularity']}/10</small></td>
    <td><span class="ret-info">{ret_str}</span></td>
    <td><span class="badge badge-risk" style="border-left:3px solid {r_color}">{ch['risk_level']}</span></td>
    <td>{ch['trade_frequency']}</td>
    <td><div class="desc-preview">{ch['description'][:80]}...</div></td>
    <td><span class="expand-btn" onclick="toggleDetail({ch['id']})">展开▾</span></td>
</tr>
<tr class="detail-row" id="detail-{ch['id']}">
    <td colspan="11">
        <div class="detail-cell">
            <div class="detail-grid">
                <div class="detail-item"><strong>📝 操作步骤</strong><div>{ch['how_to'] or '—'}</div></div>
                <div class="detail-item"><strong>🚪 参与门槛</strong><div>{ch['requirements'] or '—'}</div></div>
                <div class="detail-item"><strong>⚠️ 主要风险</strong><div>{ch['key_risks'] or '—'}</div></div>
                <div class="detail-item"><strong>🏦 操作平台</strong><div>{ch['platform'] or '—'}</div></div>
                <div class="detail-item"><strong>📱 信息平台</strong><div>{ch['source_platforms'] or '—'}</div></div>
                <div class="detail-item"><strong>💰 额度说明</strong><div>{quota_str}</div></div>
"""

        # 添加参考链接
        if ch["source_urls"]:
            try:
                urls = json.loads(ch["source_urls"])
                if urls:
                    html += '<div class="detail-item"><strong>🔗 参考链接</strong><div>'
                    for u in urls:
                        html += f'<a href="{u}" target="_blank" style="display:block;margin-top:4px;">{u[:70]}...</a>'
                    html += '</div></div>'
            except:
                pass

        # 推荐博主
        if ch["recommended_bloggers"]:
            try:
                bloggers = json.loads(ch["recommended_bloggers"])
                if bloggers:
                    html += '<div class="detail-item"><strong>👤 推荐博主</strong><div>'
                    for b in bloggers:
                        name = b.get("name", "")
                        plat = b.get("platform", "")
                        url = b.get("url", "")
                        html += f'<a href="{url}" target="_blank" style="display:block;margin-top:4px;">{name} ({plat})</a>'
                    html += '</div></div>'
            except:
                pass

        html += """
            </div>
        </div>
    </td>
</tr>
"""

    html += """
</tbody>
</table>
</div>

<div class="sources-section">
    <h2>📢 推荐关注：套利相关博主 & 信息来源</h2>
    <div class="source-cards">
"""
    for s in sources:
        rel_stars = "⭐" * s["reliability"]
        url_html = f'<a href="{s["url"]}" target="_blank">{s["url"]}</a>' if s["url"] and s["url"].startswith("http") else s["url"]
        html += f"""
<div class="source-card">
    <h3>{s['name']}</h3>
    <div class="platform-tag">{s['platform']}</div>
    <div class="desc">{s['description']}</div>
    <div class="meta">{rel_stars} 可靠性 · {s['followers']} · {s['update_frequency']}更新</div>
    <div style="margin-top:8px;font-size:0.82em;">🔗 {url_html}</div>
</div>
"""

    html += f"""
    </div>
</div>

<div class="footer">
    <p>📊 套利渠道追踪系统 &copy; 2026 | 每日自动更新 | 数据仅供参考，不构成投资建议</p>
</div>

</div>

<script>
function filterTable() {{
    var search = document.getElementById('searchBox').value.toLowerCase();
    var diff = document.getElementById('diffFilter').value;
    var cat = document.getElementById('catFilter').value;
    var rows = document.querySelectorAll('.channel-row');
    var count = 0;
    rows.forEach(function(row) {{
        var name = row.getAttribute('data-name').toLowerCase();
        var rDiff = row.getAttribute('data-diff');
        var rCat = row.getAttribute('data-cat');
        var show = true;
        if (search && !name.includes(search)) show = false;
        if (diff && rDiff !== diff) show = false;
        if (cat && rCat !== cat) show = false;
        row.style.display = show ? '' : 'none';
        // 隐藏对应详情行
        var detailRow = row.nextElementSibling;
        if (detailRow && detailRow.classList.contains('detail-row')) {{
            detailRow.style.display = 'none';
            detailRow.classList.remove('open');
        }}
        if (show) count++;
    }});
}}

function toggleDetail(id) {{
    var detail = document.getElementById('detail-' + id);
    if (detail.classList.contains('open')) {{
        detail.classList.remove('open');
        detail.style.display = 'none';
    }} else {{
        detail.classList.add('open');
        detail.style.display = 'table-row';
    }}
}}

function sortTable(sortBy, btn) {{
    // 切换active状态
    document.querySelectorAll('.sort-btns button').forEach(function(b) {{ b.classList.remove('active'); }});
    btn.classList.add('active');
    // 重新加载页面
    window.location.href = '?sort=' + sortBy;
}}

// 从URL获取排序参数
var urlParams = new URLSearchParams(window.location.search);
var sort = urlParams.get('sort');
if (sort) {{
    var activeBtn = document.querySelector('[onclick*="' + sort + '"]');
    if (activeBtn) {{
        document.querySelectorAll('.sort-btns button').forEach(function(b) {{ b.classList.remove('active'); }});
        activeBtn.classList.add('active');
    }}
}}
</script>
</body>
</html>
"""
    return html


def save_report(sort_by="popularity"):
    """生成并保存HTML报告，文件名带日期"""
    html = generate_html(sort_by)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"arbitrage_report_{today}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] Report saved to {report_path}")
    return report_path


if __name__ == "__main__":
    save_report()
