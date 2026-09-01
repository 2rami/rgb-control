@echo off
REM cam_off.bat 과 같은 일을 하되 pause 가 없다.
REM 숨김 창으로 자동 실행할 때 쓴다 (pause 가 있으면 거기서 멈춘다).
REM 되돌리려면 cam_on.bat.

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
REM 서비스를 먼저 내려야 한다. 프로세스만 죽이면 서비스가 계속 되살린다.
net stop CAMService >nul 2>&1
sc config CAMService start= demand >nul

taskkill /IM "NZXT CAM.exe" /F >nul 2>&1
taskkill /IM "cam_helper.exe" /F >nul 2>&1
exit /b
