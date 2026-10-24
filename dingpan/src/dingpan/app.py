"""
盯盘 — 桌面悬浮行情挂件（单文件原生程序）
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from . import win32 as w32
from . import storage, quotes, legacy, icon
from .win32 import gdi32, user32, shell32, kernel32
from .widget import Widget, Theme, COLUMN_DEFS, COLUMN_MAP

try:
    w32.init_common_controls()
except Exception:
    pass

APP_NAME = '盯盘'
WM_TRAY = w32.WM_APP_TRAY
WM_APP_RELOAD = w32.WM_USER + 30
WM_APP_SETTINGS_SAVED = w32.WM_USER + 31
WM_APP_FETCH_DONE = w32.WM_USER + 32  # 后台行情线程 → UI 线程：套用结果并重绘
WM_APP_SYNC_DONE = w32.WM_USER + 33   # 后台自动同步线程 → UI 线程：刷新提示


def _version_text():
    """菜单里显示的版本号（便于确认运行的是哪个构建）"""
    try:
        from . import __version__
        ver = __version__
    except Exception:  # noqa: BLE001
        ver = '?'
    try:
        from ._buildinfo import BUILD_TAG
        return '盯盘 v%s（构建 %s）' % (ver, BUILD_TAG)
    except Exception:  # noqa: BLE001
        return '盯盘 v%s' % ver

ID_TRAY = 1
CMD_SHOW = 1001
CMD_HIDE = 1002
CMD_SETTINGS = 1003
CMD_REFRESH = 1004
CMD_NEXT_GROUP = 1005
CMD_PREV_GROUP = 1006
CMD_QUIT = 1007
CMD_TRAY_SOURCE_BASE = 1100

# ---------------- 托盘宿主 + 弹出菜单宿主窗口 ----------------
# 关键点：悬浮窗带 WS_EX_NOACTIVATE，永远无法成为前台窗口。
# 而 TrackPopupMenu 要求 owner 是前台窗口，否则菜单会「一弹出就被系统关掉」
# —— 这才是「右键没反应 / 菜单闪一下就没」的真正原因，和消息解析无关。
# 托盘图标必须挂在一个「可激活」的普通窗口上：
#   · 系统在弹出托盘右键菜单前，会把前台权限给图标的 owner 窗口
#   · owner 可激活 → 菜单能正常显示并停留
# 所以这里单独建一个普通弹出窗口，同时充当「托盘宿主」和「所有右键菜单的 owner」。
_TRAY_HOSTS = {}               # hwnd -> App 实例
_TRAY_HOST_READY = False
_TRAY_HOST_CLASS = 'DingPanTrayHost'


def _tray_host_wndproc(hwnd, msg, wparam, lparam):
    """托盘宿主窗口过程：只负责把托盘回调转给 App，其余交给系统默认处理。"""
    if msg == WM_TRAY:
        app = _TRAY_HOSTS.get(int(hwnd))
        if app is not None:
            try:
                app._on_tray_notify(wparam, lparam)
            except Exception as e:  # noqa: BLE001
                log_exception('tray.notify', e)
            return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_TRAY_HOST_PROC = w32.WNDPROC(_tray_host_wndproc)


def _create_tray_host():
    """创建托盘宿主窗口（普通弹出窗口，可激活；0x0 尺寸、不显示）"""
    global _TRAY_HOST_READY
    hinst = kernel32.GetModuleHandleW(None)
    if not _TRAY_HOST_READY:
        cls = w32.WNDCLASS()
        cls.style = 0x0001
        cls.lpfnWndProc = _TRAY_HOST_PROC
        cls.hInstance = hinst
        cls.hCursor = user32.LoadCursorW(None, ctypes.c_wchar_p(32512))
        cls.hbrBackground = user32.GetSysColorBrush(5)
        cls.lpszClassName = _TRAY_HOST_CLASS
        user32.RegisterClassW(ctypes.byref(cls))
        _TRAY_HOST_READY = True
    # WS_EX_TOOLWINDOW：不占任务栏；不用 WS_EX_NOACTIVATE：需要它能被激活
    hwnd = user32.CreateWindowExW(w32.WS_EX_TOOLWINDOW, _TRAY_HOST_CLASS, '',
                                  w32.WS_POPUP, 0, 0, 0, 0,
                                  None, None, hinst, None)
    return hwnd


def _show_popup(menu, sx, sy, owner):
    """弹出菜单的标准做法（微软推荐模式）：
    1) 先把 owner 提到前台，否则菜单一弹出就被系统关掉
    2) TrackPopupMenu 用 TPM_RETURNCMD 直接拿命令号
    3) 结束后给 owner 发一条 WM_NULL，让系统正确把前台还给原来的程序
    """
    user32.SetForegroundWindow(owner)
    cmd = user32.TrackPopupMenu(menu, w32.TPM_RIGHTBUTTON | w32.TPM_RETURNCMD | w32.TPM_NONOTIFY,
                                sx, sy, 0, owner, None)
    user32.PostMessageW(owner, w32.WM_NULL, 0, 0)
    return cmd


def resource_path(rel):
    """兼容 PyInstaller 单文件模式"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _fallbacks(acc):
    """为被占用的组合生成备用方案（保证核心功能始终有键可用）"""
    if not acc:
        return
    parts = [p.strip() for p in acc.replace('-', '+').split('+') if p.strip()]
    if not parts:
        return
    key = [p for p in parts if p.lower() not in ('ctrl', 'alt', 'shift', 'win')]
    if not key:
        return
    k = key[-1]
    seen = set()
    for pre in ([], ['Win']):
        base = pre + (['Ctrl', 'Alt'] if 'Shift' not in pre else ['Ctrl', 'Shift'])
        for combo in (base, pre + ['Ctrl', 'Shift'], pre + ['Ctrl', 'Alt', 'Shift']):
            cand = '+'.join(combo + [k])
            if cand != acc and cand not in seen:
                seen.add(cand)
                yield cand


class App:
    def __init__(self):
        # ⚠️ 必须**先读位置指针**再读配置：
        #    配置文件可能在用户自定义的目录里，指针文件记录了它在哪。
        storage.load_location()
        self.cfg = storage.load_config()
        self.widget = Widget(self)
        self.hwnd = None
        self.tray_host = None
        self.settings_hwnd = None
        self.tray_added = False
        self.hotkey_ids = {}
        self.failed_hotkeys = []
        self.running = True
        self._timer_id = 1
        self._sync_timer_id = 2
        self._fetching = False   # 后台线程拉取中（仅 UI 线程读写）
        self._pending = False    # 拉取期间又收到了刷新请求
        self._fetch_result = None
        self._resize = None      # (起点的窗口宽高, 起点光标屏幕坐标)
        # 拖动窗口（任意位置可拖）：按下时记起点，移动超过 3px 才算拖动，
        # 随后交给系统原生移动（流畅、无重影）
        self._drag_hwnd = None
        self._drag_from = (0, 0)     # 按下时鼠标在客户区的坐标
        self._drag_moved = False
        self._last_drag_ts = 0.0     # 上次拖动结束的时间（避免拖完误触发双击隐藏）
        self._sync_pending = False
        self._sync_busy = False
        self._next_fetch = 0.0     # 休市降频：早于这个时间点的定时器跳过
        self._fail_count = 0       # 连续失败次数 → 指数退避，避免网络挂了还每 5 秒猛刷
        self._cache_sig = None
        self.sync_msg = ''       # 最近一次自动同步结果（设置界面可展示）
        self._restore_cache()

    # ---------------- 启动即显示 ----------------
    def _restore_cache(self):
        """用上次成功抓到的行情先把界面填满，避免启动后几秒空白"""
        try:
            quotes, saved_at = storage.QuoteSnapshot.load()
        except Exception:  # noqa: BLE001
            quotes, saved_at = {}, ''
        if not quotes:
            return
        groups = self.cfg.get('groups') or []
        gi = self.group_index()
        codes = set()
        if 0 <= gi < len(groups):
            codes = {s.get('code') for s in groups[gi].get('stocks') or []}
        hit = {k: v for k, v in quotes.items() if k in codes} if codes else quotes
        if not hit:
            return
        self.widget.quotes = hit
        hhmm = saved_at[11:16] if len(saved_at) >= 16 else ''
        self.widget.status_text = ('缓存 %s' % hhmm) if hhmm else '缓存行情'
        self.widget.status_ok = True
        self.widget.status_warn = True    # 状态点转强调色：这是缓存，不是实时价
        self.widget.last_update = hhmm

    # ---------------- 配置保存 ----------------
    def save_cfg(self, cfg=None, sync=True):
        """保存配置；sync=True 时按用户勾选触发自动备份 / WebDAV 同步（带防抖）"""
        if cfg is not None:
            self.cfg = cfg
        ok = storage.save_config(self.cfg)
        if sync:
            self._schedule_auto_sync()
        return ok

    def _auto_sync_on(self):
        return bool(self.cfg.get('autoLocalBackup')) or bool(
            self.cfg.get('autoDavSync') and (self.cfg.get('webdav') or {}).get('url'))

    def _schedule_auto_sync(self):
        """延迟 4 秒执行：连续拖动/改设置只会触发最后一次，避免频繁写盘与上传"""
        if not self.hwnd or not self._auto_sync_on():
            return
        self._sync_pending = True
        user32.SetTimer(self.hwnd, self._sync_timer_id, 4000, None)

    def _run_auto_sync(self):
        """设置变动后的自动备份 / 自动同步"""
        self._sync_pending = False
        if self.cfg.get('autoLocalBackup'):
            ok, path, err = storage.save_auto_backup(self.cfg)
            self.sync_msg = f'本地自动备份 {time.strftime("%H:%M:%S")}：' + ('成功' if ok else err)
        w = self.cfg.get('webdav') or {}
        if self.cfg.get('autoDavSync') and w.get('url') and not self._sync_busy:
            self._sync_busy = True
            threading.Thread(target=self._auto_sync_worker, args=(self.cfg,), daemon=True).start()

    def _auto_sync_worker(self, cfg):
        try:
            ok, name, err = storage.webdav_upload(cfg, fixed=True)
            self.sync_msg = ('WebDAV 自动同步：已上传 %s' % name) if ok else ('WebDAV 自动同步失败：%s' % err)
        except Exception as e:  # noqa: BLE001
            self.sync_msg = 'WebDAV 自动同步失败：%s' % e
        finally:
            self._sync_busy = False
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_APP_SYNC_DONE, 0, 0)

    def _on_sync_done(self):
        dlg = self.settings_hwnd
        if dlg and user32.IsWindow(dlg) and hasattr(self, 'widget'):
            self.widget.paint_now()
        # 设置窗若打开，刷新其 WebDAV 提示
        win = getattr(self, '_settings_obj', None)
        if win is not None and getattr(win, 'hwnd', None):
            try:
                win.on_sync_msg()
            except Exception:  # noqa: BLE001
                pass

    # ---------------- 分组 ----------------
    def group_index(self):
        groups = self.cfg.get('groups') or []
        for i, g in enumerate(groups):
            if g.get('id') == self.cfg.get('activeGroupId'):
                return i
        return 0

    def set_group(self, i):
        groups = self.cfg.get('groups') or []
        if not groups:
            return
        i %= len(groups)
        self.cfg['activeGroupId'] = groups[i]['id']
        self.save_cfg()
        self.widget.scroll = 0
        self.refresh()
        # 换个分组行数可能不同 → 窗口高度跟着变
        self._apply_auto_size()
        self.widget.paint_now()

    # ---------------- 行情 ----------------
    def refresh(self):
        """触发一次行情刷新（立即返回，网络请求在后台线程执行，绝不阻塞 UI）"""
        if self._fetching:
            self._pending = True
            return
        if self.hwnd:
            self._next_fetch = time.time() + self._refresh_gap()
        groups = self.cfg.get('groups') or []
        gi = self.group_index()
        stocks = groups[gi].get('stocks', []) if 0 <= gi < len(groups) else []
        codes = [s.get('code') for s in stocks if s.get('code')]
        if not codes:
            self.widget.quotes = {}
            self.widget.status_text = '无自选股'
            self.widget.status_ok = True
            self.widget.paint_now()
            return
        self._fetching = True
        self._pending = False
        threading.Thread(target=self._fetch_worker,
                         args=(codes, self.cfg.get('source', 'tencent')),
                         daemon=True).start()

    # ---------------- 显示 / 隐藏 ----------------
    def set_visible(self, visible):
        """显示/隐藏悬浮窗：隐藏时停掉刷新定时器，不再白耗流量和 CPU"""
        if not self.hwnd:
            return
        if visible:
            user32.ShowWindow(self.hwnd, w32.SW_SHOWNOACTIVATE)
            user32.SetTimer(self.hwnd, self._timer_id,
                            max(1500, int(self.cfg.get('refreshInterval', 5000))), None)
            self.refresh()          # 重新出现立刻给一份最新行情
        else:
            user32.ShowWindow(self.hwnd, w32.SW_HIDE)
            user32.KillTimer(self.hwnd, self._timer_id)

    # ---------------- 休市降频 ----------------
    @staticmethod
    def market_open(now=None):
        """A 股交易时段（不含节假日判断，节假日同样按休市降频处理）"""
        import datetime
        n = now or datetime.datetime.now()
        if n.weekday() >= 5:
            return False
        hm = n.hour * 60 + n.minute
        return (9 * 60 + 15 <= hm <= 11 * 60 + 35) or (12 * 60 + 55 <= hm <= 15 * 60 + 5)

    def _refresh_gap(self):
        """刷新间隔下限：休市 5 分钟一次；连续失败按 5/10/20/40/60 秒退避"""
        base = 0.0 if self.market_open() else 300.0
        if self._fail_count:
            back = min(60.0, 5.0 * (2 ** min(self._fail_count, 4)))
            return max(base, back)
        return base

    def _fetch_worker(self, codes, source):
        """后台线程：只做网络请求，结果交给 UI 线程套用（GDI 只能在 UI 线程调）"""
        try:
            res = quotes.fetch_quotes(codes, source,
                                   self.cfg.get('customSource') or {})
        except Exception as e:  # noqa: BLE001
            res = {'ok': False, 'error': str(e), 'data': {}}
        self._fetch_result = res
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_FETCH_DONE, 0, 0)

    def _apply_fetch(self):
        """UI 线程：套用后台线程的拉取结果"""
        res = self._fetch_result
        self._fetch_result = None
        self._fetching = False
        if not res:
            return
        if not res.get('ok'):
            self._fail_count = min(self._fail_count + 1, 6)
            gap = int(self._refresh_gap())
            self.widget.status_ok = False
            self.widget.status_warn = False
            self.widget.status_text = ('%s · %d 秒后重试' % (res.get('error', '获取失败'), gap)
                                       if gap else res.get('error', '获取失败'))
        else:
            self._fail_count = 0
            self.widget.prev_prices = {k: v.get('price') for k, v in self.widget.quotes.items()}
            self.widget.quotes = res['data']
            # 回填名称（仅在真的变了才落盘，避免每 5 秒写一次配置）
            changed = False
            for g in self.cfg.get('groups') or []:
                for s in g.get('stocks') or []:
                    q = self.widget.quotes.get(s.get('code'))
                    if q and q.get('name') and s.get('name') != q['name']:
                        s['name'] = q['name']
                        changed = True
            if changed:
                self.save_cfg(sync=False)   # 只是补名字，不必触发一次云同步
            if res.get('fallback'):
                label = {'tencent': '腾讯', 'sina': '新浪', 'eastmoney': '东财'}.get(res['source'], res['source'])
                self.widget.status_text = f'{label}降级（主源异常）'
                self.widget.status_ok = False
                self.widget.status_warn = True
            else:
                head = '已更新' if self.market_open() else '休市'
                self.widget.status_text = f'{head} {len(res["data"])} 只'
                self.widget.status_ok = True
                self.widget.status_warn = False
            self.widget.last_update = time.strftime('%H:%M:%S')
            storage.QuoteSnapshot.save(self.widget.quotes)   # 内容无变化时内部自动跳过
        # 行情到位后列宽会变（名称/价格实际长度不同）→ 重新算窗口大小
        if self._apply_auto_size():
            self.widget.paint_now()
        else:
            self.widget.paint_now()
        self._update_tray_tip()
        if self._pending:
            self._pending = False
            self.refresh()

    def _update_tray_tip(self):
        """托盘气泡：鼠标悬停就能看到最新更新时间，不用展开悬浮窗"""
        if not self.tray_added:
            return
        try:
            tip = '%s · %s' % (self.widget.status_text, self.widget.last_update) \
                if self.widget.last_update else _version_text()
            nid = w32.NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(w32.NOTIFYICONDATA)
            nid.hWnd = self.tray_host or self.hwnd
            nid.uID = ID_TRAY
            nid.uFlags = w32.NIF_TIP
            nid.szTip = tip[:120]
            shell32.Shell_NotifyIconW(w32.NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    # ---------------- 窗口 ----------------
    def create_window(self):
        hinst = kernel32.GetModuleHandleW(None)
        wndproc = w32.WNDPROC(self._wndproc)

        cls = w32.WNDCLASS()
        cls.style = 0x0008 | 0x0002 | 0x0001  # CS_DBLCLKS | CS_HREDRAW | CS_VREDRAW
        cls.lpfnWndProc = wndproc
        cls.hInstance = hinst
        cls.hCursor = user32.LoadCursorW(None, ctypes.c_wchar_p(32512))  # IDC_ARROW
        cls.hbrBackground = user32.GetSysColorBrush(5)  # COLOR_WINDOW
        cls.lpszClassName = 'DingPanWidget'
        user32.RegisterClassW(ctypes.byref(cls))
        self._wndproc_ref = wndproc  # 防止被 GC

        w = int(self.cfg.get('width', 320))
        h = int(self.cfg.get('height', 380))
        w = max(240, min(900, w))
        h = max(180, min(1600, h))
        bounds = self.cfg.get('windowBounds')
        if bounds:
            x, y = int(bounds.get('x', 100)), int(bounds.get('y', 100))
            # 上次拖动改过大小则以窗口矩形为准
            if bounds.get('w') and bounds.get('h'):
                w = max(240, min(900, int(bounds['w'])))
                h = max(180, min(1600, int(bounds['h'])))
        else:
            wa = w32.get_work_area()
            x = wa.right - w - 30
            y = wa.top + 60
        # 拔掉显示器 / 换过分辨率后，别把窗口留在看不见的地方
        x, y = w32.clamp_to_work_area(x, y, w, h)

        style = w32.WS_POPUP | w32.WS_CLIPCHILDREN | w32.WS_CLIPSIBLINGS
        exstyle = (w32.WS_EX_LAYERED | w32.WS_EX_TOOLWINDOW | w32.WS_EX_NOACTIVATE
                   | w32.WS_EX_TOPMOST)  # 出生即置顶，不依赖后续 SetWindowPos

        hwnd = user32.CreateWindowExW(
            exstyle, 'DingPanWidget', APP_NAME, style,
            x, y, w, h, None, None, hinst, None)
        if not hwnd:
            raise RuntimeError('创建悬浮窗失败')

        self.hwnd = hwnd
        self.widget.hwnd = hwnd
        # 必须在 ShowWindow 之前把配置交给 widget：
        # widget.cfg 默认是空 dict，ShowWindow 会立刻触发首帧绘制，
        # 晚一步赋值就会闪一帧「空表头 / 暂无自选股」。
        self.widget.cfg = self.cfg

        # 设置窗口图标
        try:
            h_big = icon.load_icon(32)
            h_small = icon.load_icon(16)
            if h_big:
                user32.SendMessageW(hwnd, w32.WM_SETICON, 1, h_big)
            if h_small:
                user32.SendMessageW(hwnd, w32.WM_SETICON, 0, h_small)
        except Exception:
            pass

        user32.SetWindowLongPtrW(hwnd, w32.GWLP_USERDATA, ctypes.cast(
            ctypes.pointer(ctypes.c_longlong(id(self))), ctypes.c_void_p).value)

        # 分层属性：先给一个"全不透明"初值，首次 paint 会改用逐像素 alpha 提交
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, w32.LWA_ALPHA)

        if self.cfg.get('alwaysOnTop', True):
            w32.set_always_on_top(hwnd, True)

        # 字号跟随系统缩放（150% 屏上不至于小得看不清）
        try:
            self.widget.dpi_scale = w32.window_scale(hwnd)
        except Exception:
            self.widget.dpi_scale = 1.0

        user32.ShowWindow(hwnd, w32.SW_SHOWNOACTIVATE)
        # 窗口建好后再按内容算一次尺寸（测量列宽需要窗口句柄）
        self._apply_auto_size()
        # 托盘宿主窗口：可激活，既当托盘图标 owner，也当所有右键菜单的 owner
        self.tray_host = _create_tray_host()
        if self.tray_host:
            _TRAY_HOSTS[int(self.tray_host)] = self
        self._create_tray()
        self._register_hotkeys()
        self._show_hint_once()
        return hwnd

    def _show_hint_once(self):
        """首次运行给一个非阻塞提示（托盘气泡），告诉用户怎么用"""
        try:
            if self.cfg.get('hintShown'):
                return
            nid = w32.NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(w32.NOTIFYICONDATA)
            nid.hWnd = self.tray_host or self.hwnd
            nid.uID = ID_TRAY
            nid.uFlags = w32.NIF_INFO
            nid.szInfoTitle = '盯盘已启动'
            nid.szInfo = '拖动标题栏移动、拖右下角改大小；右键添加自选'
            shell32.Shell_NotifyIconW(w32.NIM_MODIFY, ctypes.byref(nid))
            self.cfg['hintShown'] = True
            self.save_cfg(sync=False)
        except Exception:
            pass

    def _create_tray(self):
        hicon = icon.load_icon(16) or icon.load_icon(0)
        if not hicon:
            hicon = user32.LoadIconW(None, ctypes.c_wchar_p(32512))

        nid = w32.NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(w32.NOTIFYICONDATA)
        # 图标挂在「可激活」的托盘宿主窗口上，而不是 NOACTIVATE 的悬浮窗：
        # 系统弹出托盘右键菜单前会把前台权限给 owner，owner 不可激活就收不到，
        # 菜单会一闪即逝（表现为「右键没反应」）。
        nid.hWnd = self.tray_host or self.hwnd
        nid.uID = ID_TRAY
        nid.uFlags = w32.NIF_MESSAGE | w32.NIF_ICON | w32.NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = hicon
        nid.szTip = _version_text()
        if shell32.Shell_NotifyIconW(w32.NIM_ADD, ctypes.byref(nid)):
            self.tray_added = True
        nid.uTimeoutOrVersion = w32.NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(w32.NIM_SETVERSION, ctypes.byref(nid))

    def _on_tray_notify(self, wparam, lparam):
        """托盘图标回调（NOTIFYICON_VERSION_4：LOWORD(lParam) 是通知事件）

        - 左键 / 回车 → 显示或隐藏悬浮窗
        - 右键 → 弹出托盘菜单
        """
        notify = lparam & 0xFFFF
        if notify in (w32.WM_LBUTTONUP, w32.WM_LBUTTONDBLCLK,
                      w32.NIN_SELECT, w32.NIN_KEYSELECT):
            self.set_visible(not user32.IsWindowVisible(self.hwnd))
        elif notify in (w32.WM_RBUTTONUP, w32.WM_CONTEXTMENU,
                        w32.NIN_POPUPOPEN):
            self._show_tray_menu()

    def _destroy_tray(self):
        if self.tray_added:
            nid = w32.NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(w32.NOTIFYICONDATA)
            nid.hWnd = self.tray_host or self.hwnd
            nid.uID = ID_TRAY
            shell32.Shell_NotifyIconW(w32.NIM_DELETE, ctypes.byref(nid))
            self.tray_added = False
        if self.tray_host:
            _TRAY_HOSTS.pop(int(self.tray_host), None)
            user32.DestroyWindow(self.tray_host)
            self.tray_host = None

    # ---------------- 全局快捷键 ----------------
    def _parse_hotkey(self, acc):
        """'Ctrl+Alt+D' → (mods, vk)"""
        if not acc:
            return None, None
        parts = [p.strip() for p in acc.replace('-', '+').split('+') if p.strip()]
        if not parts:
            return None, None
        mods = 0
        key = ''
        keymap = {'right': w32.VK_RIGHT, 'left': w32.VK_LEFT, 'up': w32.VK_UP,
                  'down': w32.VK_DOWN, 'space': w32.VK_SPACE, 'esc': w32.VK_ESCAPE,
                  'enter': w32.VK_RETURN, 'delete': w32.VK_DELETE}
        for p in parts:
            low = p.lower()
            if low == 'ctrl':
                mods |= w32.MOD_CONTROL
            elif low == 'alt':
                mods |= w32.MOD_ALT
            elif low == 'shift':
                mods |= w32.MOD_SHIFT
            elif low == 'win':
                mods |= w32.MOD_WIN
            else:
                key = low
        if not key:
            return None, None
        vk = keymap.get(key)
        if vk is None:
            if len(key) == 1 and key.isalnum():
                vk = ord(key.upper())
            elif key.startswith('f') and key[1:].isdigit():
                vk = w32.VK_F1 + int(key[1:]) - 1
            else:
                return None, None
        return mods | w32.MOD_NOREPEAT, vk

    def _register_hotkeys(self):
        """注册全局热键：未勾选启用的不注册；组合被占用时自动降级到备用组合"""
        for hid in list(self.hotkey_ids.keys()):
            user32.UnregisterHotKey(self.hwnd, hid)
        self.hotkey_ids.clear()
        hks = self.cfg.get('hotkeys') or {}
        enabled = self.cfg.get('hotkeyEnabled') or {}
        hid = 0
        for name, acc in hks.items():
            if not enabled.get(name, True):
                continue          # 用户没勾选 → 完全不注册
            if not acc:
                continue
            # 构造候选：用户设定 → 逐个去掉修饰键组合的备选
            candidates = [acc] + list(_fallbacks(acc))
            for cand in candidates:
                mods, vk = self._parse_hotkey(cand)
                if mods is None:
                    continue
                hid += 1
                if user32.RegisterHotKey(self.hwnd, hid, mods, vk):
                    self.hotkey_ids[hid] = name
                    if cand != acc:
                        print(f'[hotkey] {name}: {acc} 被占用，已降级为 {cand}')
                    break
                hid -= 1
        self.failed_hotkeys = [n for n, a in hks.items()
                               if enabled.get(n, True) and a and n not in self.hotkey_ids.values()]

    # ---------------- 托盘菜单 ----------------
    def _build_tray_menu(self):
        """构建托盘右键菜单，返回 HMENU。

        单独拆出来是为了能被 tools/menu_check.py 直接调用**生产代码**校验
        （之前测试是复刻一份，等于测自己抄的副本，生产代码坏了也测不出来）。
        返回的句柄由调用方负责 DestroyMenu。
        """
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, w32.MF_STRING, CMD_SHOW, '显示悬浮窗')
        user32.AppendMenuW(menu, w32.MF_STRING, CMD_HIDE, '隐藏悬浮窗')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, CMD_REFRESH, '立即刷新')
        user32.AppendMenuW(menu, w32.MF_STRING, CMD_NEXT_GROUP, '下一分组')
        user32.AppendMenuW(menu, w32.MF_STRING, CMD_PREV_GROUP, '上一分组')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        sub = user32.CreatePopupMenu()
        cur = self.cfg.get('source', 'tencent')
        for sid, (label, _) in quotes.SOURCES.items():
            flag = w32.MF_STRING | (w32.MF_RADIOCHECK if sid == cur else 0)
            user32.AppendMenuW(sub, flag, CMD_TRAY_SOURCE_BASE + list(quotes.SOURCES).index(sid), label)
        user32.AppendMenuW(menu, w32.MF_POPUP, sub, '数据源')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, CMD_SETTINGS, '设置…')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING | w32.MF_GRAYED, 0, _version_text())
        user32.AppendMenuW(menu, w32.MF_STRING, CMD_QUIT, '退出')
        return menu

    def _show_tray_menu(self):
        menu = self._build_tray_menu()
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        cmd = _show_popup(menu, pt.x, pt.y, self.tray_host)
        user32.DestroyMenu(menu)
        self._handle_menu_cmd(cmd)

    def _handle_menu_cmd(self, cmd):
        if not cmd:
            return
        if cmd == CMD_SHOW:
            self.set_visible(True)
        elif cmd == CMD_HIDE:
            self.set_visible(False)
        elif cmd == CMD_SETTINGS:
            self.open_settings()
        elif cmd == CMD_REFRESH:
            self.refresh()
            self.widget.paint_now()
        elif cmd == CMD_NEXT_GROUP:
            self.set_group(self.group_index() + 1)
        elif cmd == CMD_PREV_GROUP:
            self.set_group(self.group_index() - 1)
        elif cmd == CMD_QUIT:
            self.quit()
        elif CMD_TRAY_SOURCE_BASE <= cmd < CMD_TRAY_SOURCE_BASE + 10:
            idx = cmd - CMD_TRAY_SOURCE_BASE
            sids = list(quotes.SOURCES)
            if 0 <= idx < len(sids):
                self.cfg['source'] = sids[idx]
                self.save_cfg()
                self.refresh()
                self.widget.paint_now()

    def quit(self):
        self.running = False
        user32.PostMessageW(self.hwnd, w32.WM_QUIT, 0, 0)

    # ---------------- 消息处理 ----------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            return self._wndproc_inner(hwnd, msg, wparam, lparam)
        except Exception as e:  # noqa: BLE001
            # windowed 模式下 ctypes 会静默吞掉回调异常，必须落盘才能排查
            log_exception('widget.wndproc msg=0x%04X w=0x%X l=0x%X' % (msg, wparam & 0xFFFFFFFF, lparam & 0xFFFFFFFF), e)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _wndproc_inner(self, hwnd, msg, wparam, lparam):
        if msg == w32.WM_NCHITTEST:
            # 标题栏（除按钮外）返回 HTCAPTION：交给系统原生拖动，最可靠
            x = ctypes.c_short(lparam & 0xFFFF).value   # 屏幕坐标（多屏可为负）
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            cx, cy = x - r.left, y - r.top
            hit_h = self.widget.header_h or 8   # 无表头时顶部留 8px 拖动条
            if 0 <= cy < hit_h and not self.widget.hit_button(cx, cy):
                return w32.HTCAPTION  # 系统原生拖动
            # 其余区域返回 HTCLIENT —— 由我们自己处理拖动，
            # 这样同一区域既能拖动窗口，又能保留「点击选中行」的行为。
            return w32.HTCLIENT
        if msg == w32.WM_EXITSIZEMOVE:
            self._snap_to_edge()
            self._save_bounds()
            return 0
        if msg == w32.WM_TIMER:
            if wparam == self._sync_timer_id:
                user32.KillTimer(hwnd, self._sync_timer_id)
                self._run_auto_sync()
                return 0
            # 窗口隐藏时不拉数据。
            # set_visible(False) 里已经 KillTimer，但 KillTimer 执行前就已入队的
            # WM_TIMER 仍会被派发出来 → 这里再显式判一次可见性，
            # 让「隐藏即停刷新」不依赖 KillTimer 的时序，隐藏状态下绝不偷跑网络请求。
            if not user32.IsWindowVisible(hwnd):
                return 0
            # 休市后降频：定时器照常触发，但没到间隔就跳过网络请求
            if time.time() < self._next_fetch:
                return 0
            self.refresh()
            return 0
        if msg == WM_APP_FETCH_DONE:
            self._apply_fetch()
            return 0
        if msg == WM_APP_SYNC_DONE:
            self._on_sync_done()
            return 0
        if msg == w32.WM_PAINT:
            self.widget.paint()
            user32.ValidateRect(hwnd, None)   # 不校验会导致 WM_PAINT 无限循环（CPU 100%）
            return 0
        if msg == w32.WM_SETCURSOR:
            # 右下角显示斜向箭头，提示可拖动改大小
            lp = lparam & 0xFFFF
            if lp == w32.HTCLIENT and self._cursor_on_grip():
                hcur = user32.LoadCursorW(None, ctypes.c_wchar_p(w32.IDC_SIZENWSE))
                user32.SetCursor(hcur)
                return 1
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == w32.WM_ERASEBKGND:
            return 1
        if msg == w32.WM_HOTKEY:
            name = self.hotkey_ids.get(int(wparam))
            if name == 'toggleVisible':
                self.set_visible(not user32.IsWindowVisible(hwnd))
            elif name == 'refresh':
                self.refresh()
                self.widget.paint_now()
            elif name == 'openSettings':
                self.open_settings()
            elif name == 'nextGroup':
                self.set_group(self.group_index() + 1)
            return 0
        if msg == w32.WM_NCLBUTTONDBLCLK:
            # 标题栏双击：系统不会发 WM_LBUTTONDBLCLK，这里补上「隐藏」行为
            self.set_visible(False)
            return 0
        if msg == w32.WM_MOUSEMOVE:
            self._on_mousemove(lparam)
            return 0
        if msg == w32.WM_LBUTTONDOWN:
            self._on_lbutton_down(hwnd, lparam)
            return 0
        if msg == w32.WM_LBUTTONUP:
            self._end_resize()
            self._on_lbutton_up(lparam)
            return 0
        if msg == w32.WM_CAPTURECHANGED:
            self._resize = None
            # 拖动过程中**真的**失去捕获（Alt+Tab 等）→ 复位，别留下野状态。
            # ⚠️ 不能无条件清：SetCapture 到自己时，Windows 也会给「旧捕获窗口」
            # （也就是自己）发 WM_CAPTURECHANGED —— 无条件清会让第二次按下
            # 刚设置好的 _drag_hwnd 立刻被清掉，表现为「点第二下就没反应」。
            # 用 GetCapture() 判断现在到底归谁。
            if self._drag_hwnd and user32.GetCapture() != self._drag_hwnd:
                self._drag_hwnd = None
                self._drag_moved = False
            return 0
        if msg == w32.WM_LBUTTONDBLCLK:
            self._on_dblclick(lparam)
            return 0
        if msg == w32.WM_RBUTTONUP:
            self._on_rbutton_up(hwnd, lparam)
            return 0
        if msg == w32.WM_MOUSEWHEEL:
            delta = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            step = delta // 120
            if w32.low_level_key(w32.VK_CONTROL):
                # Ctrl+滚轮：直接调背景不透明度，不用开设置窗
                a = int(self.cfg.get('bgAlpha', 100)) + step * 5
                self.cfg['bgAlpha'] = max(20, min(100, a))
                self.save_cfg()
                self.widget.status_text = '背景不透明度 %d%%' % self.cfg['bgAlpha']
                self.widget.paint_now()
                return 0
            self.widget.scroll = max(0, min(self.widget.max_scroll,
                                             self.widget.scroll - step))
            self.widget.paint_now()
            return 0
        if msg == w32.WM_KEYDOWN:
            self._on_keydown(hwnd, wparam)
            return 0
        if msg == w32.WM_SIZE:
            self.widget._cleanup_buffers()
            self.widget.paint_now()
            return 0
        if msg == w32.WM_GETMINMAXINFO:
            mmi = ctypes.cast(lparam, ctypes.POINTER(w32.MINMAXINFO)).contents
            mmi.ptMinTrackSize.x = 240
            mmi.ptMinTrackSize.y = 180
            mmi.ptMaxTrackSize.x = 900
            mmi.ptMaxTrackSize.y = 1600
            return 0
        if msg == w32.WM_DESTROY:
            self._save_bounds()
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_APP_RELOAD:
            self.cfg = storage.load_config()
            self.widget.cfg = self.cfg
            self.widget._fonts.clear()
            self._register_hotkeys()
            # 刷新间隔改了要立刻生效，而不是等下次重启
            self._fail_count = 0
            self._next_fetch = 0.0
            user32.SetTimer(hwnd, self._timer_id,
                            max(1500, int(self.cfg.get('refreshInterval', 5000))), None)
            self.widget.paint_now()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _cursor_on_grip(self):
        """光标是否落在右下角缩放宽热区"""
        if not self.hwnd:
            return False
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        r = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        return self.widget.hit_resize(pt.x - r.left, pt.y - r.top)

    def _begin_resize(self, hwnd):
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        self._resize = ((r.right - r.left, r.bottom - r.top), (pt.x, pt.y))
        try:
            user32.SetCapture(hwnd)
        except Exception:  # noqa: BLE001
            pass

    def _do_resize(self, hwnd, pt=None):
        if not self._resize:
            return
        (sw, sh), (sx, sy) = self._resize
        if pt is None:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
        w = max(240, min(900, sw + pt.x - sx))
        h = max(160, min(1600, sh + pt.y - sy))
        user32.SetWindowPos(hwnd, None, 0, 0, w, h,
                            0x0002 | 0x0004 | 0x0010)  # NOMOVE|NOZORDER|NOACTIVATE

    def _end_resize(self):
        if not self._resize:
            return
        self._resize = None
        try:
            user32.ReleaseCapture()
        except Exception:  # noqa: BLE001
            pass
        r = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        self.cfg['width'] = r.right - r.left
        self.cfg['height'] = r.bottom - r.top
        # 用户主动改了尺寸 → 关掉「按内容自适应」，尊重他的选择
        if self.cfg.get('autoSize', True):
            self.cfg['autoSize'] = False
            self.widget.status_text = '已关闭自动适应（可在基础设置里开启）'
        self.save_cfg(sync=False)
        self.widget._cleanup_buffers()
        self.widget.paint_now()

    def _on_mousemove(self, lparam):
        """鼠标移动：正在拖动窗口 / 正在改大小时分别处理，其余只更新悬停高亮"""
        if self._resize:
            self._do_resize(self.hwnd)
            return
        if self._drag_hwnd:
            # 还没判定为拖动 → 观察移动量；超过阈值就切成系统原生移动
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            ox, oy = self._drag_from
            if not self._drag_moved and (abs(x - ox) > 3 or abs(y - oy) > 3):
                self._drag_moved = True
                self._begin_native_move()
            return
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        btn = self.widget.hit_button(x, y)
        row = self.widget.hit_row(x, y)
        if btn != self.widget.hover_btn or row != self.widget.hover_row:
            self.widget.hover_btn = btn
            self.widget.hover_row = row
            self.widget.paint_now()

    def _on_lbutton_down(self, hwnd, lparam):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        # 右下角：拖动改大小
        if self.widget.hit_resize(x, y):
            self._begin_resize(hwnd)
            return
        # 标题栏按钮：‹ › ⟳ ⚙ ✕
        btn = self.widget.hit_button(x, y)
        if btn:
            if btn == 'prev':
                self.set_group(self.group_index() - 1)
            elif btn == 'next':
                self.set_group(self.group_index() + 1)
            elif btn == 'refresh':
                self.refresh()
            elif btn == 'settings':
                self.open_settings()
            elif btn == 'close':
                self.set_visible(False)  # 隐藏到托盘
            return
        # 标题栏空白区交给 HTCAPTION 原生拖动，不处理按下
        if y < self.widget.header_h:
            return
        # 分组标签
        ti = self.widget.hit_tab(x, y)
        if ti is not None:
            self.set_group(ti)
            return
        # 其余任何位置 → 进入「可能拖动窗口」状态。
        # 按下时先不动，等鼠标移动超过阈值才判定为拖动；
        # 没移动就在松开时按「点击」处理（选中行）。
        self._drag_from = (x, y)
        self._drag_moved = False
        self._drag_hwnd = hwnd
        # 捕获鼠标消息（不改光标位置），这样按住鼠标移出窗口也能继续收到移动
        try:
            user32.SetCapture(hwnd)
        except Exception:  # noqa: BLE001
            pass

    def _begin_native_move(self):
        """判定为拖动 → 切换到**系统原生**窗口移动。

        为什么不用自己 SetWindowPos 跟鼠标走：
        1) 每移一次就触发一次 WM_SIZE → 重绘整个分层窗口（alpha 逐像素合成很贵）
           → 表现为「拖不动、很卡」；
        2) 分层窗口快速移动时合成跟不上 → 出现重影/拖影。
        交给系统（WM_NCLBUTTONDOWN + HTCAPTION）由系统来搬位图，
        既流畅又不会重影。
        """
        hwnd = self._drag_hwnd
        self._drag_hwnd = None
        try:
            user32.ReleaseCapture()
        except Exception:  # noqa: BLE001
            pass
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        lp = (pt.y << 16) | (pt.x & 0xFFFF)
        # 这条消息会走 DefWindowProc → 系统进入移动循环（阻塞到用户松开鼠标）
        user32.SendMessageW(hwnd, w32.WM_NCLBUTTONDOWN, w32.HTCAPTION, lp)
        self._last_drag_ts = time.time()
        # 原生移动结束会发 WM_EXITSIZEMOVE → 那里会 _snap_to_edge + _save_bounds

    def _on_lbutton_up(self, lparam):
        """松开鼠标：没移动过就按点击处理（选中行）。

        真的拖动过的话，_begin_native_move() 已经把 _drag_hwnd 清了，
        原生移动由系统负责，这里什么都不用做。
        """
        if not self._drag_hwnd:
            return
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        self._drag_hwnd = None
        self._drag_moved = False
        try:
            user32.ReleaseCapture()
        except Exception:
            pass
        # 没移动 → 当作点击：选中行
        ri = self.widget.hit_row(x, y)
        if ri >= 0:
            self.widget.selected = ri
            self.widget.paint_now()

    def _on_dblclick(self, lparam):
        """双击悬浮窗 → 隐藏到托盘（这是默认行为）。

        「打开行情页」改由行上的右键菜单提供（菜单项 1），
        避免用户想隐藏时却误开浏览器。

        注意：刚拖动过窗口时不要当成双击 —— 否则「拖完顺手双击」会把窗口弄丢。
        """
        if time.time() - self._last_drag_ts < 0.4:
            return
        self.set_visible(False)

    def open_settings(self):
        """打开设置窗口（始终复用同一个实例）。

        历史 Bug：每次都 `SettingsWindow(self).show()` 新建一个对象，
        于是点几次「设置」就叠出几个设置窗，旧的还挂在屏幕上，
        控件句柄/页面状态全乱 —— 表现就是「保存后再打开就出错、页面打不开」。
        """
        obj = getattr(self, '_settings_obj', None)
        if obj is None:
            from .settings import SettingsWindow
            obj = SettingsWindow(self)
            self._settings_obj = obj
        obj.show()
        return obj

    def _open_quote(self, code):
        """打开行情详情页（平台可在「基础设置」里选，也支持自定义 URL 模板）。

        默认雪球：https://xueqiu.com/S/<交易所><代码>
        A股 SH600519 / SZ000001 / BJ430047，港股 HK00700，美股 AAPL。
        """
        url = quotes.build_quote_url(
            code,
            self.cfg.get('quotePlatform', 'xueqiu'),
            self.cfg.get('quoteUrlTemplate', ''))
        if not url:
            return
        try:
            os.startfile(url)  # noqa: S606
        except OSError:
            pass

    def _on_rbutton_up(self, hwnd, lparam):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        # 坐标转换到屏幕
        pt = wintypes.POINT(x, y)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        ri = self.widget.hit_row(x, y)
        if ri >= 0:
            self._show_row_menu(pt.x, pt.y, ri)
        else:
            self._show_main_menu(pt.x, pt.y)

    def _build_row_menu(self, row_index):
        """构建某一行股票的右键菜单，返回 HMENU（无效行返回 None）。"""
        groups = self.cfg.get('groups') or []
        gi = self.group_index()
        stocks = groups[gi].get('stocks', []) if 0 <= gi < len(groups) else []
        if not (0 <= row_index < len(stocks)):
            return None
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, w32.MF_STRING, 1, '打开行情页')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING | (w32.MF_GRAYED if row_index == 0 else 0), 2, '上移')
        user32.AppendMenuW(menu, w32.MF_STRING | (w32.MF_GRAYED if row_index >= len(stocks) - 1 else 0), 3, '下移')
        user32.AppendMenuW(menu, w32.MF_STRING | (w32.MF_GRAYED if row_index == 0 else 0), 4, '置顶')
        user32.AppendMenuW(menu, w32.MF_STRING | (w32.MF_GRAYED if row_index >= len(stocks) - 1 else 0), 5, '置底')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, 6, '复制代码')
        user32.AppendMenuW(menu, w32.MF_STRING, 7, '删除自选')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, 8, '设置…')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, 9, '退出程序')
        return menu

    def _show_row_menu(self, sx, sy, row_index):
        menu = self._build_row_menu(row_index)
        if not menu:
            return
        groups = self.cfg.get('groups') or []
        gi = self.group_index()
        stocks = groups[gi].get('stocks', []) if 0 <= gi < len(groups) else []
        cmd = _show_popup(menu, sx, sy, self.tray_host)
        user32.DestroyMenu(menu)
        if cmd == 1:
            self._open_quote(stocks[row_index].get('code', ''))
        elif cmd == 2:
            self._move_stock(row_index, -1)
        elif cmd == 3:
            self._move_stock(row_index, 1)
        elif cmd == 4:
            self._pin_stock(row_index, True)
        elif cmd == 5:
            self._pin_stock(row_index, False)
        elif cmd == 6:
            w32.clipboard_set_text(stocks[row_index].get('code', ''))
            self.widget.status_text = '已复制 %s' % stocks[row_index].get('code', '')
            self.widget.paint_now()
        elif cmd == 7:
            groups[gi]['stocks'].pop(row_index)
            self.cfg['activeGroupId'] = groups[gi]['id']
            self.save_cfg()
            self.widget.selected = min(row_index, len(groups[gi]['stocks']) - 1)
            self.refresh()
            self._apply_auto_size()
            self.widget.paint_now()
        elif cmd == 8:
            self.open_settings()
        elif cmd == 9:
            self.quit()

    # ---------------- 行顺序 ----------------
    def _move_stock(self, row, delta):
        groups = self.cfg.get('groups') or []
        gi = self.group_index()
        stocks = groups[gi].get('stocks', []) if 0 <= gi < len(groups) else []
        j = row + delta
        if not (0 <= row < len(stocks) and 0 <= j < len(stocks)):
            return
        stocks[row], stocks[j] = stocks[j], stocks[row]
        self.widget.selected = j
        self.widget.ensure_visible(j)
        self.save_cfg()
        self.widget.paint_now()

    def _pin_stock(self, row, to_top=True):
        groups = self.cfg.get('groups') or []
        gi = self.group_index()
        stocks = groups[gi].get('stocks', []) if 0 <= gi < len(groups) else []
        if not (0 <= row < len(stocks)):
            return
        s = stocks.pop(row)
        stocks.insert(0, s) if to_top else stocks.append(s)
        self.widget.selected = 0 if to_top else len(stocks) - 1
        self.widget.ensure_visible(self.widget.selected)
        self.save_cfg()
        self.widget.paint_now()

    def _copy_all_codes(self):
        groups = self.cfg.get('groups') or []
        gi = self.group_index()
        stocks = groups[gi].get('stocks', []) if 0 <= gi < len(groups) else []
        text = '\n'.join(s.get('code', '') for s in stocks if s.get('code'))
        ok = w32.clipboard_set_text(text) if text else False
        self.widget.status_text = ('已复制 %d 个代码' % len(stocks)) if ok else '没有可复制的代码'
        self.widget.status_ok = ok
        self.widget.paint_now()

    def _build_main_menu(self):
        """构建悬浮窗空白处右键菜单，返回 HMENU。"""
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, w32.MF_STRING, 1, '添加自选股…')
        user32.AppendMenuW(menu, w32.MF_STRING, 2, '从剪贴板添加')
        user32.AppendMenuW(menu, w32.MF_STRING, 3, '复制全部代码')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, 4, '设置…')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, 5, '隐藏到托盘')
        user32.AppendMenuW(menu, w32.MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, w32.MF_STRING, 6, '退出程序')
        return menu

    def _show_main_menu(self, sx, sy):
        menu = self._build_main_menu()
        cmd = _show_popup(menu, sx, sy, self.tray_host)
        user32.DestroyMenu(menu)
        if cmd == 1:
            self._prompt_add_stock()
        elif cmd == 2:
            self._add_from_clipboard()
        elif cmd == 3:
            self._copy_all_codes()
        elif cmd == 4:
            self.open_settings()
        elif cmd == 5:
            self.set_visible(False)
        elif cmd == 6:
            self.quit()

    def _prompt_add_stock(self):
        """弹出输入框添加自选股，支持一次粘贴多只（空格 / 逗号 / 换行分隔）"""
        from .dialogs import prompt_text
        text = prompt_text('添加自选股', '代码，多只用空格或逗号分隔',
                           '例如 600519 000001 sz300750 00700')
        if not text:
            return
        codes = quotes.parse_codes(text)
        if not codes:
            from .dialogs import message_box
            message_box('添加自选股', '没有识别到有效的证券代码', 'warning')
            return
        self._add_codes(codes)

    def _add_from_clipboard(self):
        from .dialogs import message_box
        codes = quotes.extract_codes(w32.clipboard_get_text())
        if not codes:
            message_box('从剪贴板添加', '剪贴板里没有识别到证券代码', 'warning')
            return
        self._add_codes(codes)

    def _add_codes(self, codes):
        """批量添加：一次请求校验全部代码，失败的汇总报告，避免一只一只慢慢试"""
        from .dialogs import message_box
        codes = [c for c in dict.fromkeys(codes) if c]
        if not codes:
            return 0
        groups = self.cfg.get('groups') or []
        if not groups:
            groups = [{'id': 'g_default', 'name': '默认分组', 'stocks': []}]
            self.cfg['groups'] = groups
        gi = self.group_index() if 0 <= self.group_index() < len(groups) else 0
        stocks = groups[gi].setdefault('stocks', [])
        existing = {s.get('code') for s in stocks}
        todo = [c for c in codes if c not in existing]
        dup = len(codes) - len(todo)
        if not todo:
            message_box('添加自选股', '这些代码都已经在列表里了', 'info')
            return 0
        res = quotes.fetch_quotes(todo, self.cfg.get('source', 'tencent'),
                                    self.cfg.get('customSource') or {})
        if not res.get('ok'):
            message_box('添加失败', res.get('error') or '网络异常，请稍后再试', 'error')
            return 0
        data = res.get('data') or {}
        added, failed = [], []
        for c in todo:
            q = data.get(c) or {}
            if q.get('name'):
                stocks.append({'code': c, 'name': q['name']})
                added.append('%s %s' % (c, q['name']))
            else:
                failed.append(c)
        if added:
            self.cfg['activeGroupId'] = groups[gi]['id']
            self.save_cfg()
            self.widget.quotes.update({c: data[c] for c in todo if c in data})
            self.refresh()
            self.widget.paint_now()
        parts = []
        if added:
            parts.append('已添加 %d 只' % len(added))
        if dup:
            parts.append('已存在 %d 只' % dup)
        if failed:
            parts.append('未找到：' + '、'.join(failed))
        if failed:
            message_box('添加自选股', '\n'.join(parts), 'warning' if added else 'error')
        elif added:
            self.widget.status_text = '已添加 %d 只' % len(added)
            self.widget.paint_now()
        return len(added)

    def _on_keydown(self, hwnd, wparam):
        vk = int(wparam)
        ctrl = w32.low_level_key(w32.VK_CONTROL)
        alt = w32.low_level_key(w32.VK_MENU)
        shift = w32.low_level_key(w32.VK_SHIFT)
        if ctrl and alt:
            if vk == ord('R'):
                self.refresh()
                self.widget.paint_now()
            elif vk == ord('S'):
                self.open_settings()
            elif vk == ord('D'):
                self.set_visible(False)
            elif vk == w32.VK_RIGHT:
                self.set_group(self.group_index() + 1)
            elif vk == w32.VK_LEFT:
                self.set_group(self.group_index() - 1)
            return
        if ctrl and vk == ord('N'):
            self._prompt_add_stock()
            return
        if ctrl and vk in (w32.VK_UP, w32.VK_DOWN):
            # Ctrl+↑/↓：调整选中行的位置（不改数据，只改显示顺序）
            if self.widget.selected >= 0:
                self._move_stock(self.widget.selected, -1 if vk == w32.VK_UP else 1)
            return
        if vk in (w32.VK_UP, w32.VK_DOWN, w32.VK_PRIOR, w32.VK_NEXT,
                  w32.VK_HOME, w32.VK_END):
            groups = self.cfg.get('groups') or []
            gi = self.group_index()
            n = len(groups[gi].get('stocks', [])) if 0 <= gi < len(groups) else 0
            if n:
                page = max(1, getattr(self.widget, '_visible_rows', 1) - 1)
                cur = self.widget.selected
                if vk == w32.VK_UP:
                    cur = max(0, cur - 1) if cur >= 0 else 0
                elif vk == w32.VK_DOWN:
                    cur = min(n - 1, cur + 1) if cur >= 0 else 0
                elif vk == w32.VK_PRIOR:
                    cur = max(0, (cur if cur >= 0 else 0) - page)
                elif vk == w32.VK_NEXT:
                    cur = min(n - 1, (cur if cur >= 0 else 0) + page)
                elif vk == w32.VK_HOME:
                    cur = 0
                else:
                    cur = n - 1
                self.widget.selected = cur
                # 选中项跟着滚动，别让光标跑到看不见的地方
                self.widget.ensure_visible(cur)
                self.widget.paint_now()
            return
        if vk in (w32.VK_DELETE, w32.VK_BACK):
            groups = self.cfg.get('groups') or []
            gi = self.group_index()
            stocks = groups[gi].get('stocks', []) if 0 <= gi < len(groups) else []
            if 0 <= self.widget.selected < len(stocks):
                stocks.pop(self.widget.selected)
                self.cfg['activeGroupId'] = groups[gi]['id']
                self.save_cfg()
                self.widget.selected = -1
                self.refresh()
                self.widget.paint_now()

    def _snap_to_edge(self):
        """拖到离屏幕边缘 14px 以内时自动贴边"""
        if not self.hwnd:
            return
        r = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        nx, ny = w32.snap_to_edges(r.left, r.top, w, h)
        if (nx, ny) != (r.left, r.top):
            user32.SetWindowPos(self.hwnd, None, nx, ny, 0, 0,
                                w32.SWP_NOSIZE | w32.SWP_NOZORDER | w32.SWP_NOACTIVATE)

    def _save_bounds(self):
        if not self.hwnd:
            return
        r = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        self.cfg['windowBounds'] = {'x': r.left, 'y': r.top,
                                    'w': r.right - r.left, 'h': r.bottom - r.top}
        self.save_cfg(sync=False)

    def _apply_window_flags(self):
        """把「窗口标题 / 始终置顶 / 刷新间隔」立刻作用到运行中的窗口。

        设置页改这几项时实时调用，不用点保存也不用重启。
        """
        if not self.hwnd:
            return
        try:
            title = (self.cfg.get('title') or '').strip()
            gname = ''
            groups = self.cfg.get('groups') or []
            gi = self.group_index()
            if 0 <= gi < len(groups):
                gname = groups[gi].get('name', '')
            text = title or (('盯盘 · ' + gname) if gname else '盯盘')
            user32.SetWindowTextW(self.hwnd, text)
            w32.set_always_on_top(self.hwnd, bool(self.cfg.get('alwaysOnTop', True)))
            interval = max(1500, int(self.cfg.get('refreshInterval', 5000)))
            if interval != getattr(self, '_cur_interval', None):
                self._cur_interval = interval
                user32.SetTimer(self.hwnd, self._timer_id, interval, None)
        except Exception:  # noqa: BLE001
            pass

    def _apply_auto_size(self):
        """按内容自适应窗口大小（列宽总宽 × 可见行数）。

        - 开着 autoSize 时，窗口尺寸完全由内容决定（不再固定长宽）
        - 字段变多/变少、股票变多变少、字号改变，都会重新算
        - 用户手动拖右下角改过大小 → 自动关掉 autoSize，尊重用户的选择
        """
        if not self.hwnd or not self.cfg.get('autoSize', True):
            return False
        try:
            w, h = self.widget.needed_size()
        except Exception:  # noqa: BLE001
            return False
        r = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        if (r.right - r.left) == w and (r.bottom - r.top) == h:
            return False
        # ⚠️ 必须带 SWP_NOMOVE(0x0002) —— 只改尺寸、**保持左上角不动**。
        #    漏掉它时 x=0,y=0 会被当成新坐标应用 → 窗口每次改设置都跑到 (0,0)，
        #    「记住上次位置」完全失效（用户反馈）。
        user32.SetWindowPos(self.hwnd, None, r.left, r.top, w, h,
                            0x0004 | 0x0010)  # NOZORDER|NOACTIVATE
        # 尺寸变大后可能越出屏幕 → 把左上角拉回可见区域
        nx, ny = w32.clamp_to_work_area(r.left, r.top, w, h)
        if (nx, ny) != (r.left, r.top):
            user32.SetWindowPos(self.hwnd, None, nx, ny, 0, 0,
                                0x0001 | 0x0004 | 0x0010)  # NOMOVE|NOZORDER|NOACTIVATE
        return True

    # ---------------- 主循环 ----------------
    def run(self):
        self.create_window()
        self.widget.cfg = self.cfg
        self.widget.paint_now()
        interval = max(1500, int(self.cfg.get('refreshInterval', 5000)))
        user32.SetTimer(self.hwnd, self._timer_id, interval, None)
        threading.Thread(target=self._initial_refresh, daemon=True).start()
        msg = wintypes.MSG()
        while self.running:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._cleanup()

    def _initial_refresh(self):
        time.sleep(0.4)
        # refresh 非阻塞：结果经 PostMessage 回 UI 线程后自动重绘
        self.refresh()

    def _cleanup(self):
        try:
            for hid in self.hotkey_ids:
                user32.UnregisterHotKey(self.hwnd, hid)
            self._destroy_tray()
            self.widget.release_fonts()
            self.widget._cleanup_buffers()
            self._save_bounds()
            icon.cleanup()      # 删掉临时图标文件，不留缓存
        except Exception:  # noqa: BLE001
            pass


def main():
    install_excepthook()
    if sys.platform != 'win32':
        print('本程序仅支持 Windows')
        return 1
    # 单实例：已有新版本实例在运行时把它唤到前台然后退出
    mutex = kernel32.CreateMutexW(None, False, 'DingPan_SingleInstance_Mutex')
    if mutex and ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = user32.FindWindowW('DingPanWidget', None)
        if hwnd:
            user32.ShowWindow(hwnd, w32.SW_SHOWNOACTIVATE)
            w32.set_always_on_top(hwnd, True)  # 置顶但不抢焦点
        return 0
    # 成为主实例：启动窗口（绝不触碰任何其他进程的窗口，避免误关用户程序）
    app = App()
    try:
        app.run()
    except Exception as e:  # noqa: BLE001
        log_exception('run()', e)
        try:
            from .dialogs import message_box
            message_box('盯盘 启动失败', str(e), 'error')
        except Exception:  # noqa: BLE001
            traceback_print(e)
        return 1
    return 0


def traceback_print(e):
    import traceback
    traceback.print_exc()
    log_exception('traceback', e)


def crash_log_path():
    try:
        d = storage.app_dir()
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, 'crash.log')
    except Exception:
        return None


_LOG_MAX = 192 * 1024   # 单个日志上限 192 KB，超了轮转，避免长期运行越积越大


def _rotate_log(p):
    """日志超过上限就改名成 crash.log.old（只留一份）"""
    try:
        if os.path.isfile(p) and os.path.getsize(p) > _LOG_MAX:
            old = p + '.old'
            try:
                os.remove(old)
            except OSError:
                pass
            os.replace(p, old)
    except OSError:
        pass


def log_exception(context, exc):
    """windowed 模式无控制台，异常一律落盘便于排查"""
    try:
        import datetime
        import traceback
        p = crash_log_path()
        if not p:
            return
        _rotate_log(p)
        with open(p, 'a', encoding='utf-8') as f:
            f.write('\n===== %s | %s =====\n' % (context, datetime.datetime.now()))
            traceback.print_exc(file=f)
    except Exception:
        pass


def install_excepthook():
    """捕获未处理异常写入 crash.log（含后台线程）"""
    import threading as _t

    def hook(args):
        try:
            log_exception('thread: %s' % (getattr(args.exc_type, '__name__', '?')),
                          args.exc_value)
        except Exception:
            pass

    try:
        _t.excepthook = hook
    except Exception:
        pass

    orig = sys.excepthook

    def _sys_hook(typ, val, tb):
        try:
            import traceback
            p = crash_log_path()
            if p:
                _rotate_log(p)
                with open(p, 'a', encoding='utf-8') as f:
                    f.write('\n===== sys.excepthook =====\n')
                    traceback.print_exception(typ, val, tb, file=f)
        except Exception:
            pass
        try:
            orig(typ, val, tb)
        except Exception:
            pass

    sys.excepthook = _sys_hook
