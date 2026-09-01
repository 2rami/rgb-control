"""Razer 컨트롤러의 신호 생성을 완전히 중단시키고 리안리만 남긴다.
두 신호원의 충돌이 원인이라면, 이것만으로 무지개가 사라져야 한다."""

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


cli = OpenRGBClient(address="127.0.0.1", port=6742, name="razer-off")
razer = next((d for d in cli.devices if "Razer" in d.name and "Addressable" in d.name), None)
lianli = next((d for d in cli.devices if "Lian Li" in d.name), None)

print("=== 1. Razer 신호 생성 중단 ===")
if razer:
    print(f"  사용 가능한 모드: {', '.join(m.name for m in razer.modes)}")
    # Direct 모드는 계속 데이터를 흘려보낸다. Off 모드로 바꿔 신호 자체를 끊는다.
    try:
        razer.set_mode("off")
        print("  -> 'Off' 모드로 전환 (신호 생성 중단)")
    except Exception as e:
        print(f"  -> Off 모드 실패: {e!r}")
        try:
            razer.set_colors([RGBColor(0, 0, 0)] * len(razer.leds))
            print("  -> 대신 전체 소등 적용")
        except Exception as e2:
            print(f"  -> 소등도 실패: {e2!r}")
time.sleep(2)

print("\n=== 2. 리안리만 빨강 적용 ===")
if lianli:
    mode_names = [m.name.lower() for m in lianli.modes]
    try:
        lianli.set_mode("custom" if "custom" in mode_names else "static")
    except Exception as e:
        print(f"  모드 전환 실패: {e!r}")
    time.sleep(0.5)
    try:
        lianli.set_colors([RGBColor(255, 0, 0)] * len(lianli.leds))
        print(f"  -> 빨강 적용 (LED {len(lianli.leds)}개)")
    except Exception as e:
        print(f"  -> 실패: {e!r}")

print(f"\n서버 상태: {'정상' if alive() else '죽음'}")
print("\n>>> Razer 신호를 끊은 상태입니다. 무지개가 사라졌는지 확인하세요.")
