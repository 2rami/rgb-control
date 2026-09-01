"""채널-링 대응을 눈으로 확인하기 위한 일회성 도구.

    python map_rings.py

fan.py의 DEAD_ZONES를 무시하고 8채널 전부에 서로 다른 색을 칠한 뒤
그대로 붙잡고 있는다. 고장난 팬의 안쪽/바깥쪽이 각각 무슨 색으로
보이는지 확인하면, 그 팬이 실제로 어느 채널에 물려 있는지 알 수 있다.

"짝수=안쪽, 홀수=바깥쪽" 가정이 맞는지 검증하는 게 목적이다.
포트 하나에 팬이 여러 개 물려 있으면 이 가정이 깨진다.
"""

import time

from openrgb.utils import RGBColor

import fan

PALETTE = [
    ("빨강", RGBColor(255, 0, 0)),
    ("주황", RGBColor(255, 90, 0)),
    ("노랑", RGBColor(255, 230, 0)),
    ("초록", RGBColor(0, 255, 0)),
    ("청록", RGBColor(0, 255, 220)),
    ("파랑", RGBColor(0, 60, 255)),
    ("보라", RGBColor(170, 0, 255)),
    ("분홍", RGBColor(255, 0, 140)),
]


def main():
    cli, dev = fan.setup("map-rings")
    n = len(dev.leds)
    zones = len(dev.zones)

    colors = [RGBColor(0, 0, 0)] * n
    for z in range(zones):
        _, color = PALETTE[z % len(PALETTE)]
        for i in fan.zone_range(z):
            if i < n:
                colors[i] = color

    print(f"연결됨: {dev.name} (LED {n} / 채널 {zones})")
    print("소등 없이 8채널 전부 칠한다.\n")
    for z in range(zones):
        print(f"  채널 {z} = {PALETTE[z % len(PALETTE)][0]}")
    print("\n색을 계속 붙잡는 중. 멈추려면 Ctrl+C")

    while True:
        try:
            dev.set_colors(colors)
        except Exception:
            while not fan.server_alive():
                time.sleep(2)
            cli, dev = fan.setup("map-rings")
            continue
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n멈췄어.")
