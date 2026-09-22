# GSR 鈥斺€?闈㈠悜 MobileBench-OL 鐨勩€屾墽琛岄『搴?鈫?鎴愬姛鐜囥€嶅疄楠屽伐浣滃彴

> 璇鹃锛?*闈㈠悜绉诲姩 GUI 鏅鸿兘浣撹瘎娴嬬殑搴旂敤鐘舵€佹薄鏌撴娴嬪拰鎭㈠鏂规硶鐮旂┒**锛堝紑棰樻姤鍛婅 `寮€棰樻姤鍛?鈥?md`锛?>
> 鏈粨搴撴湇鍔′簬鍏朵腑涓€涓叿浣撳疄楠岋細
> **OD Flaky tests 鏄惁褰卞搷鎴愬姛鐜囷紵鏌愪釜浠诲姟鍥犱负鎵ц椤哄簭鍙樺寲鑰屽け璐?*
> - 椤哄簭鎵ц vs. 涔卞簭鎵ц
> - 澶氫釜 Agent

**鏍稿績鏈哄埗**锛歁obileBench-OL 鐨勬墽琛岄『搴?= **CSV 琛屽簭**锛坄load_tasks()` 鐢?`csv.DictReader` 椤哄簭璇汇€佹棤鎺掑簭鏃犳墦涔憋級銆?鎵€浠?鎵撲贡浠诲姟"= 鐢熸垚鍚屼竴鎵逛换鍔＄殑鍙︿竴浠借搴忔帓鍒楃殑 CSV 鈥斺€?鏈粨搴撴彁渚涚敓鎴愬櫒銆?
**鏈枃妗ｆ墍鏈夊懡浠ら兘鍐欐垚 CMD 鐗堟湰**锛圵indows 鍛戒护鎻愮ず绗︼紝鍙洿鎺ョ矘璐达級銆?涓や釜鍏ュ彛 `run_mbl.cmd` / `pilot.cmd` 鏄?PowerShell 鑴氭湰鐨勫寘瑁咃紝鐜鍙橀噺浼氳嚜鍔ㄨ浇鍏ワ紝cmd 閲屼笉闇€瑕佷簨鍏?`set` 浠讳綍涓滆タ銆?锛堟兂鐢?PowerShell 鐩存帴璋冧篃鍙互锛歚powershell -NoProfile -File run_mbl.ps1 -TaskFile ... `锛?
---

## 鐩綍閫熸煡

| 璺緞 | 鍐呭 |
|---|---|
| `mobile.env.ps1` | **鐜閰嶇疆**锛欰PI key銆佹ā鍨嬫敞鍐岃〃锛堝惈鍧愭爣绾﹀畾锛夈€佽矾寰勩€佽澶囧簭鍒楀彿 |
| `run_mbl.cmd` / `run_mbl.ps1` | 璺戜竴杞細鑷 鈫?鍐?manifest 鈫?鎵ц 鈫?鎻愮ず杞牸寮?|
| `pilot.cmd` / `pilot.ps1` | **涓€鏉″懡浠よ窇瀹屼袱杞『搴?+ 鑷姩鍒嗘瀽** |
| `experiments/docs/` | 01 鏁版嵁闆嗕笌 Agent 閫夊瀷銆?2 瀹為獙鏂规锛?脳2 鏋愬洜 / 鎸囨爣 / 鏍锋湰閲忥級 |
| `experiments/scripts/` | 鍏ㄩ儴鑴氭湰锛堣涓嬶級 |
| `third_party/mobilebench-ol-main/` | **宸叉墦琛ヤ竵**鐨?MobileBench-OL锛堟簮鐮?+ 鍏ㄥ CSV + 椤哄簭浠诲姟闆?+ reset 閰嶇疆锛?|
| `third_party/mobilebench-ol-main/results/` | 杩愯浜х墿锛?*宸茶 .gitignore 鎺掗櫎**锛屼綋绉?3 GB+锛?|

**鑴氭湰娓呭崟**锛堥兘鍦?`experiments/scripts/`锛?
| 鑴氭湰 | 鐢ㄩ€?|
|---|---|
| `mbl_make_task_csv.py` | **鐢熸垚椤哄簭浠诲姟闆?*锛氬瓙闆?+ canonical / reverse / shuffle(seed) |
| `mbl_traj_to_episodes.py` | 鐪熸満缁撴灉 鈫?`episodes.jsonl`锛堝垎鏋愬櫒鐨勮緭鍏ワ級锛涘惈榛戝睆妫€娴?|
| `analyze_order_effects.py` | **鏍稿績鍒嗘瀽**锛?脳2 鏋愬洜銆佄擲R / CTCI / PASR / victim / polluter / DiD |
| `mbl_apply_api_patch.py` | 缁?MobileBench-OL 鎵撹ˉ涓侊紙骞傜瓑 / 鑷姩澶囦唤 / `--revert`锛?|
| `mbl_api_probe.py` | 闆朵緷璧栨帰娴嬬鐐癸紙妯″瀷鍙敤鎬с€乣--scan`銆乣--dump-models`锛?|
| `mbl_coord_convention_check.py` | **鍒ゅ畾妯″瀷鍧愭爣绾﹀畾**锛坣orm / pixel锛夆€斺€?鎹㈡ā鍨嬪繀璺?|
| `mbl_app_checklist.py` | 鐢熸垚"瑕佽鍝簺 App"娓呭崟锛堝彲鏌ヨ澶囧凡瑁呮儏鍐碉級 |
| `mbl_task_audit.py` | 浠诲姟闆嗗璁★紙缂栫爜 / 鍧忚 / App / Reset 鏍囨敞 / reset 闆嗛噸鍙狅級 |
| `mbl_purge_tasks.py` | 闀胯窇鍚庢憳鎺?涓庡疄楠屾棤鍏崇殑澶辫触"锛堥粦灞忕瓑锛変互渚胯ˉ璺?|
| `mbl_find_actions.py` | **杞ㄨ抗鍙栬瘉**锛氭煡"鏄摢涓换鍔＄殑鍝竴姝ユ敼浜嗕粈涔? |
| `task_catalog.py` / `order_runner.py` / `make_sim_data.py` / `power_analysis.py` / `selftest.py` | AndroidWorld 閭ｆ潯閾捐矾锛堝彟涓€鏉¤矾绾匡紝宸查獙璇侊級 |

---

# A. 鏂版満鍣ㄩ儴缃诧紙6 姝ワ級

## 0) 鍓嶇疆
**Git** + **Python 3.10 鎴栦互涓?*锛堟湰浠撳簱瀹炴祴 3.10.7锛夈€?
```cmd
git --version
python --version
```

## 1) 鍏嬮殕锛堣矾寰勯殢鎰?鈥斺€?鑴氭湰宸叉敼涓鸿嚜鍔ㄥ畾浣嶏級

```cmd
set MBL=D:\GSR
git clone https://github.com/drunksu/GSR.git %MBL%
cd /d %MBL%
```

> `cd /d` 鍦?cmd 閲岃法鐩樼鍒囨崲蹇呴』鍔?`/d`銆?
## 2) 寤鸿櫄鎷熺幆澧冿紙鈽?鍚嶅瓧蹇呴』鍙?`mobile`锛屽繀椤诲湪浠撳簱鏍圭洰褰曪級

```cmd
python -m venv mobile
mobile\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
mobile\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple uiautomator2 pillow opencv-python numpy openai defusedxml lxml requests
```

> 鐢ㄦ竻鍗庨暅鍍忥細`pypi.org` 瀹樻柟婧愬湪鍥藉唴缃戠粶涓?TLS 鎻℃墜浼氳涓柇锛坄SSLEOFError`锛夈€?> cmd 閲岀画琛岀鏄?`^`锛堜笉鏄?PowerShell 鐨勫弽寮曞彿锛夛紝涓€琛屽啓涓嶄笅鏃舵墠闇€瑕併€?
## 3) adb 鈥斺€?**宸茬粡闅忎粨搴撴彁渚涳紝涓嶇敤涓嬭浇**

浠撳簱閲屽凡鍖呭惈 adb 杩愯蹇呴渶鐨?3 涓枃浠讹紙`adb.exe` + `AdbWinApi.dll` + `AdbWinUsbApi.dll`锛屽叡 8.1 MB锛夛紝
clone 瀹岀洿鎺ラ獙璇佸嵆鍙細

```cmd
third_party\platform-tools\adb.exe version
```

> **涓轰粈涔堥殢浠撳簱鎻愪緵**锛歐indows 鑷甫 curl 璧?schannel锛屼笅杞芥椂浼氬厛鍘?*鑱旂綉鏍￠獙璇佷功鍚婇攢鐘舵€?*锛?> 涓€鏃﹁繛涓嶄笂鍚婇攢鏈嶅姟鍣ㄥ氨鐩存帴澶辫触锛堟柊鏈哄櫒涓婂疄娴嬭俯鍒帮級锛?> ```
> curl: (35) schannel: next InitializeSecurityContext failed:
> CRYPT_E_REVOCATION_OFFLINE (0x80092013) - 鐢变簬鍚婇攢鏈嶅姟鍣ㄥ凡鑴辨満锛屽悐閿€鍔熻兘鏃犳硶妫€鏌ュ悐閿€銆?> ```

**鑻ヤ綘鎵嬩笂鏄棫鐗堟湰浠撳簱锛堟病鏈夎繖 3 涓枃浠讹級**锛屼换閫変竴绉嶆柟寮忚ˉ涓婏細

```cmd
rem 鏂瑰紡 1锛氳烦杩囧悐閿€妫€鏌ワ紙curl 8.x锛涙洿娓╁拰鐨勫啓娉曟槸 --ssl-revoke-best-effort锛?curl --ssl-no-revoke -L -o third_party\platform-tools.zip https://dl.google.com/android/repository/platform-tools-latest-windows.zip

rem 鏂瑰紡 2锛氭崲 PowerShell 涓嬭浇锛堣蛋 .NET锛屼笉鍋氬悐閿€妫€鏌ワ級
powershell -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile 'third_party\platform-tools.zip'"

rem 鏂瑰紡 3锛氭祻瑙堝櫒鎵嬪姩涓嬭浇锛屾斁鍒?third_party\ 涓?
rem 鐒跺悗瑙ｅ帇 + 楠岃瘉
tar -xf third_party\platform-tools.zip -C third_party
third_party\platform-tools\adb.exe version
```

> `tar` 鏄?Windows 10/11 鑷甫鐨勶紙`C:\Windows\System32\tar.exe`锛夛紝涓嶉渶瑕侀澶栧畨瑁呫€?
## 4) 鎵嬫満 + 鏀逛竴琛岄厤缃?
```cmd
third_party\platform-tools\adb.exe devices
notepad mobile.env.ps1
```

`notepad` 鎵撳紑鍚?*鍙敼 `$DEVICE` 閭ｄ竴琛?*锛堟崲鎴愭柊鎵嬫満鐨勫簭鍒楀彿锛夈€侫PI key 宸茬粡鍦ㄤ粨搴撻噷锛屼笉鐢ㄩ噸濉€?
鎵嬫満绔姹傦細

- 寮€ **USB 璋冭瘯**锛堝浗浜ф満鍨嬭繕瑕佸紑"USB 璋冭瘯锛堝畨鍏ㄨ缃級"锛?- **绯荤粺璇█涓枃**锛堟垚鍔熸潯浠舵槸涓枃鏂囨鐨?xpath锛?- **鍏呯數鏃朵繚鎸佸父浜?*锛堣 B1锛涚唲灞忎細閫犳垚鏁磋疆鍋囧け璐ワ級
- base 瀛愰泦鐨?**12 涓?App**锛欱绔?/ 缃戞槗浜?/ 鐣寗 / 鎷煎澶?/ QQ / 58鍚屽煄 / 鍚岃姳椤?/ 浠婃棩澶存潯 / 楂樺痉 / 鐧惧害 / 閽夐拤 / 缇庢煔锛?*瑕佺櫥褰?*锛屽緢澶氫换鍔′緷璧栬处鍙锋棦鏈夌姸鎬侊級

## 5) 鑷锛堜笉鎻掓墜鏈轰篃鑳借窇锛?
```cmd
run_mbl.cmd -TaskFile data\smoke_2task.csv -Output results\_selftest -DryRun
```

鐪嬪埌 `[run_mbl] 妯″瀷 = qwen3-vl-plus   鍧愭爣绾﹀畾 = norm` 鍗崇幆澧冨氨缁€?
## 6) 寮€璺?鈫?瑙佷笅闈?B 鑺?
---

# B. 杩愯鍛戒护

## B0 鍏堣濂借繖鍑犱釜鍙橀噺锛堟瘡涓柊鐨?cmd 绐楀彛璺戜竴娆★級

```cmd
set MBL=D:\GSR
set PY=%MBL%\mobile\Scripts\python.exe
set S=%MBL%\experiments\scripts
set REPO=%MBL%\third_party\mobilebench-ol-main
set ADB=%MBL%\third_party\platform-tools\adb.exe
cd /d %REPO%
```

> 鈿狅笍 **`set` 蹇呴』鍗曠嫭涓€琛?*銆俢md 鍦?*瑙ｆ瀽鏁磋鏃?*灏卞睍寮€ `%VAR%`锛屾墍浠?> `set PY=x && %PY% y.py` 杩欑鍐欐硶閲?`%PY%` 浼氬睍寮€鎴?*绌哄€?*锛堝疄娴嬭俯杩囷級銆?> 鈿狅笍 `set VAR=鍊糮锛氱瓑鍙蜂袱杈?*涓嶈兘鏈夌┖鏍?*锛屽€?*涓嶈鍔犲紩鍙?*锛堝紩鍙蜂細鍙樻垚鍊肩殑涓€閮ㄥ垎锛夈€?> 鈿狅笍 `cd /d` 鎹㈢洏绗︽椂蹇呴』鍔?`/d`銆?> 鈿狅笍 鑻ヤ綘鐨勮矾寰勫惈绌烘牸锛岃皟鐢ㄦ椂鍔犲紩鍙凤細`"%MBL%\run_mbl.cmd" ...`銆?
**涓轰粈涔堣 `cd` 鍒?`%REPO%`**锛歜enchmark 鐢ㄧ浉瀵硅矾寰?`data\...` 瑙ｆ瀽浠诲姟闆嗭紝杈撳嚭鐩綍 `results\...` 涔熻惤鍦?benchmark 鐩綍涓嬶紙涓庡畼鏂逛竴鑷达級銆?`%PY%` / `%S%` / `%ADB%` 閮芥槸**缁濆璺緞**锛屾墍浠ュ湪鍝釜鐩綍涓嬮兘鑳界敤銆?
## B1 鍞ら啋鎵嬫満锛?*姣忔闀胯窇鍓嶅繀鍋?*锛?
```cmd
%ADB% -s 浣犵殑搴忓垪鍙?shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
```

## B2 鍐掔儫锛? 涓?B绔欎换鍔★紙绾?3 鍒嗛挓锛?
```cmd
%MBL%\run_mbl.cmd -TaskFile data\smoke_2task.csv -Output results\smoke
```

## B3 鍏ㄩ噺涓ょ椤哄簭锛堜竴鏉″懡浠よ窇瀹屼袱杞?+ 鑷姩鍒嗘瀽锛?
```cmd
%MBL%\pilot.cmd -Tag base -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
```

- 310 涓换鍔?/ 涓€绉嶉『搴忕害 **3 灏忔椂**銆佺害 17 M tokens
- 鎶ュ憡鑷姩鐢熸垚鍦?`results\base_analysis\report.md`
- **涓柇涓嶇敤鎬?*锛氱粨鏋滄寜浠诲姟钀界洏锛岄噸璺戝悓涓€鏉″懡浠や細鑷姩缁窇锛堝凡瀹屾垚浠诲姟璺宠繃锛?
## B4 reset 閫氶亾锛堣窇 benchmark 鑷甫鐨?cleaner锛?
```cmd
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_smoke_2task.csv -Output results\reset_smoke
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\reset_r1
```

绗竴鏉℃槸 2 涓换鍔＄殑閫氶亾楠岃瘉锛堢害 3 鍒嗛挓锛夛紝绗簩鏉℃槸瀹屾暣鐨?65 涓换鍔★紙绾?40 鍒嗛挓锛夈€?
璺戝畬 `run_mbl.cmd` 浼?*鑷姩**鍦ㄥ悓鐩綍鐢熸垚 `episodes.jsonl`锛堣浆鏍煎紡宸插唴缃紝瑙佸潙 #10锛夈€傛墍浠ヨ鍗曠嫭杞崲鐨勫彧鏈夈€岀敤鍒殑鍔炴硶璺戠殑杞銆嶏細

```cmd
%PY% %S%\mbl_traj_to_episodes.py --run-dir results\reset_r1
```

鈿狅笍 **reset 蹇呴』鐢ㄧ嫭绔嬬殑 `-Output`**锛歳eset 闆嗙殑 65 涓?task_identifier 涓庝富闆?*瀹屽叏閲嶅彔**锛屽叡鐢ㄧ洰褰曚細璁╀富杩愯鎶婂畠浠綋鎴?宸插畬鎴?璺宠繃銆?
## B5 鎹㈡ā鍨?/ 澶?Agent 瀵规瘮

```cmd
%MBL%\pilot.cmd -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
```

**鍙敤妯″瀷涓庡潗鏍囩害瀹?*锛坄mobile.env.ps1` 閲岀殑娉ㄥ唽琛紱鈽?绾﹀畾濉敊 鈫?鎵€鏈夌偣鍑绘尋鍒板乏涓婅銆佷换鍔″叏鐏級

| 妯″瀷 | 绾﹀畾 | 澶囨敞 |
|---|---|---|
| `qwen3-vl-plus` | **norm** | 涓诲姏锛屽畾浣?1 px锛屽凡鏈?310 涓粨鏋?|
| `qwen3-vl-flash` | **norm** | 鍚屼唬鏇村急鏇翠究瀹?鈫?鏇村鏄撹惤鍦?0.2鈥?.8 淇″彿甯︼紝**鎺ㄨ崘褰撶浜屼釜 Agent** |
| `qwen3-vl-plus-2025-12-19` | **norm** | 鏃ユ湡蹇収 鈫?鍙仛鐗堟湰娑堣瀺 |
| `qwen3.8-omni-flash` / `qwen3.5-omni-plus` | **norm** | 鏇存柊涓栦唬锛屽疄娴嬬簿纭?|
| `qwen-vl-max` | **pixel** | 鑰佷笘浠ｏ紝鍚堟垚鍥惧畾浣嶅亸 630 px |
| `gui-plus` | **pixel** | GUI 涓撶敤浣嗗畾浣嶆渶宸紙鍋?890 px锛?|
| `qwen-vl-plus` | norm锛堟帹娴嬶級 | 杈撳嚭鏍煎紡鏈夌偣鑴?|
| `qwen3-vl-max` / `qwen2.5-vl-7b/72b-instruct` | 鈥?| **涓嶅彲鐢?*锛?04 / 403锛?|

**鍔犳柊妯″瀷**锛氬厛璺戝潗鏍囨娴嬶紙杩欎袱涓瘖鏂剼鏈蛋鏍囧噯搴撶洿杩?API銆佷笉缁忚繃 PowerShell锛屾墍浠ヨ鑷繁 `set`锛沰ey 鍙粠 `mobile.env.ps1` 閲屽鍒讹級锛?
```cmd
set MBL_API_KEY=sk-浣犵殑key
%PY% %S%\mbl_coord_convention_check.py --model 鏂版ā鍨嬪悕 --repo %REPO%
```

## B6 鐢熸垚鏂扮殑椤哄簭浠诲姟闆?
```cmd
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order reverse --out base_reverse.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order shuffle --seed 1 --out base_shuffle1.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --limit 30 --order shuffle --seed 0 --out sub30_shuffle0.csv
```

> `--out` 鍐欐垚绾枃浠跺悕鏃讹紝杈撳嚭钀藉埌 `%REPO%\data\` 涓嬶紱鏂囦欢鍚嶅繀椤诲惈 `shuffle<鏁板瓧>` 鎵嶄細琚?manifest 璇嗗埆涓轰贡搴忓苟璁板綍 seed銆?
## B7 闀胯窇鍚庣殑娓呮礂涓庤ˉ璺?
```cmd
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-only --dry-run
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-only
```

鎽樻帀閭ｄ簺涓庨『搴忔棤鍏崇殑澶辫触锛堥粦灞忕瓑锛変箣鍚庯紝閲嶈窇 B3 灏变細鑷姩琛ヨ窇瀹冧滑銆?
## B8 鍗曠嫭鍑烘姤鍛?
```cmd
%PY% %S%\analyze_order_effects.py --input results\base_canonical\episodes.jsonl results\base_shuffle\episodes.jsonl --out results\base_analysis --official-condition none
type results\base_analysis\report.md
```

## B9 鍏朵粬甯哥敤鏌ョ湅鍛戒护

```cmd
type results\base_canonical\result_list.txt
dir /b results\base_canonical | find /c /v ""
notepad results\base_analysis\report.md
```

---

# C. 鍚屾鏂瑰紡

## C1 涓婁紶鑷繁鐨勫疄楠岀粨鏋滐紙**姣忚疆璺戝畬閮借鍋?*锛?
```cmd
cd /d "D:\projects\GUI state recovery"
git add -A
git commit -m "results: base_shuffle 310/310"
git push
```

`git add -A` 涔嬪悗**鍏堢湅涓€鐪煎皢瑕佹彁浜や粈涔?*锛屽埆鐩叉帹锛?
```cmd
git status --short
git diff --cached --stat
```

鍙鐪嬪埌 `results\...\episodes.jsonl`銆乣run_manifest.json`銆乣trajectory.json`銆乣result_list.txt`銆乣*_analysis\report.md` 鍑虹幇鍦ㄥ垪琛ㄩ噷锛屽氨鏄鐨勩€?**濡傛灉鍒楄〃閲屼竴涓?`results\` 閮芥病鏈?鈫?鍋滐紝鍏堢湅鍧?#9銆?*

## C2 鎷夊彇鍒汉鐨勭粨鏋?
```cmd
cd /d "D:\projects\GUI state recovery"
git stash
git pull
git stash pop
```

`git stash` 鍙槸涓轰簡淇濇姢浣犲彲鑳借繕鍦ㄦ敼鐨勬湰鍦版枃浠讹紱宸ヤ綔鍖哄共鍑€鏃跺彲浠ヨ烦杩囥€?
## C3 浠€涔堜細鍚屾銆佷粈涔堜笉浼?
| 浼氬悓姝ワ紙绾?3.2 MB锛?| 涓嶄細鍚屾 |
|---|---|
| 浠ｇ爜銆侀厤缃€佹枃妗?| `step_*.png` / `step_*.xml` / `*_som.png`锛堟埅鍥句笌鍏冪礌鏍戯紝3 GB+锛?|
| `results\*\episodes.jsonl`锛堟瘡浠诲姟涓€琛岋紝鍒ゅ畾+姝ユ暟锛?| `mobile\`锛坴env锛?45 MB锛?|
| `results\*\run_manifest.json`锛堣繖涓洰褰曟槸鍝椤哄簭/鏉′欢锛?| `third_party\platform-tools.zip` |
| `results\*\*\trajectory.json`銆乣api_metrics.jsonl`銆乣step_timing.jsonl`銆乣result_list.txt` | `paper\`锛堝弬鑰冭鏂?PDF锛?|
| `results\*_analysis\report.md` 绛夊垎鏋愪骇鐗?| `experiments\results\sim\`锛堝悎鎴愭暟鎹紝鍙噸鐢熸垚锛?|
| adb锛坄adb.exe` + 2 涓?DLL锛?.1 MB锛岃 A3锛?| |

---

# D. 涔濅釜蹇呰俯鐨勫潙

| # | 鍧?| 鍚庢灉 / 瀵圭瓥 |
|---|---|---|
| 1 | **鍧愭爣绾﹀畾** | 妯″瀷杈撳嚭 0鈥?000 褰掍竴鍖栧潗鏍囪€屼唬鐮佸綋鍍忕礌鐢?鈫?鎵€鏈夌偣鍑绘尋鍒板乏涓婅銆?*浠诲姟鍏ㄧ伃涓旂湅涓嶅嚭鍘熷洜**銆傚绛栵細娉ㄥ唽琛?+ `MBL_COORD`锛屾崲妯″瀷蹇呰窇妫€娴?|
| 2 | **`-Output` 鐩綍澶嶇敤** | `result_list.txt` 鏄画璺戠紦瀛橈紝閲嶅悕浼氳浠诲姟**鍏ㄩ儴琚烦杩?*銆傚绛栵細姣忕椤哄簭鐢ㄧ嫭绔嬬洰褰?|
| 3 | **venv 蹇呴』鍙?`mobile` 涓斿湪浠撳簱鏍?* | `mobile.env.ps1` 閲?`$PY = "$MBL_ROOT\mobile\Scripts\python.exe"` |
| 4 | **鎵嬫満鐔勫睆** | 鎴浘鍏ㄩ粦 鈫?鏁磋疆鍙樻垚"鍋囧け璐?锛屼笌姹℃煋鏃犲叧銆傚绛栵細B1 鍞ら啋 + 淇濇寔鍏呯數锛涘垎鏋愬墠鐢?`mbl_purge_tasks.py --blank-only` 鍓旈櫎 |
| 5 | **cmd 閲屽啓涓枃娉ㄩ噴** | cmd.exe 鐢ㄦ湰鍦颁唬鐮侀〉锛堜腑鏂?Windows 鏄?GBK锛夎 `.bat/.cmd`锛孶TF-8 涓枃浼氳璇銆乣rem` 琛屾柇鎺夊悗琚綋鎴愬懡浠ゆ墽琛屻€?*鎵瑰鐞嗘枃浠朵竴寰嬬函 ASCII**锛堟湰浠撳簱鐨?`.cmd` 宸查伒瀹堬紱鎯冲啓涓枃璇存槑灏卞啓杩?`.md`锛?|
| 6 | **cmd 閲?`set` 涓?`%VAR%` 鍐欏湪鍚屼竴琛?* | cmd 鍦?*瑙ｆ瀽鏁磋鏃?*灏卞睍寮€ `%VAR%`锛宍set PY=x && %PY% y.py` 浼氳 `%PY%` 鍙樻垚绌哄€笺€?*`set` 蹇呴』鍗曠嫭涓€琛?*锛堝疄娴嬭俯杩囷級 |
| 7 | **鐩稿璺緞鐨勫熀鍑嗙洰褰?* | `results\...` 鏄浉瀵?benchmark 鐩綍锛宍mobile\Scripts\...` 鏄浉瀵逛粨搴撴牴 鈥斺€?娣风敤浼氭姤"鏂囦欢涓嶅瓨鍦?銆傚绛栵細鎸?B0 璁惧ソ缁濆璺緞鍙橀噺 |
| 8 | **Windows curl 涓嬭浇澶辫触锛坰channel 鍚婇攢妫€鏌ワ級** | `curl: (35) ... CRYPT_E_REVOCATION_OFFLINE (0x80092013)` 鈥斺€?curl 璧?schannel锛岃仈缃戞煡涓嶅埌璇佷功鍚婇攢鐘舵€佸氨鎷掔粷涓嬭浇銆傚绛栵細`curl --ssl-no-revoke ...`銆佹垨鎹?`Invoke-WebRequest`銆佹垨娴忚鍣ㄤ笅杞姐€傦紙adb 宸查殢浠撳簱鎻愪緵锛屾甯告儏鍐典笅涓嶉渶瑕佷笅杞斤級 |
| 9 | **`.gitignore` 鎶?`results\` 鍏ㄦ帓鎺?鈫?瀹為獙缁撴灉鎮勬倓浼犱笉涓婂幓** | 瀹炴祴韪╄繃锛氬彟涓€鍙版満鍣ㄨ窇瀹?`git add -A; git commit -m "add report"; git push`锛?*鐪嬬潃涓€鍒囨甯?*锛屼絾鎺ㄤ笂鏉ョ殑 commit 鍙敼浜?`mobile.env.ps1` 涓€涓枃浠讹紝310 涓换鍔＄殑鏃ュ織鍏ㄧ暀鍦ㄦ湰鍦般€傚師鍥犲氨鏄?`.gitignore` 閲岀殑 `**/results/**`銆傚绛栵細鍙帓闄?`step_*.png/xml/som/jpg`锛堝綋鍓?`.gitignore` 宸插姝わ級锛屽苟涓?*鎺ㄩ€佸墠鐢?`git diff --cached --stat` 纭 `results\` 鍦ㄥ垪琛ㄩ噷** |
| 10 | **`run_mbl.ps1` 鎶?benchmark 璺戜袱閬嶃€佷笖浠庝笉杞牸寮?* | 瀹炴祴韪╄繃锛氳剼鏈湯灏?*閲嶅璋冪敤浜嗕竴娆?`& $PY @runArgs`**锛岃€屼笂涓€琛屾彁绀哄啓鐨勬槸"杞垚鍒嗘瀽鏍煎紡 mbl_traj_to_episodes.py"銆傚悗鏋滐細鈶?鐧借窇涓€閬嶅叏閲忔壂鎻忥紙闀胯窇鏃跺ソ鍑犲垎閽燂級锛涒憽 绗竴閬嶅穿浜嗙浜岄亶浼?*鎮勬倓缁窇**锛岄€€鍑虹爜娌℃硶瑙ｈ锛涒憿 鏈€瑕佸懡 鈥斺€?`run_mbl.cmd` 璺戝畬**鏍规湰娌℃湁 `episodes.jsonl`**锛岀洿鎺ユ帴 B8 浼氭姤"娌℃湁璇诲埌浠讳綍 episode"銆傚凡淇紙瑙佸潙 #10 淇鍚庣殑 `run_mbl.ps1`锛夛紝骞跺湪缁撳熬鎵撳嵃 episodes 琛屾暟 |
| 11 | **缂栬緫宸ュ叿浼氭妸 `.ps1` 鐨?UTF-8 BOM 鍚冩帀** | 鍚腑鏂囩殑 `.ps1` 涓€鏃︿涪浜?BOM锛孭owerShell **5.1**锛坄run_mbl.cmd` 璧扮殑灏辨槸 5.1锛変細鎸夋湰鍦颁唬鐮侀〉 GBK 璇伙紝杞诲垯杈撳嚭涔辩爜銆侀噸鍒欒娉曢敊璇€傚疄娴嬭俯杩囦袱娆°€傚绛栵細`selftest.py` 鏂板 G1/G2 涓ら」瀹堝崼锛堝惈涓枃鐨?`.ps1` 蹇呴』鏈?BOM銆乣.cmd`/`.bat` 蹇呴』绾?ASCII锛夛紝**鏀瑰畬 `.ps1` 灏辫窇涓€娆¤嚜妫€** |

鍏朵粬宸蹭慨鎺夌殑涓や釜闈欓粯澶辨晥锛?
- PowerShell 鍙橀噺鍚嶅ぇ灏忓啓涓嶆晱鎰燂紝鍙傛暟 `$Config` 浼氬拰 `mobile.env.ps1` 閲岀殑 `$CONFIG` 鎾炴垚鍚屼竴涓彉閲忚瑕嗙洊 鈫?宸叉敼鍚?`$ConfigFile`锛堜繚鐣?`-Config` 鍒悕锛夈€?- Git 鎹㈣绗﹁嫢琚浆鎴?CRLF锛屼細璁?鎸夌簿纭枃鏈敋鐐规墦琛ヤ竵"鐨勮剼鏈叏閮ㄥけ閰?鈫?宸插姞 `.gitattributes` 缁熶竴 LF銆?
**cmd 閲屼腑鏂囪緭鍑轰贡鐮佹椂**锛氬厛鎵ц `chcp 65001`锛堟湰浠撳簱鐨?`.cmd` 娌℃湁寮哄埗鍒囨崲锛屼互鍏嶅奖鍝嶄綘缁堢鍏朵粬绋嬪簭鐨勮緭鍑猴級銆?
---

# E. 瀵?benchmark 鎵撶殑琛ヤ竵锛堜负浠€涔堥渶瑕侊級

`mobilebench/utils/mbl_api_shim.py` 鏄柊澧炴ā鍧楋紱7 涓枃浠跺叡 50+ 澶勬爣璁般€傚叏閮ㄥ箓绛夈€佽嚜鍔ㄥ浠姐€乣--revert` 鍙洖婊氥€?
```cmd
%PY% %S%\mbl_apply_api_patch.py --repo third_party\mobilebench-ol-main --with-retry --coord-norm --task-file-env --metrics --resilient
```

| 琛ヤ竵 | 瑙ｅ喅浠€涔?|
|---|---|
| **key / 妯″瀷鍚嶈蛋鐜鍙橀噺** | 鍘熶唬鐮?`api_key="123456"` 鍐欐銆佺敤 `models.list().data[0].id` 鐚滄ā鍨嬪悕 鈫?鎵樼 API 涓婁細閫変腑 `qwen-mt-uni`锛堢炕璇戞ā鍨嬶級 |
| **API 閿欒鏃ュ織 + 閲嶈瘯** | 鍘熶唬鐮佹帴鍙ｅけ璐ュ彧 `print` 灏辫繑鍥?None 鈫?闈欓粯鍙樻垚 `invalid` action 鈫?**浼氳璇垽鎴愰『搴忔晥搴?* |
| **鍧愭爣褰掍竴鍖栨崲绠?+ 鐪熷疄鍒嗚鲸鐜?* | 瑙佸潙 #1锛涘悓鏃舵妸鍐欐鐨?`1080脳2400` 鎹㈡垚鐪熷疄鎴浘灏哄 |
| **婊戝姩鐢ㄧ湡瀹炲睆骞曞昂瀵?* | `adb_executor` 鍘熷啓姝?1080脳2400锛堝疄娴嬭澶?1220脳2712锛?|
| **`MBL_TASK_FILE`** | `get_task_file()` 鍙 5 涓唴缃?subset锛屼笖**娌℃湁浠讳綍 subset 鎸囧悜 `*-reset.csv`** 鈫?鏃犳硶鎺у埗椤哄簭銆佹棤娉曡窇 reset |
| **姣忔鏃堕棿鎴?/ API 寤惰繜 / token** | 鍘?`trajectory.json` 瀹屽叏娌℃湁鏃堕棿涓庢垚鏈俊鎭紝鏃犳硶鍖哄垎"瓒呮椂澶辫触"涓?姹℃煋澶辫触" |
| **鎶楁姈鍔?* | 鍘?`run_with_reconnect` 鐨勯噸杩炴槸**姝讳唬鐮?*銆乣try_execute_task_with_retry` 鐨?try 琚敞閲婃帀 鈫?**涓€娆℃帴鍙ｆ姈鍔ㄨ鏁翠釜闀胯窇宕╂簝**锛堝凡瀹為檯鍙戠敓锛?026-09-20 04:03锛?10 涓换鍔¤窇鍒扮 25 涓椂杩涚▼姝讳骸锛?|

---

# F. 褰撳墠杩涘害锛堣瘹瀹炶褰曪級

| 椤?| 鐘舵€?|
|---|---|
| `base_canonical`锛堣鑼冨簭 310 浠诲姟锛宷wen3-vl-plus锛?| 鉁?**310/310 瀹屾垚锛孲R = 57.1%锛?77/310锛?*锛岀敤鏃?2.85 h |
| `base_shuffle`锛堜贡搴?310 浠诲姟锛?| 鈿狅笍 **26/310** 鈥斺€?2026-09-20 04:03 鎺ュ彛鏂繛瀵艰嚧杩涚▼宕╂簝锛岄渶鐢?B3 缁窇 |
| `pilot12`锛?2 浠诲姟 脳 2 椤哄簭锛?| 鉁?瀹屾垚锛毼擲R +0.083 [0.000, +0.250]銆丆TCI 0.154銆丳ASR 0.385锛? 涓换鍔＄炕杞紙`bili_4`锛?|
| 鍐掔儫锛? 浠诲姟锛?| 鉁?1/2锛涘潗鏍囨崲绠楀湪鐪熸満涓婄簿纭惢鍚堬紙`378,756` 鈫?`461,2050` = 378/1000脳1220, 756/1000脳2712锛?|
| reset 閫氶亾 | 鈴?閰嶇疆涓庝换鍔￠泦宸插氨缁紝鏈窇 |
| 璺ㄨ繍琛岀姸鎬佹畫鐣?| 鉁?宸叉湁閾佽瘉锛氳鑼冨簭鎶婄櫨搴︽祻瑙堝櫒鍒囧埌澶滈棿妯″紡锛堟湯甯т寒搴?44.7锛夛紝涔卞簭閭ｈ疆**棣栧抚灏辨槸 34.4** 鈥斺€?缁ф壙浜嗕笅鏉?|
| QQ 缇?濂藉弸姹℃煋閾?| 鉁?宸插畾浣嶏細`qq_1`锛?**鏌ョ湅**QQ鎼滅储鎵綝ND缇ょ粍"锛屽垽瀹?*鎴愬姛**锛夊疄闄呮彁浜や簡鍔犵兢鐢宠锛堝洖绛斾簡楠岃瘉闂"榫欎笌鍦颁笅鍩?锛夛紱`qq_4` 娣诲姞浜嗗ソ鍙嬨€傞殢鍚?5 涓?QQ 浠诲姟杩炵画澶辫触锛堝钩鍧?17 姝ワ級锛屾帹鐞嗛噷鍙嶅琚偅涓兢璇 |

---

# G. 鏈

| 鏈 | 鍚箟 |
|---|---|
| **OD flaky** | Order-Dependent flaky锛氱粨鏋滀緷璧栨墽琛岄『搴忕殑涓嶇ǔ瀹氫换鍔?|
| **victim** | 鍥犻『搴忓彉鍖栬€屽け璐ョ殑浠诲姟 |
| **polluter** | 鎶婄姸鎬佸紕鑴忋€佸寰楀悗缁换鍔″け璐ョ殑鍓嶅簭浠诲姟 |
| **螖SR** | 涔卞簭涓庤鑼冨簭鐨勬垚鍔熺巼宸紙閫愪换鍔￠厤瀵癸級 |
| **CTCI** | Cross-Task Contamination Index锛氶『搴忎笉纭畾鎬у甫鏉ョ殑鎴愬姛鐜囧叏骞?|
| **PASR** | Pollution-Aware Success Rate锛氭渶鍧忛『搴忎笅鐨勬湡鏈涙垚鍔熺巼锛堝彲淇′笅鐣岋級 |
| **DiD** | Difference-in-Differences锛氶『搴?脳 閲嶇疆鐨勪氦浜掗」 |
| **condition** | 閲嶇疆鏉′欢锛歚official`锛堣窇浜?cleaner锛? `none`锛堝彧閲嶅惎 App锛?|
| **order_mode** | 椤哄簭妗ｄ綅锛歚canonical` / `reverse` / `shuffle<seed>` / `adversarial`锛坅dversarial 灏氭湭瀹炵幇锛?|
