"""易用性 / 省资源相关自检

覆盖：休市降频、隐藏时停刷新、边缘吸附、位置回收、键盘滚动、日志轮转、滚动条绘制。
全部进程内验证，不依赖真实鼠标注入。
"""
import datetime
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpux_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan.app import App, log_exception, crash_log_path   # noqa: E402
from dingpan import win32 as w32                             # noqa: E402
from dingpan import quotes as qmod                              # noqa: E402

results = []


def check(name, ok, extra=''):
    results.append(bool(ok))
    print('  %s %s%s' % ('✓' if ok else '✗', name, (' — ' + str(extra)) if extra else ''))


def pump(app, ms):
    import ctypes
    import time
    from ctypes import wintypes
    end = time.time() + ms / 1000.0
    msg = wintypes.MSG()
    while time.time() < end:
        while w32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            w32.user32.TranslateMessage(ctypes.byref(msg))
            w32.user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)


def main():
    print('=== 1. 交易时段判断 ===')
    t = datetime.datetime(2026, 10, 22, 10, 0)      # 周四 10:00
    check('工作日盘中 → 交易中', App.market_open(t))
    check('午休 12:00 → 休市', not App.market_open(t.replace(hour=12, minute=0)))
    check('收盘后 15:30 → 休市', not App.market_open(t.replace(hour=15, minute=30)))
    check('集合竞价 09:20 → 交易中', App.market_open(t.replace(hour=9, minute=20)))
    sat = datetime.datetime(2026, 10, 24, 10, 0)    # 周六
    check('周末 → 休市', not App.market_open(sat))

    print('=== 2. 屏幕位置回收 / 吸附 ===')
    wa = w32.work_area_for(100, 100, 400, 380)
    x, y = w32.clamp_to_work_area(wa.right + 500, wa.bottom + 500, 400, 380)
    check('完全在屏幕外 → 拉回可见区',
          wa.left <= x < wa.right and wa.top <= y < wa.bottom, (x, y))
    x2, y2 = w32.clamp_to_work_area(wa.right - 50, wa.top + 10, 400, 380)
    check('部分越界 → 至少留 120px 可点', x2 <= wa.right - 120, x2)
    sx, sy = w32.snap_to_edges(wa.right - 400 - 6, wa.top + 5, 400, 380)
    check('靠近右边 → 吸附', sx == wa.right - 400, sx)
    check('靠近顶部 → 吸附', sy == wa.top, sy)

    app = App()
    app.cfg['refreshInterval'] = 1500

    # 用计数器替代真实网络：
    #   1) 消除网络延迟造成的断言抖动（原来靠 _fetching 猜，1/10 会假失败）
    #   2) 精确判断「到底有没有发出请求」，而不是间接看标志位
    calls = []
    orig_fetch = qmod.fetch_quotes

    def _fake_fetch(codes, source, custom_spec=None):
        calls.append(list(codes))
        return {'ok': True, 'data': {}}

    qmod.fetch_quotes = _fake_fetch
    app.create_window()
    try:
        try:
            print('=== 3. 隐藏时停刷新 ===')
            app.set_visible(False)
            check('窗口已隐藏', not w32.user32.IsWindowVisible(app.hwnd))
            app._fetching = False
            app._next_fetch = 0
            n_before = len(calls)
            app._wndproc(app.hwnd, w32.WM_TIMER, app._timer_id, 0)
            pump(app, 400)
            check('隐藏后定时器不再拉数据', len(calls) == n_before,
                  '新增请求 %d 次' % (len(calls) - n_before))

            app._fetching = False
            n_before = len(calls)
            app.set_visible(True)
            check('重新显示后窗口可见', bool(w32.user32.IsWindowVisible(app.hwnd)))
            pump(app, 600)
            check('重新显示立刻刷新一次', len(calls) > n_before,
                  '新增请求 %d 次' % (len(calls) - n_before))

            print('=== 4. 休市降频 ===')
            app._fetching = False
            app._next_fetch = __import__('time').time() + 30
            n_before = len(calls)
            app._wndproc(app.hwnd, w32.WM_TIMER, app._timer_id, 0)
            pump(app, 400)
            check('未到间隔 → 跳过本次刷新', len(calls) == n_before,
                  '新增请求 %d 次' % (len(calls) - n_before))

            app._fetching = False
            app._next_fetch = 0
            n_before = len(calls)
            app._wndproc(app.hwnd, w32.WM_TIMER, app._timer_id, 0)
            pump(app, 500)
            check('到点 → 正常刷新', len(calls) > n_before,
                  '新增请求 %d 次' % (len(calls) - n_before))
        finally:
            # 桩只覆盖「隐藏时停刷新 / 休市降频」这两节，结束立即还原真实网络函数，
            # 免得后面的用例把假桩当成原函数存回去
            qmod.fetch_quotes = orig_fetch

        print('=== 5. 键盘滚动跟随 ===')
        app.widget._visible_rows = 5
        app.widget.max_scroll = 10
        app.widget.scroll = 0
        app.widget.ensure_visible(8)
        check('选中第 9 行 → 自动滚动', app.widget.scroll == 4, app.widget.scroll)
        app.widget.ensure_visible(1)
        check('回到第 2 行 → 滚回顶部', app.widget.scroll == 1, app.widget.scroll)

        print('=== 6. 滚动条绘制 ===')
        app.cfg['fontSize'] = 13
        app.widget.cfg = app.cfg
        app.cfg['groups'][0]['stocks'] = [
            {'code': 'sz%06d' % i, 'name': '测试%d' % i} for i in range(30)]
        app.widget.paint()
        check('行数超出时 max_scroll > 0', app.widget.max_scroll > 0, app.widget.max_scroll)
        lay = app.widget._lay
        ok = lay is not None
        if ok:
            import ctypes as C
            w, h = app.widget.client_size()

            def thumb_rows():
                """统计「滚动条列(w-3) 与 参考列(w-6) 颜色不同」的行，
                只统计行区（跳过底部缩放提示与边框）"""
                buf = C.string_at(lay['cbits'].value, w * h * 4)
                y_from = app.widget._rows_top
                y_to = min(h - 8, y_from + app.widget.body_h)
                out = []
                for yy in range(max(0, y_from), max(0, y_to)):
                    a = buf[((yy * w) + (w - 3)) * 4:((yy * w) + (w - 3)) * 4 + 3]
                    b = buf[((yy * w) + (w - 6)) * 4:((yy * w) + (w - 6)) * 4 + 3]
                    if a != b:
                        out.append(yy)
                return out

            rows = thumb_rows()
            check('右侧确实画了滚动条', 18 <= len(rows) <= max(20, app.widget.body_h // 2),
                  '%d 行（行区高 %d）' % (len(rows), app.widget.body_h))
            top_before = rows[0] if rows else 0
            app.widget.scroll = app.widget.max_scroll
            app.widget.paint()
            rows2 = thumb_rows()
            check('滚动后滑块位置跟着下移',
                  bool(rows2) and rows2[0] > top_before,
                  '%d → %d' % (top_before, rows2[0] if rows2 else -1))
            app.cfg['groups'][0]['stocks'] = app.cfg['groups'][0]['stocks'][:2]
            app.widget.paint()
            check('行数装得下时没有滚动条', not thumb_rows(), '%d 行' % len(thumb_rows()))

        print('=== 7. 崩溃日志轮转 ===')
        p = crash_log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(b'x' * (200 * 1024))
        try:
            raise ValueError('测试异常')
        except ValueError as e:
            log_exception('rotation-test', e)
        check('超过 192KB 自动轮转出 .old',
              os.path.exists(p + '.old') and os.path.getsize(p) < 8192,
              '%d B / old %d B' % (os.path.getsize(p), os.path.getsize(p + '.old')))

        print('=== 8. 行情快照（启动即显示 / 不增长）===')
        from dingpan import storage
        storage.QuoteSnapshot.clear()
        quotes = {'sh600519': {'code': 'sh600519', 'name': '贵州茅台', 'price': 1688.0,
                               'prevClose': 1650.0, 'change': 38.0, 'changePct': 2.3,
                               'time': '2026-10-22 15:00:00', 'extra': 'x' * 500}}
        check('首次写入成功', storage.QuoteSnapshot.save(quotes))
        got, at = storage.QuoteSnapshot.load()
        check('能读回并保留关键字段',
              got.get('sh600519', {}).get('price') == 1688.0 and got['sh600519']['name'] == '贵州茅台',
              at)
        check('无效字段被裁掉（体积可控）', 'extra' not in got['sh600519'])
        size1 = os.path.getsize(storage.QuoteSnapshot.file())
        check('内容没变时不重复写盘', not storage.QuoteSnapshot.save(quotes), '%d B' % size1)
        quotes['sh600519']['price'] = 1700.0
        check('内容变了才写', storage.QuoteSnapshot.save(quotes))
        check('文件体积始终很小（30 只 < 8KB）',
              os.path.getsize(storage.QuoteSnapshot.file()) < 8192,
              '%d B' % os.path.getsize(storage.QuoteSnapshot.file()))
        app2 = App()
        check('新实例启动即用缓存填满界面',
              app2.widget.quotes.get('sh600519', {}).get('price') == 1700.0,
              app2.widget.status_text)
        check('缓存状态点用强调色（不冒充实时）', app2.widget.status_warn is True)
        app2.widget.release_fonts()

        print('=== 9. 失败退避 ===')
        old_open = App.market_open
        App.market_open = staticmethod(lambda now=None: True)
        try:
            app._fail_count = 0
            check('交易时段正常间隔不限速', app._refresh_gap() == 0)
            gaps = []
            for n in (1, 2, 3, 4, 5, 9):
                app._fail_count = n
                gaps.append(int(app._refresh_gap()))
            check('连续失败逐级退避并封顶 60 秒',
                  gaps == [10, 20, 40, 60, 60, 60], gaps)
            app._fail_count = 0
        finally:
            App.market_open = old_open
        app._fail_count = 0
        App.market_open = staticmethod(lambda now=None: False)
        try:
            check('休市间隔放宽到 5 分钟', int(app._refresh_gap()) == 300)
        finally:
            App.market_open = old_open
        app._fail_count = 0

        print('=== 10. 批量添加 / 代码解析 ===')
        check('混输解析（空格/逗号/分号/港股）',
              qmod.parse_codes('600519 000001, sz300750; 00700') ==
              ['sh600519', 'sz000001', 'sz300750', 'hk00700'])
        check('剪贴板文本里捞代码', qmod.extract_codes(
            '自选：贵州茅台(600519.SH)、平安银行 000001、腾讯 hk00700、单号 2023102212345678') ==
              ['sh600519', 'sz000001', 'hk00700'])
        real_fetch = qmod.fetch_quotes
        from dingpan import dialogs as dlg
        real_mb = dlg.message_box
        dlg.message_box = lambda *a, **k: None      # 测试里不要弹模态框
        qmod.fetch_quotes = lambda codes, src='tencent', custom_spec=None: {
            'ok': True, 'source': 'tencent', 'fallback': False,
            'data': {c: {'code': c, 'name': 'N-' + c[-3:], 'price': 10.0} for c in codes}}
        app.refresh = lambda: None
        try:
            app.cfg['groups'][0]['stocks'] = [{'code': 'sh600000', 'name': '浦发银行'}]
            app.cfg['activeGroupId'] = app.cfg['groups'][0]['id']
            n = app._add_codes(['sh600000', 'sz000001', 'sh600519'])
            codes = [s['code'] for s in app.cfg['groups'][0]['stocks']]
            check('一次添加多只（重复的自动跳过）', n == 2, codes)
            check('名称已回填', app.cfg['groups'][0]['stocks'][1].get('name') == 'N-001')
            qmod.fetch_quotes = lambda codes, src='tencent', custom_spec=None: {
                'ok': True, 'source': 'tencent', 'data': {}}
            check('全都无效时不误加', app._add_codes(['sh600001']) == 0)
        finally:
            qmod.fetch_quotes = real_fetch
            dlg.message_box = real_mb

        print('=== 11. 行顺序调整 ===')
        app.cfg['groups'][0]['stocks'] = [{'code': 'sh60000%d' % i, 'name': 'S%d' % i}
                                         for i in range(4)]
        app.widget.selected = 0
        app._move_stock(1, -1)
        order = [s['code'] for s in app.cfg['groups'][0]['stocks']]
        check('上移交换相邻两行', order[:2] == ['sh600001', 'sh600000'], order)
        app._pin_stock(2, True)
        order = [s['code'] for s in app.cfg['groups'][0]['stocks']]
        check('置顶移到第一位', order[0] == 'sh600002', order)
        app._pin_stock(0, False)
        order = [s['code'] for s in app.cfg['groups'][0]['stocks']]
        check('置底移到末位', order[-1] == 'sh600002', order)
        app._copy_all_codes()
        clip = w32.clipboard_get_text()
        check('复制全部代码到剪贴板', clip.count('\n') == 3 and clip.startswith('sh'), clip.replace('\n', '|'))

        print('=== 12. 配置损坏自愈 ===')
        import json as _json
        import shutil as _shutil
        d = storage.backup_dir()
        os.makedirs(d, exist_ok=True)
        good = _json.loads(_json.dumps(app.cfg))
        good['groups'] = [{'id': 'g1', 'name': '我的自选',
                           'stocks': [{'code': 'sh600519', 'name': '贵州茅台'}]}]
        good['activeGroupId'] = 'g1'
        storage.save_auto_backup(good)
        with open(storage.config_path(), 'w', encoding='utf-8') as f:
            f.write('{坏掉的 json,,')
        healed = storage.load_config()
        check('损坏的配置 → 从自动备份恢复自选',
              [s['code'] for s in healed['groups'][0]['stocks']] == ['sh600519'],
              healed['groups'][0].get('name'))
        check('留下 .bad 证据文件', os.path.exists(storage.config_path() + '.bad'))
        os.remove(storage.config_path() + '.bad')
        # 没有备份时不能崩，退回默认配置
        os.remove(os.path.join(d, storage.AUTO_BACKUP_FILE))
        with open(storage.config_path(), 'w', encoding='utf-8') as f:
            f.write('[]')
        try:
            fallback = storage.load_config()
            ok = isinstance(fallback, dict) and bool(fallback.get('groups'))
        except Exception:  # noqa: BLE001
            ok = False
        check('无备份时安全退回默认配置', ok)
        _shutil.rmtree(d, ignore_errors=True)
    finally:
        app._cleanup()

    print('\n结果: %d/%d 通过' % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
