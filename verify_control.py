"""OpenRGB가 하드웨어를 실제로 제어하는지 안전하게 검증한다.

원칙:
- resize를 하지 않는다 (크래시 방아쇠 회피)
- LED 개수를 하드웨어가 스스로 보고한 장치만 다룬다
- 매 단계마다 서버가 살아있는지 확인한다
"""

import socket
import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor


def server_alive(host="127.0.0.1", port=6742, timeout=3):
    """서버가 살아있는지 소켓으로 직접 확인한다."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


if not server_alive():
    print("[X] OpenRGB 서버가 응답하지 않습니다. 실행 중인지 확인하세요.")
    raise SystemExit(1)

cli = OpenRGBClient(address="127.0.0.1", port=6742, name="verify")
print(f"[O] 연결됨 - 장치 {len(cli.devices)}개\n")

# LED 개수가 0보다 큰 장치 = 하드웨어가 스스로 보고한 것. resize 불필요.
targets = [d for d in cli.devices if len(d.leds) > 0]

if not targets:
    print("[X] LED 개수가 확정된 장치가 없습니다.")
    raise SystemExit(1)

print("검증 대상 (resize 없이 그대로 사용):")
for d in targets:
    print(f"  - {d.name}: LED {len(d.leds)}개")
print()

for d in targets:
    if "direct" in [m.name.lower() for m in d.modes]:
        try:
            d.set_mode("direct")
        except Exception as e:
            print(f"  [!] {d.name} direct 실패: {e!r}")
    time.sleep(0.2)

sequence = [
    ("빨강", RGBColor(255, 0, 0)),
    ("초록", RGBColor(0, 255, 0)),
    ("파랑", RGBColor(0, 0, 255)),
    ("흰색", RGBColor(255, 255, 255)),
]

for label, color in sequence:
    if not server_alive():
        print(f"\n[X] '{label}' 직전에 서버가 죽었습니다.")
        raise SystemExit(1)

    print(f"  -> {label}")
    for d in targets:
        try:
            d.set_colors([color] * len(d.leds))
        except Exception as e:
            print(f"     [!] {d.name}: {e!r}")
    time.sleep(2.5)

print("\n  -> 보라색 고정")
for d in targets:
    try:
        d.set_colors([RGBColor(160, 0, 255)] * len(d.leds))
    except Exception as e:
        print(f"     [!] {d.name}: {e!r}")

print(f"\n서버 상태: {'정상' if server_alive() else '죽음'}")
print("검증 끝. 램과 스피커를 확인하세요.")
