# -*- coding: utf-8 -*-
"""屏幕级回归：悬浮窗背景**真的**透明吗？

前面 alpha_check.py 只能证明「DIB 里的 alpha 平面是对的」，
但那只说明**提交给系统的那张图**没问题 —— 屏幕上的效果还可能不对
（比如窗口底下残留了一块 GDI 画的不透明白板 → 看着完全不透明）。

本测试用「前后截屏对比」验证屏幕上的真实效果：
  ① 把悬浮窗挪走 → 截「底图」
  ② 把它挪回原位 → 再截一次
  ③ 挑一块**没有文字**的空白区域比较两次的像素
     → 几乎没差别 = 背景真透明；差很多 = 底下压着一块不透明的东西

跑法：python tools/alpha_screen_check.py [--exe]
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


def pump(ms):
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)


# 测试用配置：红底 + 白字 + 背景 0%（完全透明）
CFG = {'theme': 'custom', 'customBg': '#ff0000', 'customText': '#ffffff',
       'textOutline': 'off', 'bgAlpha': 0, 'bgTransparent': True, 'textAlpha': 100,
       'showHeader': False, 'showTableHead': False, 'showStatus': False,
       'groups': [{'id': 'g', 'name': '默认',
                   'stocks': [{'code': 'sh600519', 'name': '贵州茅台'}]}],
       'activeGroupId': 'g'}


def start(use_exe):
    if use_exe:
        kill_stale()
        tmp = tempfile.mkdtemp(prefix='dpasc_')
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
        # ⚠️ 必须等到窗口真的有尺寸再继续：
        #    单实例互斥锁会让第二个实例直接退出，FindWindowW 可能拿到
        #    一个还没建好的（尺寸为 0 的）窗口 → 后面量到的是桌面而不是悬浮窗。
        t0 = time.time()
        while time.time() - t0 < 20:
            r0 = wintypes.RECT()
            user32.GetWindowRect(hw, ctypes.byref(r0))
            if r0.right > r0.left and r0.bottom > r0.top:
                break
            hw = user32.FindWindowW('DingPanWidget', None)
            if not hw:
                time.sleep(0.3)
                continue
            time.sleep(0.3)
        time.sleep(2.0)
        return hw, None, proc
    os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpasc_')
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
    pump(900)
    return app.widget.hwnd, app, None


def main():
    use_exe = '--exe' in sys.argv
    print('=== 屏幕级：悬浮窗背景是否真透明 ===')
    hw, app, proc = start(use_exe)
    r = wintypes.RECT()
    user32.GetWindowRect(hw, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    tx, ty = r.left, r.top
    # ① 挪走 → 底图
    user32.SetWindowPos(hw, None, -4000, -4000, 0, 0, 0x0001 | 0x0004)
    time.sleep(0.9)
    before = grab(tx, ty, w, h)
    # ② 挪回 → 再截
    user32.SetWindowPos(hw, None, tx, ty, 0, 0, 0x0001 | 0x0004)
    time.sleep(1.4)
    after = grab(tx, ty, w, h)
    after.save(os.path.join(ROOT, 'tools', 'visual_shots', 'alpha_screen_check.png'))
    bp, ap = before.load(), after.load()
    # 取底部空白条（没有文字）统计。
    # 用**中位数**而不是平均值：右下角有个缩放提示（三小块），
    # 平均值会被那几���像素拉高，误判成"不透明"。
    y0 = int(h * 0.78)
    diffs = sorted(max(abs(bp[x, y][i] - ap[x, y][i]) for i in range(3))
                   for y in range(y0, h - 4, 2) for x in range(3, w - 12, 3))
    med = diffs[len(diffs) // 2] if diffs else 255
    p90 = diffs[int(len(diffs) * 0.9)] if diffs else 255
    print('    底图角点=%s  之后角点=%s  空白区差异中位数=%d / 90分位=%d'
          % (bp[8, y0 + 2], ap[8, y0 + 2], med, p90))
    check('背景 0% 时屏幕上真的透明（空白区与底图一致）', med < 8 and p90 < 40,
          '中位数 %d / 90分位 %d（>8 说明底下压着一块不透明的东西）' % (med, p90))

    if app:
        app._cleanup()
    if proc:
        kill_tree(proc.pid)
    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %s' % FAILS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
