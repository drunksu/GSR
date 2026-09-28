@echo off
rem ===========================================================================
rem  run_missing.cmd -- re-run ONLY the parts that produced 0 episodes.
rem
rem  Why they failed (root cause, 2026-09-27):
rem    pilot.ps1 built its extra arguments as an ARRAY and splatted it:
rem        $modelArgs = @('-Model', $Model);  & run_mbl.ps1 ... @modelArgs
rem    PowerShell does NOT treat '-Model' inside a splatted array as a
rem    parameter name -- it becomes a POSITIONAL value, so everything shifts
rem    one slot:  $Subset got '-Model', $ConfigFile got 'qwen3-vl-flash'.
rem    The command actually sent to run.py was therefore
rem        run.py --subset -Model --config qwen3-vl-flash
rem    -> argparse refused -> 1 second per run, 0 episodes.  And because
rem    $Model stayed empty the manifest still said agent=qwen3-vl-plus, so it
rem    LOOKED like "the model flag was ignored" instead of "nothing ran".
rem    pilot.ps1 is fixed, but this script deliberately bypasses it and calls
rem    run_mbl.cmd directly with explicit parameter names (the path already
rem    proven by the f_* runs, which all completed with the right agent).
rem
rem  Safe to re-run: each -Output dir starts with no result_list.txt, so all
rem  tasks run; re-running later skips whatever finished.
rem
rem  Cost: ~12.1 h (310 x 2 orders) + ~0.9 h (12 x 2)  =  ~13 h
rem
rem  Keep this file PURE ASCII.
rem ===========================================================================
setlocal
cd /d "%~dp0"

set MBL=%~dp0
if "%MBL:~-1%"=="\" set MBL=%MBL:~0,-1%
set PY=%MBL%\mobile\Scripts\python.exe
set S=%MBL%\experiments\scripts
set REPO=%MBL%\third_party\mobilebench-ol-main
set ADB=%MBL%\third_party\platform-tools\adb.exe
set DEV=GAGU8HGYW8JF9TIJ
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ============ 0. environment check ============
echo [CHECK] MBL=[%MBL%]
echo [CHECK] PY=[%PY%]
echo [CHECK] REPO=[%REPO%]
if not exist "%MBL%\run_mbl.cmd" (echo [FATAL] run_mbl.cmd missing under MBL -- STOP & goto :fail)
if not exist "%PY%" (echo [FATAL] venv python missing at PY -- STOP & goto :fail)
if not exist "%REPO%\run.py" (echo [FATAL] benchmark missing under REPO -- STOP & goto :fail)

echo.
echo ============ 1. wake phone ============
"%ADB%" devices
"%ADB%" -s %DEV% shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
cd /d "%REPO%"

echo.
echo ============ 2. flash on the full base set: 310 x 2 orders (~12.1 h) ============
rem NOTE: pass -Model and -ConfigFile explicitly by NAME. Never build an array
rem       of switches and splat it -- that is exactly what broke before.
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf -TaskFile data\base_canonical.csv -Output results\baseflash_canonical

echo.
echo verify the manifest says agent=qwen3-vl-flash (NOT qwen3-vl-plus):
findstr /C:"qwen3-vl-flash" results\baseflash_canonical\run_manifest.json >nul
if errorlevel 1 (echo [FATAL] manifest agent is wrong -- parameters mis-bound again & goto :fail)
echo   OK: baseflash_canonical manifest carries qwen3-vl-flash

call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf -TaskFile data\base_shuffle0.csv  -Output results\baseflash_shuffle

echo.
echo verify the manifest again:
findstr /C:"qwen3-vl-flash" results\baseflash_shuffle\run_manifest.json >nul
if errorlevel 1 (echo [FATAL] manifest agent is wrong & goto :fail)
echo   OK: baseflash_shuffle manifest carries qwen3-vl-flash

echo.
echo ============ 3. pilot12 with flash (~0.9 h) ============
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf -TaskFile data\pilot12_canonical.csv -Output results\pilot12flash_canonical
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf -TaskFile data\pilot12_shuffle0.csv  -Output results\pilot12flash_shuffle

echo.
echo ============ 4. rebuild every report ============
"%PY%" "%S%\analyze_order_effects.py" --input results\base_canonical results\base_shuffle results\baseflash_canonical results\baseflash_shuffle --out results\scale_analysis --official-condition official
"%PY%" "%S%\analyze_order_effects.py" --input results\p1_none_can results\p1_off_can results\p2_none_shf results\p2_off_shf results\f_none_can results\f_off_can results\f_none_shf results\f_off_shf --out results\twomodel_2x2 --official-condition official
"%PY%" "%S%\analyze_order_effects.py" --input results\base_canonical results\base_shuffle results\reset_can results\reset_shf --out results\master_analysis --official-condition official
"%PY%" "%S%\analyze_order_effects.py" --input results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 --out results\repeat_analysis --official-condition none

echo.
echo ============ 5. show the headline numbers ============
type results\scale_analysis\report.md
type results\twomodel_2x2\report.md

echo.
echo ============ 6. upload ============
cd /d "%MBL%"
git pull --rebase --autostash
call "%MBL%\sync.cmd" "results: backfill flash base scale + pilot12flash (pilot splat bug)"

echo.
echo ============ ALL DONE ============
pause
exit /b 0

:fail
echo.
echo ==========================================================
echo  [FATAL] Stopped. See the [CHECK]/[FATAL] lines above.
echo ==========================================================
pause
exit /b 1
