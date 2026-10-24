#!/usr/bin/env python
"""
打包为单文件 exe（PyInstaller onefile，零控制台窗口）
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 项目根（tools 的上一级）
SRC = os.path.join(ROOT, 'src')
DIST = os.path.join(ROOT, 'dist')
BUILD = os.path.join(ROOT, 'build_tmp')
ICON = os.path.join(ROOT, 'tools', 'assets', 'icon.ico')
MANIFEST = os.path.join(ROOT, 'tools', 'app.manifest')
ENTRY = os.path.join(ROOT, 'launcher.py')

LAUNCHER_TEMPLATE = os.path.join(HERE, 'launcher_template.py')

# 注意：selectors 是 ssl 的隐式依赖，绝对不能排除（行情走 HTTPS）
EXCLUDES = [
    # GUI / 科学计算 / 测试工具 —— 一律不需要
    'tkinter', 'numpy', 'PIL', 'matplotlib', 'pytest', 'IPython',
    # 打包与开发工具
    'setuptools', 'pip', 'wheel', 'pkg_resources', 'distutils', 'venv',
    # 标准库无关模块
    'unittest', 'doctest', 'pydoc', 'lib2to3', 'test', 'multiprocessing',
    'asyncio', 'curses', 'turtle', 'sqlite3',
    'socketserver', 'http.server', 'ftplib', 'imaplib', 'poplib',
    'smtplib', 'telnetlib', 'zoneinfo', 'lzma', 'bz2',
    'difflib', 'pdb', 'profile', 'pstats', 'timeit', 'tabnanny',
    'tkinter.font', 'tkinter.ttk', 'ctypes.macholib',
]


def write_buildinfo():
    """生成构建信息（版本 + 时间戳），用于在界面上确认运行的是哪个版本"""
    import datetime
    tag = datetime.datetime.now().strftime('%m-%d %H:%M')
    path = os.path.join(SRC, 'dingpan', '_buildinfo.py')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# 由 build.py 自动生成，请勿手改\n')
        f.write("BUILD_TAG = '%s'\n" % tag)
    print('[build] 构建标识: %s' % tag)
    return path


def _free_old_exe():
    """构建前把旧的 dist/dingpan.exe 让开。

    用户很可能正开着盯盘 → 旧 exe 被进程锁住，PyInstaller 删不掉就直接构建失败
    （OSError: [safe-delete] 操作失败）。
    同卷改名在 Windows 上是允许的（哪怕文件被占用），改完名 PyInstaller
    就能创建新的 exe。改名后的旧文件等进程退出后再删。
    """
    exe = os.path.join(DIST, 'dingpan.exe')
    if not os.path.isfile(exe):
        return
    old = exe + '.old'
    for i in range(3):
        try:
            if os.path.exists(old):
                os.remove(old)
        except OSError:
            pass
        try:
            os.replace(exe, old)
            print('[build] 旧 exe 正在被占用，已改名为 %s（关掉程序后可删除）'
                  % os.path.basename(old))
            return
        except OSError as e:
            print('[build] 改名旧 exe 失败（第 %d 次）: %s' % (i + 1, e))
    print('[build] 警告：旧 exe 仍被占用，PyInstaller 可能无法覆盖')


def main():
    os.makedirs(DIST, exist_ok=True)
    write_buildinfo()
    shutil.copyfile(LAUNCHER_TEMPLATE, ENTRY)
    _free_old_exe()

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onefile',
        '--windowed',
        '--clean',
        '--name', 'dingpan',
        '--icon', ICON,
        '--manifest', MANIFEST,
        '--paths', SRC,
        '--distpath', DIST,
        '--workpath', BUILD,
        '--specpath', BUILD,
        '--optimize', '2',
        '--strip',
        '--noupx',
        '--python-option', 's',   # 不生成 .pyc
    ]
    for m in EXCLUDES:
        cmd += ['--exclude-module', m]

    # 只收集必需资源（图标已base64内嵌，无需外部文件）
    cmd += [ENTRY]

    print('[build] ' + ' '.join(cmd[:6]) + ' ...')
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print('[build] 打包失败')
        return 1

    exe = os.path.join(DIST, 'dingpan.exe')
    if os.path.isfile(exe):
        sz = os.path.getsize(exe)
        print(f'[build] 完成: {exe}  {sz/1024/1024:.2f} MB')
    # 清掉历史命名的产物，避免用户点到旧文件
    for old in ('盯盘.exe', '盯盘'):
        p = os.path.join(DIST, old)
        if os.path.isfile(p):
            try:
                os.remove(p)
                print('[build] 已删除旧产物: %s' % old)
            except OSError:
                pass
    # 清掉中间的 build_tmp（约 23 MB），只留 dist 里的成品
    try:
        if os.path.isdir(BUILD):
            shutil.rmtree(BUILD, ignore_errors=True)
            print('[build] 已清理中间目录 build_tmp')
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
