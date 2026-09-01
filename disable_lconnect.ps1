Start-Transcript -Path "C:\Users\2rami\Desktop\rgb-control\lconnect_result.txt" -Force | Out-Null
$ErrorActionPreference = 'SilentlyContinue'
$backup = "C:\Users\2rami\Desktop\rgb-control\RESTORE_INFO.txt"

"" | Out-File $backup -Append
"=== L-Connect 서비스 비활성화 ($(Get-Date)) ===" | Out-File $backup -Append
"LConnectServiceWatcher = Automatic (원래값)" | Out-File $backup -Append
"LConnectService = Automatic (원래값)" | Out-File $backup -Append
"되돌리기: Set-Service -Name LConnectService -StartupType Automatic" | Out-File $backup -Append
"          Set-Service -Name LConnectServiceWatcher -StartupType Automatic" | Out-File $backup -Append

Write-Output "=== 1. Watcher 먼저 비활성화 ==="
Set-Service -Name 'LConnectServiceWatcher' -StartupType Disabled
Stop-Service -Name 'LConnectServiceWatcher' -Force
Write-Output "  LConnectServiceWatcher: Disabled + 중지"
Start-Sleep -Seconds 2

Write-Output ""
Write-Output "=== 2. 본체 서비스 비활성화 ==="
Set-Service -Name 'LConnectService' -StartupType Disabled
Stop-Service -Name 'LConnectService' -Force
Write-Output "  LConnectService: Disabled + 중지"
Start-Sleep -Seconds 2

Write-Output ""
Write-Output "=== 3. 남은 프로세스 정리 ==="
foreach ($n in @('L-Connect-Service-Watcher','L-Connect-Service','L-Connect 3','L-Connect')) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force
        Write-Output "  종료: $($_.ProcessName) ($($_.Id))"
    }
}
Start-Sleep -Seconds 3

Write-Output ""
Write-Output "=== 4. 결과 확인 ==="
Get-Service | Where-Object { $_.Name -match 'LConnect' } | Select-Object Name, Status, StartType | Format-Table -AutoSize | Out-String | Write-Output
$left = Get-Process | Where-Object { $_.ProcessName -match 'L-Connect' } | Select-Object ProcessName, Id
if ($left) { Write-Output "아직 실행 중:"; $left | Format-Table -AutoSize | Out-String | Write-Output }
else { Write-Output "L-Connect 프로세스 완전 종료됨" }

Stop-Transcript | Out-Null
