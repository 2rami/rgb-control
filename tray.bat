@echo off
REM RGB 제어 - 트레이로 띄운다. 이게 주인이다.
REM 트레이를 끝내면 대시보드도 같이 꺼진다.
title RGB 제어 트레이

REM ---- 관리자 확인 ----
REM OpenRGB 가 램(SMBus)을 보려면 관리자여야 한다. 자식은 부모 권한을
REM 물려받으므로 여기서 한 번만 올리면 대시보드까지 관리자가 된다.
REM
REM ★net session 으로 판정하지 마라. Server 서비스가 꺼져 있으면 관리자인데도
REM 실패해서 자기가 자기를 끝없이 다시 띄운다. 실제로 그래서 창이 깜빡이고
REM 컴퓨터가 멎었다. fltmc 는 관리자만 성공하고 서비스와 무관하다.
fltmc >nul 2>&1
if not errorlevel 1 goto _is_admin
if /i "%~1"=="__elevated__" (
    echo 관리자로 다시 실행했는데도 관리자가 아닙니다. 그냥 진행합니다.
    goto _is_admin
)
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '__elevated__' -Verb RunAs"
exit /b
:_is_admin

REM pythonw 는 검은 창을 안 남긴다. 트레이는 창이 필요 없다.
where pythonw >nul 2>&1
if errorlevel 1 (
    python "%~dp0tray.py"
) else (
    start "" pythonw "%~dp0tray.py"
)
