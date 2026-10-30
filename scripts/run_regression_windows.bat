@echo off
setlocal
cd /d "%~dp0.."
if not exist reports mkdir reports
".venv\Scripts\python.exe" -m pytest -m "(api or ui) and not stateful and not auth" -v --junitxml=reports\regression.xml
pause
