"""
盯盘 — 功能自检
运行: python tools/selftest.py
"""
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

# ⚠️ 必须隔离 APPDATA！
# test_config() 会真的写配置文件再复原，原来直接写用户的真实配置，
# 每次跑自检都会把用户的自选/样式/显示开关重置成默认值。
# 这里必须先切到临时目录，再 import storage（storage 在 import 时就记下了路径）。
REAL_APPDATA = os.environ.get('APPDATA')      # 记下真实目录：原版配置导入要用
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='dpselftest_')

from dingpan import quotes, storage, legacy  # noqa: E402

results = []
names = []


def check(name, ok, extra=''):
    results.append(ok)
    names.append(name)
    print(f"  {'✓' if ok else '✗'} {name}{(' — ' + str(extra)) if extra else ''}")


# ============================== 数据源 ==============================
def test_sources():
    print('\n=== 数据源 ===')
    cases = [('sh600519', '贵州茅台'), ('sz000001', '平安银行'), ('sz300750', '宁德时代')]
    for src in ('tencent', 'sina', 'eastmoney'):
        t0 = time.time()
        res = quotes.fetch_quotes([c for c, _ in cases], src)
        dt = (time.time() - t0) * 1000
        n = len(res.get('data') or {})
        check(f'{src} 拉取', res['ok'] and n >= 1, f'{n} 条 / {dt:.0f}ms')
        if res['ok'] and n:
            q = res['data'].get('sh600519')
            if q:
                # 涨跌幅交叉校验
                pc, price, pct = q.get('prevClose'), q.get('price'), q.get('changePct')
                if pc and price and pct is not None:
                    expect = (price - pc) / pc * 100
                    check(f'{src} 涨跌幅自洽', abs(expect - pct) < 0.15,
                          f'算得 {expect:.2f}% vs 源 {pct:.2f}%')
                    check(f'{src} 名称正确', q.get('name') == '贵州茅台', q.get('name'))
    # 代码归一化
    for raw, want in [('600519', 'sh600519'), ('000001', 'sz000001'),
                      ('00700', 'hk00700'), ('430047', 'bj430047')]:
        check(f'代码归一化 {raw}', quotes.normalize_code(raw) == want,
              quotes.normalize_code(raw))
    # 校验接口
    ok, c, name, err = quotes.verify_code('600519')
    check('verify_code 有效代码', ok and c == 'sh600519' and name == '贵州茅台', name)
    ok, _, _, err = quotes.verify_code('999999')
    check('verify_code 无效代码', not ok, err)


# ============================== 配置 ==============================
def test_config():
    print('\n=== 配置读写 ===')
    cfg = storage.load_config()
    check('默认配置结构', isinstance(cfg.get('groups'), list) and len(cfg['groups']) > 0)
    check('配置路径', storage.config_path().endswith('dingpan-config.json'),
          storage.config_path())
    # 改之前先留一份快照，测完原样写回
    # 以前这里是 save_config(DEFAULT_CONFIG) —— 直接把用户配置覆盖成默认值，
    # 一旦本脚本没隔离 APPDATA，用户的主题/透明度/显示开关全被抹掉。
    snapshot = storage.deep_merge(storage.DEFAULT_CONFIG, cfg)
    try:
        cfg['groups'][0]['name'] = '测试分组'
        storage.save_config(cfg)
        back = storage.load_config()
        check('配置持久化', back['groups'][0]['name'] == '测试分组', back['groups'][0]['name'])
    finally:
        # 原样还原测试前的配置，而不是默认值
        storage.save_config(snapshot)
    restored = storage.load_config()
    check('测试后配置已原样还原',
          restored.get('groups', [{}])[0].get('name') == snapshot['groups'][0]['name'],
          restored.get('groups', [{}])[0].get('name'))


# ============================== WebDAV ==============================
class _DAVHandler(BaseHTTPRequestHandler):
    files = {}

    def log_message(self, *a):
        pass

    def _auth_ok(self):
        import base64
        expect = 'Basic ' + base64.b64encode(b'u:p').decode()
        return self.headers.get('Authorization') == expect

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    def do_PUT(self):
        if not self._auth_ok():
            self.send_response(401)
            self.end_headers()
            return
        self.files[self.path] = self._body()
        self.send_response(201)
        self.end_headers()

    def do_GET(self):
        if not self._auth_ok():
            self.send_response(401)
            self.end_headers()
            return
        if self.path in self.files:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(self.files[self.path])
        else:
            self.send_response(404)
            self.end_headers()

    def do_PROPFIND(self):
        if not self._auth_ok():
            self.send_response(401)
            self.end_headers()
            return
        hrefs = [f'<D:href>{k}</D:href>' for k in self.files if k.startswith(self.path.rstrip('/') + '/')]
        body = ('<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">'
                + ''.join(hrefs) + '</D:multistatus>').encode()
        self.send_response(207)
        self.send_header('Content-Type', 'application/xml')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_MKCOL(self):
        self.send_response(201)
        self.end_headers()


def test_webdav():
    print('\n=== WebDAV ===')
    srv = HTTPServer(('127.0.0.1', 0), _DAVHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f'http://127.0.0.1:{port}'
    cfg = storage.deep_merge(storage.DEFAULT_CONFIG, {})
    cfg['webdav'] = {'url': base, 'username': 'u', 'password': 'p', 'dir': '/dingpan'}
    cfg['groups'] = [{'id': 'g1', 'name': '测试组',
                      'stocks': [{'code': 'sh600519', 'name': '贵州茅台'}]}]

    ok, msg = storage.webdav_test(cfg)
    check('测试连接', ok, msg)

    ok, fname, err = storage.webdav_upload(cfg)
    check('上传备份', ok, fname or err)

    ok, res, err = storage.webdav_download(cfg)
    check('下载备份', ok, (res[1] if ok and isinstance(res, tuple) else err))
    if ok:
        newcfg, fname = res
        check('恢复内容一致', newcfg['groups'][0]['name'] == '测试组', newcfg['groups'][0]['name'])

    bad = storage.deep_merge(cfg, {})
    bad['webdav']['password'] = 'wrong'
    ok, msg = storage.webdav_test(bad)
    check('错误密码被拒绝', not ok, msg)

    srv.shutdown()


# ============================== 本地备份 ==============================
def test_backup():
    print('\n=== 本地备份 ===')
    cfg = storage.load_config()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'bak.json')
        ok, path, err = storage.export_backup(cfg, p)
        check('导出备份', ok and os.path.isfile(p), err)
        ok, back, err = storage.import_backup(p)
        check('导入备份', ok and back is not None, err)
        if ok:
            check('备份内容一致', back['groups'][0]['id'] == cfg['groups'][0]['id'])
        # 坏文件
        bad = os.path.join(d, 'bad.json')
        with open(bad, 'w', encoding='utf-8') as f:
            f.write('{not json')
        ok, _, err = storage.import_backup(bad)
        check('坏文件被拒绝', not ok, err)


# ============================== 原版导入 ==============================
def test_legacy():
    print('\n=== 原版配置导入 ===')
    # 原版配置装在**真实的** %APPDATA%\StockWidget 下，
    # 而本脚本为了不碰用户配置隔离了 APPDATA → 这里显式指向真实目录。
    p = legacy.find_legacy_config(REAL_APPDATA)
    check('检测原版配置', bool(p), p or '未找到（%s）' % (REAL_APPDATA or 'APPDATA 未知'))
    ok, cfg, count, path, err = legacy.import_legacy(REAL_APPDATA)
    check('导入原版配置', ok, f'{count} 只' if ok else err)
    if ok:
        check('分组已建立', len(cfg['groups']) == 1 and cfg['groups'][0]['name'] == '原版自选')
        check('自选数量一致', len(cfg['groups'][0]['stocks']) == count)
        check('快捷键已转换', 'Ctrl' in cfg['hotkeys']['toggleVisible'],
              cfg['hotkeys']['toggleVisible'])
    for raw, want in [('Ctrl+Alt+F', 'Ctrl+Alt+F'), ('Ctrl+Shift+D', 'Ctrl+Shift+D')]:
        check(f'快捷键归一化 {raw}', legacy.normalize_hotkey(raw) == want,
              legacy.normalize_hotkey(raw))


if __name__ == '__main__':
    print('盯盘 — 功能自检')
    test_sources()
    test_config()
    test_webdav()
    test_backup()
    test_legacy()
    passed = sum(1 for r in results if r)
    failed = [names[i] for i, r in enumerate(results) if not r]
    if failed:
        print('\n未通过: ' + '、'.join(failed))
    print(f'\n结果: {passed}/{len(results)} 通过')
    sys.exit(0 if passed == len(results) else 1)
