"""팬 조명 효과 모음.

    python effects.py wave              무지개 물결 (팬을 따라 흐름)
    python effects.py rainbow           전체가 같이 색상 순환
    python effects.py breathe a000ff    숨쉬기
    python effects.py static ff0000     한 색으로 고정
    python effects.py soft               은은하게 아주 천천히 색이 바뀜
    python effects.py ice                흰색-하늘색-파랑 고정 배치
    python effects.py depth             안쪽 링과 바깥 테두리를 근사한 색으로
    python effects.py screen            화면 색을 따라감 (월페이퍼 엔진 동기화)
    python effects.py pulse             소리 크기에 맞춰 아이스 배치가 출렁임
    python effects.py vu                소리 크기만큼 차오르는 레벨 미터
    python effects.py spectrum          저음=빨강 / 고음=파랑, 밝기는 소리 크기

속도를 바꾸려면 뒤에 숫자를 붙인다:
    python effects.py wave 2

모든 효과는 초당 20번 색을 다시 쏜다. 그래서 불량 팬이 무지개로 튀어도
0.05초 안에 덮어써진다 — keep_color.py를 따로 돌릴 필요가 없다.
"""

import colorsys
import math
import sys
import time

from openrgb.utils import RGBColor

import fan

# 480개 LED를 매 프레임 전송하므로, 이보다 올리면 허브가 밀린다.
FPS = 20
DELAY = 1.0 / FPS


def hsv(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return RGBColor(int(r * 255), int(g * 255), int(b * 255))


def parse_hex(text):
    text = text.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"색은 ff0000 같은 6자리여야 해: {text!r}")
    r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
    return RGBColor(r, g, b)


def scaled(color, level):
    return RGBColor(int(color.red * level),
                    int(color.green * level),
                    int(color.blue * level))


def wave(n, speed):
    """무지개 한 바퀴가 LED 줄을 따라 흘러간다."""
    step = 0.005 * speed
    t = 0.0
    while True:
        yield [hsv(t + (i / n) * 2.0) for i in range(n)]
        t += step


def rainbow(n, speed):
    """전체가 같은 색으로 천천히 순환한다."""
    step = 0.003 * speed
    t = 0.0
    while True:
        yield [hsv(t)] * n
        t += step


def soft(n, speed):
    """색이 아주 천천히, 은은하게 바뀐다.

    rainbow와 같은 색상 순환이지만 채도 0.5 / 밝기 0.7로 눌러서 원색의
    쨍한 느낌을 없앴고, 도는 속도도 rainbow의 1/4이다. 한 바퀴에 몇 분 걸려서
    쳐다보고 있으면 안 변하는 것 같은데 나중에 보면 다른 색이 되어 있다.
    """
    step = 0.0008 * speed
    t = 0.0
    while True:
        yield [hsv(t, 0.5, 0.7)] * n
        t += step


def breathe(n, speed, color):
    """한 색이 밝아졌다 어두워진다. 완전히 꺼지진 않게 0.12를 바닥으로 둔다."""
    step = 0.04 * speed
    t = 0.0
    while True:
        level = 0.12 + 0.88 * (math.sin(t) + 1) / 2
        yield [scaled(color, level)] * n
        t += step


def static(n, color):
    while True:
        yield [color] * n


ICE_STOPS = [
    (255, 255, 255),   # 흰색
    (205, 238, 255),   # 아주 옅은 하늘
    (155, 215, 255),   # 하늘색
    (95, 175, 255),    # 밝은 파랑
]


def _ramp(stops, t):
    """색 목록 사이를 t(0~1) 위치로 부드럽게 잇는다."""
    if t <= 0:
        return RGBColor(*stops[0])
    if t >= 1:
        return RGBColor(*stops[-1])
    span = len(stops) - 1
    i = int(t * span)
    local = t * span - i
    a, b = stops[i], stops[i + 1]
    return RGBColor(*(int(a[k] + (b[k] - a[k]) * local) for k in range(3)))


def ice_colors(n):
    """ice 배치를 리스트 하나로 만들어 돌려준다.

    움직이지 않는 배치라 매 프레임 다시 계산할 이유가 없다. 소리 효과가
    이 배치를 바탕색으로 쓰기 때문에 제너레이터에서 떼어냈다.
    """
    zones = max(1, n // fan.LEDS_PER_CHANNEL)
    total_fans = max(1, (zones + 1) // 2)

    # 링 하나를 꺼둔 팬이 흰색(가장 밝은 끝)을 맡으면, 반쪽만 남은 주제에
    # 제일 밝아서 혼자 튄다. 다른 팬은 안쪽 흰색과 테두리 색이 섞여 보이는데
    # 그 팬만 흰 링 하나로 남기 때문이다.
    # 성한 팬들에게 밝은 쪽을 먼저 주고, 반쪽 팬은 가장 어두운 끝으로 민다.
    muted = set(fan.DEAD_ZONES) | {z for z, _, _ in fan.DEAD_RANGES}
    dead_fans = {z // 2 for z in muted}
    order = [f for f in range(total_fans) if f not in dead_fans]
    order += [f for f in range(total_fans) if f in dead_fans]
    slot = {f: i for i, f in enumerate(order)}

    colors = [RGBColor(0, 0, 0)] * n
    for z in range(zones):
        fan_idx = z // 2
        c = _ramp(ICE_STOPS, slot[fan_idx] / max(1, total_fans - 1))
        if z % 2 == 1:
            # 바깥 테두리는 살짝 눌러서 안쪽이 더 도드라지게.
            # 세 채널을 같은 비율로 깎아야 한다. 예전엔 파랑만 덜 깎아서
            # 어두워질수록 색이 파랑 쪽으로 밀렸다.
            c = RGBColor(int(c.red * 0.8), int(c.green * 0.8), int(c.blue * 0.8))
        for i in fan.zone_range(z):
            if i < n:
                colors[i] = c
    return colors


def ice(n, speed):
    """흰색에서 하늘색을 거쳐 파랑으로 번지는 고정 배치.

    한쪽 끝은 희고 반대로 갈수록 파래져서, 단색 하나보다 계열감이 살아난다.
    안쪽 링은 조금 밝게 둬서 테두리와 층이 지게 했다.
    """
    colors = ice_colors(n)
    while True:
        yield list(colors)


def depth(n, speed):
    """안쪽 링과 바깥 테두리를 비슷하지만 살짝 다른 색으로 칠한다.

    채널 0이 안쪽, 1이 바깥쪽인 걸 실측으로 확인했으므로
    짝수 채널 = 안쪽 링, 홀수 채널 = 바깥 테두리로 본다.
    두 링을 색상환에서 조금 떼어놓으면 평면이 아니라 깊이가 있어 보인다.
    """
    step = 0.004 * speed
    zones = max(1, n // fan.LEDS_PER_CHANNEL)
    t = 0.0
    while True:
        colors = [RGBColor(0, 0, 0)] * n
        for z in range(zones):
            # 팬 하나가 채널 두 개(안/바깥)를 쓰므로 z//2가 팬 번호가 된다.
            hue = t + (z // 2) * 0.07
            if z % 2 == 0:
                c = hsv(hue, 1.0, 1.0)          # 안쪽: 진하고 선명하게
            else:
                c = hsv(hue + 0.055, 0.7, 0.85)  # 바깥: 근사한 색조로 살짝 연하게
            for i in fan.zone_range(z):
                if i < n:
                    colors[i] = c
        yield colors
        t += step


# ---------------------------------------------------------------- 소리 반응

# 소리를 읽는 스레드는 하나면 충분하다. 효과를 바꿔가며 켜고 끄면 그때마다
# 오디오 장치를 다시 여느라 첫 1초가 멎는다. 그래서 한 번 켜면 그냥 둔다.
_audio = None


def get_audio():
    global _audio
    if _audio is None:
        import audio
        _audio = audio.AudioLevel()
        _audio.start()
    return _audio


def audio_status():
    """대시보드가 '소리를 읽고 있나'를 보여주기 위해 쓴다."""
    if _audio is None:
        return {"running": False, "ok": False, "error": "", "level": 0.0,
                "bands": {"low": 0.0, "mid": 0.0, "high": 0.0}}
    s = _audio.snapshot()
    s["running"] = True
    return s


def pulse(n, speed):
    """아이스 배치 그대로, 소리 크기에 따라 전체가 밝아졌다 어두워진다.

    색은 안 건드리고 밝기만 움직인다. 그래서 지금 쓰는 흰색-하늘색 테마가
    그대로 유지되면서 음악에 맞춰 숨쉬듯 출렁인다.
    완전히 꺼지면 조용한 구간에서 방이 깜깜해지니 0.18을 바닥으로 둔다.
    """
    a = get_audio()
    base = ice_colors(n)
    floor, span = 0.18, 0.82
    while True:
        lv = a.snapshot()["level"]
        level = floor + span * min(1.0, lv * speed)
        yield [scaled(c, level) for c in base]


# 레벨 미터 색. 아래는 초록, 꽉 차면 빨강 - 오디오 기기에서 익숙한 배색이다.
VU_STOPS = [
    (0, 255, 90),
    (180, 255, 0),
    (255, 190, 0),
    (255, 40, 0),
]


def vu(n, speed):
    """소리 크기만큼 LED 줄이 차오르는 레벨 미터.

    채널 순서가 팬0 안쪽 -> 팬0 테두리 -> 팬1 안쪽 ... 이라서, 차오르는 게
    팬 하나씩 채워지는 것처럼 보인다.
    """
    a = get_audio()
    black = RGBColor(0, 0, 0)
    while True:
        lv = min(1.0, a.snapshot()["level"] * speed)
        edge = lv * n
        colors = []
        for i in range(n):
            if i < edge:
                colors.append(_ramp(VU_STOPS, i / max(1, n - 1)))
            else:
                colors.append(black)
        yield colors


def spectrum(n, speed):
    """저음이 세면 붉게, 고음이 세면 푸르게. 밝기는 소리 크기를 따라간다.

    대역은 서로의 비율(합이 1)로 들어오므로 볼륨을 올려도 색은 안 튀고
    곡의 성격만 색으로 나온다. 킥이 박히면 순간 붉어지는 게 눈에 보인다.
    """
    a = get_audio()
    zones = max(1, n // fan.LEDS_PER_CHANNEL)

    # 저음은 원래 고음보다 에너지가 훨씬 크다. 그래서 두 값을 그냥 빼면
    # 어떤 곡이든 늘 저음 쪽으로 붙어서 색이 빨강에서 안 움직인다.
    # 대신 최근 평균을 중심으로 잡고 거기서 얼마나 벗어났는지를 색으로 쓴다.
    # 곡이 바뀌어도 몇 초 안에 알아서 중심을 다시 잡는다.
    avg = None
    while True:
        s = a.snapshot()
        b = s["bands"]
        raw = b["low"] - b["high"]
        avg = raw if avg is None else avg + (raw - avg) * 0.002
        # +1이면 평소보다 저음이 센 순간, -1이면 고음이 센 순간.
        # 0.28을 곱해 빨강(0) ~ 초록(0.28) ~ 파랑(0.56) 구간에 앉힌다.
        tilt = max(-1.0, min(1.0, (raw - avg) * 8.0))
        hue = 0.28 * (1.0 - tilt)
        level = 0.15 + 0.85 * min(1.0, s["level"] * speed)

        colors = [RGBColor(0, 0, 0)] * n
        for z in range(zones):
            # 팬마다 색을 조금씩 밀어 한 덩어리로 안 보이게 한다.
            c = hsv(hue + (z // 2) * 0.02, 1.0, level)
            for i in fan.zone_range(z):
                if i < n:
                    colors[i] = c
        yield colors


def _avg_color(img, samples=2500):
    """화면 픽셀을 듬성듬성 훑어 평균색을 구한다.

    4K 전체를 순회하면 프레임당 수백만 픽셀이라 너무 느리다.
    일정 간격으로 건너뛰며 읽어도 평균색은 거의 같다.
    """
    raw = img.rgb
    total = len(raw) // 3
    step = max(1, total // samples)
    r = g = b = cnt = 0
    for i in range(0, total, step):
        j = i * 3
        r += raw[j]
        g += raw[j + 1]
        b += raw[j + 2]
        cnt += 1
    return (r // cnt, g // cnt, b // cnt)


def _vivid(rgb, sat_gain=1.7, min_v=0.30):
    """화면 평균색은 회색에 가까워지기 쉬우니 채도와 밝기를 끌어올린다."""
    r, g, b = (c / 255 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, s * sat_gain)
    v = max(min_v, v)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return RGBColor(int(r * 255), int(g * 255), int(b * 255))


def _blend(a, b, t):
    return RGBColor(
        int(a.red + (b.red - a.red) * t),
        int(a.green + (b.green - a.green) * t),
        int(a.blue + (b.blue - a.blue) * t),
    )


def screen(n, speed):
    """화면에 보이는 색을 조명이 따라간다 (월페이퍼 엔진 동기화).

    화면 캡처는 비싸서 매 프레임 하지 않는다. 초당 5번만 찍고, 그 사이는
    이전 색에서 새 색으로 부드럽게 이어붙인다. 그래서 화면이 확 바뀌어도
    조명은 튀지 않고 스르륵 따라간다.
    """
    import mss

    grab_every = max(1, int(FPS / 5))
    ease = min(1.0, 0.10 * speed)
    current = RGBColor(0, 0, 0)
    target = RGBColor(0, 0, 0)
    tick = 0

    with mss.mss() as sct:
        mon = sct.monitors[1]  # 0번은 전체 합성 화면, 1번이 주 모니터
        while True:
            if tick % grab_every == 0:
                try:
                    target = _vivid(_avg_color(sct.grab(mon)))
                except Exception:
                    pass  # 캡처가 한 번 실패해도 직전 색을 유지한다
            current = _blend(current, target, ease)
            yield [current] * n
            tick += 1


def run(frames_for):
    cli, dev = fan.setup("effects")
    n = len(dev.leds)
    print(f"연결됨: {dev.name} (LED {n}개)")
    print("멈추려면 Ctrl+C\n")

    frames = frames_for(n)
    sent = 0
    reconnects = 0

    for colors in frames:
        try:
            dev.set_colors(fan.mute_dead(colors))
            sent += 1
        except Exception:
            # 서버가 죽거나 끊기면 살아날 때까지 기다렸다 다시 붙는다.
            reconnects += 1
            print(f"\n연결이 끊겼어. 다시 붙는 중... ({reconnects}회)")
            while not fan.server_alive():
                time.sleep(2)
            try:
                cli, dev = fan.setup("effects")
                n = len(dev.leds)
                frames = frames_for(n)
                print("다시 연결됐어.\n")
            except Exception:
                time.sleep(2)
            continue

        if sent % FPS == 0:
            print(f"\r{sent // FPS}초째 실행 중 / 재연결 {reconnects}회   ",
                  end="", flush=True)
        time.sleep(DELAY)


def main():
    args = sys.argv[1:]
    mode = args[0] if args else "wave"

    color = RGBColor(160, 0, 255)
    speed = 1.0
    for a in args[1:]:
        try:
            speed = float(a)
        except ValueError:
            color = parse_hex(a)

    if mode == "wave":
        frames_for = lambda n: wave(n, speed)
    elif mode == "rainbow":
        frames_for = lambda n: rainbow(n, speed)
    elif mode == "breathe":
        frames_for = lambda n: breathe(n, speed, color)
    elif mode == "static":
        frames_for = lambda n: static(n, color)
    elif mode == "soft":
        frames_for = lambda n: soft(n, speed)
    elif mode == "ice":
        frames_for = lambda n: ice(n, speed)
    elif mode == "depth":
        frames_for = lambda n: depth(n, speed)
    elif mode == "screen":
        frames_for = lambda n: screen(n, speed)
    elif mode == "pulse":
        frames_for = lambda n: pulse(n, speed)
    elif mode == "vu":
        frames_for = lambda n: vu(n, speed)
    elif mode == "spectrum":
        frames_for = lambda n: spectrum(n, speed)
    else:
        print(__doc__)
        return 1

    try:
        run(frames_for)
    except KeyboardInterrupt:
        print("\n\n멈췄어. 조명은 마지막 상태 그대로야.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
