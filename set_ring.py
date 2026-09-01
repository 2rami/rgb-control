"""채널 하나만 원하는 색으로 통째로 칠하고, 나머지는 map_rings와 동일하게 둔다.

    python set_ring.py 9bd7ff        채널1을 하늘색으로
    python set_ring.py ff5a00 3      채널3을 주황으로

색이 원인인지 '여러 색으로 쪼갠 것'이 원인인지 가리기 위한 도구다.
map_rings.py와 나머지 조건을 똑같이 맞춰야 비교가 성립한다.
"""

import sys
import time

from openrgb.utils import RGBColor

import fan

# map_rings.py와 같은 배색. 이걸 유지해야 조건이 같다.
PALETTE = [
    RGBColor(255, 0, 0),
    RGBColor(255, 90, 0),
    RGBColor(255, 230, 0),
    RGBColor(0, 255, 0),
    RGBColor(0, 255, 220),
    RGBColor(0, 60, 255),
    RGBColor(170, 0, 255),
    RGBColor(255, 0, 140),
]


def parse_hex(text):
    text = text.lstrip("#")
    return RGBColor(int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def main():
    if len(sys.argv) < 2:
        print("사용법: python set_ring.py <색상6자리> [채널번호]")
        return 1

    color = parse_hex(sys.argv[1])
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    cli, dev = fan.setup("set-ring")
    print("채널 %d 를 #%02x%02x%02x 하나로 통째로 칠한다."
          % (target, color.red, color.green, color.blue))
    print("나머지 채널은 map_rings 와 같은 배색 그대로.")
    print("멈추려면 Ctrl+C\n")

    def paint():
        for z in dev.zones:
            count = len(z.leds)
            if count == 0:
                continue
            c = color if z.id == target else PALETTE[z.id % len(PALETTE)]
            z.set_colors([c] * count)

    while True:
        try:
            paint()
        except Exception:
            while not fan.server_alive():
                time.sleep(2)
            cli, dev = fan.setup("set-ring")
            continue
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n멈췄어.")
