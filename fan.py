"""팬 조명 제어 공통 모듈 (리안리 Uni Hub - SL Infinity 기준).

이후의 모든 이펙트 스크립트는 이 파일을 import해서 쓴다.

알아낸 하드웨어 사실:
- 팬은 리안리 허브에 물려 있다 (Razer 컨트롤러엔 팬이 없다)
- 허브는 8채널, 채널당 최대 96 LED (그 이상은 조용히 잘린다)
- 8채널 = 물리 포트 4개 x 링 2개(안쪽/바깥쪽)
- Direct 모드가 없어 Custom 모드로 LED를 개별 제어한다
- L-Connect가 켜져 있으면 색을 덮어써 무지개가 되므로 반드시 꺼져 있어야 한다
"""

import socket
import time
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# 허브의 채널당 상한. 실측으로 확인했다 - 96까지는 늘어나고 144를 요청하면
# 에러 없이 96에서 잘린다. 60으로 쓰던 때는 각 채널의 앞 60개만 켜고 있었다.
LEDS_PER_CHANNEL = 96
HOST = "127.0.0.1"
PORT = 6742

# 통째로 끌 채널 번호. 채널 하나가 팬 하나가 아니므로 웬만하면 비워 둔다.
DEAD_ZONES = []

# 채널 안에서 일부 구간만 끌 때 쓴다. (채널, 시작, 끝) - 끝은 포함하지 않는다.
#
# 리안리 허브는 포트 하나에 팬을 여러 개 줄줄이 연결한다. 그래서 채널 하나가
# 팬 여러 개에 걸쳐 있고, 채널을 통째로 끄면 멀쩡한 팬까지 같이 꺼진다.
# find_segment.py 로 확인한 결과 채널 1 은 팬 3개의 테두리를 나눠 갖고 있고,
# 불량 팬은 그중 첫 32개(LED 0~31)를 쓴다.
#
# 실측으로 가려낸 것: 이 링은 색에 따라 증상이 다르다.
#   주황(파랑 0)  -> 깜빡임만, 무지개 없음
#   하늘색/흰색   -> 무지개로 튐
# 채널 전체를 한 색으로 통일해도 하늘색이면 튀었으므로, 원인은 배색이
# 아니라 색 자체다. 파랑 성분이 든 데이터를 제대로 못 받는다.
# 우리 배색이 흰색-하늘색 계열이라 이 링은 쓸 수가 없어 꺼둔다.
DEAD_RANGES = [(1, 0, 32)]


def server_alive(timeout=3):
    """OpenRGB 서버가 살아있는지 소켓으로 직접 확인한다."""
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except Exception:
        return False


def connect(name="fan-control", retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            return OpenRGBClient(address=HOST, port=PORT, name=name)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2)
    raise ConnectionError(
        f"OpenRGB 연결 실패: {last_err}\n"
        "OpenRGB가 --server 옵션으로 실행 중인지 확인하세요."
    )


def get_hub(cli):
    """팬이 물려 있는 리안리 허브를 찾는다."""
    for dev in cli.devices:
        if "Lian Li" in dev.name:
            return dev
    raise LookupError("리안리 허브를 찾지 못했습니다. 장치 감지가 끝났는지 확인하세요.")


def ensure_ready(cli, dev, leds=LEDS_PER_CHANNEL):
    """채널 크기를 맞추고 Custom 모드로 전환한다.

    Custom 모드여야 LED 하나하나에 색을 지정할 수 있다.
    다른 모드는 허브가 자체 효과를 재생하느라 우리 색을 무시한다.
    """
    if any(len(z.leds) != leds for z in dev.zones):
        for zone in dev.zones:
            zone.resize(leds)
            time.sleep(0.4)
            if not server_alive():
                raise RuntimeError("채널 크기 변경 중 OpenRGB가 죽었습니다.")
        time.sleep(1.5)
        cli.update()
        dev = cli.devices[dev.id]

    want = "custom" if any(m.name.lower() == "custom" for m in dev.modes) else "static"
    target = next((m for m in dev.modes if m.name.lower() == want), None)

    # 장치에 색과 별개인 밝기 값이 있다. 기본이 37/50이라 색을 255로 줘도
    # 그 위에서 74%로 깎였다. 최대로 올려야 L-Connect만큼 밝아진다.
    if target is not None and getattr(target, "brightness_max", None):
        target.brightness = target.brightness_max
        dev.set_mode(target)
    else:
        dev.set_mode(want)

    time.sleep(0.4)
    return dev


def setup(name="fan-control"):
    """연결부터 준비까지 한 번에. 대부분의 스크립트는 이것만 부르면 된다."""
    if not server_alive():
        raise ConnectionError("OpenRGB 서버가 응답하지 않습니다.")
    cli = connect(name)
    dev = get_hub(cli)
    dev = ensure_ready(cli, dev)
    return cli, dev


def fill(dev, color):
    """전체 LED를 한 가지 색으로 채운다."""
    dev.set_colors([color] * len(dev.leds))


def off(dev):
    """모든 LED를 끈다."""
    fill(dev, RGBColor(0, 0, 0))


def zone_range(z):
    """채널 z가 차지하는 LED 인덱스 범위."""
    return range(z * LEDS_PER_CHANNEL, (z + 1) * LEDS_PER_CHANNEL)


def mute_dead(colors):
    """불량 팬이 차지하는 LED를 검게 만든다.

    DEAD_ZONES는 채널 통째로, DEAD_RANGES는 채널 안의 일부 구간만 끈다.
    포트 하나에 팬이 여러 개 물려 있으므로 보통은 DEAD_RANGES를 쓴다.
    """
    if not DEAD_ZONES and not DEAD_RANGES:
        return colors
    black = RGBColor(0, 0, 0)
    total = len(colors)

    for z in DEAD_ZONES:
        for i in zone_range(z):
            if i < total:
                colors[i] = black

    for z, lo, hi in DEAD_RANGES:
        base = z * LEDS_PER_CHANNEL
        for i in range(base + lo, min(base + hi, total)):
            colors[i] = black

    return colors


def dead_leds():
    """소등 대상 LED 인덱스 집합. 대시보드 표시용."""
    out = set()
    for z in DEAD_ZONES:
        out.update(zone_range(z))
    for z, lo, hi in DEAD_RANGES:
        base = z * LEDS_PER_CHANNEL
        out.update(range(base + lo, base + hi))
    return out

# ---------------------------------------------------------------- 자리 나누기
#
# 허브는 포트가 4개고, 포트 하나에 팬을 최대 3개까지 줄줄이 연결한다.
# 채널 번호로는 포트 하나가 두 칸을 쓴다 - 짝수가 안쪽 링, 홀수가 테두리.
#
#   포트 0 -> 채널 0(안), 1(밖)
#   포트 1 -> 채널 2(안), 3(밖)   ...
#
# 채널 하나(96개)를 32개씩 셋으로 나눈 것이 각각 한 팬이다.
# 그래서 "자리"는 (포트, 줄에서 몇 번째) 두 숫자로 정해진다.
PORTS = 4
FANS_PER_PORT = 3
LEDS_PER_FAN = 32


def slot_leds(port, daisy, ring=None):
    """자리 하나가 차지하는 LED 번호들.

    ring=None 이면 안쪽·바깥쪽 둘 다, 0 이면 안쪽만, 1 이면 바깥쪽만.
    """
    out = []
    rings = (0, 1) if ring is None else (ring,)
    for r in rings:
        base = (port * 2 + r) * LEDS_PER_CHANNEL + daisy * LEDS_PER_FAN
        out += list(range(base, base + LEDS_PER_FAN))
    return out


def slot_id(port, daisy):
    return f"f{port}{daisy}"


def parse_slot(sid):
    """f01 -> (0, 1). 모양이 아니면 None."""
    if not (isinstance(sid, str) and len(sid) == 3 and sid[0] == "f"):
        return None
    try:
        port, daisy = int(sid[1]), int(sid[2])
    except ValueError:
        return None
    if 0 <= port < PORTS and 0 <= daisy < FANS_PER_PORT:
        return port, daisy
    return None


def all_slots():
    return [slot_id(p, d) for p in range(PORTS) for d in range(FANS_PER_PORT)]
