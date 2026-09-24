@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 scripts\run.py %*
) else (
    python scripts\run.py %*
)
exit /b %errorlevel%
