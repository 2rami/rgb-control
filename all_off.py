"""리안리와 Razer를 완전히 소등한다.
이 상태에서도 켜져 있는 팬은 두 컨트롤러 어디에도 속하지 않는다는 뜻이다."""

import socket
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

BLACK = RGBColor(0, 0, 0)


def alive(timeout=3):
    try:
        with socket.create_connection(("127.0.0.1", 6742), timeout=timeout):
            return True
    except Exception:
        return False


cli = OpenRGBClient(address="127.0.0.1", port=6742, name="all-off")

for dev in cli.devices:
    if len(dev.leds) == 0:
        continue
    try:
        dev.set_colors([BLACK] * len(dev.leds))
        print(f"  소등: {dev.name} (LED {len(dev.leds)}개)")
    except Exception as e:
        print(f"  실패: {dev.name} - {e!r}")

print(f"\n서버 상태: {'정상' if alive() else '죽음'}")
print("\n>>> 지금 켜져 있는 팬이 있다면, 그 팬은 OpenRGB가 제어하는")
print("    어떤 컨트롤러에도 연결돼 있지 않다는 뜻입니다.")
