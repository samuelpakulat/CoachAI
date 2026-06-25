@echo off
REM ===================================================================
REM  Double-click this file (or point Windows Task Scheduler at it) to
REM  run the job tracker. It always runs from its own folder, loads any
REM  local secrets, and appends output to run.log.
REM ===================================================================

cd /d "%~dp0"

REM Load secrets (email/Adzuna keys) if you created secrets.bat. This file
REM is git-ignored so your password never gets committed. See secrets.example.bat
if exist "secrets.bat" call secrets.bat

python job_tracker.py >> run.log 2>&1

REM Keep the window open when run by double-click so you can see any error.
if "%1"=="" pause
