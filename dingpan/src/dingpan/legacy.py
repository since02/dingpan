"""
原版 StockWidget.exe (SW_config.json) 配置导入
"""
import json
import os
import re

from .storage import DEFAULT_CONFIG, deep_merge


def candidate_paths(appdata=None):
    """原版配置的候选位置。

    appdata 允许外部指定（测试里要指向真实安装目录，
    因为自检脚本会隔离 APPDATA，不能跟着一起被隔离掉）。
    """
    home = os.path.expanduser('~')
    if appdata is None:
        appdata = os.environ.get('APPDATA') or os.path.join(home, 'AppData', 'Roaming')
    return [
        os.path.join(appdata, 'StockWidget', 'SW_config.json'),
        os.path.join(appdata, 'stockwidget', 'SW_config.json'),
        os.path.join(home, '.stockwidget', 'SW_config.json'),
        os.path.join(home, 'SW_config.json'),
        os.path.join(home, '.config', 'stockwidget', 'SW_config.json'),
    ]


def find_legacy_config(appdata=None):
    for p in candidate_paths(appdata):
        try:
            if os.path.isfile(p):
                return p
        except OSError:
            continue
    return None


def hex_to_rgb(h):
    m = re.match(r'^#?([0-9a-fA-F]{6})$', str(h or '').strip())
    if not m:
        return None
    v = int(m.group(1), 16)
    return {'r': (v >> 16) & 255, 'g': (v >> 8) & 255, 'b': v & 255}


def rgb_to_hex(c):
    if not c:
        return None
    def cl(v):
        return max(0, min(255, int(v or 0)))
    return '#{:02x}{:02x}{:02x}'.format(cl(c.get('r')), cl(c.get('g')), cl(c.get('b')))


def is_dark(c):
    if not c:
        return True
    lum = (0.299 * c.get('r', 0) + 0.587 * c.get('g', 0) + 0.114 * c.get('b', 0)) / 255
    return lum < 0.5


def normalize_hotkey(s):
    """'Ctrl+Alt+F' → 'Ctrl+Alt+F'（内部统一用 Ctrl 记法）"""
    if not s or not isinstance(s, str):
        return None
    parts = [p.strip() for p in s.split('+') if p.strip()]
    if not parts:
        return None
    out = []
    for p in parts:
        low = p.lower()
        if low in ('ctrl', 'control'):
            out.append('Ctrl')
        elif low == 'alt':
            out.append('Alt')
        elif low == 'shift':
            out.append('Shift')
        elif low in ('cmd', 'command', 'win', 'meta'):
            out.append('Win')
        elif low == 'right':
            out.append('Right')
        elif low == 'left':
            out.append('Left')
        elif low == 'up':
            out.append('Up')
        elif low == 'down':
            out.append('Down')
        elif re.match(r'^f\d{1,2}$', low):
            out.append(low.upper())
        elif len(p) == 1:
            out.append(p.upper())
        else:
            out.append(p[0].upper() + p[1:])
    return '+'.join(out)


def convert(legacy, base=None):
    """将原版配置转换为新配置"""
    cfg = json.loads(json.dumps(base or DEFAULT_CONFIG))

    codes = legacy.get('codes') or []
    visible = set(legacy.get('visible_codes') or codes)
    stocks = [{'code': str(c).strip(), 'name': ''}
              for c in codes if isinstance(c, str) and c.strip()]
    cfg['groups'] = [{'id': 'g_legacy', 'name': '原版自选', 'stocks': stocks}]
    cfg['activeGroupId'] = 'g_legacy'

    cols = ['name', 'price', 'change', 'changePct']
    if legacy.get('short_code'):
        cols.insert(1, 'code')
    if legacy.get('b1s1_price'):
        cols.append('volume')
    if legacy.get('grid_visible'):
        cols += ['open', 'high', 'low']
    cols.append('time')
    seen, uniq = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    cfg['columns'] = uniq

    bg = legacy.get('bg') if isinstance(legacy.get('bg'), dict) else None
    cfg['theme'] = 'dark' if is_dark(bg) else 'light'
    try:
        cfg['opacity'] = max(0.3, min(1.0, float(legacy.get('opacity_pct', 69)) / 100))
    except (TypeError, ValueError):
        cfg['opacity'] = 0.69
    try:
        cfg['fontSize'] = max(10, min(20, int(legacy.get('font_size', 10))))
    except (TypeError, ValueError):
        cfg['fontSize'] = 10
    cfg['showHeader'] = legacy.get('header_visible', False) is not False

    fg = legacy.get('fg')
    if isinstance(fg, str) and re.match(r'^#[0-9a-fA-F]{6}$', fg) and not legacy.get('default_color'):
        cfg['theme'] = 'custom'
        cfg['customText'] = fg
        cfg['customDim'] = fg
    if bg:
        h = rgb_to_hex(bg)
        if h:
            cfg['theme'] = 'custom'
            cfg['customBg'] = h

    try:
        rs = float(legacy.get('refresh_seconds') or 0)
    except (TypeError, ValueError):
        rs = 0
    cfg['refreshInterval'] = int(max(1, min(300, rs if rs > 0 else 5)) * 1000)

    pos = legacy.get('pos')
    if isinstance(pos, dict) and 'x' in pos and 'y' in pos:
        try:
            cfg['windowBounds'] = {'x': int(pos['x']), 'y': int(pos['y'])}
        except (TypeError, ValueError):
            pass

    hk = legacy.get('hotkey')
    if hk:
        v = normalize_hotkey(hk)
        if v:
            cfg['hotkeys'] = dict(cfg.get('hotkeys') or {})
            cfg['hotkeys']['toggleVisible'] = v
    return cfg


def import_legacy(appdata=None):
    """返回 (ok, config, count, path, error)"""
    p = find_legacy_config(appdata)
    if not p:
        return False, None, 0, None, '未找到原版 StockWidget 的配置文件（SW_config.json）'
    try:
        with open(p, 'r', encoding='utf-8-sig') as f:
            legacy = json.load(f)
        if not isinstance(legacy, dict) or not isinstance(legacy.get('codes'), list):
            return False, None, 0, p, '原版配置文件格式不正确'
        return True, convert(legacy), len(legacy['codes']), p, ''
    except (OSError, ValueError) as e:
        return False, None, 0, p, f'读取原版配置失败：{e}'
