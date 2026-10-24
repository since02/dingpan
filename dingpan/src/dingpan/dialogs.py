"""
原生对话框：输入框 / 消息框 / 文件选择
"""
import ctypes
import os
from ctypes import wintypes

from . import win32 as w32
from .win32 import user32, kernel32, comctl32, comdlg32

MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONINFORMATION = 0x00000040
MB_ICONWARNING = 0x00000030
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000

IDOK = 1
IDCANCEL = 2
IDYES = 6
IDNO = 7

# 通用对话框
OPENFILENAME = None


def message_box(title, text, kind='info'):
    """弹出消息框"""
    flags = MB_OK | MB_SETFOREGROUND
    if kind == 'error':
        flags |= MB_ICONERROR
    elif kind == 'warning':
        flags |= MB_ICONWARNING
    else:
        flags |= MB_ICONINFORMATION
    user32.MessageBoxW(None, str(text), str(title), flags)


def _make_class(name, proc):
    hinst = kernel32.GetModuleHandleW(None)
    cls = w32.WNDCLASS()
    cls.style = 0x0003  # CS_HREDRAW | CS_VREDRAW
    cls.lpfnWndProc = proc
    cls.hInstance = hinst
    cls.hCursor = user32.LoadCursorW(None, ctypes.c_wchar_p(32512))
    cls.hbrBackground = user32.GetSysColorBrush(5)
    cls.lpszClassName = name
    user32.RegisterClassW(ctypes.byref(cls))
    return hinst


class _Prompt:
    """模态输入框"""

    def __init__(self, title, prompt, default=''):
        self.title = title
        self.prompt = prompt
        self.default = default
        self.value = ''
        self.hwnd = None
        self.edit = None
        self._proc = w32.WNDPROC(self._wndproc)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == w32.WM_COMMAND:
            if wparam == IDOK:
                n = user32.GetWindowTextLengthW(self.edit)
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(self.edit, buf, n + 1)
                self.value = buf.value.strip()
                user32.DestroyWindow(hwnd)
                return 0
            if wparam == IDCANCEL:
                self.value = ''
                user32.DestroyWindow(hwnd)
                return 0
        if msg == w32.WM_CLOSE:
            self.value = ''
            user32.DestroyWindow(hwnd)
            return 0
        if msg == w32.WM_KEYDOWN:
            if wparam == w32.VK_RETURN:
                user32.PostMessageW(hwnd, w32.WM_COMMAND, IDOK, 0)
                return 0
            if wparam == w32.VK_ESCAPE:
                user32.PostMessageW(hwnd, w32.WM_COMMAND, IDCANCEL, 0)
                return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        hinst = _make_class('DingPanPrompt', self._proc)
        W, H = 400, 150
        wa = w32.get_work_area()
        x = (wa.left + wa.right) // 2 - W // 2
        y = (wa.top + wa.bottom) // 2 - H // 2
        style = w32.WS_POPUP | w32.WS_CAPTION | w32.WS_SYSMENU
        ex = w32.WS_EX_TOPMOST | w32.WS_EX_DLGMODALFRAME
        hwnd = user32.CreateWindowExW(
            ex, 'DingPanPrompt', self.title, style, x, y, W, H,
            None, None, hinst, None)
        self.hwnd = hwnd

        font = w32.make_font('Microsoft YaHei', 14)
        # 提示文本
        st = user32.CreateWindowExW(0, 'STATIC', self.prompt, w32.WS_CHILD | 0x0000,
                                    16, 16, W - 40, 20, hwnd, None, hinst, None)
        user32.SendMessageW(st, w32.WM_SETFONT, font, 1)
        # 输入框
        self.edit = user32.CreateWindowExW(
            0x00000200, 'EDIT', self.default,
            w32.WS_CHILD | w32.WS_VISIBLE | w32.WS_BORDER | w32.ES_AUTOHSCROLL,
            16, 44, W - 40, 26, hwnd, None, hinst, None)
        user32.SendMessageW(self.edit, w32.WM_SETFONT, font, 1)
        # 按钮
        ok = user32.CreateWindowExW(0, 'BUTTON', '确定',
                                    w32.WS_CHILD | w32.WS_VISIBLE | w32.BS_DEFPUSHBUTTON,
                                    W - 170, 90, 72, 28, hwnd, (IDOK), hinst, None)
        user32.SendMessageW(ok, w32.WM_SETFONT, font, 1)
        cancel = user32.CreateWindowExW(0, 'BUTTON', '取消',
                                        w32.WS_CHILD | w32.WS_VISIBLE | w32.BS_PUSHBUTTON,
                                        W - 90, 90, 72, 28, hwnd, (IDCANCEL), hinst, None)
        user32.SendMessageW(cancel, w32.WM_SETFONT, font, 1)

        user32.ShowWindow(hwnd, w32.SW_SHOW)
        user32.UpdateWindow(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(self.edit)
        user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

        msg = wintypes.MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            if msg.message == w32.WM_COMMAND and msg.wParam == IDOK:
                n = user32.GetWindowTextLengthW(self.edit)
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(self.edit, buf, n + 1)
                self.value = buf.value.strip()
                user32.DestroyWindow(hwnd)
                continue
            if msg.message == w32.WM_COMMAND and msg.wParam == IDCANCEL:
                self.value = ''
                user32.DestroyWindow(hwnd)
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        w32.gdi32.DeleteObject(font)
        return self.value


def prompt_text(title, prompt, default=''):
    return _Prompt(title, prompt, default).run()


def confirm(title, text):
    """确认框（是/否）"""
    flags = w32.MB_YESNO | MB_SETFOREGROUND | MB_TOPMOST
    r = user32.MessageBoxW(None, str(text), str(title), flags)
    return r == IDYES


# 打开文件对话框（使用 GetOpenFileNameW）
class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ('lStructSize', wintypes.DWORD),
        ('hwndOwner', wintypes.HWND),
        ('hInstance', wintypes.HINSTANCE),
        ('lpstrFilter', wintypes.LPCWSTR),
        ('lpstrCustomFilter', wintypes.LPWSTR),
        ('nMaxCustFilter', wintypes.DWORD),
        ('nFilterIndex', wintypes.DWORD),
        ('lpstrFile', wintypes.LPWSTR),
        ('nMaxFile', wintypes.DWORD),
        ('lpstrFileTitle', wintypes.LPWSTR),
        ('nMaxFileTitle', wintypes.DWORD),
        ('lpstrInitialDir', wintypes.LPCWSTR),
        ('lpstrTitle', wintypes.LPCWSTR),
        ('Flags', wintypes.DWORD),
        ('nFileOffset', wintypes.WORD),
        ('nFileExtension', wintypes.WORD),
        ('lpstrDefExt', wintypes.LPCWSTR),
        ('lCustData', ctypes.c_longlong),
        ('lpfnHook', ctypes.c_void_p),
        ('lpTemplateName', wintypes.LPCWSTR),
        ('pvReserved', ctypes.c_void_p),
        ('dwReserved', wintypes.DWORD),
        ('FlagsEx', wintypes.DWORD),
    ]


def open_file_dialog(title, filter_str='JSON 文件\0*.json\0\0'):
    buf = ctypes.create_unicode_buffer(1024)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.lpstrFilter = filter_str
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = 1024
    ofn.lpstrTitle = title
    ofn.Flags = 0x00081800  # OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
    # GetOpenFileNameW / GetSaveFileNameW 在 **comdlg32.dll**，不在 user32！
    # 写成 user32.Xxx 会抛 AttributeError → 「导出备份 / 从文件恢复」直接报错。
    if comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return buf.value
    return ''


def save_file_dialog(title, def_name, filter_str='JSON 文件\0*.json\0\0'):
    buf = ctypes.create_unicode_buffer(1024)
    buf.value = def_name
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.lpstrFilter = filter_str
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = 1024
    ofn.lpstrTitle = title
    ofn.Flags = 0x00081800 | 0x00000002  # + OFN_OVERWRITEPROMPT
    if comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
        return buf.value
    return ''


def pick_folder_dialog(title):
    """选择文件夹（IFileDialog 不依赖 COM 初始化，使用 SHBrowseForFolder 简化版）"""
    BIF_RETURNONLYFSDIRS = 0x00000001
    BIF_NEWDIALOGSTYLE = 0x00000040
    SHBrowseForFolder = ctypes.windll.shell32.SHBrowseForFolder
    SHBrowseForFolder.restype = ctypes.c_longlong
    SHBrowseForFolder.argtypes = [ctypes.c_void_p, ctypes.c_longlong, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ('hwndOwner', wintypes.HWND),
            ('pidlRoot', ctypes.c_void_p),
            ('pszDisplayName', wintypes.LPWSTR),
            ('lpszTitle', wintypes.LPCWSTR),
            ('ulFlags', wintypes.UINT),
            ('lpfn', ctypes.c_void_p),
            ('lParam', ctypes.c_longlong),
            ('iImage', ctypes.c_int),
        ]

    bi = BROWSEINFOW()
    disp = ctypes.create_unicode_buffer(260)
    bi.pszDisplayName = ctypes.cast(disp, wintypes.LPWSTR)
    bi.lpszTitle = title
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
    pidl = SHBrowseForFolder(ctypes.byref(bi), None, None, None, None)
    if not pidl:
        return ''
    try:
        import ctypes.wintypes as wt
        path = ctypes.create_unicode_buffer(260)
        SHGetPathFromIDListW = ctypes.windll.shell32.SHGetPathFromIDListW
        SHGetPathFromIDListW(pidl, ctypes.cast(path, wintypes.LPWSTR))
        return path.value
    finally:
        ctypes.windll.shell32.SHILFree(pidl)
