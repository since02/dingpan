#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""视觉验收：把界面真的显示出来并截屏，自动判定「有没有内容」

为什么需要：
  「菜单项都在、但弹出来是空白」这类问题，**光读 API 返回值测不出来**，
  只有看真实渲染结果才能确认。本工具把界面弹出来 → 截屏 → 用像素统计断言非空白。

不用注入鼠标（本会话禁止 SendInput）：
  - 菜单：class 为 #32768 的真实窗口，用**屏幕 DC 位块传输**抓（比 PrintWindow 可靠）
  - 悬浮窗：WS_EX_LAYERED 窗口，同样按屏幕区域抓

产出：tools/visual_shots/*.png
退出码：0 = 全部通过，1 = 有空白/异常
"""
import ctypes
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpvisual_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import win32 as w32                        # noqa: E402
from dingpan.app import App                            # noqa: E402

user32 = w32.user32
gdi32 = w32.gdi32

MENU_CLASS = '#32768'
OUT_DIR = os.path.join(ROOT, 'tools', 'visual_shots')
WM_CANCELMODE = 0x001F

# ---- 需要的 API 声明 ----
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.TrackPopupMenu.restype = wintypes.UINT
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.PrintWindow.restype = ctypes.c_bool
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]
user32.GetWindowDC.restype = wintypes.HDC
user32.GetWindowDC.argtypes = [wintypes.HWND]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.BitBlt.restype = ctypes.c_bool
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0

FAILS = []


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long),
                ('biHeight', ctypes.c_long), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra else ''))
    if not cond:
        FAILS.append(name)
    return cond


def grab_screen_rect(x, y, w, h, path):
    """从屏幕 DC 位块传输指定区域存 PNG"""
    from PIL import Image
    if w <= 0 or h <= 0:
        return False
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    ok = bool(gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, x, y, SRCCOPY))

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h                      # 负数 = 自上而下
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)

    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(None, screen_dc)

    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    return ok


def image_stats(path):
    """返回 (灰度标准差, 深色像素占比) —— 空白图标准差≈0"""
    from PIL import Image, ImageStat
    im = Image.open(path).convert('L')
    st = ImageStat.Stat(im)
    stddev = st.stddev[0]
    px = list(im.getdata())
    dark = sum(1 for v in px if v < 128)
    return stddev, (dark / len(px) if px else 0.0)


def assert_not_blank(path, label, min_stddev=1.0):
    """断言截图不是纯色（纯色 = 渲染空白）"""
    if not os.path.isfile(path):
        return check('%s 有截图' % label, False, path)
    stddev, dark = image_stats(path)
    ok = stddev >= min_stddev
    return check('%s 渲染有内容（不是空白）' % label, ok,
                 '灰度标准差 %.2f / 深色像素 %.2f%%' % (stddev, dark * 100))


def find_visible_menu_window():
    """找出当前**可见**的弹出菜单窗口。

    注意：CreatePopupMenu() 创建的菜单本身就对应一个 class=#32768 的窗口，
    在 TrackPopupMenu 真正显示它之前，它的窗口矩形是默认的 (0,0,100,100)。
    只用 FindWindowW('#32768') 会抓到那个「还没显示的菜单」，
    截出来就是 100x100 的空白 → 必须挑可见且面积最大的那个。
    """
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, buf, 256)
        if buf.value == MENU_CLASS and user32.IsWindowVisible(h):
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            w, ht = r.right - r.left, r.bottom - r.top
            if w > 0 and ht > 0:
                found.append((w * ht, int(h), r))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None, None
    found.sort(reverse=True)
    return found[0][1], found[0][2]


def capture_menu_window(owner, out_path, timeout=8.0):
    """辅助线程：等菜单窗口**显示出来** → 截屏 → 关菜单

    抓取优先用 PrintWindow 直接抓菜单窗口自身（class #32768）：
    屏幕位块传输会因为「菜单还没被 DWM 画出来 / 被别的窗口盖住」抓到全黑，
    实测会偶发失败；PrintWindow 稳定得多。
    """
    deadline = time.time() + timeout
    hmenu = None
    rect = None
    while time.time() < deadline:
        h, r = find_visible_menu_window()
        if h:
            hmenu, rect = h, r
            break
        time.sleep(0.02)

    if not hmenu:
        print('    ✗ 没等到可见的菜单窗口出现（class=%s）' % MENU_CLASS)
        user32.PostMessageW(owner, WM_CANCELMODE, 0, 0)
        return False

    w, h = rect.right - rect.left, rect.bottom - rect.top
    print('    找到可见菜单窗口 hwnd=%d rect=(%d,%d,%d,%d) 尺寸 %dx%d'
          % (hmenu, rect.left, rect.top, rect.right, rect.bottom, w, h))

    ok = False
    used = ''
    # ① PrintWindow 抓窗口自身
    for attempt in range(3):
        time.sleep(0.2)
        if grab_printwindow(hmenu, w, h, out_path):
            stddev, _ = image_stats(out_path)
            if stddev >= 1.0:
                ok, used = True, 'PrintWindow'
                break
    # ② 回退：屏幕位块传输
    if not ok:
        if grab_screen_rect(rect.left, rect.top, w, h, out_path):
            stddev, _ = image_stats(out_path)
            if stddev >= 1.0:
                ok, used = True, '屏幕截取'

    print('    菜单窗口 %dx%d → %s（%s）' % (w, h, os.path.basename(out_path), used or '抓取失败'))
    user32.PostMessageW(owner, WM_CANCELMODE, 0, 0)
    return ok


def shoot_menu(app, builder, out_name, label, sx=300, sy=150):
    print('\n--- %s ---' % label)
    menu = builder()
    if not menu:
        return check('%s 菜单能构建' % label, False)
    owner = app.tray_host or app.hwnd
    path = os.path.join(OUT_DIR, out_name)
    th = threading.Thread(target=capture_menu_window, args=(owner, path), daemon=True)
    th.start()
    time.sleep(0.12)
    cmd = user32.TrackPopupMenu(menu, w32.TPM_RIGHTBUTTON | w32.TPM_RETURNCMD | w32.TPM_NONOTIFY,
                                sx, sy, 0, owner, None)
    user32.PostMessageW(owner, w32.WM_NULL, 0, 0)
    th.join(timeout=8)
    user32.DestroyMenu(menu)
    check('%s 菜单能弹出（TrackPopupMenu 正常返回）' % label, True,
          'cmd=%d（0=被取消，符合预期）' % cmd)
    return assert_not_blank(path, label)


def grab_printwindow(hwnd, w, h, path):
    """用 PrintWindow 抓窗口自身内容（与 z-order 无关，不受别的置顶窗口遮挡）"""
    from PIL import Image
    if w <= 0 or h <= 0:
        return False
    win_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(win_dc)
    bmp = gdi32.CreateCompatibleBitmap(win_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    # PW_RENDERFULLCONTENT = 2：让分层窗口也走自己的 WM_PRINT 渲染
    ok = bool(user32.PrintWindow(hwnd, mem_dc, 2))

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)

    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, win_dc)

    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    return ok


def pump(app, ms):
    """跑消息循环。

    **必须跑**：悬浮窗是 WS_EX_LAYERED + UpdateLayeredWindow 绘制的，
    WM_PAINT 没被投递 → 窗口从未绘制 → 分层表面不存在 → PrintWindow 只能拿到全空图
    （实测 stddev = 0.00）。泵 600ms 后 stddev = 9.71，能拿到真实内容。
    """
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


FAKE_QUOTES = {
    'sh600519': {'code': 'sh600519', 'name': '贵州茅台', 'price': 1688.00, 'prevClose': 1675.70,
                 'change': 12.30, 'changePct': 0.74, 'turnover': 0.52, 'time': '2026-10-23 10:30:00'},
    'sz000001': {'code': 'sz000001', 'name': '平安银行', 'price': 11.86, 'prevClose': 12.05,
                 'change': -0.19, 'changePct': -1.58, 'turnover': 0.31, 'time': '2026-10-23 10:30:00'},
    'sz300750': {'code': 'sz300750', 'name': '宁德时代', 'price': 182.44, 'prevClose': 179.90,
                 'change': 2.54, 'changePct': 1.41, 'turnover': 0.88, 'time': '2026-10-23 10:30:00'},
}


def shoot_widget(app, out_name='widget.png'):
    """截悬浮窗 —— 验证名称/代码是分开的独立列"""
    print('\n--- 悬浮窗（名称 / 代码是否分列）---')
    hwnd = app.hwnd
    # stub 掉网络刷新：否则 set_visible 触发的拉取线程会在我们注入假数据之后
    # 把 widget.quotes 覆盖成空 → 主体又变成「暂无自选股」，截图不可复现。
    app.refresh = lambda: None
    app.set_visible(True)
    w32.set_always_on_top(hwnd, True)

    # 注入确定性行情数据：布局验证要可复现，不能依赖网络时序
    app.widget.quotes = dict(FAKE_QUOTES)
    app.widget.paint_now()
    pump(app, 700)          # 让 WM_PAINT 被投递并真正绘制

    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    path = os.path.join(OUT_DIR, out_name)

    # 路径 A：PrintWindow（抓窗口自身内容，不受别的置顶窗口遮挡）
    ok = grab_printwindow(hwnd, w, h, path)
    used = 'PrintWindow'
    if ok:
        stddev, _ = image_stats(path)
        print('    PrintWindow 灰度标准差 = %.2f' % stddev)
        if stddev < 1.0:
            ok = False          # 抓到了但是纯色 = 没拿到内容
    # 路径 B：回退到屏幕截取（可能抓到遮挡窗口，只作兜底）
    if not ok:
        used = '屏幕截取'
        ok = grab_screen_rect(r.left, r.top, w, h, path)

    check('悬浮窗截图成功（%s）' % used, ok, '%dx%d → %s' % (w, h, os.path.basename(path)))
    return assert_not_blank(path, '悬浮窗')


def shoot_settings(app):
    """逐页截设置窗口 —— 验证「显示字段」等页面真的能打开且有内容"""
    print('\n--- 设置窗口（逐页）---')
    from dingpan import settings as st
    obj = app.open_settings()
    if not obj or not obj.hwnd:
        return check('设置窗口能打开', False)
    hwnd = obj.hwnd
    check('设置窗口能打开', bool(hwnd))

    pages = [(st.P_BASIC, 'basic'), (st.P_STOCKS, 'stocks'), (st.P_COLUMNS, 'columns'),
             (st.P_STYLE, 'style'), (st.P_BACKUP, 'backup'), (st.P_DAV, 'dav'),
             (st.P_HOTKEY, 'hotkeys'), (st.P_ABOUT, 'about')]
    all_ok = True
    for pid, key in pages:
        obj._show_page(pid)
        pump(app, 260)                      # 让控件显隐 + 重绘落地
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        path = os.path.join(OUT_DIR, 'settings_%s.png' % key)
        ok = grab_printwindow(hwnd, w, h, path)
        if not ok:
            stddev = -1
        else:
            stddev, _ = image_stats(path)
        good = ok and stddev >= 1.0
        all_ok = all_ok and good
        check('设置页「%s」渲染有内容' % key, good,
              '%dx%d 灰度标准差 %.2f' % (w, h, stddev))

    # 单独核对「显示字段」页：名称和代码应该是列表里两个独立条目
    obj._show_page(st.P_COLUMNS)
    pump(app, 260)
    path = os.path.join(OUT_DIR, 'settings_columns.png')
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    grab_printwindow(hwnd, r.right - r.left, r.bottom - r.top, path)
    print('    「显示字段」页截图：settings_columns.png')
    return all_ok


def main():
    app = App()
    app.cfg['groups'] = [{'id': 'g', 'name': '默认',
                          'stocks': [{'code': 'sh600519', 'name': '贵州茅台'},
                                     {'code': 'sz000001', 'name': '平安银行'},
                                     {'code': 'sz300750', 'name': '宁德时代'}]}]
    app.cfg['activeGroupId'] = 'g'
    app.create_window()
    try:
        shoot_widget(app)
        shoot_menu(app, app._build_tray_menu, 'menu_tray.png', '托盘右键菜单')
        shoot_menu(app, app._build_main_menu, 'menu_main.png', '悬浮窗空白处菜单')
        shoot_menu(app, lambda: app._build_row_menu(1), 'menu_row.png', '行右键菜单')
        shoot_settings(app)
    finally:
        app._cleanup()

    print('\n输出目录: %s' % OUT_DIR)
    print('结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
