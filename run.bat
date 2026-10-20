@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "DSH_PY=C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

where python >nul 2>&1
if %errorlevel%==0 (
    python bot.py
    goto :end
)

if exist "%DSH_PY%" (
    "%DSH_PY%" bot.py
    goto :end
)

echo Python не найден. Установите Python 3.10+ и добавьте его в PATH.
pause

:end
if errorlevel 1 pause
endlocal
