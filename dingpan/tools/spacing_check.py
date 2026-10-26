# -*- coding: utf-8 -*-
"""悬浮窗内部间距（padX / padY / rowGap / colGap / padMode）离线回归测试。

不联网、不创建窗口：只验证 compute_pad 的「自适应 / 手动 / 越界夹紧」逻辑，
以及配置、显示方案、布局（content_width / column_widths）是否正确接入 4 维间距。

跑法：python tools/spacing_check.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

import dingpan.widget as widget
import dingpan.storage as storage
from dingpan.settings import SettingsWindow as SW

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


print('1) compute_pad —— 自适应（auto）随字号缩放 4 维')
check('auto fs=10 -> (5, 2, 2, 4)',
      widget.compute_pad({'padMode': 'auto'}, 10), (5, 2, 2, 4))
check('auto fs=13 -> (6, 3, 3, 5)',
      widget.compute_pad({'padMode': 'auto'}, 13), (6, 3, 3, 5))
check('auto fs=20 -> (10, 5, 4, 7)',
      widget.compute_pad({'padMode': 'auto'}, 20), (10, 5, 4, 7))
# 缺省 padMode 也应按 auto 处理
check('缺省 padMode -> auto', widget.compute_pad({}, 13), (6, 3, 3, 5))

print('2) compute_pad —— 手动（custom）原样返回并夹紧')
check('custom 20/8/6/10',
      widget.compute_pad({'padMode': 'custom', 'padX': 20, 'padY': 8,
                          'rowGap': 6, 'colGap': 10}, 13), (20, 8, 6, 10))
check('custom 缺省 -> 6/4/4/6',
      widget.compute_pad({'padMode': 'custom'}, 13), (6, 4, 4, 6))
check('custom padX 越界 999 -> 80',
      widget.compute_pad({'padMode': 'custom', 'padX': 999}, 13)[0], 80)
check('custom padY 越界 -5 -> 0',
      widget.compute_pad({'padMode': 'custom', 'padY': -5}, 13)[1], 0)
check('custom rowGap 越界 999 -> 40',
      widget.compute_pad({'padMode': 'custom', 'rowGap': 999}, 13)[2], 40)
check('custom colGap 越界 999 -> 40',
      widget.compute_pad({'padMode': 'custom', 'colGap': 999}, 13)[3], 40)

print('3) 配置与显示方案带 4 维 pad 键')
check('DEFAULT_CONFIG 含 4 维 pad 键',
      all(k in storage.DEFAULT_CONFIG for k in ('padMode', 'padX', 'padY',
                                                'rowGap', 'colGap')), True)
check("DEFAULT padMode == 'auto'", storage.DEFAULT_CONFIG.get('padMode'), 'auto')
check('DEFAULT rowGap == 4', storage.DEFAULT_CONFIG.get('rowGap'), 4)
check('DEFAULT colGap == 6', storage.DEFAULT_CONFIG.get('colGap'), 6)
check('DISPLAY_KEYS 含 4 维 pad 键',
      all(k in SW.DISPLAY_KEYS for k in ('padMode', 'padX', 'padY',
                                         'rowGap', 'colGap')), True)

print('4) 布局计算：列间距计入总宽 / 列宽可用空间')
# 用最小 FakeW 复用 spacing 布局数学（不创建真实窗口）
import types


class FakeW(widget.Widget):
    def __init__(self, cfg):
        self.cfg = cfg
        self.dpi_scale = 1.0
        self._cols = None
        self._wkey = None
        self._wval = None
        self._mkey = None
        self._mval = None
        self.app = types.SimpleNamespace(group_index=lambda: 0)
        self.quotes = {}

    def client_size(self):
        return (400, 600)

    def row_count(self):
        return 5

    def name_row_two_line(self):
        return False

    def measure_columns(self):
        return ([80, 60, 60], [60, 40, 40])

    def col_plan(self):
        return (['name', 'price', 'changePct'], 'fixed')


# 3 列：natural 和 = 200。custom colGap=10 → 总宽应 = 200 + padX*2 + colGap*2
fw = FakeW({'padMode': 'custom', 'padX': 10, 'padY': 5,
            'rowGap': 3, 'colGap': 10})
cw = fw.column_widths(400)
total_content = sum(cw) + fw._pad_x() * 2 + fw._col_gap() * 2
check('3 列列宽之和 + 左右边距 + 2 列间距 <= 400', total_content <= 400, True)
# 自定义值被原样采用（证明 custom 模式不会被 auto 覆盖 → 改了会生效）
check('custom 模式 _pad_x 采用 10', fw._pad_x(), 10)
check('custom 模式 _col_gap 采用 10', fw._col_gap(), 10)
check('custom 模式 _row_gap 采用 3', fw._row_gap(), 3)

# 自适应：列间距应 > 0（名称↔价格之间确实有间距）
fw_auto = FakeW({'padMode': 'auto'})
check('auto colGap > 0（名称↔价格有间距）', fw_auto._col_gap() > 0, True)

print('')
print('%d 项检查，%d 项失败' % (PASS + FAIL, FAIL))
if FAIL == 0:
    print('全部通过 ✓')
    sys.exit(0)
else:
    sys.exit(1)
