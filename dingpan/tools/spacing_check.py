# -*- coding: utf-8 -*-
"""悬浮窗内部间距（padX / padY / padMode）离线回归测试。

不联网、不创建窗口：只验证 compute_pad 的「自适应 / 手动 / 越界夹紧」三档逻辑，
以及配置与显示方案是否正确带上了 padMode / padX / padY。

跑法：python tools/spacing_check.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

import dingpan.widget as widget
import dingpan.storage as storage
from dingpan.settings import SettingsWindow

PASS = 0
FAIL = 0


def check(desc, got, want):
    global PASS, FAIL
    ok = (got == want)
    if ok:
        PASS += 1
        print('  ✓ %s   (got %s)' % (desc, got))
    else:
        FAIL += 1
        print('  ✗ %s   (got %s, want %s)' % (desc, got, want))


print('1) compute_pad —— 自适应（auto）随字号缩放')
check('auto fs=10 -> (5, 2)', widget.compute_pad({'padMode': 'auto'}, 10), (5, 2))
check('auto fs=13 -> (6, 3)', widget.compute_pad({'padMode': 'auto'}, 13), (6, 3))
check('auto fs=20 -> (10, 5)', widget.compute_pad({'padMode': 'auto'}, 20), (10, 5))
# 缺省 padMode 也应按 auto 处理
check('缺省 padMode -> auto', widget.compute_pad({}, 13), (6, 3))

print('2) compute_pad —— 手动（custom）原样返回并夹紧到 0~40')
check('custom 20/8', widget.compute_pad({'padMode': 'custom', 'padX': 20, 'padY': 8}, 13), (20, 8))
check('custom 缺省 -> 6/4', widget.compute_pad({'padMode': 'custom'}, 13), (6, 4))
check('custom 越界 999 -> 40', widget.compute_pad({'padMode': 'custom', 'padX': 999}, 13)[0], 40)
check('custom 越界 -5 -> 0', widget.compute_pad({'padMode': 'custom', 'padY': -5}, 13)[1], 0)

print('3) 配置与显示方案带 pad 键')
check('DEFAULT_CONFIG 含 padMode/padX/padY',
      all(k in storage.DEFAULT_CONFIG for k in ('padMode', 'padX', 'padY')), True)
check("DEFAULT padMode == 'auto'",
      storage.DEFAULT_CONFIG.get('padMode'), 'auto')
check('DISPLAY_KEYS 含 padMode/padX/padY',
      all(k in SettingsWindow.DISPLAY_KEYS for k in ('padMode', 'padX', 'padY')), True)

print('4) 显示方案快照含 pad（_default_display 合并 DEFAULT）')
from dingpan.settings import SettingsWindow as SW
# _default_display 是实例方法，这里用类默认配置模拟其逻辑：
base = {k: storage.DEFAULT_CONFIG.get(k) for k in SW.DISPLAY_KEYS}
check('默认显示快照含 padMode', 'padMode' in base, True)
check('默认显示快照 padX=6', base.get('padX'), 6)

print('')
print('%d 项检查，%d 项失败' % (PASS + FAIL, FAIL))
if FAIL == 0:
    print('全部通过 ✓')
    sys.exit(0)
else:
    sys.exit(1)
