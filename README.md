# 盯盘 DingPan

> Windows 桌面股票盯盘工具 —— 纯 Win32 原生实现，绿色单文件，无 Python 运行时依赖。

一个常驻桌面的小悬浮窗，实时显示你自选股票的现价、涨跌幅等行情。
纯 `ctypes` 调用 Win32 API 写成，**不依赖任何第三方 GUI 框架**（无 PyQt / 无 Electron / 无 tkinter），
打包后是一个 ~8.5 MB 的独立 exe，丢到任何 Windows 机器上双击就能用。

![版本](https://img.shields.io/badge/version-v1.0.23-2563eb)
![Python](https://img.shields.io/badge/python-3.8%2B-3776ab)
![平台](https://img.shields.io/badge/platform-Windows%20x64-2ea44f)
![许可](https://img.shields.io/badge/license-MIT-blue)

---

## 特性

| | |
|---|---|
| **单文件绿色版** | 打包成一个 exe，不需要装 Python，不写注册表，双击即用 |
| **纯原生渲染** | `WS_EX_LAYERED` + `UpdateLayeredWindow` + 32bpp top-down DIB，**逐像素 alpha**，圆角、描边、半透明全部到位 |
| **两条透明度通道独立** | 背景不透明度与文字不透明度完全分开，可做「背景近透明、文字完全不透明」的效果 |
| **智能文字描边** | 背景越透明自动给文字加描边（浅底配深色描边 / 深底配浅色描边），保证任何背景下都清晰 |
| **背景可全透明** | 一个勾选框让背景完全透明（只剩文字浮在桌面上），滑块自动禁用 |
| **改完即生效** | 所有设置改完立即生效并自动保存，不需要点保存 |
| **自绘可勾选列表** | 设置页的自选股、显示字段列表都是自绘的：左复选框 / 中内容 / 右拖拽手柄，可勾选、可拖拽排序 |
| **绿色便携** | 配置和备份默认就在 exe 旁边，整个文件夹拷走即可带走全部设置；位置可自定义 |
| **完整显示方案** | 一个方案 = 一整套显示设置（字段 + 主题 + 颜色 + 两个透明度 + 字号 + 5 个显示开关） |
| **多数据源** | 腾讯财经 / 新浪财经 / 东方财富，失败自动降级；也可接入**自定义接口** |
| **自定义行情页跳转** | 雪球 / 腾讯 / 东财 / 新浪 / 同花顺，或自己填 URL 模板 |
| **托盘常驻** | 托盘图标显示/隐藏，右键菜单直接进设置；双击悬浮窗隐藏 |

## 界面

设置窗口共 9 个页面：

```
基础设置   行情数据源 / 刷新间隔 / 打开行情页平台 / 窗口标题 / 各类显示开关
自选管理   分组管理、添加股票（带代码校验）、勾选显示、拖拽排序
显示字段   单列表勾选显示的字段 + 拖拽排序，即悬浮窗各列的排列顺序
样式外观   主题 / 背景色 / 文字色 / 两个不透明度 / 字号 / 涨跌色 / 显示方案
备份恢复   导出 / 导入 / WebDAV 自动同步
快捷键     全局快捷键录制
关于       版本信息
```

## 快速开始

### 直接用

1. 到 [Releases](https://github.com/since02/dingpan/releases) 下载 `dingpan.exe`
2. 双击运行 → 托盘出现图标 → 双击托盘图标显示悬浮窗
3. 右键托盘图标 →「设置…」→ 自选管理 → 添加你的股票代码

### 从源码构建

需要 Python 3.8+ 和 PyInstaller：

```bash
git clone <repo-url>
cd <repo>
pip install pyinstaller

# 构建（产物在 dingpan/dist/dingpan.exe）
python dingpan/tools/build.py
```

> Windows 下若旧版 exe 正在运行会导致构建失败，`build.py` 已自动处理（先把旧文件改名让开）。

### 跑测试

项目带 19 个自动化检查套件，全部在进程内跑，不需要启动 GUI：

```bash
cd dingpan
python tools/selftest.py          # 单元自检
python tools/api_audit.py         # ctypes 函数签名审计
python tools/api_coverage.py      # Win32 API 的 DLL 归属与 argtypes 检查
python tools/static_check.py      # 静态规则（禁用 API、危险模式）
python tools/style_check.py       # 样式与透明度像素级回归
python tools/visual_check.py      # 界面截图验收
python tools/v18_check.py         # 功能专项回归
# ... 等
```

## 行情数据源

| 数据源 | 接口 | 说明 |
|---|---|---|
| 腾讯财经 | `qt.gtimg.cn` | GBK 编码，支持北交所；字段最全 |
| 新浪财经 | `hq.sinajs.cn` | 需带 `Referer` 头 |
| 东方财富 | `push2.eastmoney.com` | 需 `÷100` 换算 |

三者互为降级：主源失败会自动切到备用源，悬浮窗不会空着。

### 自定义数据源

在「基础设置 → 行情数据源」选「自定义接口…」，填：

| 填什么 | 说明 |
|---|---|
| 接口地址 | 如 `https://api.example.com/quote?codes={codes}`，`{codes}` 会替换成代码列表 |
| 字段映射 | `内部字段=接口返回的字段名`，逗号分隔，如 `name=name,price=last` |
| 编码 | `utf-8`（默认）/ `gbk` |
| 代码字段名 | 返回体里代码所在的键，默认 `code` |

返回体支持两种格式：

```json
{"sh600519": {"name": "贵州茅台", "last": 1688.0}}
```

```json
[{"code": "sh600519", "name": "贵州茅台", "last": 1688.0}]
```

没给 `change` / `changePct` 也没关系，程序会按「现价 − 昨收」自己算。

## 配置存放位置

**默认全部在主程序文件夹内**（绿色便携）：

```
<程序目录>\dingpan-config.json       主配置
<程序目录>\dingpan-cache.json        行情缓存
<程序目录>\dingpan-backups\          备份文件夹
<程序目录>\dingpan-location.json     记录自定义存储位置的指针
<程序目录>\crash.log                 崩溃日志（异常时写这里）
```

- 整个文件夹拷走 = 连同全部设置和备份一起带走。
- 程序文件夹不可写时自动降级到 `%APPDATA%\DingPan`。
- **可在「基础设置 → 存储位置」自定义**配置文件目录和备份文件目录。

## 项目结构

```
dingpan/
├── src/dingpan/          # 应用本体（约 8100 行）
│   ├── win32.py          #   Win32 / GDI API 声明与封装
│   ├── widget.py         #   分层窗口渲染
│   ├── app.py            #   主控、托盘、刷新线程
│   ├── settings.py       #   设置窗口（9 页）
│   ├── storage.py        #   配置读写、深合并、显示方案
│   ├── quotes.py         #   行情源与自定义接口
│   ├── icon.py           #   图标绘制
│   └── dialogs.py        #   通用对话框
├── tools/                # 构建与测试（约 5200 行，24 个脚本）
│   ├── build.py          #   PyInstaller 打包
│   ├── launcher_template.py
│   └── *_check.py        #   各类检查脚本
└── dist/dingpan.exe      # 构建产物（不入版本库）
```

## 技术要点

这个项目踩过的坑基本都在 `.workbuddy/memory/MEMORY.md` 里，总结几条最关键的：

- **owner-draw 的 `WM_DRAWITEM` 在部分 Windows 上不触发**，列表会画成空白。
  可行路子是**子类化原生 LISTBOX 后拦截 `WM_PAINT` 自己画**。
- **自绘必须用 `GetDC` 而不是 `BeginPaint`**：后者的 DC 被裁剪到「更新区域」，
  而更新区域按系统行高算 → 同一行被画到两个位置 → 重影。
- **不能用 `LB_SETCURSEL` 改选中**：原生 listbox 会立刻用自己的样式画一遍选中行，覆盖自绘。
  选中行号得存在自己这边。
- **ctypes 的 `argtypes` 参数个数写错不会立刻报错**，而是让功能「静默失效」。
  所以有 `api_audit.py` 专门审计签名，`api_coverage.py` 核对 API 归属哪个 DLL。
- **透明度不能乘两次**（颜色预乘一次 + alpha 平面再乘一次 → 被打平方）。

## 已知限制

- 仅支持 Windows（x64 实测）。
- 行情数据来自公开接口，稳定性由第三方决定；程序已做多源自动降级。
- 自定义数据源需要用户自备可用接口。

## 许可

[MIT](LICENSE)

## 致谢

- 行情接口：腾讯财经 / 新浪财经 / 东方财富
- 图标与交互参考：[Win32 透明窗口](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features) 系列文档
