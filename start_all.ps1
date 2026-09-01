# RGB 통합 제어 시작 스크립트
#
# start.bat 을 관리자 권한으로 실행하면 이 파일이 돌아간다.
# 관리자 권한이 필요한 이유: OpenRGB가 램(SMBus)을 보려면 관리자여야 한다.
#
# 하는 일
#   1. G.SKILL hid.exe 종료  - 얘가 SMBus를 쥐고 있으면 램 제어가 통째로 무시된다
#   2. OpenRGB를 서버 모드로 실행
#   3. 장치 감지가 끝날 때까지 대기 (약 45초 걸린다)
#   4. 대시보드를 창 없이 실행
#
# 모든 단계를 start.log 에 적는다. 이 창이 눈 깜짝할 새에 닫혀 버리면
# 로그가 무슨 일이 있었는지 말해주는 유일한 증거다.

# 부팅 자동 시작에서는 브라우저를 안 띄운다. 손으로 켤 때만 띄운다.
# -PrepOnly: 준비만 하고 대시보드는 안 띄운다. 트레이가 주인일 때 쓴다 -
# 트레이가 대시보드를 자기 자식으로 띄워야 끌 때 같이 끌 수 있다.
param([switch]$NoBrowser, [switch]$PrepOnly)

$ErrorActionPreference = 'Continue'
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$log  = Join-Path $proj 'start.log'

function Say($msg, $color = 'Gray') {
    Write-Host $msg -ForegroundColor $color
    "$(Get-Date -Format 'MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

"" | Out-File -FilePath $log -Append -Encoding utf8
$isAdmin = (New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
Say "=== 시작 (관리자=$isAdmin) ===" Cyan

try {
    Say "[1/4] 다른 조명 프로그램 종료" Cyan
    # 이 둘이 살아 있으면 우리가 쏘는 색이 통째로 무시된다. 쓰기는 성공으로
    # 돌아오는데 장치는 저쪽 색 그대로라, 안 되는 이유를 찾기가 아주 어렵다.
    #   hid            = G.SKILL Trident Z Lighting Control -> 램(SMBus)을 쥔다
    #   RazerAppEngine = Razer Synapse -> Razer ARGB 컨트롤러(=글카)를 쥔다
    foreach ($name in @('hid', 'RazerAppEngine', 'razerwdl')) {
        $procs = @(Get-Process -Name $name -ErrorAction SilentlyContinue)
        if ($procs.Count -gt 0) {
            $procs | Stop-Process -Force -ErrorAction SilentlyContinue
            Say "      $name $($procs.Count)개 종료함" Green
        } else {
            Say "      $name 이미 꺼져 있음"
        }
    }

    Say "[2/4] OpenRGB 확인" Cyan
    $env:PYTHONIOENCODING = 'utf-8'
    $rgb = Get-Process -Name 'OpenRGB' -ErrorAction SilentlyContinue
    $wait = 45
    if ($rgb) {
        # 이미 떠 있어도 그냥 쓰면 안 된다. 관리자가 아닌 채로 떠 있었으면
        # 램(SMBus)이 목록에 아예 안 잡히는데, 겉으로는 멀쩡해 보인다.
        $ram = (& python "$proj\has_ram.py" 2>$null | Select-Object -Last 1)
        Say "      실행 중 (PID $($rgb.Id)), 램 보임=$ram"
        if ($ram -eq 'yes') {
            $wait = 3
        } else {
            Say "      램이 안 보임 - 관리자로 다시 띄움" Yellow
            $rgb | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Start-Process "C:\Program Files\OpenRGB\OpenRGB.exe" -ArgumentList "--server"
        }
    } else {
        Start-Process "C:\Program Files\OpenRGB\OpenRGB.exe" -ArgumentList "--server"
        Say "      실행함" Green
    }

    Say "[3/4] 장치 감지 대기 ($wait 초)" Cyan
    for ($i = $wait; $i -gt 0; $i--) {
        Write-Host "`r      $i 초 남음   " -NoNewline
        Start-Sleep -Seconds 1
    }
    Write-Host "`r                    "

    if ($PrepOnly) {
        Say "=== 준비 완료 (대시보드는 트레이가 띄운다) ===" Green
        return
    }

    Say "[4/4] 대시보드 실행" Cyan
    # 이미 돌고 있으면 포트 5000을 못 잡고 조용히 죽는다. 먼저 정리한다.
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*dashboard.py*' } |
        ForEach-Object { Say "      기존 대시보드 종료 (PID $($_.ProcessId))"
                         Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    # pythonw 는 콘솔 창을 안 만든다. python 으로 띄우면 검은 창이 계속 떠 있다.
    $pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    if (-not $pyw) { $pyw = 'python' }
    Start-Process $pyw -ArgumentList "dashboard.py" -WorkingDirectory $proj -WindowStyle Hidden
    Say "      $pyw 로 띄움" Green

    Start-Sleep -Seconds 5
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:5000" }
    Say "=== 완료 - http://127.0.0.1:5000 ===" Green
}
catch {
    Say "!!! 오류: $($_.Exception.Message)" Red
    Say "!!! 위치: $($_.InvocationInfo.PositionMessage)" Red
    Read-Host "엔터를 누르면 닫힌다"
}
