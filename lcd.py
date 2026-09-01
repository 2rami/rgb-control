"""NZXT Kraken LCD 제어.

    python lcd.py liquid            액체 온도 표시
    python lcd.py bright 80         밝기 0~100
    python lcd.py rotate 90         화면 회전 0/90/180/270
    python lcd.py image 그림.png     정지 이미지 띄우기
    python lcd.py gif 움짤.gif       움직이는 GIF 띄우기

liquidctl은 Windows에서 이미지를 보낼 때 winusbcdc 라이브러리를 쓰는데,
이 PC에서는 그게 USB 장치를 하나도 열거하지 못한다 (관리자 권한으로도 0개).
그래서 liquidctl이 만든 패킷을 pyusb로 대신 내보내는 어댑터를 끼운다.

프로토콜 조립은 liquidctl이 그대로 하고, 마지막 전송 경로만 바뀐다.
"""

import sys

import owner
import time

import usb.util
from liquidctl import find_liquidctl_devices

VID, PID = 0x1E71, 0x300C
BULK_OUT_EP = 0x02


class PyUsbBulk:
    """liquidctl이 기대하는 WinUsbPy 인터페이스를 pyusb로 흉내낸다.

    liquidctl은 sys.platform이 win32면 close_winusb_device()를 부른다.

    ★놓아주는 것을 반드시 해야 한다. 예전엔 close/release가 True만 돌려주고
    실제로는 아무것도 안 놓았다. 그러면 우리 프로그램이 끝난 뒤에도 장치를
    잡고 있는 것처럼 남아서 NZXT CAM이 "크라켄 연결 안 됨"이 된다.
    """

    def __init__(self, dev):
        self.dev = dev

    def write(self, endpoint, data):
        return self.dev.write(endpoint, bytes(data), timeout=5000)

    def _dispose(self):
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
        return True

    def close_winusb_device(self):
        return self._dispose()

    def release(self):
        return self._dispose()


def find_bulk():
    try:
        import libusb_package
        dev = libusb_package.find(idVendor=VID, idProduct=PID)
    except Exception:
        import usb.core
        dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise RuntimeError("Kraken USB 장치를 못 찾았습니다.")
    return PyUsbBulk(dev)


def get_kraken():
    dev = next((d for d in find_liquidctl_devices() if "Kraken" in d.description), None)
    if dev is None:
        raise RuntimeError("Kraken을 못 찾았습니다. CAM이 잡고 있으면 종료하세요.")
    return dev


def run(mode, value):
    dev = get_kraken()
    with dev.connect():
        # 이미지 계열만 bulk 전송이 필요하다. 나머지는 원래 경로로도 잘 된다.
        if mode in ("static", "gif") and not dev.bulk_device:
            dev.bulk_device = find_bulk()

        t0 = time.time()
        dev.set_screen("lcd", mode, value)
        return time.time() - t0


def main():
    owner.require_free("LCD 를 직접 만지기")
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1

    cmd = args[0]
    arg = args[1] if len(args) > 1 else None

    # 딕셔너리로 묶으면 int(arg)가 이미지 경로에도 실행되므로 분기로 둔다.
    if cmd == "liquid":
        mode, value = "liquid", None
    elif cmd == "bright":
        mode, value = "brightness", int(arg) if arg else 80
    elif cmd == "rotate":
        mode, value = "orientation", int(arg) if arg else 0
    elif cmd == "image":
        mode, value = "static", arg
    elif cmd == "gif":
        mode, value = "gif", arg
    else:
        print(__doc__)
        return 1
    if mode in ("static", "gif") and not value:
        print("파일 경로를 지정해줘.")
        return 1

    try:
        dt = run(mode, value)
        print(f"성공: {cmd} ({dt:.2f}초)")
    except Exception as e:
        print(f"실패: {e!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
