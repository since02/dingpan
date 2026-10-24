#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v1.0.15 新功能的专项测试

覆盖用户这一轮提的 6 项需求：
  1) 悬浮窗大小按内容自适应
  2) 窗口任意位置可拖动（且不影响点击选中行）
  3) 悬浮窗右键菜单里有「设置」入口
  4) 显示方案：内置预设 + 自定义保存 + 切换
  5) 股票名称可指定显示几个字符
  6) 基础设置移除「显示股票名称 / 显示股票代码」，统一到「显示字段」

不注入鼠标，不截图（截图由 tools/visual_check.py 负责）。
"""
import ctypes
import io
import json
import os
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpv15_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan import storage                      # noqa: E402
from dingpan import settings as st               # noqa: E402
from dingpan.app import App                      # noqa: E402
from dingpan import widget as wid                # noqa: E402
from dingpan.win32 import user32                 # noqa: E402

FAILS = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra != '' else ''))
    if not cond:
        FAILS.append(name)


def pump(app, ms=120):
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def window_size(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.right - r.left, r.bottom - r.top


def main():
    app = App()
    app.cfg['groups'] = [{'id': 'g', 'name': '默认', 'stocks': [
        {'code': 'sh600519', 'name': '贵州茅台'},
        {'code': 'sz000001', 'name': '平安银行'},
        {'code': 'sz300750', 'name': '宁德时代'}]}]
    app.cfg['activeGroupId'] = 'g'
    app.create_window()
    app.refresh = lambda: None            # 不联网，保证测试确定性
    app.widget.quotes = {
        'sh600519': {'code': 'sh600519', 'name': '贵州茅台', 'price': 1688.0,
                     'change': 12.3, 'changePct': 0.74, 'turnover': 0.52,
                     'time': '2026-10-23 10:30:00'},
        'sz000001': {'code': 'sz000001', 'name': '平安银行', 'price': 11.86,
                     'change': -0.19, 'changePct': -1.58, 'turnover': 0.31,
                     'time': '2026-10-23 10:30:00'},
        'sz300750': {'code': 'sz300750', 'name': '宁德时代', 'price': 182.44,
                     'change': 2.54, 'changePct': 1.41, 'turnover': 0.88,
                     'time': '2026-10-23 10:30:00'},
    }
    try:
        print('=== 1. 悬浮窗大小按内容自适应 ===')
        w_cfg = app.widget
        w_cfg.cfg = app.cfg
        w_cfg._mkey = w_cfg._mval = None
        need_w, need_h = w_cfg.needed_size()
        check('能算出所需尺寸', need_w > 0 and need_h > 0, '%dx%d' % (need_w, need_h))
        app._apply_auto_size()
        pump(app, 120)
        cur_w, cur_h = window_size(app.hwnd)
        check('窗口已按内容调整到所需宽度', cur_w == need_w, '%d vs %d' % (cur_w, need_w))
        # 列宽总和应正好等于窗口宽度（不浪费也不截断）
        eff, _mode = w_cfg.col_plan()
        widths = w_cfg.column_widths(cur_w)
        check('列宽总和 = 窗口宽度 - 内边距',
              sum(widths) == cur_w - 12, '列宽合计 %d，窗口 %d' % (sum(widths), cur_w))
        # 字段变少 → 窗口变窄
        old_cols = list(app.cfg['columns'])
        app.cfg['columns'] = ['name', 'price']
        w_cfg.cfg = app.cfg
        w_cfg._mkey = w_cfg._mval = None
        app._apply_auto_size()
        pump(app, 120)
        narrow_w, _ = window_size(app.hwnd)
        check('字段变少 → 窗口变窄', narrow_w < cur_w, '%d → %d' % (cur_w, narrow_w))
        app.cfg['columns'] = old_cols
        w_cfg.cfg = app.cfg
        w_cfg._mkey = w_cfg._mval = None

        # 关掉自适应 → 尺寸不再跟着内容变
        app.cfg['autoSize'] = False
        app._apply_auto_size()
        before = window_size(app.hwnd)
        app.cfg['columns'] = ['name', 'price']
        w_cfg.cfg = app.cfg
        w_cfg._mkey = w_cfg._mval = None
        app._apply_auto_size()
        pump(app, 100)
        check('关闭自适应后尺寸不再自动变化', window_size(app.hwnd) == before,
              '%s vs %s' % (window_size(app.hwnd), before))
        app.cfg['autoSize'] = True
        app.cfg['columns'] = old_cols
        w_cfg.cfg = app.cfg
        w_cfg._mkey = w_cfg._mval = None

        print('\n=== 2. 窗口任意位置可拖动 ===')
        # hit_row 依赖绘制时算出的 rows，先画一帧（真实使用时窗口显示必然已绘制）
        app.widget.paint_now()
        pump(app, 150)
        # WM_NCHITTEST 的 lparam 是**屏幕坐标**：
        # 要测「非标题栏区域」，得传数据行所在的屏幕 y，
        # 传 0 会落在屏幕原点 → 反而命中标题栏分支。
        wr = wintypes.RECT()
        user32.GetWindowRect(app.hwnd, ctypes.byref(wr))
        row_y = w_cfg.header_h + w_cfg.tabs_h + 30
        screen_y = wr.top + row_y
        hit = app._wndproc_inner(app.hwnd, 0x0084, 0, (screen_y << 16) | (wr.left + 100))
        check('非标题栏区域返回 HTCLIENT（走自己的拖动逻辑）',
              hit == 1, 'hit=%s（1=HTCLIENT，2=HTCAPTION）' % hit)
        # 模拟：在一个数据行位置按下 → 进入拖动候选
        row_y = w_cfg.header_h + w_cfg.tabs_h + 30
        lparam = (row_y << 16) | 100
        app._on_lbutton_down(app.hwnd, lparam)
        check('在数据行位置按下 → 进入「可拖动」状态', app._drag_hwnd == app.hwnd)
        check('此时还没有判定为拖动（避免误判）', app._drag_moved is False)
        # 微小移动 → 仍不算拖动（否则单击会被误判）
        app._on_mousemove((row_y << 16) | 102)
        check('微小移动不算拖动', app._drag_moved is False)
        # 超过阈值会切到**系统原生移动**，那条路在 §7 单独验证
        # （这里会阻塞在系统的移动循环里，不能在同步测试里直接跑）
        app._drag_hwnd = None
        app._drag_moved = False
        check('纯移动位置不会关闭「自动适应」（改大小才关）',
              app.cfg.get('autoSize', True) is True,
              'autoSize=%s' % app.cfg.get('autoSize'))
        # 单纯点击（没移动）→ 仍然选中行
        app.widget.selected = -1
        app._on_lbutton_down(app.hwnd, (row_y << 16) | 100)
        app._on_lbutton_up((row_y << 16) | 100)
        check('不移动直接松开 → 仍然能选中行', app.widget.selected >= 0,
              'selected=%s' % app.widget.selected)

        print('\n=== 3. 悬浮窗右键菜单里有「设置」===')
        menu = app._build_row_menu(1)
        check('行菜单能构建', bool(menu))
        if menu:
            texts = []
            for i in range(user32.SendMessageW(menu, 0x018B, 0, 0)):
                buf = ctypes.create_unicode_buffer(256)
                user32.SendMessageW(menu, 0x0189, i, buf)   # LB-ish: 用 GetMenuString
                texts.append(buf.value)
            # GetMenuStringW 更可靠
            texts = []
            n = user32.GetMenuItemCount(menu)
            for i in range(n):
                ln = user32.GetMenuStringW(menu, i, None, 0, 0x0400)
                b = ctypes.create_unicode_buffer(ln + 1)
                user32.GetMenuStringW(menu, i, b, ln + 1, 0x0400)
                texts.append(b.value)
            check('行菜单里有「设置…」', '设置…' in texts, str(texts))
            user32.DestroyMenu(menu)
        m2 = app._build_main_menu()
        if m2:
            texts = []
            n = user32.GetMenuItemCount(m2)
            for i in range(n):
                ln = user32.GetMenuStringW(m2, i, None, 0, 0x0400)
                b = ctypes.create_unicode_buffer(ln + 1)
                user32.GetMenuStringW(m2, i, b, ln + 1, 0x0400)
                texts.append(b.value)
            check('空白处菜单里有「设置…」', '设置…' in texts, str(texts))
            user32.DestroyMenu(m2)

        print('\n=== 4. 显示方案：预设 + 自定义 + 切换 ===')
        presets = storage.DEFAULT_CONFIG.get('presets') or []
        check('内置了若干显示方案', len(presets) >= 3, '%d 个' % len(presets))
        check('每个内置方案都有名字和字段',
              all(p.get('name') and p.get('columns') for p in presets))
        obj = app.open_settings()
        pump(app, 200)
        check('设置窗口能打开', bool(obj and obj.hwnd))
        # 下拉框里有方案
        items = obj._combo_items(obj.cb_preset)
        check('方案下拉框已填充', len(items) >= 3, str(items))
        # 应用第一个方案
        obj._set_combo_sel(obj.cb_preset, 0)
        obj._apply_preset()
        pump(app, 150)
        sel = obj._get_selected_columns()
        check('应用方案后已选字段同步更新', sel == presets[0]['columns'],
              '%s vs %s' % (sel, presets[0]['columns']))
        # 保存为自定义方案
        obj._set_text(obj.ed_preset_name, '我的方案')
        obj._save_preset()
        pump(app, 100)
        mine = [p for p in (app.cfg.get('presets') or []) if p.get('name') == '我的方案']
        check('自定义方案已保存', len(mine) == 1, str(app.cfg.get('presets')))
        if mine:
            check('自定义方案记住了当前字段', mine[0]['columns'] == sel)
        items2 = obj._combo_items(obj.cb_preset)
        check('下拉框里出现了自定义方案', '我的方案' in items2, str(items2))
        # 切换到自定义方案
        idx = items2.index('我的方案')
        obj._set_combo_sel(obj.cb_preset, idx)
        obj._apply_preset()
        pump(app, 120)
        check('可以切换到自定义方案', obj._get_selected_columns() == mine[0]['columns'])
        # 删除
        obj._delete_preset()
        pump(app, 100)
        check('自定义方案已删除',
              not [p for p in (app.cfg.get('presets') or []) if p.get('name') == '我的方案'])
        # 内置方案不能删
        obj._set_combo_sel(obj.cb_preset, 0)
        obj._delete_preset()
        pump(app, 80)
        check('内置方案不会被删掉', len(obj._presets()) >= 3, str(len(obj._presets())))

        print('\n=== 5. 名称最多显示几个字符 ===')
        cfg2 = dict(app.cfg)
        cfg2['nameChars'] = 0
        w_cfg.cfg = cfg2
        check('nameChars=0 → 名称完整显示',
              w_cfg.name_display_text('贵州茅台') == '贵州茅台')
        cfg2['nameChars'] = 2
        w_cfg.cfg = cfg2
        check('nameChars=2 → 只显示 2 个字 + 省略号',
              w_cfg.name_display_text('贵州茅台') == '贵州…',
              w_cfg.name_display_text('贵州茅台'))
        cfg2['nameChars'] = 6
        w_cfg.cfg = cfg2
        check('nameChars 超过名称长度 → 不截断',
              w_cfg.name_display_text('贵州茅台') == '贵州茅台')
        # 列宽测量也要按截断后的文本
        cfg2['nameChars'] = 0
        w_cfg.cfg = cfg2
        w_cfg._mkey = w_cfg._mval = None
        w_full = w_cfg.content_width()
        cfg2['nameChars'] = 2
        w_cfg.cfg = cfg2
        w_cfg._mkey = w_cfg._mval = None
        w_short = w_cfg.content_width()
        check('名称截断后内容宽度变小', w_short < w_full, '%d → %d' % (w_full, w_short))
        cfg2['nameChars'] = 0
        w_cfg.cfg = cfg2
        w_cfg._mkey = w_cfg._mval = None

        print('\n=== 6. 基础设置不再有名称/代码开关，统一到显示字段 ===')
        src = io.open(os.path.join(ROOT, 'src', 'dingpan', 'settings.py'),
                      encoding='utf-8').read()
        check('基础设置不再创建「显示股票名称」复选框',
              "'显示股票名称'" not in src)
        check('基础设置不再创建「显示股票代码」复选框',
              "'显示股票代码'" not in src)
        check('没有残留的 cb_name / cb_code 引用',
              'cb_name' not in src and 'cb_code' not in src)
        # 显示字段页能增删名称 / 代码
        cfg3 = dict(app.cfg)
        cfg3['columns'] = ['name', 'code', 'price']
        obj.app.cfg = cfg3
        obj._load_ui()
        pump(app, 100)
        sel2 = obj._get_selected_columns()
        check('显示字段页的已选列表包含名称和代码',
              'name' in sel2 and 'code' in sel2, str(sel2))
        # 取消勾选「代码」→ 保存后 showCode 变 False
        idx_code = obj._field_order.index('code')
        obj._toggle_field_enabled(idx_code)
        pump(app, 80)
        collected = obj._collect()
        check('移除代码列 → showCode 变 False', collected.get('showCode') is False)
        check('移除代码列 → columns 里没有 code', 'code' not in collected.get('columns', []))
        check('showName 仍为 True', collected.get('showName') is True)

        # 名称字符数也被收集
        obj._set_text(obj.ed_name_chars, '3')
        collected2 = obj._collect()
        check('名称字符数被正确收集', collected2.get('nameChars') == 3,
              collected2.get('nameChars'))
        check('自动适应开关被正确收集',
              'autoSize' in collected2, collected2.get('autoSize'))

        user32.SendMessageW(obj.hwnd, 0x0010, 0, 0)   # WM_CLOSE
        pump(app, 120)

        # ================= v1.0.16 新增三项 =================
        print('\n=== 7. 拖动走系统原生移动（流畅、无重影）===')
        # 自己 SetWindowPos 跟鼠标走会每次触发 WM_SIZE → 重绘分层窗口 → 卡顿 + 重影。
        # 现在改成：超过阈值就切到 WM_NCLBUTTONDOWN + HTCAPTION，由系统搬位图。
        app2 = App()
        app2.cfg['groups'] = [{'id': 'g', 'name': '默认', 'stocks': [
            {'code': 'sh600519', 'name': '贵州茅台'}]}]
        app2.cfg['activeGroupId'] = 'g'
        app2.create_window()
        app2.refresh = lambda: None
        try:
            calls = []
            real_native = app2._begin_native_move

            def spy():
                calls.append(1)
                app2._drag_hwnd = None      # 模拟真实实现里释放自己的状态
            app2._begin_native_move = spy
            row_y = app2.widget.header_h + app2.widget.tabs_h + 30
            app2._on_lbutton_down(app2.hwnd, (row_y << 16) | 100)
            check('按下后进入待判定状态', app2._drag_hwnd == app2.hwnd)
            app2._on_mousemove((row_y << 16) | 102)     # 只移动 2px
            check('微小移动不算拖动（不打断点击）',
                  not calls and app2._drag_moved is False)
            app2._on_mousemove((row_y << 16) | 140)     # 移动 40px
            check('超过阈值 → 切换到系统原生移动',
                  bool(calls) and app2._drag_moved is True)
            check('切到原生移动后释放了自己的捕获', app2._drag_hwnd is None)
            app2._begin_native_move = real_native
            app2._on_lbutton_up((row_y << 16) | 140)

            # 真正走一次原生移动（会阻塞到鼠标松开 → 用辅助线程发 WM_LBUTTONUP）
            import threading
            app2._on_lbutton_down(app2.hwnd, (row_y << 16) | 100)
            done = []

            def release():
                time.sleep(0.25)
                user32.PostMessageW(app2.hwnd, 0x0202, 0, 0)   # WM_LBUTTONUP
                done.append(1)

            th = threading.Thread(target=release, daemon=True)
            th.start()
            app2._on_mousemove((row_y << 16) | 160)
            th.join(3)
            check('原生移动流程能正常返回（不会卡死）', bool(done),
                  'done=%s' % done)
            app2._drag_hwnd = None
        finally:
            try:
                app2._cleanup()
            except Exception:
                pass

        print('\n=== 8. 设置项改动实时预览（不用点保存）===')
        app3 = App()
        app3.cfg['groups'] = [{'id': 'g', 'name': '默认', 'stocks': [
            {'code': 'sh600519', 'name': '贵州茅台'}]}]
        app3.cfg['activeGroupId'] = 'g'
        app3.create_window()
        app3.refresh = lambda: None
        try:
            obj3 = app3.open_settings()
            pump(app3, 250)
            check('设置窗口能打开', bool(obj3 and obj3.hwnd))
            # 拖动「背景不透明度」滑块 → 悬浮窗立刻变
            obj3._set_trackbar(obj3.sb_bg, 45, 20, 100)
            obj3._preview()
            pump(app3, 120)
            check('改不透明度 → 悬浮窗立即生效（未保存）',
                  app3.widget.cfg.get('bgAlpha') == 45,
                  'bgAlpha=%s' % app3.widget.cfg.get('bgAlpha'))
            # 改字号
            # 字号已改成下拉框（滑块的刻度会被系统稀疏化，选不到 12/14）
            obj3._set_combo_sel(obj3.cb_font, 17 - 10)
            obj3._preview()
            pump(app3, 120)
            check('改字号 → 立即生效', app3.widget.cfg.get('fontSize') == 17,
                  'fontSize=%s' % app3.widget.cfg.get('fontSize'))
            # 勾掉「显示列表表头」→ 立即生效
            obj3._set_check(obj3.cb_table_head, False)
            obj3._preview()
            pump(app3, 120)
            check('关表头 → 立即生效',
                  app3.widget.cfg.get('showTableHead') is False)
            # 名称字符数
            obj3._set_text(obj3.ed_name_chars, '2')
            obj3._preview()
            pump(app3, 120)
            check('改名称字符数 → 立即生效',
                  app3.widget.cfg.get('nameChars') == 2,
                  'nameChars=%s' % app3.widget.cfg.get('nameChars'))
            # 预览不应写盘
            check('预览不会写入配置（只是内存里的效果）',
                  app3.cfg.get('bgAlpha') == 100,
                  'app.cfg bgAlpha=%s' % app3.cfg.get('bgAlpha'))

            print('\n=== 9. 涨跌颜色支持任意自定义 ===')
            items = obj3._combo_items(obj3.cb_up)
            check('上涨颜色下拉框末尾有「自定义…」',
                  items and items[-1].startswith('自定义'), str(items))
            check('预设项也都在', len(items) >= 7, '%d 项' % len(items))
            # 选一个预设
            obj3._set_combo_sel(obj3.cb_up, 0)
            check('选中预设项能取到颜色值',
                  obj3._combo_color(obj3.cb_up) == 'f6465d',
                  obj3._combo_color(obj3.cb_up))
            # 模拟选了「自定义…」并设成任意颜色
            idx = len(items) - 1
            obj3._set_combo_item_text(obj3.cb_up, idx, '自定义 #a1b2c3')
            obj3._set_combo_sel(obj3.cb_up, idx)
            check('自定义颜色能取到值',
                  obj3._combo_color(obj3.cb_up) == 'a1b2c3',
                  obj3._combo_color(obj3.cb_up))
            # 保存后能正确落盘
            collected = obj3._collect()
            check('自定义上涨颜色能被保存',
                  collected.get('upColor') == 'a1b2c3',
                  collected.get('upColor'))
            # 重新打开设置 → 自定义值能被正确选中并显示
            obj3._select_color_combo(obj3.cb_up, 'a1b2c3')
            items2 = obj3._combo_items(obj3.cb_up)
            check('重开设置能显示自定义颜色',
                  any('a1b2c3' in it for it in items2), str(items2))
            check('重开后取到的仍是自定义值',
                  obj3._combo_color(obj3.cb_up) == 'a1b2c3')
            # 预设值也要能正确选中
            obj3._select_color_combo(obj3.cb_down, '#0ecb81')
            check('预设颜色能被正确选中',
                  obj3._combo_color(obj3.cb_down) == '0ecb81',
                  obj3._combo_color(obj3.cb_down))
            user32.SendMessageW(obj3.hwnd, 0x0010, 0, 0)
            pump(app3, 120)
        finally:
            try:
                app3._cleanup()
            except Exception:
                pass

    finally:
        try:
            app._cleanup()
        except Exception:
            pass

    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


def w32_htclient():
    from dingpan import win32 as w
    return getattr(w, 'HTCLIENT', 1)


if __name__ == '__main__':
    raise SystemExit(main())
