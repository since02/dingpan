# -*- coding: utf-8 -*-
"""回归测试：背景/文字透明度必须真正独立 + 「背景透明」复选框必须画得出来

覆盖两个曾经很难定位的坑：
1. UpdateLayeredWindow 被 SetLayeredWindowAttributes 毒化 → 整窗统一透明度
   → 「背景全透明文字也没了 / 调文字透明度没反应 / 调背景文字一起变」
2. 设置页「背景透明」复选框被同排的数值标签（STATIC）擦掉 → 控件「莫名消失」

跑法：python tools/alpha_check.py
"""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpalpha_')
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import win32 as w32            # noqa: E402
from dingpan.app import App                 # noqa: E402

user32 = w32.user32
gdi32 = w32.gdi32
FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra else ''))
    if not cond:
        FAILS.append(name)
    return cond


def pump(ms):
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)


def grab(x, y, w, h):
    """屏幕取色（BGRA → RGB 列表）"""
    from PIL import Image
    sdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmp = gdi32.CreateCompatibleBitmap(sdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, sdc, x, y, 0x00CC0020)

    class BIH(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                    ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]
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
    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
    return img


def alpha_hist(wg, w, h):
    """从分层 DIB 里统计 alpha 分布：返回 {alpha值: 像素数}"""
    lay = wg._lay
    cbuf = ctypes.string_at(lay['cbits'].value, w * h * 4)
    alpha = cbuf[3::4]
    hist = {}
    for i in range(0, w * h, 3):
        v = alpha[i]
        hist[v] = hist.get(v, 0) + 1
    return hist


def main():
    app = App()
    app.cfg['groups'] = [{'id': 'g', 'name': '默认',
                          'stocks': [{'code': 'sh600519', 'name': '贵州茅台'},
                                     {'code': 'sz000001', 'name': '平安银行'}]}]
    app.cfg['activeGroupId'] = 'g'
    app.create_window()
    try:
        app.refresh = lambda: None
        app.set_visible(True)
        app.widget.quotes = {
            'sh600519': {'code': 'sh600519', 'name': '贵州茅台', 'price': 1335.0,
                         'prevClose': 1318.49, 'change': 16.51, 'changePct': 1.25,
                         'time': '2026-10-24 10:30:00'},
            'sz000001': {'code': 'sz000001', 'name': '平安银行', 'price': 11.2,
                         'prevClose': 11.3, 'change': -0.1, 'changePct': -0.88,
                         'time': '2026-10-24 10:30:00'},
        }
        pump(400)
        wg = app.widget
        w, h = wg.client_size()

        print('\n=== 1. 分层绘制必须成功（不能退化成整窗统一透明度）===')
        ok_all = True
        for cfg in ({'bgAlpha': 100, 'textAlpha': 100, 'bgTransparent': False},
                    {'bgAlpha': 47, 'textAlpha': 100, 'bgTransparent': False},
                    {'bgAlpha': 100, 'textAlpha': 40, 'bgTransparent': False},
                    {'bgAlpha': 20, 'textAlpha': 100, 'bgTransparent': False},
                    {'bgAlpha': 100, 'textAlpha': 100, 'bgTransparent': True}):
            wg.cfg.update(cfg)
            layered = wg._paint_layered(w, h, wg.eff_font_size())
            bg_a, tx_a = wg._alphas()
            check('UpdateLayeredWindow 成功 %s' % cfg, layered is True,
                  'bg_a=%d tx_a=%d' % (bg_a, tx_a))
            ok_all = ok_all and layered is True

        print('\n=== 2. 背景 / 文字 两条 alpha 通道必须独立 ===')
        # (a) 改背景不影响文字的 alpha
        #     注意：bg_a 不能取 255，否则背景和文字的 alpha 混在一起数不出来。
        wg.cfg.update({'bgAlpha': 47, 'textAlpha': 100, 'bgTransparent': False})
        wg.paint()
        h1 = alpha_hist(wg, w, h)
        wg.cfg.update({'bgAlpha': 30, 'textAlpha': 100, 'bgTransparent': False})
        wg.paint()
        h2 = alpha_hist(wg, w, h)
        tx100 = h1.get(255, 0)
        tx100b = h2.get(255, 0)
        check('调背景透明度，文字像素的 alpha 不变',
              tx100 > 0 and abs(tx100 - tx100b) <= max(3, tx100 * 0.02),
              '文字像素数 %d → %d（文字 alpha 恒为 255）' % (tx100, tx100b))
        check('调背景透明度，背景像素的 alpha 跟着变',
              h1.get(119, 0) > 0 and h2.get(76, 0) > 0,
              'bg_a: 119 → 76')

        # (b) 改文字不影响背景的 alpha
        wg.cfg.update({'bgAlpha': 80, 'textAlpha': 100, 'bgTransparent': False})
        wg.paint()
        h3 = alpha_hist(wg, w, h)
        bg_a3 = 80 * 255 // 100
        wg.cfg.update({'bgAlpha': 80, 'textAlpha': 40, 'bgTransparent': False})
        wg.paint()
        h4 = alpha_hist(wg, w, h)
        check('调文字透明度，背景像素的 alpha 不变',
              h3.get(bg_a3, 0) > 0 and abs(h3.get(bg_a3, 0) - h4.get(bg_a3, 0)) <= 3,
              '背景像素数 %d → %d（背景 alpha 恒为 %d）'
              % (h3.get(bg_a3, 0), h4.get(bg_a3, 0), bg_a3))
        tx40 = 40 * 255 // 100
        check('调文字透明度，文字像素的 alpha 跟着变',
              h4.get(tx40, 0) > 0, '文字 alpha = %d' % tx40)

        # (c) 背景全透明时，文字仍然是 255（不能整窗变透明）
        wg.cfg.update({'bgAlpha': 20, 'textAlpha': 100, 'bgTransparent': True})
        wg.paint()
        h5 = alpha_hist(wg, w, h)
        check('背景全透明时，背景 alpha = 0', h5.get(0, 0) > 1000,
              '透明像素 %d' % h5.get(0, 0))
        check('背景全透明时，文字 alpha 仍是 255（文字不会跟着消失）',
              h5.get(255, 0) > 200, '不透明像素 %d' % h5.get(255, 0))

        print('\n=== 3. 设置页「背景透明」复选框必须真的画出来 ===')
        from dingpan import settings as st
        obj = app.open_settings()
        pump(500)
        obj._show_page(st.P_STYLE)
        pump(500)
        cb = obj.cb_bg_transparent
        check('复选框窗口存在且可见',
              bool(cb) and bool(user32.IsWindowVisible(cb)))
        r = wintypes.RECT()
        user32.GetWindowRect(cb, ctypes.byref(r))
        # 复选框方框在按钮左侧，取 24x24 区域看有没有深色像素（方框线/文字）
        img = grab(r.left - 2, r.top + 2, 26, 20)
        px = img.load()
        dark = sum(1 for yy in range(20) for xx in range(26) if sum(px[xx, yy]) < 500)
        check('复选框在屏幕上真的画出来了（不是空白）', dark > 0,
              '区域内深色像素 = %d' % dark)
        # 数值标签不能与复选框重叠
        for nm in ('lbl_bg', 'lbl_text'):
            lab = getattr(obj, nm, None)
            if lab:
                lr = wintypes.RECT()
                user32.GetWindowRect(lab, ctypes.byref(lr))
                overlap = not (lr.right <= r.left or lr.left >= r.right
                               or lr.bottom <= r.top or lr.top >= r.bottom)
                check('%s 与复选框不重叠' % nm, not overlap,
                      'label=(%d,%d,%d,%d) cb=(%d,%d,%d,%d)'
                      % (lr.left, lr.top, lr.right, lr.bottom,
                         r.left, r.top, r.right, r.bottom))
    finally:
        app._cleanup()

    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
