"""自动备份 / 自动同步自检

验证三件事：
1. 设置变动后 4 秒内落一次本地自动备份，文件名固定；
2. 再次变动仍写同一个文件（覆盖，不堆积）；
3. 关掉开关后不再产生备份。

用临时 APPDATA，绝不碰用户真实配置。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpsync_')
# 程序目录也要隔离：配置默认写在程序目录内，不隔离会污染项目目录
os.environ['DINGPAN_HOME'] = tempfile.mkdtemp(prefix='dphome_')

from dingpan.app import App                      # noqa: E402
from dingpan import storage                      # noqa: E402

results = []


def check(name, ok, extra=''):
    results.append(bool(ok))
    print('  %s %s%s' % ('✓' if ok else '✗', name, (' — ' + str(extra)) if extra else ''))


def pump(app, ms):
    """泵消息直到到时间：让 WM_TIMER(防抖) 和 WM_APP_SYNC_DONE 真正被处理"""
    import ctypes
    import time
    from ctypes import wintypes
    from dingpan import win32 as w32
    end = time.time() + ms / 1000.0
    msg = wintypes.MSG()
    while time.time() < end:
        while w32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            w32.user32.TranslateMessage(ctypes.byref(msg))
            w32.user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)


def main():
    app = App()
    app.cfg['autoLocalBackup'] = True
    app.cfg['autoDavSync'] = False          # 不碰网络，只验本地链路
    app.create_window()
    try:
        bak = os.path.join(storage.backup_dir(), storage.AUTO_BACKUP_FILE)
        print('=== 1. 设置变动 → 自动本地备份 ===')
        check('初始没有自动备份文件', not os.path.exists(bak))
        app.cfg['fontSize'] = 15
        app.save_cfg()
        pump(app, 7000)
        check('4 秒后已生成备份', os.path.exists(bak),
              os.path.basename(bak) if os.path.exists(bak) else '缺失')
        if os.path.exists(bak):
            import json
            with open(bak, encoding='utf-8') as f:
                d = json.load(f)
            check('备份文件结构正确', 'config' in d and d.get('app') == 'dingpan')
            check('备份内容与当前配置一致', d['config'].get('fontSize') == 15,
                  d['config'].get('fontSize'))

        print('=== 2. 再次变动仍覆盖同一个文件 ===')
        before = sorted(os.listdir(storage.backup_dir()))
        app.cfg['fontSize'] = 17
        app.save_cfg()
        pump(app, 7000)
        after = sorted(os.listdir(storage.backup_dir()))
        check('没有新增文件（始终覆盖）', before == after, after)
        mtime1 = os.path.getmtime(bak)
        import time
        time.sleep(1.1)
        app.cfg['fontSize'] = 18
        app.save_cfg()
        pump(app, 7000)
        check('同一个文件被重写', os.path.getmtime(bak) > mtime1)

        print('=== 3. 关掉开关后不再备份 ===')
        app.cfg['autoLocalBackup'] = False
        app.save_cfg()
        pump(app, 2000)
        os.remove(bak)
        app.cfg['fontSize'] = 19
        app.save_cfg()
        pump(app, 7000)
        check('关闭开关后不再生成备份', not os.path.exists(bak))

        print('=== 4. 防抖：连续多次改动只写一次 ===')
        app.cfg['autoLocalBackup'] = True
        writes = {'n': 0}
        orig = storage.save_auto_backup

        def counting(cfg):
            writes['n'] += 1
            return orig(cfg)
        storage.save_auto_backup = counting
        app.save_cfg()
        app.save_cfg()
        app.save_cfg()
        pump(app, 7000)
        storage.save_auto_backup = orig
        check('3 次连续改动合并成 1 次写入', writes['n'] == 1, '%d 次' % writes['n'])
    finally:
        app._cleanup()

    print('\n结果: %d/%d 通过' % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
