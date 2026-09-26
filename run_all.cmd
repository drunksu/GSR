@echo off
rem ===========================================================================
rem  run_all.cmd -- run the complete GSR experiment set (plus + flash).
rem
rem  Usage:  D:\GSR\run_all.cmd
rem          (or just double-click it)
rem
rem  Do NOT paste the commands by hand: pasting a large multi-line block into
rem  cmd is fragile (buffered input gets echoed but not executed, and any
rem  non-ASCII byte corrupts the following line -- see README pitfall #18).
rem  Running this file avoids both problems entirely.
rem
rem  Safe to re-run: every run directory has its own result_list.txt, so
rem  completed tasks are skipped. Interrupting and re-running = resume.
rem
rem  Total cost: ~28 h wall clock, ~177 M tokens, ~8 GB disk.
rem
rem  This file must stay PURE ASCII (cmd reads it in the local code page).
rem  Loop variables therefore use %%r, not %r.
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
echo ============ 1. self-test + flash coord check + wake phone (5 min) ============
echo coord check exit code 3 = "norm convention" = EXPECTED, not a failure
"%PY%" "%S%\selftest.py"
if errorlevel 1 (echo [FATAL] self-test FAILED -- STOP & goto :fail)
"%ADB%" devices
"%PY%" "%S%\mbl_coord_convention_check.py" --model qwen3-vl-flash --repo "%REPO%"
"%ADB%" -s %DEV% shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
cd /d "%REPO%"

echo.
echo ============ 2. plus: backfill base_shuffle + 65-task same-day 2x2 (6.1 h) ============
call "%MBL%\pilot.cmd" -Tag base -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
call "%MBL%\run_mbl.cmd" -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_canonical.csv -Output results\p1_none_can
call "%MBL%\run_mbl.cmd" -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\p1_off_can
call "%MBL%\run_mbl.cmd" -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_shuffle0.csv  -Output results\p2_none_shf
call "%MBL%\run_mbl.cmd" -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_shuffle0.csv  -Output results\p2_off_shf
"%PY%" "%S%\mbl_purge_tasks.py" --run-dir results\base_shuffle --blank-failed-only --dry-run

echo.
echo ============ 3. flash: 65-task 2x2 + 310x2 full scale (17.9 h) ============
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_canonical.csv -Output results\f_none_can
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\f_off_can
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_shuffle0.csv  -Output results\f_none_shf
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_shuffle0.csv  -Output results\f_off_shf
call "%MBL%\pilot.cmd" -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv

echo.
echo ============ 4. pilot12 with flash (0.9 h) ============
call "%MBL%\pilot.cmd" -Tag pilot12flash -Model qwen3-vl-flash -TasksCanonical data\pilot12_canonical.csv -TasksShuffle data\pilot12_shuffle0.csv

echo.
echo ============ 5. repeat experiment, redone: 6 rounds x 2 orders x 2 models (3.7 h) ============
echo At every pause, restore QQ state on the phone:
echo   (a) leave the group that round added
echo   (b) delete friend 1098074562
echo   (c) unpin the chat, restore the chat history if it was deleted
for /l %%r in (1,1,6) do (
  call "%MBL%\run_mbl.cmd" -TaskFile data\qqset_canonical.csv -Output results\q2_A_%%r
  echo.
  echo ==== round %%r order A done. Restore QQ state on the phone, then press any key ====
  pause
  call "%MBL%\run_mbl.cmd" -TaskFile data\qqset_reverse.csv -Output results\q2_B_%%r
  echo.
  echo ==== round %%r order B done. Restore QQ state again, then press any key ====
  pause
)
for /l %%r in (1,1,6) do (
  call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -TaskFile data\qqset_canonical.csv -Output results\q2_Af_%%r
  echo.
  echo ==== flash round %%r order A done. Restore QQ state, then press any key ====
  pause
  call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -TaskFile data\qqset_reverse.csv -Output results\q2_Bf_%%r
  echo.
  echo ==== flash round %%r order B done. Restore QQ state again, then press any key ====
  pause
)

echo.
echo ============ 6. build all reports ============
"%PY%" "%S%\analyze_order_effects.py" --input results\p1_none_can results\p1_off_can results\p2_none_shf results\p2_off_shf results\f_none_can results\f_off_can results\f_none_shf results\f_off_shf --out results\twomodel_2x2 --official-condition official
"%PY%" "%S%\analyze_order_effects.py" --input results\base_canonical results\base_shuffle results\baseflash_canonical results\baseflash_shuffle --out results\scale_analysis --official-condition official
"%PY%" "%S%\analyze_order_effects.py" --input results\base_canonical results\base_shuffle results\reset_can results\reset_shf --out results\master_analysis --official-condition official
"%PY%" "%S%\analyze_order_effects.py" --input results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 --out results\repeat_analysis --official-condition none
type results\twomodel_2x2\report.md
type results\scale_analysis\report.md
type results\repeat_analysis\report.md

echo.
echo ============ 7. upload ============
rem NOTE: git pull/push need no special args here; sync.cmd handles staging,
rem       verifies that results\ files made it in, then pushes.
cd /d "%MBL%"
git pull --rebase --autostash
call "%MBL%\sync.cmd" "results: full experiment set, plus and flash, 2x2 scale repeats"

echo.
echo ============ ALL DONE ============
echo Reports: %REPO%\results\twomodel_2x2\report.md
echo          %REPO%\results\scale_analysis\report.md
echo          %REPO%\results\repeat_analysis\report.md
pause
exit /b 0

:fail
echo.
echo ==========================================================
echo  [FATAL] Stopped before running any experiment.
echo  See the [CHECK]/[FATAL] lines above.
echo  Common causes:
echo    - repo not at the expected location / venv missing
echo    - phone not connected or not authorised (adb devices)
echo ==========================================================
pause
exit /b 1
