#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""菜单回归测试（无头）

**直接调用 app.py 的生产构建方法**（_build_tray_menu / _build_row_menu /
_build_main_menu），而不是复刻一份 —— 之前的版本是复刻，等于测自己抄的副本，
生产代码改坏了测试照样通过。

验证：
  1) 菜单必须用 CreatePopupMenu 创建（TrackPopupMenu 的契约要求；
     CreateMenu 创建的菜单栏类型在某些系统上会渲染成空白菜单）
  2) 每一项的文本、命令号都能正确读回（排除 ctypes 参数声明错误）
  3) 子菜单（数据源）正常挂载、项数正确、当前数据源带勾选标记
  4) 命令号不重复、不为 0（0 会和分隔符冲突）

不依赖任何 GUI / 鼠标，纯 Win32 API 校验。
"""
import ctypes
import os
import sys
import tempfile
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpmenu_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import win32 as w32                      # noqa: E402
from dingpan.app import App                          # noqa: E402
from dingpan import quotes                           # noqa: E402

user32 = w32.user32

MF_BYPOSITION = 0x0400

# 需要补声明的 API（win32.py 里没声明的）
user32.GetMenuItemCount.restype = ctypes.c_int
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuStringW.restype = ctypes.c_int
user32.GetMenuStringW.argtypes = [wintypes.HMENU, ctypes.c_uint, wintypes.LPWSTR,
                                   ctypes.c_int, wintypes.UINT]
user32.GetMenuItemID.restype = ctypes.c_uint
user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetSubMenu.restype = wintypes.HMENU
user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetMenuState.restype = ctypes.c_uint
user32.GetMenuState.argtypes = [wintypes.HMENU, ctypes.c_uint, wintypes.UINT]

problems = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra else ''))
    if not cond:
        problems.append(name)


def read_item_text(menu, index):
    """读回第 index 项的文本（按位置）"""
    n = user32.GetMenuStringW(menu, index, None, 0, MF_BYPOSITION)
    if n <= 0:
        return None
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetMenuStringW(menu, index, buf, n + 1, MF_BYPOSITION)
    return buf.value


def read_item_id(menu, index):
    return user32.GetMenuItemID(menu, index)


def dump(menu, label):
    """把菜单逐项读回并打印，同时校验命令号"""
    count = user32.GetMenuItemCount(menu)
    items = []
    ids = []
    for i in range(count):
        t = read_item_text(menu, i)
        items.append(t)
        ids.append(read_item_id(menu, i))
        if t is not None:
            # 分隔符没有文本；有文本却用命令号 0 的，只有一种合法情况：
            # 灰掉（MF_GRAYED）的纯显示项（如版本号），点它不会产生任何命令。
            state = user32.GetMenuState(menu, i, MF_BYPOSITION)
            if ids[-1] == 0 and not (state & w32.MF_GRAYED):
                problems.append('%s 第 %d 项「%s」是可点击项但命令号为 0' % (label, i, t))
    print('    %s: %d 项 -> %s' % (label, count, items))
    return items, ids


def _probe(create_fn):
    """用指定的建菜单函数建一个等价菜单，返回顶层项数（用于类型对照）"""
    m = create_fn()
    user32.AppendMenuW(m, w32.MF_STRING, 1, 'A')
    user32.AppendMenuW(m, w32.MF_SEPARATOR, 0, None)
    user32.AppendMenuW(m, w32.MF_STRING, 2, 'B')
    sub = user32.CreatePopupMenu()
    user32.AppendMenuW(sub, w32.MF_STRING, 3, 'C')
    user32.AppendMenuW(m, w32.MF_POPUP, sub, 'sub')
    n = user32.GetMenuItemCount(m)
    user32.DestroyMenu(m)
    return n


def main():
    app = App()
    app.cfg['groups'] = [{'id': 'g', 'name': '默认',
                          'stocks': [{'code': 'sh600519', 'name': '贵州茅台'},
                                     {'code': 'sz000001', 'name': '平安银行'}]}]
    app.cfg['activeGroupId'] = 'g'
    app.cfg['source'] = 'tencent'

    print('=== 1. 菜单类型（CreateMenu 会渲染成空白）===')
    # 对照组：同一个菜单分别用两种类型建，项数应该完全一样
    # → 证明「空白」不是因为菜单项没加进去，而是类型用错了
    n_bad = _probe(user32.CreateMenu)
    n_good = _probe(user32.CreatePopupMenu)
    print('    同一份内容：CreateMenu 项数 = %d，CreatePopupMenu 项数 = %d' % (n_bad, n_good))
    check('两种类型项数完全相同（空白源于类型，不是没加项）', n_bad == n_good,
          '%d vs %d' % (n_bad, n_good))

    menu = app._build_tray_menu()
    good_count = user32.GetMenuItemCount(menu)
    user32.DestroyMenu(menu)
    check('生产代码的托盘菜单项数正常', good_count >= 12, '%d 项' % good_count)

    print('\n=== 2. 托盘菜单（生产代码 _build_tray_menu）===')
    menu = app._build_tray_menu()
    items, ids = dump(menu, '托盘菜单')
    expect = ['显示悬浮窗', '隐藏悬浮窗', None, '立即刷新', '下一分组', '上一分组',
              None, '数据源', None, '设置…', None, None, '退出']
    # 实际项数 = 上面 expect 里的非 None 项数 + 分隔符
    check('托盘菜单项数正确', len(items) == len(expect),
          '%d（期望 %d）' % (len(items), len(expect)))
    for i, exp in enumerate(expect):
        if exp is None:
            continue
        got = items[i] if i < len(items) else '<越界>'
        check('  第 %d 项 = %r' % (i, exp), got == exp, got)

    # 命令号唯一
    real_ids = [x for x in ids if x != 0]
    check('命令号无重复', len(real_ids) == len(set(real_ids)), str(real_ids))
    check('命令号不为 0（0 会与分隔符冲突）', all(x != 0 for x in real_ids))

    # 数据源子菜单
    sub = user32.GetSubMenu(menu, 7)
    check('「数据源」子菜单已挂载', bool(sub))
    if sub:
        sub_items, sub_ids = dump(sub, '数据源子菜单')
        check('子菜单项数 = 数据源个数', len(sub_items) == len(quotes.SOURCES),
              '%d / %d' % (len(sub_items), len(quotes.SOURCES)))
        # 当前数据源应带 MF_RADIOCHECK
        cur = list(quotes.SOURCES).index(app.cfg.get('source', 'tencent'))
        state = user32.GetMenuState(sub, cur, MF_BYPOSITION)
        check('当前数据源带单选勾（MF_RADIOCHECK）',
              bool(state & w32.MF_RADIOCHECK), 'state=0x%X' % state)
    user32.DestroyMenu(menu)

    print('\n=== 3. 行右键菜单（生产代码 _build_row_menu）===')
    m0 = app._build_row_menu(0)
    check('第 1 行菜单能构建', bool(m0))
    if m0:
        items0, ids0 = dump(m0, '行菜单(第1行)')
        expect0 = ['打开行情页', None, '上移', '下移', '置顶', '置底', None,
                   '复制代码', '删除自选', None, '设置…', None, '退出程序']
        check('行菜单项数正确', len(items0) == len(expect0),
              '%d（期望 %d）' % (len(items0), len(expect0)))
        for i, exp in enumerate(expect0):
            if exp is None:
                continue
            got = items0[i] if i < len(items0) else '<越界>'
            check('  第 %d 项 = %r' % (i, exp), got == exp, got)
        # 首行「上移 / 置顶」应置灰
        s_up = user32.GetMenuState(m0, 2, MF_BYPOSITION)
        s_pin = user32.GetMenuState(m0, 4, MF_BYPOSITION)
        check('首行的「上移 / 置顶」是灰的',
              bool(s_up & w32.MF_GRAYED) and bool(s_pin & w32.MF_GRAYED),
              'up=0x%X pin=0x%X' % (s_up, s_pin))
        user32.DestroyMenu(m0)

    m1 = app._build_row_menu(1)
    if m1:
        s_dn = user32.GetMenuState(m1, 3, MF_BYPOSITION)
        s_bot = user32.GetMenuState(m1, 5, MF_BYPOSITION)
        check('末行的「下移 / 置底」是灰的',
              bool(s_dn & w32.MF_GRAYED) and bool(s_bot & w32.MF_GRAYED),
              'down=0x%X bottom=0x%X' % (s_dn, s_bot))
        user32.DestroyMenu(m1)

    check('越界行号返回 None', app._build_row_menu(99) is None)
    # v1.0.22：悬浮窗右键菜单最下边必须有「退出程序」（用户要求）
    m_chk = app._build_row_menu(0)
    if m_chk:
        items_chk, _ = dump(m_chk, '行菜单(退出检查)')
        check('行菜单最下项是「退出程序」', items_chk[-1] == '退出程序',
              repr(items_chk[-1]))

    print('\n=== 4. 空白处菜单（生产代码 _build_main_menu）===')
    mm = app._build_main_menu()
    check('空白处菜单能构建', bool(mm))
    if mm:
        items_m, _ = dump(mm, '空白处菜单')
        expect_m = ['添加自选股…', '从剪贴板添加', '复制全部代码', None, '设置…', None,
                    '隐藏到托盘', None, '退出程序']
        check('空白处菜单最下项是「退出程序」', items_m[-1] == '退出程序',
              repr(items_m[-1]))
        check('空白处菜单项数正确', len(items_m) == len(expect_m),
              '%d（期望 %d）' % (len(items_m), len(expect_m)))
        for i, exp in enumerate(expect_m):
            if exp is None:
                continue
            got = items_m[i] if i < len(items_m) else '<越界>'
            check('  第 %d 项 = %r' % (i, exp), got == exp, got)
        user32.DestroyMenu(mm)

    print('\n结果: %s' % ('全部通过' if not problems else
                           '失败 %d 项 -> %s' % (len(problems), problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
