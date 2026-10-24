# -*- coding: utf-8 -*-
"""Win32 API 签名审计：argtypes 声明的参数个数必须和 MSDN 真实签名一致。

为什么重要：ctypes 允许「多传参数」和「少传参数」的宽松行为，
参数个数写错时往往不报错，而是把参数错位传给系统函数 →
表现成「点了没反应 / 画面错乱 / 崩溃」，极难排查。

真实历史事故：
  TrackPopupMenu 声明成 8 个参数（真实 7 个），
  于是每一次右键菜单都在调用处抛 TypeError，
  托盘菜单、空白处菜单、行菜单全部「完全不弹」。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 函数名 -> (真实签名, 真实参数个数)
REAL_SIGNATURES = {
    # ---- 菜单（右键菜单全靠这些）----
    'TrackPopupMenu': ('BOOL TrackPopupMenu(HMENU hMenu, UINT uFlags, int x, int y, '
                       'int nReserved, HWND hWnd, RECT *lpRect)', 7),
    'TrackPopupMenuEx': ('BOOL TrackPopupMenuEx(HMENU hMenu, UINT uFlags, int x, int y, '
                         'HWND hWnd, LPARAM lpParam, DWORD dwExOptions)', 7),
    'AppendMenuW': ('BOOL AppendMenuW(HMENU, UINT uFlags, UINT_PTR uIDNewItem, '
                    'LPCWSTR lpNewItem)', 4),
    'DestroyMenu': ('BOOL DestroyMenu(HMENU)', 1),
    'CreateMenu': ('HMENU CreateMenu()', 0),
    # ---- 窗口 ----
    'CreateWindowExW': ('HWND CreateWindowExW(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, '
                        'int, int, HWND, HMENU, HINSTANCE, LPVOID)', 12),
    'DefWindowProcW': ('LRESULT DefWindowProcW(HWND, UINT, WPARAM, LPARAM)', 4),
    'SetWindowLongPtrW': ('LONG_PTR SetWindowLongPtrW(HWND, int, LONG_PTR)', 3),
    'GetWindowLongPtrW': ('LONG_PTR GetWindowLongPtrW(HWND, int)', 2),
    'SetWindowPos': ('BOOL SetWindowPos(HWND, HWND, int, int, int, int, UINT)', 7),
    'GetClientRect': ('BOOL GetClientRect(HWND, LPRECT)', 2),
    'GetWindowRect': ('BOOL GetWindowRect(HWND, LPRECT)', 2),
    'AdjustWindowRectEx': ('BOOL AdjustWindowRectEx(LPRECT, DWORD, BOOL, DWORD)', 4),
    'FillRect': ('int FillRect(HDC, LPCRECT, HBRUSH)', 3),
    'FrameRect': ('int FrameRect(HDC, LPCRECT, HBRUSH)', 3),
    'DrawTextW': ('int DrawTextW(HDC, LPCWSTR, int, LPRECT, UINT)', 5),
    'SetWindowTextW': ('BOOL SetWindowTextW(HWND, LPCWSTR)', 2),
    'GetWindowTextW': ('int GetWindowTextW(HWND, LPWSTR, int)', 3),
    'GetWindowTextLengthW': ('int GetWindowTextLengthW(HWND)', 1),
    'RegisterClassW': ('ATOM RegisterClassW(const WNDCLASSW*)', 1),
    'ClientToScreen': ('BOOL ClientToScreen(HWND, LPPOINT)', 2),
    'ShowWindow': ('BOOL ShowWindow(HWND, int)', 2),
    'UpdateWindow': ('BOOL UpdateWindow(HWND)', 1),
    'IsWindowVisible': ('BOOL IsWindowVisible(HWND)', 1),
    'GetClassNameW': ('int GetClassNameW(HWND, LPWSTR, int)', 3),
    'GetWindow': ('HWND GetWindow(HWND, UINT)', 2),
    'RedrawWindow': ('BOOL RedrawWindow(HWND, HDC, HRGN, UINT)', 4),
    'SetForegroundWindow': ('BOOL SetForegroundWindow(HWND)', 1),
    'GetCursorPos': ('BOOL GetCursorPos(LPPOINT)', 1),
    'SetCursor': ('HCURSOR SetCursor(HCURSOR)', 1),
    'SetCapture': ('HWND SetCapture(HWND)', 1),
    'ReleaseCapture': ('BOOL ReleaseCapture()', 0),
    'EnableWindow': ('BOOL EnableWindow(HWND, BOOL)', 2),
    'SetFocus': ('HWND SetFocus(HWND)', 1),
    'SetTimer': ('UINT_PTR SetTimer(HWND, UINT_PTR, UINT, VOID*)', 4),
    'KillTimer': ('BOOL KillTimer(HWND, UINT_PTR)', 2),
    'GetSystemMetrics': ('int GetSystemMetrics(int)', 1),
    'MapVirtualKeyW': ('UINT MapVirtualKeyW(UINT, UINT)', 2),
    'MessageBoxW': ('int MessageBoxW(HWND, LPCWSTR, LPCWSTR, UINT)', 4),
    'LoadIconW': ('HICON LoadIconW(HINSTANCE, LPCWSTR)', 2),
    'LoadCursorW': ('HCURSOR LoadCursorW(HINSTANCE, LPCWSTR)', 2),
    'LoadImageW': ('HANDLE LoadImageW(HINSTANCE, LPCWSTR, UINT, int, int, UINT)', 6),
    'GetSysColorBrush': ('HBRUSH GetSysColorBrush(int)', 1),
    'SetLayeredWindowAttributes': ('BOOL SetLayeredWindowAttributes(HWND, COLORREF, BYTE, DWORD)', 4),
    'UpdateLayeredWindow': ('BOOL UpdateLayeredWindow(HWND, HDC, POINT*, SIZE*, HDC, POINT*, '
                            'DWORD, BLENDFUNCTION*, DWORD)', 9),
    'SendMessageW': ('LRESULT SendMessageW(HWND, UINT, WPARAM, LPARAM)', 4),
    'PostMessageW': ('BOOL PostMessageW(HWND, UINT, WPARAM, LPARAM)', 4),
    'RegisterHotKey': ('BOOL RegisterHotKey(HWND, int, UINT, UINT)', 4),
    'UnregisterHotKey': ('BOOL UnregisterHotKey(HWND, int)', 2),
    'IsDialogMessageW': ('BOOL IsDialogMessageW(HWND, LPMSG)', 2),
    'FindWindowW': ('HWND FindWindowW(LPCWSTR, LPCWSTR)', 2),
    'TrackMouseEvent': ('BOOL TrackMouseEvent(LPTRACKMOUSEEVENT)', 1),
    'MonitorFromWindow': ('HMONITOR MonitorFromWindow(HWND, DWORD)', 2),
    'MonitorFromRect': ('HMONITOR MonitorFromRect(LPCRECT, DWORD)', 2),
    'GetMonitorInfoW': ('BOOL GetMonitorInfoW(HMONITOR, LPMONITORINFO)', 2),
    'OpenClipboard': ('BOOL OpenClipboard(HWND)', 1),
    'CloseClipboard': ('BOOL CloseClipboard()', 0),
    'EmptyClipboard': ('BOOL EmptyClipboard()', 0),
    'GetClipboardData': ('HANDLE GetClipboardData(UINT)', 1),
    'SetClipboardData': ('HANDLE SetClipboardData(UINT, HANDLE)', 2),
    # ---- GDI ----
    'CreateCompatibleDC': ('HDC CreateCompatibleDC(HDC)', 1),
    'CreateCompatibleBitmap': ('HBITMAP CreateCompatibleBitmap(HDC, int, int)', 3),
    'SelectObject': ('HGDIOBJ SelectObject(HDC, HGDIOBJ)', 2),
    'DeleteObject': ('BOOL DeleteObject(HGDIOBJ)', 1),
    'DeleteDC': ('BOOL DeleteDC(HDC)', 1),
    'BitBlt': ('BOOL BitBlt(HDC, int, int, int, int, HDC, int, int, DWORD)', 9),
    'CreateSolidBrush': ('HBRUSH CreateSolidBrush(COLORREF)', 1),
    'CreateFontIndirectW': ('HFONT CreateFontIndirectW(const LOGFONTW*)', 1),
    'SetTextColor': ('COLORREF SetTextColor(HDC, COLORREF)', 2),
    'SetBkMode': ('int SetBkMode(HDC, int)', 2),
    'SetBkColor': ('COLORREF SetBkColor(HDC, COLORREF)', 2),
    'RoundRect': ('BOOL RoundRect(HDC, int, int, int, int, int, int)', 7),
    'Rectangle': ('BOOL Rectangle(HDC, int, int, int, int)', 5),
    'MoveToEx': ('BOOL MoveToEx(HDC, int, int, LPRECT)', 4),
    'LineTo': ('BOOL LineTo(HDC, int, int)', 3),
    'ExtTextOutW': ('BOOL ExtTextOutW(HDC, int, int, UINT, LPRECT, LPCWSTR, int, LPINT, void*)', 9),
    'GetTextExtentPoint32W': ('BOOL GetTextExtentPoint32W(HDC, LPCWSTR, int, LPSIZE)', 4),
    'SetPixel': ('COLORREF SetPixel(HDC, int, int, COLORREF)', 4),
    'GetDIBits': ('int GetDIBits(HDC, HBITMAP, UINT, UINT, LPVOID, LPVOID, UINT)', 7),
    'PatBlt': ('BOOL PatBlt(HDC, int, int, int, int, HDC, int, int, DWORD)', 9),
    'Ellipse': ('BOOL Ellipse(HDC, int, int, int, int)', 5),
    'CreatePen': ('HPEN CreatePen(int, int, COLORREF)', 3),
    'GetStockObject': ('HGDIOBJ GetStockObject(int)', 1),
    'Polygon': ('BOOL Polygon(HDC, const POINT*, int)', 3),
    'CreateDIBSection': ('HBITMAP CreateDIBSection(HDC, const BITMAPINFO*, UINT, void**, '
                         'HANDLE, DWORD)', 6),
    # ---- 其它 ----
    'Shell_NotifyIconW': ('BOOL Shell_NotifyIconW(DWORD, PNOTIFYICONDATA)', 2),
    'GlobalAlloc': ('HGLOBAL GlobalAlloc(UINT, SIZE_T)', 2),
    'GlobalLock': ('HGLOBAL GlobalLock(HGLOBAL)', 1),
    'GlobalUnlock': ('BOOL GlobalUnlock(HGLOBAL)', 1),
    'GlobalFree': ('HGLOBAL GlobalFree(HGLOBAL)', 1),
    'GetOpenFileNameW': ('BOOL GetOpenFileNameW(LPOPENFILENAMEW)', 1),
    'GetSaveFileNameW': ('BOOL GetSaveFileNameW(LPOPENFILENAMEW)', 1),
    'ChooseColorW': ('BOOL ChooseColorW(LPCHOOSECOLORW)', 1),
}

FAILS = []


def main():
    path = os.path.join(ROOT, 'src', 'dingpan', 'win32.py')
    with io.open(path, encoding='utf-8') as f:
        src = f.read()

    print('=== Win32 API 签名审计（argtypes 参数个数）===')
    checked = 0
    for fn, (sig, want) in sorted(REAL_SIGNATURES.items()):
        m = re.search(r'\w+\.%s\.argtypes\s*=\s*\[([^\]]*)\]' % fn, src, re.S)
        if not m:
            continue
        checked += 1
        body = m.group(1)
        # 按顶层逗号切分（忽略括号内的逗号）
        depth = 0
        parts = []
        cur = ''
        for ch in body:
            if ch in '([{':
                depth += 1
            elif ch in ')]}':
                depth -= 1
            if ch == ',' and depth == 0:
                parts.append(cur)
                cur = ''
            else:
                cur += ch
        if cur.strip():
            parts.append(cur)
        n = len([p for p in parts if p.strip()])
        ok = (n == want)
        print('  %s %-30s 声明 %2d / 真实 %2d' % ('✓' if ok else '✗', fn, n, want))
        if not ok:
            print('      真实签名: %s' % sig)
            FAILS.append(fn)

    print('\n检查了 %d 个函数签名，错误 %d 个' % (checked, len(FAILS)))
    if FAILS:
        print('错误函数: %s' % ', '.join(FAILS))
        return 1
    print('全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
