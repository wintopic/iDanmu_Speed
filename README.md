# iDanmu Toolkit

涓€涓潰鍚?Windows 鐨勫脊骞曟壒閲忎笅杞藉伐鍏烽泦锛堢函 Python 杩愯鏃讹紝涓嶄緷璧?Node.js锛夈€?
鍖呭惈锛?
- `danmu_batch_downloader.py`锛氬懡浠よ鎵归噺涓嬭浇鍣?- `danmu_gui.py`锛氬畬鏁寸増 GUI
- `mini_gui/mini_gui.py`锛氳交閲忕増 GUI

## 鍔熻兘

- 鏀寔 4 绉嶄换鍔℃ā寮忥細`url` / `commentId` / `fileName` / `anime+episode`
- 鏀寔浠诲姟杈撳叆锛歚jsonl` / `json` / `csv`
- 鏀寔杈撳嚭鏍煎紡锛歚json` / `xml`
- 鏀寔骞跺彂銆侀噸璇曘€佽妭娴併€佽秴鏃?- 鑷姩鐢熸垚 `download-report.json`
- GUI 鏀寔鎼滅储銆侀€夐泦銆侀槦鍒楀鍏ュ鍑?
## 鐜瑕佹眰

- Windows 10/11锛堟帹鑽愶級
- Python 3.10+

## 蹇€熷紑濮?
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

### 瀹屾暣 GUI

```powershell
.\run-gui.bat
```

鎴栵細

```powershell
python .\danmu_gui.py
```

### Mini GUI

```powershell
.\mini_gui\run-mini-gui.bat
```

鎴栵細

```powershell
python .\mini_gui\mini_gui.py
```

## 浠诲姟鏂囦欢鏍煎紡

姣忔潯浠诲姟鑷冲皯婊¤冻涓€绉嶆ā寮忋€?
### JSONL

```json
{"name":"绗?闆?,"commentId":123456}
{"name":"绗?闆?,"url":"https://v.qq.com/x/cover/xxx.html"}
{"name":"绗?闆?,"fileName":"鏌愬墽 S01E03"}
{"name":"绗?闆?,"anime":"鏌愬墽","episode":"4","format":"xml"}
```

### JSON

```json
[
  { "name": "绗?闆?, "commentId": 123456 },
  { "name": "绗?闆?, "url": "https://v.qq.com/x/cover/xxx.html" }
]
```

### CSV

```csv
name,commentId,url,fileName,anime,episode,format,disabled
绗?闆?123456,,,,,json,false
绗?闆?,https://v.qq.com/x/cover/xxx.html,,,,json,false
```

## CLI 鍙傛暟

| 鍙傛暟 | 璇存槑 | 榛樿鍊?|
|---|---|---|
| `--input <path>` | 浠诲姟鏂囦欢璺緞锛堝繀濉級 | - |
| `--base-url <url>` | API 鍦板潃 | `http://127.0.0.1:9321` |
| `--token <token>` | Token锛堝彲閫夛級 | 绌?|
| `--output <dir>` | 杈撳嚭鐩綍 | `downloads` |
| `--format <json\|xml>` | 榛樿杈撳嚭鏍煎紡 | `json` |
| `--concurrency <n>` | 骞跺彂鏁?| `6` |
| `--retries <n>` | 閲嶈瘯娆℃暟 | `3` |
| `--retry-delay-ms <ms>` | 閲嶈瘯闂撮殧锛堝熀纭€锛?| `4000` |
| `--throttle-ms <ms>` | 浠诲姟鍚姩鑺傛祦 | `0` |
| `--timeout-ms <ms>` | 璇锋眰瓒呮椂 | `45000` |

## 鎵撳寘 EXE

```powershell
.\build-exe.bat
.\mini_gui\build-mini-exe.bat
```

杈撳嚭锛?
- `dist\iDanmu\iDanmu.exe`
- `mini_gui\dist\iDanmuMini\iDanmuMini.exe`

璇存槑锛欵XE 杩愯鏃朵笉闇€瑕?Node.js銆?
## 鏍￠獙鍛戒护

```powershell
python -m py_compile .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
python -m ruff check .\danmu_batch_downloader.py .\danmu_gui.py .\mini_gui\mini_gui.py
```

## 鏂囨。绱㈠紩

- 瀹屾暣 GUI锛歔GUI_README.md](./GUI_README.md)
- Mini GUI锛歔mini_gui/README.md](./mini_gui/README.md)
- CLI锛歔WINDOWS_TOOL_README.md](./WINDOWS_TOOL_README.md)
- 鍙戝竷娓呭崟锛歔RELEASING.md](./RELEASING.md)

## 寮€婧愬崗浣?
- [CONTRIBUTING.md](./CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- [SECURITY.md](./SECURITY.md)
- [CHANGELOG.md](./CHANGELOG.md)

## 鍏嶈矗澹版槑

- 鏈」鐩粎鐢ㄤ簬瀛︿範鍜屾妧鏈爺绌躲€?- 浣跨敤鑰呭簲閬靛畧褰撳湴娉曞緥娉曡涓庡钩鍙版潯娆俱€?- 鍥犱笉褰撲娇鐢ㄩ€犳垚鐨勫悗鏋滅敱浣跨敤鑰呰嚜琛屾壙鎷呫€?
## License

[MIT](./LICENSE)

