"""
Win32 原生层（ctypes 封装）
零第三方依赖，直接调用 user32 / gdi32 / shell32 / comctl32。
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
comdlg32 = ctypes.WinDLL('comdlg32', use_last_error=True)
comctl32 = ctypes.WinDLL('comctl32', use_last_error=True)

user32.SetProcessDPIAware.restype = wintypes.BOOL
user32.SetProcessDPIAware.argtypes = []
user32.SetProcessDPIAware()

# PrintWindow：把窗口自身内容画进 DC（视觉验收工具用来抓悬浮窗/菜单的渲染结果）
user32.PrintWindow.restype = wintypes.BOOL
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]


def init_common_controls():
    """初始化公共控件（启用视觉样式所需的 comctl32 v6）"""
    try:
        INITCOMMONCONTROLSEX = ctypes.c_size_t * 2

        class IccEx(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('dwICC', wintypes.DWORD)]

        c = IccEx()
        c.dwSize = ctypes.sizeof(IccEx)
        c.dwICC = 0x00003FFF          # ICC_STANDARD_CLASSES | ... 全量
        comctl32.InitCommonControlsEx(ctypes.byref(c))
        del INITCOMMONCONTROLSEX
        return True
    except Exception:
        return False

# ------------------------------ 常量 ------------------------------
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_APPWINDOW = 0x00040000
WS_EX_CLIENTEDGE = 0x00000200
WS_OVERLAPPEDWINDOW = 0x00CF0000   # WS_CAPTION|WS_MAXIMIZEBOX|WS_MINIMIZEBOX|WS_SYSMENU|WS_THICKFRAME
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_EX_DLGMODALFRAME = 0x00000001
WM_HSCROLL = 0x0114
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000

WS_POPUP_WINDOW = WS_POPUP

SW_SHOW = 5
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

GWL_EXSTYLE = -20
GWL_WNDPROC = -4
GWL_STYLE = -16
GWL_USERDATA = -21

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_NULL = 0x0000
WM_SIZE = 0x0005
WM_PAINT = 0x000F
WM_SETFOCUS = 0x0007
WM_KILLFOCUS = 0x0008
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_CONTEXTMENU = 0x007B
WM_APP = 0x8000
WM_HOTKEY = 0x0312
WM_ERASEBKGND = 0x0014
WM_NCHITTEST = 0x0084
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONDBLCLK = 0x00A3
WM_CAPTURECHANGED = 0x0215
WM_SETCURSOR = 0x0020
WM_EXITSIZEMOVE = 0x0232
WM_GETMINMAXINFO = 0x0024
WM_DISPLAYCHANGE = 0x007E
WM_SETTINGCHANGE = 0x001A

HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

IDC_SIZENWSE = 32642          # 右下角拖动用的斜向箭头光标
IDC_ARROW = 32512

AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0

LWA_COLOR = 0x01
LWA_ALPHA = 0x02

ULW_ALPHA = 0x00000002

TRANSPARENT = 0
OPAQUE = 255

SRCCOPY = 0x00CC0020
DSTINVERT = 0x00F00021
PATCOPY = 0x00F00021

BI_RGB = 0

# 托盘
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NOTIFYICON_VERSION_4 = 4

WM_SETICON = 0x0080
WM_USER = 0x0400
WM_APP_TRAY = WM_USER + 20
WM_APP_QUIT = WM_USER + 21

# NOTIFYICON_VERSION_4 下 LOWORD(lParam) 才是通知事件：
# 左键 → NIN_SELECT / NIN_KEYSELECT；右键 → NIN_POPUPOPEN（应用要自己弹菜单）
NIN_SELECT = WM_USER + 0
NIN_KEYSELECT = WM_USER + 1
NIN_BALLOONSHOW = WM_USER + 2
NIN_BALLOONHIDE = WM_USER + 3
NIN_BALLOONTIMEOUT = WM_USER + 4
NIN_BALLOONUSERCLICK = WM_USER + 5
NIN_POPUPOPEN = WM_USER + 6
NIN_POPUPCLOSE = WM_USER + 7

# 菜单
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_POPUP = 0x00000010
MF_GRAYED = 0x00000001
MF_CHECKED = 0x00000008
MF_UNCHECKED = 0x00000000
MF_RADIOCHECK = 0x00000020
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

MF_BYCOMMAND = 0x00000000
TPM_LEFTALIGN = 0x0000

# 编辑框
ES_AUTOHSCROLL = 0x0080
ES_LEFT = 0x0000
WS_CHILD = 0x40000000
WS_BORDER = 0x00800000
WS_TABSTOP = 0x00010000
WS_VSCROLL = 0x00200000
WS_HSCROLL = 0x00100000
# 列表框样式：0x0008 是 LBS_MULTIPLESEL（多选），多选列表框会忽略 LB_SETCURSEL，
# 必须用 LBS_NOTIFY | LBS_NOINTEGRALHEIGHT 才是正常的单选可滚动列表。
LBS_NOTIFY = 0x0001
LBS_NOINTEGRALHEIGHT = 0x0100
LISTBOX_STYLE = (LBS_NOTIFY | LBS_NOINTEGRALHEIGHT | WS_BORDER
                 | WS_VSCROLL | WS_TABSTOP)
BS_DEFPUSHBUTTON = 0x0001
BS_PUSHBUTTON = 0x0000
BS_AUTOCHECKBOX = 0x0003
BS_AUTORADIOBUTTON = 0x0009
SS_LEFT = 0x0000
SS_CENTER = 0x0001
ES_NUMBER = 0x2000

WM_CTLCOLOREDIT = 0x0133
WM_CTLCOLORSTATIC = 0x0138
WM_CTLCOLORBTN = 0x0135

# 消息框
MB_OK = 0x00000000
MB_YESNO = 0x00000004
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000
IDYES = 6

# 通用文件对话框
OFN_OVERWRITEPROMPT = 0x00000002
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_EXPLORER = 0x00080000

# SetWindowPos 标志
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

# 通用控件
ICC_LISTVIEW_CLASSES = 0x00000001
LVS_EX_FULLROWSELECT = 0x00000020
LVS_EX_DOUBLEBUFFER = 0x00010000
LVS_REPORT = 0x0001
LVS_NOSORTHEADER = 0x0800
LVS_SHOWSELALWAYS = 0x0008
LVIF_TEXT = 0x0001
LVIF_SUBITEM = 0x00040000
LVIF_STATE = 0x0008

# 组合框
CBS_DROPDOWNLIST = 0x0002
CBS_HASSTRINGS = 0x0008
CBN_SELCHANGE = 1

# 复选框
BST_CHECKED = 0x00000001
BST_UNCHECKED = 0x00000000
BST_PUSHED = 0x00000008

WM_GETFONT = 0x0031
WM_SETFONT = 0x0030
DEFAULT_GUI_FONT = 17

# 键盘
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_DELETE = 0x2E
VK_BACK = 0x08
VK_UP = 0x26
VK_DOWN = 0x28
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_F1 = 0x70
VK_TAB = 0x09
VK_SPACE = 0x20
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_HOME = 0x24
VK_END = 0x23
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_INSERT = 0x2D
WM_SYSKEYDOWN = 0x0104

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# 窗口消息常量
GWLP_USERDATA = -21
GA_ROOT = 2

# 颜色
CLR_NONE = 0xFFFFFFFF

MONITOR_DEFAULTTONEAREST = 2
ENUM_CURRENT_SETTINGS = -1


class DRAWITEMSTRUCT(ctypes.Structure):
    """WM_DRAWITEM 的参数（自绘列表/按钮）"""
    _fields_ = [
        ('CtlType', wintypes.UINT),
        ('CtlID', wintypes.UINT),
        ('hwndItem', wintypes.HWND),
        ('hDC', wintypes.HDC),
        ('rcItem', wintypes.RECT),
        ('itemData', wintypes.LPARAM),
        ('itemState', wintypes.UINT),
    ]


class MEASUREITEMSTRUCT(ctypes.Structure):
    """WM_MEASUREITEM 的参数（自绘列表必须回填 itemHeight，否则一项都不显示）"""
    _fields_ = [
        ('CtlType', wintypes.UINT),
        ('CtlID', wintypes.UINT),
        ('hwndItem', wintypes.HWND),
        ('itemHeight', wintypes.UINT),
        ('itemData', wintypes.LPARAM),
    ]


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ('style', ctypes.c_uint),
        ('lpfnWndProc', ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM)),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HANDLE),
        ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ('hdc', wintypes.HDC),
        ('fErase', wintypes.BOOL),
        ('rcPaint', wintypes.RECT),
        ('fRestore', wintypes.BOOL),
        ('fIncUpdate', wintypes.BOOL),
        ('rgbReserved', ctypes.c_byte * 32),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', ctypes.c_long),
        ('biHeight', ctypes.c_long),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uID', wintypes.UINT),
        ('uFlags', wintypes.UINT),
        ('uCallbackMessage', wintypes.UINT),
        ('hIcon', wintypes.HICON),
        ('szTip', wintypes.WCHAR * 128),
        ('dwState', wintypes.DWORD),
        ('dwStateMask', wintypes.DWORD),
        ('szInfo', wintypes.WCHAR * 256),
        ('uTimeoutOrVersion', wintypes.UINT),
        ('szInfoTitle', wintypes.WCHAR * 64),
        ('dwInfoFlags', wintypes.DWORD),
        ('guidItem', ctypes.c_byte * 16),
        ('hBalloonIcon', wintypes.HICON),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', wintypes.RECT),
        ('rcWork', wintypes.RECT),
        ('dwFlags', wintypes.DWORD),
    ]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ('ptReserved', wintypes.POINT),
        ('ptMaxSize', wintypes.POINT),
        ('ptMaxPosition', wintypes.POINT),
        ('ptMinTrackSize', wintypes.POINT),
        ('ptMaxTrackSize', wintypes.POINT),
    ]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('dwHoverTime', wintypes.DWORD),
        ('rcRect', wintypes.RECT),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ('BlendOp', wintypes.BYTE),
        ('BlendFlags', wintypes.BYTE),
        ('SourceConstantAlpha', wintypes.BYTE),
        ('AlphaFormat', wintypes.BYTE),
    ]


class CHOOSECOLORW(ctypes.Structure):
    _fields_ = [
        ('lStructSize', wintypes.DWORD),
        ('hwndOwner', wintypes.HWND),
        ('hInstance', wintypes.HWND),
        ('rgbResult', wintypes.DWORD),
        ('lpCustColors', ctypes.POINTER(wintypes.DWORD)),
        ('Flags', wintypes.DWORD),
        ('lCustData', wintypes.LPARAM),
        ('lpfnHook', ctypes.c_void_p),
        ('lpTemplateName', wintypes.LPCWSTR),
    ]


_CUST_COLORS = (wintypes.DWORD * 16)(0x00FFFFFF, 0x00C0C0C0, 0x00808080, 0x00404040,
                                    0x00FF0000, 0x0000FF00, 0x000000FF, 0x00FFFF00,
                                    0x00FF00FF, 0x0000FFFF, 0x00800000, 0x00008000,
                                    0x00000080, 0x00808000, 0x00800080, 0x00008080)


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)


def _init_prototypes():
    """声明函数原型（32/64 位安全）"""
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
    ]
    user32.DefWindowProcW.restype = ctypes.c_longlong
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetWindowLongPtrW.restype = ctypes.c_longlong
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    # CallWindowProcW：子类化窗口过程后，把消息转回「原窗口过程」要用
    user32.CallWindowProcW.restype = ctypes.c_longlong
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                       ctypes.c_ulonglong, ctypes.c_longlong]
    user32.GetWindowLongPtrW.restype = ctypes.c_longlong
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.InvalidateRect.restype = wintypes.BOOL
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_longlong
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.CreateMenu.restype = wintypes.HMENU
    user32.CreateMenu.argtypes = []
    # 弹出菜单必须用 CreatePopupMenu（不是 CreateMenu 的菜单栏类型），
    # 否则 TrackPopupMenu 会把菜单渲染成一块空白。
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.CreatePopupMenu.argtypes = []
    # 关键：TrackPopupMenu 只有 7 个参数
    #   (HMENU hMenu, UINT uFlags, int x, int y, int nReserved, HWND hWnd, RECT *lpRect)
    # 之前这里多写了一个 c_int（8 个 argtypes），ctypes 会直接抛
    # "this function takes 8 arguments (7 given)"，
    # 于是每一次右键菜单（托盘 / 空白处 / 行菜单）都在调用处炸掉，
    # 表现为「右键没反应、菜单完全不弹」。
    user32.TrackPopupMenu.restype = wintypes.UINT
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    # TrackPopupMenuEx 也只有 7 个参数
    #   (HMENU, UINT, int x, int y, HWND, LPARAM, DWORD dwExOptions)
    user32.TrackPopupMenuEx.restype = wintypes.UINT
    user32.TrackPopupMenuEx.argtypes = [wintypes.HMENU, wintypes.UINT,
                                        ctypes.c_int, ctypes.c_int,
                                        wintypes.HWND, ctypes.c_void_p, wintypes.DWORD]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_ulong, wintypes.LPCWSTR]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    # ---- 补齐此前遗漏的原型 ----
    # 不声明 argtypes 时 ctypes 用 C int（32 位）传参，
    # 句柄值一旦超过 2^31 就会抛 OverflowError。
    # HWND / HDC / HMENU 这类句柄必须显式声明，否则 64 位下会随机失败。
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetMessageW.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.c_void_p]
    user32.DispatchMessageW.restype = ctypes.c_longlong
    user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PostQuitMessage.restype = None
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.ValidateRect.restype = wintypes.BOOL
    user32.ValidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.RedrawWindow.restype = wintypes.BOOL
    user32.RedrawWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p, wintypes.UINT]
    user32.AdjustWindowRectEx.restype = wintypes.BOOL
    user32.AdjustWindowRectEx.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD,
                                           wintypes.BOOL, wintypes.DWORD]
    user32.GetDpiForWindow.restype = wintypes.UINT
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForSystem.restype = wintypes.UINT
    user32.GetDpiForSystem.argtypes = []
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
        wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
        ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    user32.SetCursor.restype = wintypes.HANDLE
    user32.SetCursor.argtypes = [wintypes.HANDLE]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowTextW.restype = wintypes.BOOL
    user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.SetTimer.restype = wintypes.UINT
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_ulong, wintypes.UINT, ctypes.c_void_p]
    user32.KillTimer.restype = wintypes.BOOL
    user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_ulong]
    user32.LoadIconW.restype = wintypes.HICON
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetSysColorBrush.restype = wintypes.HBRUSH
    user32.GetSysColorBrush.argtypes = [ctypes.c_int]
    user32.GetSysColor.restype = wintypes.COLORREF
    user32.GetSysColor.argtypes = [ctypes.c_int]
    user32.BeginPaint.restype = wintypes.HDC
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.EndPaint.restype = wintypes.BOOL
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.SetCapture.restype = wintypes.HWND
    user32.SetCapture.argtypes = [wintypes.HWND]
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.ReleaseCapture.argtypes = []
    # GetCapture 返回 HWND，必须声明 restype —— 否则 64 位下句柄被截断成 32 位，
    # 与 WM_CAPTURECHANGED 的判断就会出错。
    user32.GetCapture.restype = wintypes.HWND
    user32.GetCapture.argtypes = []
    user32.TrackMouseEvent.restype = wintypes.BOOL
    user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromRect.restype = wintypes.HANDLE
    user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetKeyState.restype = ctypes.c_short
    user32.GetKeyState.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.EnableWindow.restype = wintypes.BOOL
    user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.SetFocus.restype = wintypes.HWND
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.IsDialogMessageW.restype = wintypes.BOOL
    user32.IsDialogMessageW.argtypes = [wintypes.HWND, ctypes.c_void_p]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateFontIndirectW.restype = wintypes.HGDIOBJ
    gdi32.CreateFontIndirectW.argtypes = [ctypes.c_void_p]
    gdi32.SetTextColor.restype = wintypes.COLORREF
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.SetBkMode.restype = ctypes.c_int
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetBkColor.restype = wintypes.COLORREF
    gdi32.SetBkColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.RoundRect.restype = wintypes.BOOL
    gdi32.RoundRect.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int]
    gdi32.Rectangle.restype = wintypes.BOOL
    gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    gdi32.MoveToEx.restype = wintypes.BOOL
    gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    gdi32.LineTo.restype = wintypes.BOOL
    gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.ExtTextOutW.restype = wintypes.BOOL
    # ExtTextOutW 真实签名只有 9 个参数，之前多声明了一个 c_void_p。
    # ctypes 允许多传参数，所以侥幸能跑，但属于隐患，改成严格对齐。
    gdi32.ExtTextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int,
                                  ctypes.c_void_p, ctypes.c_void_p]
    gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL
    gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.SIZE)]
    gdi32.SetPixel.restype = wintypes.COLORREF
    gdi32.SetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
    user32.FillRect.restype = ctypes.c_int
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.FrameRect.restype = ctypes.c_int
    user32.FrameRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.DrawTextW.restype = ctypes.c_int
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                  ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.PatBlt.restype = wintypes.BOOL
    gdi32.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.Ellipse.restype = wintypes.BOOL
    gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int]
    gdi32.CreatePen.restype = wintypes.HPEN
    gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
    gdi32.GetStockObject.restype = wintypes.HGDIOBJ
    gdi32.GetStockObject.argtypes = [ctypes.c_int]
    gdi32.Polygon.restype = wintypes.BOOL
    gdi32.Polygon.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.c_int]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]

    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATA)]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    comdlg32.GetOpenFileNameW.restype = wintypes.BOOL
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.c_void_p]
    comdlg32.GetSaveFileNameW.restype = wintypes.BOOL
    comdlg32.GetSaveFileNameW.argtypes = [ctypes.c_void_p]
    comdlg32.ChooseColorW.restype = wintypes.BOOL
    comdlg32.ChooseColorW.argtypes = [ctypes.POINTER(CHOOSECOLORW)]

    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]


class LOGFONTW(ctypes.Structure):
    _fields_ = [
        ('lfHeight', ctypes.c_long),
        ('lfWidth', ctypes.c_long),
        ('lfEscapement', ctypes.c_long),
        ('lfOrientation', ctypes.c_long),
        ('lfWeight', ctypes.c_long),
        ('lfItalic', wintypes.BYTE),
        ('lfUnderline', wintypes.BYTE),
        ('lfStrikeOut', wintypes.BYTE),
        ('lfCharSet', wintypes.BYTE),
        ('lfOutPrecision', wintypes.BYTE),
        ('lfClipPrecision', wintypes.BYTE),
        ('lfQuality', wintypes.BYTE),
        ('lfPitchAndFamily', wintypes.BYTE),
        ('lfFaceName', wintypes.WCHAR * 32),
    ]


# 修正 CreateFontIndirectW 原型（需在 LOGFONTW 定义之后）
gdi32.CreateFontIndirectW.restype = wintypes.HGDIOBJ
gdi32.CreateFontIndirectW.argtypes = [ctypes.POINTER(LOGFONTW)]

_init_prototypes()


# ------------------------------ 工具函数 ------------------------------
def lp_str(s):
    """把 Python 字符串转为 LPARAM 指针值
    注意：仅在缓冲区仍存活时有效（如 create_unicode_buffer 变量）。
    传临时字符串请用 send_msg_text。"""
    return ctypes.cast(ctypes.c_wchar_p(s), ctypes.c_void_p).value


# SendMessageW 的 c_void_p 变体：lparam 可直接传 c_wchar_p（调用期间缓冲区保活）
_SendMessageW_text = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p
)(('SendMessageW', user32))


def send_msg_text(hwnd, msg, wparam, s):
    """SendMessageW 且 lparam 为字符串（自动管理缓冲区生命周期）"""
    return _SendMessageW_text(hwnd, msg, wparam, ctypes.c_wchar_p(s))


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)


def rgb_hex(h):
    """#rrggbb → COLORREF"""
    h = h.lstrip('#')
    return rgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def hex_rgb(colorref):
    """COLORREF → #rrggbb"""
    return '#{:02x}{:02x}{:02x}'.format(colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF)


def winerror():
    return ctypes.get_last_error()


def get_ex_style(hwnd):
    return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)


def set_ex_style(hwnd, style):
    return user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)


def set_always_on_top(hwnd, on=True):
    """置顶（HWND_TOPMOST = -1）"""
    user32.SetWindowPos.restype = ctypes.c_bool
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    ok = user32.SetWindowPos(hwnd, ctypes.c_void_p(-1 if on else -2), 0, 0, 0, 0,
                             0x0001 | 0x0002 | 0x0010)  # SWP_NOMOVE|NOSIZE|NOACTIVATE
    if not ok:
        import sys
        print('[dingpan] SetWindowPos(TOPMOST) 失败 err=%s' % ctypes.GetLastError(),
              file=sys.stderr)
    return ok


def set_click_through(hwnd, on=True):
    """点击穿透"""
    style = get_ex_style(hwnd)
    if on:
        style |= 0x00000020  # WS_EX_TRANSPARENT
    else:
        style &= ~0x00000020
    set_ex_style(hwnd, style)


def set_window_alpha(hwnd, alpha):
    """整体透明度 0-255"""
    user32.SetLayeredWindowAttributes(hwnd, 0, max(0, min(255, int(alpha))), LWA_ALPHA)


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def clipboard_get_text():
    """读剪贴板文本；失败返回空串（不抛异常，不弹窗）"""
    if not user32.OpenClipboard(None):
        return ''
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ''
        p = kernel32.GlobalLock(h)
        if not p:
            return ''
        try:
            return ctypes.wstring_at(p) or ''
        finally:
            kernel32.GlobalUnlock(h)
    except OSError:
        return ''
    finally:
        user32.CloseClipboard()


def clipboard_set_text(text):
    """写剪贴板文本，返回是否成功"""
    data = str(text or '')
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        size = (len(data) + 1) * ctypes.sizeof(ctypes.c_wchar)
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            return False
        p = kernel32.GlobalLock(h)
        if not p:
            kernel32.GlobalFree(h)
            return False
        ctypes.memmove(p, ctypes.create_unicode_buffer(data), size)
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True
    except OSError:
        return False
    finally:
        user32.CloseClipboard()


def choose_color(hwnd, default_hex='#1c1f28'):
    """弹出系统颜色选择器；返回 (ok, '#rrggbb')"""
    cc = CHOOSECOLORW()
    cc.lStructSize = ctypes.sizeof(CHOOSECOLORW)
    cc.hwndOwner = hwnd
    try:
        cc.rgbResult = rgb_hex(str(default_hex or '#1c1f28'))
    except (ValueError, TypeError):
        cc.rgbResult = rgb_hex('#1c1f28')
    cc.lpCustColors = ctypes.cast(_CUST_COLORS, ctypes.POINTER(wintypes.DWORD))
    cc.Flags = 0x00000001 | 0x00000002 | 0x00000100   # RGBINIT | FULLOPEN | ANYCOLOR
    if not comdlg32.ChooseColorW(ctypes.byref(cc)):
        return False, hex_rgb(cc.rgbResult)
    return True, hex_rgb(cc.rgbResult)


def get_work_area(hwnd=None):
    """获取工作区（排除任务栏）"""
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if hwnd:
        mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    else:
        mon = user32.MonitorFromWindow(None, MONITOR_DEFAULTTONEAREST)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    return mi.rcWork


def work_area_for(x, y, w, h):
    """给定窗口矩形，返回它所在那块显示器的工作区（多屏安全）"""
    r = wintypes.RECT(int(x), int(y), int(x) + max(1, int(w)), int(y) + max(1, int(h)))
    try:
        mon = user32.MonitorFromRect(ctypes.byref(r), MONITOR_DEFAULTTONEAREST)
    except Exception:  # noqa: BLE001
        return get_work_area()
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return get_work_area()
    return mi.rcWork


def clamp_to_work_area(x, y, w, h, margin=6):
    """把窗口位置拉回可见区域

    规则：
    - 完全落在屏幕外（拔掉显示器 / 换了分辨率）→ 回到主屏右上角；
    - 只是部分越界 → 平移，保证左上角抓得到、右下角不出界。
    """
    wa = work_area_for(x, y, w, h)
    if wa.right <= wa.left or wa.bottom <= wa.top:
        return int(x), int(y)
    if (x + w <= wa.left or x >= wa.right
            or y + h <= wa.top or y >= wa.bottom):
        return wa.right - w - 30, wa.top + 60
    nx = max(wa.left, min(int(x), wa.right - max(80, min(w, 120))))
    ny = max(wa.top, min(int(y), wa.bottom - 40))
    return nx, ny


def snap_to_edges(x, y, w, h, snap=14):
    """拖动结束后吸附到屏幕边缘（含任务栏边界），返回吸附后的 (x, y)"""
    wa = work_area_for(x, y, w, h)
    nx, ny = int(x), int(y)
    if abs(nx - wa.left) <= snap:
        nx = wa.left
    if abs((nx + w) - wa.right) <= snap:
        nx = wa.right - w
    if abs(ny - wa.top) <= snap:
        ny = wa.top
    if abs((ny + h) - wa.bottom) <= snap:
        ny = wa.bottom - h
    return nx, ny


def window_scale(hwnd=None):
    """当前显示器缩放比例（150% → 1.5），用于让字号跟着系统缩放走"""
    dpi = 0
    try:
        if hwnd:
            dpi = int(user32.GetDpiForWindow(hwnd))
    except Exception:  # noqa: BLE001
        dpi = 0
    if not dpi:
        try:
            dpi = int(user32.GetDpiForSystem())
        except Exception:  # noqa: BLE001
            dpi = 0
    if not dpi:
        try:
            dpi = int(gdi32.GetDeviceCaps(user32.GetDC(None), 88))  # LOGPIXELSX
        except Exception:  # noqa: BLE001
            dpi = 96
    return max(0.8, min(2.0, (dpi or 96) / 96.0))


def low_level_key(vk):
    return bool(user32.GetKeyState(vk) & 0x8000)


def make_font(name, height, bold=False, italic=False):
    """创建 GDI 字体"""
    lf = LOGFONTW()
    lf.lfHeight = -abs(int(height))
    lf.lfWeight = 700 if bold else 400
    lf.lfItalic = 1 if italic else 0
    lf.lfCharSet = 134  # GB2312_CHARSET
    lf.lfQuality = 5  # CLEARTYPE_QUALITY
    lf.lfFaceName = name[:31]
    return gdi32.CreateFontIndirectW(ctypes.byref(lf))
