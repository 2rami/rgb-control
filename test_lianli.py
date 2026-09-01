"""리안리 Uni Hub에 실제로 팬이 물려 있는지 확인한다.
이 허브는 Direct 모드가 없어서 Custom 또는 Static 모드를 써야 한다."""

import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

LEDS_PER_CHANNEL = 20

cli = OpenRGBClient(address="127.0.0.1", port=6742, name="lianli-test")

hub = None
for dev in cli.devices:
    if "Lian Li" in dev.name:
        hub = dev
        break

if hub is None:
    print("[X] Lian Li Uni Hub를 찾지 못했습니다.")
    raise SystemExit(1)

print(f"[O] 대상: {hub.name}")
print(f"    채널 {len(hub.zones)}개, 전체 LED {len(hub.leds)}개")
print(f"    지원 모드: {', '.join(m.name for m in hub.modes)}\n")

print(f"채널을 LED {LEDS_PER_CHANNEL}개로 설정합니다...")
for i, zone in enumerate(hub.zones):
    try:
        zone.resize(LEDS_PER_CHANNEL)
        print(f"  채널 {i+1}: 완료")
    except Exception as e:
        print(f"  채널 {i+1}: 실패 - {e}")
    time.sleep(0.3)

time.sleep(1)
cli.update()
hub = cli.devices[hub.id]
print(f"\n[O] 재확인: 전체 LED {len(hub.leds)}개\n")

# Custom 모드가 LED 개별 제어를 지원하는지 확인
mode_names = [m.name.lower() for m in hub.modes]
target_mode = "custom" if "custom" in mode_names else "static"
print(f"모드를 '{target_mode}'로 전환합니다.")
try:
    hub.set_mode(target_mode)
    time.sleep(0.5)
except Exception as e:
    print(f"  모드 전환 실패: {e}")

if len(hub.leds) == 0:
    print("[X] LED가 0개입니다. 채널 크기 설정이 반영되지 않았습니다.")
    raise SystemExit(1)

for label, color in [("전체 빨강", RGBColor(255, 0, 0)),
                     ("전체 초록", RGBColor(0, 255, 0)),
                     ("전체 파랑", RGBColor(0, 0, 255))]:
    print(f"  -> {label}")
    try:
        hub.set_colors([color] * len(hub.leds))
    except Exception as e:
        print(f"     실패: {e}")
    time.sleep(2.5)

print("\n  -> 채널별 색상")
CH = [RGBColor(255,0,0), RGBColor(0,255,0), RGBColor(0,0,255), RGBColor(255,255,0),
      RGBColor(255,0,255), RGBColor(0,255,255), RGBColor(255,128,0), RGBColor(255,255,255)]
names = ["빨강","초록","파랑","노랑","자홍","하늘","주황","흰색"]
colors = []
for i, zone in enumerate(hub.zones):
    colors.extend([CH[i % len(CH)]] * len(zone.leds))
    print(f"     채널 {i+1} = {names[i % len(names)]}")
hub.set_colors(colors)
print("\n테스트 끝. 이 색이 유지됩니다.")
