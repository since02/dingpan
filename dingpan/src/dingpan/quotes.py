"""
行情数据源适配层
三大源：腾讯财经 / 新浪财经 / 东方财富
统一输出结构（dict）
"""
import gzip
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def http_get(url, headers=None, timeout=12, encoding='utf-8'):
    """HTTP GET，返回 (status, text)"""
    h = {'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'zh-CN,zh;q=0.9',
         'Connection': 'close'}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            raw = resp.read()
            if resp.headers.get('Content-Encoding', '').lower() == 'gzip':
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            return resp.status, raw.decode(encoding, errors='replace')
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, body.decode(encoding, errors='replace')
        except Exception:
            return e.code, ''
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise ConnectionError(str(e)) from e


def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ('', '-', '--'):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f


def normalize_code(code):
    """统一证券代码：sh600519 / sz000001 / bj430047 / hk00700 / usAAPL

    纯数字会自动识别交易所前缀：
      6/9 开头 → 上交所(sh)，0/3 开头 → 深交所(sz)，4/8 开头 → 北交所(bj)，
      5 位数字 → 港股(hk)。
    """
    raw = re.sub(r'\s+', '', str(code or '')).lower()
    if not raw:
        return None
    m = re.match(r'^(sh|sz|bj|hk|us|sh\.|sz\.)(\d{5,6})$', raw)
    if m:
        return m[1].replace('.', '') + m[2]
    # 美股：us + 字母（AAPL / TSLA）；也允许直接写字母（会被当成美股）
    m = re.match(r'^us\.?([a-z]{1,6})$', raw)
    if m:
        return 'us' + m[1].upper()
    if re.match(r'^\d{6}$', raw):
        if raw[0] in '69':
            return 'sh' + raw
        if raw[0] in '03':
            return 'sz' + raw
        if raw[0] in '48':
            return 'bj' + raw
        return 'sh' + raw
    if re.match(r'^\d{5}$', raw):
        return 'hk' + raw
    return raw


def price_decimals(code):
    """某证券的报价小数位数（东方财富缩放 & 显示格式化的统一依据）。

    A 股股票/科创板/北交所 = 2 位；场内基金/ETF/LOF/可转债/国债/港股 = 3 位。
    - 东方财富把价格按 10^小数位 放大返回（股票×100、基金×1000）→ 要 ÷10^dec 还原；
    - 盯盘窗口对基金/可转债/港股要显示 3 位小数，股票显示 2 位。
    """
    c = (code or '').lower()
    if c.startswith('hk'):
        return 3
    if c.startswith('us'):
        return 2
    digits = re.sub(r'^[a-z]+', '', c)
    if len(digits) != 6:
        return 2
    if c.startswith('sh'):
        # 5xxxxx 基金/ETF/LOF/REITs；11xxxxx 可转债；9xxxxx 沪市B股 → 3 位
        return 3 if digits[0] in '159' else 2
    if c.startswith('sz'):
        # 1xxxxx 基金/ETF/LOF/可转债/国债；20xxxxx 深市B股 → 3 位
        return 3 if digits[0] in '12' else 2
    if c.startswith('bj'):
        return 2  # 北交所股票 2 位
    return 2


_CODE_RE = re.compile(r'^(?:(sh|sz|bj|hk|us)\.?)?(\d{5,6})(?:\.(sh|sz|bj|hk|us))?$', re.I)
# 美股代码（字母）：只在明确带 us 前缀时认，避免把普通英文单词当代码
_US_CODE_RE = re.compile(r'^us\.?([a-z]{1,6})$', re.I)


def looks_like_code(tok):
    """严格判断一个 token 是不是证券代码（避免把「茅台」当代码发出去）"""
    s = str(tok or '').strip()
    m = _CODE_RE.match(s)
    if not m:
        return False
    # 纯 5 位只在带 hk 前缀时才认（否则和港股无前缀无法区分，容易误判）
    return not (len(m.group(2)) == 5 and not (m.group(1) or m.group(3)))


def parse_codes(text):
    """把「600519 000001, sz300750; 00700」这类混输拆成去重代码列表

    这里是用户明确输入的场合，所以 5 位纯数字直接按港股理解（00700 → hk00700）。
    """
    out = []
    for tok in re.split(r'[\s,;，；、|/]+', str(text or '')):
        tok = tok.strip()
        m = _CODE_RE.match(tok)
        if not m:
            mu = _US_CODE_RE.match(tok)
            if mu:
                code = 'us' + mu.group(1).upper()
                if code not in out:
                    out.append(code)
            continue
        prefix = (m.group(1) or m.group(3) or '').lower()
        digits = m.group(2)
        code = (prefix + digits) if prefix else normalize_code(digits)
        if code and code not in out:
            out.append(code)
    return out


def extract_codes(text):
    """从任意文本（剪贴板、表格列、聊天记录）里捞出证券代码

    正则限定「前后不紧邻字母数字」，所以 600519.SH / SH600519 / 600519 都能识别，
    又不会把 1234567 这种长数字误当成代码。
    """
    out = []
    pat = re.compile(r'(?<![0-9A-Za-z])(?:(sh|sz|bj|hk|us)\.?)?(\d{5,6})(?:\.(sh|sz|bj|hk|us))?(?![0-9A-Za-z])',
                     re.I)
    for m in pat.finditer(str(text or '')):
        prefix = (m.group(1) or m.group(3) or '').lower()
        digits = m.group(2)
        if len(digits) == 5 and prefix != 'hk':
            continue
        code = (prefix + digits) if prefix else normalize_code(digits)
        if code and code not in out:
            out.append(code)
    return out


def _fmt_time(t):
    t = str(t or '')
    if len(t) < 14:
        return t
    return f'{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:14]}'


def _fmt_unix(ts):
    n = num(ts)
    if not n or n <= 0:
        return ''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(n))


# ============================== 腾讯 qt.gtimg.cn ==============================
def parse_tencent_body(text):
    """从腾讯接口返回文本里解析出行情 dict（与网络无关，便于单测）。

    字段：1名称 3现价 4昨收 5今开 6成交量 30时间 31涨跌 32涨跌幅
    33最高 34最低 37成交额 38换手率 39市盈 43振幅 44流通市值 45总市值 46市净
    """
    out = {}
    for m in re.finditer(r'v_([a-z]{2}\d{5,6})="([^"]*)"', text):
        code, body = m.group(1), m.group(2)
        f = body.split('~')
        if len(f) < 40:
            continue
        out[code] = {
            'code': code, 'name': f[1] or '',
            'price': num(f[3]), 'prevClose': num(f[4]), 'open': num(f[5]),
            'volume': num(f[6]), 'time': _fmt_time(f[30]),
            'change': num(f[31]), 'changePct': num(f[32]),
            'high': num(f[33]), 'low': num(f[34]),
            'amount': num(f[37]), 'turnover': num(f[38]), 'pe': num(f[39]),
            'amplitude': num(f[43]), 'floatCap': num(f[44]), 'totalCap': num(f[45]),
            'pb': num(f[46]), 'source': 'tencent',
        }
    return out


def fetch_tencent(codes):
    lst = [c for c in (normalize_code(x) for x in codes) if c]
    if not lst:
        return {}
    url = 'https://qt.gtimg.cn/q=' + ','.join(lst)
    _, text = http_get(url, encoding='gbk')
    return parse_tencent_body(text)


# ============================== 新浪 hq.sinajs.cn ==============================
def parse_sina_body(text):
    """从新浪接口返回文本里解析出行情 dict（与网络无关，便于单测）。

    仅沪深；字段：0名称 1今开 2昨收 3现价 4最高 5最低 8成交量(股) 9成交额(元)
    30日期 31时间。涨跌额按证券小数位取舍，避免基金类丢第 3 位。
    """
    out = {}
    for m in re.finditer(r'var hq_str_([a-z]{2}\d{5,6})="([^"]*)"', text):
        code, body = m.group(1), m.group(2)
        f = body.split(',')
        if len(f) < 10:
            continue
        price, prev = num(f[3]), num(f[2])
        change = round(price - prev, price_decimals(code)) if (price is not None and prev) else None
        pct = round((price - prev) / prev * 100, 2) if (price is not None and prev) else None
        hi, lo = num(f[4]), num(f[5])
        amp = round((hi - lo) / prev * 100, 2) if (hi is not None and lo is not None and prev) else None
        out[code] = {
            'code': code, 'name': f[0] or '',
            'price': price, 'prevClose': prev, 'open': num(f[1]),
            'volume': round(num(f[8]) / 100) if num(f[8]) else None,
            'amount': round(num(f[9]) / 10000, 2) if num(f[9]) else None,
            'time': f'{f[30] or ""} {f[31] or ""}'.strip(),
            'change': change, 'changePct': pct,
            'high': hi, 'low': lo,
            'turnover': None, 'pe': None, 'amplitude': amp,
            'floatCap': None, 'totalCap': None, 'pb': None,
            'source': 'sina',
        }
    return out


def fetch_sina(codes):
    """需 Referer；list= 后不可追加参数；仅支持沪深"""
    lst = [c for c in (normalize_code(x) for x in codes)
           if c and (c.startswith('sh') or c.startswith('sz'))]
    if not lst:
        return {}
    url = 'https://hq.sinajs.cn/list=' + ','.join(lst)
    _, text = http_get(url, headers={'Referer': 'https://finance.sina.com.cn/'}, encoding='gbk')
    return parse_sina_body(text)


# ========================= 东方财富 push2.eastmoney.com =========================
EM_HOSTS = ['push2.eastmoney.com', '82.push2.eastmoney.com',
            '48.push2.eastmoney.com', 'push2delay.eastmoney.com']
EM_FIELDS = 'f1,f2,f3,f4,f5,f6,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f124'


def _fetch_em_once(codes, host_idx):
    lst = [c for c in (normalize_code(x) for x in codes) if c]
    if not lst:
        return {}
    secids = []
    for c in lst:
        mkt = c[:2]
        prefix = '1' if mkt == 'sh' else ('0' if mkt in ('sz', 'bj') else '1')
        secids.append(f'{prefix}.{c[2:]}')
    host = EM_HOSTS[host_idx % len(EM_HOSTS)]
    url = (f'https://{host}/api/qt/ulist.np/get?fields={EM_FIELDS}'
           f'&secids={",".join(secids)}&ut=fa5fd1943c7b386f172d6893dbfba10b'
           f'&r={int(time.time() * 1000)}')
    # 不可带 Referer，否则服务端直接断连
    _, text = http_get(url, headers={'Referer': ''}, timeout=10)
    text = re.sub(r'^\s*cb\s*\(', '', text)
    text = re.sub(r'\)\s*;?\s*$', '', text)
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {}
    diff = (payload or {}).get('data', {}).get('diff') or []
    out = {}

    for d in diff:
        rec = _parse_em_item(d)
        if rec:
            out[rec['code']] = rec
    return out


def _parse_em_item(d):
    """把东方财富单条 diff 解析成统一结构。

    关键：东财把价格按 10^小数位 放大返回 —— A 股 2 位（×100）、场内基金/ETF/LOF/
    可转债/国债/港股 3 位（×1000）。价格类字段(f2/f4/f15/f16/f17/f18)要 ÷10^dec 还原；
    百分比/比率类(f3 涨跌幅/f8 换手率/f9 市盈/f10 振幅)是 ×100，÷100 即可。
    """
    cn = str(d.get('f12') or '')
    if not cn:
        return None
    mkt = {0: 'sz', 1: 'sh'}.get(d.get('f13'), 'bj')
    code = mkt + cn
    dec = price_decimals(code)

    def P(v):  # 价格类：÷10^小数位
        n = num(v)
        return None if n is None else round(n / (10 ** dec), dec)

    def R(v):  # 百分比/比率类：÷100
        n = num(v)
        return None if n is None else round(n / 100, 2)

    return {
        'code': code, 'name': d.get('f14') or '',
        'price': P(d.get('f2')), 'prevClose': P(d.get('f18')),
        'open': P(d.get('f17')), 'volume': num(d.get('f5')),
        'amount': round(num(d.get('f6')) / 10000, 2) if num(d.get('f6')) else None,
        'time': _fmt_unix(d.get('f124')),
        'change': P(d.get('f4')), 'changePct': R(d.get('f3')),
        'high': P(d.get('f15')), 'low': P(d.get('f16')),
        'turnover': R(d.get('f8')), 'pe': R(d.get('f9')),
        'amplitude': R(d.get('f10')),
        'floatCap': None,
        'totalCap': round(num(d.get('f20')) / 1e8, 2) if num(d.get('f20')) else None,
        'pb': None, 'source': 'eastmoney',
    }


def fetch_eastmoney(codes):
    """多域名轮换 + 指数退避重试（东财约 30% 概率主动断连）"""
    last = None
    for attempt in range(3):
        try:
            data = _fetch_em_once(codes, attempt)
            if data:
                return data
            last = RuntimeError('返回空数据')
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.22 * (attempt + 1))
    raise last or RuntimeError('东方财富数据源不可用')


SOURCES = {
    'tencent': ('腾讯财经', fetch_tencent),
    'sina': ('新浪财经', fetch_sina),
    'eastmoney': ('东方财富', fetch_eastmoney),
}

# 自定义数据源在界面上显示的名字（不放在 SOURCES 里 —— 它需要配置参数）
CUSTOM_SOURCE_NAME = '自定义接口…'


# ============================== 自定义数据源 ==============================
# 配置结构（cfg['customSource']）：
#   {
#     'url':      'https://example.com/api/quote?codes={codes}',
#     'mapping':  'name=name,price=last,change=chg',   # 内部字段=返回字段名
#     'encoding': 'utf-8',                              # utf-8 / gbk
#     'codeKey':  'code',                               # 返回体里代码所在的键
#   }
# 支持两种返回格式（自动识别）：
#   ① 对象：{"sh600519": {"name": "贵州茅台", "last": 1688.0}, ...}
#   ② 数组：[{"code": "sh600519", "name": "贵州茅台", "last": 1688.0}, ...]
CUSTOM_FIELDS = [
    ('name', '名称'), ('code', '代码'), ('price', '现价'), ('prevClose', '昨收'),
    ('open', '今开'), ('high', '最高'), ('low', '最低'), ('change', '涨跌'),
    ('changePct', '涨跌幅'), ('volume', '成交量'), ('amount', '成交额'),
    ('turnover', '换手率'), ('pe', '市盈'), ('pb', '市净'), ('amplitude', '振幅'),
    ('floatCap', '流通值'), ('totalCap', '总市值'), ('time', '时间'),
]

# 映射左侧（小写）→ 内部字段名（驼峰）
_FIELD_ALIAS = {k.lower(): k for k, _ in CUSTOM_FIELDS}


def _norm_field_key(k):
    """把映射左侧的字段名规范成内部字段名（大小写不敏感）。

    内部字段名是驼峰的（prevClose / changePct / floatCap / totalCap），
    而用户在映射里可能写成 prevClose 或 prevclose —— 都要认。
    """
    key = str(k or '').strip().lower()
    return _FIELD_ALIAS.get(key, key)


def parse_custom_mapping(text):
    """把「内部字段=返回字段」的映射文本解析成 dict。

    支持换行 / 逗号 / 分号分隔，空格与中文逗号都能识别。
    例：'name=name, price=last' → {'name': 'name', 'price': 'last'}
    ⚠️ 左侧（内部字段名）大小写不敏感，右侧（接口返回的字段名）**保持原样**。
    """
    out = {}
    raw = str(text or '').replace('\r', '\n')
    for chunk in re.split(r'[\n,;；，]+', raw):
        chunk = chunk.strip()
        if not chunk or '=' not in chunk:
            continue
        k, v = chunk.split('=', 1)
        k = _norm_field_key(k)
        v = v.strip()
        if k and v:
            out[k] = v
    return out


def _dig(obj, path):
    """按 'a.b.c' 取值；取不到返回 None"""
    cur = obj
    for part in str(path or '').split('.'):
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def fetch_custom(codes, spec):
    """按用户配置的接口抓取行情。

    spec: {'url': 模板, 'mapping': 映射文本或 dict, 'encoding': 'utf-8'|'gbk',
           'codeKey': 'code'}
    """
    spec = spec or {}
    url_tpl = str(spec.get('url') or '').strip()
    if not url_tpl:
        raise RuntimeError('未配置自定义数据源地址')
    mapping = spec.get('mapping')
    if isinstance(mapping, str):
        mapping = parse_custom_mapping(mapping)
    # 左侧统一规范成内部字段名（用户可能写 prevclose / prevClose 都行）
    mapping = {_norm_field_key(k): v for k, v in (mapping or {}).items() if v}
    if not mapping:
        raise RuntimeError('未配置字段映射')
    enc = (spec.get('encoding') or 'utf-8').lower()
    if enc not in ('utf-8', 'gbk', 'gb2312', 'big5'):
        enc = 'utf-8'
    code_key = str(spec.get('codeKey') or 'code').strip() or 'code'

    lst = [c for c in (normalize_code(x) for x in codes) if c]
    if not lst:
        return {}
    # {codes} → 逗号分隔的代码；{code} → 第一个代码
    url = url_tpl.replace('{codes}', ','.join(lst)).replace('{code}', lst[0])
    _, text = http_get(url, encoding=enc)
    text = (text or '').strip()
    if not text:
        raise RuntimeError('接口返回空内容')
    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as e:
        raise RuntimeError('返回内容不是合法 JSON：%s' % str(e)[:80]) from e

    items = []
    if isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        # 优先找常见的容器键
        for key in ('data', 'result', 'list', 'items', 'rows'):
            v = payload.get(key)
            if isinstance(v, list):
                items = [x for x in v if isinstance(x, dict)]
                break
            if isinstance(v, dict):
                payload = v
                break
        if not items:
            # {code: {...}} 形式
            for k, v in payload.items():
                if isinstance(v, dict):
                    d = dict(v)
                    d.setdefault(code_key, k)
                    items.append(d)
    if not items:
        raise RuntimeError('返回内容里找不到行情条目')

    out = {}
    for it in items:
        code = None
        for ck in (code_key, 'code', 'symbol', 'id'):
            v = _dig(it, ck)
            if v:
                code = normalize_code(str(v)) or str(v).lower()
                break
        if not code:
            continue
        rec = {'code': code, 'source': 'custom'}
        for key, src in mapping.items():
            val = _dig(it, src)
            if val is None:
                continue
            if key in ('name', 'time', 'code'):
                rec[key] = str(val)
            else:
                n = num(val)
                if n is not None:
                    rec[key] = n
        # 涨跌/涨跌幅没给就算出来（很多接口只给现价和昨收）
        if rec.get('change') is None and rec.get('price') is not None \
                and rec.get('prevClose') is not None:
            rec['change'] = round(rec['price'] - rec['prevClose'], 4)
        if rec.get('changePct') is None and rec.get('change') is not None \
                and rec.get('prevClose'):
            rec['changePct'] = round(rec['change'] / rec['prevClose'] * 100, 4)
        if rec.get('name'):
            out[code] = rec
    if not out:
        raise RuntimeError('解析后没有得到有效行情')
    return out


def test_custom_source(spec, code='sh600519'):
    """设置页的「测试」：返回 (ok, 说明, 条数)"""
    try:
        data = fetch_custom([code], spec)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:160], 0
    if not data:
        return False, '接口返回了空数据', 0
    first = list(data.values())[0]
    return True, '成功，%d 条；示例：%s' % (len(data), first.get('name') or '-'), len(data)



# ============================== 「打开行情页」平台 ==============================
# 每个平台一个 URL 模板：
#   {code} → 带前缀的小写代码（sh600519）
#   {sym}  → 带前缀的大写代码（SH600519）
#   {num}  → 纯数字代码（600519）
QUOTE_PLATFORMS = {
    'xueqiu':    ('雪球',       'https://xueqiu.com/S/{sym}'),
    'tencent':   ('腾讯财经',   'https://gu.qq.com/{code}/gp'),
    'eastmoney': ('东方财富',   'https://quote.eastmoney.com/{code}.html'),
    'sina':      ('新浪财经',   'https://finance.sina.com.cn/realstock/company/{code}/nc.shtml'),
    'ths':       ('同花顺',     'https://stockpage.10jqka.com.cn/{num}/'),
    'custom':    ('自定义…',    ''),
}


def build_quote_url(code, platform='xueqiu', template=''):
    """按平台生成股票详情页 URL。

    platform 为 'custom' 时用 template；模板里可用 {code} / {sym} / {num} 占位符。
    """
    c = str(code or '').strip().lower()
    if not c:
        return ''
    if c.startswith('hk'):
        sym = 'HK' + c[2:].upper()
    elif c.startswith('us'):
        sym = c[2:].upper()
    elif c.startswith('bj'):
        sym = 'BJ' + c[2:]
    elif c.startswith('sh'):
        sym = 'SH' + c[2:]
    else:
        sym = 'SZ' + c[2:]
    num = re.sub(r'^[a-z]+', '', c)
    tpl = template
    if platform != 'custom':
        entry = QUOTE_PLATFORMS.get(platform)
        if entry:
            tpl = entry[1]
    if not tpl:
        return ''
    try:
        return tpl.replace('{code}', c).replace('{sym}', sym).replace('{num}', num)
    except Exception:  # noqa: BLE001
        return ''

FALLBACK_ORDER = {
    'tencent': ['tencent', 'sina', 'eastmoney'],
    'sina': ['sina', 'tencent', 'eastmoney'],
    'eastmoney': ['eastmoney', 'tencent', 'sina'],
    # 自定义源失败时降级到腾讯 → 新浪 → 东财
    'custom': ['custom', 'tencent', 'sina', 'eastmoney'],
}


def fetch_quotes(codes, source_id='tencent', custom_spec=None):
    """返回 dict: {ok, source, data, fallback, error}"""
    order = FALLBACK_ORDER.get(source_id, FALLBACK_ORDER['tencent'])
    codes = list(codes or [])
    if not codes:
        return {'ok': True, 'source': source_id, 'data': {}, 'fallback': False}
    last_err = None
    for i, sid in enumerate(order):
        if sid == 'custom':
            # 自定义源：没有配置就跳过，交给后面的备用源
            if not custom_spec:
                last_err = RuntimeError('未配置自定义数据源')
                continue
            try:
                data = fetch_custom(codes, custom_spec)
                if data:
                    return {'ok': True, 'source': 'custom', 'data': data,
                            'fallback': i > 0, 'fallbackFrom': order[0] if i > 0 else None}
                last_err = RuntimeError('自定义数据源返回空数据')
            except Exception as e:  # noqa: BLE001
                last_err = e
            continue
        entry = SOURCES.get(sid)
        if not entry:
            continue
        try:
            data = entry[1](codes)
            if data:
                return {'ok': True, 'source': sid, 'data': data,
                        'fallback': i > 0, 'fallbackFrom': order[0] if i > 0 else None}
            last_err = RuntimeError(f'{entry[0]} 返回空数据')
        except Exception as e:  # noqa: BLE001
            last_err = e
    return {'ok': False, 'source': source_id, 'data': {},
            'error': str(last_err or '获取失败')}


def verify_code(code):
    """校验证券代码，返回 (ok, code, name, error)"""
    c = normalize_code(code)
    if not c:
        return False, None, None, '代码格式不正确'
    res = fetch_quotes([c], 'tencent')
    if not res['ok']:
        return False, None, None, res.get('error', '获取失败')
    q = res['data'].get(c)
    if not q or not q.get('name'):
        return False, None, None, '未找到该证券'
    return True, c, q['name'], ''
