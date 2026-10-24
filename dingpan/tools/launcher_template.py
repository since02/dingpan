#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""盯盘 启动入口（永不以静默方式失败）

本文件是打包模板：build.py 会原样拷贝成根目录的 launcher.py 作为 PyInstaller 入口。
放在独立文件里是为了避免在 build.py 里嵌套转义字符串。
"""
import os
import sys

_LOG_MAX = 192 * 1024


def _log(context):
    r"""无控制台时把异常写入 AppData\DingPan\crash.log（超过 192KB 自动轮转）"""
    try:
        d = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'DingPan')
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, 'crash.log')
        import traceback
        try:
            if os.path.isfile(p) and os.path.getsize(p) > _LOG_MAX:
                old = p + '.old'
                if os.path.isfile(old):
                    os.remove(old)
                os.replace(p, old)
        except OSError:
            pass
        with open(p, 'a', encoding='utf-8') as f:
            f.write('\n===== ' + context + ' =====\n')
            traceback.print_exc(file=f)
    except Exception:
        pass


def _add_src_paths():
    """开发环境兜底：把同目录 / 上一级的 src 加进 sys.path（打包后不存在，自然跳过）"""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, 'src'), os.path.join(here, '..', 'src')):
        cand = os.path.abspath(cand)
        if os.path.isdir(os.path.join(cand, 'dingpan')) and cand not in sys.path:
            sys.path.insert(0, cand)


try:
    from dingpan.app import main
except Exception:
    _log('launcher import')
    _add_src_paths()
    try:
        from dingpan.app import main
    except Exception:
        _log('launcher import retry')
        raise

if __name__ == '__main__':
    sys.exit(main())
