"""
配置持久化 / 本地备份 / WebDAV 备份恢复
"""
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from .quotes import UA, _SSL_CTX

APP_DIR_NAME = 'DingPan'
CONFIG_FILE = 'dingpan-config.json'
AUTO_BACKUP_FILE = 'dingpan-autobackup.json'   # 自动备份固定一个文件，始终覆盖
DAV_AUTO_FILE = 'dingpan-autosync.json'        # WebDAV 自动同步固定一个文件，不堆积
CACHE_FILE = 'dingpan-cache.json'              # 上次行情快照：启动先显示，避免空白等待
POINTER_FILE = 'dingpan-location.json'         # 记录自定义的存储位置（程序目录下的指针）

# 快照只留这些字段，几十只股票也就几 KB
_CACHE_FIELDS = ('name', 'price', 'prevClose', 'change', 'changePct', 'open',
                 'high', 'low', 'volume', 'amount', 'turnover', 'pe',
                 'amplitude', 'totalCap', 'pb', 'time')

DEFAULT_CONFIG = {
    'version': 2,
    'source': 'tencent',
    'refreshInterval': 5000,
    'showHeader': True,
    'showName': True,
    'showCode': True,
    'showTableHead': True,
    'showStatus': True,
    # 悬浮窗外框（默认关：用户要求无边框）
    'showBorder': False,
    # 表格内部线段（表头下划线 / 状态栏上沿线）
    'showGridLines': True,
    'alwaysOnTop': True,
    'fontSize': 13,
    'theme': 'dark',
    'width': 400,
    'height': 380,
    # 窗口大小是否按内容自适应（关掉则用上面 width/height 固定值）
    'autoSize': True,
    # 股票名称最多显示几个字符（0 = 全部显示）
    'nameChars': 0,
    'title': '',
    # 背景 / 文字透明度，0-100 各自独立
    'bgAlpha': 100,
    'textAlpha': 100,
    # 文字描边：auto（背景透明时自动开）/ on（始终）/ off（关闭）
    # 默认 off —— 描边在某些背景上看着像重影，用户反馈过，默认关掉更干净
    'textOutline': 'off',
    # 背景完全透明（勾上后背景 alpha = 0，滑块失效）
    'bgTransparent': False,
    # 悬浮窗内部间距（单位 px）
    # padMode: 'auto'（按字号自适应，4 维一起算）/ 'custom'（手动设定下面各项）
    # padX   ：横向外边距 —— 内容区左右各留多少 px（影响列布局与左右留白）
    # padY   ：竖向外边距 —— 首末行与标题栏/状态栏各留多少 px
    # rowGap ：行高（绝对）—— 每一行的高度 px（参照 Excel，不再叠加行间距）
    # colGap ：列间距 —— 相邻两列之间留多少 px（名称列↔价格列等）
    # colWidth：列宽（最小宽度下限）—— 每列至少多宽 px；0 = 按内容自适应
    'padMode': 'auto',
    'padX': 6,
    'padY': 4,
    'rowGap': 24,
    'colGap': 6,
    'colWidth': 0,
    # 存储位置：空 = 用默认（主程序文件夹内）
    'configDir': '',
    'backupDir': '',
    # 自定义配色
    'customBg': '#1c1f28',
    'customText': '#e6e8ef',
    'upColor': '#f6465d',
    'downColor': '#0ecb81',
    'columns': ['name', 'code', 'price', 'change', 'changePct', 'turnover', 'time'],
    # 显示字段页的**完整**顺序（含未勾选的字段）——
    # 用户拖动排序时，未勾选的字段也要留在原位，所以顺序要单独存一份
    'fieldOrder': [],
    # 「打开行情页」用哪个平台：
    #   xueqiu / tencent / eastmoney / sina / ths / custom
    'quotePlatform': 'xueqiu',
    # 自定义平台的 URL 模板，可用占位符 {code}（带前缀小写，如 sh600519）
    # 和 {sym}（大写带前缀，如 SH600519）
    'quoteUrlTemplate': 'https://xueqiu.com/S/{sym}',
    # 自定义数据源：{'url': 模板, 'format': 'json'|'kv', 'mapping': {...}}
    'customSource': {},
    # 显示方案预设：内置几种 + 用户自定义（可在「样式外观」页保存与切换）
    # 显示方案预设：一套**完整的显示配置**（字段 + 主题 + 颜色 + 透明度 +
    # 字号 + 各种显示开关）。切换方案 = 一次性套用整套外观。
    'presets': [
        {'name': '精简（名称+涨跌）', 'builtin': True,
         'columns': ['name', 'price', 'changePct'],
         'display': {'fontSize': 15, 'showStatus': False}},
        {'name': '标准（含代码）', 'builtin': True,
         'columns': ['name', 'code', 'price', 'change', 'changePct', 'turnover', 'time'],
         'display': {'fontSize': 13, 'showStatus': True}},
        {'name': '完整（全部字段）', 'builtin': True,
         'columns': ['name', 'code', 'price', 'change', 'changePct', 'open', 'high',
                     'low', 'prevClose', 'volume', 'amount', 'turnover', 'pe', 'pb',
                     'amplitude', 'floatCap', 'totalCap', 'time'],
         'display': {'fontSize': 12, 'showStatus': True}},
        {'name': '只看代码', 'builtin': True,
         'columns': ['code', 'price', 'changePct'],
         'display': {'fontSize': 13, 'showStatus': False}},
    ],
    'groups': [
        {'id': 'g_default', 'name': '默认分组',
         'stocks': [{'code': 'sh600519', 'name': '贵州茅台'},
                    {'code': 'sz000001', 'name': '平安银行'},
                    {'code': 'sz300750', 'name': '宁德时代'}]},
    ],
    'activeGroupId': 'g_default',
    'webdav': {'url': '', 'username': '', 'password': '', 'dir': '/dingpan'},
    # 设置变动后自动同步
    'autoLocalBackup': True,
    'autoDavSync': False,
    'hintShown': False,          # 首次启动的托盘提示只弹一次
    'hotkeys': {
        'toggleVisible': 'Ctrl+Alt+D',
        'refresh': 'Ctrl+Alt+R',
        'openSettings': 'Ctrl+Alt+S',
        'nextGroup': 'Ctrl+Alt+Right',
    },
    # 每个快捷键是否启用；未勾选的不注册
    'hotkeyEnabled': {
        'toggleVisible': True,
        'refresh': True,
        'openSettings': True,
        'nextGroup': True,
    },
}


# ---------------------------------------------------------------------------
# 存储位置
# ---------------------------------------------------------------------------
# 默认全部放在**主程序所在文件夹**内（绿色便携）：
#   配置文件  → <程序目录>/dingpan-config.json
#   备份文件  → <程序目录>/dingpan-backups/
# 整个文件夹拷走即可带走全部设置。
# 用户可在设置里改成任意自定义路径（自定义后写进配置文件本身）。
#
# ⚠️ 程序目录不可写时（如装到 C:\Program Files、或从 U 盘只读运行）
#    自动降级到 %APPDATA% 下的 DingPan，并在设置页给出提示。

_PATH_OVERRIDES = {'config': None, 'backup': None}   # 用户自定义路径


def _program_dir():
    """主程序所在目录（打包后 = exe 同级；源码运行 = 项目根）

    ⚠️ DINGPAN_HOME 环境变量可覆盖它 —— 测试用它把「程序目录」隔离到临时目录，
    否则测试会把配置写进真实的项目目录（还会互相干扰）。
    """
    override = os.environ.get('DINGPAN_HOME')
    if override:
        return os.path.abspath(override)
    try:
        if getattr(sys, 'frozen', False):
            return os.path.dirname(os.path.abspath(sys.executable))
    except Exception:  # noqa: BLE001
        pass
    # 源码运行：src/dingpan/storage.py → 上两级是项目根
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _fallback_dir():
    """降级目录：%APPDATA% 下的 DingPan"""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, APP_DIR_NAME)


def _writable(path):
    """目录是否可写（能建文件就算可写）"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, '.dingpan_write_test')
        with open(probe, 'w', encoding='utf-8') as f:
            f.write('x')
        os.remove(probe)
        return True
    except Exception:  # noqa: BLE001
        return False


def set_path_override(kind, path):
    """设置自定义路径（kind: 'config' / 'backup'）。传空串则恢复默认。"""
    _PATH_OVERRIDES[kind] = (path or None)


def get_path_override(kind):
    return _PATH_OVERRIDES.get(kind)


def app_dir():
    """配置目录

    优先级：
      1. 用户自定义路径（设置页选的目录）
      2. 主程序所在文件夹（绿色便携，exe 同级）
      3. %APPDATA% 下的 DingPan（程序目录不可写时降级）
    """
    override = _PATH_OVERRIDES.get('config')
    if override:
        try:
            os.makedirs(override, exist_ok=True)
            return override
        except Exception:  # noqa: BLE001
            pass
    prog = _program_dir()
    if _writable(prog):
        return prog
    fb = _fallback_dir()
    try:
        os.makedirs(fb, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return fb


def backup_dir():
    """备份文件目录

    默认 <程序目录>/dingpan-backups/；用户可自定义。
    """
    override = _PATH_OVERRIDES.get('backup')
    if override:
        try:
            os.makedirs(override, exist_ok=True)
            return override
        except Exception:  # noqa: BLE001
            pass
    base = app_dir()
    d = os.path.join(base, 'dingpan-backups')
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:  # noqa: BLE001
        return base


def config_path():
    return os.path.join(app_dir(), CONFIG_FILE)


# ---------------------------------------------------------------------------
# 位置指针
# ---------------------------------------------------------------------------
# 鸡生蛋问题：配置文件在自定义目录里，但要先知道目录才能找到配置文件。
# 解法：在**程序目录**（或降级目录）放一个很小的指针文件，
# 记录「配置在哪 / 备份在哪」。启动时先读指针，再读配置。

def _pointer_dir():
    """指针文件所在目录：程序目录；不可写则用降级目录"""
    prog = _program_dir()
    if _writable(prog):
        return prog
    fb = _fallback_dir()
    try:
        os.makedirs(fb, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return fb


def load_location():
    """启动时读指针，恢复用户自定义的存储位置"""
    try:
        p = os.path.join(_pointer_dir(), POINTER_FILE)
        with open(p, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict):
            set_path_override('config', d.get('configDir') or None)
            set_path_override('backup', d.get('backupDir') or None)
            return True
    except (OSError, ValueError):
        pass
    return False


def save_location():
    """把当前生效的存储位置写进指针文件"""
    try:
        d = os.path.join(_pointer_dir(), POINTER_FILE)
        payload = {'configDir': _PATH_OVERRIDES.get('config') or '',
                   'backupDir': _PATH_OVERRIDES.get('backup') or ''}
        tmp = d + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, d)
        return True
    except Exception:  # noqa: BLE001
        return False


def deep_merge(base, patch):
    """递归合并，数组整体替换"""
    if not isinstance(patch, dict):
        return patch
    out = dict(base) if isinstance(base, dict) else {}
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    path = config_path()
    raw = None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError('配置根节点不是对象')
        cfg = deep_merge(DEFAULT_CONFIG, raw)
    except ValueError:
        # 配置文件损坏（断电/磁盘满/手工改坏）：先留证据，再拿自动备份救回来，
        # 不要一声不响把用户攒了很久的自选股清空
        try:
            os.replace(path, path + '.bad')
        except OSError:
            pass
        cfg = _from_auto_backup() or json.loads(json.dumps(DEFAULT_CONFIG))
        raw = None
        save_config(cfg)
    except OSError:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        raw = None
    cfg, migrated = _migrate(cfg, raw)
    # 老配置读进来后立刻落盘升级一次，避免每次启动重复迁移
    if isinstance(raw, dict) and (raw.get('version') != cfg.get('version') or migrated):
        save_config(cfg)
    return cfg


def _from_auto_backup():
    """从自动备份里救回配置；没有可用备份时返回 None"""
    try:
        with open(os.path.join(backup_dir(), AUTO_BACKUP_FILE), 'r', encoding='utf-8') as f:
            parsed = json.load(f)
        cfg = parsed.get('config') if isinstance(parsed, dict) else None
        if isinstance(cfg, dict) and isinstance(cfg.get('groups'), list):
            return deep_merge(DEFAULT_CONFIG, cfg)
    except (OSError, ValueError):
        pass
    return None


def _migrate(cfg, raw):
    """老版本配置升级（不丢用户设置）

    返回 (cfg, changed)：changed 为 True 时由 load_config 负责落盘一次，
    避免同一项迁移每次启动都重复执行（例如用户后来刻意删掉某列又被迫加回）。
    """
    changed = False
    if isinstance(raw, dict):
        # v1.0.24：背景透明度改成 0–100%，0% 就是「完全透明」。
        # 老配置里勾了「背景透明」是独立开关（bgTransparent=True），
        # 现在统一折算成 bgAlpha=0 —— 否则升级后背景不再透明（用户会以为功能坏了）。
        if raw.get('bgTransparent') and int(cfg.get('bgAlpha', 100) or 0) > 0:
            cfg['bgAlpha'] = 0
            changed = True
        # v1 的 opacity(0.3~1.0) 拆成 bgAlpha(0~100)
        if 'bgAlpha' not in raw and 'opacity' in raw:
            try:
                cfg['bgAlpha'] = int(round(float(raw['opacity']) * 100))
            except (TypeError, ValueError):
                pass
        # 老的自定义配色键名
        for old, new in (('customDim', None), ('customUp', 'upColor'), ('customDown', 'downColor')):
            if new and old in raw and new not in raw and raw[old]:
                cfg[new] = '#%s' % str(raw[old]).lstrip('#')
        # 老版本 showHeader 同时控制「标题栏+分组标签」和「列表表头」，
        # 现在拆成 showHeader / showTableHead 两个独立开关。
        # 迁移时让表头沿用用户原来的 showHeader 值，避免升级后表头突然冒出来。
        if 'showTableHead' not in raw:
            cfg['showTableHead'] = bool(raw.get('showHeader', True))
        # 旧配置里没有独立的「代码」列：名称列会把代码当第二行挤在同一个格里，
        # 用户感知是「名称和代码显示在一起」。这里把代码提升为独立列（插在名称之后），
        # 实现真正的「分开显示」，且名称、代码各自可被 showName/showCode 单独开关。
        # 一次性迁移：用 _codeColMigrated 标记，之后即使用户刻意删掉 code 列也不再加回。
        if (not cfg.get('_codeColMigrated')
                and isinstance(cfg.get('columns'), list)
                and 'name' in cfg['columns']
                and 'code' not in cfg['columns']
                and bool(cfg.get('showCode', True))):
            idx = cfg['columns'].index('name')
            cfg['columns'].insert(idx + 1, 'code')
            cfg['_codeColMigrated'] = True
            changed = True
        # v1.0.15：名称 / 代码的开关从基础设置移到「显示字段」，
        # 显示逻辑改为「以 columns 里勾选的列为准」。
        # 老配置里 showName / showCode=False 的，要真的把对应的列从 columns 里去掉，
        # 否则用户明明关了「显示股票代码」，升级后代码列又冒出来了。
        if isinstance(cfg.get('columns'), list):
            for key, flag in (('name', 'showName'), ('code', 'showCode')):
                if (not cfg.get(flag, True) and key in cfg['columns']):
                    cfg['columns'] = [c for c in cfg['columns'] if c != key]
                    changed = True
            # 反向同步：勾了列就等于开了开关（保证两个键自洽）
            cfg['showName'] = 'name' in cfg['columns']
            cfg['showCode'] = 'code' in cfg['columns']
    cfg.pop('opacity', None)
    return cfg, changed


def save_config(cfg):
    try:
        os.makedirs(app_dir(), exist_ok=True)
        tmp = config_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path())
        return True
    except OSError:
        return False


def stamp():
    return datetime.now().strftime('%Y%m%d-%H%M%S')


# ============================== 行情快照 ==============================
class QuoteSnapshot(object):
    """行情快照缓存

    - 固定文件名 dingpan-cache.json，每次整份覆盖，不会随使用时间增长
    - 只在内容真的变了才写盘，避免每个刷新周期都碰磁盘
    """
    path = None
    _last_sig = None

    @classmethod
    def file(cls):
        return os.path.join(app_dir(), CACHE_FILE)

    @classmethod
    def save(cls, quotes):
        """quotes: {code: {..}}；内容无变化时直接跳过"""
        try:
            slim = {}
            for code, q in (quotes or {}).items():
                row = {'code': code}
                for f in _CACHE_FIELDS:
                    if q.get(f) is not None:
                        row[f] = q[f]
                if row.get('name'):
                    slim[code] = row
            if not slim:
                return False
            sig = json.dumps(slim, sort_keys=True, ensure_ascii=False)
            if sig == cls._last_sig:
                return False
            cls._last_sig = sig
            os.makedirs(app_dir(), exist_ok=True)
            p = cls.file()
            tmp = p + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'savedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                           'quotes': slim}, f, ensure_ascii=False, separators=(',', ':'))
            os.replace(tmp, p)
            return True
        except OSError:
            return False

    @classmethod
    def load(cls):
        """返回 (quotes, savedAt)；无缓存或损坏时返回 ({}, '')"""
        try:
            with open(cls.file(), 'r', encoding='utf-8') as f:
                data = json.load(f)
            quotes = data.get('quotes') or {}
            if not isinstance(quotes, dict):
                return {}, ''
            return quotes, str(data.get('savedAt') or '')
        except (OSError, ValueError):
            return {}, ''

    @classmethod
    def clear(cls):
        cls._last_sig = None
        try:
            os.remove(cls.file())
        except OSError:
            pass


# ============================== 本地备份 ==============================
def export_backup(cfg, dest_path):
    """写入备份文件，返回 (ok, path, error)"""
    try:
        payload = {'app': 'dingpan', 'exportedAt': datetime.now().isoformat(), 'config': cfg}
        with open(dest_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True, dest_path, ''
    except OSError as e:
        return False, None, f'写入失败：{e}'


def save_auto_backup(cfg):
    """设置变动后的自动备份：固定文件名，覆盖写，永远不会堆积文件"""
    try:
        os.makedirs(backup_dir(), exist_ok=True)
        p = os.path.join(backup_dir(), AUTO_BACKUP_FILE)
        tmp = p + '.tmp'
        payload = {'app': 'dingpan', 'exportedAt': datetime.now().isoformat(), 'config': cfg}
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True, p, ''
    except OSError as e:
        return False, None, f'写入失败：{e}'


def import_backup(src_path):
    """读取备份文件，返回 (ok, config, error)"""
    try:
        with open(src_path, 'r', encoding='utf-8') as f:
            parsed = json.load(f)
        cfg = parsed.get('config') if isinstance(parsed, dict) else None
        if not (isinstance(cfg, dict) and isinstance(cfg.get('groups'), list)):
            cfg = parsed
        if not (isinstance(cfg, dict) and isinstance(cfg.get('groups'), list)):
            return False, None, '文件格式不正确'
        return True, deep_merge(DEFAULT_CONFIG, cfg), ''
    except (OSError, ValueError) as e:
        return False, None, f'读取失败：{e}'


# ============================== WebDAV ==============================
def _auth_header(user, password):
    raw = f'{user or ""}:{password or ""}'.encode('utf-8')
    return 'Basic ' + base64.b64encode(raw).decode('ascii')


def _dav_url(base, subdir, filename=''):
    u = base.strip().rstrip('/')
    if subdir:
        u += '/' + subdir.strip().strip('/')
    if filename:
        u += '/' + filename
    return u


def _dav_request(url, method, body=None, w=None, extra_headers=None, timeout=20, retries=3):
    """返回 (ok, text, error)

    网络抖动（连接被服务器提前关闭、超时等）会自动重试，避免「测试连接」偶发失败；
    HTTP 状态码错误属于确定性结果，不重试。
    """
    w = w or {}
    headers = {'User-Agent': 'DingPan/1.0', 'Authorization': _auth_header(w.get('username'), w.get('password'))}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if method == 'PROPFIND':
        xml = ('<?xml version="1.0" encoding="utf-8" ?>'
               '<D:propfind xmlns:D="DAV:"><D:prop>'
               '<D:displayname/><D:resourcetype/></D:prop></D:propfind>')
        headers['Content-Type'] = 'application/xml; charset=utf-8'
        data = xml.encode('utf-8')
    elif body is not None:
        data = body.encode('utf-8') if isinstance(body, str) else body
        headers['Content-Type'] = 'application/json; charset=utf-8'
    if data is not None:
        headers['Content-Length'] = str(len(data))

    last = ''
    tries = max(1, int(retries))
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                raw = resp.read()
                if resp.headers.get('Content-Encoding', '').lower() == 'gzip':
                    import gzip
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                return True, raw.decode('utf-8', errors='replace'), ''
        except urllib.error.HTTPError as e:
            code = e.code
            if code in (401, 403):
                return False, '', '认证失败（用户名或密码错误 / 无权限）'
            if code == 404:
                return False, '', '路径不存在（404），请检查目录设置'
            if code == 405:
                return False, '', '服务器不支持该方法（405），该地址可能不是 WebDAV'
            if code == 409:
                return False, '', '目录冲突（409），请更换存储目录名'
            return False, '', f'HTTP {code}'
        except Exception as e:  # noqa: BLE001
            last = str(e) or e.__class__.__name__
            if attempt + 1 < tries:
                time.sleep(0.5 * (attempt + 1))
                continue
    return False, '', last or '网络异常'


def webdav_test(cfg):
    w = cfg.get('webdav') or {}
    if not w.get('url'):
        return False, '请先填写 WebDAV 地址'
    ok, _, err = _dav_request(_dav_url(w['url'], w.get('dir'), ''), 'PROPFIND', w=w,
                               extra_headers={'Depth': '0'})
    return (True, '连接成功') if ok else (False, '连接失败：' + err)


def webdav_upload(cfg, fixed=False):
    """上传备份

    fixed=True 时使用固定文件名（自动同步用），每次覆盖，服务器上不会越积越多。
    """
    w = cfg.get('webdav') or {}
    if not w.get('url'):
        return False, None, '请先填写 WebDAV 地址'
    fname = DAV_AUTO_FILE if fixed else f'dingpan-backup-{stamp()}.json'
    url = _dav_url(w['url'], w.get('dir'), fname)
    body = json.dumps({'app': 'dingpan', 'exportedAt': datetime.now().isoformat(),
                       'config': cfg}, ensure_ascii=False, indent=2)
    if w.get('dir'):
        # 确保目录存在（405/409 表示已存在，忽略）
        _dav_request(_dav_url(w['url'], w.get('dir'), ''), 'MKCOL', w=w)
    ok, _, err = _dav_request(url, 'PUT', body, w=w)
    if not ok:
        return False, None, '上传失败：' + err
    return True, fname, ''


def webdav_download(cfg):
    w = cfg.get('webdav') or {}
    if not w.get('url'):
        return False, None, '请先填写 WebDAV 地址'
    ok, listing, err = _dav_request(_dav_url(w['url'], w.get('dir'), ''), 'PROPFIND', w=w,
                                     extra_headers={'Depth': '1'})
    if not ok:
        return False, None, '下载失败：' + err
    files = []
    for m in re.finditer(r'<(?:[a-zA-Z0-9]+:)?href[^>]*>([^<]+)</(?:[a-zA-Z0-9]+:)?href>', listing):
        href = m.group(1).strip()
        try:
            from urllib.parse import unquote
            href = unquote(href)
        except Exception:  # noqa: BLE001
            pass
        name = href.rstrip('/').split('/')[-1]
        if name.lower().endswith('.json'):
            files.append(name)
    if not files:
        return False, None, 'WebDAV 中未找到备份文件'
    if DAV_AUTO_FILE in files:
        latest = DAV_AUTO_FILE          # 自动同步文件优先（它总是最新的）
    else:
        files.sort()
        latest = files[-1]
    ok, text, err = _dav_request(_dav_url(w['url'], w.get('dir'), latest), 'GET', w=w)
    if not ok:
        return False, None, '下载失败：' + err
    try:
        parsed = json.loads(text)
    except ValueError:
        return False, None, '下载失败：备份内容不是有效 JSON'
    cfgd = parsed.get('config') if isinstance(parsed, dict) else None
    if not (isinstance(cfgd, dict) and isinstance(cfgd.get('groups'), list)):
        cfgd = parsed
    if not (isinstance(cfgd, dict) and isinstance(cfgd.get('groups'), list)):
        return False, None, '下载失败：备份内容格式不正确'
    return True, (deep_merge(DEFAULT_CONFIG, cfgd), latest), ''
