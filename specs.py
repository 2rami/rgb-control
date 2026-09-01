"""이 컴퓨터에 뭐가 꽂혀 있는지 스스로 알아낸다.

    python specs.py

대시보드를 켜면 사양을 훑어서 케이스 그림을 알아서 채우게 하려고 만들었다.
사람이 부품 목록을 손으로 적을 필요가 없다.

무엇을 어디서 가져오나
    CPU·메인보드·램     WMI (윈도우가 들고 있는 것)
    그래픽카드          nvidia-smi (없으면 WMI)
    조명 장치           OpenRGB 가 잡은 목록 (허브 채널 수까지)
    수랭 쿨러           liquidctl (수온·펌프까지 읽히는 것이 곧 증거)

★알 수 없는 것: 팬이 케이스의 '어디'에 달렸는지
    허브는 "채널 3에 팬이 있다"까지만 안다. 그게 위인지 옆인지는 전기적으로
    알 방법이 없다. 그건 사람이 한 번 맞춰 줘야 한다(대시보드의 색칠 기능).
    그래서 이 파일은 "무엇이 몇 개"까지만 책임진다.
"""

import json
import subprocess
import sys
import time

CREATE_NO_WINDOW = 0x08000000
CACHE_SECONDS = 60.0
_cache = {"at": 0.0, "data": None}


def _hidden():
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def _powershell(script):
    """PowerShell 한 조각을 돌려 JSON 으로 받는다.

    창이 뜨면 안 된다. 대시보드는 창 없이 도는 프로그램이고, 사양 조회는
    주기적으로 일어나기 때문에 창이 새면 계속 깜빡인다.
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW, startupinfo=_hidden())
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except Exception:
        return None


def hardware():
    """WMI 로 CPU·보드·램을 읽는다."""
    data = _powershell(r"""
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$bb  = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
$mem = @(Get-CimInstance Win32_PhysicalMemory)
[pscustomobject]@{
  cpu   = $cpu.Name
  cores = $cpu.NumberOfCores
  board = ($bb.Manufacturer + ' ' + $bb.Product)
  ram   = @($mem | ForEach-Object {
            [pscustomobject]@{
              maker = $_.Manufacturer
              gb    = [int]($_.Capacity / 1GB)
              speed = $_.ConfiguredClockSpeed
              slot  = $_.DeviceLocator
            } })
} | ConvertTo-Json -Depth 4 -Compress
""")
    if not data:
        return {}
    ram = data.get("ram") or []
    if isinstance(ram, dict):
        ram = [ram]
    return {
        "cpu": (data.get("cpu") or "").strip(),
        "cores": data.get("cores"),
        "board": (data.get("board") or "").strip(),
        "ram_sticks": len(ram),
        "ram_total_gb": sum(int(x.get("gb") or 0) for x in ram),
        "ram_maker": (ram[0].get("maker") or "").strip() if ram else "",
        "ram_speed": ram[0].get("speed") if ram else None,
    }


def gpu():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=6,
            creationflags=CREATE_NO_WINDOW, startupinfo=_hidden())
        if r.returncode == 0 and r.stdout.strip():
            name, vram = (x.strip() for x in r.stdout.strip().splitlines()[0].split(","))
            return {"name": name, "vram": vram}
    except Exception:
        pass
    d = _powershell("Get-CimInstance Win32_VideoController | "
                    "Select-Object -First 1 Name | ConvertTo-Json -Compress")
    return {"name": (d or {}).get("Name", "")} if d else {}


def lighting():
    """OpenRGB 가 잡은 장치들. 허브는 채널 수까지 본다."""
    try:
        import fan
        cli = fan.connect("specs")
    except Exception:
        return []
    out = []
    try:
        for d in cli.devices:
            item = {"name": d.name, "type": d.type.name, "leds": len(d.leds)}
            zones = getattr(d, "zones", None)
            if zones:
                item["channels"] = len(zones)
                # 유니팬은 채널 하나에 팬 3개까지 줄줄이 물린다.
                item["fan_slots"] = sum(len(z.leds) // 32 for z in zones)
            out.append(item)
    except Exception:
        pass
    return out


def cooler():
    """수랭 쿨러. 대시보드가 이미 잡고 있으면 그쪽 정보를 쓴다."""
    try:
        import owner
        if owner.dashboard_holding():
            return {"name": "NZXT Kraken Elite", "held_by": "대시보드"}
    except Exception:
        pass
    try:
        from liquidctl import find_liquidctl_devices
        for d in find_liquidctl_devices():
            return {"name": d.description}
    except Exception:
        pass
    return {}


def collect(force=False):
    """전부 모아서 돌려준다. 자주 물어도 되게 1분간 기억해 둔다."""
    now = time.time()
    if not force and _cache["data"] and now - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]

    data = {"hardware": hardware(), "gpu": gpu(),
            "lighting": lighting(), "cooler": cooler()}

    # 케이스 그림이 쓸 요약. "팬 자리가 몇 개까지 가능한가"를 알려 준다.
    hub = next((x for x in data["lighting"] if "Uni Hub" in x["name"]), None)
    data["summary"] = {
        "fan_slots": hub.get("fan_slots") if hub else 0,
        "hub": hub["name"] if hub else None,
        "ram_sticks": data["hardware"].get("ram_sticks", 0),
        "has_gpu_led": any(x["type"] == "LEDSTRIP" for x in data["lighting"]),
        "has_speaker": any(x["type"] == "SPEAKER" for x in data["lighting"]),
        "has_lcd": bool(data["cooler"]),
    }
    _cache.update(at=now, data=data)
    return data


def main():
    d = collect(force=True)
    h, g = d["hardware"], d["gpu"]
    print(f"CPU        {h.get('cpu','?')}  ({h.get('cores','?')}코어)")
    print(f"메인보드   {h.get('board','?')}")
    print(f"램         {h.get('ram_sticks','?')}개 / {h.get('ram_total_gb','?')}GB "
          f"{h.get('ram_maker','')} {h.get('ram_speed','')}MHz")
    print(f"그래픽카드 {g.get('name','?')} {g.get('vram','')}")
    print(f"수랭       {d['cooler'].get('name','못 찾음')}")
    print()
    print("조명 장치")
    for x in d["lighting"]:
        extra = ""
        if "channels" in x:
            extra = f"  채널 {x['channels']}개, 팬 자리 최대 {x['fan_slots']}개"
        print(f"  {x['type']:9s} {x['leds']:4d} LED  {x['name']}{extra}")
    print()
    print("요약:", d["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
