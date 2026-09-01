"""OpenRGB에 연결해서 인식된 장치와 LED 구성을 확인한다.
본격적인 이펙트를 짜기 전에, 어떤 장치가 몇 개의 LED를 갖는지 알아야 한다."""

from openrgb import OpenRGBClient
from openrgb.utils import DeviceType

try:
    cli = OpenRGBClient(address="127.0.0.1", port=6742, name="rgb-check")
except Exception as e:
    print(f"[X] OpenRGB SDK 서버에 연결 실패: {e}")
    print("\n확인할 것:")
    print("  1. OpenRGB가 실행 중인가?")
    print("  2. OpenRGB > Settings(설정) > 'Start Server' 체크됐나?")
    print("  3. 포트가 6742인가?")
    raise SystemExit(1)

print(f"[O] 연결 성공 — 장치 {len(cli.devices)}개 발견\n")
print("=" * 64)

for i, dev in enumerate(cli.devices):
    print(f"\n[{i}] {dev.name}")
    print(f"    종류      : {dev.type.name}")
    print(f"    전체 LED  : {len(dev.leds)}개")

    mode_names = [m.name for m in dev.modes]
    print(f"    사용 모드 : {', '.join(mode_names)}")
    has_direct = any(m.name.lower() == "direct" for m in dev.modes)
    print(f"    Direct 지원: {'예 (실시간 제어 가능)' if has_direct else '아니오'}")

    # 존 = 물리적으로 분리된 LED 묶음. 팬 하나가 보통 존 하나에 대응한다.
    for z in dev.zones:
        print(f"      - 존 '{z.name}': LED {len(z.leds)}개")

print("\n" + "=" * 64)
print("\n다음 단계: 위 목록에서 팬이 연결된 장치의 번호를 확인하세요.")
