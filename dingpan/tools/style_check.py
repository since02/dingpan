"""悬浮窗样式自检：分层透明、圆角、自定义配色、可拖拽尺寸

不依赖真实鼠标：直接创建窗口 → 调用 paint() → 检查 DIB 里的逐像素 alpha。
"""
import ctypes
import os
import sys
import tempfile
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# 用临时 APPDATA，避免污染用户配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpstyle_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan.app import App                      # noqa: E402
from dingpan import win32 as w32                 # noqa: E402

results = []


def check(name, ok, extra=''):
    results.append(bool(ok))
    print('  %s %s%s' % ('✓' if ok else '✗', name, (' — ' + str(extra)) if extra else ''))


def main():
    app = App()
    app.cfg.update({
        'theme': 'custom', 'customBg': '#123456', 'customText': '#00ff00',
        'bgAlpha': 60, 'textAlpha': 100, 'width': 420, 'height': 400,
        'columns': ['name', 'price', 'changePct'],
        # 这里要测「固定尺寸下」的渲染，所以关掉按内容自适应
        'autoSize': False,
    })
    app.create_window()
    app.widget.cfg = app.cfg
    app.widget.quotes = {}
    try:
        print('=== 1. 分层绘制 ===')
        app.widget.paint()
        lay = app.widget._lay
        check('已创建分层 DIB 缓冲', lay is not None)
        w, h = app.widget.client_size()
        check('客户区尺寸', (w, h) == (420, 400), '%dx%d' % (w, h))

        n = w * h
        buf = ctypes.string_at(lay['cbits'].value, n * 4)
        alphas = buf[3::4]
        corners = [alphas[0], alphas[w - 1], alphas[(h - 1) * w], alphas[h * w - 1]]
        check('四角完全透明（圆角）', all(c == 0 for c in corners), corners)

        bg_alpha = alphas[(h // 2) * w + w // 2]
        check('背景 alpha = 60%', abs(bg_alpha - 153) <= 2, bg_alpha)
        check('存在不透明文字像素', max(alphas) >= 250, 'max=%d' % max(alphas))
        translucent = sum(1 for a in alphas if 0 < a < 250)
        check('存在两种透明度的过渡像素', translucent > 0, '%d 个' % translucent)

        # ⚠️ 分层窗口的源图**必须预乘**（UpdateLayeredWindow 的合成公式
        #    Cr = Cs + Cd×(1-As)）。不预乘的话，alpha=0 的像素会把
        #    自己的颜色「加」到屏幕上 → 白色背景 + 0% 不透明度 = 屏幕上还是纯白，
        #    黑色背景 + 0% 不透明度 = 什么都不加（正常透明）。
        #    这正是用户说的「背景色为黑色时透明度有用、为白色时没用」。
        #    → 背景 RGB 应 = 原色 × (bgAlpha/255)
        i = (h // 2) * w + 8
        b, g, r = buf[i * 4], buf[i * 4 + 1], buf[i * 4 + 2]
        _f = 153 / 255.0
        check('背景色按 alpha 预乘（分层窗口硬性要求）',
              abs(b - 0x56 * _f) <= 3 and abs(g - 0x34 * _f) <= 3
              and abs(r - 0x12 * _f) <= 3,
              (hex(r), hex(g), hex(b)))
        # 背景像素的 alpha 应等于 bgAlpha
        bg_a = int(max(0, min(100, float(app.cfg.get('bgAlpha', 100))))) * 255 // 100
        check('背景像素 alpha = 背景不透明度',
              abs(alphas[(h // 2) * w + 8] - bg_a) <= 2,
              'alpha=%s 期望≈%s' % (alphas[(h // 2) * w + 8], bg_a))
        # 文字像素的 alpha 应等于 textAlpha，与 bgAlpha 无关
        tx_a = int(max(0, min(100, float(app.cfg.get('textAlpha', 100))))) * 255 // 100
        # 定位文字像素：**按绿通道**找（测试里文字是 #00ff00，背景 #123456 暗蓝）。
        # 不能按 alpha 找：文字透明度可能低于背景，那时 alpha 最大的反而是背景。
        # 也不能按 RGB 元组找：DIB 是 BGRA 顺序，蓝色分量优先会选中背景。
        bright = max(range(n), key=lambda k: buf[k * 4 + 1])
        check('文字像素 alpha = 文字不透明度（与背景无关）',
              abs(alphas[bright] - tx_a) <= 2,
              'alpha=%s 期望≈%s' % (alphas[bright], tx_a))

        print('\n=== 2. 文字不透明度独立 ===')
        app.cfg['textAlpha'] = 50
        app.widget.cfg = app.cfg
        app.widget.paint()
        buf2 = ctypes.string_at(app.widget._lay['cbits'].value, n * 4)
        a2 = buf2[3::4]
        text_px = sum(1 for a in a2 if 120 <= a <= 132)      # 50% ≈ 127
        check('文字 alpha 降到 50%', text_px > 50 and max(a2) <= 155,
              '50%%像素 %d 个，最大 %d' % (text_px, max(a2)))
        check('背景 alpha 仍为 60%', abs(a2[(h // 2) * w + w // 2] - 153) <= 2)

        print('\n=== 2b. 两条透明度通道彻底独立（用户报告的核心问题）===')

        def alphas_of(bg, tx):
            """返回 (背景像素 alpha, 文字像素 alpha)"""
            app.cfg['bgAlpha'] = bg
            app.cfg['textAlpha'] = tx
            app.widget.cfg = app.cfg
            app.widget.paint()
            b2 = ctypes.string_at(app.widget._lay['cbits'].value, n * 4)
            a = b2[3::4]
            from collections import Counter
            # 背景像素：alpha 众数（背景占比最大）
            bg_a_val = Counter(a).most_common(1)[0][0]
            # 文字像素：**精确匹配预乘后的正文色**。
            # 正文色是 #00ff00，预乘后正好是 (B=0, G=tx_a, R=0)，
            # 比「找最大绿通道」可靠得多（次要文字、状态栏的涨绿也会是绿的）。
            _tx = int(max(0, min(100, float(tx))) * 255 / 100)
            cands = [k for k in range(n)
                     if b2[k * 4] == 0 and b2[k * 4 + 1] == _tx and b2[k * 4 + 2] == 0]
            if not cands:
                cands = [k for k in range(n) if a[k] != bg_a_val] or list(range(n))
                br = max(cands, key=lambda k: b2[k * 4 + 1])
            else:
                br = cands[0]
            return bg_a_val, a[br]

        b1, t1 = alphas_of(100, 100)
        b2_, t2 = alphas_of(30, 100)
        b3, t3 = alphas_of(100, 30)
        check('调低背景不透明度 → 背景 alpha 下降',
              b2_ < b1, '%d → %d' % (b1, b2_))
        check('调低背景不透明度 → 文字 alpha **不变**',
              abs(t2 - t1) <= 2, '%d → %d' % (t1, t2))
        check('调低文字不透明度 → 文字 alpha 下降',
              t3 < t1, '%d → %d' % (t1, t3))
        check('调低文字不透明度 → 背景 alpha **不变**',
              abs(b3 - b1) <= 2, '%d → %d' % (b1, b3))
        app.cfg['bgAlpha'] = 60
        app.cfg['textAlpha'] = 100
        app.widget.cfg = app.cfg

        print('\n=== 3. 拖动改大小 ===')
        app.cfg['textAlpha'] = 100
        app.widget.cfg = app.cfg
        user32 = w32.user32
        r = wintypes.RECT()
        user32.GetWindowRect(app.hwnd, ctypes.byref(r))
        start = (r.right - r.left, r.bottom - r.top)
        app._resize = (start, (500, 500))
        app._do_resize(app.hwnd, wintypes.POINT(560, 530))   # 模拟向右下拖动 60x30
        user32.GetWindowRect(app.hwnd, ctypes.byref(r))
        got = (r.right - r.left, r.bottom - r.top)
        check('窗口尺寸随拖动变化', got[0] > start[0] and got[1] > start[1],
              '%s → %s' % (start, got))
        app.widget.paint()
        check('尺寸变化后能重新绘制', app.widget._lay['size'] == app.widget.client_size(),
              app.widget._lay['size'])
        # 主动改过尺寸 → 应自动关掉「按内容自适应」，否则下一帧就被拉回去。
        # 注意必须先调 _end_resize（它要求 _resize 还在），再清空。
        app._end_resize()
        check('手动改过尺寸后自动关闭「按内容自适应」',
              app.cfg.get('autoSize', True) is False,
              'autoSize=%s' % app.cfg.get('autoSize'))
        app._resize = None
        app.cfg['autoSize'] = True

        print('\n=== 4. 命中测试 ===')
        ww, hh = app.widget.client_size()
        check('右下角是缩放宽热区', app.widget.hit_resize(ww - 4, hh - 4))
        check('中间不是缩放宽热区', not app.widget.hit_resize(ww // 2, hh // 2))
        check('标题栏空白处可拖动', app.widget.hit_button(10, 10) is None)
    finally:
        try:
            app.widget._cleanup_buffers()
            w32.user32.DestroyWindow(app.hwnd)
        except Exception:  # noqa: BLE001
            pass
    ok = sum(1 for r in results if r)
    print('\n结果: %d/%d 通过' % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
