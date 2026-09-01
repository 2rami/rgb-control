"""팬 색을 계속 유지하는 감시 스크립트.

리안리 컨트롤러는 조명을 자체 메모리에 저장하지 않아서, 신호가 끊기면
공장 기본 무지개로 돌아간다. 이 스크립트는 주기적으로 색을 다시 보내서
무지개가 나타나도 몇 초 안에 원래 색으로 되돌린다.

근본 치료가 아니라 증상 완화다. 접촉 불량 자체는 하드웨어 교체가 답이다.

사용법:
    python keep_color.py              # 기본 색(보라)으로 유지
    python keep_color.py ff0000       # 빨강으로 유지
    python keep_color.py 00ff88 2     # 민트색, 2초 간격
중단: Ctrl+C
"""

import sys
import time
import traceback

import fan
from openrgb.utils import RGBColor

DEFAULT_HEX = "a000ff"   # 보라
DEFAULT_INTERVAL = 4.0   # 초


def parse_args():
    hex_str = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HEX
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_INTERVAL
    return hex_str.lstrip("#"), max(1.0, interval)


def connect_hub():
    """허브에 연결하고 제어 준비까지 끝낸 상태로 돌려준다."""
    cli = fan.connect("keep-color")
    hub = fan.get_hub(cli)
    hub = fan.ensure_ready(cli, hub)
    return cli, hub


def main():
    hex_str, interval = parse_args()
    color = RGBColor.fromHEX(hex_str)

    print(f"유지할 색 : #{hex_str}")
    print(f"재적용 주기: {interval}초")
    print("중단하려면 Ctrl+C\n")

    cli, hub = connect_hub()
    print(f"연결됨: {hub.name} (LED {len(hub.leds)}개)\n")

    applied = 0
    reconnects = 0

    while True:
        try:
            hub.set_colors([color] * len(hub.leds))
            applied += 1
            # 같은 줄을 덮어써서 로그가 쌓이지 않게 한다.
            print(f"\r적용 {applied}회 / 재연결 {reconnects}회   ", end="", flush=True)

        except Exception:
            reconnects += 1
            print(f"\n[!] 연결이 끊겼습니다. 재연결 시도 {reconnects}회...")
            # 서버가 살아날 때까지 기다렸다가 다시 붙는다.
            for _ in range(30):
                if fan.server_alive():
                    break
                time.sleep(2)
            try:
                cli, hub = connect_hub()
                print(f"[O] 재연결 성공 (LED {len(hub.leds)}개)")
            except Exception:
                print("[X] 재연결 실패. 10초 후 다시 시도합니다.")
                time.sleep(10)

        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n중단했습니다. 색은 마지막 상태로 남습니다.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
