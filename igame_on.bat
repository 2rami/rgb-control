@echo off
REM iGameCenter 를 다시 켠다.
title iGameCenter 켜기

REM ---- 관리자 확인 (무한 반복 방지) ----
fltmc >nul 2>&1
if not errorlevel 1 goto _is_admin
if /i "%~1"=="__elevated__" (
    echo.
    echo 관리자로 다시 실행했는데도 관리자가 아닙니다. 여기서 멈춥니다.
    pause
    exit /b 1
)
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '__elevated__' -Verb RunAs"
exit /b
:_is_admin

sc start iGameCenterService >nul 2>&1
echo iGameCenter 다시 켬.
timeout /t 2 >nul
exit /b
