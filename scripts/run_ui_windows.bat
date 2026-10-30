@echo off
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m pytest -m "ui and smoke" -v
pause
