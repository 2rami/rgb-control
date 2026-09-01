@echo off
REM 램(SMBus) 제어권을 확보한다.
REM   1. G.SKILL hid.exe 종료 - 얘가 SMBus를 쥐면 우리 쓰기가 무시된다
REM   2. OpenRGB를 관리자 권한으로 재시작 - 아니면 램이 목록에 안 뜬다
REM
REM 관리자 권한이 아니면 스스로 다시 실행한다.

REM ---- 관리자 확인 (무한 반복 방지) ----
REM net session 은 Server 서비스가 꺼져 있으면 관리자여도 실패한다. 그러면
REM 관리자로 올라간 자기 자신이 또 자기를 띄워 끝없이 증식하고 컴퓨터가 멈춘다.
REM fltmc 로 확인하고, 재실행에는 표식을 붙여 딱 한 번만 시도한다.
fltmc >nul 2>&1
if not errorlevel 1 goto _is_admin
if /i "%~1"=="__elevated__" (
    echo.
    echo 관리자로 다시 실행했는데도 관리자가 아닙니다.
    echo 무한 반복을 막기 위해 여기서 멈춥니다.
    echo 이 파일을 오른쪽 클릭 - "관리자 권한으로 실행" 해주세요.
    pause
    exit /b 1
)
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '__elevated__' -Verb RunAs -WindowStyle Hidden"
exit /b
:_is_admin
taskkill /IM hid.exe /F >nul 2>&1
taskkill /IM OpenRGB.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
start "" "C:\Program Files\OpenRGB\OpenRGB.exe" --server
exit /b
