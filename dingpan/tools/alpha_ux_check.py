# -*- coding: utf-8 -*-
"""端到端验收：背景透明度**必须随时可调**，且真的生效。

覆盖用户反馈的两个点：
  ① 勾上「背景透明」后背景滑块被禁用 → 「背景透明度调整完全没用了」
  ② 背景 0% 时屏幕上必须是透明的（不是一块不透明的白板）

跑法：python tools/alpha_ux_check.py [--exe]
"""
import ctypes
import io
import json
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
gdi32 = w32.gdi32
FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra else ''))
    if not cond:
        FAILS.append(name)


class BIH(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


def grab(x, y, w, h):
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
    return Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')


def find_children(hwnd):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        txt = ctypes.create_unicode_buffer(96)
        user32.GetWindowTextW(h, txt, 96)
        out.append((int(h), cls.value, txt.value))
        return True
    user32.EnumChildWindows(hwnd, cb, 0)
    return out


def pump(ms):
    """跑消息循环：源码跑起来没有自己的主循环，必须手动泵消息，
    否则 InvalidateRect 产生的 WM_PAINT 根本不会被处理（画不出来）。"""
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)


TBM_SETPOS = 0x0405
TBM_GETPOS = 0x0400
WM_HSCROLL = 0x0114
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0

CFG = {'theme': 'custom', 'customBg': '#ff0000', 'customText': '#ffffff',
       'textOutline': 'off', 'bgAlpha': 60, 'bgTransparent': False, 'textAlpha': 100,
       'showHeader': False, 'showTableHead': False, 'showStatus': False,
       'groups': [{'id': 'g', 'name': '默认',
                   'stocks': [{'code': 'sh600519', 'name': '贵州茅台'}]}],
       'activeGroupId': 'g'}


def main():
    use_exe = '--exe' in sys.argv
    print('=== 背景透明度可调性 + 实际生效验收 ===')
    if use_exe:
        tmp = tempfile.mkdtemp(prefix='dpux_')
        shutil.copy2(os.path.join(ROOT, 'dist', 'dingpan.exe'),
                     os.path.join(tmp, 'dingpan.exe'))
        cfg = json.load(io.open(os.path.join(ROOT, 'dist', 'dingpan-config.json'),
                                encoding='utf-8'))
        cfg.update(CFG)
        io.open(os.path.join(tmp, 'dingpan-config.json'), 'w',
                encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False, indent=2))
        proc = subprocess.Popen([os.path.join(tmp, 'dingpan.exe')])
        t0 = time.time()
        hw = None
        while time.time() - t0 < 20 and not hw:
            hw = user32.FindWindowW('DingPanWidget', None)
            time.sleep(0.2)
        t0 = time.time()
        while time.time() - t0 < 20:
            r0 = wintypes.RECT()
            user32.GetWindowRect(hw, ctypes.byref(r0))
            if r0.right > r0.left:
                break
            time.sleep(0.3)
        time.sleep(2.0)
    else:
        os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpux_')
        home = tempfile.mkdtemp(prefix='dphome_')
        os.environ['DINGPAN_HOME'] = home
        from dingpan.app import App
        app = App()
        app.cfg.update(CFG)
        app.create_window()
        app.refresh = lambda: None
        app.set_visible(True)
        app.widget.quotes = {'sh600519': {'code': 'sh600519', 'name': '贵州茅台',
                                          'price': 1335.0, 'prevClose': 1318.49,
                                          'change': 16.51, 'changePct': 1.25}}
        time.sleep(0.5)
        hw = app.widget.hwnd

    # 打开设置 → 样式页
    user32.SendMessageW(hw, w32.WM_HOTKEY, 3, 0)
    t0 = time.time()
    sh = None
    while time.time() - t0 < 10 and not sh:
        sh = user32.FindWindowW('DingPanSettings', None)
        time.sleep(0.2)
    time.sleep(0.6)
    user32.PostMessageW(sh, 0x0111, 8000 + 3, 0)     # 样式页
    pump(800)

    sb_bg = cb = None
    for h, cls, txt in find_children(sh):
        if cls == 'msctls_trackbar32' and sb_bg is None:
            sb_bg = h
        if txt == '背景透明':
            cb = h
    if not (sb_bg and cb):
        check('找到背景滑块与「背景透明」复选框', False)
        return 1

    def bg_opacity():
        """量一下悬浮窗背景在屏幕上到底有多不透明（相对底图）"""
        r = wintypes.RECT()
        user32.GetWindowRect(hw, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        tx, ty = r.left, r.top
        if not user32.IsWindowVisible(hw):
            print('    ⚠ 悬浮窗当前不可见，无法测量')
        user32.SetWindowPos(hw, None, -4000, -4000, 0, 0, 0x0001 | 0x0004)
        pump(700)
        before = grab(tx, ty, w, h)
        user32.SetWindowPos(hw, None, tx, ty, 0, 0, 0x0001 | 0x0004)
        pump(1200)
        after = grab(tx, ty, w, h)
        bp, ap = before.load(), after.load()
        y0 = int(h * 0.78)
        vals = []
        for y in range(y0, h - 4, 3):
            for x in range(3, w - 12, 5):
                b, a = bp[x, y], ap[x, y]
                # 背景是纯红(255,0,0)，桌面多为浅色：
                # 桌面绿通道被背景盖住多少 = 背景不透明度
                vals.append(max(0, b[1] - a[1]) / 255.0)
        vals.sort()
        return vals[len(vals) // 2] if vals else 0.0

    def set_slider(v):
        user32.SendMessageW(sb_bg, TBM_SETPOS, 1, int(v))
        user32.SendMessageW(sh, WM_HSCROLL, 0, sb_bg)
        pump(600)

    print('  --- 滑块 ---')
    check('背景滑块默认可用', bool(user32.IsWindowEnabled(sb_bg)))
    set_slider(60)
    op60 = bg_opacity()
    check('背景 60% 时屏幕上背景不透明度 ≈60%%', 0.45 < op60 < 0.75,
          '实测 %.0f%%' % (op60 * 100))
    set_slider(0)
    op0 = bg_opacity()
    check('背景 0% 时屏幕上背景不透明度 ≈0%%（真透明）', op0 < 0.10,
          '实测 %.0f%%' % (op0 * 100))
    check('拖到 0% 后滑块依然可用（不会被禁用）',
          bool(user32.IsWindowEnabled(sb_bg)))
    check('拖到 0% 后「背景透明」自动勾上',
          user32.SendMessageW(cb, BM_GETCHECK, 0, 0) == 1)
    set_slider(30)
    check('离开 0% 后「背景透明」自动取消',
          user32.SendMessageW(cb, BM_GETCHECK, 0, 0) == 0)
    op30 = bg_opacity()
    check('背景 30% 时屏幕上背景不透明度 ≈30%%', 0.18 < op30 < 0.45,
          '实测 %.0f%%' % (op30 * 100))

    print('  --- 「背景透明」复选框 ---')
    user32.SendMessageW(cb, BM_CLICK, 0, 0)      # 勾上 → 滑块应拉到 0
    pump(900)
    check('勾上「背景透明」后滑块变成 0%',
          user32.SendMessageW(sb_bg, TBM_GETPOS, 0, 0) == 0,
          '实际 %d' % user32.SendMessageW(sb_bg, TBM_GETPOS, 0, 0))
    check('勾上「背景透明」后滑块依然可用',
          bool(user32.IsWindowEnabled(sb_bg)))
    opc = bg_opacity()
    check('勾上「背景透明」后屏幕上背景全透', opc < 0.10, '实测 %.0f%%' % (opc * 100))
    user32.SendMessageW(cb, BM_CLICK, 0, 0)      # 取消 → 恢复上次非 0 值
    pump(900)
    pos = user32.SendMessageW(sb_bg, TBM_GETPOS, 0, 0)
    check('取消「背景透明」后滑块恢复成非 0 值', pos > 0, '实际 %d' % pos)

    if use_exe:
        proc.kill()
    else:
        app._cleanup()
    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %s' % FAILS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
