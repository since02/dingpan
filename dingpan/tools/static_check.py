# -*- coding: utf-8 -*-
"""静态检查：不开窗口、不截图，直接扫源码找「结构性错误」。

这些检查捕捉的是「改了设置却没生效 / 点一下就跳页 / 点了没反应」这类
反复回归的根因，比截图靠谱得多。
"""
import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src', 'dingpan')

FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + extra) if extra else ''))
    if not cond:
        FAILS.append(name)


def read(name):
    with io.open(os.path.join(SRC, name), encoding='utf-8') as f:
        return f.read()


def read_tool(name):
    with io.open(os.path.join(ROOT, 'tools', name), encoding='utf-8') as f:
        return f.read()


def main():
    app = read('app.py')
    st = read('settings.py')
    wid = read('widget.py')
    w32 = read('win32.py')

    print('=== 1. 控件 ID 唯一性（撞号 = 点一下跳页）===')
    # 找出所有 _ctl(..., cid=N) 里显式指定的 ID
    ids = []
    for m in re.finditer(r'_ctl\([^)]*?,\s*(\d+)\)', st, re.S):
        ids.append(int(m.group(1)))
    dup = sorted({i for i in ids if ids.count(i) > 1})
    check('设置页显式控件 ID 无重复', not dup, '重复: %s' % dup)

    # 导航按钮 ID 段必须和 pages_check.py 里用的保持一致
    pc = read_tool('pages_check.py')
    check('pages_check 用的导航 ID 与设置页一致（8000+pid）',
          '8000 + pid' in pc and 'cid=8000 + pid' in st)

    # 导航按钮必须用独立 ID 段
    check('导航按钮使用 8000+pid 独立 ID 段',
          'cid=8000 + pid' in st)
    check('_on_command 按 8000 段识别导航',
          re.search(r'8000\s*<=\s*cid\s*<\s*8000', st) is not None)

    # 自动分配 ID 的起点不能和显式 ID 段冲突
    m = re.search(r'_auto_cid\s*=\s*(\d+)', st)
    start = int(m.group(1)) if m else -1
    check('自动 ID 起点不与显式 ID 冲突', start > 0 and not any(
        start <= i <= start + 500 for i in ids),
        '起点 %d，显式 ID: %s' % (start, sorted(set(ids))[:12]))

    print('\n=== 2. 窗口类只注册一次（重复注册 = 旧回调 = 保存后打不开）===')
    check('设置窗口类有「只注册一次」保护',
          '_SETTINGS_CLASS_READY' in st and '_SETTINGS_CLASS_READY = True' in st)
    check('设置窗口用模块级常驻窗口过程',
          '_SETTINGS_WNDPROC' in st)
    check('设置窗口按 hwnd 查实例', '_SETTINGS_INSTANCES' in st)
    check('销毁时从登记表移除', '_SETTINGS_INSTANCES.pop' in st)
    check('不再逐实例 SetWindowLongPtrW 覆盖窗口过程',
          'GWL_WNDPROC' not in st)
    check('托盘宿主窗口类只注册一次', '_TRAY_HOST_READY' in app)
    check('托盘宿主用模块级常驻窗口过程', '_TRAY_HOST_PROC' in app)

    print('\n=== 3. 弹出菜单必须有「可激活的 owner」===')
    check('存在独立托盘宿主窗口', '_create_tray_host' in app)
    check('托盘图标挂在宿主窗口上（不是 NOACTIVATE 悬浮窗）',
          re.search(r'nid\.hWnd\s*=\s*self\.tray_host', app) is not None)
    # 宿主窗口的 CreateWindowExW 调用里不能带 WS_EX_NOACTIVATE
    m = re.search(r'CreateWindowExW\(([^)]*?)\)\s*\n\s*return hwnd', app, re.S)
    host_call = m.group(1) if m else ''
    check('宿主窗口创建时没有 WS_EX_NOACTIVATE',
          'WS_EX_NOACTIVATE' not in host_call, host_call[:80].replace('\n', ' '))
    check('弹出菜单统一走 _show_popup（含 SetForegroundWindow + WM_NULL）',
          app.count('_show_popup(') >= 4 and 'PostMessageW(owner, w32.WM_NULL' in app)
    # TrackPopupMenu 只能出现在 _show_popup 内部
    tp = [m.start() for m in re.finditer(r'user32\.TrackPopupMenu\(', app)]
    sp = app.find('def _show_popup')
    check('TrackPopupMenu 只在 _show_popup 内出现',
          len(tp) == 1 and sp < tp[0] < app.find('\ndef ', sp + 10))

    print('\n=== 4. 托盘通知码（V4 的事件在 LOWORD(lParam)）===')
    check('win32 定义了 NIN_POPUPOPEN', 'NIN_POPUPOPEN' in w32)
    check('win32 定义了 NIN_SELECT', 'NIN_SELECT' in w32)
    check('托盘回调识别 NIN_POPUPOPEN', 'NIN_POPUPOPEN' in app)
    check('托盘回调识别 NIN_SELECT', 'NIN_SELECT' in app)
    check('托盘回调统一走 _on_tray_notify', '_on_tray_notify' in app)

    print('\n=== 5. 双击 = 隐藏悬浮窗 ===')
    m = re.search(r'def _on_dblclick\(self.*?\n(?=    def )', app, re.S)
    body = m.group(0) if m else ''
    check('_on_dblclick 存在', bool(body))
    check('双击无条件隐藏（不因点在行上而改变行为）',
          'set_visible(False)' in body and '_open_quote' not in body)
    check('补了标题栏双击 WM_NCLBUTTONDBLCLK', 'WM_NCLBUTTONDBLCLK' in app)
    check('win32 定义了 WM_NCLBUTTONDBLCLK', 'WM_NCLBUTTONDBLCLK' in w32)
    check('行右键菜单仍保留「打开行情页」', "'打开行情页'" in app)

    print('\n=== 6. 名称 / 代码 独立开关 + 独立列 ===')
    check('配置里有 showName', 'showName' in read('storage.py'))
    check('配置里有 showCode', 'showCode' in read('storage.py'))
    check('配置里有 showTableHead', 'showTableHead' in read('storage.py'))
    check('配置里有 showStatus', 'showStatus' in read('storage.py'))
    check('widget 有列显示方案 col_plan', 'def col_plan' in wid)
    check('列宽计算走 col_plan', 'self.col_plan()' in wid)
    check('绘制走 col_plan', 'eff, mode = self.col_plan()' in wid)
    check('「代码」可作为独立列', "('code', '代码'" in wid)
    check('名称列支持仅名称 / 仅代码 / 两者',
          "mode == 'both'" in wid and "mode == 'name'" in wid and "mode == 'code'" in wid)

    print('\n=== 7. 表头 / 状态栏可独立隐藏 ===')
    check('表头绘制受 showTableHead 控制', "showTableHead" in wid)
    check('状态栏绘制受 showStatus 控制', "showStatus" in wid)
    check('状态栏高度随开关变化', 'status_h = max(18' in wid and "else 0" in wid)
    check('行高随「名称两行/单行」变化', 'name_row_two_line' in wid)

    print('\n=== 8. 设置页控件操作正确性 ===')
    # 显示字段页 v1.0.18 改成「单列表 + [√] 勾选 + 拖动排序」
    check('字段列表用文本前缀表示勾选',
          'FIELD_MARK_ON' in st and 'FIELD_MARK_OFF' in st)
    check('字段列表支持拖动排序', '_move_field_row' in st and '_move_field_row(' in st)
    check('字段顺序单独存（未勾选的字段也保留位置）',
          "fieldOrder" in st)
    check('_get_selected_columns 只取勾选了的', 'FIELD_MARK_ON' in st)
    check('「恢复默认」用 DEFAULT_CONFIG',
          "storage.DEFAULT_CONFIG.get('columns')" in st)
    # ⚠️ 绕过 _ctl 直接创建的控件必须 _track，否则会显示在所有设置页上
    check('自建列表控件登记到当前页', 'self._track(h)' in st)

    print('\n=== 10. 弹出菜单类型（用 CreateMenu 会渲染成空白）===')
    # MSDN 契约：TrackPopupMenu 的 hMenu 必须由 CreatePopupMenu 创建。
    # 传 CreateMenu（菜单栏类型）→ 菜单项确实加进去了（GetMenuItemCount 正常），
    # 但弹出来是一片空白，历史上踩过两次。
    src_all = ''
    for f in sorted(os.listdir(SRC)):
        if f.endswith('.py'):
            src_all += read(f)
    bad = re.findall(r'\bCreateMenu\s*\(', src_all)
    check('源码中没有 CreateMenu( 调用（必须用 CreatePopupMenu）',
          not bad, '发现 %d 处: %s' % (len(bad), bad[:5]))
    check('win32 声明了 CreatePopupMenu', 'CreatePopupMenu' in w32)
    n_popup = src_all.count('CreatePopupMenu(')
    n_track = src_all.count('TrackPopupMenu(')
    check('建菜单的地方都用 CreatePopupMenu',
          n_popup >= 1 and n_popup >= n_track,
          'CreatePopupMenu %d 处 / TrackPopupMenu %d 处' % (n_popup, n_track))

    print('\n=== 11. 隐藏后停刷新（不能只靠 KillTimer）===')
    check('WM_TIMER 处理里显式判断窗口可见性',
          'IsWindowVisible(hwnd)' in app)
    ux = read_tool('ux_check.py')
    check('ux_check 用网络计数器做确定性断言（不依赖真实网络）',
          'orig_fetch' in ux and '新增请求' in ux)
    taut = re.findall(r'or True\)', ux)
    check('ux_check 没有恒真断言（or True 恒成立 = 没测）',
          not taut, '发现 %d 处' % len(taut))

    print('\n=== 12. 测试绝不能碰用户的真实配置 ===')
    # 历史事故：tools/selftest.py 的 test_config() 会真写配置文件再"复原"，
    # 而复原用的是 DEFAULT_CONFIG → 每跑一次自检就把用户的自选/样式/显示开关重置。
    # 而且它没隔离 APPDATA，直接写的是 %APPDATA%\DingPan\dingpan-config.json。
    # v1.0.22 起配置默认写在**程序目录**内 → 除了 APPDATA，还必须隔离 DINGPAN_HOME，
    # 否则测试会把配置写进真实项目目录（还会互相干扰）。
    tool_dir = os.path.join(ROOT, 'tools')
    bad_tools = []
    no_home = []
    for fn in sorted(os.listdir(tool_dir)):
        if not fn.endswith('.py'):
            continue
        src_ = read_tool(fn)
        writes = re.search(r'save_config\(|save_auto_backup\(|save_cfg\(', src_)
        if not writes:
            continue
        if 'APPDATA' not in src_:
            bad_tools.append('%s（会写配置但没隔离 APPDATA）' % fn)
        if 'DINGPAN_HOME' not in src_:
            no_home.append('%s（没隔离 DINGPAN_HOME，会写进程序目录）' % fn)
    check('会写配置的工具都隔离了 APPDATA', not bad_tools,
          '; '.join(bad_tools) if bad_tools else '已全部隔离')
    check('会写配置的工具都隔离了程序目录（DINGPAN_HOME）', not no_home,
          '; '.join(no_home) if no_home else '已全部隔离')
    # selftest 的"复原"不能用 DEFAULT_CONFIG 覆盖用户配置
    if os.path.isfile(os.path.join(tool_dir, 'selftest.py')):
        st_src = read_tool('selftest.py')
        check('selftest 的配置复原不是「用默认值覆盖用户配置」',
              'save_config(storage.deep_merge(storage.DEFAULT_CONFIG' not in st_src)

    print('\n=== 9. 语法检查（全部模块可导入）===')
    for f in sorted(os.listdir(SRC)):
        if not f.endswith('.py'):
            continue
        p = os.path.join(SRC, f)
        try:
            with io.open(p, encoding='utf-8') as fh:
                ast.parse(fh.read(), filename=f)
            ok, err = True, ''
        except SyntaxError as e:
            ok, err = False, str(e)
        check('%s 语法正确' % f, ok, err)

    print('\n结果: %d/%d 通过' % (
        0, 0) if False else '\n结果: %s' % ('全部通过' if not FAILS else
                                          '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
