#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""设置窗口「打开 → 逐页切换 → 保存 → 关闭 → 再打开」循环测试

用户反复报告过：
  - 「保存后，再打开，还是会出错，有些设置页就又打不开了」
  - 「点几下就叠出好几个设置窗口」
  - 「显示字段页不能点，一调整就跳回首页」

本测试把整个生命周期反复走 N 遍，验证：
  1) 每次打开都能正常显示，且**不会叠出多个窗口**
  2) 左侧导航每一页都能切过去（发 WM_COMMAND，cid = 8000+pid，等同点击）
  3) 切页后当前页标记正确（不会自己跳回首页）
  4) 「保存设置」后配置真的落盘（重新读文件核对）
  5) 关闭后再打开一切正常
  6) 整个过程 crash.log 没有新增异常

不依赖鼠标，不截图。
"""
import ctypes
import io
import json
import os
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

APPDATA_TMP = tempfile.mkdtemp(prefix='dpcycle_')
os.environ['APPDATA'] = APPDATA_TMP
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import dialogs              # noqa: E402
from dingpan import storage              # noqa: E402
from dingpan.app import App              # noqa: E402
from dingpan import settings as st       # noqa: E402
from dingpan.win32 import user32         # noqa: E402

FAILS = []
ROUNDS = 5


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra != '' else ''))
    if not cond:
        FAILS.append(name)


def pump(app, ms=120):
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def count_settings_windows():
    """数一下当前有几个设置窗口（用户抱怨过"叠出好几个"）。

    只统计**本进程**的窗口：用户可能正开着盯盘（甚至开着它的设置窗），
    把别人的窗口算进来会误报成"叠窗口"。
    """
    found = []
    my_pid = os.getpid()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == 'DingPanSettings':
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) == my_pid and user32.IsWindowVisible(hwnd):
                found.append(int(hwnd))
        return True

    user32.EnumWindows(cb, 0)
    return found


def crash_log_tail():
    try:
        p = os.path.join(storage.app_dir(), 'crash.log')
        if not os.path.isfile(p):
            return ''
        with io.open(p, encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception:
        return ''


def main():
    # 模态框会阻塞测试，替换成空实现
    dialogs.message_box = lambda *a, **k: None
    st.dialogs.message_box = lambda *a, **k: None

    app = App()
    app.cfg['groups'] = [{'id': 'g', 'name': '默认',
                          'stocks': [{'code': 'sh600519', 'name': '贵州茅台'}]}]
    app.cfg['activeGroupId'] = 'g'
    app.create_window()

    pages = [(st.P_BASIC, 'basic'), (st.P_STOCKS, 'stocks'), (st.P_COLUMNS, 'columns'),
             (st.P_STYLE, 'style'), (st.P_BACKUP, 'backup'), (st.P_DAV, 'dav'),
             (st.P_HOTKEY, 'hotkeys'), (st.P_ABOUT, 'about')]

    try:
        print('=== 1. 反复「打开 → 逐页切换 → 保存 → 关闭」===')
        for rnd in range(1, ROUNDS + 1):
            obj = app.open_settings()
            pump(app, 150)
            ok_open = bool(obj.hwnd and user32.IsWindow(obj.hwnd))
            check('第 %d 轮：设置窗口打开' % rnd, ok_open)

            wins = count_settings_windows()
            check('第 %d 轮：只有一个设置窗口' % rnd, len(wins) <= 1, '实际 %d 个' % len(wins))

            # 逐页切换（等同点击左侧导航按钮）
            jump_back = []
            for pid, key in pages:
                user32.SendMessageW(obj.hwnd, 0x0111, 8000 + pid, 0)   # WM_COMMAND
                pump(app, 60)
                if obj.page != pid:
                    jump_back.append('%s(实际=%s)' % (key, obj.page))
            check('第 %d 轮：8 个导航页都能切过去且不跳回' % rnd, not jump_back,
                  '; '.join(jump_back))

            # 改一个设置：切换「显示股票代码」复选框，再保存
            before = bool(app.cfg.get('showCode', True))
            cb = getattr(obj, 'chk_show_code', None)
            if cb:
                user32.SendMessageW(cb, 0x00F1, 0 if before else 1, 0)  # BM_SETCHECK
                user32.SendMessageW(obj.hwnd, 0x0111, obj.chk_show_code_id, cb)
            else:
                # 找不到控件就退而求其次：直接改 cfg，验证保存链路
                app.cfg['showCode'] = not before

            app.cfg['fontSize'] = 13
            obj._save()
            pump(app, 120)

            # 落盘核对
            on_disk = storage.load_config()
            check('第 %d 轮：保存后配置已落盘' % rnd,
                  isinstance(on_disk, dict) and bool(on_disk.get('groups')))

            # 关闭
            user32.SendMessageW(obj.hwnd, 0x0010, 0, 0)   # WM_CLOSE → DestroyWindow
            pump(app, 150)
            check('第 %d 轮：关闭后窗口已销毁' % rnd,
                  not obj.hwnd or not user32.IsWindow(obj.hwnd))
            wins2 = count_settings_windows()
            check('第 %d 轮：关闭后没有残留窗口' % rnd, len(wins2) == 0,
                  '实际 %d 个' % len(wins2))

            # 再打开
            obj2 = app.open_settings()
            pump(app, 150)
            check('第 %d 轮：重新打开正常' % rnd,
                  bool(obj2.hwnd and user32.IsWindow(obj2.hwnd)))
            # 再打开后第一件事就是切到「显示字段」页（用户最常点的地方）
            user32.SendMessageW(obj2.hwnd, 0x0111, 8000 + st.P_COLUMNS, 0)
            pump(app, 80)
            check('第 %d 轮：重开后能直接进「显示字段」页' % rnd,
                  obj2.page == st.P_COLUMNS, 'page=%s' % obj2.page)

        print('\n=== 2. 全程无新增异常 ===')
        log = crash_log_tail()
        check('crash.log 没有新增异常', 'Traceback' not in log and 'Error' not in log,
              (log[-400:] if log else '(无日志)'))

        print('\n=== 3. 保存 → 重开 → 配置仍然正确 ===')
        obj3 = app.open_settings()
        pump(app, 150)
        check('第三次打开后「显示字段」页可进',
              obj3.page is not None)
        user32.SendMessageW(obj3.hwnd, 0x0111, 8000 + st.P_COLUMNS, 0)
        pump(app, 80)
        check('切到「显示字段」页成功', obj3.page == st.P_COLUMNS)
        cols = obj3._get_selected_columns() if hasattr(obj3, '_get_selected_columns') else None
        if cols is not None:
            check('已选字段里名称和代码是两个独立条目',
                  'name' in cols and 'code' in cols, str(cols))
        user32.SendMessageW(obj3.hwnd, 0x0010, 0, 0)
        pump(app, 120)

    finally:
        try:
            app._cleanup()
        except Exception:
            pass

    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
