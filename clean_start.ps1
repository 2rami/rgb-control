$ErrorActionPreference = 'SilentlyContinue'

Write-Output "=== 1. Razer 서비스 중지 ==="
Get-Service | Where-Object { $_.Name -match 'Razer' -and $_.Status -eq 'Running' } | ForEach-Object {
    Write-Output "  중지: $($_.Name)"
    Stop-Service -Name $_.Name -Force
}

Write-Output ""
Write-Output "=== 2. RGB 프로그램 종료 ==="
$targets = @('NZXT CAM','cam_helper','lghub','lghub_agent','lghub_system_tray','lghub_updater',
             'RazerAppEngine','RazerExperienceService','razer_elevation_service','RazerCentralService')
foreach ($t in $targets) {
    Get-Process -Name $t -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Output "  종료: $($_.ProcessName) (PID $($_.Id))"
        Stop-Process -Id $_.Id -Force
    }
}

Start-Sleep -Seconds 3

Write-Output ""
Write-Output "=== 3. 남은 RGB 프로그램 확인 ==="
$left = Get-Process | Where-Object { $_.ProcessName -match 'Razer|NZXT|cam_helper|lghub' }
if ($left) { $left | Select-Object Id, ProcessName | Format-Table -AutoSize | Out-String | Write-Output }
else { Write-Output "  없음 - 깨끗함" }

Write-Output ""
Write-Output "=== 4. OpenRGB 재시작 (장치 재감지) ==="
Get-Process OpenRGB -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-Process -FilePath "C:\Program Files\OpenRGB\OpenRGB.exe" -ArgumentList "--server"
Write-Output "  OpenRGB 시작됨. 장치 감지에 약 30초 걸립니다."
