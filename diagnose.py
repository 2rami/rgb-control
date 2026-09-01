"""set_colors가 왜 실패하는지 정확한 예외를 확인한다."""

import traceback
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

print("=== 연결 시도 ===")
cli = OpenRGBClient(address="127.0.0.1", port=6742, name="diag")
print(f"연결됨. 장치 {len(cli.devices)}개")

try:
    print(f"프로토콜 버전: {cli.comms.version}")
except Exception as e:
    print(f"프로토콜 버전 조회 불가: {e!r}")

dev = None
for d in cli.devices:
    if len(d.leds) > 0:
        dev = d
        break

if dev is None:
    print("[X] LED가 있는 장치 없음")
    raise SystemExit(1)

print(f"\n=== 테스트 대상: {dev.name} (LED {len(dev.leds)}개) ===")
print(f"현재 모드: {dev.modes[dev.active_mode].name}")

print("\n--- set_mode('direct') ---")
try:
    dev.set_mode("direct")
    print("성공")
except Exception:
    traceback.print_exc()

print("\n--- set_colors ---")
try:
    dev.set_colors([RGBColor(255, 0, 0)] * len(dev.leds))
    print("성공")
except Exception:
    traceback.print_exc()

print("\n--- 단일 LED 직접 지정 ---")
try:
    dev.leds[0].set_color(RGBColor(0, 255, 0))
    print("성공")
except Exception:
    traceback.print_exc()

print("\n--- 장치 전체 색 지정 (set_color) ---")
try:
    dev.set_color(RGBColor(0, 0, 255))
    print("성공")
except Exception:
    traceback.print_exc()
