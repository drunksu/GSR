@echo off
rem ===========================================================================
rem  pilot.cmd -- CMD wrapper for pilot.ps1 (same arguments)
rem  One command runs the whole flow: wake phone -> order A -> order B ->
rem  convert -> analyse -> print report path.
rem
rem  Examples (run from the repo root):
rem     pilot.cmd -Tag base -TasksCanonical data/base_canonical.csv -TasksShuffle data/base_shuffle0.csv
rem     pilot.cmd -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data/base_canonical.csv -TasksShuffle data/base_shuffle0.csv
rem     pilot.cmd -Tag base -Condition official -TasksCanonical data/base_canonical.csv -TasksShuffle data/base_shuffle0.csv
rem     pilot.cmd -Tag pilot12 -TasksCanonical data/pilot12_canonical.csv -TasksShuffle data/pilot12_shuffle0.csv -DryRun
rem
rem  NOTE: keep this file pure ASCII (see run_mbl.cmd for the reason).
rem ===========================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pilot.ps1" %*
exit /b %ERRORLEVEL%
