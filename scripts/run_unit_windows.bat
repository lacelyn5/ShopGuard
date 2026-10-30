@echo off
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m pytest -m unit -v
pause
