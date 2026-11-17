"""NZXT Kraken Elite 제어 - 냉각과 화면을 한 곳에서.

    python kraken.py status          지금 상태 보기
    python kraken.py pump 80         펌프를 80%로 고정
    python kraken.py curve           수온에 따라 자동으로 (기본 곡선)
    python kraken.py watch           1초마다 상태를 찍어 보여주기

★장치를 잡을 수 있는 것은 한 프로그램뿐이다
    NZXT CAM 이 켜져 있으면 열 수 없다. 그리고 우리 쪽에서도 화면(LCD)과
    냉각을 서로 다른 프로세스가 만지면 안 된다. 그래서 이 파일의 Kraken
    클래스가 연결을 하나만 들고, 화면도 냉각도 그것을 통해서 한다.

펌프를 함부로 낮추지 마라
    수랭은 펌프가 멈추면 열이 안 빠진다. liquidctl 이 알려주는 하한이 20%
    지만 그건 장치가 받는 값일 뿐 안전한 값이 아니다. 여기서는 PUMP_FLOOR
    아래로는 절대 안 내려간다.
"""

import sys
import threading
import time

from liquidctl.error import Timeout

import owner
import lcd
import lcd_stream as L

# 펌프를 이 아래로는 내리지 않는다. 조용하게 만들자고 냉각을 포기할 수는 없다.
PUMP_FLOOR = 60
PUMP_CEIL = 100

# 수온(°C) -> 펌프 세기(%). 사이 값은 직선으로 잇는다.
# 지금 이 시스템은 가만히 둬도 수온이 50도 근처라 그 구간을 촘촘히 잡았다.
DEFAULT_CURVE = [(35, 60), (45, 70), (50, 85), (55, 100)]

# 상태를 읽는 간격.
# ★읽는 동안에는 화면이 멈춘다. 자주 읽을수록 눈에 띄는 멈칫이 잦아진다.
# 수온은 몇 초 사이에 크게 안 변하므로 넉넉히 잡는다.
POLL_SECONDS = 4.0

# 이 범위를 벗어난 수온은 헛읽기로 보고 버린다. 물이 얼거나 끓지는 않는다.
# ★위쪽은 끓는점이다. 80 으로 잡았을 때는, 상태 응답이 맞는데도 80 을 넘는
# 수온을 헛읽기로 버려서 정말 뜨거워져도 아무도 못 보게 돼 있었다.
LIQUID_MIN = 5.0
LIQUID_MAX = 100.0

# 상태 응답의 보고 번호. LCD 전송의 대답(ack)도 같은 HID 통로로 오는데, 늦게
# 온 대답이 큐를 비운 뒤에 도착하면 liquidctl 은 그것을 상태로 읽는다(첫 장만
# 보고 번호를 안 본다). 그 바이트가 수온·rpm 자리에 들어가 헛읽기가 된다.
STATUS_REPLY = 0x75
STATUS_READ_TRIES = 8

# ★화면 보내는 속도 상한 - 이제 거의 쓸 일이 없다.
#
# 전송 한 장을 단계별로 재보니 이랬다 (11KB 짜리와 48KB 짜리가 거의 같다):
#     시작 명령          2.0 ms
#     데이터 밀어넣기    1.1 ~ 3.4 ms   <- 데이터 크기는 병목이 아니었다
#     끝 명령의 대답    18.6 ~ 20.4 ms  <- 여기서 다 먹는다
# 장치가 "한 장 다 받았다"고 대답하는 데 20ms 가 고정으로 든다. 그래서
# 아무리 서둘러도 초당 40장쯤이 천장이다. 즉 장치가 스스로 제동을 건다.
#
# 우리가 sleep 으로 또 막으면 오히려 해롭다. ★윈도우의 sleep 은 기본
# 해상도가 약 15.6ms 라, 1ms 를 자라고 해도 15ms 를 잔다. 그 들쭉날쭉함이
# 눈에는 "멈칫거림"으로 보인다. 그래서 상한을 천장 위로 올려 사실상 끈다.
LCD_MAX_FPS = 120

# 상태를 읽은 직후에는 잠깐 쉰다. HID 응답이 아직 오가는 중에 큰 덩어리를
# 밀어넣으면 서로 엉킨다.
SETTLE_AFTER_STATUS = 0.015


def interpolate(curve, x):
    """곡선 위의 값 하나. 양 끝을 벗어나면 끝값으로 잡는다."""
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0
            return y0 + (y1 - y0) * t
    return curve[-1][1]


class Kraken:
    """크라켄 연결 하나를 들고 냉각과 화면을 모두 맡는다.

    with 문으로 쓰면 끝날 때 화면을 장치 기본으로 되돌리고 USB 를 놓는다.
    그걸 안 하면 마지막 화면이 얼어붙고 CAM 도 장치를 못 가져간다.
    """

    def __init__(self):
        self.dev = None
        self.ctx = None
        self.stream = None
        self.orientation = 0
        self.lock = threading.Lock()
        self._last_show = 0.0
        self._min_gap = 1.0 / LCD_MAX_FPS
        self.fast = True
        # 마지막 상태 읽기에서 실제로 받은 것. 버린 회차도 왜 버렸는지 남긴다 -
        # 값이 없으면 "장치가 이상한지, 우리가 잘못 읽는지"를 가를 수 없다.
        self.last_read = {}

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def open(self):
        self.dev = lcd.get_kraken()
        self.ctx = self.dev.connect()
        self.ctx.__enter__()
        return self

    def close(self):
        if self.dev is not None:
            try:
                self.dev._delete_all_buckets()
            except Exception:
                pass
        if self.ctx is not None:
            try:
                self.ctx.__exit__(None, None, None)
            except Exception:
                pass
        self.dev = self.ctx = self.stream = None

    # ------------------------------------------------------------- 냉각

    def status(self):
        """수온·펌프·팬을 읽어 알아보기 쉬운 이름으로 돌려준다.

        ★믿을 수 없는 값이면 None 을 돌려준다.
        화면을 초당 몇십 장씩 보내는 중에 상태를 읽으면, 장치가 아직 안
        치운 옛 응답을 집어 와서 수온이 0.0 으로 읽히는 일이 있다. 그걸
        그대로 믿으면 "차가우니 펌프를 줄여도 되겠다"고 판단해 버린다.
        실제로는 뜨거운데 펌프를 늦추는 것이라 위험하다.
        그래서 물리적으로 말이 되는 범위를 벗어나면 그 회차를 버린다.
        """
        skipped = []
        msg = None
        with self.lock:
            # liquidctl 의 get_status 와 같은 요청·같은 자리지만, 보고 번호가
            # 상태인 것만 받는다. 앞에 낀 다른 대답은 건너뛴다.
            self.dev.device.clear_enqueued_reports()
            self.dev._write([0x74, 0x01])
            try:
                for _ in range(STATUS_READ_TRIES):
                    m = self.dev._read()
                    if m and m[0] == STATUS_REPLY:
                        msg = m
                        break
                    skipped.append(bytes(m[:2]).hex(" ") if m else "-")
            except Timeout:
                # 대답이 5초 안에 안 온 것은 상태 한 번을 못 읽은 것뿐이다. 끊김으로
                # 올려 보내면 바깥 루프가 장치를 닫았다 다시 열고 화면까지 끊는다.
                skipped.append("5초 무응답")
            # 읽고 나서 바로 큰 덩어리를 밀어넣으면 통로가 엉킨다.
            time.sleep(SETTLE_AFTER_STATUS)
        read = {"at": time.time(), "skipped": skipped}
        self.last_read = read
        if msg is None:
            read["why"] = f"상태 응답이 {STATUS_READ_TRIES}번 안에 안 옴"
            return None
        out = {
            "liquid": msg[15] + msg[16] / 10,
            "pump_rpm": msg[18] << 8 | msg[17],
            "pump_duty": msg[19],
            "fan_rpm": msg[24] << 8 | msg[23],
            "fan_duty": msg[25],
        }
        read.update(out, reply=bytes(msg[:2]).hex(" "))

        if msg[15:17] == [0xFF, 0xFF]:
            read["why"] = "장치가 수온을 못 읽음(FF FF, liquidctl 이 펌웨어 고장으로 보는 값)"
            return None
        if not (LIQUID_MIN <= out["liquid"] <= LIQUID_MAX):
            read["why"] = "수온이 말이 안 되는 범위"
            return None
        # 펌프가 돌고 있는데 0 rpm 으로 읽히는 것도 같은 종류의 헛읽기다.
        if out["pump_rpm"] <= 0:
            read["why"] = "펌프 0 rpm"
            return None
        return out

    def set_pump(self, duty):
        """펌프 세기를 정한다. 안전 하한 아래로는 안 내려간다."""
        duty = int(max(PUMP_FLOOR, min(PUMP_CEIL, duty)))
        with self.lock:
            self.dev.set_fixed_speed("pump", duty)
        return duty

    def set_fan(self, duty):
        """크라켄에 직접 물린 팬. 지금 이 시스템에는 아무것도 안 물려 있어
        (0 rpm) 사실상 쓸 일이 없지만, 나중에 꽂으면 바로 쓴다."""
        duty = int(max(0, min(100, duty)))
        with self.lock:
            self.dev.set_fixed_speed("fan", duty)
        return duty

    # ------------------------------------------------------------- 화면

    def screen_ready(self):
        """화면을 쓰기 전에 한 번만 준비한다. bulk 통로와 화면 방향."""
        if self.stream is None:
            if not self.dev.bulk_device:
                self.dev.bulk_device = lcd.find_bulk()
            self.orientation = L.read_orientation(self.dev)
            self.stream = L.Stream(self.dev)
            try:
                import q565_rust  # noqa: F401
                self.fast = True
            except ImportError:
                # 옛 방식으로도 그림은 나온다. 다만 오래 쓰면 장치가 상한다.
                self.fast = False
        return self.stream

    def show_raw(self, data):
        """이미 Q565 로 만들어진 바이트를 그대로 보낸다.

        만드는 일(캡처·인코딩)은 다른 스레드가 미리 해 둔다. 이 함수는
        보내기만 하므로 장치가 쉬는 시간이 없다. 예전에는 한 스레드가
        캡처하고 인코딩하고 보내고 상태까지 읽어서, 보내지 않는 동안
        화면이 그대로 멈춰 있었다. 그게 "끊긴다"의 정체였다.
        """
        now = time.time()
        wait = self._min_gap - (now - self._last_show)
        if wait > 0:
            time.sleep(wait)
        self.screen_ready()
        with self.lock:
            L.send_fast(self.dev, data, L.KIND_Q565)
        self._last_show = time.time()
        return True

    def show(self, img):
        """PIL 이미지 한 장을 화면에 띄운다.

        기본은 빠른 경로(Q565)다. 버킷 방식보다 빠르고, 무엇보다 HID 통로를
        안 망가뜨린다. q565_rust 가 없으면 옛 방식으로 물러난다.

        화면이 둥그니 원 바깥은 검게 만든다. 어차피 안 보이는 자리이고,
        검게 채우면 압축이 잘 돼 데이터가 20% 가까이 줄어든다.
        """
        now = time.time()
        wait = self._min_gap - (now - self._last_show)
        if wait > 0:
            time.sleep(wait)

        st = self.screen_ready()
        fitted = L.fit(img, self.orientation)
        with self.lock:
            if self.fast:
                L.send_fast(self.dev, L.to_q565(L.crop_circle(fitted)), L.KIND_Q565)
            else:
                st.send(L.to_gif(fitted))
        self._last_show = time.time()
        return True


def cmd_status(k):
    s = None
    for _ in range(5):          # 헛읽기가 섞이면 몇 번 더 물어본다
        s = k.status()
        if s:
            break
        time.sleep(0.3)
    if not s:
        print("  상태를 못 읽었다 (헛읽기만 돌아옴)")
        return
    print(f"  수온       {s.get('liquid', 0):.1f} °C")
    print(f"  펌프       {s.get('pump_rpm', 0)} rpm  ({s.get('pump_duty', 0)}%)")
    fan_rpm = s.get("fan_rpm", 0)
    note = "  <- 크라켄에 직접 물린 팬 없음" if fan_rpm == 0 else ""
    print(f"  팬         {fan_rpm} rpm  ({s.get('fan_duty', 0)}%){note}")


def cmd_watch(k, seconds=30):
    print("수온에 따라 펌프가 어떻게 움직여야 하는지 같이 보여준다.")
    print("(보기만 한다. 실제로 바꾸지는 않는다)\n")
    end = time.time() + seconds
    while time.time() < end:
        s = k.status()
        if not s:
            time.sleep(0.5)
            continue
        t = s["liquid"]
        want = interpolate(DEFAULT_CURVE, t)
        print(f"\r  수온 {t:5.1f}°C   펌프 {s.get('pump_rpm',0):5d}rpm "
              f"({s.get('pump_duty',0):3d}%)   곡선이 원하는 값 {want:.0f}%   ",
              end="", flush=True)
        time.sleep(1.0)
    print()


def cmd_curve(k, seconds=None):
    print("수온을 따라 펌프를 맞춘다. 멈추려면 Ctrl+C\n")
    last = None
    end = time.time() + seconds if seconds else None
    try:
        while end is None or time.time() < end:
            s = k.status()
            if not s:
                time.sleep(0.5)
                continue
            t = s["liquid"]
            want = int(round(interpolate(DEFAULT_CURVE, t)))
            # 1~2% 흔들릴 때마다 명령을 보내면 장치를 괴롭히기만 한다.
            if last is None or abs(want - last) >= 3:
                applied = k.set_pump(want)
                last = applied
                print(f"  수온 {t:.1f}°C -> 펌프 {applied}%")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\n멈춤")


def main():
    owner.require_free("크라켄을 직접 만지기")
    args = sys.argv[1:]
    cmd = args[0] if args else "status"

    try:
        with Kraken() as k:
            if cmd == "status":
                cmd_status(k)
            elif cmd == "watch":
                cmd_watch(k, float(args[1]) if len(args) > 1 else 30)
            elif cmd == "curve":
                cmd_curve(k, float(args[1]) if len(args) > 1 else None)
            elif cmd == "pump":
                if len(args) < 2:
                    print("몇 %로 할지 알려줘. 예: python kraken.py pump 80")
                    return 1
                print(f"펌프를 {k.set_pump(float(args[1]))}% 로 맞췄다")
            else:
                print(__doc__)
                return 1
    except Exception as e:
        print(f"실패: {e!r}")
        print("CAM 이 켜져 있으면 cam_off_quiet.bat 으로 먼저 내려줘.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
