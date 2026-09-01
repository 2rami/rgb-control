"""L-Connect 없는 깨끗한 상태에서의 첫 제어 테스트."""

import time
import fan
from openrgb.utils import RGBColor

cli = fan.connect("first-control")
print(f"연결됨 - 장치 {len(cli.devices)}개")
for d in cli.devices:
    print(f"  - {d.name} (LED {len(d.leds)}개)")

hub = fan.get_hub(cli)
print(f"\n대상: {hub.name}")
print(f"  채널 {len(hub.zones)}개 / LED {len(hub.leds)}개")

hub = fan.ensure_ready(cli, hub)
print(f"  준비 완료 - LED {len(hub.leds)}개, 모드 '{hub.modes[hub.active_mode].name}'\n")

for label, color in [("빨강", RGBColor(255, 0, 0)),
                     ("초록", RGBColor(0, 255, 0)),
                     ("파랑", RGBColor(0, 0, 255))]:
    print(f"  -> {label} (5초)")
    fan.fill(hub, color)
    time.sleep(5)

print("\n  -> 보라색으로 고정")
fan.fill(hub, RGBColor(160, 0, 255))

print(f"\n서버 상태: {'정상' if fan.server_alive() else '죽음'}")
print("이 색이 계속 유지되는지, 무지개로 돌아가지 않는지 지켜보세요.")
