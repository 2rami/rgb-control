"""LCD를 장치 기본 상태로 되돌리고 손을 뗀다.

    python lcd_reset.py

우리가 프레임을 보내다 중간에 멈추면, 화면 모드가 계속 우리 버킷을
가리킨 채로 남아 마지막 프레임이 얼어붙은 것처럼 붙어 있는다.
그 상태에서는 NZXT CAM 도 화면을 못 가져간다.

되돌리는 순서
  1. 화면 모드를 액체 온도(2)로
  2. 버킷 16개 비우기
  3. USB 자원 놓기

CAM 이 돌고 있으면 장치를 못 연다. 먼저 cam_off_quiet.bat 으로 내리고
이걸 돌린 다음 cam_on_quiet.bat 으로 되살리면 된다.
"""

import sys

import usb.util

import owner
import lcd


def main():
    owner.require_free("LCD 되돌리기")
    try:
        dev = lcd.get_kraken()
    except Exception as e:
        print(f"장치를 못 찾았어: {e}")
        print("CAM 이 잡고 있으면 cam_off_quiet.bat 을 먼저 실행해줘.")
        return 1

    bulk = None
    try:
        with dev.connect():
            # _delete_all_buckets 는 액체 모드로 돌린 뒤 버킷 16개를 비운다.
            dev._delete_all_buckets()
            print("화면 모드 = 액체 온도, 버킷 비움")
            try:
                dev.set_screen("lcd", "liquid", None)
            except Exception:
                pass
    except Exception as e:
        print(f"되돌리는 중 오류: {e}")
        return 1
    finally:
        # 우리가 잡은 USB 자원을 확실히 놓아야 CAM 이 들어갈 수 있다.
        try:
            import libusb_package
            d = libusb_package.find(idVendor=lcd.VID, idProduct=lcd.PID)
            if d is not None:
                usb.util.dispose_resources(d)
                print("USB 자원 놓음")
        except Exception:
            pass

    print("완료. 이제 CAM 이 화면을 가져갈 수 있어.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
