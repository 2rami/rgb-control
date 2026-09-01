"""채널1을 0개로 줄인 상태에서 나머지 채널에 색을 넣고 붙잡는다.

채널 크기가 더 이상 균일하지 않으므로, 장치 전체에 한 번에 칠하는 대신
채널마다 따로 칠한다. 그래야 인덱스 계산이 틀어지지 않는다.
"""

import time

from openrgb.utils import RGBColor

import fan

PALETTE = [
    RGBColor(255, 255, 255),   # 0
    RGBColor(0, 0, 0),         # 1 (0개라 무시됨)
    RGBColor(170, 225, 255),   # 2
    RGBColor(120, 175, 229),   # 3
    RGBColor(100, 190, 255),   # 4
    RGBColor(72, 148, 229),    # 5
    RGBColor(30, 120, 255),    # 6
    RGBColor(21, 93, 229),     # 7
]


def paint(dev):
    for z in dev.zones:
        count = len(z.leds)
        if count == 0:
            continue
        z.set_colors([PALETTE[z.id % len(PALETTE)]] * count)


def main():
    cli = fan.connect("hold-test")
    dev = fan.get_hub(cli)
    print("채널별 LED:", [len(z.leds) for z in dev.zones])
    print("채널1은 0개 - 허브가 그 링을 아예 안 건드린다.")
    print("색 유지 중. 멈추려면 Ctrl+C")

    while True:
        try:
            paint(dev)
        except Exception:
            while not fan.server_alive():
                time.sleep(2)
            cli = fan.connect("hold-test")
            dev = fan.get_hub(cli)
            continue
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n멈췄어.")
