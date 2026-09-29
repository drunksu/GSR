@echo off
rem ===========================================================================
rem  run_finish.cmd -- the two remaining pieces of work.
rem
rem  Usage:  D:\GSR\run_finish.cmd        (paste nothing; just run the file)
rem
rem  PIECE 1 -- backfill qq_5 in baseflash_shuffle   (~1 min, no pause)
rem    baseflash_shuffle finished with 309/310 episodes; qq_5 is missing.
rem    Re-running with the SAME -Output skips everything done and only runs it.
rem
rem  PIECE 2 -- victim-table experiment v3            (~5 h + 56 manual pauses)
rem    Goal: make the "victim" table non-empty. It needs a task with
rem    |delta-SR| >= 0.2 AND BH-FDR q < 0.05.
rem
rem    Why the old 8-task QQ set cannot do it:
rem      Under plus only qq_1 has any variance at all; under flash only
rem      qq_1 / qq_10 / qq_13 / qq_14 do. The other tasks score 0.000 or
rem      1.000 under BOTH orders, so they can never flip - they only inflate
rem      the multiple-comparison burden. Measured: the 8-task set would need
rem      n=24 repeats per order (~17 h) to yield a single victim.
rem
rem    So this script pre-registers the 4 tasks that actually vary:
rem      qqvar4_canonical.csv = qq_1 -> qq_10 -> qq_13 -> qq_14  (writer first)
rem      qqvar4_reverse.csv   = reversed
rem    and runs 14 more rounds, taking the total to n=20 per order.
rem    The first 6 rounds already exist (q2_* dirs) and are reused via
rem    --tasks, so only 14 more rounds are run here:
rem      14 rounds x 2 orders x 2 models x 4 tasks = 224 episodes  ~= 5 h
rem
rem    At n=20 with K=4 the projected q for qq_14 is 0.033 (< 0.05).
rem    Caveat: that projection extrapolates the n=6 effect sizes, and those 4
rem    tasks were picked BECAUSE they varied at n=6. If the effect was
rem    selection noise it will shrink instead of growing - then the honest
rem    conclusion is "per-task victim detection at this effect size costs more
rem    than the budget", which is itself a useful result.
rem
rem  56 pauses: after every order-A run and every order-B run, restore the QQ
rem  state on the phone (leave the group / delete friend 1098074562 / unpin).
rem
rem  Keep this file PURE ASCII.
rem ===========================================================================
setlocal enabledelayedexpansion
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
set ROUNDS=14

echo ============ 0. environment check ============
echo [CHECK] MBL=[%MBL%]
echo [CHECK] PY=[%PY%]
echo [CHECK] REPO=[%REPO%]
if not exist "%MBL%\run_mbl.cmd" (echo [FATAL] run_mbl.cmd missing -- STOP & goto :fail)
if not exist "%PY%" (echo [FATAL] venv python missing -- STOP & goto :fail)
if not exist "%REPO%\run.py" (echo [FATAL] benchmark missing -- STOP & goto :fail)
if not exist "%REPO%\data\qqvar4_canonical.csv" (echo [FATAL] qqvar4 task CSVs missing -- pull first & goto :fail)

echo.
echo ============ 1. wake phone ============
"%ADB%" devices
"%ADB%" -s %DEV% shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
cd /d "%REPO%"

echo.
echo ============ 2. backfill qq_5 into baseflash_shuffle (~1 min) ============
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf -TaskFile data\base_shuffle0.csv -Output results\baseflash_shuffle
findstr /C:"qwen3-vl-flash" results\baseflash_shuffle\run_manifest.json >nul
if errorlevel 1 (echo [FATAL] baseflash_shuffle manifest agent is wrong -- STOP & goto :fail)

echo.
echo ==========================================================================
echo  PIECE 2: victim experiment v3 -- %ROUNDS% more rounds, %ROUNDS%*2 pauses
echo.
echo  At EVERY pause, do this on the phone:
echo    [a] leave the QQ group that round joined - the DND one
echo    [b] delete friend 1098074562
echo    [c] unpin the chat with that contact; if the chat history was
echo        deleted, send one message to restore it
echo  Then come back here and press any key.
echo ==========================================================================
echo.
pause

for /l %%r in (1,1,%ROUNDS%) do (
  echo.
  echo ---- v3 round %%r / %ROUNDS% : order A, writer first ----
  call "%MBL%\run_mbl.cmd" -TaskFile data\qqvar4_canonical.csv -Output results\s3_A_%%r
  echo.
  echo ==== v3 round %%r order A done. Restore QQ state, then press any key ====
  pause
  echo.
  echo ---- v3 round %%r / %ROUNDS% : order B, writer last ----
  call "%MBL%\run_mbl.cmd" -TaskFile data\qqvar4_reverse.csv -Output results\s3_B_%%r
  echo.
  echo ==== v3 round %%r order B done. Restore QQ state, then press any key ====
  pause
)

echo.
echo ---- same %ROUNDS% rounds with flash ----
for /l %%r in (1,1,%ROUNDS%) do (
  echo.
  echo ---- v3 flash round %%r / %ROUNDS% : order A ----
  call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -TaskFile data\qqvar4_canonical.csv -Output results\s3_Af_%%r
  echo.
  echo ==== v3 flash round %%r order A done. Restore QQ state, then press any key ====
  pause
  echo.
  echo ---- v3 flash round %%r / %ROUNDS% : order B ----
  call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -TaskFile data\qqvar4_reverse.csv -Output results\s3_Bf_%%r
  echo.
  echo ==== v3 flash round %%r order B done. Restore QQ state, then press any key ====
  pause
)

echo.
echo ============ 3. rebuild every analysis ============
rem 3.1 victim table: the 4-task pre-registered subset, pooling the old 6
rem     rounds (q2_*) with the new 14 (s3_*) -> n=20 per order.
"%PY%" "%S%\analyze_order_effects.py" --input results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 results\s3_A_1 results\s3_A_2 results\s3_A_3 results\s3_A_4 results\s3_A_5 results\s3_A_6 results\s3_A_7 results\s3_A_8 results\s3_A_9 results\s3_A_10 results\s3_A_11 results\s3_A_12 results\s3_A_13 results\s3_A_14 results\s3_B_1 results\s3_B_2 results\s3_B_3 results\s3_B_4 results\s3_B_5 results\s3_B_6 results\s3_B_7 results\s3_B_8 results\s3_B_9 results\s3_B_10 results\s3_B_11 results\s3_B_12 results\s3_B_13 results\s3_B_14 results\s3_Af_1 results\s3_Af_2 results\s3_Af_3 results\s3_Af_4 results\s3_Af_5 results\s3_Af_6 results\s3_Af_7 results\s3_Af_8 results\s3_Af_9 results\s3_Af_10 results\s3_Af_11 results\s3_Af_12 results\s3_Af_13 results\s3_Af_14 results\s3_Bf_1 results\s3_Bf_2 results\s3_Bf_3 results\s3_Bf_4 results\s3_Bf_5 results\s3_Bf_6 results\s3_Bf_7 results\s3_Bf_8 results\s3_Bf_9 results\s3_Bf_10 results\s3_Bf_11 results\s3_Bf_12 results\s3_Bf_13 results\s3_Bf_14 --tasks qq_1,qq_10,qq_13,qq_14 --out results\victim_analysis --official-condition none

rem 3.2 keep the original 8-task view for comparison
"%PY%" "%S%\analyze_order_effects.py" --input results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 --out results\repeat_analysis --official-condition none

rem 3.3 refresh the scale analysis now that qq_5 is in
"%PY%" "%S%\analyze_order_effects.py" --input results\base_canonical results\base_shuffle results\baseflash_canonical results\baseflash_shuffle --out results\scale_analysis --official-condition official

echo.
echo ============ 4. results ============
type results\victim_analysis\report.md

echo.
echo ============ 5. upload ============
cd /d "%MBL%"
git pull --rebase --autostash
call "%MBL%\sync.cmd" "results: backfill qq_5 + victim experiment v3 (4-task subset, n=20)"

echo.
echo ============ ALL DONE ============
echo   victim table : %REPO%\results\victim_analysis\report.md
echo   repeats (8)  : %REPO%\results\repeat_analysis\report.md
echo   scale        : %REPO%\results\scale_analysis\report.md
pause
exit /b 0

:fail
echo.
echo ==========================================================
echo  [FATAL] Stopped. See the [CHECK]/[FATAL] lines above.
echo ==========================================================
pause
exit /b 1
