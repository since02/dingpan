# -*- coding: utf-8 -*-
"""逐页检查设置窗口：切到每一页后统计可见子控件，定位空白页"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'src'))
# ⚠️ 隔离 APPDATA：测试绝不能碰用户的真实配置
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dppages_')

from dingpan import win32 as w32  # noqa: E402

user32 = w32.user32
PAGES = [(0, '基础设置'), (1, '自选管理'), (2, '显示字段'), (3, '样式外观'),
         (4, '备份恢复'), (5, 'WebDAV'), (6, '快捷键'), (7, '关于')]


def kill_all():
    import ctypes.wintypes as wt2
    k32 = w32.kernel32

    class PE32(ctypes.Structure):
        _fields_ = [('dwSize', wt2.DWORD), ('cntUsage', wt2.DWORD),
                    ('th32ProcessID', wt2.DWORD),
                    ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                    ('th32ModuleID', wt2.DWORD), ('cntThreads', wt2.DWORD),
                    ('th32ParentProcessID', wt2.DWORD),
                    ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt2.DWORD),
                    ('szExeFile', wt2.WCHAR * 260)]
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    e = PE32()
    e.dwSize = ctypes.sizeof(PE32)
    if k32.Process32FirstW(snap, ctypes.byref(e)):
        while True:
            if '盯盘' in e.szExeFile:
                h = k32.OpenProcess(1, False, e.th32ProcessID)
                if h:
                    k32.TerminateProcess(h, 1)
                    k32.CloseHandle(h)
            if not k32.Process32NextW(snap, ctypes.byref(e)):
                break


def enum_children(hwnd):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        txt = ctypes.create_unicode_buffer(96)
        user32.GetWindowTextW(h, txt, 96)
        r = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        out.append({'h': h, 'cls': cls.value, 'text': txt.value,
                    'vis': bool(user32.IsWindowVisible(h)),
                    'rect': (r.left, r.top, r.right, r.bottom)})
        return True
    user32.EnumChildWindows(hwnd, cb, 0)
    return out


kill_all()
time.sleep(1)
proc = subprocess.Popen([os.path.join(ROOT, 'dist', 'dingpan.exe')])
hwnd = None
t0 = time.time()
while time.time() - t0 < 20 and not hwnd:
    hwnd = user32.FindWindowW('DingPanWidget', None)
    if not hwnd:
        time.sleep(0.2)
assert hwnd, '悬浮窗未创建'
time.sleep(1.5)

user32.SendMessageW(hwnd, w32.WM_HOTKEY, 3, 0)  # 打开设置
sh = None
t0 = time.time()
while time.time() - t0 < 10 and not sh:
    sh = user32.FindWindowW('DingPanSettings', None)
    if not sh:
        time.sleep(0.2)
assert sh, '设置窗未创建'
time.sleep(1)

sr = wintypes.RECT()
user32.GetWindowRect(sh, ctypes.byref(sr))
print('设置窗 rect:', (sr.left, sr.top, sr.right, sr.bottom))

NAV = {'基础设置', '自选管理', '显示字段', '样式外观', '备份恢复',
       'WebDAV', '快捷键', '关于', '保存设置', '关闭'}

MARK = {'基础设置': '行情数据源', '自选管理': '新建分组', '显示字段': '可选字段',
        '样式外观': '背景不透明度', '备份恢复': '本地备份', 'WebDAV': 'WebDAV 服务器地址',
        '快捷键': '窗口内快捷键', '关于': '配置位置'}
bad = []
for pid, name in PAGES:
    # 导航按钮的控件 ID 是 8000+pid（独立 ID 段，避免和列表框等撞号）
    user32.PostMessageW(sh, 0x0111, 8000 + pid, 0)  # WM_COMMAND：点导航
    time.sleep(0.5)
    kids = enum_children(sh)
    content = [k for k in kids if k['vis'] and k['text'] not in NAV and k['cls'] != 'Static']
    labels = [k for k in kids if k['vis'] and k['cls'] == 'Static' and k['text'].strip()]
    # 只统计位于内容区（x > 侧栏宽度）的控件
    in_content = [k for k in content + labels if k['rect'][0] >= sr.left + 145]
    mark = MARK.get(name, '')
    hit = any(mark in k['text'] for k in in_content) if mark else True
    if len(in_content) < 3 or not hit:
        bad.append(name)
    print('\n== %s (pid=%d) ==  页标识「%s」%s' % (name, pid, mark, '命中' if hit else '未命中!'))
    print('   可见控件总数: %d（内容区 %d）' % (len([k for k in kids if k['vis']]), len(in_content)))
    for k in in_content[:12]:
        print('     %-22s %-28s %s' % (k['cls'][:22], k['text'][:28].replace('\n', ' '),
                                       (k['rect'][0] - sr.left, k['rect'][1] - sr.top)))

print('\n空白/异常页:', bad if bad else '无')
kill_all()
