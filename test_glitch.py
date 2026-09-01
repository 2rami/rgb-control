"""불량 팬 테두리가 무지개로 튀는 원인을 가려낸다.

    python test_glitch.py

가설 두 가지를 한 번에 시험한다.
  A. 전류 - 흰색은 R,G,B를 다 켜서 전력을 가장 많이 먹는다.
     접촉이 나쁘면 전압이 주저앉아 컨트롤러가 헛돈다.
  B. 비트 - 흰색은 비트가 전부 1이라, 신호가 하나만 깨져도
     한 채널이 통째로 빠지면서 색이 확 변한다.

불량 팬의 테두리(채널1의 LED 0~31)를 8개씩 4구간으로 쪼개고
조건이 다른 색을 넣는다. 어느 구간이 튀는지 보면 원인이 갈린다.

  흰색 풀만 튄다        -> 전류 문제 (A)
  흰색 둘 다 튄다       -> 비트 문제 (B)
  전부 튄다             -> 색과 무관, 순수 접촉 불량
"""

import time

from openrgb.utils import RGBColor

import fan

# 불량 팬이 차지하는 구간
BAD_ZONE = 1
BAD_LO = 0
BAD_HI = 32

# 1차 시험에서 흰색/파랑/하늘색이 전부 튀었다. 유일하게 안 튀었던 게
# 주황이었으므로, 이번엔 파랑 성분을 0부터 조금씩 올려가며 어디서
# 무너지는지 본다. 파랑이 범인이면 4번만 튄다.
TESTS = [
    ("빨강 (파랑 0)", RGBColor(255, 0, 0)),
    ("주황 (파랑 0)", RGBColor(255, 90, 0)),
    ("노랑 (파랑 0)", RGBColor(255, 200, 0)),
    ("연분홍 (파랑 조금)", RGBColor(255, 120, 90)),
]

# 비교 기준. 파랑을 뺀 어두운 색으로 깔아서 기준선도 오염되지 않게 한다.
BASE = RGBColor(70, 40, 0)


def main():
    cli, dev = fan.setup("test-glitch")
    span = BAD_HI - BAD_LO
    step = span // len(TESTS)

    print("불량 팬 테두리(채널 %d, LED %d~%d)를 %d구간으로 나눈다.\n"
          % (BAD_ZONE, BAD_LO, BAD_HI - 1, len(TESTS)))
    for i, (label, _) in enumerate(TESTS):
        lo = BAD_LO + i * step
        hi = BAD_HI if i == len(TESTS) - 1 else BAD_LO + (i + 1) * step
        print("  구간 %d: LED %d~%d = %s" % (i + 1, lo, hi - 1, label))
    print("\n어느 구간이 무지개로 튀는지 봐줘. 멈추려면 Ctrl+C\n")

    def paint():
        for z in dev.zones:
            count = len(z.leds)
            if count == 0:
                continue
            buf = [BASE] * count
            if z.id == BAD_ZONE:
                for i, (_, color) in enumerate(TESTS):
                    lo = BAD_LO + i * step
                    hi = BAD_HI if i == len(TESTS) - 1 else BAD_LO + (i + 1) * step
                    for j in range(lo, min(hi, count)):
                        buf[j] = color
            z.set_colors(buf)

    while True:
        try:
            paint()
        except Exception:
            while not fan.server_alive():
                time.sleep(2)
            cli, dev = fan.setup("test-glitch")
            continue
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n멈췄어.")
