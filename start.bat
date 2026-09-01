@echo off
title RGB 통합 제어

REM 관리자 권한이 아니면 스스로 다시 띄운다 (OpenRGB가 램을 보려면 필요).
REM ★net session 으로 판정하지 마라. Server 서비스가 꺼져 있으면 관리자인데도
REM 실패해서, 자기가 자기를 끝없이 다시 띄운다. 실제로 그래서 창이 깜빡이고
REM 컴퓨터가 멎었다. fltmc 는 관리자만 성공하고 서비스와 무관하다.
fltmc >nul 2>&1
if not errorlevel 1 goto _is_admin
if /i "%~1"=="__elevated__" (
    echo 관리자로 다시 실행했는데도 관리자가 아닙니다. 그냥 진행합니다.
    goto _is_admin
)
echo 관리자 권한으로 다시 실행합니다...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '__elevated__' -Verb RunAs"
exit /b
:_is_admin

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_all.ps1"
