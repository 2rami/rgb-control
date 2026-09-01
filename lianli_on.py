"""리안리 허브에 색을 고정한다. 시간 제한 없이 켜두고 사용자가 확인한다."""

import socket
import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor


def alive(timeout=3):
    try:
        with socket.create_connection(("127.0.0.1", 6742), timeout=timeout):
            return True
    except Exception:
        return False


cli = OpenRGBClient(address="127.0.0.1", port=6742, name="lianli-on")
lianli = next((d for d in cli.devices if "Lian Li" in d.name), None)
razer = next((d for d in cli.devices if "Razer" in d.name and "Addressable" in d.name), None)

if lianli is None:
    print("[X] 리안리 허브를 찾지 못했습니다.")
    raise SystemExit(1)

print(f"리안리: 채널 {len(lianli.zones)}개 / LED {len(lianli.leds)}개")
print(f"현재 모드: {lianli.modes[lianli.active_mode].name}\n")

# Razer는 계속 꺼둬서 변화의 원인을 리안리로 한정한다.
if razer and len(razer.leds) > 0:
    try:
        razer.set_colors([RGBColor(0, 0, 0)] * len(razer.leds))
        print("Razer: 소등 유지")
    except Exception as e:
        print(f"Razer 소등 실패: {e!r}")

mode_names = [m.name.lower() for m in lianli.modes]
target = "custom" if "custom" in mode_names else "static"
try:
    lianli.set_mode(target)
    print(f"리안리 모드: {target}")
except Exception as e:
    print(f"모드 전환 실패: {e!r}")
time.sleep(0.5)

print("\n>>> 리안리 전체 빨강으로 고정합니다.")
try:
    lianli.set_colors([RGBColor(255, 0, 0)] * len(lianli.leds))
    print("적용 완료")
except Exception as e:
    print(f"실패: {e!r}")

print(f"\n서버 상태: {'정상' if alive() else '죽음'}")
print("\n색이 이대로 유지됩니다. 천천히 확인하세요.")
