@echo off
REM 대시보드를 내린다. 관리자로 떠 있을 수도 있어서(작업 스케줄러가 띄운
REM 경우) 우리도 관리자여야 죽일 수 있다. 권한이 없으면 목록에 보이지도
REM 않아서 "0개 남음"으로 착각하게 된다.
title RGB 제어 정지

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

powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*dashboard.py*' } | ForEach-Object { Write-Host ('대시보드 종료 PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }"

echo.
echo 조명은 마지막 색 그대로 남습니다.
echo 크라켄은 풀렸으니 이제 NZXT CAM 을 쓸 수 있습니다.
echo.
timeout /t 3 >nul
