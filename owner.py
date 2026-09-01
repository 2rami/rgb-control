"""크라켄을 지금 누가 쥐고 있는지 확인한다.

크라켄은 한 프로그램만 잡을 수 있다. 이미 잡혀 있는데 다른 프로그램이
비집고 들어가면 그냥 실패하는 게 아니라 ★장치가 통째로 굳는다.
굳으면 hid.enumerate 조차 멈추고, 재부팅 말고는 푸는 방법이 없다.

2026-09-02 에 실제로 그렇게 만들었다. 대시보드가 화면을 보내고 있는데
lcd_stream.py bench 를 따로 돌렸고, 그 뒤로 "Could not write to device"
가 계속 나다가 결국 아무것도 못 하게 됐다. USB 를 껐다 켜도 안 풀렸다.

그래서 장치를 여는 모든 스크립트는 시작할 때 require_free() 를 부른다.
"""

import json
import sys
import urllib.request

DASHBOARD = "http://127.0.0.1:5000/api/state"


def dashboard_holding():
    """대시보드가 크라켄을 쥐고 있으면 True.

    대시보드가 안 떠 있거나, 떠 있어도 크라켄을 못 잡은 상태면 False.
    """
    try:
        with urllib.request.urlopen(DASHBOARD, timeout=2) as r:
            data = json.load(r)
    except Exception:
        return False
    k = data.get("kraken") or {}
    return bool(k.get("ok"))


def cam_running():
    """NZXT CAM 이 떠 있으면 True."""
    try:
        import psutil
    except ImportError:
        return False
    for p in psutil.process_iter(["name"]):
        n = (p.info.get("name") or "").lower()
        if n.startswith("nzxt cam") or n == "cam_helper.exe":
            return True
    return False


def require_free(what="이 작업"):
    """장치가 비어 있지 않으면 아무것도 안 하고 끝낸다."""
    if dashboard_holding():
        print("대시보드가 크라켄을 쓰고 있습니다.")
        print("  둘이 동시에 열면 장치가 굳어서 재부팅해야 합니다.")
        print(f"  {what} 전에 stop.bat 으로 대시보드를 내려주세요.")
        print("  (대시보드 안에서도 같은 일을 할 수 있습니다: http://127.0.0.1:5000)")
        sys.exit(2)
    if cam_running():
        print("NZXT CAM 이 켜져 있습니다.")
        print(f"  {what} 전에 cam_off_quiet.bat 으로 내려주세요.")
        sys.exit(2)


if __name__ == "__main__":
    print("대시보드가 쥐고 있나:", dashboard_holding())
    print("CAM 이 떠 있나     :", cam_running())
