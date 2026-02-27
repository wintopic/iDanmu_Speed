# iDanmu_Speed Mini GUI

对应文件：`mini_gui.py`

适合“快速搜索 -> 一键加入全集 -> 直接下载”的轻量场景。

## 启动

```powershell
.\run-mini-gui.bat
```

或：

```powershell
python .\mini_gui.py
```

默认服务地址是 `http://127.0.0.1:9321`，程序会自动从 `..\danmu_api-main` 启动本地 API（首次会自动执行 `npm install`）。

## 功能

- 自动解析服务地址中的 token
- 搜索来源并展示结果
- 一键加入所选来源全集
- 队列去重（按 commentId）
- 实时日志与停止任务
- 支持手动全屏切换：`F11` 切换、`Esc` 退出全屏

## 打包

```powershell
.\build-mini-exe.bat
```

输出：
- `mini_gui\dist\iDanmu_Speed_Mini\iDanmu_Speed_Mini.exe`

说明：使用纯本地 API 时需要本机可用的 Node.js + npm。


