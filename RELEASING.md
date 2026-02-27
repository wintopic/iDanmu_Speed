# 发布清单（GitHub）

## 首次开源前

1. 创建仓库并推送代码
2. 确认仓库设置：
   - 默认分支 `main`
   - 启用 Issues / Pull Requests
   - 启用 Security（建议 private vulnerability reporting）
3. 确认首页文件：
   - `README.md`
   - `LICENSE`
   - `CONTRIBUTING.md`
   - `CODE_OF_CONDUCT.md`
   - `SECURITY.md`

## 本地自检

```powershell
python -m py_compile .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
python -m ruff check .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
```

## 建议首个版本

- 标签：`v0.2.0`
- Release Note 建议包含：
  - 纯 Python 下载器（无需 Node.js）
  - GUI / Mini GUI
  - 任务导入导出与批量下载
  - CI 与开源协作模板
