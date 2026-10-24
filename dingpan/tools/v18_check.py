"""v1.0.18 新需求专项测试

覆盖用户这一轮提的 5 件事：
  1. 设置菜单出错了，所有页面都显示了打勾的自选股票代码
  2. 悬浮窗边框和内部线段，可分别自选是否显示
  3. 自选代码和自选的显示数据，改成简单的选择方式，并都支持直接拖拽进行排序，
     支持设置是否勾选显示
  4. 打开行情页进入的平台，可以提供几个常用的来进行选择或自定义平台
  5. 数据源可自定义平台，提供简单的设置提示
"""
import ctypes
import io
import os
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ⚠️ 必须在 import dingpan.storage **之前**隔离 APPDATA
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dp_v18_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import quotes, storage, win32 as w32           # noqa: E402
from dingpan.app import App                                 # noqa: E402
from dingpan import settings as st                          # noqa: E402
from dingpan.win32 import user32                            # noqa: E402

FAILS = []


def check(name, cond, extra=''):
    if cond:
        print('  ✓ %s' % name)
    else:
        print('  ✗ %s   %s' % (name, extra))
        FAILS.append(name)


def pump(app, ms=150):
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def visible_children(hwnd):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h):
            out.append(int(h))
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    return out


def main():
    app = App()
    app.cfg['groups'] = [{'id': 'g', 'name': '默认', 'stocks': [
        {'code': 'sh600519', 'name': '贵州茅台'},
        {'code': 'sz000001', 'name': '平安银行'},
        {'code': 'sz300750', 'name': '宁德时代'}]}]
    app.cfg['activeGroupId'] = 'g'
    app.create_window()
    app.refresh = lambda: None
    obj = app.open_settings()
    pump(app, 400)

    # ============ 1. 自选列表不能跑到所有设置页上 ============
    print('\n=== 1. 自选列表只在自己那一页显示 ===')
    pages = [(st.P_BASIC, '基础设置'), (st.P_STYLE, '样式方案'),
             (st.P_STOCKS, '自选管理'), (st.P_COLUMNS, '显示字段'),
             (st.P_BACKUP, '备份恢复'),
             (st.P_HOTKEY, '快捷键'), (st.P_ABOUT, '关于')]
    leak = []
    for pid, name in pages:
        obj._show_page(pid)
        pump(app, 80)
        vis = visible_children(obj.hwnd)
        if pid != st.P_STOCKS and int(obj.lb_stocks) in vis:
            leak.append(name)
    check('自选列表没有泄漏到其它设置页', not leak, str(leak))
    obj._show_page(st.P_STOCKS)
    pump(app, 80)
    check('切到「自选管理」页时自选列表可见',
          int(obj.lb_stocks) in visible_children(obj.hwnd))
    obj._show_page(st.P_COLUMNS)
    pump(app, 80)
    check('切到「显示字段」页时自选列表隐藏',
          int(obj.lb_stocks) not in visible_children(obj.hwnd))
    check('切到「显示字段」页时字段列表可见',
          int(obj.lb_fields) in visible_children(obj.hwnd))

    # ============ 2. 边框与内部线段分别可选 ============
    print('\n=== 2. 外边框 / 内部线段分别可选 ===')
    app.cfg['theme'] = 'custom'
    app.cfg['customBg'] = '#000000'
    app.cfg['customText'] = '#ffffff'
    app.cfg['columns'] = ['name', 'price']
    app.widget.cfg = app.cfg
    app.widget.quotes = {'sh600519': {'code': 'sh600519', 'name': '贵州茅台',
                                      'price': 1688.0, 'change': 1.0, 'changePct': 0.1,
                                      'turnover': 0.1, 'time': '10:30'}}
    app.widget._mkey = app.widget._mval = None
    app.widget._wkey = app.widget._wval = None

    def edge_and_grid(border, grid):
        app.cfg['showBorder'] = border
        app.cfg['showGridLines'] = grid
        app.widget.cfg = app.cfg
        app.widget._cleanup_buffers()
        app.widget.paint()
        lay = app.widget._lay
        w, h = app.widget.client_size()
        buf = ctypes.string_at(lay['cbits'].value, w * h * 4)
        # 外框像素：左边缘中点处，若与内部背景同色 → 没画框
        edge = buf[((h // 2) * w) * 4 + 1]          # 绿通道
        mid = buf[((h // 2) * w + w // 2) * 4 + 1]
        # 内部线段：表头下沿那一行（表头之后约 fs+3）
        fs = app.widget.eff_font_size()
        ly = app.widget.header_h + app.widget.tabs_h + fs + 3
        if ly < h:
            line_px = buf[(ly * w + w // 2) * 4 + 1]
        else:
            line_px = -1
        return edge, mid, line_px

    e0, m0, l0 = edge_and_grid(False, True)
    check('默认不画外框（边缘与内部背景同色）', e0 == m0, '%s vs %s' % (e0, m0))
    e1, m1, l1 = edge_and_grid(True, True)
    check('勾上「显示悬浮窗外边框」后边缘变色', e1 != m1, '%s vs %s' % (e1, m1))
    e2, m2, l2 = edge_and_grid(True, False)
    check('关掉「显示表格内部线段」后表头下划线消失', l2 != l1 or l2 < 0,
          '%s -> %s' % (l1, l2))
    # 设置页的两个复选框存在且能收集
    obj._show_page(st.P_BASIC)
    pump(app, 100)
    obj._set_check(obj.cb_border, True)
    obj._set_check(obj.cb_gridlines, False)
    got = obj._collect()
    check('「显示悬浮窗外边框」被收集', got.get('showBorder') is True, str(got.get('showBorder')))
    check('「显示表格内部线段」被收集', got.get('showGridLines') is False,
          str(got.get('showGridLines')))
    app.cfg['showBorder'] = False
    app.cfg['showGridLines'] = True

    # ============ 3. 显示字段：勾选 + 拖拽排序 ============
    print('\n=== 3. 显示字段页：单列表 + 勾选 + 拖拽排序 ===')
    obj._show_page(st.P_COLUMNS)
    pump(app, 100)
    n = user32.SendMessageW(obj.lb_fields, 0x018B, 0, 0)
    check('列出全部可选字段', n == len(st.COLUMN_DEFS), '%d 项' % n)
    labels = [obj._lb_text(obj.lb_fields, i) for i in range(n)]
    check('每项都带 [√]/[  ] 勾选标记', all(x.startswith('[') for x in labels),
          str(labels[:2]))
    # 勾选切换
    idx = next(i for i, x in enumerate(labels) if not x.startswith(st.FIELD_MARK_ON))
    key = obj._field_order[idx]
    obj._toggle_field_enabled(idx)
    check('点 [√] → 该字段被勾上', key in obj._get_selected_columns(),
          str(obj._get_selected_columns()))
    obj._toggle_field_enabled(idx)
    check('再点 → 取消勾选，但字段没被删',
          key not in obj._get_selected_columns()
          and user32.SendMessageW(obj.lb_fields, 0x018B, 0, 0) == n,
          str(obj._get_selected_columns()))
    # 真实鼠标拖动排序
    order0 = list(obj._field_order)
    user32.SendMessageW(obj.lb_fields, 0x0201, 1, (5 << 16) | 100)
    user32.SendMessageW(obj.lb_fields, 0x0200, 1, (65 << 16) | 100)
    user32.SendMessageW(obj.lb_fields, 0x0202, 0, (65 << 16) | 100)
    # y=65 → 行号 65//20 = 3 → 移到第 3 位
    check('鼠标拖动真的换了顺序',
          obj._field_order[:4] == [order0[1], order0[2], order0[3], order0[0]],
          str(obj._field_order[:4]))
    check('拖动后完整顺序被记住（含未勾选字段）',
          len(obj.app.cfg.get('fieldOrder') or []) == len(st.COLUMN_DEFS),
          str(len(obj.app.cfg.get('fieldOrder') or [])))
    # 自选列表也支持拖动 + 勾选
    obj._show_page(st.P_STOCKS)
    pump(app, 100)
    stocks0 = [s['code'] for s in obj._stocklist_rows()]
    obj._toggle_stock_enabled(0)
    check('自选列表点 [√] 能取消勾选',
          obj._stocklist_rows()[0].get('enabled') is False, str(stocks0))
    obj._toggle_stock_enabled(0)
    user32.SendMessageW(obj.lb_stocks, 0x0201, 1, (5 << 16) | 100)
    user32.SendMessageW(obj.lb_stocks, 0x0200, 1, (45 << 16) | 100)
    user32.SendMessageW(obj.lb_stocks, 0x0202, 0, (45 << 16) | 100)
    check('自选列表鼠标拖动能排序',
          [s['code'] for s in obj._stocklist_rows()] != stocks0,
          str([s['code'] for s in obj._stocklist_rows()]))

    # ============ 4. 行情页平台可选 / 可自定义 ============
    print('\n=== 4. 「打开行情页」平台可选择 / 可自定义 ===')
    check('内置多个常用平台', len(quotes.QUOTE_PLATFORMS) >= 5,
          str(list(quotes.QUOTE_PLATFORMS.keys())))
    check('默认雪球', quotes.build_quote_url('sh600519', 'xueqiu')
          == 'https://xueqiu.com/S/SH600519', quotes.build_quote_url('sh600519', 'xueqiu'))
    check('腾讯', quotes.build_quote_url('sz000001', 'tencent')
          == 'https://gu.qq.com/sz000001/gp')
    check('东方财富', quotes.build_quote_url('sh600519', 'eastmoney')
          == 'https://quote.eastmoney.com/sh600519.html')
    check('港股', quotes.build_quote_url('hk00700', 'xueqiu')
          == 'https://xueqiu.com/S/HK00700')
    check('自定义模板支持 {code}/{sym}/{num}',
          quotes.build_quote_url('sh600519', 'custom', 'https://x.com/{code}/{sym}/{num}')
          == 'https://x.com/sh600519/SH600519/600519')
    check('自定义模板为空 → 返回空（不乱跳）', quotes.build_quote_url('sh600519', 'custom', '') == '')
    # 设置页能选平台并保存
    obj._show_page(st.P_BASIC)
    pump(app, 100)
    keys = list(quotes.QUOTE_PLATFORMS.keys())
    obj._set_combo_sel(obj.cb_quote_platform, keys.index('eastmoney'))
    obj._set_text(obj.ed_quote_url, 'https://mine/{code}')
    got = obj._collect()
    check('行情页平台被保存', got.get('quotePlatform') == 'eastmoney',
          str(got.get('quotePlatform')))
    check('自定义平台地址被保存', got.get('quoteUrlTemplate') == 'https://mine/{code}',
          str(got.get('quoteUrlTemplate')))
    # app._open_quote 用配置的平台
    app.cfg['quotePlatform'] = 'eastmoney'
    app.cfg['quoteUrlTemplate'] = ''
    check('app 按配置的平台拼 URL',
          quotes.build_quote_url('sh600519', app.cfg['quotePlatform']) ==
          'https://quote.eastmoney.com/sh600519.html')

    # ============ 5. 自定义数据源 ============
    print('\n=== 5. 数据源可自定义 + 简单设置提示 ===')
    check('下拉框里有「自定义接口…」', quotes.CUSTOM_SOURCE_NAME == '自定义接口…',
          quotes.CUSTOM_SOURCE_NAME)
    m = quotes.parse_custom_mapping('name=name, price=last；turnover=rate')
    check('字段映射能解析（逗号/中文逗号/分号都行）',
          m == {'name': 'name', 'price': 'last', 'turnover': 'rate'}, str(m))
    # 模拟接口返回：{code: {...}}（stub 掉 http_get，不发真实请求）
    payload = {'sh600519': {'name': '贵州茅台', 'last': 1688.0, 'chg': 12.3,
                            'prev': 1675.7, 'ts': '2026-10-23 10:30:00'}}
    spec = {'url': 'https://x.com/q?codes={codes}',
            'mapping': 'name=name,price=last,change=chg,prevClose=prev,time=ts',
            'encoding': 'utf-8', 'codeKey': 'code'}
    import json as _json
    _orig_get = quotes.http_get
    _seen = []

    def _fake_get(url, headers=None, timeout=12, encoding='utf-8'):
        _seen.append(url)
        return 200, _json.dumps(payload, ensure_ascii=False)

    quotes.http_get = _fake_get
    try:
        got = quotes.fetch_custom(['sh600519'], spec)
    finally:
        quotes.http_get = _orig_get
    check('接口地址里的 {codes} 被替换成代码列表',
          _seen and 'codes=sh600519' in _seen[0], str(_seen))
    check('自定义源：{code: {...}} 形式能解析',
          got.get('sh600519', {}).get('name') == '贵州茅台', str(got))
    check('自定义源：数值字段被转成 float',
          got.get('sh600519', {}).get('price') == 1688.0, str(got))
    check('自定义源：没给涨跌时按 现价-昨收 自动算',
          abs(got.get('sh600519', {}).get('change', 0) - 12.3) < 0.01, str(got))
    check('自定义源：没给涨跌幅时自动算',
          abs(got.get('sh600519', {}).get('changePct', 0) - 12.3 / 1675.7 * 100) < 0.01,
          str(got))
    # 数组形式（同样 stub 网络）
    def _fake_get2(url, headers=None, timeout=12, encoding='utf-8'):
        return 200, _json.dumps([{'code': 'sh600519', 'name': '贵州茅台',
                                   'last': 1688.0}], ensure_ascii=False)

    quotes.http_get = _fake_get2
    try:
        got2 = quotes.fetch_custom(['sh600519'], spec)
    finally:
        quotes.http_get = _orig_get
    check('自定义源：数组形式也能解析',
          got2.get('sh600519', {}).get('name') == '贵州茅台', str(got2))
    # 缺配置时要给出清楚的错误
    try:
        quotes.fetch_custom(['sh600519'], {})
        check('没填地址时给出明确错误', False, '没抛异常')
    except RuntimeError as e:
        check('没填地址时给出明确错误', '地址' in str(e), str(e))
    try:
        quotes.fetch_custom(['sh600519'], {'url': 'https://x.com'})
        check('没填映射时给出明确错误', False, '没抛异常')
    except RuntimeError as e:
        check('没填映射时给出明确错误', '映射' in str(e), str(e))
    # 设置页：选自定义 → 显示配置区 + 提示
    obj._show_page(st.P_BASIC)
    pump(app, 100)
    obj._set_combo_sel(obj.cb_source, obj._source_ids().index('custom'))
    obj._sync_custom_source_enabled()
    pump(app, 80)
    vis = visible_children(obj.hwnd)
    check('选「自定义接口…」后配置区显示出来',
          int(obj.ed_cust_url) in vis and int(obj.ed_cust_map) in vis
          and int(obj.btn_cust_test) in vis)
    check('有简单的设置提示', '示例' in obj._get_text(obj.lbl_cust_hint),
          obj._get_text(obj.lbl_cust_hint)[:40])
    obj._set_text(obj.ed_cust_url, 'https://x.com/q?codes={codes}')
    obj._set_text(obj.ed_cust_map, 'name=name,price=last')
    got = obj._collect()
    check('自定义数据源配置被保存',
          got.get('customSource', {}).get('url') == 'https://x.com/q?codes={codes}',
          str(got.get('customSource')))
    check('数据源 id 切到 custom', got.get('source') == 'custom', str(got.get('source')))
    # 切回内置源 → 配置区隐藏
    obj._set_combo_sel(obj.cb_source, 0)
    obj._sync_custom_source_enabled()
    pump(app, 80)
    vis = visible_children(obj.hwnd)
    check('切回内置源后自定义配置区隐藏', int(obj.ed_cust_url) not in vis)

    # ============ 6. 列表：三列自绘 + 字体统一 + 拖动真的生效 ============
    print('\n=== 6. 列表三列布局 / 字体 / 拖动排序 ===')
    # 6.1 字体：列表要用设置窗口的微软雅黑，不能是系统默认（宋体）
    for name, lb in (('自选列表', obj.lb_stocks), ('字段列表', obj.lb_fields)):
        fid = user32.SendMessageW(lb, 0x0031, 0, 0)   # WM_GETFONT
        # ⚠️ 句柄只比较低 32 位：WM_GETFONT 返回的是符号扩展过的有符号 64 位，
        #    而 self._font 是无符号大数，直接比会不相等（但其实是同一个句柄）
        check('%s 用了设置窗口的字体（不是系统默认）' % name,
              (fid & 0xFFFFFFFF) == (int(obj._font) & 0xFFFFFFFF),
              'font=%s 期望=%s' % (hex(fid & 0xFFFFFFFF), hex(int(obj._font) & 0xFFFFFFFF)))
    # 6.2 自绘：拦截 WM_PAINT 自己画（owner-draw 的 WM_DRAWITEM 本机不触发）
    src_set = io.open(os.path.join(ROOT, 'src', 'dingpan', 'settings.py'),
                      encoding='utf-8').read()
    check('列表走自绘（拦截 WM_PAINT）', '_draw_checklist' in src_set
          and 'WM_PAINT' in src_set)
    check('自绘里画了复选框方框', '_draw_checkbox' in src_set)
    check('自绘里画了拖拽手柄', '_draw_drag_handle' in src_set)
    # 6.3 未勾选项不该把 [  ] 文字画出来（只画方框）
    obj._show_page(st.P_COLUMNS)
    pump(app, 100)
    labels = [obj._lb_text(obj.lb_fields, i) for i in
              range(user32.SendMessageW(obj.lb_fields, 0x018B, 0, 0))]
    off = [x for x in labels if not x.startswith(st.FIELD_MARK_ON)]
    check('存在未勾选项用于验证', bool(off), str(labels[:2]))
    if off:
        idx = labels.index(off[0])
        name = off[0]
        end = name.find(']')
        shown = name[end + 1:].strip() if end > 0 else name
        check('未勾选项的文本只有字段名（标记是画出来的方框）',
              shown and not shown.startswith('['), repr(shown))
    # 6.4 自选股拖动排序：列表显示与配置顺序都要变（用户反馈「无法移动」）
    obj._show_page(st.P_STOCKS)
    pump(app, 100)
    before = [x.split()[1] for x in
              (obj._lb_text(obj.lb_stocks, i) for i in
               range(user32.SendMessageW(obj.lb_stocks, 0x018B, 0, 0)))]
    user32.SendMessageW(obj.lb_stocks, 0x0201, 1, (5 << 16) | 100)
    user32.SendMessageW(obj.lb_stocks, 0x0200, 1, (48 << 16) | 100)
    user32.SendMessageW(obj.lb_stocks, 0x0202, 0, (48 << 16) | 100)
    after = [x.split()[1] for x in
             (obj._lb_text(obj.lb_stocks, i) for i in
              range(user32.SendMessageW(obj.lb_stocks, 0x018B, 0, 0)))]
    cfg_after = [s['code'] for s in obj._stocklist_rows()]
    check('拖动后列表显示的顺序变了', after != before, '%s -> %s' % (before, after))
    check('拖动后配置里的顺序也变了', cfg_after == after,
          '%s vs %s' % (cfg_after, after))
    check('拖动的是第 0 行到第 2 位', after[:3] == [before[1], before[2], before[0]],
          str(after[:3]))
    # 6.5 显示字段页拖动同样生效
    obj._show_page(st.P_COLUMNS)
    pump(app, 100)
    fbefore = list(obj._field_order)
    user32.SendMessageW(obj.lb_fields, 0x0201, 1, (5 << 16) | 100)
    user32.SendMessageW(obj.lb_fields, 0x0200, 1, (48 << 16) | 100)
    user32.SendMessageW(obj.lb_fields, 0x0202, 0, (48 << 16) | 100)
    check('显示字段页拖动排序也生效',
          obj._field_order[:3] == [fbefore[1], fbefore[2], fbefore[0]],
          str(obj._field_order[:3]))

    # ============ 7. 本轮修复：选中跟随 / 透明度 / 方案 / 位置 ============
    print('\n=== 7. 拖动选中跟随 / 透明度独立 / 方案完整 / 窗口位置 ===')
    obj._show_page(st.P_STOCKS)
    pump(app, 120)
    # 7.1 拖动时选中框要跟着走（用户反馈「选中的框没有跟随移动」）
    # ⚠️ 选中行号存在 Python 侧（不用原生 LB_GETCURSEL）——
    #    原生 LB_SETCURSEL 会让原生 listbox 立刻用自己的样式画一遍选中行 → 覆盖自绘。
    user32.SendMessageW(obj.lb_stocks, 0x0201, 1, (5 << 16) | 100)
    check('按下后选中那一行', obj._cl_sel('stocks') == 0,
          'selected=%s' % obj._cl_sel('stocks'))
    user32.SendMessageW(obj.lb_stocks, 0x0200, 1, (48 << 16) | 100)
    check('拖动过程中选中框跟到目标行', obj._cl_sel('stocks') == 2,
          'selected=%s' % obj._cl_sel('stocks'))
    user32.SendMessageW(obj.lb_stocks, 0x0202, 0, (48 << 16) | 100)
    check('松手后选中仍在目标行', obj._cl_sel('stocks') == 2,
          'selected=%s' % obj._cl_sel('stocks'))
    # 7.2 透明度两条通道独立（白底黑字，用户实际用的配色）
    obj._show_page(st.P_STYLE)
    pump(app, 100)

    # 注入假行情：表头文字是「派生灰」，只有数据行的名称/代码才用纯黑 customText
    app.widget.quotes = {
        'sh600519': {'code': 'sh600519', 'name': '贵州茅台', 'price': 1688.0,
                     'change': 12.3, 'changePct': 0.74, 'turnover': 0.5,
                     'time': '10:30'},
    }
    app.widget._mkey = app.widget._mval = None
    app.widget._wkey = app.widget._wval = None

    def alpha_probe(bg, tx):
        w = app.widget
        c = dict(app.cfg)
        c['theme'] = 'custom'; c['customBg'] = '#ffffff'; c['customText'] = '#0000ff'
        c['upColor'] = '#000000'; c['downColor'] = '#000000'
        c['columns'] = ['name', 'price']
        c['showStatus'] = False; c['showTableHead'] = False
        c['bgAlpha'] = bg; c['textAlpha'] = tx
        prev = w.cfg
        w.cfg = c
        w._cleanup_buffers(); w.paint()
        lay = w._lay
        ww, hh = w.client_size()
        buf = ctypes.string_at(lay['cbits'].value, ww * hh * 4)
        # 全图统计（不能用 if/elif：白色像素很常见，会把后面的黑色像素漏掉）
        from collections import Counter as _C
        bg_c, tx_c = _C(), _C()
        # ⚠️ 源图是**预乘**过的（分层窗口硬性要求）：
        #    白底 #ffffff 预乘后 = (bg_a, bg_a, bg_a) 灰阶；
        #    正文改成纯蓝 #0000ff，预乘后 = (0, 0, tx_a)，
        #    这样背景和正文不会互相认错。
        for i in range(ww * hh):
            r, g, b, a = buf[i * 4 + 2], buf[i * 4 + 1], buf[i * 4], buf[i * 4 + 3]
            if r == g == b and b > 0:
                bg_c[a] += 1
            elif r == 0 and g == 0 and b > 0:
                tx_c[a] += 1
        w.cfg = prev
        return (bg_c.most_common(1)[0][0] if bg_c else None,
                tx_c.most_common(1)[0][0] if tx_c else None)

    b62, t62 = alpha_probe(62, 100)
    check('白底黑字：背景 62% 时背景变半透明', b62 is not None and 150 <= b62 <= 166,
          'bg_alpha=%s' % b62)
    check('白底黑字：背景 62% 时文字仍 100% 不透明', t62 == 255, 'tx_alpha=%s' % t62)
    b30, t30 = alpha_probe(30, 100)
    check('背景再降到 30%，文字依然是 100%', t30 == 255, 'tx_alpha=%s' % t30)
    b100, t40 = alpha_probe(100, 40)
    check('文字降到 40% 时背景仍是 100% 不透明', b100 == 255, 'bg_alpha=%s' % b100)
    check('文字透明度本身生效', t40 is not None and abs(t40 - 102) <= 3, 'tx_alpha=%s' % t40)
    # 7.3 显示方案要保存完整设置
    obj._set_check(obj.rb_custom, True)
    obj._set_text(obj.btn_bg_color, '#123456')
    obj._set_trackbar(obj.sb_bg, 45, 20, 100)
    obj._set_trackbar(obj.sb_text, 85, 20, 100)
    obj._set_combo_sel(obj.cb_font, 16 - 10)
    obj._set_check(obj.cb_status, False)
    obj._set_text(obj.ed_preset_name, '完整性验证方案')
    obj._save_preset()
    saved = [x for x in (app.cfg.get('presets') or [])
             if x.get('name') == '完整性验证方案']
    check('方案已保存', bool(saved))
    if saved:
        disp = saved[0].get('display') or {}
        need = ('theme', 'customBg', 'bgAlpha', 'textAlpha', 'fontSize',
                'upColor', 'downColor', 'showStatus', 'showTableHead',
                'showBorder', 'showGridLines', 'nameChars')
        miss = [k for k in need if k not in disp]
        check('方案里存了完整的显示设置', not miss, '缺少 %s' % miss)
    # 改乱 → 切回来
    obj._set_check(obj.rb_dark, True)
    obj._set_trackbar(obj.sb_bg, 100, 20, 100)
    obj._set_combo_sel(obj.cb_font, 13 - 10)
    obj._set_check(obj.cb_status, True)
    names = [x['name'] for x in obj._presets()]
    obj._set_combo_sel(obj.cb_preset, names.index('完整性验证方案'))
    obj._apply_preset()
    pump(app, 100)
    # v1.0.26：**在下拉框里换方案就立即套用**，不用再点「应用 / 保存」
    _obj_before = app.cfg.get('theme')
    obj._set_check(obj.rb_dark, True)
    obj._apply_change()
    pump(app, 60)
    _set_combo_sel_notify = obj.cb_preset
    # 模拟「用户在下拉框里选了另一个方案」：CBN_SELCHANGE
    obj._on_command(9424, _set_combo_sel_notify, 1)
    pump(app, 120)
    check('下拉框换方案立即生效（不用再点保存）',
          app.cfg.get('theme') == 'custom', str(app.cfg.get('theme')))
    check('切换方案后主题回来了', app.cfg.get('theme') == 'custom', str(app.cfg.get('theme')))
    check('切换方案后背景色回来了', app.cfg.get('customBg') == '#123456',
          str(app.cfg.get('customBg')))
    check('切换方案后背景不透明度回来了', app.cfg.get('bgAlpha') == 45,
          str(app.cfg.get('bgAlpha')))
    check('切换方案后文字不透明度回来了', app.cfg.get('textAlpha') == 85,
          str(app.cfg.get('textAlpha')))
    check('切换方案后字号回来了', app.cfg.get('fontSize') == 16,
          str(app.cfg.get('fontSize')))
    check('切换方案后显示状态栏开关回来了', app.cfg.get('showStatus') is False,
          str(app.cfg.get('showStatus')))
    check('切换方案后界面滑块也同步了',
          user32.SendMessageW(obj.sb_bg, 0x0400, 0, 0) == 45,
          str(user32.SendMessageW(obj.sb_bg, 0x0400, 0, 0)))
    # 7.4 改设置不能把窗口位置弄丢
    r0 = wintypes.RECT(); user32.GetWindowRect(app.hwnd, ctypes.byref(r0))
    for cols in (['name'], ['name', 'code', 'price'], ['code', 'price']):
        app.cfg['columns'] = cols
        app.widget.cfg = app.cfg
        app.widget._mkey = app.widget._mval = None
        app.widget._wkey = app.widget._wval = None
        app._apply_auto_size()
    pump(app, 100)
    r1 = wintypes.RECT(); user32.GetWindowRect(app.hwnd, ctypes.byref(r1))
    check('反复改设置后窗口左上角不动（记住上次位置）',
          (r1.left, r1.top) == (r0.left, r0.top),
          '(%d,%d) -> (%d,%d)' % (r0.left, r0.top, r1.left, r1.top))

    # ============ 8. 本轮：实时同步 / 无重影 / 高亮不越界 / 描边 ============
    print('\n=== 8. 实时同步 / 列表重影 / 高亮越界 / 文字描边 ===')
    obj._show_page(st.P_STOCKS)
    pump(app, 120)
    w = app.widget
    # 8.1 取消勾选 → 悬浮窗立刻少一只（用户反馈「取消勾选后还在显示」）
    w.paint()
    n0 = len(w.rows)
    obj._toggle_stock_enabled(0)
    pump(app, 120)
    check('取消勾选后悬浮窗立刻少一行', len(w.rows) == n0 - 1,
          '%d -> %d' % (n0, len(w.rows)))
    obj._toggle_stock_enabled(0)
    pump(app, 120)
    check('勾回来后悬浮窗立刻恢复', len(w.rows) == n0,
          '%d' % len(w.rows))
    # 8.2 新增自选 → 悬浮窗立刻多一行
    groups = app.cfg.get('groups') or []
    groups[0].setdefault('stocks', []).append(
        {'code': 'sh601318', 'name': '中国平安'})
    obj._refresh_stock_list()
    obj._sync_widget_stocks()
    pump(app, 120)
    check('新增自选后悬浮窗立刻多一行', len(w.rows) == n0 + 1,
          '%d -> %d' % (n0, len(w.rows)))
    groups[0]['stocks'].pop()
    obj._refresh_stock_list()
    obj._sync_widget_stocks()
    pump(app, 100)
    # 8.3 列表无重影：每一行文字只能占**一个连续区间**
    def _row_bands(lb):
        """返回列表里每一行文字的 y 区间（检测重影用）"""
        n = user32.SendMessageW(lb, 0x018B, 0, 0)
        bands = []
        for i in range(n):
            # 读该项文本长度 → 用 LB_GETITEMRECT 拿不到（自绘），
            # 这里改成按固定行高推算区间，再看有没有第二段
            bands.append(i * obj.ROW_H)
        return bands
    # 用像素验证太重，这里用「自绘必须存在」+「不能走原生」两条静态断言代替
    src_set = io.open(os.path.join(ROOT, 'src', 'dingpan', 'settings.py'),
                      encoding='utf-8').read()
    # 精确取 _draw_checklist / _checklist_proc 函数体，并**去掉注释**再判断
    def _code_only(text):
        out = []
        for ln in text.split('\n'):
            t = ln.split('#')[0]
            if t.strip():
                out.append(t)
        return '\n'.join(out)
    fn_draw = _code_only(src_set.split('def _draw_checklist')[1].split('\n    def ')[0])
    fn_proc = _code_only(src_set.split('def _checklist_proc')[1].split('\n    def ')[0])
    paint_branch = (fn_proc.split('if msg == w32.WM_PAINT:')[-1]
                    .split('if msg == w32.WM_LBUTTONDOWN:')[0])
    check('自绘用 GetDC（不受更新区域裁剪 → 不会重影）',
          'user32.GetDC(hwnd)' in fn_draw and 'BeginPaint' not in fn_draw,
          'GetDC=%s BeginPaint=%s' % ('user32.GetDC(hwnd)' in fn_draw,
                                      'BeginPaint' in fn_draw))
    check('WM_PAINT 分支绝不转发原生（自己画完就 return 0）',
          'return 0' in paint_branch, repr(paint_branch[:120]))
    check('自绘列表不再用 LB_SETCURSEL 改选中（否则原生会抢画）',
          '0x0186' not in fn_proc, '自绘过程里还有 LB_SETCURSEL')
    check('选中行号存在 Python 侧', '_checklist_sel' in src_set)
    check('自绘异常会落盘（不再静默吞掉）', 'crash.log' in src_set)
    # 8.4 选中高亮不覆盖拖拽手柄区
    check('高亮留出了手柄区宽度', 'self.HANDLE_W' in src_set)
    check('行高与原生一致（LB_SETITEMHEIGHT）', '0x01A0' in src_set)
    # 8.5 文字描边（背景透明时保证可读）
    src_w = io.open(os.path.join(ROOT, 'src', 'dingpan', 'widget.py'),
                    encoding='utf-8').read()
    check('支持文字描边（自动/始终/关闭）',
          'textOutline' in src_set and '_outline_color' in src_w)
    # 描边色：浅背景 → 深色描边；深背景 → 浅色描边
    from dingpan.widget import Theme as _Theme
    t_light = _Theme(dict(app.cfg, theme='custom', customBg='#ffffff',
                          customText='#000000'))
    t_dark = _Theme(dict(app.cfg, theme='custom', customBg='#1c1f28',
                         customText='#e6e8ef'))
    check('浅背景用深色描边', w._outline_color(t_light) == 0x00000000,
          hex(w._outline_color(t_light)))
    check('深背景用浅色描边', w._outline_color(t_dark) == 0x00FFFFFF,
          hex(w._outline_color(t_dark)))
    # 描边决策：只有背景「很透」时才自动描边。
    # ⚠️ 阈值曾经是 bg_a<200（≈背景 78% 以下就描边），
    #    半透明背景上描边看着像「重影」（用户反馈过），所以压到 bg_a<60（背景 ≤23%）。
    wcfg = dict(app.cfg)
    wcfg['theme'] = 'custom'; wcfg['customBg'] = '#ffffff'
    wcfg['customText'] = '#000000'; wcfg['columns'] = ['name', 'price']
    prev = w.cfg
    for bg, expect in ((20, True), (40, False), (100, False)):
        wcfg['bgAlpha'] = bg; wcfg['textAlpha'] = 100; wcfg['textOutline'] = 'auto'
        wcfg['bgTransparent'] = False
        w.cfg = wcfg
        w.theme = _Theme(w.cfg)
        w._cleanup_buffers()
        ok = w._paint_layered(*w.client_size(), w.eff_font_size())
        got = w.theme.outline is not None
        check('背景 %d%% 时%s描边' % (bg, '自动开启' if expect else '自动关闭'),
              got == expect, 'outline=%s' % w.theme.outline)
    wcfg['bgAlpha'] = 40; wcfg['textOutline'] = 'off'; wcfg['bgTransparent'] = False
    w.cfg = wcfg
    w.theme = _Theme(w.cfg)
    w._cleanup_buffers()
    w._paint_layered(*w.client_size(), w.eff_font_size())
    check('手动关闭描边后不描边', w.theme.outline is None, str(w.theme.outline))
    # 描边选「关闭」时**必须真的关掉**：
    # v1.0.24 曾在背景全透明时强制开描边 → 用户反馈「描边关掉了还是能看见」。
    wcfg['textOutline'] = 'off'; wcfg['bgTransparent'] = True; wcfg['bgAlpha'] = 0
    w.cfg = wcfg
    w.theme = _Theme(w.cfg)
    w._cleanup_buffers()
    w._paint_layered(*w.client_size(), w.eff_font_size())
    check('描边选「关闭」时真的不描边（不被强制开启）',
          w.theme.outline is None, str(w.theme.outline))
    wcfg['textOutline'] = 'on'
    w.cfg = wcfg
    w.theme = _Theme(w.cfg)
    w._cleanup_buffers()
    w._paint_layered(*w.client_size(), w.eff_font_size())
    check('描边选「始终开启」时描边生效',
          w.theme.outline is not None, str(w.theme.outline))
    wcfg['textOutline'] = 'off'
    wcfg['bgTransparent'] = False
    wcfg['textOutline'] = 'on'; wcfg['bgAlpha'] = 100
    w.cfg = wcfg
    w.theme = _Theme(w.cfg)
    w._cleanup_buffers()
    w._paint_layered(*w.client_size(), w.eff_font_size())
    check('手动始终开启描边（哪怕背景不透明）', w.theme.outline is not None,
          str(w.theme.outline))
    w.cfg = prev

    # ============ 9. v1.0.22：存储位置 / 退出菜单 / 描边默认关 ============
    print('\\n=== 9. 存储位置 / 退出菜单 / 描边默认值 ===')
    from dingpan import storage as _st
    # 9.1 默认配置目录 = 程序目录；备份目录 = 程序目录下的 dingpan-backups
    _st.set_path_override('config', None)
    _st.set_path_override('backup', None)
    check('默认配置目录在程序文件夹内', _st.app_dir() == _st._program_dir(),
          '%s vs %s' % (_st.app_dir(), _st._program_dir()))
    check('默认备份目录是程序目录下的 dingpan-backups',
          _st.backup_dir().endswith('dingpan-backups'), _st.backup_dir())
    # 9.2 自定义路径生效 + 指针文件能恢复
    _tmp = tempfile.mkdtemp(prefix='dpstore_t_')
    _cd = os.path.join(_tmp, 'cfg')
    _bd = os.path.join(_tmp, 'bak')
    _st.set_path_override('config', _cd)
    _st.set_path_override('backup', _bd)
    check('自定义配置目录生效', _st.app_dir() == _cd, _st.app_dir())
    check('自定义备份目录生效', _st.backup_dir() == _bd, _st.backup_dir())
    _st.save_location()
    _st.set_path_override('config', None)
    _st.set_path_override('backup', None)
    _st.load_location()
    check('指针文件能恢复自定义目录（重启后仍生效）',
          _st.app_dir() == _cd and _st.backup_dir() == _bd,
          '%s / %s' % (_st.app_dir(), _st.backup_dir()))
    _st.set_path_override('config', None)
    _st.set_path_override('backup', None)
    _st.save_location()
    # 9.3 描边默认应为 off
    from dingpan.storage import DEFAULT_CONFIG as _DC
    check('描边默认是 off（不是 auto）', _DC.get('textOutline') == 'off',
          str(_DC.get('textOutline')))
    # 9.4 悬浮窗右键菜单最下项是「退出程序」
    def _menu_labels(m):
        out = []
        n = user32.GetMenuItemCount(m)
        for i in range(n):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetMenuStringW(m, i, buf, 256, 0x0400)
            out.append(buf.value)
        return out
    mm = app._build_main_menu()
    labs = _menu_labels(mm)
    user32.DestroyMenu(mm)
    check('悬浮窗空白处菜单最下项是「退出程序」',
          labs and labs[-1] == '退出程序', repr(labs[-1] if labs else None))
    mr = app._build_row_menu(0)
    labs_r = _menu_labels(mr)
    user32.DestroyMenu(mr)
    check('行右键菜单最下项是「退出程序」',
          labs_r and labs_r[-1] == '退出程序', repr(labs_r[-1] if labs_r else None))
    # 9.5 样式页没有「背景 100%」按钮了
    src_set2 = io.open(os.path.join(ROOT, 'src', 'dingpan', 'settings.py'),
                       encoding='utf-8').read()
    check('样式页已移除「背景 100%」按钮', 'btn_bg_100' not in src_set2)
    check('两个透明度各自独占一行',
          "self._label(p, '背景不透明度', x, y)" in src_set2
          and "self._label(p, '文字不透明度', x, y)" in src_set2)
    # 9.6 存储位置 UI 存在
    check('基础设置页有存储位置输入框与浏览按钮',
          all(hasattr(obj, n) for n in ('ed_config_dir', 'ed_backup_dir',
                                        'btn_cfg_dir', 'btn_bak_dir',
                                        'btn_reset_dirs')))

    # ============ 10. v1.0.23：背景全透明 / 自动生效 / 删除 StockWidget ============
    print('\\n=== 10. 背景全透明 / 设置自动生效 / StockWidget 已删除 ===')
    # 10.1 背景完全透明：背景 alpha = 0，文字 alpha 不变
    w = app.widget
    wcfg = dict(app.cfg)
    wcfg['theme'] = 'custom'; wcfg['customBg'] = '#ffffff'
    wcfg['customText'] = '#000000'; wcfg['upColor'] = '#000000'
    wcfg['downColor'] = '#000000'; wcfg['columns'] = ['name', 'price']
    wcfg['bgAlpha'] = 100; wcfg['textAlpha'] = 100
    wcfg['bgTransparent'] = False
    prev = w.cfg
    w.cfg = wcfg
    check('未勾选时背景 alpha = 255', w._alphas()[0] == 255, str(w._alphas()))
    check('未勾选时文字 alpha = 255', w._alphas()[1] == 255, str(w._alphas()))
    wcfg['bgTransparent'] = True
    w.cfg = wcfg
    bg_a, tx_a = w._alphas()
    check('勾选「背景透明」后背景 alpha = 0（完全透明）', bg_a == 0, str(bg_a))
    check('勾选「背景透明」后文字 alpha 不受影响（仍 255）', tx_a == 255, str(tx_a))
    wcfg['bgTransparent'] = False
    w.cfg = wcfg
    w.cfg = prev
    # 10.2 复选框与滑块联动
    # v1.0.24：背景不透明度范围改成 0–100%，0% 即完全透明；
    # 滑块**永远可调**（以前勾上复选框就把滑块禁用了，
    # 用户反馈「背景透明度调整完全没用了」），复选框只是 0% 的快捷方式。
    obj._show_page(st.P_STYLE)
    pump(app, 100)
    check('样式页有「背景透明」复选框',
          hasattr(obj, 'cb_bg_transparent'))
    obj._set_bg_alpha(70, sync_check=False)
    obj._sync_bg_slider_enabled()
    pump(app, 60)
    check('背景滑块范围含 0%（0% = 完全透明）',
          obj._get_trackbar(obj.sb_bg) == 70)
    check('未全透时复选框不勾选',
          not obj._get_check(obj.cb_bg_transparent))
    check('背景滑块任何时候都可调（不会被禁用）',
          user32.IsWindowEnabled(obj.sb_bg))
    obj._set_bg_alpha(0, sync_check=False)
    obj._sync_bg_slider_enabled()
    pump(app, 60)
    check('滑块拖到 0% → 复选框自动勾上',
          obj._get_check(obj.cb_bg_transparent))
    check('滑块 0% 时依然可调',
          user32.IsWindowEnabled(obj.sb_bg))
    obj._set_bg_alpha(70, sync_check=False)
    obj._sync_bg_slider_enabled()
    pump(app, 60)
    check('滑块离开 0% → 复选框自动取消',
          not obj._get_check(obj.cb_bg_transparent))
    # 10.3 自动生效：改设置 → 自动落盘（不用点保存）
    obj._show_page(st.P_STYLE)
    pump(app, 80)
    obj._set_trackbar(obj.sb_text, 66, 20, 100)
    obj._apply_change()
    pump(app, 900)
    try:
        import json as _json
        _cfgf = os.path.join(_st.app_dir(), 'dingpan-config.json')
        with open(_cfgf, 'r', encoding='utf-8') as _f:
            _disk = _json.load(_f)
        check('设置改动自动落盘（不用点保存）',
              _disk.get('textAlpha') == 66,
              'disk textAlpha=%s' % _disk.get('textAlpha'))
    except Exception as e:  # noqa: BLE001
        check('设置改动自动落盘（不用点保存）', False, str(e))
    check('存在自动保存定时器机制', '_schedule_autosave' in src_set2)
    # 10.4 StockWidget 相关已全部删除
    _src_all = ''
    for _f in os.listdir(os.path.join(ROOT, 'src', 'dingpan')):
        if _f.endswith('.py'):
            _src_all += io.open(os.path.join(ROOT, 'src', 'dingpan', _f),
                                encoding='utf-8').read()
    check('源码里没有 StockWidget 字样',
          'StockWidget' not in _src_all and 'stockwidget' not in _src_all.lower())
    check('legacy.py 模块已删除',
          not os.path.isfile(os.path.join(ROOT, 'src', 'dingpan', 'legacy.py')))
    check('设置页没有「从原版导入」控件',
          not hasattr(obj, 'btn_legacy_detect')
          and not hasattr(obj, 'btn_legacy_import'))
    _tools_all = ''
    for _f in os.listdir(os.path.join(ROOT, 'tools')):
        # 排除本文件（断言里本身含这个词）
        if _f.endswith('.py') and _f != 'v18_check.py':
            _tools_all += io.open(os.path.join(ROOT, 'tools', _f),
                                  encoding='utf-8').read()
    check('测试里也没有 StockWidget 引用',
          'StockWidget' not in _tools_all)

    # 兜底：确认源码里没有残留的旧字段页控件
    src = io.open(os.path.join(ROOT, 'src', 'dingpan', 'settings.py'),
                  encoding='utf-8').read()
    check('旧的「可选字段/已选字段」双列表已移除',
          'lb_selected' not in src and 'lb_columns' not in src)

    app._cleanup()
    print('\n结果: %s' % ('全部通过' if not FAILS
                          else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
