"""데이지체인 가설 검증: Razer 채널당 LED를 20 -> 60으로 늘린다.
신호가 닿는 범위가 넓어지면 무지개 팬이 제어권 안으로 들어온다."""

import socket
import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

NEW_SIZE = 60


def alive(timeout=3):
    try:
        with socket.create_connection(("127.0.0.1", 6742), timeout=timeout):
            return True
    except Exception:
        return False


cli = OpenRGBClient(address="127.0.0.1", port=6742, name="expand")
razer = next((d for d in cli.devices if "Razer" in d.name and "Addressable" in d.name), None)
lianli = next((d for d in cli.devices if "Lian Li" in d.name), None)

if razer is None:
    print("[X] Razer 컨트롤러 없음")
    raise SystemExit(1)

print(f"현재 Razer: 채널 {len(razer.zones)}개 / LED {len(razer.leds)}개")
print(f"채널당 {NEW_SIZE}개로 확장합니다...\n")

for i, zone in enumerate(razer.zones):
    try:
        zone.resize(NEW_SIZE)
        print(f"  채널 {i+1}: OK")
    except Exception as e:
        print(f"  채널 {i+1}: 실패 - {e!r}")
    time.sleep(0.4)
    if not alive():
        print("\n[X] 서버가 죽었습니다. 이 크기는 지원되지 않습니다.")
        raise SystemExit(1)

time.sleep(1.5)
cli.update()
razer = cli.devices[razer.id]
lianli = cli.devices[lianli.id] if lianli else None
print(f"\n확장 후: LED {len(razer.leds)}개\n")

razer.set_mode("direct")
time.sleep(0.4)

# 리안리는 완전히 꺼서, 변화가 Razer 때문임을 확실히 한다.
if lianli and len(lianli.leds) > 0:
    try:
        lianli.set_colors([RGBColor(0, 0, 0)] * len(lianli.leds))
    except Exception:
        pass

print(">>> Razer 전체 빨강 (8초) — 무지개 팬을 보세요")
razer.set_colors([RGBColor(255, 0, 0)] * len(razer.leds))
time.sleep(8)

print(">>> Razer 전체 소등 (6초) — 무지개가 사라지는지 보세요")
razer.set_colors([RGBColor(0, 0, 0)] * len(razer.leds))
time.sleep(6)

print(">>> Razer 전체 초록 (유지)")
razer.set_colors([RGBColor(0, 255, 0)] * len(razer.leds))

print(f"\n서버 상태: {'정상' if alive() else '죽음'}")
