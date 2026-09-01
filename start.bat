@echo off
title RGB 통합 제어

REM 관리자 권한이 아니면 스스로 다시 띄운다 (OpenRGB가 램을 보려면 필요).
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 관리자 권한으로 다시 실행합니다...
    if not "%~1"=="--elevated" (
        powershell -NoProfile -Command "Start-Process '%~f0' -ArgumentList '--elevated' -Verb RunAs"
        exit /b
    )
    echo [guard] elevation did not take effect - continuing without admin
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_all.ps1"
