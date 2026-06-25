@echo off
REM ===================================================================
REM  TEMPLATE -- copy this file to "secrets.bat" and fill in your values.
REM  secrets.bat is git-ignored, so your password stays off GitHub.
REM
REM  1) Copy:    copy secrets.example.bat secrets.bat
REM  2) Edit secrets.bat and paste your real values below.
REM  3) run.bat will load it automatically.
REM ===================================================================

REM Gmail App Password for daily email alerts (only if EMAIL_ENABLED = True).
REM Make one at: Google Account > Security > 2-Step Verification > App passwords
set JOB_TRACKER_EMAIL_PASSWORD=paste-your-16-char-app-password-here

REM Optional: free Adzuna API keys from https://developer.adzuna.com/
REM Leave these out entirely if you don't use Adzuna.
REM set ADZUNA_APP_ID=your-app-id
REM set ADZUNA_APP_KEY=your-app-key
