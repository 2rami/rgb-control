"""웹 대시보드 - 브라우저에서 조명 상태를 보고 효과를 바꾼다.

    python dashboard.py
    브라우저에서 http://127.0.0.1:5000

OpenRGB에 접근하는 건 효과 스레드 하나뿐이다. Flask 쪽은 state/snapshot
변수만 읽고 쓴다 - 하나의 OpenRGB 연결을 여러 스레드가 동시에 만지면
프로토콜이 엉켜서 통신이 깨진다.
"""

import logging
import subprocess
import threading
import time
from pathlib import Path

import psutil
from flask import Flask, jsonify, render_template, request
from openrgb.utils import RGBColor

import effects
import fan
import kraken as kr
import log as log_mod
import lcd_monitor as lm
import video as vid
import cookies_setup
import parts as parts_mod
import playlists as pl_mod
import display as display_mod
import settings as settings_mod

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
    # 모니터가 꺼지면 조명을 끌지. 끄더라도 설정은 그대로 두고 색만 검게
    # 칠하므로, 화면이 켜지면 저절로 돌아온다.
    "off_with_monitor": True,
    # 켜자마자 흰색-하늘색 고정 배치로 뜨게 한다. 불량 팬이 파랑 성분을
    # 못 견뎌 테두리를 꺼둔 상태라, 색이 도는 효과보다 이쪽이 깔끔하다.
    "mode": "ice",
    # 조명을 껐다가 다시 켤 때 돌아갈 효과. mode 가 "off" 가 되는 순간 적힌다.
    "resume_mode": "ice",
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
    "play_list": None,      # 고른 재생목록 id. None 이면 주소칸을 쓴다
    # 모니터가 꺼질 때 LCD 도 같이 끌 것인가. 조명과 따로 고른다 - 케이스가
    # 책상 위에 있으면 화면을 끈 뒤에도 수온 정도는 보고 싶을 수 있다.
    "lcd_off_with_monitor": True,
}


def remember():
    """지금 설정을 적어 둔다. 바꾸는 곳마다 부른다.

    ★반드시 lock 을 놓은 뒤에 불러라. 파일 쓰기는 느려서, 잠근 채로 하면
    조명을 그리는 스레드가 그동안 멈춰 선다.
    """
    settings_mod.save(state, kraken_state)


def restore():
    """적어 둔 설정을 되돌린다. 없으면 기본값 그대로 둔다."""
    light, kraken = settings_mod.load()
    with lock:
        state.update(light)
        kraken_state.update(kraken)
    return light, kraken

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
    # 마지막 상태 읽기에서 받은 것과, 믿을 만한 값을 마지막으로 읽은 때.
    # kraken_ok·수온은 헛읽기가 이어져도 그대로 남아 몇 시간 묵은 값을 지금
    # 값처럼 보여줬다. 언제 읽은 값인지 같이 내보낸다.
    "kraken_last_read": {},
    "kraken_status_at": None,
    "video_title": "",
    "video_error": "",
    "video_playing": False,
    "video_index": 0,
    "video_total": 0,
}

lock = threading.Lock()

# 케이스 그림에서 부품 하나만 다른 색으로 바꾸거나, 어느 팬인지 찾을 때 쓴다.
parts = parts_mod.Parts()

# 이름 붙인 재생목록과 대기열.
playlists = pl_mod.Playlists()

# 모니터가 꺼지면 조명도 끈다. 보는 사람이 없는데 방을 밝힐 이유가 없고,
# 잘 때 눈부시다. 켜지면 원래대로 돌아온다.
monitor = None


BLACK = RGBColor(0, 0, 0)


def dark_now():
    """지금 조명을 꺼야 하는가. 모니터가 꺼져 있고 그렇게 하기로 했으면 True.

    감시가 아예 안 붙었으면 늘 False 다. 모르는 것을 근거로 조명을 꺼 버리면
    "왜 안 켜지지"가 되기 때문이다.
    """
    if monitor is None or not monitor.ok:
        return False
    with lock:
        want = state["off_with_monitor"]
    return want and not monitor.is_on()


def lcd_asleep():
    """지금 LCD 를 재워야 하는가.

    ★화면을 만드는 쪽(frame_producer)과 보내는 쪽(kraken_once)이 이 판단을
    따로 하면 서로 싸운다. 실제로 보내는 쪽만 모니터를 보고 있어서, 모니터를
    끄면 보내는 쪽이 1초마다 stop_video() 로 영상을 죽이고 만드는 쪽은 그걸
    모른 채 곧바로 새로 띄웠다. 다섯 시간 동안 ffmpeg·ffplay 가 18,682번
    태어났다 죽었고, 유튜브는 그 요청 폭주를 봇으로 보고 막았다.
    """
    with lock:
        sleeps = kraken_state["lcd_off_with_monitor"]
    # ★lock 을 놓고 부른다. dark_now 가 같은 lock 을 다시 잡는다.
    return sleeps and dark_now()


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
    if dark_now():
        # 화면이 꺼졌으면 램·글카·스피커도 같이 끈다.
        for d in targets:
            if prepare_device(d, prepared, failed):
                try:
                    d.set_colors([BLACK] * len(d.leds))
                except Exception:
                    failed.add(d.id)
        return

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
    if mode == "off":
        # 검은 화면을 계속 낸다. 반복문을 멈추지 않는 이유는 dark_now 와 같다 -
        # 멈췄다 다시 시작하면 색이 튄다. 그냥 검은색을 계속 그린다.
        return effects.static(n, RGBColor(0, 0, 0))
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
    was_dark = None      # 아직 모른다. 첫 회에 한 번 맞추게 된다
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

        # ★화면이 꺼져 있으면 전부 검게. 효과는 계속 돌려 둔다 - 멈췄다가
        # 다시 시작하면 색이 튀기 때문이다. 마지막에 덮어쓰기만 한다.
        dark = dark_now()
        if dark:
            colors = [BLACK] * len(colors)

        hub.set_colors(colors)

        tick += 1
        # ★꺼지거나 켜지는 순간에는 차례를 기다리지 않고 그 자리에서 맞춘다.
        # 램·글카·스피커는 스무 번에 한 번만 갱신하는데, 그대로 두면 팬만
        # 먼저 꺼지고 나머지가 뒤늦게 따라 꺼져 우수수 꺼지는 것처럼 보인다.
        flipped = dark != was_dark
        was_dark = dark
        if sync and (flipped or tick % SYNC_EVERY == 0):
            paint_targets(safe + (ram if use_ram else []), colors,
                          prepared, failed, solid)

        with lock:
            snapshot["zones"] = zone_swatches(colors, zones)

        time.sleep(effects.DELAY)


# ------------------------------------------------------------------- 크라켄

# 영상 재생기는 한 번에 하나만 돈다. 주소가 바뀌면 옛것을 끄고 새로 켠다.
_player = {"obj": None, "url": None}
# 화면 쪽이 마지막으로 가져간 장 번호. 같은 장을 두 번 인코딩하지 않는다.
_video_seen = {"n": 0}

# ffmpeg 에게 받는 초당 장 수. LCD 에 실제로 나오던 수(2026-11-18 실측 15.0장)에
# 맞춘다. 30 으로 뽑아도 화면에는 15장만 나왔으니, 나머지 15장은 ffmpeg 이
# 크기를 바꾸고 파이프로 밀고 파이썬이 읽어서 버리기만 했다.
VIDEO_FPS = 15


def video_frame():
    """지금 틀어야 할 영상에서 지난번 뒤로 새로 나온 한 장. 0.1초 안에 없으면 None.

    재생목록을 골랐으면 그 목록을, 아니면 주소칸에 넣은 것을 튼다.
    """
    with lock:
        url = kraken_state["video_url"].strip()
        audio = kraken_state["video_audio"]
        list_id = kraken_state.get("play_list") or None

    items = playlists.urls_of(list_id) if list_id else None
    key = f"list:{list_id}:{len(items or [])}" if list_id else url

    cur = _player["obj"]
    if not key or (list_id and not items):
        stop_video()
        return None

    if cur is None or _player["url"] != key or cur.done:
        stop_video()
        cur = vid.Player(items[0] if items else url, fps=VIDEO_FPS, audio=audio, items=items)
        # 제목은 곡을 열어야 알 수 있다. 알아내는 대로 목록에 채워 넣는다.
        cur.on_title = playlists.note_title
        cur.start()
        _player.update(obj=cur, url=key)
        say(f"영상 시작: {key}")

    with lock:
        snapshot["video_title"] = cur.title
        snapshot["video_error"] = cur.error
        snapshot["video_playing"] = not cur.done and cur.frames > 0
        snapshot["video_index"] = cur.index
        snapshot["video_total"] = cur.total
    img, _video_seen["n"] = cur.wait_new(_video_seen["n"], 0.1)
    return img


# 우리가 띄우는 미디어 프로그램. 이름으로 알아본다.
MEDIA_NAMES = ("ffplay.exe", "ffmpeg.exe", "ffplay", "ffmpeg")


def sweep_media(reason=""):
    """우리 밑에 남은 ffplay/ffmpeg 를 전부 정리한다.

    ★재생기 객체가 자기 프로세스를 추적하지만, 그 객체를 놓치는 순간
    (예외로 죽거나, 교체되거나, 경쟁 상태로 늦게 태어나거나) 그 프로세스는
    영영 아무도 안 죽인다. 실제로 그렇게 남은 ffplay 가 계속 소리를 냈다.

    개별 추적은 언제든 샌다. 그래서 "내 자식 중에 미디어 프로그램이 있는데
    지금 영상을 트는 중이 아니면 죽인다"는 그물을 따로 친다. 이건 안 샌다.
    """
    killed = []
    try:
        me = psutil.Process()
        for child in me.children(recursive=True):
            try:
                if child.name() in MEDIA_NAMES:
                    child.kill()
                    killed.append(child.pid)
            except Exception:
                pass
    except Exception:
        return 0
    if killed:
        say(f"남은 소리·영상 프로그램 {len(killed)}개 정리 {reason}".strip())
    return len(killed)


def stop_video():
    """지금 틀던 것을 확실히 끊는다.

    ★멈춘 뒤에도 유령이 남을 수 있다. 곡 주소를 푸는 데 몇 초 걸리는데
    그 사이에 멈춤이 오면, 멈출 당시에는 죽일 대상이 없었고 그 뒤에 새
    프로세스가 태어난다. 그래서 잠깐 기다렸다 한 번 더 죽인다.
    """
    cur = _player["obj"]
    _player.update(obj=None, url=None)
    if cur is not None:
        try:
            cur.stop()
        except Exception:
            pass

        def sweep():
            time.sleep(6.0)      # 주소 푸는 시간보다 넉넉히
            try:
                cur.stop()
            except Exception:
                pass
            sweep_media("(늦게 태어난 것)")

        threading.Thread(target=sweep, daemon=True).start()
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
#
# ★다만 "계속"이 쉬지 않고였던 게 탈이었다. 영상은 새 장이 없어도 같은 장을
# 몇 ms 마다 다시 돌리고 자르고 인코딩해서, LCD 가 초당 15장을 받는 동안
# 이 스레드 혼자 CPU 한 코어를 썼다(2026-11-18 실측 1.12코어). 그래서
# 영상은 새 장이 나올 때만, 쉬지 않고 바뀌는 화면(회전·화면 비추기)은
# 보내는 쪽이 지난 장을 가져간 뒤에만 만든다. 만드는 데 몇 ms, 보내는 데
# 수십 ms 라 보내는 쪽은 여전히 기다리지 않는다.
_ready = {"data": None}
_ready_lock = threading.Lock()
_ready_cv = threading.Condition(_ready_lock)
_orientation = {"v": 0}

# 대시보드에 "지금 LCD 에 뭐가 나오나"를 보여주려고 마지막 그림을 들고 있는다.
# ★돌리기(fit) 전 그림을 둔다. fit 은 패널이 비뚤게 달린 것을 보정하려고
# 미리 돌려 놓는 것이라, 그걸 그대로 보여주면 화면에서는 누워 보인다.
_preview = {"img": None}


def take_frame(timeout=0.0):
    """준비된 한 장. 없으면 timeout 초까지 기다렸다가 그래도 없으면 None."""
    with _ready_cv:
        if _ready["data"] is None and timeout:
            _ready_cv.wait_for(lambda: _ready["data"] is not None, timeout)
        d = _ready["data"]
        _ready["data"] = None
        _ready_cv.notify_all()
        return d


def put_frame(data):
    with _ready_cv:
        _ready["data"] = data
        _ready_cv.notify_all()


def wait_taken(timeout):
    """보내는 쪽이 지난 장을 가져갈 때까지. LCD 가 받는 것보다 빨리 만들지 않는다."""
    with _ready_cv:
        _ready_cv.wait_for(lambda: _ready["data"] is None, timeout)


def frame_producer():
    """화면을 만들어 Q565 로 인코딩해 두는 스레드. 장치는 안 만진다."""
    import mss

    import lcd_stream as L

    sct = None
    while True:
        with lock:
            mode = kraken_state["lcd_mode"]
            box = kraken_state["mirror_box"]

        if mode == "off" or not kraken_state["enabled"] or lcd_asleep():
            # 재생기를 만드는 곳이 여기뿐이니 정리도 여기서 한다. 만드는 쪽이
            # 쉬는 줄 모르면 남이 죽인 것을 곧바로 되살리게 된다.
            if _player["obj"] is not None:
                stop_video()
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

            _preview["img"] = img
            fitted = L.fit(img, _orientation["v"])
            # 움직이는 화면은 디더를 안 쓴다. 디더가 압축을 깨서 데이터가
            # 두세 배로 불고 그만큼 느려지는데, 움직이면 띠는 잘 안 보인다.
            put_frame(L.to_q565(L.crop_circle(fitted)))
        except Exception as e:
            say(f"화면 만들기 실패: {e!r}")
            time.sleep(1.0)
            continue

        # 상태판은 1초에 한 장이면 충분하다. 영상은 video_frame 이 다음 새 장을
        # 기다린다. 쉬지 않고 바뀌는 화면은 보내는 쪽이 가져가기를 기다린다 -
        # 잠으로 맞추지 않는 건, 1ms 를 자라고 하면 윈도우가 15ms 를 자 버려
        # 리듬이 깨지기 때문이다.
        if mode in ("stats", "sync"):
            time.sleep(1.0)
        elif mode != "video":
            wait_taken(0.5)


def kraken_once(k):
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
        with lock:
            snapshot["kraken_last_read"] = dict(k.last_read)
        # 헛읽기면 이번 회차는 통째로 건너뛴다. 옛 값을 그대로 두는 게
        # 0도라는 거짓말을 믿고 펌프를 늦추는 것보다 안전하다.
        if st is None:
            kraken_once.bad_reads += 1
            with lock:
                snapshot["kraken_bad_reads"] = kraken_once.bad_reads
            return 0.0
        with lock:
            snapshot.update(kraken_ok=True, kraken_error="", kraken_status_at=time.time(),
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

    # 영상을 트는 중이 아닌데 소리가 나면 안 된다. 몇 초에 한 번 확인한다.
    now2 = time.time()
    if lcd_mode != "video" and now2 - kraken_once.last_sweep > 4.0:
        kraken_once.last_sweep = now2
        sweep_media("(영상 모드가 아님)")

    if lcd_mode == "off" or lcd_asleep():
        # 모니터가 꺼졌으면 LCD 도 쉰다. 아무도 안 보는데 초당 서른 장을
        # 보낼 이유가 없다. 다만 그렇게 할지는 따로 고를 수 있다.
        stop_video()
        return 1.0        # 화면은 장치 기본 그대로 둔다

    # 만드는 쪽이 준비해 둔 최신 한 장. 없으면 나올 때까지 잠깐 기다린다 -
    # 예전처럼 2ms 마다 다시 보러 오면 화면이 쉬는 동안에도 초당 500번 돈다.
    # 0.1초면 상태 읽기(몇 초에 한 번) 차례를 놓칠 만큼 길지 않다.
    data = take_frame(0.1)
    if data is None:
        return 0.0
    k.show_raw(data)
    # ★실제로 보낸 것만 센다. 예전에는 루프가 돈 횟수를 세는 바람에
    # 보낼 게 없어 헛도는 것까지 세서 "초당 200장" 같은 거짓말이 나왔다.
    kraken_once.sent += 1
    return 0.0


kraken_once.last_poll = 0.0
kraken_once.last_pump = None
kraken_once.bad_reads = 0
kraken_once.sent = 0
kraken_once.last_sweep = 0.0


def kraken_loop():
    """끊겨도 계속 되살아나는 바깥 루프. 조명 쪽과 같은 구조다."""
    kraken_loop.fails = getattr(kraken_loop, "fails", 0)

    while True:
        if not kraken_state["enabled"]:
            time.sleep(3)
            continue
        try:
            with kr.Kraken() as k:
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
                    nap = kraken_once(k)
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
        "monitor": monitor.snapshot() if monitor else {"ok": False, "on": True},
        "parts": parts.snapshot(),
        "playlists": playlists.snapshot(),
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
            "last_read": snap["kraken_last_read"],
            "status_age": (round(time.time() - snap["kraken_status_at"], 1)
                           if snap["kraken_status_at"] else None),
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
            kraken_state["play_list"] = None    # 주소를 직접 넣으면 목록은 푼다
        if "play_list" in data:
            kraken_state["play_list"] = data["play_list"] or None
        if "video_audio" in data:
            kraken_state["video_audio"] = bool(data["video_audio"])
        if "lcd_mode" in data and data["lcd_mode"] in ("off", "stats", "sync", "mirror", "video", "spin"):
            kraken_state["lcd_mode"] = data["lcd_mode"]
        if "mirror_box" in data:
            kraken_state["mirror_box"] = int(max(200, min(1440, int(data["mirror_box"]))))
        if "lcd_off_with_monitor" in data:
            kraken_state["lcd_off_with_monitor"] = bool(data["lcd_off_with_monitor"])
        st = dict(kraken_state)
    remember()
    # 손으로 정한 값은 다음 한 바퀴를 기다리지 말고 바로 반영되게 한다.
    kraken_once.last_pump = None
    if ("video_url" in data or "play_list" in data
            or data.get("lcd_mode") not in (None, "video")):
        stop_video()
    return jsonify({"ok": True, "state": st})


@app.route("/api/playlist", methods=["POST"])
def api_playlist():
    """재생목록을 만들고 고친다.

    {"action":"create","name":"작업용"}
    {"action":"rename","id":...,"name":...}   {"action":"delete","id":...}
    {"action":"add","id":"queue"|목록id,"url":...}
    {"action":"remove","id":...,"index":0}    {"action":"move","id":...,"index":0,"step":-1}
    {"action":"clear_queue"}                  {"action":"play","id":...}
    """
    d = request.get_json(force=True, silent=True) or {}
    act = d.get("action")
    lid = d.get("id")
    with lock:
        if act == "create":
            _, msg = playlists.create(d.get("name"))
        elif act == "rename":
            _, msg = playlists.rename(lid, d.get("name"))
        elif act == "delete":
            _, msg = playlists.delete(lid)
        elif act == "add":
            _, msg = playlists.add(lid, d.get("url"), d.get("title"))
        elif act == "remove":
            _, msg = playlists.remove(lid, int(d.get("index", -1)))
        elif act == "move":
            _, msg = playlists.move(lid, int(d.get("index", -1)), int(d.get("step", 0)))
        elif act == "clear_queue":
            _, msg = playlists.clear_queue()
        elif act == "play":
            playlists.set_playing(lid)
            kraken_state["play_list"] = lid
            kraken_state["lcd_mode"] = "video"
            msg = "재생 시작"
        else:
            return jsonify({"ok": False, "message": "무슨 동작인지 모르겠어"})
    if act == "play":
        stop_video()
    return jsonify({"ok": True, "message": msg, "playlists": playlists.snapshot()})


@app.route("/api/lcd.jpg")
def api_lcd_preview():
    """지금 LCD 에 나가는 그림을 작게 줄여서 준다.

    매 프레임 만들지 않고 물어볼 때만 만든다. 대시보드는 초당 몇 번만
    가져가므로, 화면 보내는 일에 부담을 주지 않는다.
    """
    import io as _io

    img = _preview["img"]
    if img is None:
        return ("", 204)
    try:
        small = img.convert("RGB").resize((220, 220))
        buf = _io.BytesIO()
        small.save(buf, format="JPEG", quality=72)
        return app.response_class(
            buf.getvalue(), mimetype="image/jpeg",
            headers={"Cache-Control": "no-store"})
    except Exception:
        return ("", 204)


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
            want = str(data["mode"])
            # 끄기 직전에 뭘 켜고 있었는지 적어 둔다. 트레이의 "조명 켜기"가
            # 이걸 보고 원래 효과로 돌아간다. 안 그러면 켤 때마다 기본값이
            # 되어서, 껐다 켜는 것만으로 고른 효과가 날아간다.
            if want == "off" and state["mode"] != "off":
                state["resume_mode"] = state["mode"]
            state["mode"] = want
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
        if "off_with_monitor" in data:
            state["off_with_monitor"] = bool(data["off_with_monitor"])
        st = dict(state)
    remember()
    return jsonify({"ok": True, "state": st})


LOG = Path(__file__).with_name("dashboard.log")


# pythonw 로 띄우면 콘솔이 없어서, 죽어도 이유가 아무데도 안 남는다.
# 실제로 한 번 조용히 죽어서 조명이 멈춘 적이 있다. 그래서 파이썬이
# 터질 때의 스택까지 이 파일로 받는다. 넘치면 log.py 가 지난 판으로
# 밀어내므로 무한히 자라지 않는다.
say = log_mod.writer(LOG, capture_stderr=True)


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
    # 브라우저가 0.5초마다 상태를 물어서, 그냥 두면 로그가 접속 기록으로
    # 도배된다. 정작 조명이 왜 멈췄는지는 그 사이에 묻힌다.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    say("=== 대시보드 시작 ===" + ("" if sharpen_timer() else " (타이머 해상도 못 올림)"))

    light, kr_saved = restore()
    if light or kr_saved:
        say(f"지난 설정 되돌림: {light.get('mode', '?')}"
            f" #{light.get('color', '?')} / LCD {kr_saved.get('lcd_mode', '?')}")
    else:
        say("지난 설정이 없어 기본값으로 시작한다")

    global monitor
    monitor = display_mod.Monitor(
        on_change=lambda on: say("모니터 " + ("켜짐" if on else "꺼짐 - 조명 끔"))).start()

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
