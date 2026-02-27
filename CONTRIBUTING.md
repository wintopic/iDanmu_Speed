# Contributing

感谢贡献。

## 提交前检查

```powershell
python -m py_compile .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
python -m ruff check .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
```

## 分支建议

- `feat/<name>`
- `fix/<name>`
- `docs/<name>`

## 提交信息建议

- `feat: ...`
- `fix: ...`
- `docs: ...`
- `refactor: ...`
- `chore: ...`

## Pull Request 建议内容

1. 改动目的
2. 改动范围
3. 验证方法
4. 是否包含破坏性变更

如涉及 UI，请附截图或录屏。
