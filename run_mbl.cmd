@echo off
rem ===========================================================================
rem  run_mbl.cmd -- CMD wrapper for run_mbl.ps1 (same arguments, works in cmd)
rem
rem  Examples (run from the repo root):
rem     run_mbl.cmd -TaskFile data/smoke_2task.csv -Output results/smoke
rem     run_mbl.cmd -TaskFile data/base_canonical.csv -Output results/base_canonical
rem     run_mbl.cmd -Model qwen3-vl-flash -TaskFile data/smoke_2task.csv -Output results/_t
rem     run_mbl.cmd -ConfigFile config/interact_API_qwen3vl_reset.conf -TaskFile data/reset_canonical.csv -Output results/reset_r1
rem     run_mbl.cmd -TaskFile data/smoke_2task.csv -Output results/_t -DryRun   (rehearsal, no phone needed)
rem
rem  API key / model registry / paths are loaded automatically from mobile.env.ps1,
rem  so nothing needs to be "set" in cmd beforehand.
rem
rem  NOTE: keep this file pure ASCII. cmd.exe reads .bat/.cmd using the local
rem  codepage (GBK on Chinese Windows), so UTF-8 Chinese comments break parsing.
rem ===========================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_mbl.ps1" %*
exit /b %ERRORLEVEL%
