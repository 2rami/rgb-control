# 부팅할 때 우리 조명·냉각 프로그램이 스스로 뜨게 만든다.
#
#   설치:  install_autostart.ps1
#   제거:  install_autostart.ps1 -Remove
#
# 왜 작업 스케줄러인가
#   OpenRGB 가 램(SMBus)을 보려면 관리자여야 한다. 그런데 시작프로그램
#   (레지스트리 Run)에 넣으면 관리자로 못 뜨고, 우리가 손으로 띄우면 매번
#   UAC 창이 뜬다. 작업 스케줄러의 "가장 높은 권한으로 실행"으로 등록하면
#   로그인할 때 UAC 없이 관리자로 뜬다.
#
# CAM 자동 시작도 같이 끈다
#   CAM 이 먼저 크라켄을 잡으면 우리가 못 쓴다. 장치를 잡을 수 있는 것은
#   한 프로그램뿐이다. 지운 값은 cam_autostart_backup.txt 에 적어 두므로
#   나중에 그대로 되돌릴 수 있다.

param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = 'RGB Control'
$runKey = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
# 끌 벤더 자동 시작 목록. 이들이 살아 있으면 우리 색이 통째로 무시된다.
#   NZXT.CAM       크라켄(수랭·LCD)을 잡는다
#   RazerAppEngine Razer ARGB 컨트롤러(=그래픽카드 LED)를 잡는다
$vendorRuns = @('NZXT.CAM', 'RazerAppEngine')
$backup = Join-Path $proj 'vendor_autostart_backup.json'

$isAdmin = (New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "관리자 권한이 필요합니다. 다시 띄웁니다..." -ForegroundColor Yellow
    $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$MyInvocation.MyCommand.Path)
    if ($Remove) { $argList += '-Remove' }
    Start-Process powershell.exe -ArgumentList $argList -Verb RunAs
    return
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "자동 시작 지움: $taskName" -ForegroundColor Green

    if (Test-Path $backup) {
        $saved = Get-Content $backup -Raw | ConvertFrom-Json
        foreach ($n in $saved.PSObject.Properties.Name) {
            Set-ItemProperty -Path $runKey -Name $n -Value $saved.$n
            Write-Host "$n 자동 시작 되돌림" -ForegroundColor Green
        }
    }
    Read-Host "엔터를 누르면 닫힙니다"
    return
}

# --- 벤더 자동 시작 끄기 (되돌릴 수 있게 적어 둔다) ---
$saved = @{}
if (Test-Path $backup) {
    (Get-Content $backup -Raw | ConvertFrom-Json).PSObject.Properties |
        ForEach-Object { $saved[$_.Name] = $_.Value }
}
foreach ($n in $vendorRuns) {
    $val = (Get-ItemProperty -Path $runKey -Name $n -ErrorAction SilentlyContinue).$n
    if ($val) {
        $saved[$n] = $val
        Remove-ItemProperty -Path $runKey -Name $n
        Write-Host "$n 자동 시작 껐음" -ForegroundColor Green
    } else {
        Write-Host "$n 자동 시작은 이미 꺼져 있음" -ForegroundColor DarkGray
    }
}
if ($saved.Count -gt 0) {
    $saved | ConvertTo-Json | Set-Content -Path $backup -Encoding UTF8
    Write-Host "  되돌릴 값은 $backup 에 적어 뒀습니다" -ForegroundColor DarkGray
}

# --- 우리 것 등록 ---
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$proj\start_all.ps1`" -NoBrowser" `
    -WorkingDirectory $proj

# 로그인 직후에는 장치가 아직 다 안 올라와 있다. 조금 기다렸다 시작한다.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT30S'

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Highest

# 배터리·유휴 조건 때문에 안 뜨는 일이 없게 전부 끈다. 데스크탑이다.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "자동 시작 등록함: $taskName" -ForegroundColor Green
Write-Host "  로그인 30초 뒤에 UAC 없이 관리자로 뜹니다." -ForegroundColor DarkGray
Write-Host "  되돌리려면: install_autostart.ps1 -Remove" -ForegroundColor DarkGray
Read-Host "엔터를 누르면 닫힙니다"
