"""Kraken Elite LCD 고속 전송.

    python lcd_fast.py image 그림.png      한 장 띄우기
    python lcd_fast.py bench 그림.png 30   같은 그림을 30번 보내 속도 측정

왜 따로 만들었나
----------------
liquidctl의 기본 이미지 경로는 '버킷'을 쓴다. 프레임 하나를 보낼 때마다
버킷 16개를 일일이 조회하는데(HID 왕복 16번), 이게 프레임당 145ms 중
111ms를 잡아먹는다. 영상은커녕 초당 몇 장도 못 낸다.

그런데 이 장치엔 버킷을 안 거치는 '빠른 메모리' 경로가 따로 있다.
    [0x36, 0x01, 0x00, 0x01, 0x06]   생 RGB565 를 그대로 받음
    [0x36, 0x01, 0x00, 0x01, 0x08]   Q565 압축 형식 (별도 코덱 필요)
liquidctl 안에 0x06 경로 구현이 이미 있지만 product_id == 0x300E 일 때만
쓰도록 막혀 있다. 우리 장치는 0x300C 라서 그 분기를 안 탄다.
여기서는 그 구현을 직접 불러 쓴다.

데이터 크기도 절반이다. RGBA 640x640x4 = 1.6MB, RGB565 는 640x640x2 = 800KB.

안전장치
--------
지난번에 이 장치를 먹통으로 만든 적이 있다. liquidctl 의 버킷 경로는
버킷 준비가 실패해도 로그만 남기고 데이터를 계속 흘려보낸다
(liquidctl 이슈 #774). 장치는 굳고 호출한 쪽은 성공한 줄 안다.
그래서 여기서는 전송 시작 응답을 반드시 확인하고, 이상하면 즉시 멈춘다.
참조 구현(AIOLCDUnchained)도 같은 자리에서 상태를 보고 중단한다.
"""

import sys
import time

import numpy as np
from PIL import Image

import lcd

# 전송 시작/종료 명령에 대한 정상 응답 머리 2바이트
_ACK_START = (0x37, 0x01)
_ACK_END = (0x37, 0x02)

_BULK_HEADER = [0x12, 0xFA, 0x01, 0xE8, 0xAB, 0xCD, 0xEF, 0x98, 0x76, 0x54, 0x32, 0x10]

# 0x06 = 생 RGB565. 0x08 은 Q565 압축이라 별도 코덱이 있어야 한다.
_TYPE_RAW565 = 0x06

RES = (640, 640)


def to_rgb565(path_or_img, rotation=0):
    """이미지를 640x640 RGB565 바이트로 만든다.

    liquidctl 의 _prepare_static_file_rgb16 은 픽셀을 파이썬 반복문으로
    돌려서 40만 번 루프를 탄다. numpy 로 한 번에 계산하면 훨씬 빠르다.
    바이트 순서는 상위 바이트 먼저(big-endian)로, 원본 구현과 같다.
    """
    img = path_or_img
    if not isinstance(img, Image.Image):
        img = Image.open(img)
    if img.size != RES:
        img = img.resize(RES)
    if rotation:
        img = img.rotate(rotation * -90)

    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    v = ((a[:, :, 0] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5) | (a[:, :, 2] >> 3)
    return v.astype(">u2").tobytes()


# 장치는 우리가 묻지 않아도 상태 보고를 주기적으로 보낸다(예: 0x75 ...).
# 그래서 한 번 읽어서는 우리 응답이 아닐 수 있고, 원하는 머리가 나올 때까지
# 넘겨가며 읽어야 한다. 참조 구현의 readUntil 과 같은 방식이다.
_MAX_ACK_READS = 30


def _await_ack(dev, expect, what, first=None):
    """원하는 응답이 올 때까지 읽고, 성공 여부까지 확인한다.

    확인 없이 계속 쏘면 장치가 굳는다(liquidctl 이슈 #774). 반드시 멈춰야 한다.
    """
    resp = first
    for _ in range(_MAX_ACK_READS):
        if resp is not None and len(resp) >= 2 and (resp[0], resp[1]) == expect:
            # 머리가 맞아도 내용이 실패일 수 있다. 참조 구현이 보는 자리가 14번.
            if len(resp) > 14 and resp[14] != 1:
                raise RuntimeError(f"{what}: 장치가 거절했다 (상태 {resp[14]}) - 중단한다")
            return resp
        resp = dev._read()
    raise RuntimeError(
        f"{what}: {_MAX_ACK_READS}번 읽는 동안 "
        f"{expect[0]:#04x} {expect[1]:#04x} 응답이 없었다 - 중단한다"
    )


def send_frame(dev, data):
    """RGB565 한 프레임을 빠른 메모리로 보낸다."""
    resp = dev._write_then_read([0x36, 0x01, 0x00, 0x01, _TYPE_RAW565])
    _await_ack(dev, _ACK_START, "전송 시작", resp)

    info = [_TYPE_RAW565, 0x0, 0x0, 0x0] + list(len(data).to_bytes(4, "little"))
    dev._bulk_write(_BULK_HEADER + info)

    step = dev.bulk_buffer_size
    for i in range(0, len(data), step):
        dev._bulk_write(list(data[i : i + step]))

    resp = dev._write_then_read([0x36, 0x02])
    _await_ack(dev, _ACK_END, "전송 종료", resp)


# 화면이 무엇을 그릴지 고르는 모드. 데이터를 아무리 잘 보내도 모드가
# LIQUID 이면 화면은 계속 액체 온도만 그린다(보내는 쪽은 성공으로 보인다).
DISPLAY_LIQUID = 2
DISPLAY_BUCKET = 4
DISPLAY_FAST_BUCKET = 5


def set_display_mode(dev, mode, bucket=0):
    """화면 모드를 바꾼다. 스트리밍 전에 반드시 한 번 불러야 한다."""
    resp = dev._write_then_read([0x38, 0x01, mode, bucket])
    return _await_ack(dev, (0x39, 0x01), f"화면 모드 {mode}", resp)


def open_device():
    dev = lcd.get_kraken()
    ctx = dev.connect()
    ctx.__enter__()
    if not dev.bulk_device:
        dev.bulk_device = lcd.find_bulk()
    return dev, ctx


def start_stream(dev, data):
    """첫 프레임을 넣고 화면이 그것을 그리도록 모드를 돌린다.

    순서가 중요하다. 프레임을 넣기 전에 모드부터 바꾸면 장치가 거절한다
    (상태 2). 아직 아무것도 없는 곳을 가리키라는 뜻이 되기 때문이다.
    반대로 모드를 안 바꾸면 전송은 전부 성공하는데 화면은 계속 예전 것을
    그린다 - 보내는 쪽에서는 성공으로 보여서 알아채기 어렵다.
    """
    send_frame(dev, data)
    # 초기화 직후 한 번은 두 번 보내야 실제로 바뀐다 (원본 구현도 그렇게 한다).
    send_frame(dev, data)
    set_display_mode(dev, DISPLAY_BUCKET)


def cmd_image(path):
    data = to_rgb565(path)
    dev, ctx = open_device()
    try:
        t0 = time.time()
        start_stream(dev, data)
        print(f"성공: {len(data)/1024:.0f}KB, {time.time()-t0:.3f}초")
    finally:
        ctx.__exit__(None, None, None)


def cmd_bench(path, count):
    data = to_rgb565(path)
    dev, ctx = open_device()
    try:
        start_stream(dev, data)  # 첫 장은 초기화 비용이 섞이므로 측정에서 뺀다
        t0 = time.time()
        for _ in range(count):
            send_frame(dev, data)
        dt = time.time() - t0
        print(f"{count}장 / {dt:.2f}초 = 초당 {count/dt:.1f}장 "
              f"(장당 {dt/count*1000:.0f}ms, {len(data)/1024:.0f}KB)")
    finally:
        ctx.__exit__(None, None, None)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    try:
        if args[0] == "image":
            cmd_image(args[1])
        elif args[0] == "bench":
            cmd_bench(args[1], int(args[2]) if len(args) > 2 else 30)
        else:
            print(__doc__)
            return 1
    except Exception as e:
        print(f"실패: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
