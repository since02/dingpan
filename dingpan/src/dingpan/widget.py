"""
悬浮窗：自绘无边框置顶窗口
- 分层透明窗口（WS_EX_LAYERED）实现圆角 + 整体透明度
- 双缓冲 GDI 绘制，避免闪烁
- 标题栏拖拽、滚轮、分组标签切换
"""
import ctypes
from ctypes import wintypes

from . import win32 as w32
from .win32 import (gdi32, user32, ctypes as _ct)

# 颜色（COLORREF）
C_TRANSPARENT = 0x00000000


class Theme:
    """配色方案

    - dark / light：内置两套
    - custom：背景色、文字色来自配置（customBg / customText），
      其余层级色按背景明暗自动派生，保证任何自定义配色下都不糊在一起。
    涨跌色统一读取 upColor / downColor，所有主题共用。
    """

    def __init__(self, cfg):
        theme = cfg.get('theme', 'dark')
        if theme == 'custom':
            bg = _parse_hex(cfg.get('customBg', '#1c1f28'))
            text = _parse_hex(cfg.get('customText', '#e6e8ef'))
            dim = _mix(text, bg, 0.40)            # 次要文字：向背景靠
            panel = _shift(bg, 0.07)
            border = _shift(bg, 0.14)
            header = _shift(bg, 0.05)
            accent = _shift(bg, 0.20)
        elif theme == 'light':
            bg = _parse_hex('#f7f9fc')
            text = _parse_hex('#1c1f28')
            dim = _parse_hex('#6b7280')
            panel = _parse_hex('#ffffff')
            border = _parse_hex('#d8dde6')
            header = _parse_hex('#eef1f6')
            accent = _parse_hex('#e3e9f2')
        else:
            bg = _parse_hex('#1c1f28')
            text = _parse_hex('#e6e8ef')
            dim = _parse_hex('#9aa1b1')
            panel = _parse_hex('#262a35')
            border = _parse_hex('#343947')
            header = _parse_hex('#232733')
            accent = _parse_hex('#3a4050')

        up = _parse_hex(cfg.get('upColor') or '#f6465d')
        down = _parse_hex(cfg.get('downColor') or '#0ecb81')

        self.bg = bg
        self.text = text
        self.dim = dim
        self.up = up
        self.down = down
        self.panel = panel
        self.border = border
        self.header = header
        self.accent = accent
        self.flat = dim
        # 文字描边色：None = 不描边。背景越透明时描边越重要（保证文字可读），
        # 由 _paint_layered 按背景不透明度决定（智能描边）。
        self.outline = None


def _lum(c):
    """COLORREF → 亮度 0-255"""
    return int(0.299 * (c & 0xFF) + 0.587 * ((c >> 8) & 0xFF) + 0.114 * ((c >> 16) & 0xFF))


def _shift(c, ratio):
    """按背景明暗自动向白/黑微调，用于派生分层底色"""
    return _mix(c, 255 if _lum(c) < 128 else 0, ratio)


def _alpha_lut(bg_a, tx_a):
    """蒙版值 0(内容)..255(背景) → 输出 alpha。

    背景像素 → bg_a，内容（文字/线条）像素 → tx_a。
    两条通道彻底独立：调背景透明度不会影响文字，调文字透明度也不会影响背景。
    """
    return bytes(int(tx_a + (bg_a - tx_a) * v / 255.0 + 0.5) for v in range(256))


class MaskTheme:
    """蒙版绘制用配色：底色纯白、内容纯黑，用来生成 1 通道覆盖度"""

    def __init__(self):
        self.bg = 0x00FFFFFF
        self.text = 0x00000000
        self.dim = 0x00000000
        self.up = 0x00000000
        self.down = 0x00000000
        self.panel = 0x00FFFFFF
        self.border = 0x00000000
        self.header = 0x00FFFFFF
        self.accent = 0x00000000
        self.flat = 0x00000000


def _parse_hex(h):
    h = str(h or '').lstrip('#')
    if len(h) != 6:
        h = '1c1f28'
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        r, g, b = 28, 31, 40
    return w32.rgb(r, g, b)


def _mix(c, target, ratio):
    """按比例向目标色混合"""
    r = c & 0xFF
    g = (c >> 8) & 0xFF
    b = (c >> 16) & 0xFF
    r = int(r + (target - r) * ratio)
    g = int(g + (target - g) * ratio)
    b = int(b + (target - b) * ratio)
    return w32.rgb(r, g, b)


def _darker(c, ratio=0.18):
    r = int((c & 0xFF) * (1 - ratio))
    g = int(((c >> 8) & 0xFF) * (1 - ratio))
    b = int(((c >> 16) & 0xFF) * (1 - ratio))
    return w32.rgb(r, g, b)


# 字段定义：key, 标题, 宽度系数, 对齐
COLUMN_DEFS = [
    ('name', '名称', 1.6, 'left'),
    ('code', '代码', 0.85, 'right'),
    ('price', '现价', 0.78, 'right'),
    ('change', '涨跌', 0.72, 'right'),
    ('changePct', '涨跌幅', 0.78, 'right'),
    ('open', '今开', 0.68, 'right'),
    ('high', '最高', 0.68, 'right'),
    ('low', '最低', 0.68, 'right'),
    ('prevClose', '昨收', 0.68, 'right'),
    ('volume', '成交量', 0.82, 'right'),
    ('amount', '成交额', 0.85, 'right'),
    ('turnover', '换手', 0.6, 'right'),
    ('pe', '市盈', 0.6, 'right'),
    ('pb', '市净', 0.6, 'right'),
    ('amplitude', '振幅', 0.6, 'right'),
    ('floatCap', '流通值', 0.75, 'right'),
    ('totalCap', '总市值', 0.75, 'right'),
    ('time', '时间', 0.72, 'right'),
]
COLUMN_MAP = {c[0]: c for c in COLUMN_DEFS}

# 标题栏按钮（x 偏移相对窗口右边界）
BTN_W = 22
BTN_H = 26

# 右下角拖动改大小的热区边长
GRIP_SIZE = 16


class Widget:
    """悬浮行情窗"""

    def __init__(self, app):
        self.app = app
        self.hwnd = None
        self.cfg = {}
        self.theme = None
        self.quotes = {}
        self.prev_prices = {}
        self.rows = []
        self.row_h = 24
        self.header_h = 28
        self.tabs_h = 24
        self.status_h = 20
        self.body_h = 0
        self.body_bottom = 0
        self._rows_top = 0
        self._visible_rows = 1
        self.scroll = 0
        self.max_scroll = 0
        self.dpi_scale = 1.0        # 由 App 在创建窗口后按系统缩放设置
        self.dragging = False
        self.drag_off = (0, 0)
        self.selected = -1
        self.hover_btn = -1
        self.hover_row = -1
        self.status_text = '加载中…'
        self.status_ok = True
        self.status_warn = False   # 缓存快照等「非实时但正常」的状态
        self.last_update = ''
        self._fonts = {}
        self._dc = None
        self._bmp = None
        self._memdc = None
        self._oldsize = (0, 0)
        # 分层窗口双缓冲（颜色 pass + 蒙版 pass）
        self._lay = None
        # 列宽缓存：一次绘制内只测量一遍
        self._wkey = None
        self._wval = None
        self._mkey = None          # 列自然宽度的缓存
        self._mval = None

    # ---------------- 字体 ----------------
    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self._fonts:
            name = self.cfg.get('fontFamily') or 'Microsoft YaHei'
            self._fonts[key] = w32.make_font(name, size, bold)
        return self._fonts[key]

    def release_fonts(self):
        for f in self._fonts.values():
            gdi32.DeleteObject(f)
        self._fonts.clear()

    # ---------------- 尺寸 ----------------
    def client_size(self):
        r = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        return r.right - r.left, r.bottom - r.top

    def layout(self):
        """计算各区域高度"""
        w, h = self.client_size()
        fs = self.eff_font_size()
        show = self.cfg.get('showHeader', True)
        self.header_h = max(26, int(28 * self.dpi_scale)) if show else 0
        self.tabs_h = (max(22, int(24 * self.dpi_scale)) if show else 0)
        self.status_h = max(18, int(20 * self.dpi_scale)) if self.cfg.get('showStatus', True) else 0
        # 名称+代码两行时行高要够；只画一行时用单行高度，窗口更紧凑
        if self.name_row_two_line():
            self.row_h = max(24, int(fs * 2.15))
        else:
            self.row_h = max(18, int(fs * 1.55))
        head_h = (fs + 5) if self.cfg.get('showTableHead', True) else 0
        self.body_h = max(40, h - self.header_h - self.tabs_h - head_h - self.status_h)
        self.body_bottom = max(self.header_h + self.tabs_h + head_h, h - self.status_h)
        self.head_h = head_h

    def eff_font_size(self):
        """字号按系统缩放放大，150% 屏上不会小得看不清"""
        try:
            base = float(self.cfg.get('fontSize', 13))
        except (TypeError, ValueError):
            base = 13.0
        return max(9, int(round(base * (self.dpi_scale or 1.0))))

    # ---------------- 列显示方案 ----------------
    def col_plan(self):
        """算出「实际画哪些列」和「名称列怎么画」。

        v1.0.15 起**完全以「显示字段」页里勾选的列为准**：
        - 「名称」在已选列表里 → 有名称列
        - 「代码」在已选列表里 → 有独立的代码列
        两者彻底独立，各自勾选各自显示，名称列不再塞第二行代码。
        （旧的 showName / showCode 开关已从基础设置移除，
          保存时由 settings._collect 根据 columns 反向同步回去，保证配置一致。）

        返回 (列 key 列表, 名称列模式) —— 模式取值 none / name
        """
        cols = [c for c in (self.cfg.get('columns') or []) if c in COLUMN_MAP]
        mode = 'name' if 'name' in cols else 'none'
        eff = list(cols)
        return eff, mode

    def name_display_text(self, name):
        """按「名称最多显示字符数」截断（0 / 未设置 = 全部显示）"""
        s = str(name or '--')
        try:
            n = int(self.cfg.get('nameChars', 0) or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0 and len(s) > n:
            return s[:n] + '…'
        return s

    # ---------------- 尺寸自适应 ----------------
    MAX_VISIBLE_ROWS = 30      # 自适应时最多展开多少行，超出就滚动

    def content_width(self):
        """内容需要的总宽度（各列自然宽度之和 + 内边距）"""
        natural, _mins = self.measure_columns()
        if not natural:
            return 320
        return sum(natural) + 12

    def row_count(self):
        """当前分组有多少只自选股"""
        groups = self.cfg.get('groups') or []
        idx = self.app.group_index()
        stocks = groups[idx].get('stocks', []) if 0 <= idx < len(groups) else []
        # 取消勾选的（enabled=False）不显示，但仍保留在列表里，随时能勾回来
        stocks = [s for s in stocks if s.get('enabled', True)]
        return len(stocks)

    def needed_size(self):
        """窗口「按内容自适应」时应有的尺寸 (宽, 高)

        宽 = 各列自然宽度之和 + 内边距
        高 = 标题栏 + 分组标签 + 列表表头 + 可见行数×行高 + 状态栏
        """
        fs = self.eff_font_size()
        show = self.cfg.get('showHeader', True)
        header_h = max(26, int(28 * self.dpi_scale)) if show else 0
        tabs_h = (max(22, int(24 * self.dpi_scale)) if show else 0)
        status_h = max(18, int(20 * self.dpi_scale)) if self.cfg.get('showStatus', True) else 0
        head_h = (fs + 5) if self.cfg.get('showTableHead', True) else 0
        row_h = max(18, int(fs * 1.55))
        n = self.row_count()
        rows = max(1, min(n if n else 1, self.MAX_VISIBLE_ROWS))
        h = header_h + tabs_h + head_h + rows * row_h + status_h + 4
        # 再加一点余量，避免最后一行的下缘贴边
        h += 4
        w = max(220, min(self.content_width(), 1600))
        return w, max(120, h)

    def name_row_two_line(self):
        """名称列是否占两行（决定行高）"""
        _eff, mode = self.col_plan()
        return mode == 'both'

    def _text_px(self, hdc, s, hfont):
        """测量文本像素宽度"""
        if not s:
            return 0
        gdi32.SelectObject(hdc, hfont)
        sz = wintypes.SIZE()
        gdi32.GetTextExtentPoint32W(hdc, ctypes.c_wchar_p(s), len(s), ctypes.byref(sz))
        return sz.cx

    def measure_columns(self):
        """测量各列的「自然宽度」与「可读下限」（与窗口宽度无关）。

        返回 (natural, mins)：
          natural[i] —— 这一列按内容需要多宽
          mins[i]    —— 压到多窄就还能读（数值列=表头宽，名称列=64，代码列=内容宽）

        抽出来的原因：窗口要「按内容自适应」，得先知道内容到底需要多宽，
        才能算出该把窗口设成多宽 —— 而 column_widths 是「给定宽度再分配」。
        """
        eff, mode = self.col_plan()
        groups = self.cfg.get('groups') or []
        idx = self.app.group_index()
        stocks = groups[idx].get('stocks', []) if 0 <= idx < len(groups) else []
        # 取消勾选的（enabled=False）不显示，但仍保留在列表里，随时能勾回来
        stocks = [s for s in stocks if s.get('enabled', True)]
        cache_key = (tuple(eff), mode, self.eff_font_size(), idx,
                     tuple(s.get('code') for s in stocks[:40]),
                     self.cfg.get('nameChars', 0),
                     tuple(sorted(self.quotes.keys())))
        if self._mkey == cache_key and self._mval is not None:
            return self._mval

        defs = [COLUMN_MAP[c] for c in eff]
        if not defs:
            self._mkey, self._mval = cache_key, ([], [])
            return self._mval
        fs = self.eff_font_size()
        normal = self.font(fs)
        small = self.font(max(10, fs - 2))

        # 收集各列显示文本（有行情用实际值，否则用占位样本预留宽度）
        old_theme = self.theme
        self.theme = Theme(self.cfg)          # _cell_value 需要主题配色
        texts = {d[0]: set() for d in defs}
        placeholders = {
            'name': '名称占位四个字', 'code': 'sh600000', 'price': '8888.88',
            'change': '+88.88', 'changePct': '+10.00%', 'open': '8888.88',
            'high': '8888.88', 'low': '8888.88', 'prevClose': '8888.88',
            'volume': '888.8万', 'amount': '88.88亿', 'turnover': '88.88%',
            'pe': '888.88', 'pb': '88.88', 'amplitude': '88.88%',
            'floatCap': '8888亿', 'totalCap': '8888亿', 'time': '88:88',
        }
        for st in stocks[:40]:
            q = self.quotes.get(st.get('code'), {})
            for d in defs:
                key = d[0]
                if key == 'name':
                    texts[key].add(self.name_display_text(
                        q.get('name') or st.get('name') or '--'))
                elif key == 'code':
                    texts[key].add(st.get('code') or '--')
                else:
                    val, _c = self._cell_value(q, key)
                    if val == '--':
                        # 这一列还没行情 → 用代表性占位宽度预留。
                        # 不预留的话，窗口建出来是「窄的」，等行情到了再突然变宽，
                        # 视觉上会跳一下（实测 309px → 379px）。
                        texts[key].add(placeholders.get(key, '8888.88'))
                        if key in ('change', 'changePct', 'turnover', 'amplitude'):
                            texts[key].add('-' + placeholders.get(key, '+88.88'))
                    else:
                        texts[key].add(val)
        self.theme = old_theme

        # 整列都没有任何文本时（理论上不会），给个兜底
        for d in defs:
            key = d[0]
            if not texts[key]:
                texts[key].add(placeholders.get(key, '8888.88'))

        hdc = user32.GetDC(self.hwnd)
        try:
            natural = []
            mins = []          # 每列的「可读下限」：压到这里就不会出现省略号
            for d in defs:
                key = d[0]
                hf = small if key in ('code', 'time') else normal
                head_w = self._text_px(hdc, d[1], small) + 12      # 表头
                content_w = 0
                for s in texts[key]:
                    # 内容宽度 + 8 就够：绘制时右对齐列用 max_w=cw-6、
                    # 左对齐的名称列用 max_w=cw-4，留 8px 已经是安全余量。
                    # 原来给 +12/+16，7 列就多占 30 多像素，
                    # 宽度紧张时会把代码列挤到出现省略号。
                    content_w = max(content_w, self._text_px(hdc, s, hf) + 8)
                natural.append(max(34, head_w, content_w))
                if key == 'name':
                    # 名称可以截断（前几个字就能认出股票），保底 64
                    mins.append(64)
                elif key == 'code':
                    # 代码是标识列：压到内容宽度就不再压，宁可别的一列让位置
                    mins.append(max(40, content_w))
                else:
                    # 数值列：保底 = 表头宽度 + 8。
                    # 下限比内容宽度低 → 才有可压缩的余量，
                    # 否则所有列都到下限后溢出就只能由最后一列承担（会出现截断）。
                    mins.append(max(40, head_w + 8))
                # 下限不能超过实际需求，否则「可削减余量」算出来是负数
                mins[-1] = min(mins[-1], natural[-1])
        finally:
            user32.ReleaseDC(self.hwnd, hdc)

        self._mkey, self._mval = cache_key, (natural, mins)
        return self._mval

    def column_widths(self, total_w):
        """按实际文本测量自适应列宽；剩余空间全部给名称列"""
        eff, mode = self.col_plan()
        cache_key = (total_w, tuple(eff), mode, self.eff_font_size(),
                     self.app.group_index(), len(self.quotes))
        if self._wkey == cache_key and self._wval is not None:
            return self._wval
        defs = [COLUMN_MAP[c] for c in eff]
        if not defs:
            self._wkey, self._wval = cache_key, []
            return []
        pad = 12
        avail = max(120, total_w - pad)
        natural, mins = self.measure_columns()

        total = sum(natural)
        # 名称列下标（用户可以重排列序，不能假设是第 0 列）
        name_i = -1
        for i, d in enumerate(defs):
            if d[0] == 'name':
                name_i = i
                break
        if total <= avail:
            # 有富余：全部给名称列
            extra = avail - total
            natural[name_i if name_i >= 0 else 0] += extra
            self._wkey, self._wval = cache_key, natural
            return natural

        # 超出：按「谁最经得起截断」排序来削减
        #   ① 名称列 —— 截断了还能认出股票（保底 64），所以第一个让它让位置
        #   ② 数值列 —— 压到表头宽度为止（只有数字特别长时才会出现省略号）
        #   ③ 代码列 —— 标识列，最后才动
        # 反过来先压数值列，会把「1688.00」压成「1688.…」，比名称截断更糟。
        overflow = total - avail

        nums = [i for i in range(len(defs)) if i != name_i and defs[i][0] != 'code']
        codes = [i for i in range(len(defs)) if defs[i][0] == 'code']

        def squeeze(idxs):
            """在 idxs 之间按「超出下限的幅度」分摊压缩。

            注意：int() 取整会让各列实际削减量之和小于 cut，
            必须把零头补给余量最大的那一列，否则 overflow 账目对不上，
            最后一列会被「修正舍入误差」无端削掉几像素。
            """
            nonlocal overflow
            if not idxs or overflow <= 0:
                return
            excess = [max(0, natural[i] - mins[i]) for i in idxs]
            ex_total = sum(excess)
            if ex_total <= 0:
                return
            cut = min(overflow, ex_total)
            shares = [int(cut * e / ex_total) for e in excess]
            for k, i in enumerate(idxs):
                natural[i] = max(mins[i], natural[i] - shares[k])
            rest = cut - sum(shares)
            if rest > 0:
                k = max(range(len(idxs)), key=lambda j: excess[j])
                i = idxs[k]
                natural[i] = max(mins[i], natural[i] - rest)
            overflow -= cut

        # ① 名称列先让
        if name_i >= 0 and overflow > 0:
            can = max(0, natural[name_i] - mins[name_i])
            take = min(can, overflow)
            natural[name_i] -= take
            overflow -= take
        # ② 数值列
        squeeze(nums)
        # ③ 代码列最后
        squeeze(codes)

        # 修正舍入误差：多出来的还给名称列（它最有余量）；
        # 不够的也优先从名称列拿 —— 别让最后一列（常常是「时间」）背锅，
        # 否则时间列会被莫名削掉几像素而出现省略号。
        diff = avail - sum(natural)
        if diff > 0:
            natural[name_i if name_i >= 0 else 0] += diff
        elif diff < 0:
            need_cut = -diff
            order = ([name_i] if name_i >= 0 else []) + \
                    [i for i in range(len(defs)) if i != name_i]
            for i in order:
                if need_cut <= 0:
                    break
                can = max(0, natural[i] - mins[i])
                take = min(can, need_cut)
                natural[i] -= take
                need_cut -= take

        # 连各列下限都放不下（窗口被拖得很窄）：整体按比例缩到窗口宽度内。
        # 宁可每列都略微截断，也不要让最后一列整个跑到窗口外面去 —— 那样
        # 用户会以为「时间」这个字段不见了。
        total_now = sum(natural)
        if total_now > avail:
            scaled = [max(34, int(w * avail / total_now)) for w in natural]
            diff2 = avail - sum(scaled)
            if diff2 > 0:
                # 多出来的按比例分给各列
                for i in range(len(scaled)):
                    add = diff2 // (len(scaled) - i)
                    scaled[i] += add
                    diff2 -= add
            elif diff2 < 0:
                # 要减的：从最宽的列开始减，任何一列都不低于 34
                need = -diff2
                for i in sorted(range(len(scaled)), key=lambda j: scaled[j], reverse=True):
                    if need <= 0:
                        break
                    take = min(scaled[i] - 34, need)
                    scaled[i] -= take
                    need -= take
            natural = scaled

        self._wkey, self._wval = cache_key, natural
        return natural

    def tab_layout(self, total_w):
        """分组标签布局"""
        groups = self.cfg.get('groups') or []
        if not groups:
            return []
        items = []
        x = 8
        for i, g in enumerate(groups):
            label = g.get('name', '')[:8]
            w = 16 + len(label) * 12
            if x + w > total_w - 8:
                break
            items.append((x, w, i, label))
            x += w + 5
        return items

    def paint_now(self):
        """请求重绘（触发 WM_PAINT）"""
        if self.hwnd:
            user32.InvalidateRect(self.hwnd, None, False)

    # ---------------- 绘制 ----------------
    def paint(self):
        if not self.hwnd:
            return
        w, h = self.client_size()
        if w <= 0 or h <= 0:
            return
        self.layout()
        self._wkey = self._wval = None      # 每次绘制重新测量一次列宽
        self._mkey = self._mval = None
        self.theme = Theme(self.cfg)
        fs = self.eff_font_size()
        if self._paint_layered(w, h, fs):
            return
        self._paint_legacy(w, h, fs)

    def _alphas(self):
        """(背景 alpha, 文字 alpha)，0-255"""
        bg = int(max(0, min(100, float(self.cfg.get('bgAlpha', 100))))) * 255 // 100
        tx = int(max(0, min(100, float(self.cfg.get('textAlpha', 100))))) * 255 // 100
        return bg, tx

    def _draw_all(self, dc, w, h, fs):
        """把整窗内容画进指定 DC（颜色 pass 与蒙版 pass 共用）"""
        # 背景铺底（蒙版 pass 里这里是纯白 = 「背景区域」）
        brush = gdi32.CreateSolidBrush(self.theme.bg)
        r = wintypes.RECT(0, 0, w, h)
        user32.FillRect(dc, ctypes.byref(r), brush)
        gdi32.DeleteObject(brush)

        self._draw_header(dc, w, fs)
        if self.tabs_h:
            self._draw_tabs(dc, w, fs)
        if self.cfg.get('showTableHead', True):
            self._draw_table_head(dc, w, fs)
        self._draw_rows(dc, w, fs)
        self._draw_scrollbar(dc, w)
        if self.cfg.get('showStatus', True):
            self._draw_status(dc, w, h, fs)
        # 右下角缩放提示（三个小方块）
        br = gdi32.CreateSolidBrush(self.theme.dim)
        for i in range(3):
            r = wintypes.RECT(w - 4 - i * 5, h - 4 - i * 5, w - 2 - i * 5, h - 2 - i * 5)
            user32.FillRect(dc, ctypes.byref(r), br)
        gdi32.DeleteObject(br)
        # 外框：默认**不画**（用户要求悬浮窗无边框），可在设置里单独打开。
        # 圆角由 alpha 平面的 _round_corners 处理，与这里无关。
        if self.cfg.get('showBorder', False):
            pen = gdi32.CreateSolidBrush(self.theme.border)
            r2 = wintypes.RECT(0, 0, w - 1, h - 1)
            user32.FrameRect(dc, ctypes.byref(r2), pen)
            gdi32.DeleteObject(pen)

    # ---- 分层窗口：背景与文字各自独立透明度（逐像素 alpha） ----
    def _ensure_layered(self, w, h):
        if self._lay and self._lay['size'] == (w, h):
            return self._lay
        self._cleanup_layered()
        lay = {'size': (w, h)}
        for key in ('c', 'm'):
            bmi = w32.BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(w32.BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h          # 负值 = 自上而下
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = w32.BI_RGB
            bits = ctypes.c_void_p()
            dc = gdi32.CreateCompatibleDC(None)
            bmp = gdi32.CreateDIBSection(dc, ctypes.byref(bmi), w32.DIB_RGB_COLORS,
                                         ctypes.byref(bits), None, 0)
            old = gdi32.SelectObject(dc, bmp)
            lay[key + 'dc'] = dc
            lay[key + 'bmp'] = bmp
            lay[key + 'old'] = old
            lay[key + 'bits'] = bits
        self._lay = lay
        return lay

    def _cleanup_layered(self):
        lay = self._lay
        self._lay = None
        if not lay:
            return
        for key in ('c', 'm'):
            try:
                if lay.get(key + 'old'):
                    gdi32.SelectObject(lay[key + 'dc'], lay[key + 'old'])
                if lay.get(key + 'bmp'):
                    gdi32.DeleteObject(lay[key + 'bmp'])
                if lay.get(key + 'dc'):
                    gdi32.DeleteDC(lay[key + 'dc'])
            except Exception:  # noqa: BLE001
                pass

    def _paint_layered(self, w, h, fs):
        """用 UpdateLayeredWindow 提交逐像素 alpha 图像，返回是否成功"""
        try:
            lay = self._ensure_layered(w, h)
            bg_a, tx_a = self._alphas()
            base = self.theme
            self._base_theme = base
            # 智能描边：背景越透明，文字越难看清 → 自动给文字加一圈描边。
            #   这解决「背景调透明后文字看着也变淡」的观感问题
            #   （不透明度数值本身没变，是对比度下降）。
            mode = str(self.cfg.get('textOutline', 'off')).lower()
            if mode == 'off':
                base.outline = None
            elif mode == 'on':
                base.outline = self._outline_color(base)
            else:   # auto
                base.outline = (self._outline_color(base) if bg_a < 200 else None)

            # 1) 颜色 pass：用**原色**，不预乘 alpha
            #    最终的不透明度完全由第 2 步的 alpha 平面决定。
            #    ⚠️ 之前这里先按 alpha 预乘一次、最后 alpha 平面又乘一次
            #    → 透明度被**平方**：文字 50% 实际只剩 25%（看着像"文字透明度不管用"），
            #    而且背景调透明时文字边缘被一起拉淡（"调背景把文字也调了"）。
            #    预乘只做一次、由 alpha 平面统一负责，两条通道才真正独立。
            self.theme = base
            self._draw_all(lay['cdc'], w, h, fs)
            self.theme = base

            # 2) 蒙版 pass：底色纯白、内容纯黑，B 通道即覆盖度
            self.theme = MaskTheme()
            self._draw_all(lay['mdc'], w, h, fs)
            self.theme = base

            n = w * h
            mask = ctypes.string_at(lay['mbits'].value, n * 4)
            table = bytes(_alpha_lut(bg_a, tx_a))
            alpha = bytearray(mask[0::4].translate(table))
            self._round_corners(alpha, w, h)

            color = bytearray(ctypes.string_at(lay['cbits'].value, n * 4))
            color[3::4] = alpha
            ctypes.memmove(lay['cbits'], bytes(color), n * 4)

            # 3) 提交
            pt_dst = wintypes.POINT()
            pt_src = wintypes.POINT(0, 0)
            r = wintypes.RECT()
            user32.GetWindowRect(self.hwnd, ctypes.byref(r))
            pt_dst.x, pt_dst.y = r.left, r.top
            size = wintypes.SIZE(w, h)
            blend = w32.BLENDFUNCTION(w32.AC_SRC_OVER, 0, 255, w32.AC_SRC_ALPHA)
            sdc = user32.GetDC(None)
            try:
                ok = user32.UpdateLayeredWindow(
                    self.hwnd, sdc, ctypes.byref(pt_dst), ctypes.byref(size),
                    lay['cdc'], ctypes.byref(pt_src), 0, ctypes.byref(blend), w32.ULW_ALPHA)
            finally:
                user32.ReleaseDC(None, sdc)
            if ok:
                return True
        except Exception as e:  # noqa: BLE001
            try:
                from .app import log_exception
                log_exception('widget._paint_layered', e)
            except Exception:  # noqa: BLE001
                pass
        # 降级路径：重建 theme，但要**保留 outline**（否则描边设置会丢）
        _ol = getattr(self.theme, 'outline', None)
        self.theme = Theme(self.cfg)
        self.theme.outline = _ol
        return False

    def _outline_color(self, theme):
        """描边色：浅背景用深色描边，深背景用浅色描边（保证有对比）"""
        try:
            lum = _lum(theme.bg)
            if lum > 140:            # 浅背景 → 深色描边
                return 0x00000000
            return 0x00FFFFFF       # 深背景 → 浅色描边
        except Exception:  # noqa: BLE001
            return 0x00000000

    def _round_corners(self, alpha, w, h, radius=10):
        """把四角处理成圆角：alpha 置 0，边缘 1px 做抗锯齿"""
        r = max(0, min(radius, min(w, h) // 2))
        if r <= 0:
            return
        import math
        for y in range(r):
            dy = r - y - 0.5
            dx = r - math.sqrt(max(0.0, r * r - dy * dy))
            cut = int(dx)
            if cut <= 0:
                continue
            base = y * w
            for x in range(cut):
                alpha[base + x] = alpha[base + x] * x // max(1, cut)
                alpha[base + w - 1 - x] = alpha[base + w - 1 - x] * x // max(1, cut)
            # 最后一行镜像
            by = (h - 1 - y) * w
            for x in range(cut):
                alpha[by + x] = alpha[by + x] * x // max(1, cut)
                alpha[by + w - 1 - x] = alpha[by + w - 1 - x] * x // max(1, cut)

    # ---- 兜底：普通 GDI 双缓冲 + 整窗透明度（老系统无 ULW 时） ----
    def _paint_legacy(self, w, h, fs):
        hdc = user32.GetDC(self.hwnd)
        if not hdc:
            return
        try:
            if self._memdc is None or self._oldsize != (w, h):
                self._cleanup_buffer()
                self._memdc = gdi32.CreateCompatibleDC(hdc)
                self._bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
                self._oldbmp = gdi32.SelectObject(self._memdc, self._bmp)
                self._oldsize = (w, h)
            mdc = self._memdc
            self._draw_all(mdc, w, h, fs)
            gdi32.BitBlt(hdc, 0, 0, w, h, mdc, 0, 0, w32.SRCCOPY)
        finally:
            user32.ReleaseDC(self.hwnd, hdc)
        bg_a, tx_a = self._alphas()
        try:
            user32.SetLayeredWindowAttributes(self.hwnd, 0, min(bg_a, tx_a), w32.LWA_ALPHA)
        except Exception:  # noqa: BLE001
            pass

    def _cleanup_buffer(self):
        if self._memdc:
            if getattr(self, '_oldbmp', None):
                gdi32.SelectObject(self._memdc, self._oldbmp)
            gdi32.DeleteDC(self._memdc)
            self._memdc = None
        if self._bmp:
            gdi32.DeleteObject(self._bmp)
            self._bmp = None

    def _cleanup_buffers(self):
        """尺寸变化时释放两套缓冲（GDI 兜底 + 分层 DIB）"""
        self._cleanup_buffer()
        self._cleanup_layered()
        self._oldsize = (0, 0)

    def ensure_visible(self, idx):
        """把第 idx 行滚进可视区（键盘上下选择时用）"""
        vis = max(1, getattr(self, '_visible_rows', 1))
        if idx < self.scroll:
            self.scroll = idx
        elif idx >= self.scroll + vis:
            self.scroll = idx - vis + 1
        self.scroll = max(0, min(self.scroll, self.max_scroll))

    def hit_resize(self, x, y):
        """右下角拖动调整大小的热区"""
        try:
            w, h = self.client_size()
        except Exception:  # noqa: BLE001
            return False
        return x >= w - GRIP_SIZE and y >= h - GRIP_SIZE

    def _text(self, dc, s, x, y, color, font, align='left', max_w=None):
        if s is None:
            s = ''
        s = str(s)
        gdi32.SetTextColor(dc, color)
        gdi32.SetBkMode(dc, w32.TRANSPARENT)
        old = gdi32.SelectObject(dc, font)
        size = wintypes.SIZE()
        gdi32.GetTextExtentPoint32W(dc, s, len(s), ctypes.byref(size))
        tw, th = size.cx, size.cy
        if max_w and tw > max_w:
            # 省略号截断
            while len(s) > 1 and tw > max_w:
                s = s[:-1]
                gdi32.GetTextExtentPoint32W(dc, s + '…', len(s) + 1, ctypes.byref(size))
                tw = size.cx
            s += '…'
            gdi32.GetTextExtentPoint32W(dc, s, len(s), ctypes.byref(size))
            tw = size.cx
        if align == 'right':
            x -= tw
        elif align == 'center':
            x -= tw // 2
        # 描边：先在四个偏移位置画一遍轮廓，再画正文。
        # ⚠️ 蒙版 pass（MaskTheme）里描边色 = 正文色（黑），
        #    这样描边像素在蒙版里也算「内容」→ 拿到文字的不透明度，
        #    描边不会因为背景半透明而变虚。
        oc = None
        if isinstance(self.theme, MaskTheme):
            oc = color
        else:
            oc = getattr(self.theme, 'outline', None)
        if oc is not None:
            gdi32.SetTextColor(dc, oc)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                gdi32.ExtTextOutW(dc, x + dx, y + dy, 0, None, s, len(s), None, None)
        gdi32.SetTextColor(dc, color)
        gdi32.ExtTextOutW(dc, x, y, 0, None, s, len(s), None, None)
        gdi32.SelectObject(dc, old)
        return tw, th

    def _draw_header(self, dc, w, fs):
        if self.header_h == 0:
            return
        t = self.theme
        brush = gdi32.CreateSolidBrush(t.header)
        r = wintypes.RECT(0, 0, w, self.header_h)
        user32.FillRect(dc, ctypes.byref(r), brush)
        gdi32.DeleteObject(brush)

        # 底部分隔线
        if self.cfg.get('showGridLines', True):
            line = gdi32.CreateSolidBrush(t.border)
            r2 = wintypes.RECT(0, self.header_h - 1, w, self.header_h)
            user32.FillRect(dc, ctypes.byref(r2), line)
            gdi32.DeleteObject(line)

        # 状态点
        groups = self.cfg.get('groups') or []
        gname = ''
        idx = self.app.group_index()
        if 0 <= idx < len(groups):
            gname = groups[idx].get('name', '')
        if not self.status_ok:
            dot_c = t.up
        elif self.status_warn:
            dot_c = t.accent
        else:
            dot_c = t.down
        db = gdi32.CreateSolidBrush(dot_c)
        old_db = gdi32.SelectObject(dc, db)      # Ellipse 同样用 DC 当前刷子
        gdi32.Ellipse(dc, 10, self.header_h // 2 - 3, 16, self.header_h // 2 + 3)
        gdi32.SelectObject(dc, old_db)
        gdi32.DeleteObject(db)

        self._text(dc, gname, 24, self.header_h // 2 - fs // 2 - 1, t.text,
                   self.font(fs, True), max_w=w - 150)

        # 右侧按钮（⟳ 用 GDI 画，避免字体缺字显示成方框）
        btns = [('<', 'prev'), ('>', 'next'), ('refresh', 'refresh'), ('=', 'settings'), ('x', 'close')]
        x = w - 6
        for label, key in reversed(btns):
            x -= BTN_W
            if self.hover_btn == key:
                hb = gdi32.CreateSolidBrush(t.up if key == 'close' else t.panel)
                r3 = wintypes.RECT(x, 0, x + BTN_W, self.header_h)
                user32.FillRect(dc, ctypes.byref(r3), hb)
                gdi32.DeleteObject(hb)
            if key == 'refresh':
                self._draw_refresh_icon(dc, x + BTN_W // 2, self.header_h // 2, t.dim)
            else:
                self._text(dc, label, x + BTN_W // 2, self.header_h // 2 - fs // 2 - 1, t.dim,
                           self.font(fs), align='center')

    def _draw_refresh_icon(self, dc, cx, cy, color, r=5):
        """画一个圆形箭头（不依赖字体里是否有 ⟳ 字形）"""
        pen = gdi32.CreatePen(0, 2, color)
        old_pen = gdi32.SelectObject(dc, pen)
        old_brush = gdi32.SelectObject(dc, gdi32.GetStockObject(5))   # NULL_BRUSH
        gdi32.Ellipse(dc, cx - r, cy - r, cx + r, cy + r)
        # 右上角箭头
        pts = (wintypes.POINT * 3)()
        pts[0].x, pts[0].y = cx + 1, cy - r - 2
        pts[1].x, pts[1].y = cx + 6, cy - r - 1
        pts[2].x, pts[2].y = cx + 2, cy - r + 4
        br = gdi32.CreateSolidBrush(color)
        old_b2 = gdi32.SelectObject(dc, br)
        gdi32.Polygon(dc, pts, 3)
        gdi32.SelectObject(dc, old_b2)
        gdi32.SelectObject(dc, old_brush)
        gdi32.SelectObject(dc, old_pen)
        gdi32.DeleteObject(pen)
        gdi32.DeleteObject(br)

    def _draw_tabs(self, dc, w, fs):
        t = self.theme
        cur = self.app.group_index()
        y0 = self.header_h                      # 标签区位于标题栏之下
        f = self.font(max(10, fs - 2))
        for x, tw, i, label in self.tab_layout(w):
            active = (i == cur)
            br = gdi32.CreateSolidBrush(t.accent if active else t.panel)
            old_br = gdi32.SelectObject(dc, br)      # RoundRect 用 DC 当前刷子填充
            gdi32.RoundRect(dc, x, y0 + 2, x + tw, y0 + self.tabs_h - 2, 10, 10)
            gdi32.SelectObject(dc, old_br)
            gdi32.DeleteObject(br)
            # 活动标签文字颜色按底色明暗取反，浅色主题下也能看清
            base_acc = getattr(self, '_base_theme', t).accent
            color = (_parse_hex('#ffffff') if _lum(base_acc) < 140 else _parse_hex('#101318')) \
                if active else t.dim
            ty = y0 + 2 + max(0, (self.tabs_h - 4 - (fs - 2)) // 2)
            self._text(dc, label, x + tw // 2, ty, color, f, align='center', max_w=tw - 6)

    def _draw_table_head(self, dc, w, fs):
        t = self.theme
        y = self.header_h + self.tabs_h
        self.head_y = y
        if not self.cfg.get('showTableHead', True):
            return
        eff, _mode = self.col_plan()
        defs = [COLUMN_MAP[c] for c in eff]
        widths = self.column_widths(w)
        x = 6
        small = self.font(max(10, fs - 2))
        for i, d in enumerate(defs):
            if i >= len(widths):
                break
            cw = widths[i]
            self._text(dc, d[1], x + cw - 4, y + 2, t.dim, small,
                       align='right' if d[3] == 'right' else 'left', max_w=cw - 6)
            x += cw
        if self.cfg.get('showGridLines', True):
            line = gdi32.CreateSolidBrush(t.border)
            r = wintypes.RECT(0, y + fs + 3, w, y + fs + 4)
            user32.FillRect(dc, ctypes.byref(r), line)
            gdi32.DeleteObject(line)

    def _draw_rows(self, dc, w, fs):
        t = self.theme
        head_y = self.header_h + self.tabs_h
        y0 = head_y + (fs + 5 if self.cfg.get('showTableHead', True) else 4)
        groups = self.cfg.get('groups') or []
        idx = self.app.group_index()
        stocks = groups[idx].get('stocks', []) if 0 <= idx < len(groups) else []
        # 取消勾选的（enabled=False）不显示，但仍保留在列表里，随时能勾回来
        stocks = [s for s in stocks if s.get('enabled', True)]
        self.rows = []
        eff, mode = self.col_plan()
        widths = self.column_widths(w)
        defs = [COLUMN_MAP[c] for c in eff]

        if not stocks:
            self._text(dc, '暂无自选股', w // 2, y0 + 16, t.dim, self.font(fs), align='center')
            self._text(dc, '右键空白处添加', w // 2, y0 + 16 + fs + 6, t.dim,
                       self.font(max(10, fs - 2)), align='center')
            self.max_scroll = 0
            return

        # 行区真正的底边是状态栏上沿（body_h 是按窗口高度粗算的，必须再夹一次）
        avail_h = max(self.row_h, self.body_bottom - y0)
        visible = max(1, avail_h // self.row_h)
        self.max_scroll = max(0, len(stocks) - visible)
        self.scroll = min(self.scroll, self.max_scroll)
        self._visible_rows = visible
        self._rows_top = y0
        normal = self.font(fs)
        small = self.font(max(10, fs - 2))
        two_line = (mode == 'both')

        for i in range(self.scroll, len(stocks)):
            ry = y0 + (i - self.scroll) * self.row_h
            if ry + self.row_h > self.body_bottom:
                break
            stock = stocks[i]
            q = self.quotes.get(stock.get('code'), {})
            self.rows.append((i, ry, self.row_h))

            if i == self.selected:
                hb = gdi32.CreateSolidBrush(t.panel)
                r = wintypes.RECT(0, ry, w, ry + self.row_h)
                user32.FillRect(dc, ctypes.byref(r), hb)
                gdi32.DeleteObject(hb)

            x = 6
            for j, d in enumerate(defs):
                if j >= len(widths):
                    break
                cw = widths[j]
                key = d[0]
                if key == 'name':
                    name = self.name_display_text(q.get('name') or stock.get('name') or '--')
                    code = stock.get('code', '') or '--'
                    if two_line:
                        self._text(dc, name, x, ry + 1, t.text, normal, max_w=cw - 4)
                        self._text(dc, code, x, ry + 1 + fs, t.dim, small, max_w=cw - 4)
                    elif mode == 'name':
                        self._text(dc, name, x, ry + (self.row_h - fs) // 2 - 1,
                                   t.text, normal, max_w=cw - 4)
                    elif mode == 'code':
                        self._text(dc, code, x, ry + (self.row_h - fs) // 2 - 1,
                                   t.dim, small, max_w=cw - 4)
                elif key == 'code':
                    code = stock.get('code', '') or '--'
                    self._text(dc, code, x + cw - 4, ry + (self.row_h - fs) // 2 - 1,
                               t.dim, small, align='right', max_w=cw - 6)
                else:
                    val, color = self._cell_value(q, key)
                    f = small if key == 'time' else normal
                    self._text(dc, val, x + cw - 4, ry + (self.row_h - fs) // 2 - 1,
                               color, f, align='right', max_w=cw - 6)
                x += cw

    def _draw_scrollbar(self, dc, w):
        """自选太多时右侧画一条细滚动条，给个「还有更多」的视觉反馈"""
        if self.max_scroll <= 0 or self.body_h <= 0:
            return
        visible = max(1, getattr(self, '_visible_rows', 1))
        head_y = self.header_h + self.tabs_h
        rows_top = head_y + (self.eff_font_size() + 5 if self.cfg.get('showTableHead', True) else 4)
        total = self.max_scroll + visible
        track_h = max(10, min(self.body_h, max(10, self.body_bottom - rows_top)))
        thumb_h = max(18, int(track_h * visible / max(1, total)))
        span = max(1, track_h - thumb_h)
        top = rows_top + int(span * self.scroll / max(1, self.max_scroll))
        br = gdi32.CreateSolidBrush(self.theme.dim)
        r = wintypes.RECT(w - 3, top, w - 1, top + thumb_h)
        user32.FillRect(dc, ctypes.byref(r), br)
        gdi32.DeleteObject(br)

    def _cell_value(self, q, key):
        t = self.theme
        v = q.get(key)
        if key in ('change', 'changePct'):
            if v is None:
                return '--', t.flat
            s = ('+' if v > 0 else '') + f'{v:.2f}' + ('%' if key == 'changePct' else '')
            c = t.up if v > 0 else (t.down if v < 0 else t.flat)
            return s, c
        if key == 'price':
            if v is None:
                return '--', t.flat
            c = t.flat
            pc = q.get('prevClose')
            if pc:
                if v > pc:
                    c = t.up
                elif v < pc:
                    c = t.down
            return f'{v:.2f}', c
        if key in ('volume', 'amount', 'floatCap', 'totalCap'):
            if v is None:
                return '--', t.dim
            return _fmt_big(v), t.text
        if key in ('turnover', 'amplitude'):
            return ('--' if v is None else f'{v:.2f}%'), t.text
        if key == 'time':
            s = q.get('time') or '--'
            # 只显示「时:分」：秒级对盯盘没意义，却要占掉 12px，
            # 宽度紧张时会把代码列挤到出现省略号。
            if ':' in s:
                tpart = s.split()[-1] if ' ' in s else s
                s = tpart[:5] if len(tpart) >= 5 else tpart
            return s, t.dim
        if v is None:
            return '--', t.dim
        return f'{v:.2f}' if isinstance(v, float) else str(v), t.text

    def _draw_status(self, dc, w, h, fs):
        if not self.cfg.get('showStatus', True):
            return
        t = self.theme
        y = h - self.status_h
        brush = gdi32.CreateSolidBrush(t.header)
        r = wintypes.RECT(0, y, w, h)
        user32.FillRect(dc, ctypes.byref(r), brush)
        gdi32.DeleteObject(brush)
        if self.cfg.get('showGridLines', True):
            line = gdi32.CreateSolidBrush(t.border)
            r2 = wintypes.RECT(0, y, w, y + 1)
            user32.FillRect(dc, ctypes.byref(r2), line)
            gdi32.DeleteObject(line)

        src = {'tencent': '腾讯', 'sina': '新浪', 'eastmoney': '东财'}.get(
            self.cfg.get('source', 'tencent'), '腾讯')
        left = f"{src} · {int(self.cfg.get('refreshInterval', 5000) / 1000)}s"
        if self.status_text:
            left = self.status_text
        self._text(dc, left, 8, y + (self.status_h - fs) // 2 - 1, t.dim,
                   self.font(max(10, fs - 2)), max_w=w - 80)
        if self.last_update:
            self._text(dc, self.last_update, w - 8, y + (self.status_h - fs) // 2 - 1, t.dim,
                       self.font(max(10, fs - 2)), align='right')

    # ---------------- 命中测试 ----------------
    def hit_button(self, x, y):
        if self.header_h == 0 or y > self.header_h:
            return None
        btns = [('<', 'prev'), ('>', 'next'), ('refresh', 'refresh'), ('=', 'settings'), ('x', 'close')]
        bx = self.client_size()[0] - 6
        for label, key in reversed(btns):
            bx -= BTN_W
            if bx <= x < bx + BTN_W:
                return key
        return None

    def hit_tab(self, x, y):
        if not self.tabs_h or y < self.header_h or y > self.header_h + self.tabs_h:
            return None
        for tx, tw, i, _ in self.tab_layout(self.client_size()[0]):
            if tx <= x <= tx + tw:
                return i
        return None

    def hit_row(self, x, y):
        for i, ry, rh in self.rows:
            if ry <= y < ry + rh:
                return i
        return -1


def _fmt_big(v):
    a = abs(v)
    if a >= 1e8:
        return f'{v / 1e8:.2f}亿'
    if a >= 1e4:
        return f'{v / 1e4:.2f}万'
    return f'{v:.0f}'
