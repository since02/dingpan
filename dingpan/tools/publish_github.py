# -*- coding: utf-8 -*-
"""把当前本地提交发布到 GitHub（走 REST Git Data API，代理只放行 api.github.com）。

做���：
  1. 读本地 HEAD 的完整文件树
  2. 逐个建 blob → 建 tree（远端已删的文件用 sha:None 显式删除）
  3. 建 commit → 更新 refs/heads/main
  4. 打 tag + 建 Release（带 exe 附件）
  5. 删掉旧 tag / 旧 Release（只保留最新版）

用法：GH_TOKEN=xxx python tools/publish_github.py [版本号] [说明]
"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库根 = 往上找到带 .git 的那一级（不能用 tools 的上一级，
# 否则 git ls-tree 出来的路径会丢掉仓库根前缀，远端目录结构就错了）
ROOT = os.path.dirname(HERE)
while not os.path.isdir(os.path.join(ROOT, '.git')) and os.path.dirname(ROOT) != ROOT:
    ROOT = os.path.dirname(ROOT)
REPO = 'since02/dingpan'
API = 'https://api.github.com'
TOKEN = os.environ.get('GH_TOKEN', '').strip()


def gh(method, path, data=None, raw=False, retry=4):
    url = path if path.startswith('http') else API + path
    body = None
    headers = {
        'Authorization': 'Bearer ' + TOKEN,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'dingpan-publish',
    }
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    last = None
    for i in range(retry):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                if raw:
                    return payload
                return json.loads(payload.decode('utf-8')) if payload else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'ignore')[:300]
            last = 'HTTP %s %s' % (e.code, detail)
            if e.code in (403, 429, 502, 503):
                time.sleep(2 + i * 3)
                continue
            raise RuntimeError('%s %s -> %s' % (method, path, last))
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(2 + i * 2)
    raise RuntimeError('%s %s -> %s' % (method, path, last))


def git(*args):
    return subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True,
                          text=True, encoding='utf-8', errors='ignore').stdout.strip()


def local_files():
    """本地 HEAD 里的全部文件（相对仓库根）"""
    out = git('ls-tree', '-r', '--name-only', 'HEAD')
    return [p for p in out.splitlines() if p.strip()]


def remote_files(commit_sha):
    tree = gh('GET', '/repos/%s/git/trees/%s?recursive=1' % (REPO, commit_sha))
    return {n['path']: n['sha'] for n in tree.get('tree', []) if n.get('type') == 'blob'}


def main():
    if not TOKEN:
        print('缺少 GH_TOKEN')
        return 1
    version = sys.argv[1] if len(sys.argv) > 1 else 'v1.0.24'
    note = sys.argv[2] if len(sys.argv) > 2 else ''

    ref = gh('GET', '/repos/%s/git/ref/heads/main' % REPO)
    base_commit = ref['object']['sha']
    base_tree = gh('GET', '/repos/%s/git/commits/%s' % (REPO, base_commit))
    base_tree_sha = base_tree['tree']['sha']
    print('远端 main =', base_commit)

    want = local_files()
    have = remote_files(base_tree_sha)
    print('本地文件 %d 个，远端 %d 个' % (len(want), len(have)))

    # 1) 建 blob
    entries = []
    changed = 0
    for path in want:
        with io.open(os.path.join(ROOT, path), 'rb') as f:
            content = f.read()
        blob = gh('POST', '/repos/%s/git/blobs' % REPO,
                  {'content': base64.b64encode(content).decode('ascii'),
                   'encoding': 'base64'})
        if have.get(path) != blob['sha']:
            changed += 1
        entries.append({'path': path, 'mode': '100644', 'type': 'blob',
                        'sha': blob['sha']})
    # 2) 远端有、本地没有的文件 → 显式删除
    for path in have:
        if path not in want:
            entries.append({'path': path, 'mode': '100644', 'type': 'blob',
                            'sha': None})
            changed += 1
    print('blob 完成，变化条目 %d 个' % changed)

    # 3) 建 tree
    tree = gh('POST', '/repos/%s/git/trees' % REPO,
              {'base_tree': base_tree_sha, 'tree': entries})
    # 4) 建 commit
    msg = git('log', '-1', '--pretty=%B').strip() or ('release %s' % version)
    commit = gh('POST', '/repos/%s/git/commits' % REPO, {
        'message': msg, 'tree': tree['sha'], 'parents': [base_commit]})
    # 5) 更新 ref
    gh('PATCH', '/repos/%s/git/refs/heads/main' % REPO,
       {'sha': commit['sha'], 'force': False})
    print('main 已更新 →', commit['sha'])

    # 6) tag（已存在就先删掉重建 —— 脚本要能重复执行）
    try:
        gh('DELETE', '/repos/%s/git/refs/tags/%s' % (REPO, version))
        print('已删除同名旧 tag:', version)
    except Exception:  # noqa: BLE001
        pass
    tag = gh('POST', '/repos/%s/git/refs' % REPO,
             {'ref': 'refs/tags/' + version, 'sha': commit['sha']})
    print('tag', version, '=', tag['object']['sha'])

    # 7) 删掉旧 tag / 旧 Release（只保留这一版）
    rels = gh('GET', '/repos/%s/releases?per_page=100' % REPO)
    tags = gh('GET', '/repos/%s/git/matching-refs/tags/' % REPO)
    for t in tags:
        name = t['ref'].split('/')[-1]
        if name != version:
            print('删除旧 tag:', name)
            gh('DELETE', '/repos/%s/git/refs/tags/%s' % (REPO, name))
    for r in rels:
        # 同名 Release 也要先删掉重建（否则会出现两个同 tag 的 Release，
        # 其中一个的下载链接会变成 untagged-xxx）
        if r.get('tag_name') != version or True:
            if r.get('tag_name') == version:
                print('删除同名旧 Release:', r.get('tag_name'))
            else:
                print('删除旧 Release:', r.get('tag_name'))
            gh('DELETE', '/repos/%s/releases/%s' % (REPO, r['id']))

    # 8) 建 Release + 传 exe
    exe = os.path.join(ROOT, 'dingpan', 'dist', 'dingpan.exe')
    name = 'dingpan-%s-windows-x64.exe' % version
    body = {
        'tag_name': version,
        'name': '盯盘 %s（Windows x64 单文件）' % version,
        'body': note or ('盯盘 %s\n\n- 单文件绿色版，双击即用\n- 配置与备份默认在 exe 同目录'
                         % version),
        'draft': False,
        'prerelease': False,
    }
    release = gh('POST', '/repos/%s/releases' % REPO, body)
    print('Release 已建:', release['html_url'])

    upload_url = release['upload_url'].split('{')[0]
    data = io.open(exe, 'rb').read()
    req = urllib.request.Request(
        upload_url + '?name=' + urllib.parse.quote(name),
        data=data, method='POST',
        headers={'Authorization': 'Bearer ' + TOKEN,
                 'Content-Type': 'application/octet-stream',
                 'User-Agent': 'dingpan-publish'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            up = json.loads(r.read().decode('utf-8'))
        print('附件已上传:', up.get('browser_download_url'))
    except urllib.error.HTTPError as e:
        print('附件上传失败:', e.code, e.read().decode('utf-8', 'ignore')[:200])

    # 9) 校验远端文件集合与本地一致
    final = remote_files(commit['sha'])
    miss = [p for p in want if p not in final]
    extra = [p for p in final if p not in want]
    print('校验：本地 %d / 远端 %d，缺失 %s，多余 %s'
          % (len(want), len(final), miss or '无', extra or '无'))
    return 0 if not miss and not extra else 1


if __name__ == '__main__':
    import urllib.parse
    raise SystemExit(main())
