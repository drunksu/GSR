@echo off
rem ---------------------------------------------------------------
rem run_repeats.cmd  --  run the SAME task list N times, each into
rem                     its own -Output directory.
rem
rem Usage:
rem   run_repeats.cmd TASKFILE OUTPREFIX N [extra run_mbl args]
rem
rem Example (6 repetitions of the pre-registered QQ subset):
rem   run_repeats.cmd data\qqset_canonical.csv results\qqset_A 6
rem   run_repeats.cmd data\qqset_reverse.csv   results\qqset_B 6
rem   run_repeats.cmd data\qqset_canonical.csv results\qqset_A 6 -Model qwen3-vl-flash
rem
rem Why separate -Output dirs:
rem   result_list.txt is the resume cache. Reusing one directory means
rem   runs 2..N skip every task as "already done". Separate directories
rem   are what gives the analyzer n>1 episodes per (task x order), which
rem   is the ONLY way to populate the victim / polluter tables.
rem
rem Why this is needed at all:
rem   With one pass per order, every (task x order) has exactly 1 sample,
rem   Fisher's two-sided p is identically 1.0, and the polluter table
rem   needs the same predecessor >=3 times. See README.md section D.
rem
rem This file must stay PURE ASCII.
rem ---------------------------------------------------------------

setlocal enabledelayedexpansion
set "TF=%~1"
set "PFX=%~2"
set "N=%~3"

if "%TF%"=="" goto :usage
if "%PFX%"=="" goto :usage
if "%N%"=="" goto :usage

rem Everything after the 3rd argument, passed through to run_mbl.cmd
set "EXTRA="
for /f "tokens=1,2,3*" %%a in ("%*") do set "EXTRA=%%d"

echo Task file : %TF%
echo Output    : %PFX%_r1 ... %PFX%_r%N%
echo Repeats   : %N%
if not "%EXTRA%"=="" echo Extra args: %EXTRA%
echo.

set /a FAILED=0
for /l %%i in (1,1,%N%) do (
  echo ============================================================
  echo   repeat %%i / %N%   -^>   %PFX%_r%%i
  echo ============================================================
  call "%~dp0run_mbl.cmd" -TaskFile "%TF%" -Output "%PFX%_r%%i" %EXTRA%
  if errorlevel 1 (
    echo [WARN] repeat %%i exited non-zero - continuing
    set /a FAILED+=1
  )
)

echo.
echo ============================================================
echo   all %N% repeats finished.  %FAILED% of them exited non-zero.
echo ============================================================
if %FAILED% GTR 0 echo [WARN] Check the logs above before analysing.
echo.
echo Next: analyse every repeat directory together, e.g.
echo   %%PY%% %%S%%\analyze_order_effects.py --input ^
echo       %PFX%_r1\episodes.jsonl %PFX%_r2\episodes.jsonl ... ^
echo       --out results\qqset_analysis --official-condition official
echo.
echo Or just pass the parent pattern with the helper:
echo   %%PY%% %%S%%\analyze_order_effects.py --input %PFX%_r1 %PFX%_r2 %PFX%_r3 ^
echo       %PFX%_r4 %PFX%_r5 %PFX%_r6 --out results\qqset_analysis
exit /b 0

:usage
echo Usage: run_repeats.cmd TASKFILE OUTPREFIX N [extra run_mbl args]
echo.
echo   TASKFILE   e.g. data\qqset_canonical.csv
echo   OUTPREFIX  e.g. results\qqset_A    (creates OUTPREFIX_r1 .. _rN)
echo   N          number of repetitions, e.g. 6
echo.
echo   extra args are forwarded to run_mbl.cmd, e.g. -Model qwen3-vl-flash
echo             or -DryRun to rehearse without a phone
exit /b 1
