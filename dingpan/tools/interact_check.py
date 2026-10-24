# -*- coding: utf-8 -*-
"""进程内行为测试：真实创建设置窗口，直接发消息验证「点了会不会跳页」。

不依赖鼠标、不截图，直接向窗口发 WM_COMMAND / WM_LBUTTONDBLCLK 等消息，
验证用户报告的每一个交互问题。
"""
import ctypes
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ⚠️ 隔离 APPDATA：测试绝不能碰用户的真实配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpintera_')

from dingpan import settings as st          # noqa: E402
from dingpan import storage                 # noqa: E402
from dingpan.win32 import user32, gdi32     # noqa: E402

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
        self._settings_obj = None
        self.saved = 0
        self.group_calls = []

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
        self.group_calls.append(i)

    def save_cfg(self, cfg=None, sync=True):
        if cfg is not None:
            self.cfg = cfg
        self.saved += 1

    def widget(self):
        return None


def lb_items(lb):
    n = user32.SendMessageW(lb, 0x018B, 0, 0)
    out = []
    for i in range(n):
        buf = ctypes.create_unicode_buffer(200)
        user32.SendMessageW(lb, 0x0189, i, ctypes.addressof(buf))
        out.append(buf.value)
    return out


def lb_set_sel(lb, idx):
    user32.SendMessageW(lb, 0x0186, idx, 0)


def lb_get_sel(lb):
    return user32.SendMessageW(lb, 0x0188, 0, 0)


def _text_of(hwnd):
    buf = ctypes.create_unicode_buffer(300)
    user32.GetWindowTextW(hwnd, buf, 300)
    return buf.value


def send_command(hwnd, cid, code=0):
    """模拟一次控件通知（BN_CLICKED=0 / LBN_SELCHANGE=1）"""
    wparam = (code << 16) | (cid & 0xFFFF)
    user32.SendMessageW(hwnd, 0x0111, wparam, 0)


def main():
    cfg = json.loads(json.dumps(storage.DEFAULT_CONFIG))
    cfg['groups'] = [{'id': 'g_a', 'name': '短线',
                      'stocks': [{'code': 'sh600519', 'name': '贵州茅台'}]}]
    cfg['activeGroupId'] = 'g_a'

    app = StubApp(cfg)
    win = st.SettingsWindow(app)
    print('创建设置窗口…')
    win._create()
    hwnd = win.hwnd
    try:
        print('\n=== 1. 页面切换（点导航按钮）===')
        for pid, label in st.PAGES:
            win._show_page(pid)
            check('切到「%s」页' % label, win.page == pid, 'page=%s' % win.page)

        print('\n=== 2. 显示字段页：点列表项不能跳页（用户报告的主 bug）===')
        win._show_page(st.P_COLUMNS)
        check('当前在显示字段页', win.page == st.P_COLUMNS)
        # 模拟用户在「可选字段」列表里点一项（LBN_SELCHANGE）
        send_command(hwnd, 3001, 1)   # 自动分配的列表框 ID
        check('点列表项后仍停在显示字段页', win.page == st.P_COLUMNS,
              'page=%s' % win.page)
        # 显式用真实控件句柄发通知
        for h in (win.lb_fields,):
            cid = user32.GetDlgCtrlID(h) if hasattr(user32, 'GetDlgCtrlID') else 0
            if cid:
                send_command(hwnd, cid, 1)
        check('用真实 ID 发列表通知后仍在显示字段页', win.page == st.P_COLUMNS,
              'page=%s' % win.page)

        print('\n=== 3. 显示字段页：勾选显示/隐藏 + 拖动排序 ===')
        win._show_page(st.P_COLUMNS)
        n_all = len(lb_items(win.lb_fields))
        check('字段列表列出全部可选字段', n_all == len(st.COLUMN_DEFS),
              '%d 项' % n_all)
        check('每项都带 [√]/[  ] 勾选标记',
              all(it.startswith('[') for it in lb_items(win.lb_fields)),
              str(lb_items(win.lb_fields)[:2]))
        # 找一个当前**没勾选**的字段，取消/勾选它
        idx_off = None
        for i, it in enumerate(lb_items(win.lb_fields)):
            if not it.startswith(st.FIELD_MARK_ON):
                idx_off = i
                break
        check('存在未勾选的字段', idx_off is not None)
        if idx_off is not None:
            key = win._field_order[idx_off]
            win._toggle_field_enabled(idx_off)
            check('点 [√] 后该字段被勾上', key in win._get_selected_columns(),
                  str(win._get_selected_columns()))
            win._toggle_field_enabled(idx_off)
            check('再点一次取消勾选（字段没被删掉）', key not in win._get_selected_columns()
                  and len(lb_items(win.lb_fields)) == n_all,
                  '%d 项' % len(lb_items(win.lb_fields)))
        # 拖动排序：把第 0 项拖到第 2 项
        order0 = list(win._field_order)
        win._move_field_row(0, 2)
        # 把第 0 项挪到第 2 位 → 变成 [1, 2, 0]
        check('拖动后顺序改变', win._field_order[:3] == [order0[1], order0[2], order0[0]],
              str(win._field_order[:3]))
        check('拖动后列表内容同步', lb_items(win.lb_fields)[2].endswith(
            st.COLUMN_MAP[order0[0]][1]), str(lb_items(win.lb_fields)[:3]))
        check('拖动后已选字段顺序也跟着变',
              win._get_selected_columns()[:2] == [order0[1], order0[2]],
              str(win._get_selected_columns()[:3]))
        check('完整顺序被记住（含未勾选字段）',
              len(win.app.cfg.get('fieldOrder') or []) == len(st.COLUMN_DEFS),
              str(len(win.app.cfg.get('fieldOrder') or [])))

        print('\n=== 4. 收集配置：表头/状态栏开关 + 名称/代码由显示字段决定 ===')
        win._show_page(st.P_BASIC)
        win._set_check(win.cb_table_head, False)
        win._set_check(win.cb_status, False)
        win._set_check(win.cb_header, True)
        # 名称 / 代码不再有独立开关，改由「显示字段」的勾选决定
        # 只留「名称」「现价」两个字段勾上
        win.app.cfg['columns'] = ['name', 'price']
        win._fill_field_list()
        got = win._collect()
        check('showName 跟随「显示字段」里有没有名称列', got.get('showName') is True,
              str(got.get('showName')))
        check('showCode 跟随「显示字段」里有没有代码列', got.get('showCode') is False,
              str(got.get('showCode')))
        check('showTableHead 已保存为 False', got.get('showTableHead') is False)
        check('showStatus 已保存为 False', got.get('showStatus') is False)
        check('showHeader 已保存为 True', got.get('showHeader') is True)

        print('\n=== 5. 重新打开设置窗不能出错（用户报告：保存后再打开就挂）===')
        # 模拟「关掉再打开」：销毁窗口后用同一个实例再 show
        user32.DestroyWindow(hwnd)
        check('销毁后 hwnd 已清空', win.hwnd is None)
        win.show()
        check('重新打开成功', bool(win.hwnd) and user32.IsWindow(win.hwnd))
        check('重开后控件句柄有效', bool(user32.IsWindow(win.lb_fields)))
        check('重开后能切页', (win._show_page(st.P_COLUMNS), win.page == st.P_COLUMNS)[1])
        # 再来一次
        user32.DestroyWindow(win.hwnd)
        win.show()
        check('第三次打开也成功', bool(win.hwnd) and user32.IsWindow(win.hwnd))

        print('\n=== 6. 新实例不会互相抢窗口过程 ====')
        win2 = st.SettingsWindow(app)
        win2._create()
        try:
            check('新实例能创建设置窗', bool(win2.hwnd))
            win2._show_page(st.P_STYLE)
            check('新实例切页正常', win2.page == st.P_STYLE)
            # 老实例仍然可用
            win._show_page(st.P_COLUMNS)
            check('老实例仍能切页（没被新实例抢走）', win.page == st.P_COLUMNS)
        finally:
            if win2.hwnd:
                user32.DestroyWindow(win2.hwnd)
    finally:
        if win.hwnd:
            user32.DestroyWindow(win.hwnd)

    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
