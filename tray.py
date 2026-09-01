"""트레이 아이콘. 이 프로그램이 전체의 주인이다.

    python tray.py           준비부터 다 한다 (평소 이것)
    python tray.py --attach  이미 돌고 있는 대시보드에 붙기만 한다

무엇을 하나
    1. 준비를 시킨다 - 다른 조명 프로그램을 끄고 OpenRGB 서버를 띄운다
       (start_all.ps1 -PrepOnly 를 그대로 쓴다. 준비 절차가 두 벌이 되면
        한쪽만 고치는 일이 생긴다)
    2. 대시보드를 자기 자식으로 띄운다
    3. 트레이에 앉아서 상태를 보여주고 명령을 받는다
    4. 끝내기를 누르면 대시보드도 같이 끈다

왜 자식으로 띄우나
    아이콘이 있다 = 켜져 있다, 아이콘을 끄면 = 꺼진다. 이게 성립하려면
    대시보드의 목숨을 트레이가 쥐고 있어야 한다. 따로 띄워 놓고 신호만
    주고받으면, 트레이를 꺼도 대시보드가 남아 조명이 계속 돌아간다.

관리자 권한
    OpenRGB 가 램(SMBus)을 보려면 관리자여야 한다. tray.bat 이 권한을
    올려서 이 파일을 부른다. 자식은 부모의 권한을 물려받으므로 대시보드도
    관리자가 된다.
"""

import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:5000"
LOG = HERE / "tray.log"

# 대시보드가 뜨는 데 걸리는 시간. 장치를 다 잡을 때까지 기다린다.
BOOT_WAIT = 40
POLL_SECONDS = 3.0

MODES = [
    ("ice", "아이스"), ("wave", "물결"), ("rainbow", "순환"),
    ("breathe", "숨쉬기"), ("static", "고정"), ("soft", "은은"),
    ("depth", "깊이"), ("screen", "화면 따라"),
    ("pulse", "소리 · 출렁"), ("vu", "소리 · 레벨"), ("spectrum", "소리 · 대역색"),
]

LCD_MODES = [
    ("stats", "수온 · 온도"), ("mirror", "모니터 미러링"),
    ("video", "영상"), ("sync", "조명 색"), ("off", "끄기"),
]


def say(msg):
    line = f"{time.strftime('%m-%d %H:%M:%S')}  {msg}"
    print(line)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ 대시보드와 이야기


def get_state(timeout=2.0):
    """지금 상태. 대시보드가 안 떠 있으면 None."""
    try:
        with urllib.request.urlopen(BASE + "/api/state", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def post(path, payload):
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            BASE + path, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=4.0) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        say(f"명령 실패 {path}: {e}")
        return None


def alive():
    return get_state(timeout=1.0) is not None


# ------------------------------------------------------------------ 아이콘 그림


def make_icon(hexcolor=None, dark=False):
    """색 동그라미 하나. 꺼져 있으면 회색 테두리만.

    윈도우 트레이는 작아서(보통 16~24픽셀) 그림을 줄여 보여준다. 크게 그려
    두면 알아서 곱게 줄어든다.
    """
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 6
    box = (pad, pad, size - pad, size - pad)

    if hexcolor is None:
        # 대시보드가 안 떠 있다. 속이 빈 회색 동그라미.
        d.ellipse(box, outline=(130, 130, 130, 255), width=6)
        return img

    try:
        c = hexcolor.lstrip("#")
        rgb = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except Exception:
        rgb = (155, 215, 255)

    if dark:
        # 조명이 꺼진 상태. 무슨 색인지는 테두리로만 남긴다.
        d.ellipse(box, outline=rgb + (255,), width=5)
    else:
        d.ellipse(box, fill=rgb + (255,))
    return img


# ------------------------------------------------------------------ 앱


class Tray:
    def __init__(self, attach=False):
        self.attach = attach          # 남이 띄운 것에 붙기만 하는가
        self.child = None             # 내가 띄운 대시보드
        self.state = None
        self.stopping = False
        self.icon = pystray.Icon("rgb-control", make_icon(),
                                 "RGB 제어 (시작하는 중)", self.menu())

    # ---------------------------------------------------------- 켜고 끄기

    def prepare(self):
        """다른 조명 프로그램을 끄고 OpenRGB 서버를 띄운다."""
        say("준비 시작 (다른 조명 프로그램 종료 · OpenRGB)")
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(HERE / "start_all.ps1"), "-PrepOnly"],
                cwd=str(HERE), timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            say(f"준비 중 문제: {e}")

    def start_backend(self):
        """대시보드를 자식으로 띄운다."""
        if alive():
            # 이미 누가 띄워 놨다. 포트를 두고 다투면 새로 뜬 쪽이 조용히
            # 죽으므로, 그냥 그것을 쓴다.
            say("이미 돌고 있는 대시보드를 찾았다 - 그것을 쓴다")
            self.attach = True
            return

        self.prepare()
        # pythonw 는 검은 창을 안 만든다.
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        runner = str(pyw if pyw.exists() else exe)
        say(f"대시보드 띄움: {runner}")
        self.child = subprocess.Popen(
            [runner, "dashboard.py"], cwd=str(HERE),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def stop_backend(self):
        """내가 띄운 대시보드를 끈다. 남의 것은 안 건드린다."""
        if self.child is None:
            return
        say("대시보드 종료")
        try:
            self.child.terminate()
            self.child.wait(timeout=8)
        except Exception:
            try:
                self.child.kill()
            except Exception:
                pass
        self.child = None

    # ---------------------------------------------------------- 메뉴

    def lights_on(self):
        """지금 조명이 켜져 있나. 상태를 못 읽으면 켜진 것으로 본다."""
        s = self.state
        return not (s and s.get("state", {}).get("mode") == "off")

    def toggle_lights(self):
        s = self.state or {}
        cur = s.get("state", {})
        if cur.get("mode") == "off":
            post("/api/effect", {"mode": cur.get("resume_mode") or "ice"})
        else:
            post("/api/effect", {"mode": "off"})
        self.refresh(soon=True)

    def set_mode(self, mode):
        post("/api/effect", {"mode": mode})
        self.refresh(soon=True)

    def set_lcd(self, mode):
        post("/api/kraken", {"lcd_mode": mode})
        self.refresh(soon=True)

    def open_web(self):
        webbrowser.open(BASE)

    def quit(self):
        self.stopping = True
        self.stop_backend()
        self.icon.stop()

    def status_lines(self):
        """메뉴 맨 위에 보여줄 지금 상태. 누를 수 없는 줄이다."""
        s = self.state
        if not s:
            return ["대시보드가 응답하지 않음"]
        k = s.get("kraken", {})
        mon = s.get("monitor", {})
        light = s.get("state", {})
        name = dict(MODES).get(light.get("mode"), light.get("mode", "?"))
        if light.get("mode") == "off":
            name = "꺼짐"
        out = [f"조명   {name}  #{light.get('color', '?')}"]
        if k.get("ok"):
            liquid = k.get("liquid")
            out.append(f"수온   {liquid:.1f}도" if isinstance(liquid, (int, float))
                       else "수온   읽는 중")
            out.append(f"펌프   {k.get('pump_duty', '?')}%"
                       f"  ({k.get('pump_rpm', '?')} rpm)")
            lcd = dict(LCD_MODES).get(k.get("state", {}).get("lcd_mode"), "?")
            out.append(f"LCD    {lcd}")
        else:
            out.append("크라켄  안 붙음")
        out.append("모니터 " + ("켜짐" if mon.get("on", True) else "꺼짐 (조명 끔)"))
        return out

    def menu(self):
        def status_items():
            for line in self.status_lines():
                yield pystray.MenuItem(line, None, enabled=False)

        return pystray.Menu(
            pystray.MenuItem("대시보드 열기", lambda: self.open_web(), default=True),
            pystray.Menu.SEPARATOR,
            # 지금 상태. 메뉴를 열 때마다 다시 만들어진다.
            pystray.MenuItem("상태", pystray.Menu(lambda: status_items())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("조명 켜기 / 끄기", lambda: self.toggle_lights(),
                             checked=lambda item: self.lights_on()),
            pystray.MenuItem("효과", pystray.Menu(lambda: (
                pystray.MenuItem(
                    label, (lambda m: lambda: self.set_mode(m))(key),
                    checked=(lambda m: lambda item: (
                        self.state or {}).get("state", {}).get("mode") == m)(key),
                    radio=True)
                for key, label in MODES))),
            pystray.MenuItem("LCD 화면", pystray.Menu(lambda: (
                pystray.MenuItem(
                    label, (lambda m: lambda: self.set_lcd(m))(key),
                    checked=(lambda m: lambda item: (
                        self.state or {}).get("kraken", {}).get(
                            "state", {}).get("lcd_mode") == m)(key),
                    radio=True)
                for key, label in LCD_MODES))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("끝내기 (조명도 끔)", lambda: self.quit()),
        )

    # ---------------------------------------------------------- 상태 갱신

    def refresh(self, soon=False):
        if soon:
            # 방금 보낸 명령이 반영될 틈을 준다.
            threading.Timer(0.4, self._refresh_once).start()
        else:
            self._refresh_once()

    def _refresh_once(self):
        s = get_state()
        self.state = s
        if s is None:
            self.icon.icon = make_icon(None)
            self.icon.title = "RGB 제어 — 대시보드가 응답하지 않음"
            return
        light = s.get("state", {})
        dark = light.get("mode") == "off" or not s.get("monitor", {}).get("on", True)
        self.icon.icon = make_icon(light.get("color", "9bd7ff"), dark)

        k = s.get("kraken", {})
        liquid = k.get("liquid")
        bits = ["RGB 제어"]
        if isinstance(liquid, (int, float)):
            bits.append(f"수온 {liquid:.1f}도")
        bits.append("조명 " + ("꺼짐" if light.get("mode") == "off" else "켜짐"))
        # 트레이 풍선말은 128자까지만 보여준다. 넘칠 일은 없지만 줄여 둔다.
        self.icon.title = " · ".join(bits)[:127]

    def watch(self):
        """대시보드가 뜨기를 기다렸다가, 계속 상태를 살핀다."""
        for _ in range(BOOT_WAIT):
            if self.stopping:
                return
            if alive():
                say("대시보드 붙음")
                break
            time.sleep(1)
        else:
            say("대시보드가 시간 안에 안 떴다")

        while not self.stopping:
            self._refresh_once()
            # 내가 띄운 대시보드가 죽었으면 아이콘으로 알린다. 되살리지는
            # 않는다 - 왜 죽었는지 모르는 채로 다시 띄우면 같은 실패를
            # 무한히 되풀이한다.
            if self.child is not None and self.child.poll() is not None:
                say(f"대시보드가 스스로 죽었다 (코드 {self.child.returncode})")
                self.child = None
            time.sleep(POLL_SECONDS)

    def run(self):
        if not self.attach:
            self.start_backend()
        threading.Thread(target=self.watch, daemon=True).start()
        self.icon.run()
        # icon.run 은 끝내기를 누를 때까지 안 돌아온다.
        self.stopping = True
        self.stop_backend()


def main():
    # 자식 프로세스와 로그가 한글을 잃지 않게 한다.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    say("=== 트레이 시작 ===")
    Tray(attach="--attach" in sys.argv).run()
    say("=== 트레이 끝 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
