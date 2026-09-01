"""글카 I2C 로 보내는 조건을 하나씩 바꿔가며 무엇이 통하는지 찾는다.

    python gpu_probe.py

OpenRGB 는 포트 1 로 고정하지만 그건 자기가 아는 카드들 얘기다. 우리 카드는
목록에 없으니 포트도 다를 수 있다. 포트·주소 지정 여부를 훑으며 NVAPI 가
돌려주는 코드를 본다. 코드가 달라지는 지점이 곧 단서다.

색은 검정(0,0,0)으로 보낸다. 통해도 눈에 안 띄게 하려는 것이다.
"""

import ctypes
from ctypes import byref, c_uint8, c_uint32

import gpu

# NVAPI 가 돌려주는 값 중 여기서 나올 만한 것들.
CODES = {
    0: "성공",
    0xFFFFFFFF: "-1 일반 오류",
    0xFFFFFFFB: "-5 잘못된 인자",
    0xFFFFFF98: "-104 지원 안 함",
    0xFFFFFFFE: "-2 라이브러리 없음",
    0xFFFFFFF7: "-9 핸들 이상",
}


def label(st):
    return CODES.get(st, f"{st - (1 << 32) if st > 0x7FFFFFFF else st}")


def try_write(api, idx, addr, payload, port, set_port, ddc=0):
    buf = (c_uint8 * len(payload))(*payload)
    info = gpu.NvI2cInfoV3()
    ctypes.memset(byref(info), 0, ctypes.sizeof(info))
    info.version = gpu._struct_version(gpu.NvI2cInfoV3, 3)
    info.reg_addr_size = 0
    info.data = buf
    info.size = len(payload)
    info.is_ddc_port = ddc
    info.port_id = port
    info.is_port_id_set = 1 if set_port else 0
    info.i2c_speed = 0xFFFF
    info.i2c_speed_khz = 0
    info.i2c_dev_address = addr << 1
    unknown = c_uint32(0)
    return api._write(api.handles[idx], byref(info), byref(unknown))


def main():
    api = gpu.NvApi()
    try:
        idx, dev, sub = gpu.find_gpu(api)
        print(f"카드 {idx}번  서브시스템 {sub & 0xFFFF:04X}:{sub >> 16:04X}\n")
        pkt = gpu.colorful_packet(0, 0, 0)

        print("포트를 바꿔가며 (주소 0x61):")
        for set_port in (True, False):
            ports = range(8) if set_port else [0]
            for p in ports:
                st = try_write(api, idx, gpu.COLORFUL_ADDR, pkt, p, set_port)
                tag = f"포트 {p}" if set_port else "포트 지정 안 함"
                print(f"  {tag:16s} -> {label(st)}")

        print("\nDDC 포트로 (혹시 몰라서):")
        st = try_write(api, idx, gpu.COLORFUL_ADDR, pkt, 1, True, ddc=1)
        print(f"  ddc=1 포트1        -> {label(st)}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
