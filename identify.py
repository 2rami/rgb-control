"""8개 채널에 서로 다른 색을 칠해서, 어느 채널이 어느 팬인지 눈으로 찾는다.

    python identify.py

허브의 8채널은 물리 포트 4개 x 링 2개(안쪽/바깥쪽)다. 팬 하나가 보통
채널 2개(안/바깥)를 차지하므로, 불량 팬을 찾으면 채널 번호도 두 개 나온다.

찾은 번호는 fan.py의 DEAD_ZONES에 적으면 된다.
"""

import sys
import time

from openrgb.utils import RGBColor

import fan

# 서로 헷갈리지 않게 최대한 멀리 떨어뜨린 색들.
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
    # 인자로 받은 채널은 이번 실행에서만 추가로 꺼둔다 (fan.py는 안 건드림).
    extra = set()
    if len(sys.argv) > 1:
        extra = {int(x) for x in sys.argv[1].replace(" ", "").split(",") if x}

    cli, dev = fan.setup("identify")
    n = len(dev.leds)
    zones = len(dev.zones)
    dead = set(fan.DEAD_ZONES) | extra
    print(f"연결됨: {dev.name} (LED {n}개 / 채널 {zones}개)\n")

    black = RGBColor(0, 0, 0)
    colors = [black] * n
    for z in range(zones):
        name, color = PALETTE[z % len(PALETTE)]
        is_dead = z in dead
        for i in fan.zone_range(z):
            if i < n:
                colors[i] = black if is_dead else color
        mark = "   <- 꺼둠" if is_dead else ""
        print(f"  채널 {z} = {name}{mark}")

    print("\n색이 유지되도록 계속 다시 쏘는 중. 멈추려면 Ctrl+C")
    print("고장난 팬 자리가 '무슨 색이어야 할 자리'인지 확인해줘.\n")

    held = 0
    while True:
        try:
            # 불량 팬이 제 색을 덮어쓰지 못하도록 계속 재적용한다.
            dev.set_colors(colors)
            held += 1
        except Exception:
            print("\n연결이 끊겼어. 다시 붙는 중...")
            while not fan.server_alive():
                time.sleep(2)
            cli, dev = fan.setup("identify")
            print("다시 연결됐어.\n")
            continue
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n멈췄어.")
