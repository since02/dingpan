# -*- coding: utf-8 -*-
"""进程内渲染测试：验证「名称/代码/表头/状态栏」各种开关组合下的布局。

不截图，直接检查列方案、行高、区域高度等计算结果。
"""
import ctypes
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ⚠️ 隔离 APPDATA：测试绝不能碰用户的真实配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpwidget_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import storage                 # noqa: E402
from dingpan.widget import Widget, Theme    # noqa: E402
from dingpan.win32 import user32            # noqa: E402

FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra != '' else ''))
    if not cond:
        FAILS.append(name)


class StubApp:
    def __init__(self, cfg):
        self.cfg = cfg

    def group_index(self):
        return 0


def make_widget(cfg, w=420, h=400):
    app = StubApp(cfg)
    wd = Widget(app)
    wd.cfg = cfg
    wd.theme = Theme(cfg)
    wd.dpi_scale = 1.0
    # 造一个真实的隐藏窗口，用来量客户区尺寸
    hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
    wd.hwnd = user32.CreateWindowExW(
        0x00000080, 'STATIC', '', 0x80000000, 0, 0, w, h,
        None, None, hinst, None)
    return wd


def main():
    base = json.loads(json.dumps(storage.DEFAULT_CONFIG))
    base['groups'] = [{'id': 'g', 'name': '默认',
                        'stocks': [{'code': 'sh600519', 'name': '贵州茅台'}]}]

    print('=== 1. 列显示方案（v1.0.15 起完全以「显示字段」勾选为准）===')
    cfg = json.loads(json.dumps(base))
    cfg['columns'] = ['name', 'price', 'change']
    wd = make_widget(cfg)
    eff, mode = wd.col_plan()
    check('勾选了名称 → 有名称列', mode == 'name' and 'name' in eff,
          'mode=%s eff=%s' % (mode, eff))
    check('没勾选代码 → 不出现代码列', 'code' not in eff, str(eff))

    # 勾上「代码」→ 出现独立代码列，名称列只画名称
    cfg['columns'] = ['name', 'code', 'price']
    eff, mode = wd.col_plan()
    check('勾选代码 → 出现独立代码列', 'code' in eff, str(eff))
    check('有独立代码列时名称列只画名称（不挤两行）', mode == 'name', 'mode=%s' % mode)

    # 取消「名称」→ 只剩代码列
    cfg['columns'] = ['code', 'price']
    eff, mode = wd.col_plan()
    check('取消名称 → 名称列整体消失', mode == 'none' and 'name' not in eff, str(eff))
    check('取消名称后代码列仍在', 'code' in eff, str(eff))

    print('\n=== 2. 「代码」作为独立列 ===')
    cfg = json.loads(json.dumps(base))
    cfg['columns'] = ['name', 'code', 'price']
    wd2 = make_widget(cfg)
    eff, mode = wd2.col_plan()
    check('代码独立成列时名称列只显示名称（不重复）', mode == 'name', 'mode=%s' % mode)
    check('代码列保留', 'code' in eff, str(eff))
    # 从「显示字段」里移除「代码」→ 代码列随之消失（统一在那里设置）
    cfg['columns'] = ['name', 'price']
    eff, mode = wd2.col_plan()
    check('移除代码列 → 独立代码列也消失', 'code' not in eff, str(eff))

    # 默认配置本身就必须是「名称 + 代码」两个独立列。
    # 否则名称列会把代码挤成第二行，用户看到的还是「名称和代码显示在一起」。
    dcols = list(storage.DEFAULT_CONFIG.get('columns') or [])
    check('默认配置里名称和代码是两个独立列',
          'code' in dcols and 'name' in dcols
          and dcols.index('code') == dcols.index('name') + 1, str(dcols))
    wd_def = make_widget(json.loads(json.dumps(storage.DEFAULT_CONFIG)))
    eff_d, mode_d = wd_def.col_plan()
    check('默认配置下名称列只画名称（mode=name，不再挤成两行）',
          mode_d == 'name' and 'code' in eff_d,
          'mode=%s eff=%s' % (mode_d, eff_d))
    check('默认配置下不需要两行行高（更紧凑）',
          wd_def.name_row_two_line() is False)

    print('\n=== 2b. 列宽：代码列必须完整显示，不能被截成「sh6005…」===')
    # 背景：列宽算法原来把 code 当数值列一起压缩，
    # 400px 的默认窗口下代码只分到 51px（实际需要 60px）→ 出现省略号，
    # 「名称和代码分列」的意义就没了。
    cfg_w = json.loads(json.dumps(base))
    cfg_w['columns'] = ['name', 'code', 'price', 'change', 'changePct', 'turnover', 'time']
    cfg_w['showName'] = True
    cfg_w['showCode'] = True
    cfg_w['groups'] = [{'id': 'g', 'name': '默认', 'stocks': [
        {'code': 'sh600519', 'name': '贵州茅台'},
        {'code': 'sz000001', 'name': '平安银行'}]}]
    wd_w = make_widget(cfg_w, w=400, h=380)
    wd_w.quotes = {
        'sh600519': {'code': 'sh600519', 'name': '贵州茅台', 'price': 1688.0,
                     'change': 12.3, 'changePct': 0.74, 'turnover': 0.52,
                     'time': '2026-10-23 10:30:00'},
        'sz000001': {'code': 'sz000001', 'name': '平安银行', 'price': 11.86,
                     'change': -0.19, 'changePct': -1.58, 'turnover': 0.31,
                     'time': '2026-10-23 10:30:00'},
    }
    eff_w, _ = wd_w.col_plan()
    widths_w = wd_w.column_widths(400)
    idx_code = eff_w.index('code')
    hdc_w = user32.GetDC(wd_w.hwnd)
    small_w = wd_w.font(max(10, wd_w.eff_font_size() - 2))
    need_code = wd_w._text_px(hdc_w, 'sh600519', small_w)
    # 右对齐列用 max_w = cw-6，所以可用文字宽 = 列宽 - 6
    check('默认窗口宽度下代码列能完整显示（无省略号）',
          widths_w[idx_code] - 6 >= need_code,
          '列宽 %d，可用 %d，需要 %d' % (widths_w[idx_code], widths_w[idx_code] - 6, need_code))
    check('所有列宽加起来不超出窗口',
          sum(widths_w) <= 400 - 12, '合计 %d / 可用 %d' % (sum(widths_w), 400 - 12))
    check('名称列拿到富余空间（列序打乱也一样）',
          widths_w[eff_w.index('name')] >= 60,
          str(widths_w))
    # 时间列只显示「时:分」，不该被截成「10:30…」
    idx_time = eff_w.index('time')
    need_time = wd_w._text_px(hdc_w, '10:30', small_w)
    check('时间列能完整显示「时:分」',
          widths_w[idx_time] - 6 >= need_time,
          '列宽 %d，需要 %d' % (widths_w[idx_time], need_time))
    # 列序打乱后，富余仍应给名称列
    cfg_r = json.loads(json.dumps(cfg_w))
    cfg_r['columns'] = ['code', 'name', 'price']
    wd_r = make_widget(cfg_r, w=400, h=380)
    eff_r, _ = wd_r.col_plan()
    wr = wd_r.column_widths(400)
    check('重排列序后富余仍给名称列（不是固定第 0 列）',
          wr[eff_r.index('name')] > wr[eff_r.index('code')],
          dict(zip(eff_r, wr)))
    user32.ReleaseDC(wd_w.hwnd, hdc_w)

    print('\n=== 3. 行高与名称字符数 ===')
    cfg = json.loads(json.dumps(base))
    cfg['columns'] = ['name', 'code', 'price']
    wd3 = make_widget(cfg)
    wd3.layout()
    one_h = wd3.row_h
    check('独立代码列 → 单行行高（更紧凑）', not wd3.name_row_two_line(),
          'row_h=%s' % one_h)
    check('行高不小于字号', one_h >= wd3.eff_font_size(), 'row_h=%s' % one_h)

    # 名称最多显示几个字符（0 = 全部）
    check('nameChars=0 → 名称完整显示',
          wd3.name_display_text('贵州茅台') == '贵州茅台')
    cfg['nameChars'] = 2
    wd3.cfg = cfg
    check('nameChars=2 → 只显示前 2 个字 + 省略号',
          wd3.name_display_text('贵州茅台') == '贵州…',
          wd3.name_display_text('贵州茅台'))
    cfg['nameChars'] = 9
    wd3.cfg = cfg
    check('nameChars 超过名称长度 → 不截断',
          wd3.name_display_text('贵州茅台') == '贵州茅台')
    cfg['nameChars'] = 0
    wd3.cfg = cfg

    print('\n=== 4. 表头 / 状态栏 独立隐藏 ===')
    cfg = json.loads(json.dumps(base))
    cfg['showTableHead'] = True
    cfg['showStatus'] = True
    wd4 = make_widget(cfg, 420, 400)
    wd4.layout()
    h_with = (wd4.header_h, wd4.tabs_h, wd4.status_h, wd4.head_h)
    check('都显示时表头/状态栏有高度', h_with[2] > 0 and h_with[3] > 0, str(h_with))

    cfg['showStatus'] = False
    wd4.cfg = cfg
    wd4.layout()
    check('关掉状态栏 → 状态栏高度为 0', wd4.status_h == 0, str(wd4.status_h))
    check('关掉状态栏 → 底部区域让给数据区',
          wd4.body_bottom == 400, 'body_bottom=%s' % wd4.body_bottom)

    cfg['showTableHead'] = False
    wd4.cfg = cfg
    wd4.layout()
    check('关掉表头 → 表头高度为 0', wd4.head_h == 0, str(wd4.head_h))

    cfg['showHeader'] = False
    wd4.cfg = cfg
    wd4.layout()
    check('关掉标题栏 → 标题栏/标签栏都为 0',
          wd4.header_h == 0 and wd4.tabs_h == 0, '%s %s' % (wd4.header_h, wd4.tabs_h))

    print('\n=== 5b. 尺寸按内容自适应 ===')
    cfg_s = json.loads(json.dumps(base))
    cfg_s['columns'] = ['name', 'code', 'price', 'change', 'changePct', 'turnover', 'time']
    cfg_s['groups'] = [{'id': 'g', 'name': '默认', 'stocks': [
        {'code': 'sh600519', 'name': '贵州茅台'},
        {'code': 'sz000001', 'name': '平安银行'}]}]
    wd_s = make_widget(cfg_s, w=400, h=380)
    wd_s.quotes = {
        'sh600519': {'code': 'sh600519', 'name': '贵州茅台', 'price': 1688.0,
                     'change': 12.3, 'changePct': 0.74, 'turnover': 0.52,
                     'time': '2026-10-23 10:30:00'},
        'sz000001': {'code': 'sz000001', 'name': '平安银行', 'price': 11.86,
                     'change': -0.19, 'changePct': -1.58, 'turnover': 0.31,
                     'time': '2026-10-23 10:30:00'},
    }
    need_w, need_h = wd_s.needed_size()
    check('能算出所需尺寸', need_w > 0 and need_h > 0, '%dx%d' % (need_w, need_h))
    check('所需宽度 = 各列自然宽度之和 + 内边距',
          need_w == max(220, min(wd_s.content_width(), 1600)),
          'need=%d content=%d' % (need_w, wd_s.content_width()))
    # 股票越多窗口越高
    cfg_s['groups'][0]['stocks'].append({'code': 'sz300750', 'name': '宁德时代'})
    wd_s.cfg = cfg_s
    _, h3 = wd_s.needed_size()
    check('股票变多 → 所需高度变大', h3 > need_h, '%d → %d' % (need_h, h3))
    # 字段变少 → 所需宽度变小
    cfg_s['columns'] = ['name', 'price']
    wd_s.cfg = cfg_s
    w2, _ = wd_s.needed_size()
    check('字段变少 → 所需宽度变小', w2 < need_w, '%d → %d' % (need_w, w2))
    if wd_s.hwnd:
        user32.DestroyWindow(wd_s.hwnd)

    print('\n=== 6. 高度分配不重叠 ===')
    cfg = json.loads(json.dumps(base))
    for combo in itertools_combos():
        c = json.loads(json.dumps(base))
        c.update(combo)
        w = make_widget(c, 420, 300)
        w.layout()
        used = w.header_h + w.tabs_h + w.head_h + w.status_h
        check('组合 %s 各区不重叠' % combo, w.body_h > 0 and used <= 300,
              'used=%s body=%s' % (used, w.body_h))
        if w.hwnd:
            user32.DestroyWindow(w.hwnd)

    for w in (wd, wd2, wd3, wd4):
        if w.hwnd:
            user32.DestroyWindow(w.hwnd)

    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


def itertools_combos():
    """表头 / 状态栏的开关组合（名称与代码由「显示字段」决定，不在这里组合）"""
    out = []
    for th in (True, False):
        for st in (True, False):
            out.append({'showTableHead': th, 'showStatus': st})
    return out


if __name__ == '__main__':
    sys.exit(main())
