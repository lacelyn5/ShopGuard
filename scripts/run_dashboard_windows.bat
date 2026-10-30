@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo ShopGuard is not installed yet.
  echo First run scripts\setup_windows.bat
  pause
  exit /b 1
)
start "ShopGuard Dashboard Server" ".venv\Scripts\python.exe" dashboard\server.py
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"
echo ShopGuard Dashboard should open in your browser.
echo Keep the separate server window open while using the dashboard.
echo To stop the dashboard, focus the server window and press Ctrl+C.
pause
