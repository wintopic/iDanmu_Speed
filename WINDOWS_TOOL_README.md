# Windows CLI 使用说明

命令行工具：`danmu_batch_downloader.py`

## 环境要求

- Windows
- Python 3.10+
- Node.js 18+ 与 npm（启用纯本地 API 时需要）

## 快速开始

```powershell
python .\danmu_batch_downloader.py --help
```

示例：

```powershell
python .\danmu_batch_downloader.py `
  --input .\tasks.jsonl `
  --base-url http://127.0.0.1:9321 `
  --token 87654321 `
  --output .\downloads `
  --format xml `
  --concurrency 6 `
  --retries 5 `
  --retry-delay-ms 1500 `
  --throttle-ms 120 `
  --timeout-ms 45000
```

默认参数 `--local-api auto` 会在 `base-url` 为本地地址时自动启动 `danmu_api-main`。

也可以：

```powershell
.\download.bat --input .\tasks.jsonl --base-url http://127.0.0.1:9321 --token 87654321
```

手动启动本地 API（可选）：

```powershell
.\run-local-api.bat
```

## 任务输入

支持 `jsonl / json / csv`。每条任务至少满足一种模式：

1. `url`
2. `commentId`
3. `fileName`（调用 `/api/v2/match`）
4. `anime + episode`（调用 `/api/v2/search/episodes`）

可选字段：

- `format`：`json` / `xml`
- `disabled`：`true` 时跳过

## 输出结果

默认输出目录 `downloads/`，包含：

- 下载文件（按命名规则输出）
- `download-report.json`

## 限流建议

服务端有限流时：

- 增大 `--throttle-ms`（例如 `1000`、`2000`）
- 适当降低 `--concurrency`
- 保留 `--retries`
