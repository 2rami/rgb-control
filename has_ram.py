"""OpenRGB가 램(SMBus)을 보고 있는지 확인한다.

start_all.ps1이 쓴다. 'yes' 또는 'no' 한 줄만 찍는다.

OpenRGB를 관리자가 아닌 채로 띄우면 램이 목록에 아예 안 잡히는데,
겉으로는 멀쩡히 돌아가는 것처럼 보인다. 그래서 프로세스가 살아있는지가
아니라 램이 실제로 보이는지를 물어봐야 한다.
"""

import sys

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import DeviceType

    cli = OpenRGBClient(address="127.0.0.1", port=6742, name="has-ram")
    found = any(d.type == DeviceType.DRAM for d in cli.devices)
    print("yes" if found else "no")
except Exception:
    # 서버가 아직 안 떴거나 응답이 없으면 없는 것으로 친다.
    print("no")

sys.exit(0)
