"""OpenRGB가 실제로 하드웨어를 제어하는지 검증한다.
LED 개수가 이미 확정된 장치(램, 스피커)로 테스트하는 것이 핵심.
이 장치들이 반응하면 OpenRGB는 정상이고, 문제는 팬 배선에 있다."""

import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

cli = OpenRGBClient(address="127.0.0.1", port=6742, name="verify")

# LED 개수가 0이 아닌 장치 = 하드웨어가 스스로 보고한 확실한 장치
targets = [d for d in cli.devices if len(d.leds) > 0 and "Razer" not in d.name and "Lian Li" not in d.name]

if not targets:
    print("[X] 검증에 쓸 장치가 없습니다.")
    raise SystemExit(1)

print("검증 대상:")
for d in targets:
    print(f"  - {d.name} (LED {len(d.leds)}개)")
print()

for d in targets:
    try:
        d.set_mode("direct")
    except Exception as e:
        print(f"  {d.name}: direct 모드 실패 ({e})")
    time.sleep(0.2)

for label, color in [("빨강", RGBColor(255, 0, 0)),
                     ("초록", RGBColor(0, 255, 0)),
                     ("파랑", RGBColor(0, 0, 255)),
                     ("흰색", RGBColor(255, 255, 255))]:
    print(f"  -> 전체 {label}")
    for d in targets:
        try:
            d.set_colors([color] * len(d.leds))
        except Exception as e:
            print(f"     {d.name} 실패: {e}")
    time.sleep(2.5)

print("\n  -> 보라색으로 고정")
for d in targets:
    try:
        d.set_colors([RGBColor(160, 0, 255)] * len(d.leds))
    except Exception:
        pass
print("\n검증 끝.")
