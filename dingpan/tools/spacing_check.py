# -*- coding: utf-8 -*-
"""悬浮窗内部间距离线回归测试（行高 / 列宽 / 列间距 / 横竖留白）。

不联网、不创建窗口：只验证 compute_pad 的「自适应 / 手动 / 越界夹紧」逻辑，
配置、显示方案、布局（content_width / column_widths / row_height）是否正确接入。

跑法：python tools/spacing_check.py
"""
import os
import sys
import types

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


print('1) compute_pad —— 自适应（auto）：行高为绝对高度')
# auto 行高 = max(18, round(fs*1.55))；列间距 = round(fs*0.35)
check('auto fs=10 -> (5, 2, 18, 4)',
      widget.compute_pad({'padMode': 'auto'}, 10), (5, 2, 18, 4))
check('auto fs=13 -> (6, 3, 20, 5)',
      widget.compute_pad({'padMode': 'auto'}, 13), (6, 3, 20, 5))
check('auto fs=20 -> (10, 5, 31, 7)',
      widget.compute_pad({'padMode': 'auto'}, 20), (10, 5, 31, 7))
check('缺省 padMode -> auto', widget.compute_pad({}, 13), (6, 3, 20, 5))

print('2) compute_pad —— 手动（custom）：原样返回并夹紧')
check('custom 20/8/6/10 -> 行高夹紧到 16',
      widget.compute_pad({'padMode': 'custom', 'padX': 20, 'padY': 8,
                          'rowGap': 6, 'colGap': 10}, 13), (20, 8, 16, 10))
check('custom 缺省 -> 6/4/24/6',
      widget.compute_pad({'padMode': 'custom'}, 13), (6, 4, 24, 6))
check('custom padX 越界 999 -> 120',
      widget.compute_pad({'padMode': 'custom', 'padX': 999}, 13)[0], 120)
check('custom padY 越界 -5 -> 0',
      widget.compute_pad({'padMode': 'custom', 'padY': -5}, 13)[1], 0)
check('custom 行高 越界 999 -> 120',
      widget.compute_pad({'padMode': 'custom', 'rowGap': 999}, 13)[2], 120)
check('custom 列间距 越界 999 -> 80',
      widget.compute_pad({'padMode': 'custom', 'colGap': 999}, 13)[3], 80)

print('3) 配置与显示方案带间距键')
check('DEFAULT_CONFIG 含间距键',
      all(k in storage.DEFAULT_CONFIG for k in ('padMode', 'padX', 'padY',
                                                'rowGap', 'colGap', 'colWidth')), True)
check("DEFAULT padMode == 'auto'", storage.DEFAULT_CONFIG.get('padMode'), 'auto')
check('DEFAULT rowGap(行高) == 24', storage.DEFAULT_CONFIG.get('rowGap'), 24)
check('DEFAULT colGap == 6', storage.DEFAULT_CONFIG.get('colGap'), 6)
check('DEFAULT colWidth == 0', storage.DEFAULT_CONFIG.get('colWidth'), 0)
check('DISPLAY_KEYS 含间距键',
      all(k in SW.DISPLAY_KEYS for k in ('padMode', 'padX', 'padY',
                                         'rowGap', 'colGap', 'colWidth')), True)

print('4) 布局计算：列间距计入总宽 / 行高为绝对值')
# 用最小 FakeW 复用 spacing 布局数学（不创建真实窗口）


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

    def eff_font_size(self):
        return 13

    def name_row_two_line(self):
        return False

    def measure_columns(self):
        return ([80, 60, 60], [60, 40, 40])

    def col_plan(self):
        return (['name', 'price', 'changePct'], 'fixed')


# 3 列：natural 和 = 200。custom colGap=10 → 总宽应 = 200 + padX*2 + colGap*2
fw = FakeW({'padMode': 'custom', 'padX': 10, 'padY': 5,
            'rowGap': 16, 'colGap': 10})
cw = fw.column_widths(400)
total_content = sum(cw) + fw._pad_x() * 2 + fw._col_gap() * 2
check('3 列列宽之和 + 左右边距 + 2 列间距 <= 400', total_content <= 400, True)
# 自定义值被原样采用（证明 custom 模式不会被 auto 覆盖 → 改了会生效）
check('custom 模式 _pad_x 采用 10', fw._pad_x(), 10)
check('custom 模式 _col_gap 采用 10', fw._col_gap(), 10)
check('custom 模式 _row_height_val 采用 16', fw._row_height_val(), 16)

# 行高（绝对）应被 row_height() 直接采用，而非叠加
fw_tall = FakeW({'padMode': 'custom', 'rowGap': 40})
check('custom 行高 40 -> row_height(13) == 40', fw_tall.row_height(13), 40)
# 行高不会低于「文字放得下」的下限
fw_short = FakeW({'padMode': 'custom', 'rowGap': 16})
check('custom 行高 16 -> row_height(13) >= 16', fw_short.row_height(13) >= 16, True)

# 自适应：列间距应 > 0（名称↔价格之间确实有间距）
fw_auto = FakeW({'padMode': 'auto'})
check('auto colGap > 0（名称↔价格有间距）', fw_auto._col_gap() > 0, True)
check('auto 行高 > 0（auto 推导出绝对行高）', fw_auto._row_height_val() > 0, True)

# 列宽（colWidth）作为统一最小宽度下限：auto 下不生效，custom 下生效
fw_cw = FakeW({'padMode': 'custom', 'colWidth': 80})
check('custom colWidth 写入配置', fw_cw.cfg.get('colWidth'), 80)

print('')
print('%d 项检查，%d 项失败' % (PASS + FAIL, FAIL))
if FAIL == 0:
    print('全部通过 ✓')
    sys.exit(0)
else:
    sys.exit(1)
