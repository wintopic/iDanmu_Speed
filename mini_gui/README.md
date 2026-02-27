# iDanmu Mini GUI

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
- `mini_gui\dist\iDanmuMini\iDanmuMini.exe`

说明：运行 EXE 不需要 Node.js。
