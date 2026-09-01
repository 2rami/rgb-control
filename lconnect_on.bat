@echo off
title L-Connect 켜기 (비교용)

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
echo [1/3] OpenRGB 종료 ^(같은 허브를 잡으면 충돌^)
taskkill /IM OpenRGB.exe /F >nul 2>&1

echo [2/3] L-Connect 서비스 켜기
sc config LConnectService start= auto >nul
sc config LConnectServiceWatcher start= auto >nul
net start LConnectService
net start LConnectServiceWatcher

echo [3/3] L-Connect 3 실행
start "" "C:\Program Files\Lian-Li\L-Connect 3\L-Connect 3.exe"

echo.
echo 완료. L-Connect에서 흰색을 최대 밝기로 맞춰서 비교해보세요.
echo 비교가 끝나면 lconnect_off.bat 을 실행하세요.
echo.
pause
