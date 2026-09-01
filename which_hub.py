"""팬이 Razer 컨트롤러에 물렸는지 리안리 허브에 물렸는지 확정한다.
한쪽만 켜고 다른 쪽은 완전히 꺼서 구분한다."""

import socket
import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

BLACK = RGBColor(0, 0, 0)


def alive(host="127.0.0.1", port=6742, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


cli = OpenRGBClient(address="127.0.0.1", port=6742, name="which-hub")

razer = next((d for d in cli.devices if "Razer" in d.name and "Addressable" in d.name), None)
lianli = next((d for d in cli.devices if "Lian Li" in d.name), None)

print(f"Razer : {'LED ' + str(len(razer.leds)) + '개' if razer else '없음'}")
print(f"리안리: {'LED ' + str(len(lianli.leds)) + '개' if lianli else '없음'}\n")


def paint(dev, color):
    if dev is None or len(dev.leds) == 0:
        return
    try:
        dev.set_colors([color] * len(dev.leds))
    except Exception as e:
        print(f"    [!] {dev.name}: {e!r}")


print(">>> 1단계: Razer만 빨강, 리안리는 소등 (6초)")
paint(lianli, BLACK)
paint(razer, RGBColor(255, 0, 0))
time.sleep(6)
print(f"    서버: {'정상' if alive() else '죽음'}")

print("\n>>> 2단계: 리안리만 파랑, Razer는 소등 (6초)")
paint(razer, BLACK)
paint(lianli, RGBColor(0, 0, 255))
time.sleep(6)
print(f"    서버: {'정상' if alive() else '죽음'}")

print("\n>>> 3단계: 둘 다 소등 (4초)")
paint(razer, BLACK)
paint(lianli, BLACK)
time.sleep(4)

print("\n>>> 4단계: 둘 다 초록 (원상복구)")
paint(razer, RGBColor(0, 255, 0))
paint(lianli, RGBColor(0, 255, 0))

print(f"\n최종 서버 상태: {'정상' if alive() else '죽음'}")
