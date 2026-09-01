"""채널 하나 안에서 팬 경계를 찾는다.

    python find_segment.py [채널번호] [구간개수]

리안리 허브는 포트 하나에 팬을 여러 개 줄줄이 연결할 수 있다. 그래서
채널 하나가 팬 하나가 아니라 팬 여러 개에 걸쳐 있다. 채널을 통째로 끄면
멀쩡한 팬까지 같이 꺼지므로, 고장난 팬이 차지하는 LED 구간만 찾아야 한다.

지정한 채널을 여러 구간으로 나눠 서로 다른 색을 칠하고, 나머지 채널은
어둡게 죽여서 눈에 잘 띄게 한다.
"""

import sys
import time

from openrgb.utils import RGBColor

import fan

SEGMENT_COLORS = [
    ("빨강", RGBColor(255, 0, 0)),
    ("초록", RGBColor(0, 255, 0)),
    ("파랑", RGBColor(0, 80, 255)),
    ("노랑", RGBColor(255, 230, 0)),
    ("보라", RGBColor(190, 0, 255)),
    ("청록", RGBColor(0, 255, 220)),
]

# 나머지 채널은 완전히 끄지 않는다. 어느 팬이 어느 자리인지 보이도록
# 아주 흐린 회색으로 남겨 둔다.
DIM = RGBColor(12, 12, 14)


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    parts = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    cli = fan.connect("find-segment")
    dev = fan.get_hub(cli)

    # 앞선 실험에서 크기를 건드렸을 수 있으니 원래대로 맞춘다.
    if any(len(z.leds) != fan.LEDS_PER_CHANNEL for z in dev.zones):
        print("채널 크기를 %d개로 되돌리는 중..." % fan.LEDS_PER_CHANNEL)
        for z in dev.zones:
            if len(z.leds) != fan.LEDS_PER_CHANNEL:
                z.resize(fan.LEDS_PER_CHANNEL)
                time.sleep(0.4)
        time.sleep(1.5)
        cli.update()
        dev = cli.devices[dev.id]

    dev = fan.ensure_ready(cli, dev)
    size = len(dev.zones[target].leds)
    step = size // parts

    print("\n채널 %d 를 %d 구간으로 나눈다 (구간당 LED %d개)" % (target, parts, step))
    for i in range(parts):
        lo = i * step
        hi = size if i == parts - 1 else (i + 1) * step
        print("  구간 %d: LED %d~%d = %s" % (i, lo, hi - 1, SEGMENT_COLORS[i][0]))
    print("\n나머지 채널은 흐린 회색. 멈추려면 Ctrl+C\n")

    def paint():
        for z in dev.zones:
            count = len(z.leds)
            if count == 0:
                continue
            if z.id != target:
                z.set_colors([DIM] * count)
                continue
            buf = []
            for i in range(parts):
                lo = i * step
                hi = count if i == parts - 1 else (i + 1) * step
                buf += [SEGMENT_COLORS[i % len(SEGMENT_COLORS)][1]] * (hi - lo)
            z.set_colors(buf[:count])

    while True:
        try:
            paint()
        except Exception:
            while not fan.server_alive():
                time.sleep(2)
            cli = fan.connect("find-segment")
            dev = fan.get_hub(cli)
            continue
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n멈췄어.")
