"""제어권을 잡았는지 확인하는 기본 테스트.
전체 색을 순서대로 바꿔본 뒤, 채널별로 다른 색을 넣는다."""

import time
import fan
from openrgb.utils import RGBColor

cli, dev = fan.setup("basic-test")
print(f"[O] {dev.name}")
print(f"    채널 {len(dev.zones)}개 / 전체 LED {len(dev.leds)}개\n")

steps = [
    ("전체 빨강", RGBColor(255, 0, 0)),
    ("전체 초록", RGBColor(0, 255, 0)),
    ("전체 파랑", RGBColor(0, 0, 255)),
    ("전체 흰색", RGBColor(255, 255, 255)),
]

for label, color in steps:
    print(f"  -> {label}")
    fan.fill(dev, color)
    time.sleep(2.5)

print("  -> 전체 끄기")
fan.off(dev)
time.sleep(2)

CHANNEL_COLORS = [
    ("빨강", RGBColor(255, 0, 0)),
    ("초록", RGBColor(0, 255, 0)),
    ("파랑", RGBColor(0, 0, 255)),
    ("노랑", RGBColor(255, 255, 0)),
    ("자홍", RGBColor(255, 0, 255)),
    ("하늘", RGBColor(0, 255, 255)),
]

print("\n  -> 채널별 색상 적용")
colors = []
for i, zone in enumerate(dev.zones):
    name, color = CHANNEL_COLORS[i % len(CHANNEL_COLORS)]
    colors.extend([color] * len(zone.leds))
    print(f"     채널 {i+1} = {name}")

dev.set_colors(colors)
print("\n테스트 끝. 이 색이 유지됩니다.")
