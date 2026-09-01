"""스피커로 나가는 소리를 읽어 세기와 주파수 대역을 뽑는다.

마이크가 아니라 '루프백'을 쓴다. 실제로 재생 중인 소리를 그대로 따오므로
방 안 소음이나 목소리에 반응하지 않는다.

대시보드가 이 모듈을 백그라운드 스레드로 돌리고, 이펙트는 최신 값만 읽는다.
소리 읽기와 색 칠하기를 한 스레드에서 하면 서로를 기다리느라 둘 다 끊긴다.
"""

import threading
import time

import numpy as np

SAMPLE_RATE = 48000
BLOCK = 1024          # 한 번에 읽는 표본 수. 작을수록 반응이 빠르고 잡음이 는다.

# 사람이 음악에서 구분해 듣는 세 덩어리. 경계는 귀에 맞춰 잡았다.
BANDS = [
    ("low", 20, 250),      # 킥, 베이스
    ("mid", 250, 2000),    # 보컬, 스네어
    ("high", 2000, 16000),  # 하이햇, 심벌
]


class AudioLevel:
    """루프백에서 계속 읽으며 최신 세기를 들고 있는다.

    값은 0~1로 정규화한다. 절대 크기는 곡마다 달라서 그대로 쓰면
    조용한 곡에서 아예 안 움직인다. 그래서 최근 최대값 기준으로 맞춘다.
    """

    def __init__(self, device_name=None, decay=0.997, attack=0.5, release=0.12):
        self.device_name = device_name
        self.decay = decay        # 기준 최대값이 서서히 내려오는 속도
        self.attack = attack      # 커질 때 따라가는 속도 (빠르게)
        self.release = release    # 작아질 때 따라가는 속도 (천천히)

        self.level = 0.0
        self.bands = {name: 0.0 for name, _, _ in BANDS}
        self.peak = 1e-4
        self.ok = False
        self.error = ""

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return {
                "ok": self.ok,
                "error": self.error,
                "level": self.level,
                "bands": dict(self.bands),
            }

    def _pick_device(self):
        import soundcard as sc

        loopbacks = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
        if not loopbacks:
            raise RuntimeError("루프백 장치를 찾지 못했다")

        if self.device_name:
            for m in loopbacks:
                if self.device_name.lower() in m.name.lower():
                    return m

        # 기본 스피커와 이름이 같은 루프백을 고른다. 지금 소리가 나는 곳이다.
        try:
            want = sc.default_speaker().name.lower()
            for m in loopbacks:
                if m.name.lower() == want:
                    return m
        except Exception:
            pass
        return loopbacks[0]

    def _run(self):
        try:
            mic = self._pick_device()
        except Exception as e:
            with self._lock:
                self.ok, self.error = False, str(e)
            return

        # 대역별로 FFT 결과의 어느 칸을 볼지 미리 계산해 둔다.
        freqs = np.fft.rfftfreq(BLOCK, 1.0 / SAMPLE_RATE)
        slices = [(name, (freqs >= lo) & (freqs < hi)) for name, lo, hi in BANDS]
        window = np.hanning(BLOCK)

        try:
            with mic.recorder(samplerate=SAMPLE_RATE, blocksize=BLOCK) as rec:
                with self._lock:
                    self.ok, self.error = True, ""
                while not self._stop.is_set():
                    data = rec.record(numframes=BLOCK)
                    mono = data.mean(axis=1) if data.ndim > 1 else data
                    if len(mono) < BLOCK:
                        continue
                    self._update(mono[:BLOCK] * window, slices)
        except Exception as e:
            with self._lock:
                self.ok, self.error = False, str(e)

    def _update(self, block, slices):
        spec = np.abs(np.fft.rfft(block))

        rms = float(np.sqrt(np.mean(block ** 2)))
        self.peak = max(rms, self.peak * self.decay, 1e-5)
        target = min(1.0, rms / self.peak)

        raw = {}
        for name, sel in slices:
            v = float(spec[sel].mean()) if sel.any() else 0.0
            raw[name] = v
        total = max(sum(raw.values()), 1e-9)

        with self._lock:
            # 커질 땐 빨리, 작아질 땐 천천히. 그래야 박자가 살고 안 깜빡인다.
            k = self.attack if target > self.level else self.release
            self.level += (target - self.level) * k
            for name in raw:
                # 대역은 서로의 비율로 본다. 전체 볼륨이 변해도 색이 안 튄다.
                t = raw[name] / total
                cur = self.bands[name]
                kk = self.attack if t > cur else self.release
                self.bands[name] = cur + (t - cur) * kk


def main():
    """혼자 돌려보며 값이 실제로 움직이는지 확인한다."""
    import sys

    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    a = AudioLevel()
    a.start()
    time.sleep(1.0)

    s = a.snapshot()
    if not s["ok"]:
        print("소리를 못 읽는다:", s["error"])
        return 1

    print("소리 읽는 중. 음악을 틀어봐.\n")
    end = time.time() + seconds
    while time.time() < end:
        s = a.snapshot()
        lv = s["level"]
        b = s["bands"]
        bar = "#" * int(lv * 40)
        print(f"\r  세기 {lv:4.2f} |{bar:<40}| "
              f"저 {b['low']:4.2f}  중 {b['mid']:4.2f}  고 {b['high']:4.2f}",
              end="", flush=True)
        time.sleep(0.05)
    a.stop()
    print("\n\n끝.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
