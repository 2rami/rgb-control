"""Razer ARGB 컨트롤러의 6채널에 서로 다른 색을 쏴서 무엇이 물려 있는지 찾는다.

    python probe_razer.py            60초 동안 켜둔다
    python probe_razer.py 20         20초만

대시보드가 초당 한 번 이 컨트롤러를 덮어쓰므로, 시험하는 동안에는 동기화를
꺼야 한다. 이 스크립트가 알아서 껐다가 끝날 때 되돌린다.
"""

import json
import sys
import time
import urllib.request

import fan
from openrgb.utils import RGBColor

API = "http://127.0.0.1:5000/api/effect"

# 서로 확실히 구분되는 색만 골랐다. 비슷한 색을 쓰면 어느 채널인지 못 가린다.
#
# ★빨강은 일부러 뺐다. 제어를 못 받는 장치는 기본색으로 빨강을 띄우는 일이
# 많다. 팔레트에 빨강이 있으면 "원래 빨갛던 것"과 "우리가 빨갛게 만든 것"을
# 구분할 수 없다. 실제로 그것 때문에 글카 채널을 한 번 잘못 짚었다.
PALETTE = [
    ("초록", RGBColor(0, 255, 0)),
    ("파랑", RGBColor(0, 0, 255)),
    ("노랑", RGBColor(255, 255, 0)),
    ("청록", RGBColor(0, 255, 255)),
    ("보라", RGBColor(255, 0, 255)),
    ("하양", RGBColor(255, 255, 255)),
]


def set_sync(on):
    """대시보드 동기화를 껐다 켠다. 대시보드가 없으면 조용히 넘어간다."""
    try:
        req = urllib.request.Request(
            API, data=json.dumps({"sync_all": on}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception:
        return False


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60

    had_dashboard = set_sync(False)
    if had_dashboard:
        print("대시보드 동기화 잠깐 끔\n")
        time.sleep(1.5)   # 마지막 덮어쓰기가 지나가길 기다린다

    cli = fan.connect("probe-razer")
    dev = next(d for d in cli.devices if d.type.name == "LEDSTRIP")
    dev.set_mode("direct")

    colors = []
    for i, z in enumerate(dev.zones):
        name, c = PALETTE[i % len(PALETTE)]
        colors += [c] * len(z.leds)
        print(f"  채널 {i + 1} = {name}")
    dev.set_colors(colors)

    print(f"\n{seconds:.0f}초 동안 켜둔다. 글카 LED가 무슨 색인지 봐줘.")
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    finally:
        if had_dashboard:
            set_sync(True)
            print("\n동기화 되돌림")


if __name__ == "__main__":
    main()
