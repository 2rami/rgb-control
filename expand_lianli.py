"""리안리 채널당 LED를 늘려 데이지체인 뒤쪽 팬까지 신호를 보낸다.
크래시 이력이 있으므로 한 채널씩 늘리고 매번 서버 생사를 확인한다."""

import socket
import sys
import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

NEW_SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 60


def alive(timeout=3):
    try:
        with socket.create_connection(("127.0.0.1", 6742), timeout=timeout):
            return True
    except Exception:
        return False


if not alive():
    print("[X] 서버가 죽어 있습니다. OpenRGB를 먼저 실행하세요.")
    raise SystemExit(1)

cli = OpenRGBClient(address="127.0.0.1", port=6742, name="expand-lianli")
lianli = next((d for d in cli.devices if "Lian Li" in d.name), None)

if lianli is None:
    print("[X] 리안리 허브를 찾지 못했습니다.")
    raise SystemExit(1)

print(f"현재: 채널 {len(lianli.zones)}개 / LED {len(lianli.leds)}개")
print(f"목표: 채널당 {NEW_SIZE}개\n")

for i, zone in enumerate(lianli.zones):
    if len(zone.leds) >= NEW_SIZE:
        print(f"  채널 {i+1}: 이미 충분함 ({len(zone.leds)}개)")
        continue
    try:
        zone.resize(NEW_SIZE)
        print(f"  채널 {i+1}: {NEW_SIZE}개로 확장")
    except Exception as e:
        print(f"  채널 {i+1}: 실패 - {e!r}")
    time.sleep(0.5)
    if not alive():
        print(f"\n[X] 채널 {i+1}에서 서버가 죽었습니다.")
        print(f"    이 허브는 채널당 {NEW_SIZE}개를 감당하지 못합니다.")
        print(f"    더 작은 값으로 재시도하세요: python expand_lianli.py 40")
        raise SystemExit(1)

time.sleep(1.5)
cli.update()
lianli = cli.devices[lianli.id]
print(f"\n확장 후: LED {len(lianli.leds)}개")

mode_names = [m.name.lower() for m in lianli.modes]
try:
    lianli.set_mode("custom" if "custom" in mode_names else "static")
except Exception as e:
    print(f"모드 전환 실패: {e!r}")
time.sleep(0.5)

print("\n>>> 전체 빨강 적용 (고정)")
try:
    lianli.set_colors([RGBColor(255, 0, 0)] * len(lianli.leds))
    print("완료")
except Exception as e:
    print(f"실패: {e!r}")

print(f"\n서버 상태: {'정상' if alive() else '죽음'}")
print("무지개 팬 2개가 빨갛게 변했는지 확인하세요.")
