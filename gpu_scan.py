"""글카 I2C 버스에 무엇이 붙어 있는지 훑는다 (읽기만 한다).

    python gpu_scan.py

쓰기가 성공(코드 0)으로 돌아와도 실제로 칩이 대답했다는 뜻은 아니다.
드라이버가 "버스는 있다"는 의미로 0 을 주는 경우가 있다. 그래서 읽기로
확인한다. 읽기에 대답하는 주소가 곧 실제로 붙어 있는 칩이다.

읽기만 하므로 조명이 바뀌지 않는다.
"""

import ctypes
from ctypes import byref, c_uint8, c_uint32

import gpu


def i2c_read(api, idx, addr, port=1, length=1):
    buf = (c_uint8 * max(1, length))()
    info = gpu.NvI2cInfoV3()
    ctypes.memset(byref(info), 0, ctypes.sizeof(info))
    info.version = gpu._struct_version(gpu.NvI2cInfoV3, 3)
    info.reg_addr_size = 0
    info.data = buf
    info.size = length
    info.is_ddc_port = 0
    info.port_id = port
    info.is_port_id_set = 1
    info.i2c_speed = 0xFFFF
    info.i2c_speed_khz = 0
    info.i2c_dev_address = addr << 1
    unknown = c_uint32(0)
    st = api._read(api.handles[idx], byref(info), byref(unknown))
    return st, bytes(buf[:length])


def main():
    api = gpu.NvApi()
    api._read = api._fn(gpu.FN_I2C_READ_EX,
                        [ctypes.c_void_p,
                         ctypes.POINTER(gpu.NvI2cInfoV3),
                         ctypes.POINTER(c_uint32)])
    try:
        idx, dev, sub = gpu.find_gpu(api)
        print(f"카드 {idx}번  서브시스템 {sub & 0xFFFF:04X}:{sub >> 16:04X}")

        for port in range(4):
            hits = []
            for addr in range(0x08, 0x78):
                try:
                    st, data = i2c_read(api, idx, addr, port=port, length=1)
                except Exception:
                    continue
                if st == 0:
                    hits.append((addr, data))
            if hits:
                print(f"\n포트 {port} 에서 대답한 주소:")
                for addr, data in hits:
                    star = "  <-- OpenRGB 가 Colorful LED 로 쓰는 주소" if addr == 0x61 else ""
                    print(f"   0x{addr:02X}  첫 바이트 {data.hex()}{star}")
            else:
                print(f"\n포트 {port}: 대답 없음")
    finally:
        api.close()


if __name__ == "__main__":
    main()
