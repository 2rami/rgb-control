"""Kraken Elite(0x300C) LCD 연속 전송.

    python lcd_stream.py image 그림.png       한 장 띄우기
    python lcd_stream.py bench 그림.png 40    속도 측정

왜 이 방식인가
--------------
이 장치에는 버킷을 안 거치는 '빠른 메모리' 경로가 있다.
    [0x36,0x01,0x00,0x01,0x06]  생 RGB565   <- 0x300E 전용
    [0x36,0x01,0x00,0x01,0x08]  Q565 압축   <- 0x300C(우리 것)
0x06 을 우리 장치에 보내면 전송은 100% 성공하는데 화면에 안 그려진다.
받아주기만 하고 무시한다. 우리 것이 원하는 0x08 은 Q565 압축 형식인데,
그 코덱은 파이썬 패키지로 없다(pip 에 q565, q565_rust 둘 다 없음).

그래서 화면에 확실히 나오는 버킷 경로를 쓰되, 느린 부분만 걷어냈다.
liquidctl 은 프레임마다 버킷 16개를 일일이 조회하는데(HID 왕복 16번)
이게 111ms 를 먹는다. 배치를 우리가 정해 두면 조회가 통째로 필요 없다.

버킷 두 칸을 번갈아 쓴다. 한 칸을 채우는 동안 다른 칸이 화면에 떠 있으니
그리는 도중이 보이지 않는다.

★프레임마다 버킷을 지우고 다시 만들어야 한다. 이미 차 있는 칸에 그냥
덮어쓰려 하면 _setup_bucket 이 실패한다. 예전에 이걸 빠뜨려서 계속 실패했다.

안전장치
--------
liquidctl 은 버킷 준비가 실패해도 로그만 남기고 데이터를 계속 흘려보낸다
(이슈 #774). 장치는 굳고 부르는 쪽은 성공한 줄 안다. 실제로 이걸로 한 번
먹통을 만들어 재부팅해야 했다. 여기서는 실패하면 바로 예외를 던진다.
"""

import io
import math
import sys
import time

from PIL import Image

import owner
import lcd

RES = (640, 640)

_BULK_HEADER = [0x12, 0xFA, 0x01, 0xE8, 0xAB, 0xCD, 0xEF, 0x98, 0x76, 0x54, 0x32, 0x10]

KIND_GIF = 0x01     # 압축. 데이터가 작아 전송이 빠르다.
KIND_RGBA = 0x02    # 무압축 1.6MB. 화질은 좋지만 느리다.
KIND_Q565 = 0x08    # Q565 압축. Kraken Elite(0x300C) 전용, 빠른 경로에서 쓴다.

# ★빠른 경로 (버킷을 안 거친다)
# 버킷 방식은 한 장마다 HID 왕복을 일곱 번쯤 한다 - 조회, 지우기, 만들기,
# 열기, 닫기, 전환... 이게 장치를 지치게 만든다. 빠른 경로는 두 번뿐이다.
#   write([0x36, 0x01, 0x00, 0x01, 종류])   시작. 네 번째 1 이 "빠른 메모리".
#   bulk: 헤더 + 데이터
#   write([0x36, 0x02])                     끝
# 우리 장치(Elite, 0x300C)가 받아 주는 종류는 0x08(Q565)이다.
# 0x06 은 Elite 아닌 2023 모델용이라 우리 것에서는 전송만 되고 안 그려진다.

MODE_LIQUID = 2
MODE_BUCKET = 4

# 1KB 블록 단위. 장치 전체가 24320 블록이다.
TOTAL_BLOCKS = 24320


def to_gif(img, colors=256, fast=True):
    """PIL 이미지를 GIF 바이트로. 파일을 거치지 않고 메모리에서 끝낸다.

    ★색을 고르는 방식이 속도를 통째로 좌우한다. 실측(640x640 한 장):
        MEDIANCUT(= convert P, ADAPTIVE)  52.6ms   34KB
        FASTOCTREE                         4.5ms   45KB
    열두 배 차이다. 파일이 11KB 커지는 대신 48ms 를 아낀다. 전송이 장당
    16ms 인 것을 생각하면, 예전엔 색 고르는 데만 전송의 세 배를 쓰고 있었다.
    화면 비추기·영상처럼 계속 바뀌는 것은 fast=True 로 쓴다.
    정지화면 한 장을 곱게 띄울 때만 fast=False 가 값어치를 한다.
    """
    method = Image.Quantize.FASTOCTREE if fast else Image.Quantize.MEDIANCUT
    p = img.convert("RGB").quantize(colors=colors, method=method,
                                    dither=Image.Dither.NONE)
    buf = io.BytesIO()
    # optimize 는 파일을 몇 % 줄이자고 한 번 더 훑는다. 실시간에서는 손해다.
    p.save(buf, format="GIF", interlace=False, optimize=not fast)
    return buf.getvalue()


# 4x4 베이어 행렬. 규칙적인 미세한 흔들림을 주는 고전적인 방법이다.
_BAYER = None


def _bayer(h, w):
    global _BAYER
    import numpy as np

    if _BAYER is None:
        m = np.array([[0, 8, 2, 10], [12, 4, 14, 6],
                      [3, 11, 1, 9], [15, 7, 13, 5]], dtype="f4")
        _BAYER = m / 16.0 - 0.5
    reps = (h // 4 + 1, w // 4 + 1)
    return np.tile(_BAYER, reps)[:h, :w, None]


def dither565(img, strength=1.0):
    """RGB565 로 줄이기 전에 미세한 흔들림을 섞는다.

    ★Q565 는 채널당 5/6/5 비트뿐이다. 빨강·파랑은 32단계, 초록은 64단계.
    하늘처럼 천천히 변하는 면을 그대로 줄이면 계단(띠)이 눈에 확 보인다.
    한 칸 아래로 갈지 위로 갈지를 자리마다 조금씩 다르게 흔들어 주면,
    눈이 그 둘을 섞어서 중간색으로 본다. 띠가 사라진다.

    흔드는 폭은 각 채널의 한 칸 크기다 (빨강·파랑 255/31, 초록 255/63).
    그보다 크게 흔들면 그냥 지저분해진다.
    """
    import numpy as np

    a = np.asarray(img.convert("RGB"), dtype="f4")
    h, w, _ = a.shape
    steps = np.array([255.0 / 31, 255.0 / 63, 255.0 / 31], dtype="f4")
    a += _bayer(h, w) * steps * strength
    np.clip(a, 0, 255, out=a)
    return Image.fromarray(a.astype("u1"), "RGB")


def to_q565(img, dither=0.0):
    """Q565 압축. Rust 확장이 있어야 한다 (파이썬 판은 장당 500ms 라 못 쓴다).

    QOI 를 RGB565 용으로 고친 형식이다. 인코딩은 1.1ms 로 아주 빠른데
    결과는 GIF 보다 크다(139KB 대 38KB). 대신 빠른 경로로 보낼 수 있어서
    HID 왕복이 확 줄어든다. 어느 쪽이 유리한지는 장치에서 재봐야 안다.
    """
    import q565_rust

    rgb = dither565(img, dither) if dither else img.convert("RGB")
    w, h = rgb.size
    return q565_rust.py_encode(w, h, rgb.tobytes())


_circle_mask = None


def circle_mask():
    """화면이 둥그니 원 바깥은 검게 만든다.

    어차피 안 보이는 자리다. 검게 채우면 압축이 잘 돼 데이터가 20% 가까이
    줄고, 그만큼 전송이 빨라진다.
    """
    global _circle_mask
    if _circle_mask is None:
        from PIL import ImageDraw

        m = Image.new("L", RES, 0)
        ImageDraw.Draw(m).ellipse([0, 0, RES[0] - 1, RES[1] - 1], fill=255)
        _circle_mask = m
    return _circle_mask


def crop_circle(img):
    return Image.composite(img.convert("RGB"),
                           Image.new("RGB", RES, (0, 0, 0)), circle_mask())


_keep_bytes = None


def q565_circle(raw):
    """이미 돌려진 640x640 rgb24 바이트를 원 바깥만 검게 해서 Q565 로.

    crop_circle + to_q565 와 바이트까지 같다(2026-11-18 확인). 영상처럼 초당 열몇
    장씩 오는 것을 PIL 을 거치지 않고 한 번에 처리한다: 원 안은 0xFF, 밖은 0x00 인
    같은 길이의 표와 AND 하면 픽셀마다 세 바이트를 한 줄로 훑는다(장당 약 1ms,
    PIL 합성은 약 4ms). 채널을 따로 곱하면 안쪽 고리가 3칸이라 오히려 느리다.
    """
    import numpy as np
    import q565_rust

    global _keep_bytes
    if _keep_bytes is None:
        inside = np.asarray(circle_mask()) > 0
        _keep_bytes = np.repeat(np.where(inside, 255, 0).astype(np.uint8), 3)
    out = np.bitwise_and(np.frombuffer(raw, np.uint8), _keep_bytes)
    return q565_rust.py_encode(RES[0], RES[1], out.tobytes())


def to_rgba(img):
    """무압축 경로용. RGB 뒤에 0을 하나씩 붙인 형식이다."""
    import numpy as np

    a = np.asarray(img.convert("RGB"), dtype="u1")
    out = np.zeros((a.shape[0], a.shape[1], 4), dtype="u1")
    out[:, :, :3] = a
    return out.tobytes()


class Stream:
    """버킷 두 칸을 번갈아 쓰며 프레임을 연달아 보낸다."""

    def __init__(self, dev, slot_blocks=2048, slots=2):
        self.dev = dev
        self.slots = slots
        self.slot_blocks = slot_blocks
        self.slot = 0
        assert slot_blocks * slots <= TOTAL_BLOCKS, "장치 메모리를 넘는다"
        dev._delete_all_buckets()

    def send(self, data, kind=KIND_GIF):
        dev = self.dev
        slot = self.slot

        info = [kind, 0x0, 0x0, 0x0] + list(len(data).to_bytes(4, "little"))
        header = _BULK_HEADER + info
        blocks = math.ceil((len(header) + len(data)) / 1024)
        if blocks > self.slot_blocks:
            raise RuntimeError(
                f"프레임이 너무 크다: {blocks}블록 > 칸 크기 {self.slot_blocks}블록"
            )

        start = slot * self.slot_blocks

        dev._write_then_read([0x36, 0x03])

        # 이미 차 있는 칸은 지워야 다시 만들 수 있다. 이걸 빠뜨리면 준비가 실패한다.
        dev._delete_bucket(slot)

        if not dev._setup_bucket(slot, slot + 1,
                                 list(start.to_bytes(2, "little")),
                                 list(blocks.to_bytes(2, "little"))):
            raise RuntimeError(f"버킷 {slot} 준비 실패 - 중단한다")

        dev._write_then_read([0x36, 0x01, slot])
        dev._bulk_write(header)
        for i in range(0, len(data), dev.bulk_buffer_size):
            dev._bulk_write(list(data[i : i + dev.bulk_buffer_size]))
        dev._write([0x36, 0x02])

        if not dev._switch_bucket(slot, MODE_BUCKET):
            raise RuntimeError(f"버킷 {slot} 전환 실패 - 중단한다")

        self.slot = (self.slot + 1) % self.slots


# 대답을 몇 번까지 기다려 볼지. 엉뚱한 소식이 몇 개 끼어 있어도 넘긴다.
_ACK_TRIES = 40


def _ack(dev, cmd, want, what):
    """명령을 보내고 ★그 명령에 대한 대답이 올 때까지 기다린다.

    ★liquidctl 의 _write_then_read 는 한 번만 읽고 그게 무슨 대답인지
    확인하지 않는다. 장치는 우리가 안 물어본 상태 보고도 수시로 올리기
    때문에, 그걸 "다 됐다"로 착각하고 다음 장을 밀어넣게 된다.
    앞 장이 아직 그려지는 중에 새 장이 들어가면 화면이 찢어져 보인다.
    실제로 "모니터 깨짐 효과가 계속 깜빡인다"는 증상이 이것이었다.

    그래서 머리 두 바이트가 맞는 대답이 올 때까지 읽는다.
    """
    dev._write(cmd)
    for _ in range(_ACK_TRIES):
        msg = dev._read()
        if msg and len(msg) >= 2 and msg[0] == want[0] and msg[1] == want[1]:
            return msg
    raise RuntimeError(f"{what}: 장치가 대답하지 않는다 - 중단한다")


def send_fast(dev, data, kind=KIND_Q565):
    """버킷을 안 거치고 곧장 보낸다. HID 왕복이 두 번뿐이다.

    ★버킷을 만들지도 지우지도 않으므로 장치가 훨씬 덜 시달린다.
    NZXT CAM 이 쓰는 것도 이 경로다.
    """
    _ack(dev, [0x36, 0x01, 0x00, 0x01, kind], (0x37, 0x01), "빠른 경로 시작")

    # liquidctl 의 _bulk_write 는 윈도에서 bytes 로 바꿔 bulk_device.write(0x2, …) 를
    # 부를 뿐이다. 거기에 넘기려고 한 장(수십~수백 KB)을 파이썬 정수 목록으로 풀었다가
    # 다시 bytes 로 묶는 데 초당 15장이면 CPU 가 눈에 띄게 든다. 같은 바이트를 바로 보낸다.
    info = bytes([kind, 0x00, 0x00, 0x00]) + len(data).to_bytes(4, "little")
    dev.bulk_device.write(0x2, bytes(_BULK_HEADER) + info)
    for i in range(0, len(data), dev.bulk_buffer_size):
        dev.bulk_device.write(0x2, bytes(data[i : i + dev.bulk_buffer_size]))

    # ★이 대답을 제대로 기다리는 것이 핵심이다. 이게 "한 장 다 그렸다"다.
    _ack(dev, [0x36, 0x02], (0x37, 0x02), "빠른 경로 종료")


def read_orientation(dev):
    """장치에 저장된 화면 방향을 읽는다 (0~3, 한 칸이 90도).

    패널이 돌아간 채로 달려 있어서, 보내기 전에 그만큼 미리 돌려놔야
    똑바로 보인다. liquidctl 의 이미지 경로도 같은 보정을 한다
    (_prepare_static_file 의 rotate(rotation * -90)).
    이걸 빼먹으면 화면이 90도 누워서 나온다.
    """
    box = {}

    def parse(msg):
        box["orientation"] = msg[0x1A]

    dev._write([0x30, 0x01])
    dev._read_until({b"\x31\x01": parse})
    return box.get("orientation", 0)


def open_device():
    dev = lcd.get_kraken()
    ctx = dev.connect()
    ctx.__enter__()
    if not dev.bulk_device:
        dev.bulk_device = lcd.find_bulk()
    dev.orientation = read_orientation(dev)
    return dev, ctx


def fit(img, orientation=0):
    """640x640 으로 맞추고 장치 방향만큼 미리 돌린다."""
    if img.size != RES:
        img = img.resize(RES)
    if orientation:
        img = img.rotate(orientation * -90)
    return img


def load(path, orientation=0):
    return fit(Image.open(path), orientation)


def cmd_image(path, kind):
    dev, ctx = open_device()
    try:
        img = load(path, dev.orientation)
        data = to_gif(img) if kind == KIND_GIF else to_rgba(img)
        st = Stream(dev)
        t0 = time.time()
        st.send(data, kind)
        print(f"성공: {len(data)/1024:.0f}KB, {time.time()-t0:.3f}초")
    finally:
        ctx.__exit__(None, None, None)


def cmd_bench(path, count, kind):
    dev, ctx = open_device()
    try:
        img = load(path, dev.orientation)
        data = to_gif(img) if kind == KIND_GIF else to_rgba(img)
        st = Stream(dev)
        st.send(data, kind)
        t0 = time.time()
        for _ in range(count):
            st.send(data, kind)
        dt = time.time() - t0
        print(f"{count}장 / {dt:.2f}초 = 초당 {count/dt:.1f}장 "
              f"(장당 {dt/count*1000:.0f}ms, {len(data)/1024:.0f}KB)")
    finally:
        ctx.__exit__(None, None, None)


def main():
    owner.require_free("LCD 를 직접 만지기")
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    kind = KIND_RGBA if "--rgba" in args else KIND_GIF
    args = [a for a in args if a != "--rgba"]
    try:
        if args[0] == "image":
            cmd_image(args[1], kind)
        elif args[0] == "bench":
            cmd_bench(args[1], int(args[2]) if len(args) > 2 else 40, kind)
        else:
            print(__doc__)
            return 1
    except Exception as e:
        print(f"실패: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
