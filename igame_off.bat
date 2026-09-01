@echo off
REM iGameCenter 를 멈춘다. 얘가 글카 LED 를 계속 덮어쓰고 있으면
REM 우리가 색을 보내도 곧바로 되돌려진다.
REM (램에서 G.SKILL hid.exe 가 SMBus 를 쥐고 있던 것과 같은 구조)
title iGameCenter 끄기

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

sc stop iGameCenterService >nul 2>&1
taskkill /IM iGameCenter.exe /F >nul 2>&1
taskkill /IM iGameCenter.Service.exe /F >nul 2>&1
echo iGameCenter 멈춤. 되살리려면 igame_on.bat
timeout /t 2 >nul
exit /b
