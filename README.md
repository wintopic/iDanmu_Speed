# iDanmu_Speed Toolkit

面向 Windows 的弹幕批量下载工具集。

包含：
- `danmu_batch_downloader.py`：命令行批量下载器
- `danmu_gui.py`：完整版 GUI
- `mini_gui/mini_gui.py`：轻量版 GUI

## 功能

- 支持 4 种任务模式：`url` / `commentId` / `fileName` / `anime+episode`
- 支持任务输入：`jsonl` / `json` / `csv`
- 支持输出格式：`json` / `xml`
- 支持并发、重试、节流、超时
- 自动生成 `download-report.json`
- GUI 支持搜索、选集、队列导入导出

## 环境要求

- Windows 10/11（推荐）
- Python 3.10+
- Node.js 18+ 与 npm（启用纯本地 API 时需要）

## 快速开始

### CLI

```powershell
python .\danmu_batch_downloader.py --help
```

```powershell
python .\danmu_batch_downloader.py `
  --input .\tasks.jsonl `
  --base-url http://127.0.0.1:9321 `
  --token 87654321 `
  --output .\downloads
```

说明：默认 `--local-api auto`，当 `base-url` 指向 `localhost/127.0.0.1` 时会自动从 `danmu_api-main` 安装依赖并启动本地服务。

### 完整 GUI

```powershell
.\run-gui.bat
```

或：

```powershell
python .\danmu_gui.py
```

说明：GUI 默认连接 `http://127.0.0.1:9321`，会在首次请求时自动拉起本地 `danmu_api-main`。

### Mini GUI

```powershell
.\mini_gui\run-mini-gui.bat
```

或：

```powershell
python .\mini_gui\mini_gui.py
```

说明：Mini GUI 同样默认本地地址并自动拉起本地 API。

### 手动启动本地 API（可选）

```powershell
.\run-local-api.bat
```

## 任务文件格式

每条任务至少满足一种模式。

### JSONL

```json
{"name":"第1集","commentId":123456}
{"name":"第2集","url":"https://v.qq.com/x/cover/xxx.html"}
{"name":"第3集","fileName":"某剧 S01E03"}
{"name":"第4集","anime":"某剧","episode":"4","format":"xml"}
```

### JSON

```json
[
  { "name": "第1集", "commentId": 123456 },
  { "name": "第2集", "url": "https://v.qq.com/x/cover/xxx.html" }
]
```

### CSV

```csv
name,commentId,url,fileName,anime,episode,format,disabled
第1集,123456,,,,,json,false
第2集,,https://v.qq.com/x/cover/xxx.html,,,,json,false
```

## CLI 参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--input <path>` | 任务文件路径（必填） | - |
| `--base-url <url>` | API 地址 | `http://127.0.0.1:9321` |
| `--token <token>` | Token（可选） | 空 |
| `--output <dir>` | 输出目录 | `downloads` |
| `--format <json\|xml>` | 默认输出格式 | `xml` |
| `--naming-rule <tpl>` | 输出命名模板 | `{index:03d}_{base}` |
| `--concurrency <n>` | 并发数 | `6` |
| `--retries <n>` | 重试次数 | `5` |
| `--retry-delay-ms <ms>` | 重试基础延时 | `1500` |
| `--throttle-ms <ms>` | 任务启动节流 | `120` |
| `--timeout-ms <ms>` | 请求超时 | `45000` |
| `--local-api <auto\|on\|off>` | 本地 API 自动拉起策略 | `auto` |

## 打包 EXE

```powershell
.\build-exe.bat
.\mini_gui\build-mini-exe.bat
```

输出：
- `dist\iDanmu_Speed.exe`
- `mini_gui\dist\iDanmu_Speed_Mini.exe`

说明：EXE 运行时不需要 Node.js。
如果要使用纯本地 API（`danmu_api-main`），仍需要本机可用的 Node.js + npm。

## 校验命令

```powershell
python -m py_compile .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
python -m ruff check .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
```

## 文档索引

- 完整 GUI：[GUI_README.md](./GUI_README.md)
- Mini GUI：[mini_gui/README.md](./mini_gui/README.md)
- CLI：[WINDOWS_TOOL_README.md](./WINDOWS_TOOL_README.md)
- 发布清单：[RELEASING.md](./RELEASING.md)

## 致谢

- 弹幕获取方法代码来源：[huangxd-/danmu_api](https://github.com/huangxd-/danmu_api)

## 开源协作

- [CONTRIBUTING.md](./CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- [SECURITY.md](./SECURITY.md)
- [CHANGELOG.md](./CHANGELOG.md)

## 免责声明

- 本项目仅用于学习和技术研究。
- 使用者应遵守当地法律法规与平台条款。
- 因不当使用造成的后果由使用者自行承担。

## License

[MIT](./LICENSE)


