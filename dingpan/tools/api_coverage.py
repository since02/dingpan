#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Win32 API 覆盖审计：找出「用了但没声明 argtypes/restype」的调用。

为什么重要：
  ctypes 默认把没有声明的函数当作 `int` 返回、参数当作 C 整型。
  在 64 位系统上，HDC / HBITMAP / HMENU / HWND / HICON / HBRUSH / HGDIOBJ
  都是 64 位指针 —— 一旦返回被截断成 32 位，句柄就指向了错误的地址，
  典型表现是「画出来是花的」「菜单一弹就崩」「图标不显示」，
  而且**不报错、不崩在调用处**，极难定位。

本工具用 AST 扫出所有 `user32.X(...)` / `gdi32.X(...)` 调用，
再在运行时检查这些函数到底有没有声明 argtypes / restype。
"""
import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ⚠️ 隔离 APPDATA：测试绝不能碰用户的真实配置
import tempfile                            # noqa: E402
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpapicov_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import win32 as w32          # noqa: E402

SRC = os.path.join(ROOT, 'src', 'dingpan')
DLLS = ('user32', 'gdi32', 'shell32', 'kernel32')

# 这些函数返回值是句柄，没声明 restype 就会被截断成 32 位（高风险）
HANDLE_RET = {
    'GetDC', 'GetWindowDC', 'ReleaseDC', 'CreateCompatibleDC', 'CreateCompatibleBitmap',
    'CreateDIBSection', 'CreateBitmap', 'SelectObject', 'CreateSolidBrush',
    'CreateFontIndirectW', 'CreateFontW', 'CreatePen', 'CreateBitmap',
    'GetStockObject', 'LoadIconW', 'LoadImageW', 'LoadCursorW', 'LoadBitmapW',
    'FindWindowW', 'FindWindowExW', 'GetWindow', 'GetDlgItem', 'CreateWindowExW',
    'GetMenuItemInfoW', 'CreateMenu', 'CreatePopupMenu', 'GetSubMenu',
    'GetModuleHandleW', 'LoadLibraryW', 'GetStdHandle', 'GetDesktopWindow',
    'GetShellWindow', 'SetCapture', 'GetCapture', 'GetFocus', 'SetFocus',
    'GetParent', 'SetParent', 'GetForegroundWindow', 'GetActiveWindow',
    'MessageBoxW', 'GetMessageW', 'GetClipboardData', 'OpenClipboard',
    'SetClipboardData', 'RegisterClassW', 'FindResourceW', 'LoadResource',
    'SizeofResource', 'LockResource', 'GetIconInfo', 'CreateIconIndirect',
    'GetProcessWindowStation', 'GetThreadDesktop', 'GetDCEx', 'CreateRectRgn',
    'CreateRectRgnIndirect', 'CreatePolygonRgn', 'GetWindowLongPtrW',
    'SetWindowLongPtrW', 'SetWindowLongW', 'GetWindowLongW', 'Prop_Get',
}

FAILS = []
WARNS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra != '' else ''))
    if not cond:
        FAILS.append(name)


def warn(name, extra=''):
    print('  ! %s%s' % (name, (' — ' + str(extra)) if extra != '' else ''))
    WARNS.append(name)


def scan_calls():
    """AST 扫描：找出所有 <dll>.<Func>(...) 调用"""
    used = {}
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith('.py'):
            continue
        path = os.path.join(SRC, fn)
        with io.open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=fn)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            base = func.value
            if not isinstance(base, ast.Name):
                continue
            if base.id not in DLLS:
                continue
            used.setdefault(base.id, set()).add(func.attr)
    return used


def main():
    used = scan_calls()
    total = sum(len(v) for v in used.values())
    print('=== 扫描到 %d 个 Win32 API 调用点（%d 个不同函数）===' % (total, len(set().union(*used.values())) if used else 0))
    for dll in DLLS:
        if used.get(dll):
            print('    %-10s %d 个' % (dll, len(used[dll])))

    dlls = {'user32': w32.user32, 'gdi32': w32.gdi32,
            'shell32': w32.shell32, 'kernel32': w32.kernel32}

    print('\n=== 1. 返回句柄的函数必须有 restype（否则 64 位下被截断）===')
    bad_restype = []
    for dll, names in used.items():
        lib = dlls[dll]
        for fn in sorted(names):
            if fn not in HANDLE_RET:
                continue
            try:
                f = getattr(lib, fn)
            except AttributeError:
                bad_restype.append('%s.%s（API 不存在）' % (dll, fn))
                continue
            if getattr(f, 'restype', None) is None:
                bad_restype.append('%s.%s' % (dll, fn))
    check('所有返回句柄的 API 都声明了 restype', not bad_restype,
          '; '.join(bad_restype[:12]) if bad_restype else '共检查 %d 个' %
          len([1 for d, ns in used.items() for n in ns if n in HANDLE_RET]))

    print('\n=== 2. 用到的 API 都应有 argtypes（参数类型/宽度）===')
    no_argtypes = []
    for dll, names in used.items():
        lib = dlls[dll]
        for fn in sorted(names):
            try:
                f = getattr(lib, fn)
            except AttributeError:
                no_argtypes.append('%s.%s（API 不存在）' % (dll, fn))
                continue
            if getattr(f, 'argtypes', None) is None:
                no_argtypes.append('%s.%s' % (dll, fn))
    if no_argtypes:
        for x in no_argtypes:
            warn('未声明 argtypes：%s' % x)
        check('所有用到的 API 都声明了 argtypes', False, '%d 个未声明' % len(no_argtypes))
    else:
        check('所有用到的 API 都声明了 argtypes', True)

    print('\n=== 3. 菜单 / 图标 / 窗口 这些关键路径必须完整声明 ===')
    critical = [
        ('user32', 'CreatePopupMenu'), ('user32', 'AppendMenuW'),
        ('user32', 'TrackPopupMenu'), ('user32', 'DestroyMenu'),
        ('shell32', 'Shell_NotifyIconW'), ('user32', 'CreateWindowExW'),
        ('user32', 'RegisterClassW'), ('user32', 'SendMessageW'),
        ('user32', 'PostMessageW'), ('gdi32', 'SelectObject'),
        ('gdi32', 'CreateCompatibleDC'), ('gdi32', 'CreateCompatibleBitmap'),
        ('gdi32', 'GetDIBits'), ('user32', 'PrintWindow'),
    ]
    miss = []
    for dll, fn in critical:
        f = getattr(dlls[dll], fn, None)
        if f is None:
            miss.append('%s.%s 不存在' % (dll, fn))
        elif f.argtypes is None or f.restype is None:
            miss.append('%s.%s 声明不完整' % (dll, fn))
    check('关键路径 API 声明完整', not miss, '; '.join(miss) if miss else '共 %d 个' % len(critical))

    print('\n=== 4. 调用的 API 必须真的存在于所在的 DLL 里 ===')
    # 这是最阴的一类 bug：GetOpenFileNameW 属于 comdlg32.dll，
    # 写成 user32.GetOpenFileNameW 会在调用处抛 AttributeError，
    # 表现是「导出备份 / 从文件恢复」按钮一点就报错。
    missing_api = []
    for dll, names in used.items():
        lib = dlls[dll]
        for fn in sorted(names):
            if not hasattr(lib, fn):
                missing_api.append('%s.%s（该 API 不在这个 DLL 里）' % (dll, fn))
    check('所有调用的 API 都存在于对应 DLL', not missing_api,
          '; '.join(missing_api) if missing_api else '共 %d 个' % total)

    print('\n结果: %s' % ('全部通过' if not FAILS else
                         '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    if WARNS:
        print('提醒: %d 个 API 建议补声明（不一定是 bug，但 64 位下有风险）' % len(WARNS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
