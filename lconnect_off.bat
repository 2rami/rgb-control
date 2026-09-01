@echo off
title L-Connect 끄기 (원상복구)

REM 관리자 권한이 아니면 스스로 다시 띄운다.
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
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '__elevated__' -Verb RunAs"
exit /b
:_is_admin
echo [1/3] L-Connect 앱 종료
taskkill /IM "L-Connect 3.exe" /F >nul 2>&1

echo [2/3] 서비스 끄고 비활성화
REM Watcher를 먼저 꺼야 한다. 얘가 살아있으면 Service를 되살린다.
net stop LConnectServiceWatcher >nul 2>&1
net stop LConnectService >nul 2>&1
sc config LConnectServiceWatcher start= disabled >nul
sc config LConnectService start= disabled >nul

echo [3/3] 상태 확인
sc query LConnectService | findstr STATE
sc query LConnectServiceWatcher | findstr STATE

echo.
echo 완료. 이제 start.bat 으로 우리 제어를 다시 켜면 됩니다.
echo.
pause
