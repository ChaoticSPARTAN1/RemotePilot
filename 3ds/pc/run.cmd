@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 receiver.py serve %*
    exit /b %errorlevel%
)
python receiver.py serve %*
