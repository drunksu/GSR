@echo off
rem ---------------------------------------------------------------
rem sync.cmd  --  stage + verify + commit + push in one command
rem
rem Usage (from repo root, or anywhere):
rem   sync.cmd "results: base_shuffle 310/310"
rem
rem The verify step exists because a full run's logs were once lost:
rem .gitignore had "**/results/**", so "git add -A" silently staged
rem no experiment data and the push looked successful.
rem See README.md section C and section D pitfall 9.
rem
rem This file must stay PURE ASCII (cmd.exe reads it in the local
rem code page; UTF-8 Chinese would break the "rem" lines).
rem ---------------------------------------------------------------

setlocal
cd /d "%~dp0"

set MSG=%~1
if "%MSG%"=="" set MSG=sync

echo === 1/4  staging ===
git add -A
if errorlevel 1 goto :fail

echo.
echo === 2/4  what will be committed ===
git diff --cached --stat

echo.
git diff --cached --name-only | findstr /C:"results" >nul
if errorlevel 1 (
  echo [WARN] Nothing under results\ is staged.
  echo [WARN] If you just finished a run, its logs will NOT be uploaded.
  echo [WARN] Check .gitignore, then read README.md section D pitfall 9.
) else (
  echo [OK]   results\ files are staged.
)

echo.
echo === 3/4  commit ===
git diff --cached --quiet
if not errorlevel 1 (
  echo [INFO] Nothing changed -- skipping commit.
  goto :push
)
git commit -m "%MSG%"
if errorlevel 1 goto :fail

:push
echo.
echo === 4/4  push ===
git push
if errorlevel 1 goto :fail

echo.
echo [DONE]
exit /b 0

:fail
echo.
echo [FAILED] -- read the message above.
exit /b 1
