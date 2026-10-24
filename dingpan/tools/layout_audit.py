# -*- coding: utf-8 -*-
"""布局审计：逐页检查每个控件是否真的落在客户区可视范围内（裁切 = 用户看到的"空白"）。"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t

PAGES = [(0, '基础设置'), (1, '样式方案'), (2, '自选管理'), (3, '显示字段'),
         (4, '备份恢复'), (5, '快捷键'), (6, '关于')]


def kill_all():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq dingpan.exe', '/NH'],
                         capture_output=True, text=True, errors='ignore').stdout
    for line in out.splitlines():
        if 'dingpan.exe' in line:
            subprocess.run(['taskkill', '/PID', line.split()[1], '/F'], capture_output=True)


def children(hwnd):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        txt = ctypes.create_unicode_buffer(80)
        user32.GetWindowTextW(h, txt, 80)
        r = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        p1, p2 = wintypes.POINT(r.left, r.top), wintypes.POINT(r.right, r.bottom)
        user32.ScreenToClient(hwnd, ctypes.byref(p1))
        user32.ScreenToClient(hwnd, ctypes.byref(p2))
        out.append((h, cls.value, txt.value, bool(user32.IsWindowVisible(h)),
                    p1.x, p1.y, p2.x, p2.y))
        return True
    user32.EnumChildWindows(hwnd, cb, 0)
    return out


kill_all()
time.sleep(0.8)
proc = subprocess.Popen([os.path.join(ROOT, 'dist', 'dingpan.exe')])
hwnd = None
for _ in range(80):
    hwnd = user32.FindWindowW('DingPanWidget', None)
    if hwnd:
        break
    time.sleep(0.25)
if not hwnd:
    print('未找到悬浮窗')
    proc.terminate()
    sys.exit(1)
time.sleep(1.2)
user32.SendMessageW(hwnd, 0x0312, 3, 0)  # 打开设置
sh = None
for _ in range(40):
    sh = user32.FindWindowW('DingPanSettings', None)
    if sh:
        break
    time.sleep(0.25)
if not sh:
    print('未找到设置窗')
    proc.terminate()
    sys.exit(1)
time.sleep(1.0)

cr = wintypes.RECT()
user32.GetClientRect(sh, ctypes.byref(cr))
wr = wintypes.RECT()
user32.GetWindowRect(sh, ctypes.byref(wr))
print('窗口外框: %dx%d   客户区: %dx%d' % (wr.right - wr.left, wr.bottom - wr.top,
                                          cr.right, cr.bottom))
CW, CH = cr.right, cr.bottom

bad_total = 0
for pid, name in PAGES:
    user32.SendMessageW(sh, 0x0111, pid, 0)
    time.sleep(0.25)
    vis = [c for c in children(sh) if c[3]]
    # 导航按钮本身位于左侧栏（x<150），不计入内容
    content = [c for c in vis if c[4] >= 150]
    outside = [c for c in content if c[6] > CW or c[7] > CH or c[5] < 0 or c[4] < 0]
    clipped = [c for c in content if c[7] > CH]
    maxb = max([c[7] for c in content], default=0)
    print('  %-8s 内容控件 %2d  最下沿 y=%3d (客户区高 %d)  越界 %d  底部被裁 %d'
          % (name, len(content), maxb, CH, len(outside), len(clipped)))
    for c in clipped[:4]:
        print('        └ 被裁: %-8s %-14s y=%d..%d' % (c[1], c[2][:14], c[5], c[7]))
    for c in outside[:5]:
        print('        └ 越界: %-8s %-14s x=%d..%d y=%d..%d' % (c[1], c[2][:14], c[4], c[6], c[5], c[7]))
    bad_total += len(outside)

print('\n越界合计: %d' % bad_total)
proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    proc.kill()
