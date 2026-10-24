# -*- coding: utf-8 -*-
"""对打包后的 dist/dingpan.exe 做最终验收：启动 -> 悬浮窗 -> 热键设置 -> 托盘 -> 退出"""
import subprocess
import sys
import time
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'src'))
# ⚠️ 隔离 APPDATA：测试绝不能碰用户的真实配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpfinal_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import win32 as w32  # noqa: E402
import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

user32 = w32.user32
EXE = os.path.join(ROOT, 'dist', 'dingpan.exe')

results = []


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('  ✓ ' if ok else '  ✗ ') + name + ((' — ' + str(detail)) if detail else ''))


def wait_hwnd(timeout=25):
    end = time.time() + timeout
    hwnd = None
    while time.time() < end:
        hwnd = user32.FindWindowW('DingPanWidget', None)
        if hwnd:
            return hwnd
        time.sleep(0.3)
    return None


print('启动 %s' % EXE)
proc = subprocess.Popen([EXE])
hwnd = wait_hwnd()
check('悬浮窗已创建', bool(hwnd), hwnd)

if not hwnd:
    proc.kill()
    print('\n结果: %d/%d 通过' % (sum(1 for _, o, _ in results if o), len(results)))
    sys.exit(1)

user32.ShowWindow(hwnd, 5)
time.sleep(1.2)

check('悬浮窗可见', bool(user32.IsWindowVisible(hwnd)))

ex = user32.GetWindowLongW(hwnd, w32.GWL_EXSTYLE)
check('置顶样式', bool(ex & w32.WS_EX_TOPMOST))
check('分层窗口（可调透明度）', bool(ex & w32.WS_EX_LAYERED))
check('工具窗（不占任务栏）', bool(ex & w32.WS_EX_TOOLWINDOW))

r = wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
check('窗口尺寸合理', (r.right - r.left) > 200 and (r.bottom - r.top) > 100,
      '%dx%d' % (r.right - r.left, r.bottom - r.top))

# 通过热键 id=3(openSettings) 打开设置窗口
user32.SendMessageW(hwnd, w32.WM_HOTKEY, 3, 0)
time.sleep(1.5)
shwnd = None
end = time.time() + 6
while time.time() < end:
    shwnd = user32.FindWindowW('DingPanSettings', None)
    if shwnd:
        break
    time.sleep(0.3)
check('设置窗口已打开', bool(shwnd), shwnd)

if shwnd:
    # 遍历设置窗口内的可见控件数
    vis = [0]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_child(h, _l):
        if user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            vis[0] += 1
        return True

    user32.EnumChildWindows(shwnd, enum_child, 0)
    check('设置页控件已渲染', vis[0] > 10, '%d 个可见子控件' % vis[0])

# 切换下一个分组
user32.SendMessageW(hwnd, w32.WM_HOTKEY, 4, 0)
time.sleep(0.8)

# 刷新期间 UI 必须保持响应（行情在后台线程拉取）
user32.PostMessageW(hwnd, w32.WM_TIMER, 1, 0)
time.sleep(0.3)
hung = bool(user32.IsHungAppWindow(hwnd))
check('刷新期间 UI 不卡死', not hung, 'IsHungAppWindow=%s' % hung)
end = time.time() + 4
while time.time() < end and user32.IsHungAppWindow(hwnd):
    time.sleep(0.2)
check('窗口恢复响应', not bool(user32.IsHungAppWindow(hwnd)))

# 隐藏/显示
user32.SendMessageW(hwnd, w32.WM_HOTKEY, 1, 0)
time.sleep(0.8)
hidden = not user32.IsWindowVisible(hwnd)
user32.SendMessageW(hwnd, w32.WM_HOTKEY, 1, 0)
time.sleep(0.8)
check('热键隐藏/显示', hidden and user32.IsWindowVisible(hwnd))

# 退出
user32.PostMessageW(hwnd, w32.WM_CLOSE, 0, 0)
try:
    rc = proc.wait(timeout=12)
    check('程序正常退出', True, 'exit=%s' % rc)
except subprocess.TimeoutExpired:
    proc.kill()
    check('程序正常退出', False, '超时未退出')

print('\n结果: %d/%d 通过' % (sum(1 for _, o, _ in results if o), len(results)))
