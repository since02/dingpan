#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""备份 / 恢复 端到端测试（走真实 UI 按钮处理链路）

背景：v1.0.13 修掉了「导出备份文件 / 从文件恢复」一点就报错的真 BUG
（文件对话框 API 属于 comdlg32.dll，代码却写成 user32.GetOpenFileNameW）。
但那只验证了「按钮不再崩」，**没有验证导出的文件能不能真的导回来**。

本测试：
  1) 点「导出备份文件」→ 校验真的写出了 JSON，内容完整
  2) 改坏当前配置（删自选、改字号）
  3) 点「从文件恢复」→ 校验配置被完整还原（含分组、字段、字号）
  4) 导入一个损坏的 JSON → 校验**不会破坏现有配置**，只弹错误提示
  5) 自动本地备份：设置变动后应写出固定文件，且「配置损坏自愈」能靠它恢复
  6) 导入的备份要能正确合并默认值（老备份缺字段也不会 KeyError）

只 stub 文件对话框和模态框本身，其余走生产代码。
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

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpbackup_')

from dingpan import dialogs              # noqa: E402
from dingpan import storage              # noqa: E402
from dingpan.app import App              # noqa: E402
from dingpan import settings as st       # noqa: E402
from dingpan.win32 import user32         # noqa: E402

FAILS = []
BOXES = []


def check(name, cond, extra=''):
    print('  %s %s%s' % ('✓' if cond else '✗', name, (' — ' + str(extra)) if extra != '' else ''))
    if not cond:
        FAILS.append(name)


def pump(app, ms=150):
    msg = wintypes.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def click(app, obj, btn, cid):
    """模拟点击一个按钮：发 WM_COMMAND（BN_CLICKED）"""
    user32.SendMessageW(obj.hwnd, 0x0111, cid, btn)
    pump(app, 200)


def main():
    # 记录弹出的提示框内容（而不是真的弹出来）
    def fake_box(title, text, kind='info'):
        BOXES.append((title, text, kind))
    dialogs.message_box = fake_box
    st.dialogs.message_box = fake_box

    workdir = tempfile.mkdtemp(prefix='dpbak_file_')
    bak_path = os.path.join(workdir, 'dingpan-backup-test.json')

    # 文件对话框：只 stub 返回路径，其余逻辑走生产代码
    dialogs.save_file_dialog = lambda *a, **k: bak_path
    dialogs.open_file_dialog = lambda *a, **k: bak_path

    app = App()
    app.cfg['groups'] = [
        {'id': 'g1', 'name': '自选', 'stocks': [
            {'code': 'sh600519', 'name': '贵州茅台'},
            {'code': 'sz000001', 'name': '平安银行'}]},
        {'id': 'g2', 'name': '观察', 'stocks': [{'code': 'sz300750', 'name': '宁德时代'}]},
    ]
    app.cfg['activeGroupId'] = 'g1'
    app.cfg['fontSize'] = 15
    app.cfg['showCode'] = True
    app.create_window()

    try:
        obj = app.open_settings()
        pump(app, 200)
        check('设置窗口能打开', bool(obj and obj.hwnd))
        obj._show_page(st.P_BACKUP)
        pump(app, 150)

        print('\n=== 1. 导出备份文件 ===')
        BOXES.clear()
        click(app, obj, obj.btn_export, 9503)
        check('导出后文件存在', os.path.isfile(bak_path))
        if os.path.isfile(bak_path):
            with io.open(bak_path, encoding='utf-8') as f:
                payload = json.load(f)
            check('备份是合法 JSON 且带 app 标记', payload.get('app') == 'dingpan')
            cfg_in = payload.get('config') or {}
            check('备份里有分组和自选股',
                  len(cfg_in.get('groups') or []) == 2
                  and len(cfg_in['groups'][0]['stocks']) == 2, str(cfg_in.get('groups'))[:80])
            check('备份里有字号等样式设置', cfg_in.get('fontSize') == 15,
                  'fontSize=%s' % cfg_in.get('fontSize'))
            check('导出后弹了成功提示',
                  any('导出' in (b[1] or '') for b in BOXES), str(BOXES))

        print('\n=== 2. 改坏当前配置 ===')
        app.cfg['groups'] = []
        app.cfg['fontSize'] = 9
        app.cfg['showCode'] = False
        app.save_cfg(app.cfg)
        pump(app, 80)
        check('当前配置确实被改坏', not app.cfg.get('groups'))

        print('\n=== 3. 从文件恢复 ===')
        BOXES.clear()
        click(app, obj, obj.btn_import, 9504)
        restored = app.cfg
        check('恢复后分组回来了', len(restored.get('groups') or []) == 2,
              str(restored.get('groups'))[:80])
        check('恢复后自选股回来了',
              len((restored.get('groups') or [{}])[0].get('stocks') or []) == 2)
        check('恢复后字号回来了', restored.get('fontSize') == 15,
              'fontSize=%s' % restored.get('fontSize'))
        check('恢复后显示开关回来了', restored.get('showCode') is True,
              'showCode=%s' % restored.get('showCode'))
        check('widget 也拿到了新配置',
              app.widget.cfg is restored or app.widget.cfg.get('fontSize') == 15)
        check('恢复后弹了成功提示',
                  any('恢复' in (b[1] or '') or '导入' in (b[1] or '') for b in BOXES),
                  str(BOXES))

        print('\n=== 4. 导入损坏文件不会破坏现有配置 ===')
        BOXES.clear()
        bad = os.path.join(workdir, 'bad.json')
        with io.open(bad, 'w', encoding='utf-8') as f:
            f.write('{ 这不是合法 JSON')
        dialogs.open_file_dialog = lambda *a, **k: bad
        before_groups = json.dumps(app.cfg.get('groups'), sort_keys=True)
        click(app, obj, obj.btn_import, 9504)
        check('导入失败时弹了错误提示',
              any(b[2] == 'error' for b in BOXES), str(BOXES))
        check('导入失败没有破坏现有配置',
              json.dumps(app.cfg.get('groups'), sort_keys=True) == before_groups)

        print('\n=== 5. 导入「老格式」备份（缺字段）===')
        BOXES.clear()
        old = os.path.join(workdir, 'old.json')
        with io.open(old, 'w', encoding='utf-8') as f:
            json.dump({'app': 'dingpan', 'config': {
                'groups': [{'id': 'x', 'name': '老分组',
                            'stocks': [{'code': 'sh000001'}]}]}}, f)
        dialogs.open_file_dialog = lambda *a, **k: old
        click(app, obj, obj.btn_import, 9504)
        check('老备份能导入（不 KeyError）',
              len(app.cfg.get('groups') or []) == 1, str(app.cfg.get('groups'))[:80])
        check('老备份缺省字段被默认值补齐',
              app.cfg.get('fontSize') is not None and 'columns' in app.cfg)

        print('\n=== 6. 自动本地备份 + 配置损坏自愈 ===')
        cfg2 = dict(app.cfg)
        cfg2['fontSize'] = 14
        ok, path, err = storage.save_auto_backup(cfg2)
        check('自动备份写出成功', ok, err)
        check('自动备份是固定文件名（不会堆积）',
              path and os.path.basename(path) == storage.AUTO_BACKUP_FILE,
              os.path.basename(path or ''))
        # 模拟配置文件损坏 → 应能从自动备份恢复
        cfg_file = os.path.join(storage.app_dir(), 'dingpan-config.json')
        with io.open(cfg_file, 'w', encoding='utf-8') as f:
            f.write('{坏掉的配置')
        recovered = storage.load_config()
        check('配置损坏后能从自动备份恢复',
              isinstance(recovered, dict) and bool(recovered.get('groups')),
              str(recovered)[:80])
        check('恢复出来的字号是备份时的值', recovered.get('fontSize') == 14,
              'fontSize=%s' % recovered.get('fontSize'))

    finally:
        try:
            app._cleanup()
        except Exception:
            pass

    print('\n结果: %s' % ('全部通过' if not FAILS else '失败 %d 项 -> %s' % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
