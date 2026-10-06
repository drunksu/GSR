@echo off
rem ===========================================================================
rem  run_flash_tail.cmd -- THIS ROUND (2026-10-02): finish the flash side of
rem  victim experiment v3, plus the one missing plus round.
rem
rem  Usage:  D:\GSR\run_flash_tail.cmd        (just run the file; paste nothing)
rem
rem  -------------------------------------------------------------------------
rem  WHY THIS ROUND EXISTS
rem    v3 = 4 pre-registered QQ tasks x 2 orders x 20 rounds per arm.
rem      plus  canonical : 6 old (q2_A_*)  + 14 new (s3_A_1..14)  = 20  DONE
rem      plus  reverse   : 6 old (q2_B_*)  + 13 new (s3_B_1..14)  = 19  <- 1 short
rem      flash canonical : 6 old (q2_Af_*) +  2 new (s3_Af_1..2)   =  8  <- 12 short
rem      flash reverse   : 6 old (q2_Bf_*) +  1 new (s3_Bf_1)      =  7  <- 13 short
rem    So the model-by-order interaction in the report (-0.184) currently
rem    sits on UNEQUAL arms (20/19 vs 8/7). This round equalises them.
rem
rem  -------------------------------------------------------------------------
rem  WHAT IT RUNS: 26 runs, ~5.3 h wall clock, 26 manual pauses
rem    [1] plus  s3_B_5          1 run   ~16 min      (measured plus: 15-19 min)
rem    [2] flash s3_Af_3..14    12 runs  ~12 min each (measured flash: 11-12 min)
rem    [3] flash s3_Bf_2..14    13 runs  ~12 min each
rem    s3_Bf_2 is an EMPTY SHELL right now (run_manifest.json only, no
rem    result_list.txt): that round died 2 min in on 10-01, so it is re-run.
rem
rem  -------------------------------------------------------------------------
rem  AT EVERY PAUSE, on the phone:
rem    [a] leave the QQ group this round joined -- the DND one
rem    [b] delete friend 1098074562
rem    [c] unpin that chat; if its history was deleted, send one message first
rem    Skipping this leaves the next round a different starting state and the
rem    round is wasted -- all arms must start from the same point.
rem
rem  SAFE TO RE-RUN: every run directory keeps its own result_list.txt, so
rem  finished rounds are skipped. Interrupt + re-run = resume.
rem
rem  This file must stay PURE ASCII (cmd reads it in the local code page).
rem  Loop variables therefore use %%r, not %r.
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

set CONF=config\interact_API_qwen3vl_base.conf
set TASKS_A=data\qqvar4_canonical.csv
set TASKS_B=data\qqvar4_reverse.csv

echo ============ 0. environment check ============
echo [CHECK] MBL=[%MBL%]
echo [CHECK] PY=[%PY%]
echo [CHECK] REPO=[%REPO%]
if not exist "%MBL%\run_mbl.cmd" (echo [FATAL] run_mbl.cmd missing -- STOP & goto :fail)
if not exist "%PY%" (echo [FATAL] venv python missing -- STOP & goto :fail)
if not exist "%REPO%\run.py" (echo [FATAL] benchmark missing -- STOP & goto :fail)
if not exist "%REPO%\%TASKS_A%" (echo [FATAL] qqvar4 task CSVs missing -- git pull first & goto :fail)

echo.
echo ============ 1. wake phone ============
"%ADB%" devices
"%ADB%" -s %DEV% shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
cd /d "%REPO%"

echo.
echo ==========================================================================
echo  THIS ROUND: 26 runs, ~5.3 h, 26 pauses.
echo  The 8-cell 2x2, the 310-task scale runs and the plus side of the repeat
echo  experiment are already complete -- only the flash side is short.
echo.
echo  At EVERY pause do this on the phone:
echo    [a] leave the DND QQ group this round joined
echo    [b] delete friend 1098074562
echo    [c] unpin that chat; if the history was deleted, send a message first
echo  Then come back here and press any key.
echo ==========================================================================
pause

echo.
echo ---- [1/3] plus reverse round 5 -- the one missing plus round (~16 min) ----
call "%MBL%\run_mbl.cmd" -Model qwen3-vl-plus -ConfigFile %CONF% -TaskFile %TASKS_B% -Output results\s3_B_5
call :verify s3_B_5 qwen3-vl-plus
if errorlevel 1 goto :fail
echo ==== plus s3_B_5 done. Restore QQ state, then press any key ====
pause

echo.
echo ---- [2/3] flash canonical rounds 3..14 -- 12 runs ----
for /l %%r in (3,1,14) do (
  echo.
  echo ---- flash round %%r / 14 : order A, canonical ----
  call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile %CONF% -TaskFile %TASKS_A% -Output results\s3_Af_%%r
  call :verify s3_Af_%%r qwen3-vl-flash
  if errorlevel 1 goto :fail
  echo ==== flash round %%r order A done. Restore QQ state, then press any key ====
  pause
)

echo.
echo ---- [3/3] flash reverse rounds 2..14 -- 13 runs ----
for /l %%r in (2,1,14) do (
  echo.
  echo ---- flash round %%r / 14 : order B, reverse ----
  call "%MBL%\run_mbl.cmd" -Model qwen3-vl-flash -ConfigFile %CONF% -TaskFile %TASKS_B% -Output results\s3_Bf_%%r
  call :verify s3_Bf_%%r qwen3-vl-flash
  if errorlevel 1 goto :fail
  echo ==== flash round %%r order B done. Restore QQ state, then press any key ====
  pause
)

echo.
echo ============ 4. completeness check ============
echo All four arms must have 14 s3 rounds x 4 episodes (+ 6 q2 rounds = n=20).
"%PY%" -c "import os,sys;ds=[('s3_'+g+'_'+str(r)) for g in ('A','B','Af','Bf') for r in range(1,15)];bad=[d for d in ds if not os.path.exists('results/'+d+'/episodes.jsonl') or sum(1 for _ in open('results/'+d+'/episodes.jsonl',encoding='utf-8'))<4];print('[CHECK] rounds missing or short:',bad);sys.exit(1 if bad else 0)"
if errorlevel 1 (
  echo [WARN] the rounds listed above are incomplete.
  echo [WARN] Run this file again -- finished rounds are skipped.
)

echo.
echo ============ 5. rebuild the three analyses ============
set V3DIRS=results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 results\s3_A_1 results\s3_A_2 results\s3_A_3 results\s3_A_4 results\s3_A_5 results\s3_A_6 results\s3_A_7 results\s3_A_8 results\s3_A_9 results\s3_A_10 results\s3_A_11 results\s3_A_12 results\s3_A_13 results\s3_A_14 results\s3_B_1 results\s3_B_2 results\s3_B_3 results\s3_B_4 results\s3_B_5 results\s3_B_6 results\s3_B_7 results\s3_B_8 results\s3_B_9 results\s3_B_10 results\s3_B_11 results\s3_B_12 results\s3_B_13 results\s3_B_14 results\s3_Af_1 results\s3_Af_2 results\s3_Af_3 results\s3_Af_4 results\s3_Af_5 results\s3_Af_6 results\s3_Af_7 results\s3_Af_8 results\s3_Af_9 results\s3_Af_10 results\s3_Af_11 results\s3_Af_12 results\s3_Af_13 results\s3_Af_14 results\s3_Bf_1 results\s3_Bf_2 results\s3_Bf_3 results\s3_Bf_4 results\s3_Bf_5 results\s3_Bf_6 results\s3_Bf_7 results\s3_Bf_8 results\s3_Bf_9 results\s3_Bf_10 results\s3_Bf_11 results\s3_Bf_12 results\s3_Bf_13 results\s3_Bf_14
echo 5.1 victim table: 4-task pre-registered subset, pooled to n=20 per arm
"%PY%" "%S%\analyze_order_effects.py" --input %V3DIRS% --tasks qq_1,qq_10,qq_13,qq_14 --out results\victim_analysis --official-condition none

echo 5.2 original 8-task view for comparison (q2_* only, unchanged)
"%PY%" "%S%\analyze_order_effects.py" --input results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 --out results\repeat_analysis --official-condition none

echo 5.3 scale analysis (unchanged inputs, refreshed numbers)
"%PY%" "%S%\analyze_order_effects.py" --input results\base_canonical results\base_shuffle results\baseflash_canonical results\baseflash_shuffle --out results\scale_analysis --official-condition official

echo.
echo ============ 6. results ============
type results\victim_analysis\report.md

echo.
echo ============ 7. upload ============
cd /d "%MBL%"
git pull --rebase --autostash
call "%MBL%\sync.cmd" "results: victim v3 flash side to n=20 (26 runs) + plus s3_B_5"

echo.
echo ============ ALL DONE ============
echo   victim table : %REPO%\results\victim_analysis\report.md
echo   repeats (8)  : %REPO%\results\repeat_analysis\report.md
echo   scale        : %REPO%\results\scale_analysis\report.md
echo.
echo  Check that BOTH models now show n=80 / n=80 in section 2 of the victim
echo  report (= 4 tasks x 20 rounds). If flash delta-SR shrank a lot from
echo  -0.152, the n=6 effect was selection noise -- say so, do not hide it.
pause
exit /b 0

rem ---------------------------------------------------------------------------
rem  :verify <rundir> <expected-agent-substring>
rem  Guards against the two silent failure modes seen in this project:
rem    (a) a run that dies and leaves no episodes.jsonl
rem    (b) a run that silently used the wrong model (see pitfall 19)
rem ---------------------------------------------------------------------------
:verify
setlocal
set D=%~1
set A=%~2
if not exist "results\%D%\run_manifest.json" (
  echo [FATAL] %D% has no run_manifest.json -- the round never started
  endlocal & exit /b 1
)
findstr /C:"%A%" "results\%D%\run_manifest.json" >nul
if errorlevel 1 (
  echo [FATAL] %D% manifest agent is not %A% -- wrong model, do NOT trust this round
  endlocal & exit /b 1
)
rem Each round is 4 tasks. Fewer episodes = the round died halfway; re-running
rem this file resumes it (completed tasks are skipped).
"%PY%" -c "import os,sys;d='results/%D%/episodes.jsonl';n=sum(1 for _ in open(d,encoding='utf-8')) if os.path.exists(d) else 0;print('[CHECK] %D% episodes =',n);sys.exit(0 if n>=4 else 1)"
if errorlevel 1 (
  echo [FATAL] %D% is short or empty -- check result_list.txt
  endlocal & exit /b 1
)
endlocal & exit /b 0

:fail
echo.
echo ==========================================================
echo  [FATAL] Stopped. See the [CHECK]/[FATAL] lines above.
echo  Fix it, then run this file again -- finished rounds resume.
echo ==========================================================
pause
exit /b 1
