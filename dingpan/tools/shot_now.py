# -*- coding: utf-8 -*-
"""用 PW_RENDERFULLCONTENT 截图设置窗口，逐个页面存 PNG，便于肉眼核对。"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]
user32.SendMessageW.restype = ctypes.c_ssize_t
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
user32.GetWindowDC.restype = wintypes.HDC
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateSolidBrush.restype = wintypes.HGDIOBJ
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.HGDIOBJ]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'page_shots')
PAGES = [(0, 'basic'), (1, 'stocks'), (2, 'columns'), (3, 'style'),
         (4, 'backup'), (5, 'dav'), (6, 'hotkeys'), (7, 'about')]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


def grab(hwnd, path):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return 0, 0, 0
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    # 2 = PW_RENDERFULLCONTENT（Win8.1+，会带上子控件）；跨进程只能用 PrintWindow
    ok = user32.PrintWindow(hwnd, mdc, 2)
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth, bi.biHeight = w, -h
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    lines = gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    colors = len(set(buf.raw[i:i + 4] for i in range(0, len(buf.raw), 4 * 97)))
    # 写 BMP（32 位，负高度已由 GetDIBits 处理成正序）
    hdr = b'BM' + (54 + len(buf.raw)).to_bytes(4, 'little') + b'\0\0\0\0' + (54).to_bytes(4, 'little')
    info = (40).to_bytes(4, 'little') + w.to_bytes(4, 'little') + (-h).to_bytes(4, 'little', signed=True) \
        + (1).to_bytes(2, 'little') + (32).to_bytes(2, 'little') + (0).to_bytes(4, 'little') \
        + len(buf.raw).to_bytes(4, 'little') + b'\0' * 16
    with open(path, 'wb') as f:
        f.write(hdr + info + buf.raw)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return ok, lines, colors


def kill_all():
    """只清理自己启动的同名进程，绝不触碰其它程序"""
    import subprocess as sp
    try:
        out = sp.run(['tasklist', '/FI', 'IMAGENAME eq dingpan.exe', '/NH'],
                     capture_output=True, text=True, errors='ignore').stdout
        for line in out.splitlines():
            if 'dingpan.exe' in line:
                pid = line.split()[1]
                sp.run(['taskkill', '/PID', pid, '/F'], capture_output=True)
    except Exception:
        pass


def main():
    kill_all()
    time.sleep(0.8)
    exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dist', 'dingpan.exe')
    proc = subprocess.Popen([exe])
    hwnd = None
    for _ in range(60):
        time.sleep(0.4)
        h = user32.FindWindowW('DingPanWidget', None)
        if h:
            hwnd = h
            break
    if not hwnd:
        print('未找到悬浮窗')
        proc.terminate()
        return
    user32.SendMessageW(hwnd, 0x0312, 3, 0)  # WM_HOTKEY id=3 -> 打开设置
    hset = None
    for _ in range(40):
        h = user32.FindWindowW('DingPanSettings', None)
        hset = h
        if h:
            break
        time.sleep(0.3)
    if not hset:
        print('未找到设置窗')
        proc.terminate()
        return
    os.makedirs(OUT, exist_ok=True)
    print('设置窗:', hset)
    try:
        only = int(sys.argv[1]) if len(sys.argv) > 1 else None
        for pid, name in PAGES:
            if only is not None and pid != only:
                continue
            user32.SendMessageW(hset, 0x0111, pid, 0)  # WM_COMMAND
            time.sleep(0.5)
            p = os.path.join(OUT, 'page_%s.bmp' % name)
            ok = lines = colors = 0
            for _try in range(4):          # PrintWindow 偶发失败，重试几次
                ok, lines, colors = grab(hset, p)
                if lines:
                    break
                time.sleep(0.4)
            print('  %-8s GetDIBits=%s 颜色数=%d -> %s' % (name, lines, colors, os.path.basename(p)))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == '__main__':
    main()
