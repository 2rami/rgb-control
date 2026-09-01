"""웹 대시보드 - 브라우저에서 조명 상태를 보고 효과를 바꾼다.

    python dashboard.py
    브라우저에서 http://127.0.0.1:5000

OpenRGB에 접근하는 건 효과 스레드 하나뿐이다. Flask 쪽은 state/snapshot
변수만 읽고 쓴다 - 하나의 OpenRGB 연결을 여러 스레드가 동시에 만지면
프로토콜이 엉켜서 통신이 깨진다.
"""

import faulthandler
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
from flask import Flask, jsonify, render_template, request
from openrgb.utils import RGBColor

import effects
import fan
import kraken as kr
import lcd_monitor as lm
import video as vid
import cookies_setup
import parts as parts_mod

app = Flask(__name__)
# 화면(templates)을 고치면 새로고침만으로 보이게 한다. 기본값은 캐시라
# 대시보드를 재시작해야 반영돼서, 고쳐 놓고 "왜 안 바뀌지" 하기 쉽다.
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True

# 팬은 20fps로 쏴도 멀쩡하지만 다른 장치는 아니다. 특히 램은 SMBus를 타는데,
# 초당 5번만 쏴도 OpenRGB가 통째로 죽는 걸 확인했다. 그래서 1초에 한 번만.
SYNC_EVERY = 20

# nvidia-smi를 콘솔 창 없이 실행하기 위한 윈도우 전용 설정.
# 2초에 한 번씩 부르기 때문에, 창이 안 숨겨지면 화면에서 검은 창이 계속
# 깜빡인다. creationflags 하나만으로는 새는 경우가 있어 STARTUPINFO 로
# 한 번 더 막는다.
CREATE_NO_WINDOW = 0x08000000


def _hidden_startupinfo():
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


HIDDEN = _hidden_startupinfo()

# USB로 붙는 장치들. 색을 쏴도 비교적 안전하다.
# LEDSTRIP은 Razer ARGB 컨트롤러다. 6채널 x 60 = 360 LED.
# ★그래픽카드(Colorful RTX 4070 Ti) LED 는 채널 5 (LED 240~299)에 물려 있다.
#   빨강을 뺀 팔레트로 probe_razer.py 를 돌려 확인했다 (2026-09-02).
# ★★Razer Synapse(RazerAppEngine)가 돌고 있으면 우리 색이 통째로 무시된다.
#   쓰기는 성공으로 돌아오는데 카드는 Synapse 색 그대로다. 그것 때문에
#   "글카는 Razer 와 무관하다"는 잘못된 결론까지 갔었다.
#   start_all.ps1 이 시작할 때 RazerAppEngine 을 죽이는 이유가 이것이다.
SAFE_TYPES = ("SPEAKER", "MOUSEMAT", "LEDSTRIP")

# 색을 쏘면 OpenRGB를 통째로 죽이는 장치. 하나씩 붙여가며 실측으로 확인했다.
# (팬만=90초 생존, 팬+스피커=60초 생존, Candy 포함=10초 내 사망)
BLOCKED = ("Candy companion chip",)

# 램은 SMBus라 다른 장치와 격이 다르게 느리고 예민해서 따로 뗐다.
# 제어가 되려면 G.SKILL Trident Z Lighting Control (프로세스 이름이 그냥 `hid`)이
# 꺼져 있어야 한다. 얘가 살아있으면 OpenRGB 쓰기가 통째로 무시된다 -
# 쓰기는 성공으로 돌아오는데 OpenRGB를 재시작하면 (0,0,0)으로 읽힌다.
# start.bat이 시작할 때 hid.exe를 종료하는 이유가 이것이다.
# 참고: 램 2개 중 하나(DRAM1)는 명령을 받아도 실제로 켜지지 않는다.
RAM_TYPES = ("DRAM",)

state = {
    # 켜자마자 흰색-하늘색 고정 배치로 뜨게 한다. 불량 팬이 파랑 성분을
    # 못 견뎌 테두리를 꺼둔 상태라, 색이 도는 효과보다 이쪽이 깔끔하다.
    "mode": "ice",
    "speed": 1.0,
    "color": "9bd7ff",
    "sync_all": True,
    "sync_ram": True,
    # 램·글카·스피커를 팬 평균색 하나로 통일할지, 팬 그라데이션을 펼칠지.
    # 작은 장치가 자기 안에서 램프를 또 돌면 혼자 따로 노는 것처럼 보인다.
    "sync_solid": True,
}

# 크라켄(수랭 쿨러)은 OpenRGB 와 아무 상관이 없다. USB 로 따로 붙고,
# 그 장치를 잡을 수 있는 것은 한 프로세스뿐이다. 그래서 전용 스레드가
# 연결을 하나 들고 냉각과 화면을 모두 맡는다.
kraken_state = {
    "enabled": True,
    "pump_mode": "curve",   # curve = 수온 따라감 / fixed = 손으로 정한 값
    "pump_duty": 90,
    "lcd_mode": "stats",    # off / stats / sync / mirror / video / spin(진단용)
    "mirror_box": 640,
    "video_url": "",
    "video_audio": True,
}

snapshot = {
    "connected": False,
    "error": "",
    "zones": [],
    "devices": [],
    "synced": [],
    "ram": [],
    # 크라켄 쪽
    "kraken_ok": False,
    "kraken_error": "",
    "liquid": None,
    "pump_rpm": None,
    "pump_duty": None,
    "fan_rpm": None,
    "lcd_fps": 0.0,
    "kraken_bad_reads": 0,
    "video_title": "",
    "video_error": "",
    "video_playing": False,
    "video_index": 0,
    "video_total": 0,
}

lock = threading.Lock()

# 케이스 그림에서 부품 하나만 다른 색으로 바꾸거나, 어느 팬인지 찾을 때 쓴다.
parts = parts_mod.Parts()


def collect_devices(cli):
    return [
        {
            "id": d.id,
            "name": d.name,
            "type": d.type.name,
            "leds": len(d.leds),
        }
        for d in cli.devices
    ]


def prepare_device(d, prepared, failed):
    """장치를 Direct 모드로 돌려둔다. 한 번만 하면 된다."""
    if d.id in prepared:
        return True
    if d.id in failed:
        return False
    names = [m.name.lower() for m in d.modes]
    try:
        if "direct" in names:
            d.set_mode("direct")
        elif "static" in names:
            d.set_mode("static")
    except Exception:
        failed.add(d.id)
        return False
    prepared.add(d.id)
    return True


def sync_targets(cli, hub):
    """같이 물들일 장치를 안전한 것(USB)과 위험한 것(램)으로 나눈다.

    램은 모드를 바꾸는 것만으로도 SMBus를 건드려 OpenRGB를 죽인다. 그래서
    여기선 목록만 만들고, 사용자가 실제로 켜기 전까지는 손대지 않는다.
    """
    safe, ram = [], []
    prepared, failed = set(), set()
    for d in cli.devices:
        if d.id == hub.id or not len(d.leds) or d.name in BLOCKED:
            continue
        if d.type.name in SAFE_TYPES:
            if prepare_device(d, prepared, failed):
                safe.append(d)
        elif d.type.name in RAM_TYPES:
            ram.append(d)
    return safe, ram


def live_colors(colors):
    """꺼둔 불량 팬 자리를 뺀 색 목록.

    불량 링을 검게 칠해 뒀는데 그 검정까지 램·그래픽카드가 베껴가면,
    멀쩡한 장치에 이유 없는 검은 칸이 생긴다 (램은 LED가 8개뿐이라
    한 칸만 꺼져도 눈에 띈다). 색을 나눠줄 때는 살아있는 자리만 본다.
    """
    dead = fan.dead_leds()
    if not dead:
        return colors
    return [c for i, c in enumerate(colors) if i not in dead] or colors


def spread(src, k):
    """색 목록을 LED k개에 고르게 펼친다."""
    total = len(src)
    return [src[min(total - 1, i * total // k)] for i in range(k)]


def average(src):
    """색 목록의 평균색 하나.

    팬은 흰색에서 파랑으로 번지는 그라데이션인데, 글카처럼 작은 장치가
    그 램프를 자기 안에서 또 한 번 돌면 혼자 따로 노는 것처럼 보인다.
    팬 전체를 대표하는 색 하나로 칠하면 같은 조명의 일부로 읽힌다.
    """
    n = len(src)
    r = sum(c.red for c in src) // n
    g = sum(c.green for c in src) // n
    b = sum(c.blue for c in src) // n
    return RGBColor(r, g, b)


def paint_targets(targets, colors, prepared, failed, solid=True):
    """팬 색을 램·글카·스피커에 나눠준다.

    solid=True  팬 전체의 평균색 하나로 통일한다. 팬과 "같은 색"으로 보인다.
    solid=False 채널마다 팬의 그라데이션을 한 번씩 편다.
        ★장치 전체에 한 번만 펼치면 안 된다. 여러 채널 중 한 곳에만
        하드웨어가 물린 컨트롤러가 손해를 보기 때문이다. Razer 컨트롤러가
        그렇다 - 6채널 360개인데 글카는 채널 1(앞 60개)에만 물려 있어서,
        360개에 한 번 펼치면 글카에는 팬 앞부분 색만 갔다. 하필 그 자리가
        불량 팬이라 글카가 늘 같은 파란색이었다.

    한 번 실패한 장치는 failed에 넣고 다시 건드리지 않는다. 말썽인 장치 하나가
    OpenRGB 전체를 끌어내리는 걸 막기 위해서다.
    """
    src = live_colors(colors)
    if not src:
        return
    one = average(src) if solid else None

    for d in targets:
        if not prepare_device(d, prepared, failed):
            continue
        # 그 장치만 따로 정한 색이 있으면 그걸 쓴다.
        name = ("ram" if d.type.name in RAM_TYPES
                else "gpu" if d.type.name == "LEDSTRIP"
                else "speaker" if d.type.name == "SPEAKER" else None)
        picked = parts.device_color(name) if name else None
        try:
            if picked is not None:
                d.set_colors([picked] * len(d.leds))
                continue
            if solid:
                d.set_colors([one] * len(d.leds))
                continue
            zones = getattr(d, "zones", None)
            if zones and len(zones) > 1:
                out = []
                for z in zones:
                    out += spread(src, len(z.leds))
                d.set_colors(out)
            else:
                d.set_colors(spread(src, len(d.leds)))
        except Exception:
            failed.add(d.id)


def zone_swatches(colors, zones):
    """채널마다 대표색 하나씩. 채널 한가운데 LED를 쓴다."""
    out = []
    half = fan.LEDS_PER_CHANNEL // 2
    for z in range(zones):
        i = z * fan.LEDS_PER_CHANNEL + half
        c = colors[i] if i < len(colors) else RGBColor(0, 0, 0)
        out.append({
            "zone": z,
            "hex": f"#{c.red:02x}{c.green:02x}{c.blue:02x}",
            "dead": z in fan.DEAD_ZONES,
        })
    return out


def make_frames(mode, n, speed, color):
    if mode == "rainbow":
        return effects.rainbow(n, speed)
    if mode == "breathe":
        return effects.breathe(n, speed, color)
    if mode == "static":
        return effects.static(n, color)
    if mode == "soft":
        return effects.soft(n, speed)
    if mode == "ice":
        return effects.ice(n, speed)
    if mode == "depth":
        return effects.depth(n, speed)
    if mode == "screen":
        return effects.screen(n, speed)
    if mode == "pulse":
        return effects.pulse(n, speed)
    if mode == "vu":
        return effects.vu(n, speed)
    if mode == "spectrum":
        return effects.spectrum(n, speed)
    return effects.wave(n, speed)


def run_effect(hub, safe, ram):
    n = len(hub.leds)
    zones = len(hub.zones)
    key = None
    frames = None
    tick = 0
    failed = set()
    prepared = {d.id for d in safe}  # safe는 sync_targets에서 이미 준비됐다.

    while True:
        with lock:
            mode = state["mode"]
            speed = state["speed"]
            hexcolor = state["color"]
            sync = state["sync_all"]
            use_ram = state["sync_ram"]
            solid = state["sync_solid"]

        # 설정이 바뀌었을 때만 제너레이터를 새로 만든다.
        now = (mode, speed, hexcolor)
        if now != key:
            key = now
            try:
                color = effects.parse_hex(hexcolor)
            except ValueError:
                color = RGBColor(160, 0, 255)
            frames = make_frames(mode, n, speed, color)

        # 효과가 만든 색 위에 부품별로 정한 색을 덮는다.
        # 순서가 중요하다 - 불량 링 소등이 맨 마지막이어야 한다. 안 그러면
        # 부품 색이 꺼둔 링을 다시 켜 버린다.
        colors = parts.apply_fans(next(frames))
        colors = fan.mute_dead(colors)
        hub.set_colors(colors)

        tick += 1
        if sync and tick % SYNC_EVERY == 0:
            paint_targets(safe + (ram if use_ram else []), colors,
                          prepared, failed, solid)

        with lock:
            snapshot["zones"] = zone_swatches(colors, zones)

        time.sleep(effects.DELAY)


# ------------------------------------------------------------------- 크라켄

# 영상 재생기는 한 번에 하나만 돈다. 주소가 바뀌면 옛것을 끄고 새로 켠다.
_player = {"obj": None, "url": None}


def video_frame():
    """지금 틀어야 할 영상의 최신 한 장. 없으면 None."""
    with lock:
        url = kraken_state["video_url"].strip()
        audio = kraken_state["video_audio"]

    cur = _player["obj"]
    if not url:
        stop_video()
        return None

    if cur is None or _player["url"] != url or cur.done:
        stop_video()
        cur = vid.Player(url, audio=audio).start()
        _player.update(obj=cur, url=url)
        say(f"영상 시작: {url}")

    with lock:
        snapshot["video_title"] = cur.title
        snapshot["video_error"] = cur.error
        snapshot["video_playing"] = not cur.done and cur.frames > 0
        snapshot["video_index"] = cur.index
        snapshot["video_total"] = cur.total
    return cur.latest()


def stop_video():
    if _player["obj"] is not None:
        try:
            _player["obj"].stop()
        except Exception:
            pass
    _player.update(obj=None, url=None)
    with lock:
        snapshot["video_playing"] = False


# ★프레임을 "만드는 쪽"과 "보내는 쪽"을 나눈다.
#
# 예전에는 한 스레드가 캡처하고, 인코딩하고, 보내고, 상태까지 읽었다.
# 보내는 17ms 동안 캡처가 멈추고, 캡처하는 7ms 동안 화면이 멈춘다.
# 게다가 2초마다 상태를 읽느라 100ms 넘게 통째로 멈췄다. 그게 눈에는
# "끊기고 멈칫거린다"로 보인다.
#
# 이제 만드는 쪽은 계속 최신 한 장을 준비해 두고, 보내는 쪽은 그것만
# 집어서 보낸다. 서로 기다리지 않는다.
# 칸은 하나뿐이라 못 보낸 프레임은 그냥 덮어써진다 - 밀린 옛 화면을
# 뒤늦게 보여주는 것보다 최신 것을 보여주는 게 맞다(=지연이 안 쌓인다).
_ready = {"data": None}
_ready_lock = threading.Lock()
_orientation = {"v": 0}


def take_frame():
    with _ready_lock:
        d = _ready["data"]
        _ready["data"] = None
        return d


def put_frame(data):
    with _ready_lock:
        _ready["data"] = data


def frame_producer():
    """화면을 만들어 Q565 로 인코딩해 두는 스레드. 장치는 안 만진다."""
    import mss

    import lcd_stream as L

    sct = None
    while True:
        with lock:
            mode = kraken_state["lcd_mode"]
            box = kraken_state["mirror_box"]

        if mode == "off" or not kraken_state["enabled"]:
            time.sleep(0.3)
            continue

        try:
            if mode == "mirror":
                if sct is None:
                    sct = mss.MSS()
                img = lm.grab_region(sct, box)
            elif mode == "video":
                img = video_frame()
                if img is None:
                    time.sleep(0.05)
                    continue
            elif mode == "spin":
                img = lm.draw_spin(time.time())
            elif mode == "sync":
                # 팬 채널 대표색을 그대로 쓴다. 조명이 바뀌면 화면도 바뀐다.
                with lock:
                    zs = snapshot["zones"]
                img = lm.draw_sync(zs[0]["hex"] if zs else None)
            else:
                img = lm.draw_stats()

            fitted = L.fit(img, _orientation["v"])
            # 움직이는 화면은 디더를 안 쓴다. 디더가 압축을 깨서 데이터가
            # 두세 배로 불고 그만큼 느려지는데, 움직이면 띠는 잘 안 보인다.
            put_frame(L.to_q565(L.crop_circle(fitted)))
        except Exception as e:
            say(f"화면 만들기 실패: {e!r}")
            time.sleep(1.0)
            continue

        # 상태판은 1초에 한 장이면 충분하다.
        # 나머지는 안 쉰다 - 인코딩 자체가 몇 ms 를 쓰고, 여기서 1ms 를
        # 자라고 하면 윈도우는 15ms 를 자 버려 오히려 리듬이 깨진다.
        if mode in ("stats", "sync"):
            time.sleep(1.0)


def kraken_once(k, mirror_sct):
    """한 바퀴: 상태 읽고 -> 펌프 맞추고 -> 화면 한 장.

    화면을 그리는 것과 펌프를 정하는 것은 주기가 다르다. 상태 읽기는 장치와
    HID 로 왕복해야 해서 비싸고, 값도 그렇게 빨리 안 변한다. 화면 비추기는
    초당 여러 장이어야 화면 같다. 그래서 상태는 몇 초에 한 번만 읽는다.
    """
    now = time.time()
    if now - kraken_once.last_poll >= kr.POLL_SECONDS:
        kraken_once.last_poll = now
        # ★한 번만 읽는다. 재시도를 넣었더니 멈칫이 두 배가 됐다.
        # 상태를 읽는 동안에는 화면이 멈추기 때문이다. 헛읽기면 그 회차를
        # 건너뛰고 다음 차례(몇 초 뒤)에 다시 읽으면 된다 - 수온은 그렇게
        # 빨리 안 변한다. 화면이 매끄러운 게 더 중요하다.
        st = k.status()
        # 헛읽기면 이번 회차는 통째로 건너뛴다. 옛 값을 그대로 두는 게
        # 0도라는 거짓말을 믿고 펌프를 늦추는 것보다 안전하다.
        if st is None:
            kraken_once.bad_reads += 1
            with lock:
                snapshot["kraken_bad_reads"] = kraken_once.bad_reads
            return 0.0
        with lock:
            snapshot.update(kraken_ok=True, kraken_error="",
                            liquid=st.get("liquid"),
                            pump_rpm=st.get("pump_rpm"),
                            pump_duty=st.get("pump_duty"),
                            fan_rpm=st.get("fan_rpm"))
            mode = kraken_state["pump_mode"]
            want = kraken_state["pump_duty"]

        if mode == "curve":
            want = int(round(kr.interpolate(kr.DEFAULT_CURVE,
                                            st.get("liquid", 40))))
        # 1~2% 흔들릴 때마다 명령을 보내면 장치를 괴롭히기만 한다.
        if kraken_once.last_pump is None or abs(want - kraken_once.last_pump) >= 3:
            kraken_once.last_pump = k.set_pump(want)

    with lock:
        lcd_mode = kraken_state["lcd_mode"]
        box = kraken_state["mirror_box"]

    if lcd_mode == "off":
        stop_video()
        return 1.0        # 화면은 장치 기본 그대로 둔다

    # 만드는 쪽이 준비해 둔 최신 한 장. 없으면 아직 안 만들어진 것이다.
    data = take_frame()
    if data is None:
        return 0.002   # 만드는 쪽이 아직 못 냈다
    k.show_raw(data)
    # ★실제로 보낸 것만 센다. 예전에는 루프가 돈 횟수를 세는 바람에
    # 보낼 게 없어 헛도는 것까지 세서 "초당 200장" 같은 거짓말이 나왔다.
    kraken_once.sent += 1
    return 0.0


kraken_once.last_poll = 0.0
kraken_once.last_pump = None
kraken_once.bad_reads = 0
kraken_once.sent = 0


def kraken_loop():
    """끊겨도 계속 되살아나는 바깥 루프. 조명 쪽과 같은 구조다."""
    import mss

    kraken_loop.fails = getattr(kraken_loop, "fails", 0)

    while True:
        if not kraken_state["enabled"]:
            time.sleep(3)
            continue
        try:
            with kr.Kraken() as k, mss.MSS() as sct:
                # 만드는 쪽이 미리 돌려 놓으려면 방향을 알아야 한다.
                k.screen_ready()
                _orientation["v"] = k.orientation
                say(f"크라켄 붙음 (화면 방향 {k.orientation})")
                kraken_once.last_poll = 0.0
                kraken_once.last_pump = None
                # ★최근 구간만 본다. 연결 이후 누적 평균으로 재면 시작할 때의
                # 느린 구간이 계속 끌고 내려가서, 실제로는 30장이 나오는데
                # 5장으로 보인다. 그것 때문에 엉뚱한 곳을 최적화할 뻔했다.
                kraken_once.sent, t0 = 0, time.time()
                while kraken_state["enabled"]:
                    nap = kraken_once(k, sct)
                    now = time.time()
                    if now - t0 >= 2.0:
                        with lock:
                            snapshot["lcd_fps"] = kraken_once.sent / (now - t0)
                        kraken_once.sent, t0 = 0, now
                    if nap:
                        time.sleep(nap)
        except Exception as e:
            msg = str(e) or type(e).__name__
            with lock:
                snapshot.update(kraken_ok=False, kraken_error=msg, lcd_fps=0.0)
                mode = kraken_state["lcd_mode"]
            say(f"크라켄 끊김: {msg}")

            # ★같은 실패가 이어지면 화면을 스스로 끈다.
            # 전송이 장치를 괴롭혀서 나는 실패라면, 계속 다시 시도하는 것이
            # 상황을 악화시킨다. 냉각(수온·펌프)은 화면 없이도 돌아가므로
            # 그쪽을 지키는 편이 낫다.
            kraken_loop.fails += 1
            if kraken_loop.fails >= 3 and mode != "off":
                with lock:
                    kraken_state["lcd_mode"] = "off"
                stop_video()
                say(f"화면 전송이 {kraken_loop.fails}번 연속 실패해서 화면을 껐다. "
                    "냉각은 계속 돌아간다.")
            time.sleep(6)
        else:
            kraken_loop.fails = 0


def effect_loop():
    """연결이 끊겨도 계속 되살아나는 바깥 루프."""
    while True:
        try:
            cli, hub = fan.setup("dashboard")
            safe, ram = sync_targets(cli, hub)
            with lock:
                snapshot["connected"] = True
                snapshot["error"] = ""
                snapshot["devices"] = collect_devices(cli)
                snapshot["synced"] = [d.name for d in safe]
                snapshot["ram"] = [d.name for d in ram]
            run_effect(hub, safe, ram)
        except Exception as e:
            msg = str(e) or type(e).__name__
            with lock:
                snapshot["connected"] = False
                snapshot["error"] = msg
            # 조명이 멈췄을 때 "언제부터, 왜"를 알려면 이 줄이 있어야 한다.
            say(f"조명 루프 끊김: {msg}")
            time.sleep(3)


_gpu_cache = {"at": 0.0, "data": None}


def gpu_stats():
    now = time.time()
    if now - _gpu_cache["at"] < 2.0:
        return _gpu_cache["data"]

    data = None
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=CREATE_NO_WINDOW, startupinfo=HIDDEN,
        )
        if r.returncode == 0 and r.stdout.strip():
            name, temp, util = (x.strip() for x in r.stdout.strip().splitlines()[0].split(","))
            data = {"name": name, "temp": int(temp), "util": int(util)}
    except Exception:
        data = None

    _gpu_cache.update(at=now, data=data)
    return data


def cpu_stats():
    """이 보드는 ACPI로 CPU 온도를 안 내준다.

    LibreHardwareMonitor를 깔아 실행해두면 root/LibreHardwareMonitor WMI에서
    온도를 읽을 수 있다. 지금은 사용률만 쓴다.
    """
    return {
        "util": psutil.cpu_percent(interval=None),
        "temp": None,
        "freq": round((psutil.cpu_freq().current or 0) / 1000, 2) if psutil.cpu_freq() else None,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    with lock:
        snap = {k: v for k, v in snapshot.items()}
        st = dict(state)
    return jsonify({
        "state": st,
        "connected": snap["connected"],
        "error": snap["error"],
        "zones": snap["zones"],
        "devices": snap["devices"],
        "synced": snap["synced"],
        "ram": snap["ram"],
        "dead_zones": fan.DEAD_ZONES,
        "cpu": cpu_stats(),
        "gpu": gpu_stats(),
        "audio": effects.audio_status(),
        "parts": parts.snapshot(),
        "kraken": {
            "state": dict(kraken_state),
            "ok": snap["kraken_ok"],
            "error": snap["kraken_error"],
            "liquid": snap["liquid"],
            "pump_rpm": snap["pump_rpm"],
            "pump_duty": snap["pump_duty"],
            "fan_rpm": snap["fan_rpm"],
            "lcd_fps": round(snap["lcd_fps"], 1),
            "bad_reads": snap["kraken_bad_reads"],
            "video_title": snap["video_title"],
            "video_error": snap["video_error"],
            "video_playing": snap["video_playing"],
            "video_index": snap["video_index"],
            "video_total": snap["video_total"],
            "login": cookies_setup.status(),
        },
    })


@app.route("/api/audio")
def api_audio():
    """소리 막대만 따로 준다.

    /api/state 는 nvidia-smi 와 장치 목록까지 실어서 무겁다. 소리 미터는
    박자가 보이려면 초당 열몇 번은 읽어야 해서 가벼운 창구를 따로 뒀다.
    """
    return jsonify(effects.audio_status())


@app.route("/api/kraken", methods=["POST"])
def api_kraken():
    data = request.get_json(force=True, silent=True) or {}
    with lock:
        if "enabled" in data:
            kraken_state["enabled"] = bool(data["enabled"])
        if "pump_mode" in data and data["pump_mode"] in ("curve", "fixed"):
            kraken_state["pump_mode"] = data["pump_mode"]
        if "pump_duty" in data:
            kraken_state["pump_duty"] = int(
                max(kr.PUMP_FLOOR, min(kr.PUMP_CEIL, float(data["pump_duty"]))))
        if "video_url" in data:
            kraken_state["video_url"] = str(data["video_url"]).strip()
        if "video_audio" in data:
            kraken_state["video_audio"] = bool(data["video_audio"])
        if "lcd_mode" in data and data["lcd_mode"] in ("off", "stats", "sync", "mirror", "video", "spin"):
            kraken_state["lcd_mode"] = data["lcd_mode"]
        if "mirror_box" in data:
            kraken_state["mirror_box"] = int(max(200, min(1440, int(data["mirror_box"]))))
        st = dict(kraken_state)
    # 손으로 정한 값은 다음 한 바퀴를 기다리지 말고 바로 반영되게 한다.
    kraken_once.last_pump = None
    if "video_url" in data or data.get("lcd_mode") not in (None, "video"):
        stop_video()
    return jsonify({"ok": True, "state": st})


@app.route("/api/part", methods=["POST"])
def api_part():
    """케이스 그림에서 부품 하나를 만진다.

    {"part":"top1","color":"ff0000"}   그 부품만 그 색으로
    {"part":"top1","color":null}       해제 (효과를 따라감)
    {"part":"top1","find":1}           몇 초 하얗게 - 어느 팬인지 눈으로 찾기
    {"spot":"top1","next":1}           그 자리에 붙은 채널을 다음 것으로
    """
    data = request.get_json(force=True, silent=True) or {}
    with lock:
        if "spot" in data and data.get("next"):
            spot = parts.base_spot(str(data["spot"]))
            slot = parts.next_slot(spot, int(data["next"]))
            parts.find(spot)
            return jsonify({"ok": True, "slot": slot, "parts": parts.snapshot()})

        if "label_all" in data:
            if data["label_all"]:
                parts.label_all()
            else:
                parts.stop_labeling()
            return jsonify({"ok": True, "parts": parts.snapshot()})

        part = str(data.get("part", ""))
        if not part:
            return jsonify({"ok": False, "message": "어느 부품인지 안 왔다"})
        if data.get("find"):
            parts.find(part)
        else:
            parts.set_color(part, data.get("color"))
    return jsonify({"ok": True, "parts": parts.snapshot()})


@app.route("/api/cookies", methods=["POST"])
def api_cookies():
    """유튜브 로그인 쿠키를 대시보드에서 넣고 뺀다.

    {"text": "..."}      붙여넣은 쿠키 저장
    {"from_browser": 1}  브라우저에서 직접 뽑아 보기
    {"clear": 1}         지우기
    """
    data = request.get_json(force=True, silent=True) or {}
    if data.get("clear"):
        ok, msg = cookies_setup.clear()
    elif data.get("from_browser"):
        ok, msg = cookies_setup.from_browser()
    else:
        ok, msg = cookies_setup.save(data.get("text", ""))
    say(f"유튜브 로그인: {msg}")
    # 쿠키가 바뀌면 지금 틀던 것도 새 자격으로 다시 열게 한다.
    if ok:
        stop_video()
    return jsonify({"ok": ok, "message": msg, "status": cookies_setup.status()})


@app.route("/api/effect", methods=["POST"])
def api_effect():
    data = request.get_json(force=True, silent=True) or {}
    with lock:
        if "mode" in data:
            state["mode"] = str(data["mode"])
        if "speed" in data:
            state["speed"] = max(0.1, min(5.0, float(data["speed"])))
        if "color" in data:
            state["color"] = str(data["color"]).lstrip("#")
        if "sync_all" in data:
            state["sync_all"] = bool(data["sync_all"])
        if "sync_ram" in data:
            state["sync_ram"] = bool(data["sync_ram"])
        if "sync_solid" in data:
            state["sync_solid"] = bool(data["sync_solid"])
        st = dict(state)
    return jsonify({"ok": True, "state": st})


LOG = Path(__file__).with_name("dashboard.log")


def say(msg):
    line = f"{time.strftime('%m-%d %H:%M:%S')}  {msg}"
    print(line)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def sharpen_timer():
    """윈도우 타이머 해상도를 1ms 로 올린다.

    ★기본값은 약 15.6ms 다. time.sleep(0.001) 을 시켜도 15ms 를 자 버린다.
    화면을 초당 30~40장 보내는 프로그램에서 이건 치명적이다 - 어떤 장은
    제때 나가고 어떤 장은 15ms 늦게 나가서, 눈에는 "가끔 멈칫"으로 보인다.
    프로그램이 끝나면 윈도우가 알아서 되돌린다.
    """
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
        return True
    except Exception:
        return False


def main():
    # pythonw로 띄우면 콘솔이 없어서, 죽어도 이유가 아무데도 안 남는다.
    # 실제로 한 번 조용히 죽어서 조명이 멈춘 적이 있다. 그래서 파일로 남긴다.
    sys.stderr = LOG.open("a", encoding="utf-8", buffering=1)
    faulthandler.enable(sys.stderr)   # 파이썬 자체가 터져도 흔적은 남는다

    # 브라우저가 0.5초마다 상태를 물어서, 그냥 두면 로그가 접속 기록으로
    # 도배된다. 정작 조명이 왜 멈췄는지는 그 사이에 묻힌다.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    say("=== 대시보드 시작 ===" + ("" if sharpen_timer() else " (타이머 해상도 못 올림)"))

    threading.Thread(target=effect_loop, daemon=True).start()
    threading.Thread(target=kraken_loop, daemon=True).start()
    threading.Thread(target=frame_producer, daemon=True).start()
    try:
        app.run(host="127.0.0.1", port=5000, debug=False)
    except Exception as e:
        say(f"!!! 웹서버가 죽었다: {e!r}")
        raise
    finally:
        say("=== 대시보드 종료 ===")


if __name__ == "__main__":
    main()
