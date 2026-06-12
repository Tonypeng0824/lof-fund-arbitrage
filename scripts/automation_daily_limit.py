#!/usr/bin/env python3
"""
LOF限额每日采集 - 完整自动化脚本
整合：数据采集 → 主报告生成 → 重点基金报告 → 汇总页面 → Git推送
用法：python automation_daily_limit.py
"""
import os, sys, time, subprocess, shutil, sqlite3

WORKSPACE = os.getenv("LOF_WORKSPACE", r"C:\Users\Administrator\WorkBuddy\lof-fund-arbitrage")
DATA_DIR = os.path.join(WORKSPACE, 'lof_data')
GITHUB_PAGES = os.path.join(WORKSPACE, 'github-pages')
SCRIPTS_DIR = os.path.join(WORKSPACE, 'scripts')
PYTHON = os.getenv("LOF_PYTHON", r"C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe")

VERCEL_PROJECT = os.getenv("VERCEL_PROJECT", "lof-fund-arbitrage")
VERCEL_ORG = os.getenv("VERCEL_ORG", "")  # 留空则使用当前登录用户

# 重点基金列表（与 fund_report.py KNOWN_LIMITS 同步）
KEY_FUNDS = [
    '501312', '501225', '160644', '161128',
    '161130', '161125', '164824', '164906',
    '162415', '501300',
]

def run_script(script_path, args=None):
    """运行 Python 脚本，返回是否成功。"""
    cmd = [PYTHON, script_path]
    if args:
        cmd.extend(args)
    print(f'\n{"="*60}')
    print(f'▶ 运行: {os.path.basename(script_path)}')
    print(f'{"="*60}')
    result = subprocess.run(cmd, cwd=WORKSPACE, capture_output=False, text=True)
    return result.returncode == 0

def copy_to_github_pages():
    """将生成的报告复制到 github-pages/ 目录。"""
    import glob
    copied = 0
    today_str = time.strftime('%Y-%m-%d')

    # 1) 带日期的存档版（每日独立保留，用于历史对比）
    src_dated = os.path.join(WORKSPACE, 'data', f'lof_full_report_{today_str}.html')
    dst_dated = os.path.join(GITHUB_PAGES, f'lof_full_report_{today_str}.html')
    if os.path.exists(src_dated):
        shutil.copy2(src_dated, dst_dated)
        print(f'  ✅ 存档报告已复制: lof_full_report_{today_str}.html')
        copied += 1
    else:
        print(f'  ⚠️ 存档报告不存在: {src_dated}')

    # 2) 最新版入口（始终覆盖，供首访问问）
    src_latest = os.path.join(WORKSPACE, 'data', 'lof_full_report.html')
    dst_latest = os.path.join(GITHUB_PAGES, 'lof_full_report.html')
    if os.path.exists(src_latest):
        shutil.copy2(src_latest, dst_latest)
        print(f'  ✅ 最新报告入口已复制: lof_full_report.html')
        copied += 1

    # 3) 重点基金独立报告
    reports_dir = os.path.join(WORKSPACE, 'reports')
    if os.path.exists(reports_dir):
        count = 0
        for fname in os.listdir(reports_dir):
            if fname.endswith('_report.html'):
                src = os.path.join(reports_dir, fname)
                dst = os.path.join(GITHUB_PAGES, fname)
                shutil.copy2(src, dst)
                copied += 1
                count += 1
        if count > 0:
            print(f'  ✅ 独立报告已复制: {count} 个')

    # 4) 生成/更新报告索引页
    build_reports_index()

    return copied

def build_key_funds_index():
    """生成重点基金汇总页面 key_funds.html。"""
    db_path = os.path.join(DATA_DIR, 'lof_limits.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 获取最新日期
    cur.execute('SELECT MAX(date) FROM lof_limit_daily')
    latest_date = cur.fetchone()[0]
    if not latest_date:
        print('  ⚠️ 数据库中无数据')
        conn.close()
        return False

    # 获取重点基金最新数据
    funds = []
    for code in KEY_FUNDS:
        cur.execute(
            'SELECT name, sub_status, sub_limit FROM lof_limit_daily WHERE date=? AND code=?',
            (latest_date, code)
        )
        row = cur.fetchone()
        if row:
            funds.append({
                'code': code,
                'name': row['name'] or f'基金{code}',
                'status': row['sub_status'] or '-',
                'limit': row['sub_limit'] or '-',
            })
        else:
            funds.append({
                'code': code,
                'name': f'基金{code}',
                'status': '-',
                'limit': '-',
            })
    conn.close()

    # 生成表格行
    rows_html = ''
    for f in funds:
        code = f['code']
        report_file = f'{code}_report.html'
        report_path = os.path.join(GITHUB_PAGES, report_file)

        if os.path.exists(report_path):
            link = (f'<a href="{report_file}" target="_blank" '
                    f'style="color:#ff6b35;text-decoration:none;font-weight:700;">'
                    f'📊 查看分析</a>')
        else:
            link = '<span style="color:#888;font-size:12px;">报告生成中...</span>'

        status = f['status']
        lim = f['limit']

        if '暂停' in status or '暂停' in str(lim):
            badge = '<span style="background:#ff3d4f22;color:#ff3d4f;padding:2px 8px;border-radius:3px;font-size:12px;">🔴 暂停</span>'
        elif '大额' in status:
            badge = (f'<span style="background:#ff980022;color:#ff9800;'
                     f'padding:2px 8px;border-radius:3px;font-size:12px;">'
                     f'🟠 限大额 {lim}</span>')
        elif lim in ('无限制', '无限额', '-'):
            badge = '<span style="background:#00e67622;color:#00e676;padding:2px 8px;border-radius:3px;font-size:12px;">🟢 开放</span>'
        else:
            badge = (f'<span style="background:#ff980022;color:#ff9800;'
                     f'padding:2px 8px;border-radius:3px;font-size:12px;">'
                     f'🟠 限额 {lim}</span>')

        rows_html += f'''
        <tr style="border-bottom:1px solid #1e2a3a;">
          <td style="padding:10px;color:#ff6b35;font-weight:600;">{code}</td>
          <td style="padding:10px;color:#e6e8ec;">{f['name']}</td>
          <td style="padding:10px;">{badge}</td>
          <td style="padding:10px;color:#8b95a5;font-size:13px;">{lim}</td>
          <td style="padding:10px;text-align:center;">{link}</td>
        </tr>'''

    # 生成 HTML
    today = time.strftime('%Y-%m-%d %H:%M:%S')
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>重点基金监控 · LOF套利终端</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0e14; color:#e6e8ec; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .container {{ max-width:1200px; margin:0 auto; padding:20px; }}
  .header {{ display:flex; justify-content:space-between; align-items:center; padding:20px 0; border-bottom:1px solid #1e2a3a; margin-bottom:20px; }}
  .header h1 {{ font-size:22px; font-weight:700; background:linear-gradient(135deg,#ff6b35,#00e5ff); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
  .header .sub {{ font-size:12px; color:#5c6678; margin-top:4px; font-family:monospace; }}
  .back-link {{ color:#8b95a5; text-decoration:none; font-size:13px; }}
  .back-link:hover {{ color:#ff6b35; }}
  .card {{ background:#151b25; border:1px solid #1e2a3a; border-radius:8px; padding:20px; margin-bottom:16px; }}
  .card-title {{ font-size:16px; font-weight:700; margin-bottom:16px; color:#e6e8ec; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ background:#11161e; padding:10px 8px; text-align:left; font-size:11px; color:#5c6678; text-transform:uppercase; letter-spacing:0.5px; }}
  td {{ padding:10px 8px; }}
  tr:hover {{ background:#1a2230; }}
  .footer {{ margin-top:24px; padding:16px 0; border-top:1px solid #1e2a3a; display:flex; justify-content:space-between; font-size:11px; color:#5c6678; font-family:monospace; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>📌 重点基金监控</h1>
      <div class="sub">Key Funds Monitor · 限额变动追踪</div>
    </div>
    <div style="display:flex;gap:12px;align-items:center;">
      <a href="lof_reports_archive.html" class="back-link">📂 历史归档</a>
      <a href="lof_full_report.html" class="back-link">← 返回总报告</a>
    </div>
  </div>

  <div class="card">
    <div class="card-title">📋 重点基金列表（含历史限额记录）</div>
    <table>
      <thead>
        <tr>
          <th>代码</th><th>名称</th><th>当前状态</th><th>申购限额</th><th>分析报告</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
  </div>

  <div class="footer">
    <span>数据源: fundf10.eastmoney.com · 已知限额基金: {len(funds)} 只</span>
    <span>更新时间: {today}</span>
  </div>
</div>
</body>
</html>'''

    output_path = os.path.join(GITHUB_PAGES, 'key_funds.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    size_kb = os.path.getsize(output_path) / 1024
    print(f'  ✅ 重点基金页面已生成: {output_path}')
    print(f'     大小: {size_kb:.1f} KB')
    return True

def build_reports_index():
    """生成报告归档索引页，列出所有带日期的历史报告。"""
    import glob

    # 查找 github-pages/ 目录下所有带日期的报告文件
    pattern = os.path.join(GITHUB_PAGES, 'lof_full_report_*.html')
    files = sorted(glob.glob(pattern), reverse=True)  # 最新的在前

    rows_html = ''
    for fpath in files:
        fname = os.path.basename(fpath)
        # 从文件名提取日期 YYYY-MM-DD
        try:
            date_str = fname.replace('lof_full_report_', '').replace('.html', '')
            parts = date_str.split('-')
            display_date = f'{parts[0]}年{int(parts[1])}月{int(parts[2])}日'
        except Exception:
            date_str = fname
            display_date = date_str

        rows_html += f'''
        <tr style="border-bottom:1px solid #1e2a3a;">
          <td style="padding:10px;color:#e6e8ec;">{display_date}</td>
          <td style="padding:10px;text-align:center;">
            <a href="{fname}" target="_blank" style="color:#ff6b35;text-decoration:none;font-weight:700;">
              📊 查看报告</a>
          </td>
        </tr>'''

    today = time.strftime('%Y-%m-%d %H:%M:%S')
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LOF限额报告归档 · 历史报告索引</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0e14; color:#e6e8ec; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .container {{ max-width:1000px; margin:0 auto; padding:20px; }}
  .header {{ display:flex; justify-content:space-between; align-items:center; padding:20px 0; border-bottom:1px solid #1e2a3a; margin-bottom:20px; }}
  .header h1 {{ font-size:22px; font-weight:700; background:linear-gradient(135deg,#ff6b35,#00e5ff); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
  .header .sub {{ font-size:12px; color:#5c6678; margin-top:4px; font-family:monospace; }}
  .back-link {{ color:#8b95a5; text-decoration:none; font-size:13px; }}
  .back-link:hover {{ color:#ff6b35; }}
  .card {{ background:#151b25; border:1px solid #1e2a3a; border-radius:8px; padding:20px; margin-bottom:16px; }}
  .card-title {{ font-size:16px; font-weight:700; margin-bottom:16px; color:#e6e8ec; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ background:#11161e; padding:10px 8px; text-align:left; font-size:11px; color:#5c6678; text-transform:uppercase; letter-spacing:0.5px; }}
  td {{ padding:10px 8px; }}
  tr:hover {{ background:#1a2230; }}
  .footer {{ margin-top:24px; padding:16px 0; border-top:1px solid #1e2a3a; display:flex; justify-content:space-between; font-size:11px; color:#5c6678; font-family:monospace; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>📊 LOF限额报告归档</h1>
      <div class="sub">LOF Limit Reports Archive · 历史报告索引</div>
    </div>
    <div>
      <a href="lof_full_report.html" class="back-link">📌 最新报告</a>
    </div>
  </div>

  <div class="card">
    <div class="card-title">📋 历史报告列表（共 {len(files)} 份）</div>
    <table>
      <thead>
        <tr>
          <th>报告日期</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
  </div>

  <div class="footer">
    <span>数据源: fundf10.eastmoney.com</span>
    <span>生成时间: {today}</span>
  </div>
</div>
</body>
</html>'''

    output_path = os.path.join(GITHUB_PAGES, 'lof_reports_archive.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  ✅ 报告归档索引已生成: lof_reports_archive.html ({len(files)} 份报告)')

def git_push():
    """提交并推送到 GitHub。"""
    os.chdir(GITHUB_PAGES)

    result = subprocess.run(['git', 'status', '--short'], capture_output=True, text=True)
    if not result.stdout.strip():
        print('  ℹℹ 没有需要提交的变更')
        return True

    print('  Git 状态:')
    print(result.stdout[:500])

    subprocess.run(['git', 'add', '.'], check=False)

    msg = f"Auto update: LOF limit report + key funds - {time.strftime('%Y-%m-%d %H:%M')}"
    subprocess.run(['git', 'commit', '-m', msg], check=False)

    print('  推送到 GitHub...')
    result = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
    if result.returncode == 0:
        print('  ✅ Git 推送成功 → GitHub Pages 自动部署')
        return True
    else:
        print(f'  ⚠️ Git 推送失败: {result.stderr[:200]}')
        return False

def vercel_deploy():
    """部署 github-pages/ 到 Vercel 生产环境（静态文件，无需构建）。"""
    import re
    orig_dir = os.getcwd()
    os.chdir(GITHUB_PAGES)
    try:
        print(f'\n{"="*60}')
        print('▶ Vercel 生产部署')
        print(f'{"="*60}')
        # 查找 npx 路径
        npx = 'npx'
        if os.name == 'nt':
            wb_node = r'C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2\npx.cmd'
            if os.path.exists(wb_node):
                npx = wb_node
        cmd = [npx, 'vercel', '--prod', '--yes']
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180
        )
        output = result.stdout + '\n' + result.stderr
        if 'Ready' in output or 'Aliased' in output or result.returncode == 0:
            match = re.search(r'https://[^\s`]+\.vercel\.app', output)
            url = match.group(0) if match else 'https://lof-fund-arbitrage.vercel.app'
            print('  ✅ Vercel 部署成功')
            print('  生产地址: <ADDRESS_REMOVED>{url}'.format(url=url))
            return True
        else:
            print(f'  ⚠️ Vercel 部署失败 (code={result.returncode})')
            print(f'  {output[-500:]}')
            return False
    except subprocess.TimeoutExpired:
        print('  ⚠️ Vercel 部署超时（>180s），请手动检查')
        return False
    except Exception as e:
        print(f'  ⚠️ Vercel 部署异常: {e}')
        return False
    finally:
        os.chdir(orig_dir)

def main():
    print('=== LOF限额每日采集 - 完整自动化 ===')
    print(f'工作目录: {WORKSPACE}')
    print(f'开始时间: {time.strftime("%Y-%m-%d %H:%M:%S")}')

    # Step 1: 运行 daily_limit_tracker_v2.py（采集390只基金数据）
    success = run_script(os.path.join(SCRIPTS_DIR, 'daily_limit_tracker_v2.py'))
    if not success:
        print('⚠️ daily_limit_tracker_v2.py 运行失败，继续...')

    # Step 2: 生成主报告（lof_full_report.html）
    success = run_script(os.path.join(SCRIPTS_DIR, 'build_tech_report.py'))
    if not success:
        print('⚠️ build_tech_report.py 运行失败，继续...')

    # 复制到 github-pages/
    copy_to_github_pages()

    # Step 3: 生成重点基金独立报告（build_reports.py --known）
    print(f'\n{"="*60}')
    print('▶ 生成重点基金独立报告')
    print(f'{"="*60}')
    success = run_script(os.path.join(SCRIPTS_DIR, 'build_reports.py'), ['--known'])
    if not success:
        print('⚠️ build_reports.py 运行失败，继续...')

    # 再次复制（独立报告）
    copy_to_github_pages()

    # Step 4: 生成重点基金汇总页面（key_funds.html）
    print(f'\n{"="*60}')
    print('▶ 生成重点基金汇总页面')
    print(f'{"="*60}')
    build_key_funds_index()

    # Step 5: Git 提交与推送
    print(f'\n{"="*60}')
    print('▶ Git 提交与推送（触发 GitHub Pages 自动部署）')
    print(f'{"="*60}')
    git_push()

    # Step 6: Vercel 生产部署
    vercel_deploy()

    print(f'\n=== 全部完成 ===')
    print(f'结束时间: {time.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'GitHub Pages: https://tonypeng0824.github.io/arbitrage-tracker/lof_full_report.html')
    print(f'Vercel:      https://lof-fund-arbitrage.vercel.app/lof_full_report.html')

if __name__ == '__main__':
    main()
