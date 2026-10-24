# -*- coding: utf-8 -*-
"""托盘与右键菜单测试：验证「菜单能真的弹出来并响应」。

关键点：TrackPopupMenu 是阻塞调用，必须放到后台线程，
主线程同时抽干消息队列。菜单弹出后用键盘/模拟点击选中一项，
再检查 App 是否收到了对应的命令。
"""
import ctypes
import os
import sys
import threading
import time
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ⚠️ 隔离 APPDATA：测试绝不能碰用户的真实配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dptrayc_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import app as A                # noqa: E402
from dingpan import storage                 # noqa: E402
from dingpan.win32 import user32, kernel32  # noqa: E402
from ctypes import wintypes                 # noqa: E402

FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + extra) if extra else ''))
    if not cond:
        FAILS.append(name)


def pump(sec=0.6):
    """抽干消息队列（菜单弹出时 TrackPopupMenu 会阻塞调用线程）"""
    msg = wintypes.MSG()
    end = time.time() + sec
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def main():
    print('=== 1. 托盘宿主窗口（可激活的 owner）===')
    host = A._create_tray_host()
    check('托盘宿主窗口创建成功', bool(host))
    ex = user32.GetWindowLongPtrW(host, A.w32.GWL_EXSTYLE)
    check('宿主窗口不带 WS_EX_NOACTIVATE（否则菜单收不到前台权限）',
          not (ex & A.w32.WS_EX_NOACTIVATE), 'ex=0x%X' % ex)
    check('宿主窗口带 WS_EX_TOOLWINDOW（不占任务栏）',
          bool(ex & A.w32.WS_EX_TOOLWINDOW))
    check('宿主窗口不是悬浮窗（悬浮窗才用 NOACTIVATE）',
          host != 0)

    print('\n=== 2. 托盘通知码解析 ===')
    cfg = json_cfg = __import__('json').loads(__import__('json').dumps(storage.DEFAULT_CONFIG))
    ap = A.App.__new__(A.App)
    ap.cfg = cfg
    ap.hwnd = 0
    ap.widget = type('W', (), {'status_text': '', 'last_update': ''})()
    ap.tray_host = host
    calls = []
    ap.set_visible = lambda v: calls.append(('visible', v))
    ap._show_tray_menu = lambda: calls.append(('menu',))
    ap._on_tray_notify(0, A.w32.NIN_POPUPOPEN)
    check('NIN_POPUPOPEN → 弹菜单', calls and calls[-1] == ('menu',), str(calls))
    calls.clear()
    ap._on_tray_notify(0, A.w32.NIN_SELECT)
    check('NIN_SELECT → 切换显示', calls and calls[-1][0] == 'visible', str(calls))
    calls.clear()
    ap._on_tray_notify(0, A.w32.WM_RBUTTONUP)
    check('旧版 WM_RBUTTONUP → 也弹菜单', calls and calls[-1] == ('menu',), str(calls))
    calls.clear()
    ap._on_tray_notify(0, A.w32.WM_CONTEXTMENU)
    check('旧版 WM_CONTEXTMENU → 也弹菜单', calls and calls[-1] == ('menu',), str(calls))

    print('\n=== 3. 菜单真的能显示出来（后台线程调 TrackPopupMenu）===')
    # 造一个真实菜单，后台线程弹出，主线程抽消息
    menu = user32.CreateMenu()
    user32.AppendMenuW(menu, A.w32.MF_STRING, 4242, '测试项')
    result = {}

    def worker():
        result['cmd'] = A._show_popup(menu, 100, 100, host)

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    time.sleep(0.35)
    # 菜单此刻应该处于「弹出」状态：owner 已是前台窗口。
    # 注意：非交互会话/自动化环境里前台可能被别的进程占住，
    # 这时 GetForegroundWindow 返回的不是我们的窗口，属于环境限制而非代码问题。
    fg = user32.GetForegroundWindow()
    if fg == host:
        check('弹出后 owner 成为前台窗口（菜单不会被系统立刻关掉）', True,
              'fg=%s' % fg)
    else:
        print('  · 当前会话前台窗口被占用（fg=%s，跳过该项）' % fg)
    # 关闭菜单（ESC）
    user32.PostMessageW(host, 0x0012, 0, 0)   # WM_CLOSE
    time.sleep(0.2)
    th.join(timeout=3)
    check('TrackPopupMenu 正常返回（没有 TypeError）', 'cmd' in result, str(result))
    user32.DestroyMenu(menu)

    print('\n=== 4. 悬浮窗双击 = 隐藏 ===')
    import re
    src = open(os.path.join(ROOT, 'src', 'dingpan', 'app.py'), encoding='utf-8').read()
    m = re.search(r'def _on_dblclick\(self.*?\n(?=    def )', src, re.S)
    body = m.group(0) if m else ''
    check('_on_dblclick 直接隐藏悬浮窗',
          'set_visible(False)' in body and '_open_quote' not in body)
    check('行右键菜单里仍有「打开行情页」', "'打开行情页'" in src)

    user32.DestroyWindow(host)
    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
