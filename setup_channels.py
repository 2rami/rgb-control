"""Razer ARGB 컨트롤러의 채널 크기를 설정하고, 채널별로 다른 색을 쏘아
어느 팬이 어느 채널에 연결됐는지 눈으로 찾아내는 스크립트."""

import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

LEDS_PER_CHANNEL = 20  # 실제보다 넉넉하게. 남는 신호는 무시되므로 안전하다.

# 채널 번호 -> (색 이름, 색). 눈으로 구분하기 쉬운 원색 위주로 고름.
CHANNEL_COLORS = [
    ("빨강",   RGBColor(255, 0, 0)),
    ("초록",   RGBColor(0, 255, 0)),
    ("파랑",   RGBColor(0, 0, 255)),
    ("노랑",   RGBColor(255, 255, 0)),
    ("자홍",   RGBColor(255, 0, 255)),
    ("하늘",   RGBColor(0, 255, 255)),
]

cli = OpenRGBClient(address="127.0.0.1", port=6742, name="rgb-setup")

razer = None
for dev in cli.devices:
    if "Razer" in dev.name and "Addressable" in dev.name:
        razer = dev
        break

if razer is None:
    print("[X] Razer ARGB 컨트롤러를 찾지 못했습니다.")
    raise SystemExit(1)

print(f"[O] 대상 장치: {razer.name}")
print(f"    현재 채널 {len(razer.zones)}개, 전체 LED {len(razer.leds)}개\n")

print(f"각 채널을 LED {LEDS_PER_CHANNEL}개로 설정합니다...")
for i, zone in enumerate(razer.zones):
    try:
        zone.resize(LEDS_PER_CHANNEL)
        print(f"  채널 {i+1}: 설정 완료")
    except Exception as e:
        print(f"  채널 {i+1}: 실패 - {e}")
    time.sleep(0.3)

# 크기를 바꿨으니 장치 정보를 다시 읽어온다.
time.sleep(1)
cli.update()
razer = cli.devices[razer.id]
print(f"\n[O] 재확인: 전체 LED {len(razer.leds)}개\n")

razer.set_mode("direct")
time.sleep(0.5)

print("채널별 색상을 적용합니다. 케이스를 보세요:\n")
colors = []
for i, zone in enumerate(razer.zones):
    name, color = CHANNEL_COLORS[i % len(CHANNEL_COLORS)]
    colors.extend([color] * len(zone.leds))
    print(f"  채널 {i+1} -> {name}")

razer.set_colors(colors)

print("\n" + "=" * 56)
print("이제 케이스 안을 보고, 각 팬이 무슨 색인지 알려주세요.")
print("색이 안 들어온 팬이 있다면 그것도 알려주세요.")
print("=" * 56)
