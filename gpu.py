"""Colorful 그래픽카드 LED 제어 (NVIDIA I2C 직통).

    python gpu.py              현재 상태 확인 + I2C 통로 열기만
    python gpu.py 00ff00       초록으로 칠하기
    python gpu.py off          끄기

왜 이게 필요한가
    우리 카드는 Colorful RTX 4070 Ti (PCI 서브시스템 7377:1301)인데,
    OpenRGB 는 이 모델을 모른다. 비슷한 iGame 모델(7377:1400 등)만
    등록돼 있고, 장치 지원은 코드에 박혀 있어 설정으로 추가할 수 없다.

    그런데 OpenRGB 로그를 보면 통로 자체는 이미 열려 있다.
        Registering I2C interface: Nvidia NvAPI I2C on GPU 0
          Device 10DE:2782  Subsystem: 7377:1301
    버스는 보이는데 그 위의 LED 칩을 못 알아본 것뿐이다.
    그래서 OpenRGB 가 쓰는 것과 똑같은 방법으로 우리가 직접 쏜다.

어떻게 하는가
    NVIDIA 드라이버의 nvapi64.dll 에는 GPU 의 I2C 버스로 바이트를 보내는
    함수가 있다. 문서에 없는 함수라 이름으로 못 부르고, nvapi_QueryInterface
    에 함수마다 정해진 번호를 넣어 주소를 받아 와야 한다.

    LED 칩은 I2C 주소 0x61 에 있고, 색은 이런 꾸러미로 보낸다.
        AA EF 12 03 01 FF  R G B  + 검산 2바이트
    검산은 앞의 모든 바이트를 더한 값이다 (낮은 자리 먼저).

    ※ 이 모델이 같은 칩을 쓰는지는 해봐야 안다. 안 되면 NVAPI 가 오류를
      돌려주거나, 성공했다는데 색이 안 변한다.

주의
    iGameCenter 가 돌고 있으면 우리가 칠한 색을 덮어쓸 수 있다.
    램에서 G.SKILL hid.exe 가 SMBus 를 쥐고 있던 것과 같은 구조다.
"""

import ctypes
import sys
from ctypes import POINTER, byref, c_uint8, c_uint32, c_void_p

# nvapi_QueryInterface 에 넣을 함수 번호. NVIDIA 가 공개한 적 없는 값이라
# OpenRGB 등 여러 프로젝트가 실측으로 알아낸 것을 그대로 쓴다.
FN_INITIALIZE = 0x0150E828
FN_ENUM_GPUS = 0xE5AC921F
FN_GET_PCI_IDS = 0x2DDFB66E
FN_I2C_WRITE_EX = 0x283AC65A
FN_I2C_READ_EX = 0x4D7B0709
FN_UNLOAD = 0xD22BDD7E

MAX_GPUS = 64

# LED 칩이 앉아 있는 I2C 주소. OpenRGB 의 Colorful 등록부가 전부 이 값을 쓴다.
COLORFUL_ADDR = 0x61

# Colorful 카드는 꾸러미 형식이 두 가지다. OpenRGB 도 모델마다 갈라 쓴다.
#   V1  11바이트   머리 6 + RGB 3 + 검산 2       (대부분의 카드)
#   V2 122바이트   머리 6 + RGB 38쌍 + 검산 2    (4070 Vulcan, 4090 Neptune)
# 우리 카드가 어느 쪽인지는 목록에 없어서 해봐야 안다.
COLORFUL_HEADER_V1 = [0xAA, 0xEF, 0x12, 0x03, 0x01, 0xFF]
COLORFUL_HEADER_V2 = [0xAA, 0xEF, 0x01, 0x04, 0x88, 0x26]
COLORFUL_LEN_V1 = 11
COLORFUL_LEN_V2 = 122


class NvI2cInfoV3(ctypes.Structure):
    """NVAPI 가 기대하는 모양 그대로. 순서와 크기가 하나라도 어긋나면
    엉뚱한 값이 전달되므로 손대지 말 것."""

    _fields_ = [
        ("version", c_uint32),
        ("display_mask", c_uint32),
        ("is_ddc_port", c_uint8),
        ("i2c_dev_address", c_uint8),
        ("i2c_reg_address", POINTER(c_uint8)),
        ("reg_addr_size", c_uint32),
        ("data", POINTER(c_uint8)),
        ("size", c_uint32),
        ("i2c_speed", c_uint32),
        ("i2c_speed_khz", c_uint32),
        ("port_id", c_uint8),
        ("is_port_id_set", c_uint32),
    ]


def _struct_version(cls, ver):
    """NVAPI 는 구조체 크기와 판 번호를 합친 값으로 판을 구분한다."""
    return ctypes.sizeof(cls) | (ver << 16)


class NvApi:
    def __init__(self):
        self.dll = ctypes.WinDLL("nvapi64.dll")
        self._query = self.dll.nvapi_QueryInterface
        self._query.restype = c_void_p
        self._query.argtypes = [c_uint32]

        self._init = self._fn(FN_INITIALIZE, [])
        self._enum = self._fn(FN_ENUM_GPUS, [c_void_p, POINTER(c_uint32)])
        self._pci = self._fn(FN_GET_PCI_IDS,
                             [c_void_p] + [POINTER(c_uint32)] * 4)
        self._write = self._fn(FN_I2C_WRITE_EX,
                               [c_void_p, POINTER(NvI2cInfoV3), POINTER(c_uint32)])
        self._unload = self._fn(FN_UNLOAD, [])

        st = self._init()
        if st != 0:
            raise RuntimeError(f"NvAPI_Initialize 실패 (코드 {st})")

        self.handles = (c_void_p * MAX_GPUS)()
        count = c_uint32(0)
        st = self._enum(self.handles, byref(count))
        if st != 0 or count.value == 0:
            raise RuntimeError(f"그래픽카드를 못 찾았다 (코드 {st})")
        self.count = count.value

    def _fn(self, fn_id, argtypes):
        addr = self._query(fn_id)
        if not addr:
            raise RuntimeError(f"NVAPI 함수 {fn_id:#010x} 를 못 찾았다. "
                               "드라이버가 너무 오래됐을 수 있다.")
        proto = ctypes.CFUNCTYPE(c_uint32, *argtypes)
        return proto(addr)

    def pci_ids(self, idx):
        """(장치, 서브시스템, 리비전, 확장장치) 네 개를 돌려준다."""
        vals = [c_uint32(0) for _ in range(4)]
        st = self._pci(self.handles[idx], *(byref(v) for v in vals))
        if st != 0:
            raise RuntimeError(f"PCI 정보 읽기 실패 (코드 {st})")
        return tuple(v.value for v in vals)

    def i2c_write(self, idx, addr, payload):
        """레지스터 주소 없이 바이트 뭉치를 그대로 보낸다.

        RGB 칩은 포트 1 에 달려 있다. OpenRGB 도 항상 1 로 고정한다.
        주소를 한 칸 왼쪽으로 미는 건 I2C 규약이다 (맨 아래 비트가 읽기/쓰기).
        """
        buf = (c_uint8 * len(payload))(*payload)

        info = NvI2cInfoV3()
        ctypes.memset(byref(info), 0, ctypes.sizeof(info))
        info.version = _struct_version(NvI2cInfoV3, 3)
        info.i2c_reg_address = None
        info.reg_addr_size = 0
        info.data = buf
        info.size = len(payload)
        info.is_ddc_port = 0
        info.port_id = 1
        info.is_port_id_set = 1
        info.i2c_speed = 0xFFFF      # 옛 항목. 쓰지 말라는 표시값이다.
        info.i2c_speed_khz = 0       # NVAPI_I2C_SPEED_DEFAULT
        info.i2c_dev_address = addr << 1

        unknown = c_uint32(0)
        return self._write(self.handles[idx], byref(info), byref(unknown))

    def close(self):
        try:
            self._unload()
        except Exception:
            pass


def colorful_packet(r, g, b, version=1):
    """색 하나를 꾸러미로 만든다. 검산은 앞 바이트를 전부 더한 값이다."""
    r, g, b = r & 0xFF, g & 0xFF, b & 0xFF
    if version == 2:
        pkt = list(COLORFUL_HEADER_V2)
        while len(pkt) < COLORFUL_LEN_V2 - 2:
            pkt += [r, g, b]
        pkt = pkt[:COLORFUL_LEN_V2 - 2]
    else:
        pkt = COLORFUL_HEADER_V1 + [r, g, b]
    crc = sum(pkt)
    return pkt + [crc & 0xFF, (crc >> 8) & 0xFF]


def find_gpu(api):
    """Colorful 카드가 몇 번째인지 찾는다. 없으면 0번을 쓴다."""
    for i in range(api.count):
        dev, sub, _, _ = api.pci_ids(i)
        if (sub & 0xFFFF) == 0x7377:
            return i, dev, sub
    dev, sub, _, _ = api.pci_ids(0)
    return 0, dev, sub


def set_color(r, g, b, verbose=True, version=1):
    api = NvApi()
    try:
        idx, dev, sub = find_gpu(api)
        if verbose:
            print(f"그래픽카드 {idx}번: "
                  f"장치 {dev >> 16:04X}:{dev & 0xFFFF:04X}  "
                  f"서브시스템 {sub & 0xFFFF:04X}:{sub >> 16:04X}")

        pkt = colorful_packet(r, g, b, version)
        if verbose:
            head = " ".join(f"{x:02X}" for x in pkt[:12])
            print(f"V{version} {len(pkt)}바이트: {head}"
                  + (" ..." if len(pkt) > 12 else ""))

        st = api.i2c_write(idx, COLORFUL_ADDR, pkt)
        if verbose:
            print(f"결과 코드: {st}  ({'성공' if st == 0 else '실패'})")
        return st
    finally:
        api.close()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg is None:
        api = NvApi()
        try:
            print(f"그래픽카드 {api.count}개 찾음")
            for i in range(api.count):
                dev, sub, rev, _ = api.pci_ids(i)
                print(f"  {i}: 장치 {dev >> 16:04X}:{dev & 0xFFFF:04X}  "
                      f"서브시스템 {sub & 0xFFFF:04X}:{sub >> 16:04X}  "
                      f"리비전 {rev}")
            print("\nI2C 통로는 열렸다. 색을 칠하려면: python gpu.py 00ff00")
        finally:
            api.close()
        return 0

    if arg.lower() == "off":
        r = g = b = 0
    else:
        t = arg.lstrip("#")
        if len(t) != 6:
            print("색은 00ff00 같은 6자리로 써줘.")
            return 1
        r, g, b = (int(t[i:i + 2], 16) for i in (0, 2, 4))

    st = set_color(r, g, b)
    return 0 if st == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
