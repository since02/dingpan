# -*- coding: utf-8 -*-
"""进程内 UI 单元测试：真实创建设置窗口，直接调用方法验证「分组 -> 股票列表」联动。

不依赖鼠标、不依赖命令行进程，避免桌面 z-order / DPI 干扰。
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ⚠️ 隔离 APPDATA：测试绝不能碰用户的真实配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpuiuni_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import settings as st          # noqa: E402
from dingpan.win32 import user32            # noqa: E402

LB_GETCOUNT = 0x018B
LB_GETTEXT = 0x0189
LB_SETCURSEL = 0x0186
LB_GETCURSEL = 0x0188

GROUPS = [
    {'id': 'g_a', 'name': '短线', 'stocks': [{'code': 'sh600519', 'name': '贵州茅台'},
                                            {'code': 'sz000001', 'name': '平安银行'}]},
    {'id': 'g_b', 'name': '中线', 'stocks': [{'code': 'sz300750', 'name': '宁德时代'},
                                            {'code': 'sh601318', 'name': '中国平安'},
                                            {'code': 'sz002594', 'name': '比亚迪'}]},
    {'id': 'g_c', 'name': '观察', 'stocks': [{'code': 'bj430047', 'name': '诺思兰德'}]},
]

FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + extra) if extra else ''))
    if not cond:
        FAILS.append(name)


class StubApp:
    def __init__(self, cfg):
        self.cfg = cfg
        self.settings_hwnd = None
        self.hwnd = None
        self.saved = 0

    def group_index(self):
        for i, g in enumerate(self.cfg.get('groups') or []):
            if g.get('id') == self.cfg.get('activeGroupId'):
                return i
        return 0

    def set_group(self, i):
        groups = self.cfg.get('groups') or []
        if not groups:
            return
        i %= len(groups)
        self.cfg['activeGroupId'] = groups[i]['id']
        self.saved += 1


def _children(hwnd):
    """返回 (hwnd, 类名, 文本, 是否可见, 客户区 x1,y1,x2,y2) 列表"""
    out = []
    user32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    class PT(ctypes.Structure):
        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hh, _l):
        cls = ctypes.create_unicode_buffer(48)
        user32.GetClassNameW(hh, cls, 48)
        txt = ctypes.create_unicode_buffer(60)
        user32.GetWindowTextW(hh, txt, 60)
        r = ctypes.wintypes.RECT()
        user32.GetWindowRect(hh, ctypes.byref(r))
        p1 = PT(r.left, r.top)
        p2 = PT(r.right, r.bottom)
        user32.ScreenToClient(hwnd, ctypes.byref(p1))
        user32.ScreenToClient(hwnd, ctypes.byref(p2))
        out.append((int(hh), cls.value, txt.value, bool(user32.IsWindowVisible(hh)),
                    p1.x, p1.y, p2.x, p2.y))
        return True
    user32.EnumChildWindows(hwnd, cb, 0)
    return out


def lb_items(lb):
    n = user32.SendMessageW(lb, LB_GETCOUNT, 0, 0)
    out = []
    for i in range(n):
        buf = ctypes.create_unicode_buffer(200)
        user32.SendMessageW(lb, LB_GETTEXT, i, ctypes.addressof(buf))
        out.append(buf.value)
    return out


def main():
    cfg = st.storage.default_config() if hasattr(st.storage, 'default_config') else None
    import json
    cfg = json.loads(json.dumps(st.storage.DEFAULT_CONFIG))
    cfg['groups'] = json.loads(json.dumps(GROUPS))
    cfg['activeGroupId'] = 'g_a'
    cfg['fontSize'] = 13
    cfg['bgAlpha'] = 95
    cfg['textAlpha'] = 80
    cfg['customBg'] = '#203040'
    cfg['columns'] = ['name', 'price', 'change', 'changePct', 'turnover', 'time']

    app = StubApp(cfg)
    win = st.SettingsWindow(app)
    print('创建设置窗口…')
    win._create()
    try:
        print('\n=== 自选管理页 ===')
        win._show_page(st.P_STOCKS)
        groups = lb_items(win.lb_groups)
        stocks = lb_items(win.lb_stocks)
        check('分组列表已填充', len(groups) == 3, str(groups))
        check('当前分组有 ● 标记', groups and groups[0].startswith('●'), groups[0] if groups else '')
        check('初始股票列表已填充', len(stocks) == 2, str(stocks))

        print('\n=== 切换分组（模拟 LBN_SELCHANGE）===')
        for i, g in enumerate(GROUPS):
            user32.SendMessageW(win.lb_groups, LB_SETCURSEL, i, 0)
            win._on_command(0, win.lb_groups, 1)   # code=1 即 LBN_SELCHANGE
            items = lb_items(win.lb_stocks)
            want = [s['code'] for s in g['stocks']]
            # 列表项文本 = 「[√] 代码 名称」，取第 2 段是代码
            got = [it.split()[1] if len(it.split()) > 1 else '' for it in items]
            check('切到「%s」列表跟随' % g['name'], got == want, '%s' % items)
            check('  列表项带显示/隐藏标记',
                  all(it.startswith('[') for it in items), '%s' % items[:2])
            check('  活动分组已切换', app.cfg['activeGroupId'] == g['id'],
                  app.cfg['activeGroupId'])

        print('\n=== 遮挡检查（内容区不应有透明大容器盖住控件）===')
        win._show_page(st.P_STOCKS)
        suspects = []
        for hh, cls, txt, vis, x1, y1, x2, y2 in _children(win.hwnd):
            if vis and cls == 'Static' and not txt and (x2 - x1) > 200 and x1 >= st.SIDEBAR_W - 10:
                suspects.append((cls, x1, y1, x2 - x1, y2 - y1))
        check('内容区无大容器遮挡', not suspects, str(suspects))
        check('content 容器已移除', getattr(win, 'content', None) is None)

        print('\n=== 滑块初值（TBM_GETPOS 必须是配置里的 95 / 80 / 13）===')
        check('背景透明度滑块停在 95', int(win._get_trackbar(win.sb_bg)) == 95,
              '实际 %s' % win._get_trackbar(win.sb_bg))
        check('文字透明度滑块停在 80', int(win._get_trackbar(win.sb_text)) == 80,
              '实际 %s' % win._get_trackbar(win.sb_text))
        # 字号已改成下拉框：Windows 滑块的自动刻度会被稀疏化，
        # 10~20 之间只能点中 11/13/15 一类的中间值，选不到 12/14。
        check('字号下拉框停在 13', win._font_size_now() == 13,
              '实际 %s' % win._font_size_now())
        check('字号下拉框列出 10~20 全部可选',
              win._combo_items(win.cb_font) == [str(v) for v in range(10, 21)],
              str(win._combo_items(win.cb_font)))
        check('背景色按钮显示配置色', win._get_text(win.btn_bg_color) == '#203040',
              win._get_text(win.btn_bg_color))
        check('快捷键行数与配置一致', len(win.hk_rows) == 4, '%d 行' % len(win.hk_rows))
        check('快捷键勾选框默认勾选', win._get_check(win.hk_rows[0][1]))

        print('\n=== 保存数据回环（_collect 读回的值必须与配置一致）===')
        got = win._collect()
        check('字号未跑偏', int(got.get('fontSize')) == 13, 'fontSize=%s' % got.get('fontSize'))
        check('背景透明度未跑偏', int(got.get('bgAlpha')) == 95, 'bgAlpha=%s' % got.get('bgAlpha'))
        check('文字透明度未跑偏', int(got.get('textAlpha')) == 80, 'textAlpha=%s' % got.get('textAlpha'))
        check('自定义底色未跑偏', got.get('customBg') == '#203040', got.get('customBg'))
        check('快捷键启用状态已保存', isinstance(got.get('hotkeyEnabled'), dict),
              str(got.get('hotkeyEnabled')))
        check('显示字段未丢失', len(got.get('columns') or []) == 6, str(got.get('columns')))
        check('分组未被改写', len(got.get('groups') or []) == 3,
              str([g.get('name') for g in got.get('groups') or []]))

        print('\n=== 各页面控件数量 ===')
        for pid, name in [(0, '基础设置'), (1, '自选管理'), (2, '显示字段'), (3, '样式外观'),
                          (4, '备份恢复'), (5, 'WebDAV'), (6, '快捷键'), (7, '关于')]:
            win._show_page(pid)
            visible = 0
            for key, hs in win.page_keys.items():
                if key != {0: 'basic', 1: 'stocks', 2: 'columns', 3: 'style',
                           4: 'backup', 5: 'dav', 6: 'hotkeys', 7: 'about'}[pid]:
                    continue
                for h in hs:
                    if user32.IsWindowVisible(h):
                        visible += 1
            check('%s 页有内容' % name, visible >= 3, '%d 个控件' % visible)
    finally:
        win._dying = True
        user32.DestroyWindow(win.hwnd)
        try:
            user32.UnregisterClassW('DingPanSettings', None)
        except Exception:
            pass

    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项: %s' % (len(FAILS), FAILS)))
    return 0 if not FAILS else 1


if __name__ == '__main__':
    sys.exit(main())
