@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
if exist python\python.exe set PY=python\python.exe
%PY% -m app.main %*
echo.
echo 小灶已退出。
pause
