# -*- coding: utf-8 -*-
"""截取设置窗口每一页（屏幕级），用于肉眼验收新布局。

跑法：python tools/shot_settings.py
"""
import ctypes
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
from dingpan import win32 as w32  # noqa: E402

user32 = w32.user32


def kill_stale():
    """先清掉上一次测试残留的实例。

    残留实例会占着单实例互斥锁 → 新实例直接退出 →
    FindWindowW 找到的是**上一次的窗口** → 测出来的数据全是错的
    （我在这上面栽过：把旧窗口当成「不透明的红色背景」查了半天）。
    """
    import subprocess as _sp
    _sp.run(['taskkill', '/F', '/T', '/IM', 'dingpan.exe'], capture_output=True)
    time.sleep(0.6)


def kill_tree(pid):
    """结束整个进程树。

    ⚠️ PyInstaller onefile 会先起一个引导进程再拉起真正干活的子进程；
    只 kill 父进程的话，**子进程还活着**，它仍然占着单实例互斥锁，
    下一个测试实例会直接退出 → 测到的还是上一次的残留窗口（数据全错）。
    """
    import subprocess as _sp
    _sp.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
    time.sleep(0.8)

gdi32 = w32.gdi32
OUT = os.path.join(ROOT, 'tools', 'visual_shots')


class BIH(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


def grab(x, y, w, h, path):
    from PIL import Image
    sdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmp = gdi32.CreateCompatibleBitmap(sdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, sdc, x, y, 0x00CC0020)
    bi = BIH()
    bi.biSize = ctypes.sizeof(BIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.SelectObject(mdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(None, sdc)
    Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB').save(path)


def main():
    kill_stale()
    tmp = tempfile.mkdtemp(prefix='dpshot_')
    shutil.copy2(os.path.join(ROOT, 'dist', 'dingpan.exe'), os.path.join(tmp, 'dingpan.exe'))
    p = subprocess.Popen([os.path.join(tmp, 'dingpan.exe')])
    t0 = time.time()
    hw = None
    while time.time() - t0 < 20 and not hw:
        hw = user32.FindWindowW('DingPanWidget', None)
        time.sleep(0.2)
    time.sleep(2.0)
    user32.SendMessageW(hw, w32.WM_HOTKEY, 3, 0)
    t0 = time.time()
    sh = None
    while time.time() - t0 < 10 and not sh:
        sh = user32.FindWindowW('DingPanSettings', None)
        time.sleep(0.2)
    time.sleep(0.8)
    user32.SetWindowPos(sh, None, 10, 10, 0, 0, 0x0001 | 0x0004)
    time.sleep(0.4)
    user32.SetForegroundWindow(sh)
    time.sleep(0.6)
    r = wintypes.RECT()
    user32.GetWindowRect(sh, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    pages = [(0, 'basic'), (1, 'style'), (2, 'stocks'), (3, 'columns'),
             (4, 'backup'), (5, 'hotkeys'), (6, 'about')]
    for pid, name in pages:
        user32.PostMessageW(sh, 0x0111, 8000 + pid, 0)
        time.sleep(0.7)
        user32.SetForegroundWindow(sh)
        time.sleep(0.3)
        grab(r.left, r.top, w, h, os.path.join(OUT, 'page_%s.png' % name))
        print('已截图', name)
    kill_tree(p.pid)


if __name__ == '__main__':
    main()
