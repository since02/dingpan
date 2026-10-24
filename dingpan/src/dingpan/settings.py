"""
设置窗口：原生 Win32 控件实现
左侧分区导航 + 右侧表单
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

from . import win32 as w32
from . import storage, quotes, legacy
from .win32 import gdi32, user32, kernel32
from .widget import COLUMN_DEFS, COLUMN_MAP
from . import dialogs

WM_SETTINGSCREATED = w32.WM_USER + 40
WM_DAV_DONE = w32.WM_USER + 41          # WebDAV 后台操作完成
WM_STOCK_VERIFY_DONE = w32.WM_USER + 42  # 添加股票的代码验证完成
WM_CUSTOM_TEST_DONE = w32.WM_USER + 43  # 自定义数据源接口测试完成

# 页面 ID
P_BASIC, P_STOCKS, P_COLUMNS, P_STYLE, P_BACKUP, P_DAV, P_HOTKEY, P_ABOUT = range(8)

PAGES = [
    ('基础设置', P_BASIC),
    ('自选管理', P_STOCKS),
    ('显示字段', P_COLUMNS),
    ('样式外观', P_STYLE),
    ('备份恢复', P_BACKUP),
    ('WebDAV', P_DAV),
    ('快捷键', P_HOTKEY),
    ('关于', P_ABOUT),
]

SIDEBAR_W = 150
TOPBAR_H = 46
# 勾选标记（与自选列表共用同一套前缀）
FIELD_MARK_ON = '[√]'
FIELD_MARK_OFF = '[  ]'
# 期望的「客户区」尺寸（不含标题栏/边框）。控件坐标都按客户区计算，
# 因此外框必须用 AdjustWindowRectEx 反算，否则底部按钮会被窗口边缘裁掉。
CLIENT_W = 760
CLIENT_H = 584

# ---------------- 窗口类：全局只注册一次 ----------------
# 历史 Bug：每次打开设置窗都 RegisterClassW('DingPanSettings')，
# 第二次因类名已存在而静默失败，系统继续用「上一个对象」的窗口过程，
# 而那个对象已被回收 → 消息打进野指针，表现为「保存后再打开就出错」。
# 现在改成：模块级常驻的窗口过程 + hwnd→实例 登记表，
# 类只注册一次，回调地址永不失效。
_SETTINGS_INSTANCES = {}
_SETTINGS_PENDING = None       # 创建窗口期间（还没拿到 hwnd）的临时实例
_SETTINGS_CLASS_READY = False


def _settings_wndproc(hwnd, msg, wparam, lparam):
    """模块级窗口过程：按 hwnd 找到对应的 SettingsWindow 实例再分发。"""
    inst = _SETTINGS_INSTANCES.get(int(hwnd)) or _SETTINGS_PENDING
    if inst is None:
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    return inst._wndproc(hwnd, msg, wparam, lparam)


_SETTINGS_WNDPROC = w32.WNDPROC(_settings_wndproc)


# ================= 可勾选 + 可拖动排序的列表（通用）=================
# 原生 LISTBOX 没有复选框、也不支持拖动排序，所以这两个列表都用
# 「原生 LISTBOX + 子类化」的方式自己实现交互：
#   - 点左侧 [√] 区域 → 切换勾选（显示 / 不显示）
#   - 按住行上下拖 → 换位
# ⚠️ 必须用**原生 'LISTBOX' 类**：换成自定义窗口类名会失去 listbox 的内部行为
#    （LB_ADDSTRING 直接失效、项数为 0）。
# ⚠️ 子类化后要把消息转回**原窗口过程**（LB_* 消息不在 DefWindowProcW 里）。
_STOCKLIST_CLASS = 'DingPanStockList'
_STOCKLIST_READY = False
_STOCKLIST_INSTANCES = {}      # hwnd → SettingsWindow
_STOCKLIST_OLD_PROC = {}       # hwnd → 原窗口过程（子类化后必须转发给它）
_STOCKLIST_ROLE = {}           # hwnd → 'stocks' | 'fields'（决定用哪套数据/回调）
_STOCKLIST_PENDING = None


def _stocklist_wndproc(hwnd, msg, wparam, lparam):
    """可勾选列表的子类化窗口过程。

    ⚠️ 关键：LISTBOX 的 LB_* 消息（LB_ADDSTRING 等）是由**它自己的窗口过程**处理的，
    不在 DefWindowProcW 里。所以子类化后必须把消息转回**原窗口过程**，
    否则 LB_ADDSTRING 直接失效、列表一项都没有（实测项数恒为 0）。
    """
    inst = _STOCKLIST_INSTANCES.get(int(hwnd))
    if inst is not None:
        try:
            handled = inst._checklist_proc(hwnd, msg, wparam, lparam)
            if handled is not None:
                return handled
        except Exception:  # noqa: BLE001
            pass
    old = _STOCKLIST_OLD_PROC.get(int(hwnd))
    if old:
        return user32.CallWindowProcW(old, hwnd, msg, wparam, lparam)
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_STOCKLIST_WNDPROC = w32.WNDPROC(_stocklist_wndproc)


def _version():
    try:
        from . import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return '?'


def _build_tag():
    try:
        from ._buildinfo import BUILD_TAG
        return BUILD_TAG
    except Exception:  # noqa: BLE001
        return 'dev'


# 能写进配置的按键名（必须与 app._parse_hotkey 支持的集合一致）
_KEY_NAMES = {
    0x25: 'Left', 0x26: 'Up', 0x27: 'Right', 0x28: 'Down',
    0x20: 'Space', 0x0D: 'Enter', 0x1B: 'Esc', 0x2E: 'Delete',
}


def _vk_name(vk):
    """虚拟键码 → 配置里的按键名；不支持的返回 None（当作修饰键/无效键忽略）"""
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x70 <= vk <= 0x87:            # F1 - F24
        return 'F%d' % (vk - 0x6F)
    return _KEY_NAMES.get(vk)


class SettingsWindow:
    """设置窗口"""

    def __init__(self, app):
        self.app = app
        self.hwnd = None
        self.page = P_BASIC
        self.controls = {}
        self.page_keys = {}
        self._cur_page = None
        self.tab_buttons = []
        self._font = None
        self._font_b = None
        self._dying = False
        self._dav_busy = False
        self._dav_result = None
        self._dav_cfg = None
        self._stock_busy = False
        self._stock_result = None
        self._stock_code = None
        self._capture = None        # 正在录制的快捷键行号
        self._auto_cid = 3000       # 自动分配的控件 ID 起点（避开所有手工 ID 段）
        # 拖动排序状态：按列表角色分开（'stocks' 自选列表 / 'fields' 字段列表）
        self._drag_state = {'stocks': None, 'fields': None}
        # ⚠️ 自绘列表的选中行号存在**Python 侧**，不用原生 LB_SETCURSEL/LB_GETCURSEL：
        #    LB_SETCURSEL 会让原生 listbox 立刻用自己的样式画一遍选中行
        #    （不走 WM_PAINT）→ 覆盖掉我们的自绘 → 选中行变成原生样式（用户反馈的怪现象）。
        self._checklist_sel = {'stocks': -1, 'fields': -1}
        # 显示字段页的字段顺序（含未勾选的），下标与列表项一一对应
        self._field_order = [d[0] for d in COLUMN_DEFS]

    # ---------------- 创建 ----------------
    def show(self):
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.ShowWindow(self.hwnd, w32.SW_SHOW)
            user32.SetForegroundWindow(self.hwnd)
            return
        self._create()
    def _create(self):
        global _SETTINGS_PENDING, _SETTINGS_CLASS_READY
        hinst = kernel32.GetModuleHandleW(None)

        # 窗口类只注册一次；重复注册会失败并沿用旧回调（历史 Bug 根源）
        if not _SETTINGS_CLASS_READY:
            cls = w32.WNDCLASS()
            cls.style = 0x0003 | 0x0008
            cls.lpfnWndProc = _SETTINGS_WNDPROC
            cls.hInstance = hinst
            cls.hCursor = user32.LoadCursorW(None, ctypes.c_wchar_p(32512))
            cls.hbrBackground = user32.GetSysColorBrush(15)  # COLOR_BTNFACE
            cls.lpszClassName = 'DingPanSettings'
            user32.RegisterClassW(ctypes.byref(cls))
            _SETTINGS_CLASS_READY = True

        self._font = w32.make_font('Microsoft YaHei', 13)
        self._font_b = w32.make_font('Microsoft YaHei', 13, True)

        style = w32.WS_OVERLAPPEDWINDOW if hasattr(w32, 'WS_OVERLAPPEDWINDOW') else (
            0x00CF0000 | w32.WS_CAPTION | w32.WS_SYSMENU | w32.WS_THICKFRAME | w32.WS_MINIMIZEBOX)
        ex = w32.WS_EX_APPWINDOW

        # 由目标客户区反算外框尺寸（关键修复：原来直接用 760x560 当外框，
        # 客户区只剩 744x521，底部「关闭」按钮整条被裁掉）
        rc = wintypes.RECT(0, 0, CLIENT_W, CLIENT_H)
        try:
            user32.AdjustWindowRectEx(ctypes.byref(rc), style, False, ex)
            W = rc.right - rc.left
            H = rc.bottom - rc.top
        except Exception:  # noqa: BLE001
            W, H = CLIENT_W + 16, CLIENT_H + 39
        if W < CLIENT_W:
            W = CLIENT_W + 16
        if H < CLIENT_H:
            H = CLIENT_H + 39

        wa = w32.get_work_area()
        x = (wa.left + wa.right) // 2 - W // 2
        y = (wa.top + wa.bottom) // 2 - H // 2

        # 创建期间消息会先到（WM_CREATE 等），用 _SETTINGS_PENDING 兜住
        _SETTINGS_PENDING = self
        try:
            hwnd = user32.CreateWindowExW(ex, 'DingPanSettings',
                                          '盯盘 · 设置  v%s · 构建 %s' % (_version(), _build_tag()),
                                          style,
                                          x, y, W, H, None, None, hinst, None)
        finally:
            _SETTINGS_PENDING = None
        if not hwnd:
            raise RuntimeError('创建设置窗口失败')
        self.hwnd = hwnd
        _SETTINGS_INSTANCES[int(hwnd)] = self
        user32.SetWindowLongPtrW(hwnd, w32.GWLP_USERDATA, id(self))
        self.app._settings_obj = self

        self._build_ui(hinst)
        self._load_ui()

        user32.ShowWindow(hwnd, w32.SW_SHOW)
        user32.UpdateWindow(hwnd)
        user32.SetForegroundWindow(hwnd)

    def _stock_listbox(self, hinst, x, y, w, h, parent, role='stocks'):
        """创建「可勾选 + 可拖动排序」的列表。

        role: 'stocks'（自选管理页）/ 'fields'（显示字段页）
        必须用**原生 'LISTBOX' 类**再子类化：
        换成自定义窗口类名会失去 listbox 的内部行为（LB_ADDSTRING 直接失效、项数为 0）。
        子类化后还要把消息转回**原窗口过程**（LB_* 消息不在 DefWindowProc 里）。
        """
        global _STOCKLIST_READY, _STOCKLIST_PENDING
        # 普通 LISTBOX + 子类化。
        # 不用 owner-draw（LBS_OWNERDRAWFIXED）：实测在本机 WM_DRAWITEM 一次都不触发
        # （样式位正确、父窗口可见也一样），列表会画成空白。
        # → 改成**子类化后拦截 WM_PAINT 自己画**（三列：复选框 / 文字 / 拖拽手柄）。
        style = (0x0001 | 0x0100 | w32.WS_CHILD | w32.WS_VISIBLE)
        self._auto_cid += 1
        cid = self._auto_cid
        h = user32.CreateWindowExW(0, 'LISTBOX', '', style,
                                   x, y, w, h, parent,
                                   ctypes.cast(cid, ctypes.c_void_p), hinst, None)
        if h:
            # 子类化：替换窗口过程，用来接管「点复选框」和「拖动排序」。
            # 实例用 hwnd→对象 的登记表找（比往 GWLP_USERDATA 塞指针更安全）。
            old_proc = user32.SetWindowLongPtrW(h, -4, ctypes.cast(
                _STOCKLIST_WNDPROC, ctypes.c_void_p).value)
            # 原窗口过程必须保存：LB_* 消息要转给它，不能给 DefWindowProcW
            _STOCKLIST_OLD_PROC[int(h)] = old_proc
            _STOCKLIST_INSTANCES[int(h)] = self
            _STOCKLIST_ROLE[int(h)] = role
            self.lb_stocks_cid = cid
            # ⚠️ 必须设字体，否则会用系统默认字体（宋体），与其它控件不一致。
            if self._font:
                user32.SendMessageW(h, w32.WM_SETFONT, self._font, 1)
            # ⚠️ 行高要和自绘用的 ROW_H 一致，否则原生算出来的滚动位置/命中行
            #    跟我们对不上（会出现滚动错位、点错行）。
            user32.SendMessageW(h, 0x01A0, 0, self.ROW_H)   # LB_SETITEMHEIGHT
            # ⚠️ 必须登记到当前页（绕过 _ctl 直接创建的控件不会自动 _track）。
            #    漏掉这行 → 该控件不属于任何页面 → 切页时不隐藏 →
            #    列表会显示在**所有**设置页上（v1.0.18 修的 bug）。
            self._track(h)
        return h

    def _ctl(self, hinst, cls_name, text, style, x, y, w, h, parent=None, cid=0):
        # 控件 ID 必须全局唯一！
        # 历史 Bug：列表框/下拉框没给 ID（=0），而左侧导航第一个按钮 P_BASIC 恰好也是 0，
        # 用户在列表框点一下 → 收到 WM_COMMAND(LOWORD=0) → 被当成「点了基础设置」
        # → 页面莫名其妙跳回首页。这里统一自动分配，避免任何撞号。
        if not cid:
            self._auto_cid += 1
            cid = self._auto_cid
        h = user32.CreateWindowExW(0, cls_name, text, style | w32.WS_CHILD | w32.WS_VISIBLE,
                                   x, y, w, h, parent or self.hwnd,
                                   ctypes.cast(cid, ctypes.c_void_p),
                                   hinst, None)
        user32.SendMessageW(h, w32.WM_SETFONT, self._font, 1)
        if (parent or self.hwnd) == self.hwnd:
            self._track(h)
        return h

    def _build_ui(self, hinst):
        # 左侧导航
        self._nav_bg = self._ctl(hinst, 'STATIC', '', 0, 0, 0, SIDEBAR_W, 0)
        user32.SetWindowPos(self._nav_bg, None, 0, 0, SIDEBAR_W, CLIENT_H, 0x0004)  # SWP_SHOWWINDOW
        y = 12
        for label, pid in PAGES:
            # 导航按钮用 8000+pid 的独立 ID 段，绝不与列表框/输入框撞号
            b = self._ctl(hinst, 'BUTTON', label,
                          w32.BS_PUSHBUTTON, 8, y, SIDEBAR_W - 16, 30, cid=8000 + pid)
            self.tab_buttons.append((pid, b))
            y += 34

        # 底部按钮（按客户区高度锚定，任何 DPI 下都不会被裁掉；WM_SIZE 里同口径重排）
        self.btn_save = self._ctl(hinst, 'BUTTON', '保存设置', w32.BS_DEFPUSHBUTTON,
                                  8, CLIENT_H - 68, SIDEBAR_W - 16, 30, cid=9001)
        self.btn_close = self._ctl(hinst, 'BUTTON', '关闭', w32.BS_PUSHBUTTON,
                                   8, CLIENT_H - 34, SIDEBAR_W - 16, 28, cid=9002)

        # 右侧内容区不再使用任何 STATIC 容器：页面控件直接挂在主窗口上，
        # 避免容器把控件盖住导致「页面看着有内容但点不动 / 一片空白」。
        self.content = None

        self._build_basic(hinst)
        self._build_stocks(hinst)
        self._build_columns(hinst)
        self._build_style(hinst)
        self._build_backup(hinst)
        self._build_dav(hinst)
        self._build_hotkeys(hinst)
        self._build_about(hinst)

        self._show_page(self.page)

    # ---------------- 基础设置 ----------------
    def _build_basic(self, hinst):
        p = self._page('basic')
        x = SIDEBAR_W + 20          # 左栏 x=170（宽度上限 300，避免盖住右栏）
        xr = x + 320                # 右栏 x=490
        LW = 300                    # 左栏控件宽度上限
        RW = CLIENT_W - xr - 16     # 右栏控件宽度上限
        y = 20
        # ---- 左栏：输入类控件 ----
        self._label(p, '行情数据源', x, y, LW)
        self.cb_source = self._ctl(hinst, 'COMBOBOX', '',
                                   w32.CBS_DROPDOWNLIST | 0x0001, x, y + 20, LW, 200, p)
        self._fill_combo(self.cb_source,
                         [v[0] for v in quotes.SOURCES.values()] + [quotes.CUSTOM_SOURCE_NAME])
        y += 58

        self._label(p, '刷新间隔（秒）', x, y, 130)
        self.ed_interval = self._ctl(hinst, 'EDIT', '', w32.ES_NUMBER, x, y + 20, 90, 26, p)
        self._label(p, '悬浮窗宽度（px）', x + 140, y, 150)
        self.ed_width = self._ctl(hinst, 'EDIT', '', w32.ES_NUMBER, x + 140, y + 20, 90, 26, p)
        y += 62

        # 「打开行情页」用哪个平台
        self._label(p, '打开行情页平台', x, y, LW)
        self.cb_quote_platform = self._ctl(hinst, 'COMBOBOX', '',
                                           w32.CBS_DROPDOWNLIST | 0x0001,
                                           x, y + 20, 200, 200, p)
        self._fill_combo(self.cb_quote_platform,
                         [v[0] for v in quotes.QUOTE_PLATFORMS.values()])
        y += 62

        self._label(p, '窗口标题', x, y, LW)
        self.ed_title = self._ctl(hinst, 'EDIT', '', 0, x, y + 20, LW, 26, p)
        y += 62

        # 左栏底部：数据源状态 + 提示
        self.lbl_basic_info = self._label(p, '', x, y, LW)
        user32.SetWindowPos(self.lbl_basic_info, None, x, y, LW, 40, 0x0004)
        self._label(p, '提示：字段到「显示字段」页，配色到「样式外观」页', x, y + 46, LW)

        # ---- 右栏：复选框 ----
        yr = 20
        self.cb_topmost = self._ctl(hinst, 'BUTTON', '悬浮窗始终置顶',
                                    w32.BS_AUTOCHECKBOX, xr, yr, 240, 24, p, 9101)
        yr += 30
        self.cb_header = self._ctl(hinst, 'BUTTON', '显示标题栏和分组标签',
                                   w32.BS_AUTOCHECKBOX, xr, yr, 240, 24, p, 9102)
        yr += 30
        # 「显示股票名称 / 显示股票代码」已移到「显示字段」页统一管理
        self.cb_table_head = self._ctl(hinst, 'BUTTON', '显示列表表头（列标题）',
                                       w32.BS_AUTOCHECKBOX, xr, yr, 240, 24, p, 9105)
        yr += 30
        self.cb_status = self._ctl(hinst, 'BUTTON', '显示底部状态栏',
                                   w32.BS_AUTOCHECKBOX, xr, yr, 240, 24, p, 9106)
        yr += 30
        self.cb_autosize = self._ctl(hinst, 'BUTTON', '窗口大小按内容自动适应',
                                     w32.BS_AUTOCHECKBOX, xr, yr, 240, 24, p, 9107)
        yr += 30
        self.cb_border = self._ctl(hinst, 'BUTTON', '显示悬浮窗外边框',
                                   w32.BS_AUTOCHECKBOX, xr, yr, 240, 24, p, 9108)
        yr += 30
        self.cb_gridlines = self._ctl(hinst, 'BUTTON', '显示表格内部线段',
                                      w32.BS_AUTOCHECKBOX, xr, yr, 240, 24, p, 9109)

        # ---- 自定义平台地址（平台选「自定义…」时才显示）----
        # ⚠️ y 必须从最后一个复选框下方开始，否则新建的 STATIC 标签
        #    会盖在复选框上（后建控件 z-order 在上面）。
        ys = yr + 32
        self.lbl_quote_url = self._label(p, '自定义平台地址', xr, ys, RW)
        self.ed_quote_url = self._ctl(hinst, 'EDIT', '', 0, xr, ys + 20, RW, 26, p)
        self.lbl_quote_ph = self._label(p, '占位符：{code} {sym} {num}', xr, ys + 50, RW)
        ys += 84

        # ---- 自定义数据源（选中「自定义接口…」时才显示）----
        self.lbl_custom_src = self._label(p, '自定义数据源接口', xr, ys, RW)
        ys += 24
        self.lbl_cust_url = self._label(p, '接口地址（{codes} = 代码列表）', xr, ys, RW)
        self.ed_cust_url = self._ctl(hinst, 'EDIT', '', 0, xr, ys + 20, RW, 26, p)
        ys += 52
        self.lbl_cust_map = self._label(p, '字段映射（内部字段=接口字段名）', xr, ys, RW)
        self.ed_cust_map = self._ctl(hinst, 'EDIT', '', 0, xr, ys + 20, RW, 26, p)
        ys += 52
        self.lbl_cust_enc = self._label(p, '编码', xr, ys, 60)
        self.cb_cust_enc = self._ctl(hinst, 'COMBOBOX', '',
                                     w32.CBS_DROPDOWNLIST | 0x0001, xr, ys + 20, 70, 120, p)
        self._fill_combo(self.cb_cust_enc, ['utf-8', 'gbk'])
        self.lbl_cust_ck = self._label(p, '代码字段名', xr + 80, ys, 100)
        self.ed_cust_codekey = self._ctl(hinst, 'EDIT', '', 0, xr + 80, ys + 20, 60, 26, p)
        self.btn_cust_test = self._ctl(hinst, 'BUTTON', '测试接口',
                                       w32.BS_PUSHBUTTON, xr + 150, ys + 20, 80, 26, p, 9110)
        ys += 50
        self.lbl_cust_msg = self._label(p, '', xr, ys, RW)
        self.lbl_cust_hint = self._label(p, '示例：{"sh600519":{"name":"茅台","last":1688}}'
                                         ' → name=name,price=last', xr, ys + 22, RW)
    def _fill_combo(self, combo, items):
        CB_ADDSTRING = 0x0143
        CB_RESETCONTENT = 0x014B
        CB_SETCURSEL = 0x014E
        user32.SendMessageW(combo, CB_RESETCONTENT, 0, 0)
        for it in items:
            w32.send_msg_text(combo, CB_ADDSTRING, 0, it)
        user32.SendMessageW(combo, CB_SETCURSEL, 0, 0)

    # ---------------- 自选管理 ----------------
    def _build_stocks(self, hinst):
        p = self._page('stocks')
        x = SIDEBAR_W + 20
        self.lb_groups = self._ctl(hinst, 'LISTBOX', '',
                                   w32.LISTBOX_STYLE, x, 20, 170, 330, p)
        self.btn_group_add = self._ctl(hinst, 'BUTTON', '新建分组', w32.BS_PUSHBUTTON,
                                       x, 356, 80, 26, p, 9201)
        self.btn_group_del = self._ctl(hinst, 'BUTTON', '删除分组', w32.BS_PUSHBUTTON,
                                       x + 88, 356, 80, 26, p, 9202)

        x2 = x + 190
        # 自选列表用专门注册的窗口类（子类化）：原生 LISTBOX 没有复选框、
        # 也不支持拖动排序，这里要自己实现。
        self.lb_stocks = self._stock_listbox(hinst, x2, 20, 330, 330, p)
        self.ed_stock = self._ctl(hinst, 'EDIT', '', 0, x2, 356, 210, 26, p)
        self.btn_stock_add = self._ctl(hinst, 'BUTTON', '添加', w32.BS_PUSHBUTTON,
                                       x2 + 216, 356, 56, 26, p, 9203)
        self.btn_stock_del = self._ctl(hinst, 'BUTTON', '删除', w32.BS_PUSHBUTTON,
                                       x2 + 278, 356, 56, 26, p, 9204)
        self.lbl_stock_hint = self._label(p, '支持一次多个：600519 000001 00700', x2, 390)

    # ---------------- 显示字段 ----------------
    def _build_columns(self, hinst):
        p = self._page('columns')
        x = SIDEBAR_W + 20
        self.lbl_col_tip = self._label(
            p, '点左侧方框切换「显示 / 不显示」，按住某一行上下拖动可调整顺序',
            x, 16)
        # 单列表：所有字段都在里面，勾选的按顺序显示，未勾选的保留（随时能勾回来）
        self.lb_fields = self._stock_listbox(hinst, x, 40, 230, 380, p, role='fields')
        self.lbl_col_msg = self._label(p, '', x, 428)

        xr = x + 260
        self.btn_col_reset = self._ctl(hinst, 'BUTTON', '恢复默认', w32.BS_PUSHBUTTON,
                                       xr, 40, 100, 28, p, 9305)
        self.btn_col_all = self._ctl(hinst, 'BUTTON', '全部显示', w32.BS_PUSHBUTTON,
                                     xr, 74, 100, 28, p, 9306)
        self.btn_col_none = self._ctl(hinst, 'BUTTON', '全部隐藏', w32.BS_PUSHBUTTON,
                                      xr, 108, 100, 28, p, 9307)
        self._label(p, '名称最多显示字符（0 = 全部）', xr, 150)
        self.ed_name_chars = self._ctl(hinst, 'EDIT', '', w32.ES_NUMBER,
                                       xr, 172, 80, 26, p)
        self._label(p, '提示：顺序 = 悬浮窗里各列从左到右的排列。', xr, 210, 300)
        self._label(p, '取消勾选的字段不会显示，但不会被删掉。', xr, 232, 300)

    # ---------------- 样式 ----------------
    def _build_style(self, hinst):
        p = self._page('style')
        x = SIDEBAR_W + 20
        y = 16
        self._label(p, '主题', x, y)
        self.rb_dark = self._ctl(hinst, 'BUTTON', '深色', w32.BS_AUTORADIOBUTTON,
                                 x, y + 22, 80, 24, p, 9401)
        self.rb_light = self._ctl(hinst, 'BUTTON', '浅色', w32.BS_AUTORADIOBUTTON,
                                  x + 90, y + 22, 80, 24, p, 9402)
        self.rb_custom = self._ctl(hinst, 'BUTTON', '自定义', w32.BS_AUTORADIOBUTTON,
                                   x + 180, y + 22, 80, 24, p, 9403)
        y += 60

        # 背景颜色 + 背景不透明度（**只影响背景**，不影响文字）
        self._label(p, '背景颜色', x, y)
        self.btn_bg_color = self._ctl(hinst, 'BUTTON', '#1c1f28', w32.BS_PUSHBUTTON,
                                      x, y + 20, 110, 26, p, 9411)
        self._label(p, '背景不透明度（只调背景）', x + 140, y)
        self.sb_bg = self._ctl(hinst, 'msctls_trackbar32', '', 0x0001, x + 140, y + 18, 180, 30, p)
        self.lbl_bg = self._label(p, '', x + 328, y + 24)
        y += 62

        # 文字颜色 + 文字不透明度（**只影响文字**，不影响背景）
        self._label(p, '文字颜色', x, y)
        self.btn_text_color = self._ctl(hinst, 'BUTTON', '#e6e8ef', w32.BS_PUSHBUTTON,
                                        x, y + 20, 110, 26, p, 9412)
        self._label(p, '文字不透明度（只调文字）', x + 140, y)
        self.sb_text = self._ctl(hinst, 'msctls_trackbar32', '', 0x0001, x + 140, y + 18, 180, 30, p)
        self.lbl_text = self._label(p, '', x + 328, y + 24)
        y += 62

        # 文字描边：背景透明时给文字加一圈轮廓，保证可读性
        self._label(p, '文字描边', x, y)
        self.cb_outline = self._ctl(hinst, 'COMBOBOX', '',
                                    w32.CBS_DROPDOWNLIST | 0x0001, x, y + 18, 90, 120, p)
        self._fill_combo(self.cb_outline, ['自动（背景透明时开）', '始终开启', '关闭'])
        self.btn_bg_100 = self._ctl(hinst, 'BUTTON', '背景 100%',
                                   w32.BS_PUSHBUTTON, x + 110, y + 18, 90, 26, p, 9431)
        y += 62

        # 字号：改用下拉框而不是滑块。
        # 原因：Windows trackbar 的**自动刻度会被稀疏化**（控件宽度相对取值跨度太窄时，
        # 系统会隔几个值才画一个刻度），点击时位置又吸附到刻度上 →
        # 10~20 之间只能选到 11/13/15 一类的中间值，选不了 12/14。
        # 下拉框把 10~20 全列出来，点一下就精确选中，没有这个问题。
        self._label(p, '字体大小', x, y)
        self.cb_font = self._ctl(hinst, 'COMBOBOX', '',
                                 w32.CBS_DROPDOWNLIST | 0x0001, x, y + 18, 90, 200, p)
        self._fill_combo(self.cb_font, [str(v) for v in range(10, 21)])
        y += 62

        # 涨跌颜色（末尾带一项「自定义…」，可选任意颜色）
        self._label(p, '上涨颜色', x, y)
        self.cb_up = self._ctl(hinst, 'COMBOBOX', '', w32.CBS_DROPDOWNLIST | 0x0001,
                               x, y + 20, 120, 200, p)
        self._label(p, '下跌颜色', x + 150, y)
        self.cb_down = self._ctl(hinst, 'COMBOBOX', '', w32.CBS_DROPDOWNLIST | 0x0001,
                                 x + 150, y + 20, 120, 200, p)
        self._fill_color_combo(self.cb_up, ['红 #f6465d', '橙 #ff8b00', '绿 #0ecb81',
                                            '蓝 #3d7eff', '紫 #a855f7', '白 #ffffff'])
        self._fill_color_combo(self.cb_down, ['绿 #0ecb81', '青 #00b8d9', '蓝 #3d7eff',
                                              '紫 #a855f7', '红 #f6465d', '白 #ffffff'])
        y += 64
        # 显示方案：内置预设 + 用户自定义（保存 / 切换）
        self._label(p, '显示方案', x, y)
        self.cb_preset = self._ctl(hinst, 'COMBOBOX', '',
                                   w32.CBS_DROPDOWNLIST | 0x0001, x, y + 20, 210, 200, p)
        self.btn_preset_apply = self._ctl(hinst, 'BUTTON', '应用', w32.BS_PUSHBUTTON,
                                           x + 220, y + 20, 60, 26, p, 9421)
        y += 56
        self._label(p, '保存当前字段为自定义方案', x, y)
        self.ed_preset_name = self._ctl(hinst, 'EDIT', '', 0, x, y + 20, 210, 26, p)
        self.btn_preset_save = self._ctl(hinst, 'BUTTON', '保存', w32.BS_PUSHBUTTON,
                                          x + 220, y + 20, 60, 26, p, 9422)
        self.btn_preset_del = self._ctl(hinst, 'BUTTON', '删除', w32.BS_PUSHBUTTON,
                                         x + 286, y + 20, 60, 26, p, 9423)
        y += 60
        self.lbl_preset_msg = self._label(p, '', x, y)
        y += 34
        self.lbl_style_tip = self._label(
            p, '提示：选「自定义」后可用上面两个颜色按钮改底色/字色；\n'
               '「背景不透明度」只影响背景、「文字不透明度」只影响文字；\n'
               '拖动透明度时，悬浮窗底部会同时显示背景和文字两个数值；\n'
               '「显示方案」保存一整套显示设置（字段/主题/颜色/透明度/字号/开关），\n'
               '切换后整套一起生效；右下角可拖动改大小，改动即时预览。', x, y)

    # ---------------- 备份 ----------------
    def _build_backup(self, hinst):
        p = self._page('backup')
        x = SIDEBAR_W + 20
        y = 20
        self._label(p, '从原版 StockWidget 导入', x, y)
        self.lbl_legacy = self._label(p, '可自动迁移原版的自选股、显示字段、样式与位置', x, y + 22)
        self.btn_legacy_detect = self._ctl(hinst, 'BUTTON', '检测原版配置', w32.BS_PUSHBUTTON,
                                            x, y + 44, 110, 28, p, 9501)
        self.btn_legacy_import = self._ctl(hinst, 'BUTTON', '一键导入', w32.BS_PUSHBUTTON,
                                            x + 120, y + 44, 100, 28, p, 9502)
        y += 92

        self._label(p, '本地备份', x, y)
        self._label(p, '导出全部配置（自选、分组、样式、快捷键）为 JSON 文件', x, y + 22)
        self.btn_export = self._ctl(hinst, 'BUTTON', '导出备份文件', w32.BS_PUSHBUTTON,
                                    x, y + 44, 110, 28, p, 9503)
        self.btn_import = self._ctl(hinst, 'BUTTON', '从文件恢复', w32.BS_PUSHBUTTON,
                                    x + 120, y + 44, 100, 28, p, 9504)
        self.cb_auto_local = self._ctl(
            hinst, 'BUTTON', '设置变动后自动备份到本地（固定一个文件，始终覆盖，不会堆积）',
            w32.BS_AUTOCHECKBOX, x, y + 80, 420, 24, p, 9506)
        y += 118

        self._label(p, '重置', x, y)
        self._label(p, '恢复出厂默认设置，当前自选股将被清空', x, y + 22)
        self.btn_reset = self._ctl(hinst, 'BUTTON', '恢复默认设置', w32.BS_PUSHBUTTON,
                                   x, y + 44, 110, 28, p, 9505)

    # ---------------- WebDAV ----------------
    def _build_dav(self, hinst):
        p = self._page('dav')
        x = SIDEBAR_W + 20
        y = 20
        self._label(p, 'WebDAV 服务器地址', x, y)
        self.ed_dav_url = self._ctl(hinst, 'EDIT', '', 0, x, y + 20, 380, 26, p)
        y += 56
        self._label(p, '用户名', x, y)
        self.ed_dav_user = self._ctl(hinst, 'EDIT', '', 0, x, y + 20, 180, 26, p)
        self._label(p, '密码 / 应用密码', x + 200, y)
        self.ed_dav_pass = self._ctl(hinst, 'EDIT', '', 0x0081, x + 200, y + 20, 180, 26, p)
        y += 56
        self._label(p, '存储目录', x, y)
        self.ed_dav_dir = self._ctl(hinst, 'EDIT', '', 0, x, y + 20, 380, 26, p)
        y += 62
        self.btn_dav_test = self._ctl(hinst, 'BUTTON', '测试连接', w32.BS_PUSHBUTTON,
                                      x, y, 100, 28, p, 9601)
        self.btn_dav_up = self._ctl(hinst, 'BUTTON', '上传备份', w32.BS_PUSHBUTTON,
                                    x + 110, y, 100, 28, p, 9602)
        self.btn_dav_down = self._ctl(hinst, 'BUTTON', '从 WebDAV 恢复', w32.BS_PUSHBUTTON,
                                      x + 220, y, 130, 28, p, 9603)
        y += 40
        self.lbl_dav_msg = self._label(p, '', x, y)
        y += 26
        self.cb_auto_dav = self._ctl(
            hinst, 'BUTTON', '设置变动后自动同步到 WebDAV（固定文件名 dingpan-autosync.json）',
            w32.BS_AUTOCHECKBOX, x, y, 430, 24, p, 9604)
        y += 26
        self.lbl_dav_hint = self._label(
            p, '自动同步会在改完设置 4 秒后后台执行，只覆盖同一个文件，服务器上不会越积越多。', x, y)

    # ---------------- 快捷键 ----------------
    def _build_hotkeys(self, hinst):
        p = self._page('hotkeys')
        x = SIDEBAR_W + 20
        y = 14
        self._label(p, '勾选「启用」后该快捷键才生效；点右侧按钮，直接按下新的组合键即可设置', x, y)
        y += 28
        self.hk_rows = []          # [(key, 启用勾选框, 按键按钮)]
        names = [('toggleVisible', '显示 / 隐藏悬浮窗'),
                 ('refresh', '立即刷新行情'),
                 ('openSettings', '打开设置窗口'),
                 ('nextGroup', '切换到下一分组')]
        for i, (key, label) in enumerate(names):
            chk = self._ctl(hinst, 'BUTTON', '启用', w32.BS_AUTOCHECKBOX,
                            x, y + 1, 58, 24, p, 9800 + i)
            self._label(p, label, x + 64, y + 4)
            btn = self._ctl(hinst, 'BUTTON', '', w32.BS_PUSHBUTTON,
                            x + 250, y, 160, 26, p, 9810 + i)
            self.hk_rows.append((key, chk, btn))
            y += 32
        self.btn_hk_reset = self._ctl(hinst, 'BUTTON', '恢复默认快捷键', w32.BS_PUSHBUTTON,
                                      x, y + 6, 130, 28, p, 9701)
        self.btn_hk_clear = self._ctl(hinst, 'BUTTON', '全部禁用', w32.BS_PUSHBUTTON,
                                      x + 140, y + 6, 100, 28, p, 9702)
        y += 44
        self.lbl_hk_msg = self._label(p, '未被勾选或被占用的组合不会注册，不会影响系统其它快捷键。', x, y)
        y += 26
        self._label(p, '窗口内快捷键（悬浮窗有焦点时生效）', x, y)
        y += 22
        for k, d in [('Ctrl+N', '添加自选股'), ('↑ / ↓', '选择行'),
                     ('Delete', '删除选中自选股'), ('双击行', '打开行情网页'),
                     ('右键行', '打开操作菜单')]:
            self._label(p, f'{k}    {d}', x + 8, y)
            y += 21

    # ---------------- 关于 ----------------
    def _build_about(self, hinst):
        p = self._page('about')
        x = SIDEBAR_W + 20
        y = 30
        self._label(p, '盯盘  DingPan  v%s      构建：%s' % (_version(), _build_tag()), x, y)
        y += 28
        self.lbl_about = self._label(
            p, '桌面悬浮行情挂件\n支持多自选分组 / 多数据源 / 显示字段自定义 / 样式主题配置\n'
               '本地与 WebDAV 备份恢复 / 全局快捷键', x, y)
        y += 80
        self.lbl_cfgpath = self._label(p, f'配置位置：{storage.config_path()}', x, y)

    # ---------------- 辅助 ----------------
    def _page(self, key):
        """切换「当前页面」标记：把控件直接挂在主窗口上，按页记录句柄以显隐"""
        self._cur_page = key
        self.page_keys.setdefault(key, [])
        return self.hwnd

    def _track(self, h):
        """把控件归入当前页面（用于页面切换显隐）"""
        if self._cur_page:
            self.page_keys.setdefault(self._cur_page, []).append(h)
        return h

    def _label(self, parent, text, x, y, w=None):
        hinst = kernel32.GetModuleHandleW(None)
        # 宽度自适应到客户区右边界，避免控件矩形越过窗口（长文本会被裁）
        # ⚠️ w 参数：多栏布局时必须显式限宽，否则标签会盖住右栏的控件
        if w is None:
            w = max(60, CLIENT_W - x - 16)
        # 多行提示要给够高度，否则 STATIC 只显示第一行（之前提示语被吃掉就是这个原因）
        text = str(text or '')
        lines = text.split('\n')
        # ⚠️ STATIC 会按控件宽度**自动换行**，实际行数可能比 '\n' 数多 ——
        #    高度按 '\n' 算就会把多出来的行裁掉（v1.0.20 出现过）。
        #    这里按「每行最多能放多少个字符」估算真实行数，宁可留高一点。
        per_line = max(8, int(w / 13))       # 13px 一个汉字（含标点）大致宽度
        n = 0
        for ln in lines:
            n += max(1, (len(ln) + per_line - 1) // per_line)
        h = 20 if n == 1 else 18 * n + 4
        return self._ctl(hinst, 'STATIC', text, 0, x, y, w, h, parent)

    def _set_label(self, label, text):
        """更新 STATIC 文本（原生控件需走 Win32 API）"""
        if label is not None:
            user32.SetWindowTextW(label, str(text))

    def _show_page(self, pid):
        self.page = pid
        id2key = {P_BASIC: 'basic', P_STOCKS: 'stocks', P_COLUMNS: 'columns',
                  P_STYLE: 'style', P_BACKUP: 'backup', P_DAV: 'dav',
                  P_HOTKEY: 'hotkeys', P_ABOUT: 'about'}
        cur = id2key.get(pid)
        # 隐藏所有页面控件，再显示当前页
        for key, hs in self.page_keys.items():
            for h in hs:
                if user32.IsWindow(h):
                    user32.ShowWindow(h, w32.SW_SHOW if key == cur else w32.SW_HIDE)
        # 加固：强制重绘整窗及子控件（部分系统上 ShowWindow 后不会自动重画）
        if self.hwnd and user32.IsWindow(self.hwnd):
            try:
                user32.RedrawWindow(self.hwnd, None, None,
                                    0x0001 | 0x0004 | 0x0080 | 0x0100)  # INVALIDATE|ERASE|ALLCHILDREN|UPDATENOW
            except Exception:  # noqa: BLE001
                pass
        # ⚠️ 上面的循环把**所有**页面控件都设成了 SW_SHOW，
        #    会把「按需显示」的控件（自定义数据源区、自定义平台地址）也显示出来。
        #    所以每次切页后都要重新同步一次这些控件的显隐状态。
        try:
            self._sync_custom_source_enabled()
            self._sync_quote_url_enabled()
        except Exception:  # noqa: BLE001
            pass
        # 高亮导航
        for p, b in self.tab_buttons:
            user32.SendMessageW(b, 0x00F1, 1 if p == pid else 0, 0)  # BM_SETCHECK

    def _load_ui(self):
        cfg = self.app.cfg
        # 基础
        sids = self._source_ids()
        try:
            self._set_combo_sel(self.cb_source, sids.index(cfg.get('source', 'tencent')))
        except ValueError:
            self._set_combo_sel(self.cb_source, 0)
        # 自定义数据源
        cs = cfg.get('customSource') or {}
        self._set_text(self.ed_cust_url, cs.get('url', ''))
        self._set_text(self.ed_cust_map, cs.get('mapping', ''))
        self._set_text(self.ed_cust_codekey, cs.get('codeKey', 'code') or 'code')
        try:
            self._set_combo_sel(self.cb_cust_enc,
                                ['utf-8', 'gbk'].index(str(cs.get('encoding', 'utf-8')).lower()))
        except ValueError:
            self._set_combo_sel(self.cb_cust_enc, 0)
        self._set_label(self.lbl_cust_msg, '')
        self._set_text(self.ed_interval, str(int(cfg.get('refreshInterval', 5000) / 1000)))
        self._set_text(self.ed_width, str(cfg.get('width', 320)))
        self._set_text(self.ed_title, cfg.get('title', ''))
        self._set_check(self.cb_topmost, cfg.get('alwaysOnTop', True))
        self._set_check(self.cb_header, cfg.get('showHeader', True))
        self._set_check(self.cb_table_head, cfg.get('showTableHead', True))
        self._set_check(self.cb_status, cfg.get('showStatus', True))
        self._set_check(self.cb_autosize, cfg.get('autoSize', True))
        self._set_check(self.cb_border, cfg.get('showBorder', False))
        self._set_check(self.cb_gridlines, cfg.get('showGridLines', True))
        # 行情页平台
        try:
            pid = list(quotes.QUOTE_PLATFORMS.keys()).index(
                cfg.get('quotePlatform', 'xueqiu'))
        except ValueError:
            pid = 0
        self._set_combo_sel(self.cb_quote_platform, pid)
        self._set_text(self.ed_quote_url, cfg.get('quoteUrlTemplate', ''))
        total_stocks = sum(len(g.get('stocks', [])) for g in cfg.get('groups', []))
        self._set_label(self.lbl_basic_info,
                        f"数据源：腾讯 / 新浪 / 东方财富（失败自动降级）　"
                        f"当前自选 {total_stocks} 只")

        # 自选
        self._fill_list(self.lb_groups, [g.get('name', '') for g in cfg.get('groups', [])])
        self._refresh_stock_list()

        # 字段（单列表：勾选 = 显示，顺序 = 排列）
        self._field_order = self._init_field_order()
        self._fill_field_list()
        self._set_text(self.ed_name_chars, str(int(cfg.get('nameChars', 0) or 0)))
        # 显示方案下拉框
        self._fill_preset_combo()
        self._set_label(self.lbl_preset_msg, '')

        # 样式
        theme = cfg.get('theme', 'dark')
        self._set_check(self.rb_dark, theme == 'dark')
        self._set_check(self.rb_light, theme == 'light')
        self._set_check(self.rb_custom, theme == 'custom')
        bg_a = int(cfg.get('bgAlpha', 100))
        tx_a = int(cfg.get('textAlpha', 100))
        self._set_trackbar(self.sb_bg, bg_a, 20, 100)
        self._set_label(self.lbl_bg, f'{bg_a}%')
        self._set_trackbar(self.sb_text, tx_a, 20, 100)
        self._set_label(self.lbl_text, f'{tx_a}%')
        try:
            oi = {'auto': 0, 'on': 1, 'off': 2}.get(
                str(cfg.get('textOutline', 'auto')).lower(), 0)
            self._set_combo_sel(self.cb_outline, oi)
        except Exception:  # noqa: BLE001
            pass
        self._set_text(self.btn_bg_color, cfg.get('customBg', '#1c1f28'))
        self._set_text(self.btn_text_color, cfg.get('customText', '#e6e8ef'))
        try:
            self._set_combo_sel(self.cb_font,
                                max(0, min(10, int(cfg.get('fontSize', 13)) - 10)))
        except (TypeError, ValueError):
            self._set_combo_sel(self.cb_font, 3)
        up = cfg.get('upColor', '#f6465d')
        down = cfg.get('downColor', '#0ecb81')
        self._select_color_combo(self.cb_up, up)
        self._select_color_combo(self.cb_down, down)

        # WebDAV
        w = cfg.get('webdav') or {}
        self._set_text(self.ed_dav_url, w.get('url', ''))
        self._set_text(self.ed_dav_user, w.get('username', ''))
        self._set_text(self.ed_dav_pass, w.get('password', ''))
        self._set_text(self.ed_dav_dir, w.get('dir', '/dingpan'))
        self._set_check(self.cb_auto_dav, cfg.get('autoDavSync', False))
        self._set_check(self.cb_auto_local, cfg.get('autoLocalBackup', True))

        # 快捷键
        hks = cfg.get('hotkeys') or {}
        enabled = cfg.get('hotkeyEnabled') or {}
        for i, (key, chk, btn) in enumerate(self.hk_rows):
            self._set_check(chk, enabled.get(key, True))
            self._set_text(btn, hks.get(key, '') or '（未设置）')
            del i

        # 自定义数据源区：只有选中「自定义接口…」才可编辑
        self._sync_custom_source_enabled()
        # 自定义平台地址：只有平台选「自定义…」才显示
        self._sync_quote_url_enabled()

    def on_sync_msg(self):
        """自动同步完成后刷新提示（由 App 在 UI 线程调用）"""
        msg = getattr(self.app, 'sync_msg', '') or ''
        if msg and getattr(self, 'lbl_dav_msg', None):
            self._set_label(self.lbl_dav_msg, msg)

    def _refresh_stock_list(self):
        groups = self.app.cfg.get('groups') or []
        idx = self.app.group_index()
        names = []
        for i, g in enumerate(groups):
            mark = '● ' if i == idx else '   '
            names.append(f"{mark}{g.get('name', '')} ({len(g.get('stocks', []))})")
        self._fill_list(self.lb_groups, names)
        # 左侧分组保持选中「当前分组」，否则右侧列表无从判断该显示谁
        if groups:
            self._set_list_sel(self.lb_groups, idx if 0 <= idx < len(groups) else 0)
        self._fill_stock_list()

    def _sync_widget_stocks(self):
        """自选列表变了 → 立刻让悬浮窗重画。

        勾选 / 取消勾选 / 新增 / 删除都要走这里，
        否则悬浮窗里还留着旧的自选股（用户反馈「取消勾选后还在显示」、
        「添加新自选后悬浮窗里没增加」）。
        """
        try:
            w = self.app.widget
            if not w.hwnd:
                return
            # ⚠️ 必须把 app.cfg **本身**给 widget（不是副本），
            #    否则 widget 看到的还是旧的 groups。
            w.cfg = self.app.cfg
            w.release_fonts()
            self.app._apply_auto_size()
            # ⚠️ 用 paint() **立即同步重绘**，不要只用 paint_now() ——
            #    paint_now() 只是发 InvalidateRect，要等消息泵轮到才重画，
            #    用户会看到「改了没反应」。
            w.paint_now()
            w.paint()
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 自选列表（复选框 + 拖动排序）----------------
    CHECKBOX_W = 26          # 左侧「[√]」标记区域宽度（点这里切换显示/隐藏）
    ROW_H = 20

    def _stocklist_rows(self):
        """当前分组里要显示的自选项（含 enabled 标记）"""
        groups = self.app.cfg.get('groups') or []
        gi = self.app.group_index()
        sel = self._get_list_sel(self.lb_groups)
        if 0 <= sel < len(groups):
            gi = sel
        if not (0 <= gi < len(groups)):
            return []
        # 返回**真实引用**而不是副本 —— 拖动排序要直接改配置里的顺序
        return groups[gi].setdefault('stocks', [])

    def _stocklist_label(self, s):
        """列表项文本：前面带勾选标记，后面是「代码 名称」"""
        code = s.get('code', '') or ''
        name = s.get('name', '') or ''
        mark = '[√]' if s.get('enabled', True) else '[  ]'
        return ('%s %s %s' % (mark, code, name)).strip()

    def _checklist_index_at(self, y):
        """客户区 y → 行号"""
        if y < 0:
            return -1
        return int(y // self.ROW_H)

    # ---- 自绘（三列：复选框 / 文字 / 拖拽手柄）----
    # 系统色索引
    COLOR_WINDOW = 5
    COLOR_WINDOWTEXT = 8
    COLOR_HIGHLIGHT = 16
    COLOR_HIGHLIGHTTEXT = 17
    COLOR_3DDKSHADOW = 4
    COLOR_GRAYTEXT = 17
    DT_SINGLELINE = 0x0020
    DT_VCENTER = 0x0004
    TRANSPARENT = 1
    HANDLE_W = 22          # 右侧拖拽手柄区宽度（选中高亮不覆盖这一块）

    def _sys_color(self, idx):
        try:
            return user32.GetSysColor(idx)
        except Exception:  # noqa: BLE001
            return 0x00000000

    def _draw_checkbox(self, dc, x, y, checked, color):
        """画一个 12x12 的复选框（勾选时打勾）"""
        box = wintypes.RECT(x, y, x + 12, y + 12)
        gdi32.SetBkMode(dc, self.TRANSPARENT)
        # 框线
        pen = gdi32.CreateSolidBrush(color)
        user32.FrameRect(dc, ctypes.byref(box), pen)
        gdi32.DeleteObject(pen)
        if not checked:
            return
        # 打勾：两条短线（在 12x12 的框内居中）
        old_pen = gdi32.SelectObject(dc, pen)
        gdi32.MoveToEx(dc, x + 3, y + 6, None)
        gdi32.LineTo(dc, x + 5, y + 9)
        gdi32.MoveToEx(dc, x + 5, y + 9, None)
        gdi32.LineTo(dc, x + 9, y + 3)
        gdi32.SelectObject(dc, old_pen)
        gdi32.DeleteObject(pen)


    def _draw_drag_handle(self, dc, x, y, color):
        """画右侧的拖拽手柄（两列三点，像「⠿」）"""
        pen = gdi32.CreateSolidBrush(color)
        old_pen = gdi32.SelectObject(dc, pen)
        for col in range(2):
            for row in range(3):
                px = x + col * 5
                py = y + 2 + row * 4
                # 每个点画一个 2x2 的小方块
                r = wintypes.RECT(px, py, px + 2, py + 2)
                user32.FillRect(dc, ctypes.byref(r), pen)
        gdi32.SelectObject(dc, old_pen)
        gdi32.DeleteObject(pen)

    def _draw_checklist(self, hwnd):
        """自绘列表内容：左复选框 + 中文字 + 右拖拽手柄。

        ⚠️ 走的是「子类化后拦截 WM_PAINT」，不是 owner-draw ——
        实测本机 owner-draw 的 WM_DRAWITEM 一次都不触发，列表会画成空白。
        """
        # ⚠️ 必须用 GetDC 而不是 BeginPaint！
        #    BeginPaint 返回的 DC 被**裁剪到「更新区域」**，而更新区域是按
        #    **原生 listbox 的行高（16px）**算的；我按 20px 画 → 同一个字被画到
        #    两个不同位置 → **重影**（用户反馈）。
        #    GetDC 拿到整个客户区，每帧完整重画一遍，不会错位。
        hdc = user32.GetDC(hwnd)
        if not hdc:
            return
        try:
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            w, h = rect.right, rect.bottom
            # 背景
            brush = gdi32.CreateSolidBrush(self._sys_color(self.COLOR_WINDOW))
            user32.FillRect(hdc, ctypes.byref(rect), brush)
            gdi32.DeleteObject(brush)

            count = user32.SendMessageW(hwnd, 0x018B, 0, 0)   # LB_GETCOUNT
            if count <= 0:
                return
            top = user32.SendMessageW(hwnd, 0x018E, 0, 0)    # LB_GETTOPINDEX
            cur = self._cl_sel(_STOCKLIST_ROLE.get(int(hwnd), 'stocks'))
            rh = self.ROW_H
            # 字体
            if self._font:
                gdi32.SelectObject(hdc, self._font)
            gdi32.SetBkMode(hdc, self.TRANSPARENT)
            for i in range(top, count):
                y = (i - top) * rh
                if y >= h:
                    break
                label = self._lb_text(hwnd, i)
                checked = label.startswith(FIELD_MARK_ON)
                # 剥掉文本前缀（[√] 是 3 个字符，[  ] 是 4 个，长度不一致 → 用 find(']')）
                name = label
                if label.startswith('['):
                    end = label.find(']')
                    if end > 0:
                        name = label[end + 1:].strip()
                # 选中行高亮：只画到「拖拽手柄」左边，
                # 右边留出手柄区（用户反馈「选中行背景超出，把手柄盖住了」）
                if i == cur:
                    hb = gdi32.CreateSolidBrush(self._sys_color(self.COLOR_HIGHLIGHT))
                    rr = wintypes.RECT(0, y, max(0, w - self.HANDLE_W), y + rh)
                    user32.FillRect(hdc, ctypes.byref(rr), hb)
                    gdi32.DeleteObject(hb)
                    tcol = self._sys_color(self.COLOR_HIGHLIGHTTEXT)
                else:
                    tcol = self._sys_color(self.COLOR_WINDOWTEXT)
                # 左：复选框
                self._draw_checkbox(hdc, 5, y + (rh - 12) // 2, checked,
                                    self._sys_color(self.COLOR_3DDKSHADOW))
                # 中：文字
                gdi32.SetTextColor(hdc, tcol)
                tr = wintypes.RECT(self.CHECKBOX_W + 2, y,
                                   max(self.CHECKBOX_W + 3, w - 26), y + rh)
                user32.DrawTextW(hdc, name, len(name), ctypes.byref(tr),
                                 self.DT_SINGLELINE | self.DT_VCENTER)
                # 右：拖拽手柄
                self._draw_drag_handle(hdc, w - 14, y + (rh - 12) // 2,
                                       self._sys_color(self.COLOR_GRAYTEXT))
        finally:
            user32.ReleaseDC(hwnd, hdc)
            # 标记为已更新，避免系统重复投递 WM_PAINT
            user32.ValidateRect(hwnd, None)

    def _checklist_proc(self, hwnd, msg, wparam, lparam):
        """可勾选列表的子类化处理：自绘 + 勾选切换 + 拖动排序。

        role 决定用哪套数据与回调（'stocks' 自选管理页 / 'fields' 显示字段页）。
        返回 None 表示「不拦截，交给原窗口过程」。
        """
        role = _STOCKLIST_ROLE.get(int(hwnd), 'stocks')
        drag = self._drag_state.get(role)
        # ⚠️ WM_PAINT 单独处理，**任何情况下都不转发给原生窗口过程** ——
        #    一旦转发，原生 listbox 会把自己的内容也画一遍 → 与自绘重叠 → 重影。
        if msg == w32.WM_PAINT:
            try:
                self._draw_checklist(hwnd)
            except Exception:  # noqa: BLE001
                # ⚠️ 绝不能静默吞掉：绘制一失败，列表就变成空白/缺行，
                #    而界面上一���异常都没有 → 极难排查。必须落盘。
                try:
                    import datetime
                    import traceback
                    from .storage import app_dir
                    with open(os.path.join(app_dir(), 'crash.log'), 'a',
                              encoding='utf-8') as f:
                        f.write('\n===== settings._draw_checklist | %s =====\n'
                                % datetime.datetime.now())
                        traceback.print_exc(file=f)
                except Exception:  # noqa: BLE001
                    pass
            return 0
        try:
            if msg == w32.WM_LBUTTONDOWN:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                idx = self._checklist_index_at(y)
                if 0 <= idx < len(self._checklist_rows(role)):
                    if x <= self.CHECKBOX_W:
                        # 点勾选标记 → 切换「显示 / 不显示」
                        self._checklist_toggle(role, idx)
                        return 0
                    # 设为选中行（原生 listbox 收不到 LBUTTONDOWN，选中不会自动变）
                    # ⚠️ 只改 Python 侧状态，**不要发 LB_SETCURSEL** ——
                    #    那会让原生立刻用自己的样式画一遍选中行，覆盖自绘。
                    self._cl_set_sel(role, idx)
                    # 否则进入拖动排序
                    self._drag_state[role] = {'row': idx, 'from_y': y,
                                              'to': idx, 'moved': False}
                    try:
                        user32.SetCapture(hwnd)
                    except Exception:  # noqa: BLE001
                        pass
                    return 0
            if msg == w32.WM_MOUSEMOVE and drag:
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                if abs(y - drag['from_y']) > 4:
                    drag['moved'] = True
                to = self._checklist_index_at(y)
                if to != drag['to'] and 0 <= to < len(self._checklist_rows(role)):
                    drag['to'] = to
                    self._checklist_move(role, drag['row'], to)
                    drag['row'] = to
                    self._cl_set_sel(role, to)
                    drag['from_y'] = y
                    user32.InvalidateRect(hwnd, None, True)
                return 0
            if msg == w32.WM_LBUTTONUP:
                if drag:
                    try:
                        user32.ReleaseCapture()
                    except Exception:  # noqa: BLE001
                        pass
                    self._drag_state[role] = None
                    # 同步刷新一次，让选中高亮立刻出现
                    try:
                        user32.InvalidateRect(hwnd, None, True)
                        user32.UpdateWindow(hwnd)
                    except Exception:  # noqa: BLE001
                        pass
                    return 0
            if msg == w32.WM_CAPTURECHANGED:
                self._drag_state[role] = None
                return None
        except Exception:  # noqa: BLE001
            pass
        return None

    # ---- role 分派：自选列表 ----
    def _checklist_rows(self, role):
        if role == 'fields':
            return self._field_order
        return self._stocklist_rows()

    def _checklist_toggle(self, role, idx):
        if role == 'fields':
            return self._toggle_field_enabled(idx)
        return self._toggle_stock_enabled(idx)

    def _checklist_move(self, role, frm, to):
        if role == 'fields':
            return self._move_field_row(frm, to)
        return self._move_stock_row(frm, to)

    def _toggle_stock_enabled(self, idx):
        """切换某只自选股的「显示 / 不显示」"""
        rows = self._stocklist_rows()
        if not (0 <= idx < len(rows)):
            return
        rows[idx]['enabled'] = not rows[idx].get('enabled', True)
        self._sync_stock_enabled()
        self._fill_stock_list()
        user32.InvalidateRect(self.lb_stocks, None, True)
        # 悬浮窗里要立刻少一只 / 多一只
        self._sync_widget_stocks()

    def _move_stock_row(self, frm, to):
        """把第 frm 行拖到第 to 行的位置"""
        rows = self._stocklist_rows()
        if not (0 <= frm < len(rows)) or not (0 <= to < len(rows)) or frm == to:
            return
        item = rows.pop(frm)
        rows.insert(to, item)
        # ⚠️ 必须重填列表并重绘，否则用户看不到顺序变化
        #    （只改配置 → 列表还是旧顺序 → 感觉「拖不动」）
        # keep_sel=to：选中框要跟着被拖的那一行走，否则高亮留在原地
        self._fill_stock_list(keep_sel=to)
        user32.InvalidateRect(self.lb_stocks, None, True)
        # 顺序变了 → 悬浮窗里的行顺序也要跟着变
        self._sync_widget_stocks()

    def _sync_stock_enabled(self):
        """把勾选状态写回配置（按当前分组的股票顺序对齐）"""
        groups = self.app.cfg.get('groups') or []
        gi = self.app.group_index()
        sel = self._get_list_sel(self.lb_groups)
        if 0 <= sel < len(groups):
            gi = sel
        if not (0 <= gi < len(groups)):
            return
        stocks = groups[gi].get('stocks', []) or []
        for s in stocks:
            if 'enabled' not in s:
                s['enabled'] = True
        self.app.cfg['groups'] = groups

    def _fill_stock_list(self, keep_sel=None):
        """把当前分组的自选股填进右侧列表。

        keep_sel：重填后要把选中放在第几行（None = 保持原选中位置）。
        拖动排序时必须传**目标行号**，否则选中框会留在原地不跟着走。
        """
        groups = self.app.cfg.get('groups') or []
        gi = self.app.group_index()
        if not (0 <= gi < len(groups)):
            self._fill_list(self.lb_stocks, [])
            return
        sel = self._get_list_sel(self.lb_groups)
        if 0 <= sel < len(groups):
            gi = sel  # 以左侧列表框的选中项为准
        stocks = groups[gi].get('stocks', []) or []
        # 记住当前位置：重填（LB_RESETCONTENT）会把选中清掉
        keep = (self._cl_sel('stocks') if keep_sel is None else keep_sel)
        top = user32.SendMessageW(self.lb_stocks, 0x018E, 0, 0)  # LB_GETTOPINDEX
        # 项文本 = 「[√] 代码 名称」，前缀表示显示/隐藏状态
        # （方框与拖拽手柄由自绘画，见 _draw_checklist）
        self._fill_list(self.lb_stocks, [self._stocklist_label(s) for s in stocks])
        self._cl_set_sel('stocks', keep if 0 <= keep < len(stocks) else -1)
        if top:
            user32.SendMessageW(self.lb_stocks, 0x0197, top, 0)  # LB_SETTOPINDEX
        # 自绘列表：填完后同步重绘一次，保证内容是最新的
        user32.InvalidateRect(self.lb_stocks, None, True)
        user32.UpdateWindow(self.lb_stocks)

    # ---------------- 控件读写 ----------------
    def _set_text(self, hwnd, text):
        user32.SetWindowTextW(hwnd, str(text or ''))

    def _get_text(self, hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _set_check(self, hwnd, checked):
        user32.SendMessageW(hwnd, 0x00F1, 1 if checked else 0, 0)  # BM_SETCHECK

    def _get_check(self, hwnd):
        return user32.SendMessageW(hwnd, 0x00F0, 0, 0) == 1  # BM_GETCHECK

    def _set_combo_sel(self, combo, idx):
        user32.SendMessageW(combo, 0x014E, idx, 0)  # CB_SETCURSEL

    def _get_combo_sel(self, combo):
        return user32.SendMessageW(combo, 0x0147, 0, 0)  # CB_GETCURSEL

    def _set_combo_by_text(self, combo, hexcolor):
        items = self._combo_items(combo)
        for i, t in enumerate(items):
            if hexcolor and hexcolor.lower() in t.lower():
                self._set_combo_sel(combo, i)
                return
        self._set_combo_sel(combo, 0)

    def _combo_items(self, combo):
        count = user32.SendMessageW(combo, 0x0146, 0, 0)  # CB_GETCOUNT
        out = []
        for i in range(count):
            n = user32.SendMessageW(combo, 0x0149, i, 0)  # CB_GETLBTEXTLEN
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.SendMessageW(combo, 0x0148, i, ctypes.cast(buf, ctypes.c_void_p).value)
            out.append(buf.value)
        return out

    def _fill_list(self, lb, items):
        LB_RESETCONTENT = 0x0184
        LB_ADDSTRING = 0x0180
        user32.SendMessageW(lb, LB_RESETCONTENT, 0, 0)
        for it in items:
            w32.send_msg_text(lb, LB_ADDSTRING, 0, str(it))
        # ⚠️ 这里**只能**异步 InvalidateRect，不能同步 UpdateWindow ——
        #    UpdateWindow 可能被嵌套在 WM_PAINT 处理里（LB_ADDSTRING 会触发重绘），
        #    嵌套重绘会让列表只画出前几项、甚至整块空白。
        #    需要「立刻重画」的地方（自绘列表）在填充函数末尾单独调。
        user32.InvalidateRect(lb, None, True)

    def _cl_sel(self, role):
        """自绘列表的当前选中行（Python 侧状态）"""
        return self._checklist_sel.get(role, -1)

    def _cl_set_sel(self, role, idx):
        """设置自绘列表的选中行 —— 只改 Python 状态，不碰原生 listbox。

        改完要主动重绘：原生选中机制被绕开了，不会自动刷新高亮。
        """
        self._checklist_sel[role] = int(idx)
        # 只发 InvalidateRect（**不要**在这里同步 UpdateWindow：
        # 它可能被嵌套在另一个 WM_PAINT 里 → 递归重绘 → 列表只画出前几行）。
        lb = (getattr(self, 'lb_stocks', None) if role == 'stocks'
              else getattr(self, 'lb_fields', None))
        try:
            if lb:
                user32.InvalidateRect(lb, None, True)
        except Exception:  # noqa: BLE001
            pass

    def _get_list_sel(self, lb):
        return user32.SendMessageW(lb, 0x0188, 0, 0)  # LB_GETCURSEL

    def _set_list_sel(self, lb, idx):
        user32.SendMessageW(lb, 0x0186, idx, 0)  # LB_SETCURSEL

    def _set_trackbar(self, hwnd, pos, lo, hi):
        # 正确的消息号（原来把 TBM_SETRANGE 写成 0x0405 = TBM_SETPOS，
        # 导致设范围时其实在设位置，滑块永远停最大值）。
        TBM_SETRANGE = 0x0406   # WM_USER+6
        TBM_SETPOS = 0x0405     # WM_USER+5
        user32.SendMessageW(hwnd, TBM_SETRANGE, 1, (hi << 16) | lo)
        user32.SendMessageW(hwnd, TBM_SETPOS, 1, pos)

    def _get_trackbar(self, hwnd):
        return user32.SendMessageW(hwnd, 0x0400, 0, 0)  # TBM_GETPOS = WM_USER

    def _font_size_now(self):
        """当前选中的字号（10-20）"""
        i = self._get_combo_sel(self.cb_font)
        if 0 <= i <= 10:
            return 10 + i
        try:
            return max(10, min(20, int(self.cfg.get('fontSize', 13))))
        except (TypeError, ValueError):
            return 13

    # ---------------- 数据源 ----------------
    def _source_ids(self):
        """下拉框顺序对应的源 id 列表（最后一项是自定义）"""
        return list(quotes.SOURCES.keys()) + ['custom']

    def _source_now(self):
        """当前选中的数据源 id"""
        i = self._get_combo_sel(self.cb_source)
        ids = self._source_ids()
        return ids[i] if 0 <= i < len(ids) else 'tencent'

    def _set_source(self, source_id):
        """按源 id 选中下拉框，并同步自定义区启用状态"""
        ids = self._source_ids()
        try:
            idx = ids.index(source_id)
        except ValueError:
            idx = 0
        self._set_combo_sel(self.cb_source, idx)
        self._sync_custom_source_enabled()

    def _sync_custom_source_enabled(self):
        """只有选中「自定义接口…」时才显示/启用那组控件"""
        on = (self._source_now() == 'custom')
        for ctrl in (getattr(self, 'ed_cust_url', None),
                     getattr(self, 'ed_cust_map', None),
                     getattr(self, 'ed_cust_codekey', None),
                     getattr(self, 'cb_cust_enc', None),
                     getattr(self, 'btn_cust_test', None),
                     getattr(self, 'lbl_custom_src', None),
                     getattr(self, 'lbl_cust_url', None),
                     getattr(self, 'lbl_cust_map', None),
                     getattr(self, 'lbl_cust_enc', None),
                     getattr(self, 'lbl_cust_ck', None),
                     getattr(self, 'lbl_cust_msg', None),
                     getattr(self, 'lbl_cust_hint', None)):
            if ctrl and user32.IsWindow(ctrl):
                user32.EnableWindow(ctrl, 1 if on else 0)
                user32.ShowWindow(ctrl, w32.SW_SHOW if on else w32.SW_HIDE)
        lbl = getattr(self, 'lbl_cust_msg', None)
        if lbl and not on:
            self._set_label(lbl, '')

    def _sync_quote_url_enabled(self):
        """只有平台选「自定义…」时才显示自定义地址输入框"""
        keys = list(quotes.QUOTE_PLATFORMS.keys())
        i = self._get_combo_sel(self.cb_quote_platform)
        on = (0 <= i < len(keys) and keys[i] == 'custom')
        for ctrl in (getattr(self, 'lbl_quote_url', None),
                     getattr(self, 'ed_quote_url', None),
                     getattr(self, 'lbl_quote_ph', None)):
            if ctrl and user32.IsWindow(ctrl):
                user32.ShowWindow(ctrl, w32.SW_SHOW if on else w32.SW_HIDE)
                if on and ctrl == self.ed_quote_url:
                    user32.EnableWindow(ctrl, 1)

    def _custom_spec_now(self):
        """从界面上读出自定义数据源配置"""
        enc_i = self._get_combo_sel(self.cb_cust_enc)
        encs = ['utf-8', 'gbk']
        return {
            'url': (self._get_text(self.ed_cust_url) or '').strip(),
            'mapping': (self._get_text(self.ed_cust_map) or '').strip(),
            'encoding': encs[enc_i] if 0 <= enc_i < len(encs) else 'utf-8',
            'codeKey': (self._get_text(self.ed_cust_codekey) or 'code').strip() or 'code',
        }

    def _test_custom_source(self):
        """点「测试接口」：后台线程抓一次，结果回 UI 线程显示"""
        spec = self._custom_spec_now()
        if not spec['url']:
            self._set_label(self.lbl_cust_msg, '✗ 请先填写接口地址')
            return
        self.btn_cust_test = getattr(self, 'btn_cust_test', None)
        if self.btn_cust_test:
            user32.EnableWindow(self.btn_cust_test, 0)
        self._set_label(self.lbl_cust_msg, '正在测试…')

        def worker():
            ok, msg, _n = quotes.test_custom_source(spec)
            self._custom_test_result = (ok, msg)
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_CUSTOM_TEST_DONE, 0, 0)

        threading.Thread(target=worker, daemon=True).start()

    def _on_custom_test_done(self):
        res = getattr(self, '_custom_test_result', None)
        self._custom_test_result = None
        if self.btn_cust_test:
            user32.EnableWindow(self.btn_cust_test, 1)
        if not res:
            return
        ok, msg = res
        self._set_label(self.lbl_cust_msg, ('✓ ' if ok else '✗ ') + msg)

    # ---------------- 样式即时预览 ----------------
    def _theme_now(self):
        if self._get_check(self.rb_light):
            return 'light'
        if self._get_check(self.rb_custom):
            return 'custom'
        return 'dark'

    def _select_theme(self, name):
        # 单选按钮用 BM_SETCHECK 不会自动互斥，必须手动清一遍
        for rb, val in ((self.rb_dark, 'dark'), (self.rb_light, 'light'),
                        (self.rb_custom, 'custom')):
            self._set_check(rb, val == name)

    # ---------------- 显示方案 ----------------
    # 「显示方案」= 一整套显示配置（不只是字段）
    DISPLAY_KEYS = ('theme', 'customBg', 'customText', 'bgAlpha', 'textAlpha',
                    'fontSize', 'nameChars', 'upColor', 'downColor',
                    'showTableHead', 'showStatus', 'showHeader',
                    'showBorder', 'showGridLines', 'textOutline')

    def _default_display(self):
        """默认显示配置（方案没写到的键用这个兜底）"""
        d = storage.DEFAULT_CONFIG
        return {k: d.get(k) for k in self.DISPLAY_KEYS}

    def _presets(self):
        """当前可用的显示方案（内置 + 用户自定义）

        每个方案 = {'name', 'builtin', 'columns', 'display'}，
        display 是完整的显示配置快照。
        """
        base = self._default_display()
        out = []
        for p in (storage.DEFAULT_CONFIG.get('presets') or []):
            disp = dict(base)
            disp.update(p.get('display') or {})
            out.append({'name': p.get('name', ''), 'builtin': True,
                        'columns': list(p.get('columns') or []), 'display': disp})
        for p in (self.app.cfg.get('presets') or []):
            if p.get('builtin'):
                continue
            disp = dict(base)
            disp.update(p.get('display') or {})
            out.append({'name': p.get('name', ''), 'builtin': False,
                        'columns': list(p.get('columns') or []), 'display': disp})
        return out

    def _collect_display(self):
        """把当前界面上的显示设置读成一份快照（用于保存到方案里）"""
        def chk(name):
            ctrl = getattr(self, name, None)
            return self._get_check(ctrl) if ctrl else None
        d = {
            'theme': self._theme_now(),
            'customBg': (self._get_text(self.btn_bg_color) or '#1c1f28').strip(),
            'customText': (self._get_text(self.btn_text_color) or '#e6e8ef').strip(),
            'bgAlpha': max(20, min(100, self._get_trackbar(self.sb_bg))),
            'textAlpha': max(20, min(100, self._get_trackbar(self.sb_text))),
            'fontSize': self._font_size_now(),
            'upColor': self._combo_color(self.cb_up) or '#f6465d',
            'downColor': self._combo_color(self.cb_down) or '#0ecb81',
            'showTableHead': chk('cb_table_head'),
            'showStatus': chk('cb_status'),
            'showHeader': chk('cb_header'),
            'showBorder': chk('cb_border'),
            'showGridLines': chk('cb_gridlines'),
        }
        try:
            _oi = self._get_combo_sel(self.cb_outline)
            d['textOutline'] = ('auto', 'on', 'off')[_oi] if 0 <= _oi <= 2 else 'auto'
        except Exception:  # noqa: BLE001
            d['textOutline'] = 'auto'
        try:
            d['nameChars'] = max(0, min(20, int(self._get_text(self.ed_name_chars) or 0)))
        except (TypeError, ValueError):
            d['nameChars'] = 0
        return {k: v for k, v in d.items() if v is not None}

    def _apply_display(self, disp):
        """把一份显示配置快照套到界面 + 悬浮窗（立即可见）"""
        disp = disp or {}
        for k in self.DISPLAY_KEYS:
            if k in disp and disp[k] is not None:
                self.app.cfg[k] = disp[k]
        # 主题单选要跟着切
        theme = self.app.cfg.get('theme', 'dark')
        self._set_check(self.rb_dark, theme == 'dark')
        self._set_check(self.rb_light, theme == 'light')
        self._set_check(self.rb_custom, theme == 'custom')
        self._set_text(self.ed_name_chars, str(int(self.app.cfg.get('nameChars', 0) or 0)))
        for combo, key in ((self.cb_up, 'upColor'), (self.cb_down, 'downColor')):
            v = self.app.cfg.get(key)
            if v:
                self._select_color_combo(combo, v)

    def _fill_preset_combo(self, select_name=''):
        presets = self._presets()
        self._fill_combo(self.cb_preset, [p['name'] for p in presets])
        if select_name:
            for i, p in enumerate(presets):
                if p['name'] == select_name:
                    self._set_combo_sel(self.cb_preset, i)
                    break

    def _apply_preset(self):
        """把选中的显示方案套到悬浮窗（立即预览，不写配置）"""
        presets = self._presets()
        i = self._get_combo_sel(self.cb_preset)
        if not (0 <= i < len(presets)):
            return
        p = presets[i]
        cols = [c for c in p.get('columns') or [] if c in COLUMN_MAP]
        if not cols:
            self._set_label(self.lbl_preset_msg, '✗ 该方案没有可用字段')
            return
        # 1) 先套整套显示设置（主题/颜色/透明度/字号/开关…）
        self._apply_display(p.get('display'))
        # 2) 再套字段（勾选 + 顺序）：方案里的顺序在前，其余字段按当前顺序接在后面
        rest = [k for k in self._field_order if k not in cols]
        self._field_order = cols + rest
        self.app.cfg['columns'] = list(cols)
        self.app.cfg['fieldOrder'] = list(self._field_order)
        self._fill_field_list()
        # 3) 滑块 / 复选框 / 下拉框都要跟着刷一遍，否则界面上还是旧值
        bg_a = int(self.app.cfg.get('bgAlpha', 100))
        tx_a = int(self.app.cfg.get('textAlpha', 100))
        self._set_trackbar(self.sb_bg, bg_a, 20, 100)
        self._set_label(self.lbl_bg, f'{bg_a}%')
        self._set_trackbar(self.sb_text, tx_a, 20, 100)
        self._set_label(self.lbl_text, f'{tx_a}%')
        try:
            oi = {'auto': 0, 'on': 1, 'off': 2}.get(
                str(cfg.get('textOutline', 'auto')).lower(), 0)
            self._set_combo_sel(self.cb_outline, oi)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._set_combo_sel(self.cb_font,
                                max(0, min(10, int(self.app.cfg.get('fontSize', 13)) - 10)))
        except (TypeError, ValueError):
            pass
        for name, key in (('cb_table_head', 'showTableHead'), ('cb_status', 'showStatus'),
                          ('cb_header', 'showHeader'), ('cb_border', 'showBorder'),
                          ('cb_gridlines', 'showGridLines')):
            ctrl = getattr(self, name, None)
            if ctrl:
                self._set_check(ctrl, self.app.cfg.get(key, True))
        # 4) 立即预览到悬浮窗
        self._preview()
        self._set_label(self.lbl_preset_msg, '✓ 已套用「%s」（点「保存设置」生效）' % p['name'])

    def _save_preset(self):
        """把当前已选字段保存为一个自定义显示方案"""
        name = (self._get_text(self.ed_preset_name) or '').strip()
        if not name:
            self._set_label(self.lbl_preset_msg, '✗ 先给方案起个名字')
            return
        cols = self._get_selected_columns()
        if not cols:
            self._set_label(self.lbl_preset_msg, '✗ 当前没有选中任何字段')
            return
        saved = []
        for p in (self.app.cfg.get('presets') or []):
            if p.get('builtin'):
                continue
            if p.get('name') == name:
                continue        # 同名覆盖
            saved.append(p)
        # ⚠️ 保存**完整**的显示设置，不只是字段 —— 用户反馈过
        #    「保存后没有把所有显示的设置保存，切换后不生效」。
        disp = self._collect_display()
        disp['columns'] = list(cols)
        saved.append({'name': name, 'builtin': False, 'columns': list(cols),
                      'display': disp, 'fieldOrder': list(self._field_order)})
        self.app.cfg['presets'] = saved
        self._fill_preset_combo(name)
        self._set_label(self.lbl_preset_msg,
                        '✓ 已保存方案「%s」（含 %d 项显示设置，点「保存设置」落盘）'
                        % (name, len(disp)))

    def _delete_preset(self):
        """删除选中的自定义方案（内置方案不可删）"""
        presets = self._presets()
        i = self._get_combo_sel(self.cb_preset)
        if not (0 <= i < len(presets)):
            return
        p = presets[i]
        if p.get('builtin'):
            self._set_label(self.lbl_preset_msg, '✗ 内置方案不能删除')
            return
        saved = [x for x in (self.app.cfg.get('presets') or [])
                 if not (x.get('name') == p['name'] and not x.get('builtin'))]
        self.app.cfg['presets'] = saved
        self._fill_preset_combo()
        self._set_label(self.lbl_preset_msg, '✓ 已删除方案「%s」' % p['name'])

    def _preview(self, show_alpha=False):
        """把当前界面上的样式即时套到悬浮窗（只在内存里改，不写配置）。

        用户改任何一项都立刻能看到效果，不用点「保存设置」。
        show_alpha=True 时（拖透明度滑块）会在悬浮窗状态栏同时显示两个值 ——
        让用户能直观确认「拖背景时文字值没变」，两条通道确实是分开的。
        """
        try:
            w = self.app.widget
            if not w.hwnd:
                return
            cfg = dict(self.app.cfg)
            cfg['theme'] = self._theme_now()
            cfg['bgAlpha'] = max(20, min(100, self._get_trackbar(self.sb_bg)))
            cfg['textAlpha'] = max(20, min(100, self._get_trackbar(self.sb_text)))
            cfg['fontSize'] = self._font_size_now()
            try:
                _oi = self._get_combo_sel(self.cb_outline)
                cfg['textOutline'] = ('auto', 'on', 'off')[_oi] if 0 <= _oi <= 2 else 'auto'
            except Exception:  # noqa: BLE001
                cfg['textOutline'] = 'auto'
            cfg['customBg'] = (self._get_text(self.btn_bg_color) or '#1c1f28').strip()
            cfg['customText'] = (self._get_text(self.btn_text_color) or '#e6e8ef').strip()
            # 显示相关的开关也一并进预览（勾一下立刻生效）
            for ctrl, key in ((getattr(self, 'cb_table_head', None), 'showTableHead'),
                              (getattr(self, 'cb_status', None), 'showStatus'),
                              (getattr(self, 'cb_header', None), 'showHeader'),
                              (getattr(self, 'cb_autosize', None), 'autoSize'),
                              (getattr(self, 'cb_border', None), 'showBorder'),
                              (getattr(self, 'cb_gridlines', None), 'showGridLines')):
                if ctrl:
                    cfg[key] = self._get_check(ctrl)
            # 预览时保留「显示字段」页当前的勾选，别把刚套用的方案冲掉
            try:
                sel = self._get_selected_columns()
                if sel:
                    cfg['columns'] = sel
            except Exception:  # noqa: BLE001
                pass
            try:
                cfg['nameChars'] = max(0, min(20, int(self._get_text(self.ed_name_chars) or 0)))
            except (TypeError, ValueError):
                pass
            for combo, key in ((self.cb_up, 'upColor'), (self.cb_down, 'downColor')):
                v = self._combo_color(combo)
                if v:
                    cfg[key] = v
            # 以下几项也要实时：置顶 / 窗口标题 / 数据源 / 刷新间隔 / 宽度
            try:
                cfg['alwaysOnTop'] = self._get_check(self.cb_topmost)
            except Exception:  # noqa: BLE001
                pass
            cfg['title'] = self._get_text(self.ed_title)
            try:
                cfg['refreshInterval'] = max(
                    1, int(self._get_text(self.ed_interval) or 5)) * 1000
            except (TypeError, ValueError):
                pass
            src = self._source_now()
            changed_source = (src != self.app.cfg.get('source'))
            if changed_source:
                cfg['source'] = src
            w.cfg = cfg
            w.release_fonts()
            # 标题 / 置顶要立刻作用到窗口上
            self.app._apply_window_flags()
            # 透明度滑块：状态栏同时显示两个值，方便确认两条通道独立
            if show_alpha:
                w.status_text = '背景 %d%% ｜ 文字 %d%%' % (cfg['bgAlpha'], cfg['textAlpha'])
            # 显示字段变了 → 窗口大小要跟着变
            self.app._apply_auto_size()
            w.paint_now()
            # 数据源变了 → 立刻重新抓一次
            if changed_source:
                self.app.refresh()
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 涨跌颜色（支持任意自定义）----------------
    CUSTOM_COLOR_ITEM = '自定义…'
    CUSTOM_COLOR_PREFIX = '自定义'      # 判断「是不是自定义项」用这个，别用带省略号的

    def _fill_color_combo(self, combo, items, current=''):
        """填充涨跌颜色下拉框，末尾加一项「自定义…」"""
        self._fill_combo(combo, list(items) + [self.CUSTOM_COLOR_ITEM])
        want = (current or '').lstrip('#').lower()
        if not want:
            return                      # 没有当前值，保持「自定义…」原样
        for i, it in enumerate(items):
            if it.split('#')[-1].strip().lower() == want:
                self._set_combo_sel(combo, i)
                return
        # 自定义值：选中「自定义…」并把该项文本改成实际颜色
        idx = len(items)
        self._set_combo_sel(combo, idx)
        self._set_combo_item_text(combo, idx, '自定义 #%s' % want)

    def _set_combo_item_text(self, combo, idx, text):
        """改写下拉框某一项的显示文字。

        不能用 CB_MODIFYSTRING：实测它会**把最后一项吃掉**（项数 7 → 6，
        最后那项直接消失）。CB_DELETESTRING / CB_INSERTSTRING 同样失败。
        所以改成「读出全部项 → 改掉目标项 → 整个重填」，
        RESETCONTENT + CB_ADDSTRING 是验证过可靠的。
        """
        items = self._combo_items(combo)
        if not (0 <= idx < len(items)):
            return
        items[idx] = text
        cur = self._get_combo_sel(combo)
        self._fill_combo(combo, items)
        self._set_combo_sel(combo, cur if cur >= 0 else idx)

    def _select_color_combo(self, combo, color):
        """按颜色值选中下拉框对应项；不在预设里就落到「自定义…」并显示实际颜色"""
        want = (color or '').lstrip('#').lower()
        items = self._combo_items(combo)
        custom_idx = len(items) - 1
        for i, it in enumerate(items):
            val = it.split('#')[-1].strip().lower()
            if it.startswith(self.CUSTOM_COLOR_PREFIX):
                # 已经是自定义项：颜色对得上就选中，并把显示文字刷新成当前值
                if val == want:
                    self._set_combo_item_text(combo, i, '自定义 #%s' % want)
                    self._set_combo_sel(combo, i)
                    return
                continue
            if val == want:
                self._set_combo_sel(combo, i)
                # 命中预设 → 把「自定义…」那一项的显示文字复位
                self._set_combo_item_text(combo, custom_idx, self.CUSTOM_COLOR_ITEM)
                return
        # 自定义值
        self._set_combo_item_text(combo, custom_idx, '自定义 #%s' % (want or '000000'))
        self._set_combo_sel(combo, custom_idx)

    def _combo_color(self, combo):
        """取下拉框当前对应的颜色（返回不带 # 的 hex）

        预设项形如「红 #f6465d」，自定义项形如「自定义 #a1b2c3」，
        两者取色方式相同：取最后一个 # 后面的部分。
        """
        items = self._combo_items(combo)
        i = self._get_combo_sel(combo)
        if not (0 <= i < len(items)):
            return None
        return items[i].split('#')[-1].strip()

    def _pick_custom_color(self, combo, key):
        """选中「自定义…」→ 弹系统调色板，取任意颜色"""
        cur = self._combo_color(combo) or 'f6465d'
        ok, hexv = w32.choose_color(self.hwnd, '#' + cur.lstrip('#'))
        if not ok:
            return
        hexv = hexv.lstrip('#').lower()
        # 把「自定义…」那一项的文本改成实际颜色
        idx = len(self._combo_items(combo)) - 1
        self._set_combo_item_text(combo, idx, '自定义 #%s' % hexv)
        self._set_combo_sel(combo, idx)
        self._preview()

    def _stop_preview(self):
        """关闭设置窗但没保存时，把悬浮窗恢复成已保存的样子"""
        try:
            w = self.app.widget
            w.cfg = self.app.cfg
            w.release_fonts()
            w.paint_now()
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 快捷键录制 ----------------
    def _start_capture(self, idx):
        if not (0 <= idx < len(self.hk_rows)):
            return
        self._capture = idx
        self._set_text(self.hk_rows[idx][2], '请按下组合键…')
        self._set_label(self.lbl_hk_msg, '现在按下新的快捷键（Esc 取消，必须包含 Ctrl/Alt/Shift/Win）')
        try:
            user32.SetFocus(self.hwnd)   # 键盘消息要落到设置窗本身
        except Exception:  # noqa: BLE001
            pass

    def _end_capture(self, idx):
        self._capture = None
        key = self.hk_rows[idx][0]
        cur = (self.app.cfg.get('hotkeys') or {}).get(key, '')
        self._set_text(self.hk_rows[idx][2], cur or '（未设置）')
        self._set_label(self.lbl_hk_msg, '已取消')

    def _capture_key(self, vk):
        idx = self._capture
        if idx is None or not (0 <= idx < len(self.hk_rows)):
            self._capture = None
            return
        if vk == w32.VK_ESCAPE:
            self._end_capture(idx)
            return
        name = _vk_name(vk)
        if not name:
            return                      # 只是按下了修饰键，继续等
        mods = []
        if user32.GetKeyState(w32.VK_CONTROL) & 0x8000:
            mods.append('Ctrl')
        if user32.GetKeyState(w32.VK_MENU) & 0x8000:
            mods.append('Alt')
        if user32.GetKeyState(w32.VK_SHIFT) & 0x8000:
            mods.append('Shift')
        if (user32.GetKeyState(w32.VK_LWIN) | user32.GetKeyState(w32.VK_RWIN)) & 0x8000:
            mods.append('Win')
        if not mods:
            self._set_label(self.lbl_hk_msg,
                            '至少需要一个修饰键（Ctrl / Alt / Shift / Win），请重新按一次')
            return
        combo = '+'.join(mods + [name])
        key, chk, btn = self.hk_rows[idx]
        self._set_text(btn, combo)
        self._set_check(chk, True)
        self._capture = None
        self._set_label(self.lbl_hk_msg, f'{key} 已设为 {combo}，保存后生效')

    # ---------------- 保存 ----------------
    def _collect(self):
        cfg = storage.deep_merge(storage.DEFAULT_CONFIG, self.app.cfg)
        cfg['source'] = self._source_now()
        # 自定义数据源配置（选「自定义接口…」时才用）
        cfg['customSource'] = self._custom_spec_now()
        try:
            cfg['refreshInterval'] = max(1, int(self._get_text(self.ed_interval) or 5)) * 1000
        except ValueError:
            pass
        try:
            cfg['width'] = max(220, min(900, int(self._get_text(self.ed_width) or 320)))
        except ValueError:
            pass
        cfg['title'] = self._get_text(self.ed_title)
        cfg['alwaysOnTop'] = self._get_check(self.cb_topmost)
        cfg['showHeader'] = self._get_check(self.cb_header)
        cfg['showTableHead'] = self._get_check(self.cb_table_head)
        cfg['showStatus'] = self._get_check(self.cb_status)
        cfg['autoSize'] = self._get_check(self.cb_autosize)
        cfg['showBorder'] = self._get_check(self.cb_border)
        cfg['showGridLines'] = self._get_check(self.cb_gridlines)

        # 行情页平台
        pid = self._get_combo_sel(self.cb_quote_platform)
        keys = list(quotes.QUOTE_PLATFORMS.keys())
        cfg['quotePlatform'] = keys[pid] if 0 <= pid < len(keys) else 'xueqiu'
        cfg['quoteUrlTemplate'] = (self._get_text(self.ed_quote_url) or '').strip()

        # 字段：名称 / 代码统一在这里（显示字段页）管理
        sel = self._get_selected_columns()
        cfg['columns'] = sel
        # 完整顺序（含未勾选的字段）—— 用户拖动排序的结果要能存下来
        if self._field_order:
            cfg['fieldOrder'] = list(self._field_order)
        # showName / showCode 由「显示字段」反向同步，保证配置自洽
        # （旧版本这两个开关在基础设置里，现在已移除）
        cfg['showName'] = 'name' in sel
        cfg['showCode'] = 'code' in sel
        # 名称最多显示几个字符（0 = 全部）
        try:
            cfg['nameChars'] = max(0, min(20, int(self._get_text(self.ed_name_chars) or 0)))
        except ValueError:
            cfg['nameChars'] = 0

        # 样式
        if self._get_check(self.rb_light):
            cfg['theme'] = 'light'
        elif self._get_check(self.rb_custom):
            cfg['theme'] = 'custom'
        else:
            cfg['theme'] = 'dark'
        cfg['bgAlpha'] = max(20, min(100, self._get_trackbar(self.sb_bg)))
        cfg['textAlpha'] = max(20, min(100, self._get_trackbar(self.sb_text)))
        cfg['customBg'] = (self._get_text(self.btn_bg_color) or '#1c1f28').strip()
        cfg['customText'] = (self._get_text(self.btn_text_color) or '#e6e8ef').strip()
        cfg['fontSize'] = self._font_size_now()
        try:
            _oi = self._get_combo_sel(self.cb_outline)
            cfg['textOutline'] = ('auto', 'on', 'off')[_oi] if 0 <= _oi <= 2 else 'auto'
        except Exception:  # noqa: BLE001
            cfg['textOutline'] = 'auto'
        # 涨跌颜色：预设项或「自定义 #xxxxxx」都要能正确取到值
        up = self._combo_color(self.cb_up)
        down = self._combo_color(self.cb_down)
        if up:
            cfg['upColor'] = up
        if down:
            cfg['downColor'] = down

        # WebDAV + 自动同步
        cfg['webdav'] = {
            'url': self._get_text(self.ed_dav_url).strip(),
            'username': self._get_text(self.ed_dav_user).strip(),
            'password': self._get_text(self.ed_dav_pass),
            'dir': self._get_text(self.ed_dav_dir).strip() or '/dingpan',
        }
        cfg['autoDavSync'] = self._get_check(self.cb_auto_dav)
        cfg['autoLocalBackup'] = self._get_check(self.cb_auto_local)

        # 快捷键
        hks = dict(cfg.get('hotkeys') or {})
        enabled = dict(cfg.get('hotkeyEnabled') or {})
        for key, chk, btn in self.hk_rows:
            text = (self._get_text(btn) or '').strip()
            hks[key] = '' if text.startswith('（') else text
            enabled[key] = self._get_check(chk)
        cfg['hotkeys'] = hks
        cfg['hotkeyEnabled'] = enabled
        return cfg

    def _lb_text_len(self, lb, idx):
        """取列表框某项的文本长度（LB_GETTEXTLEN）"""
        return user32.SendMessageW(lb, 0x018A, idx, 0)

    def _lb_text(self, lb, idx, n=None):
        """安全读取列表框某项文本：必须先分配缓冲区，绝不能用 NULL 地址调 LB_GETTEXT"""
        if n is None:
            n = self._lb_text_len(lb, idx)
        if n is None or n < 0:
            return ''
        buf = ctypes.create_unicode_buffer(int(n) + 2)
        user32.SendMessageW(lb, 0x0189, idx, ctypes.addressof(buf))  # LB_GETTEXT
        return buf.value

    def _get_selected_columns(self):
        """从「显示字段」列表读取**已勾选**的字段（按列表当前顺序）。

        注意：LB_GETTEXT 的第 4 个参数是「接收缓冲区的地址」，
        以前误传 0（NULL），列表框会把文本写进 0 号地址 —— 直接访问违例崩溃。
        正确做法：先用 LB_GETTEXTLEN 取长度，再按长度分配缓冲区。
        """
        h = getattr(self, 'lb_fields', None)
        if not h:
            return list(self.app.cfg.get('columns') or [])
        count = user32.SendMessageW(h, 0x018B, 0, 0)  # LB_GETCOUNT
        out = []
        for i in range(count):
            label = self._lb_text(h, i)
            if not label.startswith(FIELD_MARK_ON):
                continue
            # 列表下标 i 对应 _field_order[i]（拖动时两者同步维护）
            if i < len(self._field_order):
                key = self._field_order[i]
                if key and key not in out:
                    out.append(key)
        # 一个字段都没选时回落到默认，否则悬浮窗会空掉
        return out or list(storage.DEFAULT_CONFIG.get('columns') or ['name'])

    # ---------------- 显示字段：勾选 + 拖动排序 ----------------
    def _init_field_order(self):
        """字段的**完整**顺序（含未勾选的）。

        优先用 cfg['fieldOrder']（用户拖出来的顺序，未勾选的字段也保留原位）；
        没有就用「已勾选的（按配置顺序）+ 其余（按默认顺序）」推一份。
        """
        saved = [c for c in (self.app.cfg.get('fieldOrder') or []) if c in COLUMN_MAP]
        cols = [c for c in (self.app.cfg.get('columns') or []) if c in COLUMN_MAP]
        rest = [d[0] for d in COLUMN_DEFS if d[0] not in cols and d[0] not in saved]
        order = saved + cols + rest
        # 去重并补齐（配置里可能有已删除的字段）
        out = []
        for k in order:
            if k not in out:
                out.append(k)
        for d in COLUMN_DEFS:
            if d[0] not in out:
                out.append(d[0])
        return out

    def _field_checked(self):
        """当前勾选了哪些字段（**从列表项前缀读**，前缀是唯一事实来源）"""
        h = getattr(self, 'lb_fields', None)
        if not h:
            return set(self.app.cfg.get('columns') or [])
        count = user32.SendMessageW(h, 0x018B, 0, 0)
        out = set()
        for i in range(count):
            if self._lb_text(h, i).startswith(FIELD_MARK_ON):
                if i < len(self._field_order):
                    out.add(self._field_order[i])
        return out

    def _sync_field_columns(self):
        """把当前勾选状态与顺序写回 app.cfg（内存，不落盘）。

        · columns  = 勾选了的字段（按列表顺序）→ 悬浮窗用它决定显示哪些列
        · fieldOrder = **完整**顺序（含未勾选的）→ 重新填充列表时不丢用户的拖动顺序
        """
        checked = self._field_checked()
        self.app.cfg['columns'] = [k for k in self._field_order if k in checked]
        self.app.cfg['fieldOrder'] = list(self._field_order)

    def _fill_field_list(self, keep_sel=None):
        """把字段列表重新填一遍（顺序 = _field_order，前缀 = 勾选状态）

        ⚠️ 这里**不**重算 _field_order —— 拖动排序刚改完顺序就调本方法，
        若在这里从配置重算，用户刚拖出来的顺序会被立刻冲掉。
        需要重算时（打开设置窗、恢复默认、应用方案）由调用方显式调
        `_init_field_order()`。
        """
        checked = set(self.app.cfg.get('columns') or [])
        labels = []
        for k in self._field_order:
            mark = FIELD_MARK_ON if k in checked else FIELD_MARK_OFF
            labels.append('%s %s' % (mark, COLUMN_MAP.get(k, (k, k))[1]))
        self._fill_list(self.lb_fields, labels)
        if keep_sel is not None and 0 <= keep_sel < len(self._field_order):
            self._cl_set_sel('fields', keep_sel)
        # 自绘列表：填完后同步重绘一次，保证内容是最新的
        user32.InvalidateRect(self.lb_fields, None, True)
        user32.UpdateWindow(self.lb_fields)

    def _toggle_field_enabled(self, idx):
        """点 [√] → 切换某字段的「显示 / 不显示」"""
        if not (0 <= idx < len(self._field_order)):
            return
        key = self._field_order[idx]
        checked = self._field_checked()
        if key in checked:
            checked.discard(key)
        else:
            checked.add(key)
        # 整表重填（LB_DELETESTRING/INSERTSTRING 常量在不同 Windows 上语义不一致，
        # 实测会丢项；重填最稳），填完把选中位置还原
        self.app.cfg['columns'] = [k for k in self._field_order if k in checked]
        self._fill_field_list(keep_sel=idx)
        self._sync_field_columns()
        name = COLUMN_MAP.get(key, (key, key))[1]
        self._set_label(self.lbl_col_msg,
                        '「%s」%s' % (name, '已隐藏' if key in checked else '已显示'))
        self._preview()

    def _move_field_row(self, frm, to):
        """把第 frm 个字段拖到第 to 个位置"""
        if not (0 <= frm < len(self._field_order)) or not (0 <= to < len(self._field_order)):
            return
        if frm == to:
            return
        item = self._field_order.pop(frm)
        self._field_order.insert(to, item)
        # 列表内容要跟着换位（勾选前缀也要跟着走）
        self._fill_field_list(keep_sel=to)
        self._sync_field_columns()
        self._preview()

    def _col_reset(self):
        """恢复默认：字段顺序与勾选都回到出厂状态"""
        self.app.cfg['columns'] = list(storage.DEFAULT_CONFIG.get('columns') or [])
        self.app.cfg['fieldOrder'] = []
        self._field_order = self._init_field_order()
        self._fill_field_list()
        self._set_label(self.lbl_col_msg, '已恢复默认显示字段')
        self._preview()

    def _col_set_all(self, on):
        """全部显示 / 全部隐藏"""
        keys = list(self._field_order)
        if on:
            self.app.cfg['columns'] = keys
        else:
            # 至少留一个，否则悬浮窗空掉
            self.app.cfg['columns'] = keys[:1]
        self._fill_field_list()
        self._sync_field_columns()
        self._set_label(self.lbl_col_msg, '已%s全部字段' % ('显示' if on else '隐藏'))
        self._preview()

    def _save(self):
        cfg = self._collect()
        self.app.cfg = cfg
        self.app.save_cfg(cfg)            # 会按勾选触发自动备份 / WebDAV 同步
        self.app.widget.cfg = cfg
        self.app.widget.release_fonts()
        self.app._register_hotkeys()
        # 显示字段改了 → 窗口大小要跟着变（列宽变了）
        self.app._apply_auto_size()
        self.app.widget.paint_now()
        tips = ['设置已保存']
        if cfg.get('autoLocalBackup'):
            tips.append('已写入本地自动备份')
        if cfg.get('autoDavSync') and (cfg.get('webdav') or {}).get('url'):
            tips.append('WebDAV 将在 4 秒后自动同步')
        failed = getattr(self.app, 'failed_hotkeys', [])
        if failed:
            tips.append('以下快捷键被系统占用未能注册：' + '、'.join(failed))
        dialogs.message_box('盯盘', '\n'.join(tips), 'info')

    # ---------------- 消息 ----------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            return self._wndproc_inner(hwnd, msg, wparam, lparam)
        except Exception as e:  # noqa: BLE001
            # windowed 模式下 ctypes 会静默吞掉回调异常，必须落盘才能排查
            try:
                import datetime
                import traceback
                from .storage import app_dir
                with open(os.path.join(app_dir(), 'crash.log'), 'a', encoding='utf-8') as f:
                    f.write('\n===== settings.wndproc msg=0x%04X w=0x%X | %s =====\n'
                            % (msg, wparam & 0xFFFFFFFF, datetime.datetime.now()))
                    traceback.print_exc(file=f)
            except Exception:
                pass
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _wndproc_inner(self, hwnd, msg, wparam, lparam):
        if msg == WM_DAV_DONE:
            self._on_dav_done()
            return 0
        if msg == WM_STOCK_VERIFY_DONE:
            self._on_stock_verified()
            return 0
        if msg == WM_CUSTOM_TEST_DONE:
            self._on_custom_test_done()
            return 0
        if msg == w32.WM_COMMAND:
            self._on_command(int(wparam) & 0xFFFF, lparam, (int(wparam) >> 16) & 0xFFFF)
            return 0
        if msg == w32.WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == w32.WM_DESTROY:
            self._stop_preview()
            _SETTINGS_INSTANCES.pop(int(hwnd), None)
            self.hwnd = None
            self.app.settings_hwnd = None
            if getattr(self.app, '_settings_obj', None) is self:
                self.app._settings_obj = None
            return 0
        if msg == w32.WM_SIZE:
            w, h = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
            if w <= 0 or h <= 0 or not self.btn_save:
                return 0
            # 底部按钮按客户区高度重排：底部留 6px 余量，确保「关闭」不会被窗口边缘裁掉
            if self.content:
                user32.SetWindowPos(self.content, None, SIDEBAR_W, 0,
                                    max(80, w - SIDEBAR_W), h, 0x0004)
            user32.SetWindowPos(self._nav_bg, None, 0, 0, SIDEBAR_W, h, 0x0004)
            user32.SetWindowPos(self.btn_save, None, 8, h - 68, SIDEBAR_W - 16, 30, 0x0004)
            user32.SetWindowPos(self.btn_close, None, 8, h - 34, SIDEBAR_W - 16, 28, 0x0004)
            return 0
        if msg == w32.WM_HSCROLL:
            # 滑块：拖动时实时预览到悬浮窗（字号已改成下拉框，不走这里）
            if lparam == self.sb_bg:
                v = self._get_trackbar(self.sb_bg)
                self._set_label(self.lbl_bg, f'{v}%')
                self._preview(show_alpha=True)
            elif lparam == self.sb_text:
                v = self._get_trackbar(self.sb_text)
                self._set_label(self.lbl_text, f'{v}%')
                self._preview(show_alpha=True)
            return 0
        if msg in (w32.WM_KEYDOWN, w32.WM_SYSKEYDOWN):
            if self._capture is not None:
                self._capture_key(int(wparam))
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _on_command(self, cid, lparam, code=0):
        # —— 实时预览：样式相关的任何改动都立刻反映到悬浮窗（不用点保存）——
        # 滑块（trackbar）发的是 WM_HSCROLL，不走 WM_COMMAND，在 wndproc 里处理。
        if code == 0x0300:          # EN_CHANGE：输入框内容变化
            if lparam and int(lparam) == int(getattr(self, 'ed_name_chars', 0) or 0):
                self._preview()
                return
            # 自选代码输入框 → 实时显示自动识别结果
            if lparam and int(lparam) == int(getattr(self, 'ed_stock', 0) or 0):
                self._preview_stock_codes()
                return
            return
        if code == 1:               # CBN_SELCHANGE / LBN_SELCHANGE（通知码都是 1）
            # ⚠️ 只能拦截指定的控件，不能无条件 return ——
            # 分组列表的 LBN_SELCHANGE 通知码也是 1，无条件 return 会把
            # 「切换分组 → 右侧列表跟随」这个功能直接废掉。
            if lparam and int(lparam) in (int(self.cb_up), int(self.cb_down)):
                combo = self.cb_up if int(lparam) == int(self.cb_up) else self.cb_down
                items = self._combo_items(combo)
                i = self._get_combo_sel(combo)
                if 0 <= i < len(items) and items[i].startswith(self.CUSTOM_COLOR_PREFIX):
                    self._pick_custom_color(combo, 'upColor' if combo is self.cb_up else 'downColor')
                    return
                self._preview()
                return
            # 字号下拉框 → 立即换字号预览
            if lparam and int(lparam) == int(getattr(self, 'cb_font', 0) or 0):
                self._preview()
                return
            # 描边下拉框 → 立即预览
            if lparam and int(lparam) == int(getattr(self, 'cb_outline', 0) or 0):
                self._preview()
                return
            # 数据源下拉框 → 切换自定义接口区的启用状态
            if lparam and int(lparam) == int(getattr(self, 'cb_source', 0) or 0):
                self._sync_custom_source_enabled()
                return
            # 行情页平台下拉框 → 选「自定义…」时显示地址输入框
            if lparam and int(lparam) == int(getattr(self, 'cb_quote_platform', 0) or 0):
                self._sync_quote_url_enabled()
                return
        # 左侧分组列表选中变化（LBN_SELCHANGE=1）：右侧股票列表跟着切换
        if lparam and lparam == self.lb_groups and code == 1:
            groups = self.app.cfg.get('groups') or []
            sel = self._get_list_sel(self.lb_groups)
            if 0 <= sel < len(groups):
                gid = groups[sel].get('id')
                if gid and gid != self.app.cfg.get('activeGroupId'):
                    self.app.set_group(sel)
            self._fill_stock_list()
            return
        # 导航（ID 段 8000+pid）
        if 8000 <= cid < 8000 + len(PAGES):
            self._show_page(cid - 8000)
            return
        # 主题单选
        if cid in (9401, 9402, 9403):
            self._preview()
            return
        # 显示相关的复选框：勾一下就立刻反映到悬浮窗
        if code == 0:               # BN_CLICKED
            for ctrl in (getattr(self, 'cb_table_head', None),
                         getattr(self, 'cb_status', None),
                         getattr(self, 'cb_header', None),
                         getattr(self, 'cb_autosize', None),
                         getattr(self, 'cb_border', None),
                         getattr(self, 'cb_gridlines', None)):
                if ctrl and lparam and int(lparam) == int(ctrl):
                    self._preview()
                    return
        # 自定义数据源：测试接口
        if cid == 9110:
            self._test_custom_source()
            return
        # 「背景 100%」快捷按钮
        if cid == 9431:
            self._set_trackbar(self.sb_bg, 100, 20, 100)
            self._set_label(self.lbl_bg, '100%')
            self._preview(show_alpha=True)
            return
        # 显示方案：应用 / 保存 / 删除
        if cid == 9421:
            self._apply_preset()
            return
        if cid == 9422:
            self._save_preset()
            return
        if cid == 9423:
            self._delete_preset()
            return
        # 自定义颜色
        if cid in (9411, 9412):
            btn = self.btn_bg_color if cid == 9411 else self.btn_text_color
            cur = (self._get_text(btn) or '#1c1f28').strip()
            ok, hexv = w32.choose_color(self.hwnd, cur)
            if ok and hexv:
                self._set_text(btn, hexv)
                self._select_theme('custom')
                self._preview()
            return
        # 快捷键录制按钮
        if 9810 <= cid < 9810 + 8:
            self._start_capture(cid - 9810)
            return
        if cid == 9001:
            self._save()
        elif cid == 9002:
            user32.DestroyWindow(self.hwnd)
        elif cid == 9201:
            self._add_group()
        elif cid == 9202:
            self._del_group()
        elif cid == 9203:
            self._add_stock()
        elif cid == 9204:
            self._del_stock()
        elif cid == 9305:
            self._col_reset()
        elif cid == 9306:
            self._col_set_all(True)
        elif cid == 9307:
            self._col_set_all(False)
        elif cid == 9501:
            self._detect_legacy()
        elif cid == 9502:
            self._import_legacy()
        elif cid == 9503:
            self._export()
        elif cid == 9504:
            self._import()
        elif cid == 9505:
            self._reset()
        elif cid == 9601:
            self._dav_test()
        elif cid == 9602:
            self._dav_upload()
        elif cid == 9603:
            self._dav_download()
        elif cid == 9701:
            defaults = storage.DEFAULT_CONFIG.get('hotkeys') or {}
            for key, chk, btn in self.hk_rows:
                self._set_text(btn, defaults.get(key, '') or '（未设置）')
                self._set_check(chk, True)
            self._set_label(self.lbl_hk_msg, '已恢复默认快捷键（保存后生效）')
        elif cid == 9702:
            for _key, chk, _btn in self.hk_rows:
                self._set_check(chk, False)
            self._set_label(self.lbl_hk_msg, '已全部取消勾选（保存后这些快捷键将不再注册）')

    # ---------------- 各项操作 ----------------
    def _add_group(self):
        name = dialogs.prompt_text('新建分组', '分组名称', f'分组 {len(self.app.cfg.get("groups", [])) + 1}')
        if not name:
            return
        gid = f'g_{int(time.time() * 1000) % 1000000}'
        self.app.cfg.setdefault('groups', []).append({'id': gid, 'name': name, 'stocks': []})
        self._refresh_stock_list()
        # 新建后自动选中这个新分组，右侧列表随之切换
        self._set_list_sel(self.lb_groups, len(self.app.cfg.get('groups', [])) - 1)
        self._fill_stock_list()

    def _del_group(self):
        groups = self.app.cfg.get('groups') or []
        if len(groups) <= 1:
            dialogs.message_box('提示', '至少保留一个分组', 'warning')
            return
        sel = self._get_list_sel(self.lb_groups)
        if sel < 0 or sel >= len(groups):
            return
        g = groups[sel]
        if not dialogs.confirm('删除分组', f'确定删除「{g.get("name", "")}」及其 {len(g.get("stocks", []))} 只自选股？'):
            return
        groups.pop(sel)
        self._refresh_stock_list()

    def _preview_stock_codes(self):
        """输入框内容变化 → 实时显示「自动识别后的代码」。

        用户直接敲 600519 / 000001 / 00700 时，这里能立刻看到
        会补成 sh600519 / sz000001 / hk00700，知道系统是怎么认的。
        """
        if getattr(self, '_stock_busy', False):
            return
        text = self._get_text(self.ed_stock).strip()
        if not text:
            self._set_label(self.lbl_stock_hint,
                            '支持一次多个：600519 000001 00700（纯数字会自动识别交易所）')
            return
        codes = quotes.parse_codes(text)
        if not codes:
            self._set_label(self.lbl_stock_hint, '✗ 没识别到代码，例如 600519 或 000001 00700')
            return
        self._set_label(self.lbl_stock_hint, '已识别 %d 个：%s' % (len(codes), '  '.join(codes)))

    def _add_stock(self):
        text = self._get_text(self.ed_stock).strip()
        if not text or self._stock_busy:
            return
        codes = quotes.parse_codes(text)
        if not codes:
            self._set_label(self.lbl_stock_hint, '没识别到代码，例如 600519 或 000001 00700')
            return
        # 代码验证走后台线程，避免网络慢时卡住整个 UI
        self._stock_busy = True
        self._stock_code = codes
        user32.EnableWindow(self.btn_stock_add, False)
        self._set_label(self.lbl_stock_hint, '正在验证 %d 个代码…' % len(codes))
        threading.Thread(target=self._stock_verify_worker, args=(codes,), daemon=True).start()

    def _stock_verify_worker(self, codes):
        """一次请求校验全部代码，返回 (ok, [(code,name)], [未找到], err)"""
        try:
            res = quotes.fetch_quotes(codes, self.app.cfg.get('source', 'tencent'))
            if not res.get('ok'):
                out = (False, [], [], res.get('error') or '网络异常')
            else:
                data = res.get('data') or {}
                got, miss = [], []
                for c in codes:
                    q = data.get(c) or {}
                    if q.get('name'):
                        got.append((c, q['name']))
                    else:
                        miss.append(c)
                out = (True, got, miss, '')
        except Exception as e:  # noqa: BLE001
            out = (False, [], [], f'验证失败：{e}')
        self._stock_result = out
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.PostMessageW(self.hwnd, WM_STOCK_VERIFY_DONE, 0, 0)

    def _on_stock_verified(self):
        if not self._stock_busy:
            return
        self._stock_busy = False
        res, self._stock_result = self._stock_result, None
        self._stock_code = None
        alive = self.hwnd and user32.IsWindow(self.hwnd)
        if alive:
            user32.EnableWindow(self.btn_stock_add, True)
            self._set_label(self.lbl_stock_hint, '支持一次多个：600519 000001 00700')
        if not alive:
            return
        if not isinstance(res, tuple) or len(res) != 4:
            dialogs.message_box('添加失败', '验证失败', 'error')
            return
        ok, got, miss, err = res
        if not ok:
            dialogs.message_box('添加失败', err or '未找到该证券', 'error')
            return
        groups = self.app.cfg.get('groups') or []
        gi = self.app.group_index()
        stocks = groups[gi].setdefault('stocks', [])
        have = {s.get('code') for s in stocks}
        added = 0
        for c, name in got:
            if c in have:
                continue
            stocks.append({'code': c, 'name': name})
            have.add(c)
            added += 1
        self._set_text(self.ed_stock, '')
        self._refresh_stock_list()
        # 新增的自选要立刻出现在悬浮窗里
        if added:
            self._sync_widget_stocks()
        if miss:
            dialogs.message_box('添加自选股',
                                '已添加 %d 只\n未找到：%s' % (added, '、'.join(miss)),
                                'warning' if added else 'error')
        elif added:
            self._set_label(self.lbl_stock_hint, '已添加 %d 只' % added)
        else:
            self._set_label(self.lbl_stock_hint, '这些代码都已经在列表里了')

    def _del_stock(self):
        groups = self.app.cfg.get('groups') or []
        gi = self.app.group_index()
        stocks = groups[gi].get('stocks', [])
        sel = self._cl_sel('stocks')
        if sel < 0 or sel >= len(stocks):
            return
        stocks.pop(sel)
        self._cl_set_sel('stocks', -1)
        self._refresh_stock_list()
        self._sync_widget_stocks()

    def _get_list_count(self, lb):
        return user32.SendMessageW(lb, 0x018B, 0, 0)  # LB_GETCOUNT

    def _detect_legacy(self):
        p = legacy.find_legacy_config()
        if p:
            self._set_label(self.lbl_legacy, f'✓ 检测到：{p}')
        else:
            self._set_label(self.lbl_legacy, '未检测到原版配置文件（SW_config.json）')

    def _import_legacy(self):
        ok, cfg, count, path, err = legacy.import_legacy()
        if not ok:
            self._set_label(self.lbl_legacy, f'✗ {err}')
            return
        self.app.cfg = cfg
        self.app.save_cfg(cfg)
        self.app.widget.cfg = cfg
        self.app.widget.release_fonts()
        self.app._register_hotkeys()
        self.app.refresh()
        self.app.widget.paint_now()
        self._load_ui()
        self._set_label(self.lbl_legacy, f'✓ 已导入 {count} 只自选股')
        dialogs.message_box('导入成功', f'已从原版导入 {count} 只自选股及样式设置', 'info')

    def _export(self):
        path = dialogs.save_file_dialog('导出备份文件', f'dingpan-backup-{storage.stamp()}.json')
        if not path:
            return
        ok, _, err = storage.export_backup(self._collect(), path)
        dialogs.message_box('盯盘', '备份已导出：\n' + path if ok else '导出失败：' + err,
                            'info' if ok else 'error')

    def _import(self):
        path = dialogs.open_file_dialog('选择备份文件')
        if not path:
            return
        ok, cfg, err = storage.import_backup(path)
        if not ok:
            dialogs.message_box('导入失败', err, 'error')
            return
        self.app.cfg = cfg
        self.app.save_cfg(cfg)
        self.app.widget.cfg = cfg
        self.app.widget.release_fonts()
        self.app._register_hotkeys()
        self.app.refresh()
        self.app.widget.paint_now()
        self._load_ui()
        dialogs.message_box('导入成功', '已从备份恢复设置', 'info')

    def _reset(self):
        if not dialogs.confirm('恢复默认设置', '确定恢复出厂默认设置？当前自选股将被清空。'):
            return
        cfg = storage.deep_merge(storage.DEFAULT_CONFIG, {})
        self.app.cfg = cfg
        self.app.save_cfg(cfg)
        self.app.widget.cfg = cfg
        self.app.widget.release_fonts()
        self.app._register_hotkeys()
        self.app.refresh()
        self.app.widget.paint_now()
        self._load_ui()
        dialogs.message_box('盯盘', '已恢复默认设置', 'info')

    def _dav_test(self):
        self._dav_run('test')

    def _dav_upload(self):
        self._dav_run('upload')

    def _dav_download(self):
        self._dav_run('download')

    def _dav_run(self, kind):
        """WebDAV 操作在后台线程执行，完成后 PostMessage 回 UI 线程"""
        if self._dav_busy:
            return
        cfg = self._collect()
        self._dav_busy = True
        self._dav_cfg = cfg
        for b in (self.btn_dav_test, self.btn_dav_up, self.btn_dav_down):
            user32.EnableWindow(b, False)
        self._set_label(self.lbl_dav_msg, {'test': '正在测试连接…',
                                           'upload': '正在上传备份…',
                                           'download': '正在获取备份列表…'}[kind])
        threading.Thread(target=self._dav_worker, args=(kind, cfg), daemon=True).start()

    def _dav_worker(self, kind, cfg):
        try:
            if kind == 'test':
                ok, msg = storage.webdav_test(cfg)
                res = (ok, msg)
            elif kind == 'upload':
                ok, fname, err = storage.webdav_upload(cfg)
                res = (ok, fname, err)
            else:
                ok, payload, err = storage.webdav_download(cfg)
                res = (ok, payload, err)
        except Exception as e:  # noqa: BLE001
            res = (False, None, f'操作失败：{e}')
        self._dav_result = (kind, res)
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.PostMessageW(self.hwnd, WM_DAV_DONE, 0, 0)

    def _on_dav_done(self):
        if not self._dav_busy:
            return
        self._dav_busy = False
        kind_res, self._dav_result = self._dav_result, None
        cfg, self._dav_cfg = self._dav_cfg, None
        alive = self.hwnd and user32.IsWindow(self.hwnd)
        if alive:
            for b in (self.btn_dav_test, self.btn_dav_up, self.btn_dav_down):
                user32.EnableWindow(b, True)
        if not alive or not kind_res:
            return
        kind, res = kind_res
        if kind == 'test':
            ok, msg = res
            self._set_label(self.lbl_dav_msg, ('✓ ' if ok else '✗ ') + msg)
        elif kind == 'upload':
            ok, fname, err = res
            self._set_label(self.lbl_dav_msg, (f'✓ 已上传 {fname}' if ok else '✗ ' + err))
            if ok and cfg:
                self.app.save_cfg(cfg)
        else:
            ok, payload, err = res
            if not ok:
                self._set_label(self.lbl_dav_msg, '✗ ' + err)
                return
            newcfg, fname = payload
            self.app.cfg = newcfg
            self.app.save_cfg(newcfg)
            self.app.widget.cfg = newcfg
            self.app.widget.release_fonts()
            self.app._register_hotkeys()
            self.app.refresh()
            self.app.widget.paint_now()
            self._load_ui()
            self._set_label(self.lbl_dav_msg, f'✓ 已从 {fname} 恢复')
