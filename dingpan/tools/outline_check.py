# -*- coding: utf-8 -*-
"""回归测试：文字描边选「关闭」时，蒙版 pass 不得给文字外加 1px 高不透明度 halo。

历史坑（v1.0.26）：颜色 pass 不画描边了，但蒙版 pass 仍无条件给每个字形外扩 1px。
那圈 halo 在蒙版里是「内容」→ 拿到文字不透明度（tx_a），而周围背景仍是 bg_a。
背景半透明+浅色、桌面深色时，这圈比背景更不透明的亮边就变成明显的描边，
看着像「描边明明关了还在」。本测试直接渲染蒙版 DIB，数「内容像素」来抓这个回归。
"""
import ctypes
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ⚠️ 隔离 APPDATA / 程序目录：测试绝不碰用户真实配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpoutline_')
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import storage                 # noqa: E402
from dingpan.widget import Widget, Theme    # noqa: E402
from dingpan.win32 import user32            # noqa: E402

FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name,
                         (' — ' + str(extra)) if extra != '' else ''))
    if not cond:
        FAILS.append(name)


class StubApp:
    def __init__(self, cfg):
        self.cfg = cfg

    def group_index(self):
        return 0


def make_widget(cfg, w=420, h=400):
    app = StubApp(cfg)
    wd = Widget(app)
    wd.cfg = cfg
    wd.theme = Theme(cfg)
    wd.dpi_scale = 1.0
    hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
    wd.hwnd = user32.CreateWindowExW(
        0x00000080, 'STATIC', '', 0x80000000, 0, 0, w, h,
        None, None, hinst, None)
    return wd


def mask_content_count(wd, w, h):
    """渲染一次（颜色 + 蒙版 pass），返回蒙版里「内容」像素数（blue==0 即黑=内容）。

    注：真实窗口下 UpdateLayeredWindow 会成功；本测试用普通 STATIC 窗口，
    ULW 必然失败并走兜底，但颜色/蒙版两次 _draw_all 已经在离屏 DIB 上画完，
    所以仍可读到蒙版字节来判断 halo 是否存在。
    """
    wd._paint_layered(w, h, 14)
    lay = wd._lay
    n = w * h
    mask = ctypes.string_at(lay['mbits'].value, n * 4)
    cnt = 0
    for i in range(0, n * 4, 4):
        if mask[i] == 0:      # mask: 白底(255)=背景，黑(0)=内容
            cnt += 1
    return cnt


def main():
    base = json.loads(json.dumps(storage.DEFAULT_CONFIG))
    base['groups'] = [{'id': 'g', 'name': '默认',
                       'stocks': [{'code': 'sh600519', 'name': '贵州茅台'},
                                  {'code': 'sz000001', 'name': '平安银行'}]}]
    # 背景较实（bg_a>=60）→ auto 在此背景下应与「关闭」等价
    base['bgAlpha'] = 80

    print('=== 文字描边关闭时不得出现蒙版 halo（v1.0.27 回归）===')
    cfg_off = json.loads(json.dumps(base));   cfg_off['textOutline'] = 'off'
    cfg_on = json.loads(json.dumps(base));    cfg_on['textOutline'] = 'on'
    cfg_auto = json.loads(json.dumps(base));  cfg_auto['textOutline'] = 'auto'

    cnt_off = mask_content_count(make_widget(cfg_off), 420, 400)
    cnt_on = mask_content_count(make_widget(cfg_on), 420, 400)
    cnt_auto = mask_content_count(make_widget(cfg_auto), 420, 400)
    print('    off=%d  on=%d  auto(bg80)=%d' % (cnt_off, cnt_on, cnt_auto))

    check('off 的内容像素严格少于 on（关闭后无 halo）',
          cnt_off < cnt_on, 'off=%d on=%d' % (cnt_off, cnt_on))
    check('off/on 的 halo 差值足够大（>50px，确属描边外扩）',
          cnt_on - cnt_off > 50, 'delta=%d' % (cnt_on - cnt_off))
    check('auto(背景较实) 与 off 基本相等（auto 在此背景不描边）',
          abs(cnt_auto - cnt_off) < 50, 'auto=%d off=%d' % (cnt_auto, cnt_off))
    check('on 的内容像素多于 auto（on 始终描边）',
          cnt_on > cnt_auto, 'on=%d auto=%d' % (cnt_on, cnt_auto))

    print('\n=== auto 在背景很透(bg_a<60)时应描边 ===')
    cfg_auto_t = json.loads(json.dumps(base))
    cfg_auto_t['textOutline'] = 'auto'
    cfg_auto_t['bgAlpha'] = 20
    cnt_auto_t = mask_content_count(make_widget(cfg_auto_t), 420, 400)
    print('    auto(bg20)=%d  off=%d' % (cnt_auto_t, cnt_off))
    check('auto(背景很透) 的内容像素多于 off（此时应描边）',
          cnt_auto_t > cnt_off, 'auto_t=%d off=%d' % (cnt_auto_t, cnt_off))

    print('\n' + ('全部通过 ✓' if not FAILS else '失败项: ' + ', '.join(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
