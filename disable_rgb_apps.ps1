Start-Transcript -Path "C:\Users\2rami\Desktop\rgb-control\disable_result.txt" -Force | Out-Null
$ErrorActionPreference = 'SilentlyContinue'
$backup = "C:\Users\2rami\Desktop\rgb-control\RESTORE_INFO.txt"

"=== RGB 소프트웨어 자동시작 해제 백업 ===" | Out-File $backup
"생성 시각: $(Get-Date)" | Out-File $backup -Append
"" | Out-File $backup -Append

Write-Output "=== 1. L-Connect 종료 (Watcher 먼저) ==="
# Watcher를 먼저 죽여야 Service가 되살아나지 않는다.
foreach ($n in @('L-Connect-Service-Watcher','L-Connect-Service','L-Connect 3','L-Connect')) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force
        Write-Output "  종료: $($_.ProcessName) ($($_.Id))"
    }
    Start-Sleep -Milliseconds 300
}

Write-Output ""
Write-Output "=== 2. L-Connect 작업 스케줄러 비활성화 ==="
$t = Get-ScheduledTask -TaskPath '\LianLi\' -ErrorAction SilentlyContinue
foreach ($task in $t) {
    "작업스케줄러: $($task.TaskPath)$($task.TaskName) = $($task.State)" | Out-File $backup -Append
    Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath | Out-Null
    Write-Output "  비활성화: $($task.TaskPath)$($task.TaskName)"
}

Write-Output ""
Write-Output "=== 3. Razer 시작 프로그램 제거 ==="
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
foreach ($name in @('RazerAppEngine')) {
    $val = (Get-ItemProperty $runKey -Name $name -ErrorAction SilentlyContinue).$name
    if ($val) {
        "레지스트리 Run: $name = $val" | Out-File $backup -Append
        Remove-ItemProperty -Path $runKey -Name $name -Force
        Write-Output "  제거: $name"
    }
}

Write-Output ""
Write-Output "=== 4. Razer 서비스 자동시작 해제 ==="
Get-Service | Where-Object { $_.Name -match 'Razer' -and $_.StartType -eq 'Automatic' } | ForEach-Object {
    "서비스: $($_.Name) = $($_.StartType)" | Out-File $backup -Append
    Set-Service -Name $_.Name -StartupType Manual
    Stop-Service -Name $_.Name -Force
    Write-Output "  Manual 전환 + 중지: $($_.Name)"
}

Write-Output ""
Write-Output "=== 5. Razer 프로세스 종료 ==="
foreach ($n in @('RazerAppEngine','RazerExperienceService','razer_elevation_service')) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force
        Write-Output "  종료: $($_.ProcessName)"
    }
}

Write-Output ""
Write-Output "=== 결과 확인 ==="
$left = Get-Process | Where-Object { $_.ProcessName -match 'Razer|L-Connect|Lian' } | Select-Object ProcessName, Id
if ($left) { $left | Format-Table -AutoSize | Out-String | Write-Output } else { Write-Output "  Razer/리안리 프로세스 없음" }

"" | Out-File $backup -Append
"=== 되돌리는 법 ===" | Out-File $backup -Append
"작업스케줄러: Enable-ScheduledTask -TaskName 'L-Connect 3' -TaskPath '\LianLi\'" | Out-File $backup -Append
"서비스: Set-Service -Name <이름> -StartupType Automatic" | Out-File $backup -Append
"시작프로그램: 위에 기록된 경로를 HKCU Run 키에 다시 추가" | Out-File $backup -Append

Write-Output ""
Write-Output "백업 파일: $backup"

Stop-Transcript | Out-Null
