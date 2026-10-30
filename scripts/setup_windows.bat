@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>&1
if %errorlevel%==0 (set "PYTHON=py -3") else (set "PYTHON=python")
echo [1/3] Creating virtual environment...
%PYTHON% -m venv .venv
if errorlevel 1 goto :fail
echo [2/3] Installing Python packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo [3/3] Installing Playwright Chromium...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :fail
echo Setup completed. Start with run_unit_windows.bat
pause
exit /b 0
:fail
echo Installation failed. Review the error above.
pause
exit /b 1
