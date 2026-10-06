@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动小灶…(服务起来后浏览器会自动打开;这个窗口别关)
set PY=python
if exist python\python.exe set PY=python\python.exe
%PY% -m app.main %*
echo.
echo 小灶已退出。
pause
