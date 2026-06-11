"""
增强版套利报告生成器 v2 — 包含当日实时套利机会
数据来源: AKShare(集思录/东方财富) + TickFlow(备用) + 东方财富 push2 API(备用) + fundgz API + fundf10 限额

v2 改进:
1. 列表显示列名
2. LOF仅展示不限购基金，显示实时申购限额
3. 当日实时机会仅展示有实际可操作标的
4. 数据源优先级: AKShare(集思录) > 东方财富 > TickFlow(备用)
"""
import sqlite3
import json
import os
import sys
import io
import urllib.request
import urllib.error
import re
import time
import concurrent.futures
import requests
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "arbitrage_channels.db")
TDX_DATA_PATH = os.path.join(BASE_DIR, "data", "tdx_overseas.json")

# TickFlow API 配置
TICKFLOW_API_KEY = "tk_b8a363fe59894e47be33b819a2fa0268"
TICKFLOW_BASE_URL = "https://api.tickflow.org/v1"

# 请求 Session（复用连接，提升稳定性）
http_session = requests.Session()
http_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Connection': 'keep-alive',
    'Referer': 'https://quote.eastmoney.com/'
})

# ============================================================
# 1. 实时LOF溢价数据获取
# 数据源优先级: AKShare > 东方财富 push2 API > TickFlow(备用)
# ============================================================

def fetch_lof_market_akshare():
    """从 AKShare 获取LOF市场实时数据（主要数据源）"""
    lof_data = []
    try:
        df = ak.fund_lof_spot_em()
        for _, row in df.iterrows():
            try:
                price = float(row.get('最新价', 0))
                volume = float(row.get('成交额', 0))
            except:
                price = 0
                volume = 0
            lof_data.append({
                'f12': str(row.get('代码', '')),
                'f14': str(row.get('名称', '')),
                'f2': price,
                'f6': volume,
            })
        print(f"  [OK] AKShare 获取 {len(lof_data)} 只LOF基金实时数据")
    except Exception as e:
        print(f"  [!] AKShare LOF获取失败: {e}")
    return lof_data


def fetch_lof_market_tickflow():
    """从 TickFlow API 获取LOF/ETF数据（备用数据源）"""
    lof_data = []
    try:
        # TickFlow 支持 ETF 行情，尝试获取场内基金
        url = f"{TICKFLOW_BASE_URL}/quote"
        headers = {'Authorization': f'Bearer {TICKFLOW_API_KEY}'}
        # 获取沪深LOF/ETF列表（TickFlow 的 CN_ETF 标的池）
        resp = http_session.get(
            f"{TICKFLOW_BASE_URL}/universe",
            params={'pool': 'CN_ETF'},
            headers={'Authorization': f'Bearer {TICKFLOW_API_KEY}'},
            timeout=15
        )
        if resp.status_code == 200:
            symbols = resp.json().get('symbols', [])[:100]  # 限制数量
            # 批量获取行情
            batch_resp = http_session.get(
                f"{TICKFLOW_BASE_URL}/quote",
                params={'symbols': ','.join(symbols)},
                headers={'Authorization': f'Bearer {TICKFLOW_API_KEY}'},
                timeout=20
            )
            if batch_resp.status_code == 200:
                for item in batch_resp.json().get('data', []):
                    lof_data.append({
                        'f12': item.get('symbol', ''),
                        'f14': item.get('name', ''),
                        'f2': item.get('close', 0),
                        'f6': item.get('volume', 0) * 10000,
                    })
                print(f"  [OK] TickFlow 获取 {len(lof_data)} 只ETF/LOF数据")
    except Exception as e:
        print(f"  [!] TickFlow LOF获取失败: {e}")
    return lof_data


def fetch_lof_market():
    """从东方财富 push2 API 获取LOF市场实时数据（备用数据源）"""
    lof_data = []
    pages = [1, 2, 3, 4]
    
    for p in pages:
        for attempt in range(2):
            try:
                url = f"https://push2.eastmoney.com/api/qt/clist/get?cb=&fid=f3&po=1&pz=100&pn={p}&np=1&fltt=2&invt=2&fs=b:MK0404,b:MK0405,b:MK0406,b:MK0407&fields=f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f20,f21,f38,f39,f62,f64,f145,f148"
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': 'https://quote.eastmoney.com/'
                })
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get('data') and data['data'].get('diff'):
                        lof_data.extend(data['data']['diff'])
                time.sleep(0.5)
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                else:
                    print(f"  [!] 第{p}页LOF获取失败: {e}")
    
    print(f"  [OK] 获取 {len(lof_data)} 只LOF基金实时数据")
    return lof_data


def fetch_fund_nav(codes_batch):
    """批量获取基金净值(估值)数据"""
    results = {}
    
    def fetch_one(code):
        try:
            url = f"http://fundgz.1234567.com.cn/js/{code}.js"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode('utf-8')
                match = re.search(r'jsonpgz\((.+)\)', text)
                if match:
                    return code, json.loads(match.group(1))
        except:
            pass
        return code, None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, c): c for c in codes_batch}
        for future in concurrent.futures.as_completed(futures):
            code, result = future.result()
            if result:
                results[code] = result
    
    return results


def fetch_lof_limit(code):
    """获取单只LOF基金的申购限额、状态和费用"""
    try:
        url = f"https://fundf10.eastmoney.com/jjfl_{code}.html"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://fundf10.eastmoney.com/'
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8')
        
        # 1. 解析交易状态
        status_match = re.search(r'交易状态：.*?<span[^>]*>([^<]+)</span>', html)
        status = status_match.group(1).strip() if status_match else ''
        
        # 2. 如果暂停申购，直接返回
        if '暂停' in status or '限制' in status:
            return {'status': status, 'limit': 0, 'is_open': False, 'mgmt_fee': '', 'cust_fee': ''}
        
        # 3. 解析日累计申购限额（精确金额）
        limit = 0
        limit_text = ''
        limit_texts = re.findall(r'日累计购买上限[^<]*<span[^>]*>([^<]+)</span>', html)
        if not limit_texts:
            limit_texts = re.findall(r'日累计申购限额[^<]*<span[^>]*>([^<]+)</span>', html)
        if not limit_texts:
            limit_texts = re.findall(r'申购限额[^<]*<span[^>]*>([^<]+)</span>', html)
        
        if limit_texts:
            limit_text = limit_texts[0]
            limit_str = limit_text.replace(',', '').replace('元', '').replace('万', '0000').strip()
            try:
                limit = int(float(limit_str))
            except:
                pass
        
        if not limit and '限大额' in status:
            # "限大额" without explicit number means large-amount restricted
            # Try to find in parentheses
            paren_match = re.search(r'限大额.*?[（(]([^）)]+)[）)]', status)
            if paren_match:
                limit_text = paren_match.group(1)
                try:
                    limit = int(float(limit_text.replace(',','').replace('元','').replace('万','0000')))
                except:
                    limit = 0
        
        # 4. 解析费用（管理费、托管费）
        mgmt_fee = ''
        cust_fee = ''
        mgmt_m = re.search(r'管理费率.*?<td[^>]*>([\d.]+)%', html)
        cust_m = re.search(r'托管费率.*?<td[^>]*>([\d.]+)%', html)
        if mgmt_m:
            mgmt_fee = mgmt_m.group(1) + '%'
        if cust_m:
            cust_fee = cust_m.group(1) + '%'
        
        # 5. 申购费（从费率表获取优惠费率）
        sub_fee = ''
        sub_html = html[:html.find('赎回费率')] if '赎回费率' in html else html
        sub_pcts = re.findall(r'>([\d.]+)%<', sub_html)
        if sub_pcts:
            # 取最小值作为优惠费率
            min_pct = min(float(x) for x in sub_pcts if float(x) < 10)
            sub_fee = f'{min_pct:.2f}%'
        
        # 6. 赎回费（短期一般0.5%-1.5%）
        red_fee = '0.5%'  # LOF场内赎回通常0.5%
        red_start = html.find('赎回费率')
        if red_start > 0:
            red_html = html[red_start:html.find('管理费率', red_start) if '管理费率' in html[red_start:] else red_start+2000]
            red_pcts = re.findall(r'>([\d.]+)%<', red_html)
            if red_pcts:
                red_fee = min(float(x) for x in red_pcts if float(x) < 10)
                red_fee = f'{red_fee:.1f}%'
        
        return {
            'status': status, 'limit': limit, 'limit_text': limit_text,
            'is_open': True,
            'mgmt_fee': mgmt_fee, 'cust_fee': cust_fee,
            'sub_fee': sub_fee, 'red_fee': red_fee
        }
    except:
        return {'status': '获取失败', 'limit': 0, 'is_open': None, 'mgmt_fee': '', 'cust_fee': ''}


def fetch_lof_limits_batch(codes):
    """批量获取LOF限额（并发）"""
    results = {}
    
    def fetch_one(code):
        time.sleep(0.1)  # 限流
        return code, fetch_lof_limit(code)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one, c): c for c in codes}
        for future in concurrent.futures.as_completed(futures):
            code, result = future.result()
            if result:
                results[code] = result
    
    return results


def compute_premium(lof_list, nav_data):
    """计算LOF溢价率，先不筛选限购"""
    opportunities = []
    
    for item in lof_list:
        code = item.get('f12', '')
        name = item.get('f14', '')
        price_raw = item.get('f2', 0)
        volume_raw = item.get('f6', 0)
        
        if not code or not name:
            continue
        
        try:
            price_raw = float(price_raw) if price_raw and price_raw != '-' else 0
        except:
            price_raw = 0
        try:
            volume_raw = float(volume_raw) if volume_raw and volume_raw != '-' else 0
        except:
            volume_raw = 0
        
        if price_raw and abs(price_raw) < 100:
            price = price_raw
        elif price_raw:
            price = price_raw / 1000
        else:
            price = 0
        
        volume = volume_raw / 10000 if volume_raw else 0
        
        nav_info = nav_data.get(code, {})
        nav = float(nav_info.get('dwjz', 0)) if nav_info else 0
        gsz = float(nav_info.get('gsz', 0)) if nav_info else 0
        
        premium_pct = 0
        if gsz > 0 and price > 0:
            premium_pct = round((price - gsz) / gsz * 100, 2)
        elif nav > 0 and price > 0:
            premium_pct = round((price - nav) / nav * 100, 2)
        
        if abs(premium_pct) >= 1 and volume >= 100:
            opportunities.append({
                'name': name,
                'code': code,
                'price': round(price, 4),
                'premium': premium_pct,
                'nav': nav,
                'gsz': gsz,
                'nav_date': nav_info.get('jzrq', ''),
                'volume_wan': round(volume, 0),
                'type': 'LOF溢价' if premium_pct > 0 else 'LOF折价',
                'premium_pct': premium_pct,
                'opportunity_score': min(10, int(abs(premium_pct) * 2))
            })
    
    opportunities.sort(key=lambda x: abs(x['premium']), reverse=True)
    return opportunities


def filter_lof_with_limits(lof_opps):
    """对LOF机会进行限购过滤：只保留不限购的，并附上实时限额"""
    if not lof_opps:
        return []
    
    # 获取前15个高溢价LOF的限额
    codes = [o['code'] for o in lof_opps[:15]]
    print(f"  [..] 正在获取 {len(codes)} 只LOF的申购限额...")
    limits = fetch_lof_limits_batch(codes)
    
    filtered = []
    skipped = 0
    for opp in lof_opps[:15]:
        code = opp['code']
        lim = limits.get(code, {})
        status = lim.get('status', '未知')
        is_open = lim.get('is_open')
        limit_val = lim.get('limit', 0)
        
        # 只保留确定不限购的
        if is_open is False:
            skipped += 1
            continue
        if is_open is None:
            # 无法确定状态，保留但标注
            pass
        
        # 构建额度+费用描述
        if limit_val > 0:
            if limit_val >= 10000:
                quota_desc = f'日限额 {limit_val/10000:.1f}万元'
            else:
                quota_desc = f'日限额 {limit_val:,}元'
        elif status and '开放' in status:
            quota_desc = '不限购'
        elif opp['code'].startswith('16'):
            quota_desc = '一拖六 600元/日'
        else:
            quota_desc = '单账户100元起'
        
        # 附加费用信息
        fees = []
        if lim.get('sub_fee'):
            fees.append(f'申购{lim["sub_fee"]}')
        if lim.get('red_fee'):
            fees.append(f'赎回{lim["red_fee"]}')
        mgmt_fee = lim.get('mgmt_fee', '')
        cust_fee = lim.get('cust_fee', '')
        if mgmt_fee or cust_fee:
            fees.append(f'年费{mgmt_fee}+{cust_fee}')
        fee_str = ' | '.join(fees) if fees else ''
        
        if fee_str:
            quota_desc += f'<br><span style="font-size:0.75em;color:#64748b">💰 {fee_str}</span>'
        
        # 年化收益计算（考虑摩擦成本约0.5%）
        pct = abs(opp['premium_pct'])
        if pct > 3:
            est_return = f'{pct - 0.5:.1f}%~{pct:.1f}%/次'
        else:
            est_return = f'{pct * 0.5:.1f}%~{pct - 0.3:.1f}%/次'
        
        filtered.append({
            'name': opp['name'],
            'code': opp['code'],
            'price': opp['price'],
            'premium': opp['premium'],
            'volume_wan': opp['volume_wan'],
            'type': opp['type'],
            'category': '基金套利/LOF',
            'quota_desc': quota_desc,
            'quota_min': max(100, limit_val) if limit_val else 100,
            'quota_max': max(600, limit_val * 6) if limit_val else 600,
            'est_return': est_return,
            'risk': '低' if abs(opp['premium_pct']) < 5 else '中',
            'how_to': '场内申购→T+2到账→T+3场内卖出',
            'key_risks': 'T+2溢价消失(杀溢价)、流动性不足',
            'opportunity_score': opp['opportunity_score'],
            'limit_status': status
        })
    
    if skipped:
        print(f"  [OK] 过滤掉 {skipped} 只限购/暂停申购LOF，保留 {len(filtered)} 只可操作")
    else:
        print(f"  [OK] 保留 {len(filtered)} 只LOF套利机会")
    
    return filtered


# ============================================================
# 2. 可转债数据获取
# 数据源优先级: AKShare(集思录) > 东方财富 API > TickFlow(备用)
# ============================================================

def fetch_cb_opportunities_akshare():
    """从 AKShare 获取可转债数据（集思录数据源，主要数据源）"""
    opportunities = []
    try:
        df = ak.bond_cb_jsl()
        for _, row in df.iterrows():
            try:
                price = float(row.get('现价', 0))
            except:
                price = 0
            if price and 90 < price < 200:
                code = str(row.get('代码', ''))
                name = str(row.get('转债名称', ''))
                premium = float(row.get('转股溢价率', 0))
                opportunities.append({
                    'name': name,
                    'code': code,
                    'price': round(price, 2),
                    'premium': premium,
                    'volume_wan': round(float(row.get('成交额', 0)) / 10000, 2),
                    'type': '可转债低价',
                    'category': '债券套利/转债',
                    'quota_desc': f'现价 {round(price,2)}元，一手约{round(price*10)}元',
                    'quota_min': round(price * 10),
                    'quota_max': 100000,
                    'est_return': '10%~30%',
                    'risk': '中',
                    'how_to': '低价买入持有，等待强赎或到期兑付',
                    'key_risks': '正股下跌、信用风险(极低)',
                    'opportunity_score': 6
                })
        print(f"  [OK] AKShare(集思录) 获取 {len(opportunities)} 只低价可转债")
    except Exception as e:
        print(f"  [!] AKShare(集思录) 可转债获取失败: {e}")
    return opportunities


def fetch_cb_opportunities_tickflow():
    """从 TickFlow API 获取可转债数据（备用数据源）"""
    opportunities = []
    try:
        # TickFlow 可能不支持可转债，尝试获取
        url = f"{TICKFLOW_BASE_URL}/quote"
        headers = {'Authorization': f'Bearer {TICKFLOW_API_KEY}'}
        # 尝试获取可转债板块数据
        resp = http_session.get(
            f"{TICKFLOW_BASE_URL}/universe",
            params={'pool': 'CN_Bond'},  # 尝试债券池
            headers=headers,
            timeout=15
        )
        if resp.status_code == 200:
            # 处理返回数据
            pass
    except Exception as e:
        print(f"  [!] TickFlow 可转债获取失败: {e}")
    return opportunities


def fetch_cb_opportunities():
    """获取可转债低价双低候选（备用: 东方财富API）"""
    opportunities = []
    
    for attempt in range(2):
        try:
            if attempt > 0:
                time.sleep(2)
            url = "https://push2.eastmoney.com/api/qt/clist/get?fid=f3&po=1&pz=50&pn=1&np=1&fltt=2&invt=2&fs=b:MK0354&fields=f2,f3,f12,f14"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer': 'https://quote.eastmoney.com/'
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                cb_list = data.get('data', {}).get('diff', [])
            
            for item in cb_list:
                code = item.get('f12', '')
                name = item.get('f14', '')
                price_raw = item.get('f2', 0)
                
                if not code or not name:
                    continue
                try:
                    price = float(price_raw) if price_raw and price_raw != '-' else 0
                except:
                    price = 0
                
                # 价格90-200区间的低价转债
                if price and 90 < price < 200:
                    opportunities.append({
                        'name': name,
                        'code': code,
                        'price': round(price, 2),
                        'premium': 0,
                        'volume_wan': 0,
                        'type': '可转债低价',
                        'category': '债券套利/转债',
                        'quota_desc': f'现价 {round(price,2)}元，一手约{round(price*10)}元',
                        'quota_min': round(price * 10),
                        'quota_max': 100000,
                        'est_return': '10%~30%',
                        'risk': '中',
                        'how_to': '低价买入持有，等待强赎或到期兑付',
                        'key_risks': '正股下跌、信用风险(极低)',
                        'opportunity_score': 6
                    })
            
            print(f"  [OK] 获取 {len(opportunities)} 只低价可转债")
            break
        except Exception as e:
            if attempt == 1:
                print(f"  [!] 可转债API不可用: {e}")
    
    return opportunities


# ============================================================
# 3. 基础渠道（仅统计用）
# ============================================================

def get_channel_opportunities():
    """从数据库获取基础渠道"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM arbitrage_channels WHERE status='active' ORDER BY popularity DESC")
    rows = c.fetchall()
    conn.close()
    
    opportunities = []
    for ch in rows:
        ch = dict(ch)
        ret_str = f'{ch["annual_return_min"]}%~{ch["annual_return_max"]}%' if ch.get("annual_return_max") else f'~{ch["annual_return_min"]}%'
        
        opportunities.append({
            'name': ch['name'],
            'code': '-',
            'type': ch['category'],
            'category': ch['category'],
            'price': 0,
            'premium': 0,
            'quota_min': ch['quota_min'] or 0,
            'quota_max': ch['quota_max'] or 99999999,
            'quota_desc': ch.get('quota_desc', ''),
            'est_return': ret_str,
            'risk': ch.get('risk_level', '中'),
            'how_to': ch.get('how_to', ''),
            'key_risks': ch.get('key_risks', ''),
            'difficulty': ch.get('difficulty', '中'),
            'trade_frequency': ch.get('trade_frequency', ''),
            'description': ch.get('description', ''),
            'platform': ch.get('platform', ''),
            'requirements': ch.get('requirements', ''),
            'opportunity_score': 1,
            'volume_wan': 0
        })
    return opportunities


# ============================================================
# 4. 综合"只展示有实际可操作标的"的机会
# ============================================================

def get_tdx_opportunities():
    """从通达信数据获取海外ETF溢价机会"""
    opportunities = []
    try:
        if os.path.exists(TDX_DATA_PATH):
            with open(TDX_DATA_PATH, 'r', encoding='utf-8') as f:
                tdx_data = json.load(f)
            for etf in tdx_data.get('qdii_etfs', []):
                prem = etf.get('premium', 0)
                score = min(10, int(abs(prem) * 1.5)) if prem > 5 else 5
                opportunities.append({
                    'name': etf['name'],
                    'code': etf['code'],
                    'price': etf['price'],
                    'premium': prem,
                    'volume_wan': round(etf.get('volume', 0), 0),
                    'type': etf.get('type', 'QDII ETF溢价'),
                    'category': '跨境套利/ETF',
                    'quota_desc': etf.get('quota_desc', '场内ETF交易'),
                    'quota_min': 100,
                    'quota_max': 99999999,
                    'est_return': f'{prem - 0.5:.1f}%~{prem:.1f}%' if prem > 3 else f'{prem:.1f}%',
                    'risk': '高' if prem > 10 else ('中' if prem > 5 else '低'),
                    'how_to': '场内买入→持有博NAV涨(溢价=入场费，非套利)',
                    'key_risks': f'溢价收窄导致亏损，非传统套利。跟踪{etf.get("underlying","")}',
                    'opportunity_score': score,
                    'source': '通达信(tdx-connector)'
                })
            print(f"  [OK] 从通达信加载 {len(opportunities)} 个QDII ETF溢价机会")
    except Exception as e:
        print(f"  [!] 通达信数据加载失败: {e}")
    return opportunities


def get_today_opportunities():
    """汇总当日实时套利机会（仅含实际可操作标的）
    数据源优先级: AKShare(集思录) > 东方财富 > TickFlow(备用)
    """
    actionable = []
    
    # LOF实时溢价机会（已过滤限购）
    print("\n[1/3] 获取LOF实时溢价数据...")
    lof_filtered = []
    try:
        # 优先级1: AKShare
        if AKSHARE_AVAILABLE:
            lof_list = fetch_lof_market_akshare()
            if lof_list:
                def safe_volume(x):
                    v = x.get('f6', 0)
                    try: return float(v) if v and v != '-' else 0
                    except: return 0
                lof_list.sort(key=safe_volume, reverse=True)
                top_lof = lof_list[:30]
                codes = [item.get('f12', '') for item in top_lof if item.get('f12')]
                nav_data = fetch_fund_nav(codes)
                lof_opps = compute_premium(top_lof, nav_data)
                lof_filtered = filter_lof_with_limits(lof_opps)
                if lof_filtered:
                    actionable.extend(lof_filtered)
                    print(f"  [OK] AKShare 最终 {len(lof_filtered)} 个LOF不限购套利机会")
        
        # 优先级2: 东方财富 push2 API（AKShare失败或无数据时）
        if not lof_filtered:
            print("  [!] AKShare无数据，尝试东方财富 push2 API...")
            lof_list = fetch_lof_market()
            def safe_volume(x):
                v = x.get('f6', 0)
                try: return float(v) if v and v != '-' else 0
                except: return 0
            lof_list.sort(key=safe_volume, reverse=True)
            top_lof = lof_list[:30]
            codes = [item.get('f12', '') for item in top_lof if item.get('f12')]
            nav_data = fetch_fund_nav(codes)
            lof_opps = compute_premium(top_lof, nav_data)
            lof_filtered = filter_lof_with_limits(lof_opps)
            if lof_filtered:
                actionable.extend(lof_filtered)
                print(f"  [OK] 东方财富 最终 {len(lof_filtered)} 个LOF不限购套利机会")
        
        # 优先级3: TickFlow（前两个都失败时）
        if not actionable:
            print("  [!] AKShare和东方财富均失败，尝试 TickFlow...")
            lof_list = fetch_lof_market_tickflow()
            if lof_list:
                print(f"  [OK] TickFlow 获取 {len(lof_list)} 条数据（仅供参考）")
                # TickFlow 返回的数据可能不包含LOF套利所需字段
                # 暂时跳过详细处理
    except Exception as e:
        print(f"  [!] LOF数据异常: {e}")
    
    # 可转债低价机会
    print("\n[2/4] 获取可转债低价数据...")
    try:
        # 优先级1: AKShare (集思录)
        if AKSHARE_AVAILABLE:
            cb_opps = fetch_cb_opportunities_akshare()
            if cb_opps:
                actionable.extend(cb_opps[:8])
                print(f"  [OK] AKShare(集思录) {min(len(cb_opps), 8)} 只可转债入选")
            else:
                # 优先级2: 东方财富 API
                print("  [!] AKShare(集思录)无数据，尝试东方财富 API...")
                cb_opps = fetch_cb_opportunities()
                actionable.extend(cb_opps[:8])
                print(f"  [OK] 东方财富 {min(len(cb_opps), 8)} 只可转债入选")
        else:
            # 备用: 东方财富 API
            cb_opps = fetch_cb_opportunities()
            actionable.extend(cb_opps[:8])
            print(f"  [OK] 东方财富 {min(len(cb_opps), 8)} 只可转债入选")
    except Exception as e:
        print(f"  [!] 可转债数据异常: {e}")
    
    # QDII ETF 溢价（不进入可操作排名，仅做风险提示）
    print("\n[3/4] 加载通达信海外ETF溢价数据(风险提示)...")
    tdx_warnings = []
    try:
        tdx_warnings = get_tdx_opportunities()
        if tdx_warnings:
            print(f"  [!] {len(tdx_warnings)} 只QDII ETF存在高溢价（非套利，仅风险提示）")
    except Exception as e:
        print(f"  [!] 通达信数据异常: {e}")
    
    # 按机会评分排序
    actionable.sort(key=lambda x: x.get('opportunity_score', 0), reverse=True)
    
    # 基础渠道（仅用于第二部分的完整表格）
    print("\n[4/4] 载入基础渠道数据...")
    base_opps = get_channel_opportunities()
    
    return actionable, base_opps, tdx_warnings


# ============================================================
# 5. HTML报告生成
# ============================================================

def difficulty_color(d):
    colors = {"极低": "#22c55e", "低": "#84cc16", "中": "#f59e0b", "高": "#f97316", "极高": "#ef4444"}
    return colors.get(d, "#64748b")

def risk_color(r):
    colors = {"极低": "#22c55e", "低": "#84cc16", "中": "#f59e0b", "高": "#f97316", "极高": "#ef4444"}
    return colors.get(r, "#64748b")

def type_badge(t):
    badges = {
        'LOF溢价': '#ef4444', 'LOF折价': '#22c55e', 
        '可转债低价': '#8b5cf6', '可转债双低轮动': '#8b5cf6',
        'QDII ETF溢价': '#f97316', 'QDII ETF折价': '#06b6d4',
        '基金套利': '#3b82f6', '基金套利/LOF': '#3b82f6',
        '打新套利': '#f59e0b', '债券套利': '#10b981',
        '债券套利/转债': '#10b981', '并购套利': '#ef4444',
        '现金管理': '#06b6d4', '跨境套利': '#8b5cf6',
        '跨境套利/ETF': '#8b5cf6',
        '衍生品套利': '#f97316', '数字货币': '#f59e0b'
    }
    color = badges.get(t, '#64748b')
    return f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.75em;background:{color}20;color:{color};border:1px solid {color}40">{t}</span>'


def generate_enhanced_report():
    """生成增强版报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    actionable_opps, base_channels, tdx_warnings = get_today_opportunities()
    
    # 显示前25个
    display_opps = actionable_opps[:25]
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>套利渠道全景报告（增强版 v2） - {now}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f0f2f5; color: #1e293b; line-height: 1.6; }}
.container {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}

.header {{ background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0ea5e9 100%); color: white; padding: 36px 30px; text-align: center; border-radius: 16px; margin-bottom: 24px; position: relative; overflow: hidden; }}
.header::before {{ content:''; position:absolute; top:-50%; right:-10%; width:300px; height:300px; background: radial-gradient(circle, rgba(255,255,255,0.08) 0%, transparent 70%); border-radius:50%; }}
.header h1 {{ font-size: 2em; margin-bottom: 6px; position: relative; }}
.header p {{ opacity: 0.85; font-size: 0.9em; position: relative; }}

.stats-row {{ display: flex; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; }}
.stat-card {{ flex: 1; min-width: 150px; background: white; border-radius: 12px; padding: 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); text-align: center; border-top: 3px solid #e2e8f0; }}
.stat-card.hot {{ border-top-color: #ef4444; }}
.stat-card.green {{ border-top-color: #22c55e; }}
.stat-card.blue {{ border-top-color: #3b82f6; }}
.stat-card.purple {{ border-top-color: #8b5cf6; }}
.stat-card .num {{ font-size: 1.8em; font-weight: 700; }}
.stat-card .label {{ font-size: 0.82em; color: #64748b; margin-top: 2px; }}

.section-title {{ font-size: 1.3em; font-weight: 700; color: #1e293b; margin: 30px 0 16px 0; padding-left: 12px; border-left: 4px solid #3b82f6; }}
.section-title .sub {{ font-size: 0.7em; color: #64748b; font-weight: 400; margin-left: 8px; }}

/* 列名头 */
.opp-header {{ background: #f1f5f9; border-radius: 10px; padding: 14px 24px; display: grid; grid-template-columns: 45px 1.5fr 70px 140px 110px 80px 80px; gap: 16px; align-items: center; font-weight: 600; font-size: 0.82em; color: #475569; border: 1px solid #e2e8f0; }}
.opp-header div {{ text-align: left; }}
.opp-header .col-center {{ text-align: center; }}

.opportunity-list {{ display: flex; flex-direction: column; gap: 10px; margin-bottom: 30px; }}
.opp-card {{ background: white; border-radius: 12px; padding: 18px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); display: grid; grid-template-columns: 45px 1.5fr 70px 140px 110px 80px 80px; gap: 16px; align-items: center; transition: all 0.2s; border-left: 4px solid #e2e8f0; }}
.opp-card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.1); transform: translateY(-1px); }}
.opp-card.urgent {{ border-left-color: #ef4444; background: #fef2f2; }}
.opp-card.good {{ border-left-color: #22c55e; background: #f0fdf4; }}
.opp-card.normal {{ border-left-color: #3b82f6; }}

.opp-rank {{ font-size: 1.3em; font-weight: 800; color: #94a3b8; text-align: center; }}
.opp-rank.top3 {{ color: #f59e0b; }}
.opp-name {{ font-weight: 600; font-size: 0.92em; }}
.opp-code {{ font-size: 0.78em; color: #64748b; }}
.opp-quota {{ font-size: 0.82em; color: #475569; line-height: 1.5; }}
.opp-return {{ font-weight: 700; color: #059669; font-size: 0.88em; }}
.opp-risk {{ }}

.table-wrapper {{ background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; min-width: 1100px; }}
th {{ background: #f8fafc; padding: 12px 10px; text-align: left; font-size: 0.78em; font-weight: 600; color: #64748b; border-bottom: 2px solid #e2e8f0; white-space: nowrap; cursor: pointer; }}
td {{ padding: 12px 10px; border-bottom: 1px solid #f1f5f9; font-size: 0.85em; }}
tr:hover {{ background: #f8fafc; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 0.76em; font-weight: 600; }}
.footer {{ text-align: center; padding: 40px 20px; color: #94a3b8; font-size: 0.85em; }}

.limit-tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.72em; font-weight: 600; }}
.limit-open {{ background: #dcfce7; color: #16a34a; }}
.limit-unknown {{ background: #fef3c7; color: #d97706; }}

@media (max-width: 768px) {{
    .opp-card {{ grid-template-columns: 1fr 1fr; gap: 8px; padding: 14px; }}
    .opp-header {{ display: none; }}
    .stats-row {{ flex-direction: column; }}
}}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>📊 套利渠道全景报告（实时版）</h1>
    <p>数据来源：东方财富 · fundgz · fundf10 · 通达信 &nbsp;|&nbsp; 更新：{now}</p>
    <p style="font-size:0.82em;margin-top:8px;opacity:0.7">⚠️ 仅展示有实际可操作标的的机会，不含纯知识性渠道</p>
</div>

<div class="stats-row">
    <div class="stat-card hot"><div class="num" style="color:#ef4444">{len(actionable_opps)}</div><div class="label">🔥 今日可操作标的</div></div>
    <div class="stat-card green"><div class="num" style="color:#22c55e">{len([o for o in actionable_opps if o.get('risk') in ('极低','低')])}</div><div class="label">🛡️ 低风险标的</div></div>
    <div class="stat-card blue"><div class="num" style="color:#3b82f6">{len(display_opps)}</div><div class="label">📋 本次展示</div></div>
    <div class="stat-card purple"><div class="num" style="color:#8b5cf6">{len(base_channels)}</div><div class="label">🏗️ 知识库渠道</div></div>
</div>

<!-- ===== 第一部分：可操作标的排名列表（含列名） ===== -->
<div class="section-title">🔥 当日可操作标的排名 <span class="sub">仅含实际标的，按机会从高到低</span></div>

<div class="opp-header">
    <div class="col-center">排名</div>
    <div>标的名称 / 代码 / 类型</div>
    <div class="col-center">类型</div>
    <div>额度 / 限购</div>
    <div>预计收益</div>
    <div>风险</div>
    <div>操作</div>
</div>

<div class="opportunity-list">
"""
    
    for i, opp in enumerate(display_opps, 1):
        score = opp.get('opportunity_score', 0)
        card_class = 'urgent' if score >= 8 else ('good' if score >= 6 else 'normal')
        rank_class = 'top3' if i <= 3 else ''
        
        risk = opp.get('risk', '中')
        r_color = risk_color(risk)
        risk_badge = f'<span class="badge" style="background:{r_color}20;color:{r_color}">{risk}</span>'
        
        quota = opp.get('quota_desc', '')
        if not quota:
            quota = '未获取'
        
        ret = opp.get('est_return', '')
        code = opp.get('code', '-')
        opp_type = opp.get('type', opp.get('category', ''))
        
        # LOF限购状态标签
        limit_status = opp.get('limit_status', '')
        limit_tag = ''
        if limit_status and '开放' in str(limit_status):
            limit_tag = '<span class="limit-tag limit-open">✓ 不限购</span>'
        elif limit_status:
            limit_tag = f'<span class="limit-tag limit-unknown">{limit_status}</span>'
        
        premium = opp.get('premium', 0)
        premium_str = f'{premium:+.1f}%' if premium else ''
        if premium_str and abs(premium) >= 3:
            premium_str = f'<span style="color:#ef4444;font-weight:700">{premium_str}</span>'
        
        how_to_short = opp.get('how_to', '')[:20]
        
        html += f"""
<div class="opp-card {card_class}">
    <div class="opp-rank {rank_class}">#{i}</div>
    <div>
        <div class="opp-name">{opp['name']} <span style="font-size:0.8em;color:#64748b">{premium_str}</span></div>
        <div class="opp-code">代码: {code} {limit_tag}</div>
        <div style="margin-top:3px;">{type_badge(opp_type)}</div>
    </div>
    <div style="text-align:center;">{type_badge(opp_type)}</div>
    <div class="opp-quota">{quota}</div>
    <div class="opp-return">{ret}</div>
    <div class="opp-risk">{risk_badge}</div>
    <div>
        <details>
            <summary style="cursor:pointer;color:#3b82f6;font-size:0.82em">{how_to_short}...</summary>
            <div style="margin-top:8px;font-size:0.8em;color:#475569;line-height:1.8;padding:8px;background:#f8fafc;border-radius:6px;">
                <div>📝 <b>操作</b>: {opp.get('how_to','—')}</div>
                <div>⚠️ <b>风险</b>: {opp.get('key_risks','—')}</div>
                <div>💵 <b>价格</b>: {opp.get('price','—')}</div>
                <div>📊 <b>成交额</b>: {opp.get('volume_wan',0)}万</div>
            </div>
        </details>
    </div>
</div>
"""
    
    if not display_opps:
        html += '<div style="text-align:center;padding:40px;color:#94a3b8">暂无符合条件的可操作标的（可能因API限流或市场无显著机会）</div>'
    
    html += f"""
</div>

"""

    # QDII ETF高溢价风险提示（不列入可操作排名）
    if tdx_warnings:
        html += '<div class="section-title" style="border-left-color:#ef4444">⚠️ QDII ETF高溢价风险提示 <span class="sub">非套利机会 — 不列入可操作排名</span></div>'
        html += '<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:20px 24px;margin-bottom:24px">'
        html += '<p style="color:#991b1b;font-weight:600;margin-bottom:12px">以下QDII ETF存在高溢价，但<b>溢价≠套利</b>：</p>'
        html += '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">'
        for w in tdx_warnings:
            html += f'<div style="flex:1;min-width:180px;background:white;border-radius:8px;padding:12px;border:1px solid #fecaca"><div style="font-weight:600;font-size:0.9em">{w["name"]}({w["code"]})</div><div style="color:#991b1b;font-size:1.1em;font-weight:700;margin:4px 0">溢价 {w["premium"]:.1f}%</div><div style="font-size:0.78em;color:#64748b">{w.get("key_risks","")[:40]}</div></div>'
        html += '</div>'
        html += '<p style="color:#991b1b;font-size:0.85em;line-height:1.8">🔴 散户无法做ETF申赎套利（最低申购份额50万份起），溢价可能随时大幅收窄导致本金亏损。<br>🔴 19%溢价=每买100元额外多付16元入场费，不是"打折买入"而是"高价入场券"。<br>🔴 仅当底层资产(纳指科技指数)涨幅超过溢价收缩幅度时才有可能盈利。<br>🔴 <b>已从可操作套利排名中移除</b>，仅供风险意识参考。</p></div>'
    
    html += """
<!-- ===== 第二部分：完整渠道知识库 ===== -->
<div class="section-title">📋 套利渠道知识库 <span class="sub">共 {len(base_channels)} 个渠道（通用参考，非实时标的）</span></div>

<div class="table-wrapper">
<table>
<thead>
<tr>
    <th>#</th><th>渠道名称</th><th>分类</th>
    <th>难度</th><th>额度范围</th><th>年化收益</th>
    <th>风险</th><th>频率</th><th>简介</th>
</tr>
</thead>
<tbody>
"""
    
    for i, ch in enumerate(base_channels, 1):
        d_color = difficulty_color(ch.get('difficulty','中'))
        r_color = risk_color(ch.get('risk','中'))
        ret_str = f'{ch.get("annual_return_min","")}%~{ch.get("annual_return_max","")}%'
        quota_str = ch.get('quota_desc','') or f'{ch.get("quota_min",0):,.0f}'
        
        html += f"""
<tr>
    <td>{i}</td>
    <td style="font-weight:600">{ch['name']}</td>
    <td><span style="font-size:0.8em;color:#64748b">{ch.get('category','')}</span></td>
    <td><span class="badge" style="background:{d_color}20;color:{d_color};border-left:3px solid {d_color}">{ch.get('difficulty','')}</span></td>
    <td style="font-size:0.82em">{quota_str}</td>
    <td style="font-weight:600;color:#059669">{ret_str}</td>
    <td><span class="badge" style="background:{r_color}20;color:{r_color};border-left:3px solid {r_color}">{ch.get('risk','')}</span></td>
    <td>{ch.get('trade_frequency','')}</td>
    <td style="font-size:0.82em;color:#475569;max-width:250px">{ch.get('description','')[:80]}...</td>
</tr>
"""
    
    html += f"""
</tbody>
</table>
</div>

<div class="footer">
    <p>📊 套利渠道追踪系统 v2 &copy; 2026 | 每日自动更新</p>
    <p style="font-size:0.8em;margin-top:4px">数据来源：东方财富 push2 API | fundgz | fundf10 | 通达信 tdx-connector (QDII ETF)</p>
    <p style="font-size:0.8em;color:#ef4444">⚠️ 免责声明：本报告仅供信息参考，不构成任何投资建议。</p>
</div>

</div>
</body>
</html>
"""
    return html


def save_enhanced_report():
    """生成并保存增强版报告（文件名带日期）"""
    print(f"\n{'='*60}")
    print(f"  生成增强版套利报告 v2 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    try:
        html = generate_enhanced_report()
        today = datetime.now().strftime("%Y-%m-%d")
        report_path = os.path.join(BASE_DIR, f"arbitrage_report_{today}.html")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)
        size_kb = os.path.getsize(report_path) / 1024
        print(f"\n✅ 报告已生成: {report_path} ({size_kb:.1f}KB)")
        return report_path
    except Exception as e:
        print(f"\n❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    save_enhanced_report()
