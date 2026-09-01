"""모니터가 켜져 있는지 꺼져 있는지 알아낸다.

    python display.py            지금 상태를 계속 찍어 본다
    python display.py --learn    전원 버튼을 알아보게 한 번 가르친다

왜 필요한가
    모니터가 꺼지면 방을 보는 사람이 없다. 그때 케이스 안이 계속 밝으면
    잘 때 눈부시고 전기도 아깝다. 화면이 꺼지면 조명도 같이 끄고, 켜지면
    원래대로 돌아온다.

어떻게 아는가 - 신호가 셋이다
    ★유휴 시간(GetLastInputInfo)으로 짐작하면 안 된다. 사람이 안 만져도
    영상을 보는 중이면 화면은 켜져 있다. 반대로 손으로 화면만 끄면 유휴
    시간은 0 이다. 둘은 다른 이야기다.

    (1) 윈도우가 화면을 재웠나
        RegisterPowerSettingNotification(GUID_CONSOLE_DISPLAY_STATE)
        절전이나 단축키로 꺼지는 경우를 잡는다. 소식을 받으려면 창이
        하나 필요해서, 보이지 않는 창을 만들어 거기서 받는다.
        받는 값: 0 꺼짐 / 1 켜짐 / 2 어두워짐(꺼지기 직전)

    (2) 붙어 있는 모니터가 하나라도 있나
        케이블이 빠지거나 그래픽카드가 화면을 놓는 경우를 잡는다.

    (3) ★모니터의 USB 허브가 붙어 있나
        (1)(2) 만으로는 모자란다. 모니터 전원 버튼으로 끄면 윈도우는
        아무것도 모른다. 화면이 잠든 것도 아니고 케이블이 빠진 것도
        아니라서 소식도 안 오고 모니터 수도 안 줄어든다. 모니터한테 직접
        묻는 길(DDC/CI)도 있지만 전원 상태 항목은 지원하는 모델이 드물다.

        대신 요즘 모니터는 대개 USB 허브를 품고 있고, 모니터가 꺼지면 그
        허브가 통째로 빠진다. 연결해제 소리가 그래서 난다. 그걸 지켜본다.
        무엇이 빠지는지는 컴퓨터마다 다르니 한 번 배워 둔다(--learn).
        배운 것은 monitor_usb.json 에 남고 그 뒤로는 저절로 쓰인다.

    셋 중 하나라도 "꺼졌다"고 하면 꺼진 것으로 본다.
"""

import ctypes
import json
import pathlib
import sys
import threading
import time
from ctypes import wintypes

# 화면 전원 상태를 알려 달라고 할 때 쓰는 식별자.
# {6FE69556-704A-47A0-8F24-C28D936FDA47}
GUID_CONSOLE_DISPLAY_STATE = (ctypes.c_ubyte * 16)(
    0x56, 0x95, 0xE6, 0x6F, 0x4A, 0x70, 0xA0, 0x47,
    0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)

WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
# 장치가 꽂히거나 빠지면 윈도우가 모든 창에 알린다. 이걸 받으면 USB 를
# 다시 세는 시각을 기다리지 않고 그 자리에서 확인할 수 있다.
# ★이 소식은 메시지 전용 창에는 안 간다. 진짜 창이어야 받는다.
WM_DEVICECHANGE = 0x0219
DBT_DEVNODES_CHANGED = 0x0007
DEVICE_NOTIFY_WINDOW_HANDLE = 0
WS_EX_TOOLWINDOW = 0x00000080
WS_OVERLAPPED = 0x00000000
SM_CMONITORS = 80        # 붙어 있는 모니터 수

OFF, ON, DIMMED = 0, 1, 2

POLL_SECONDS = 2.0

USB_SAVE = pathlib.Path(__file__).with_name("monitor_usb.json")
CM_FILTER_ENUMERATOR = 0x00000001
# ★PRESENT 를 빼면 "여태 본 적 있는 것"을 다 준다. 빠져도 목록에 남아 있어서
# 아무 변화도 안 보인다. 실제로 그래서 못 잡았다.
CM_FILTER_PRESENT = 0x00000100
CM_FILTER = CM_FILTER_ENUMERATOR | CM_FILTER_PRESENT

NUL = "\x00"
BACKSLASH = "\x5c"


class _PowerBroadcastSetting(ctypes.Structure):
    _fields_ = [("PowerSetting", ctypes.c_ubyte * 16),
                ("DataLength", wintypes.DWORD),
                ("Data", ctypes.c_ubyte * 4)]


def usb_ids():
    """지금 붙어 있는 USB 장치 이름들. 못 읽으면 None (빈 집합과 다르다)."""
    try:
        cfg = ctypes.windll.cfgmgr32
        n = wintypes.ULONG()
        f = ctypes.c_wchar_p("USB")
        if cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(n), f, CM_FILTER) != 0:
            return None
        buf = ctypes.create_unicode_buffer(n.value)
        if cfg.CM_Get_Device_ID_ListW(f, buf, n.value, CM_FILTER) != 0:
            return None
        return {x for x in buf[:n.value].split(NUL) if x}
    except Exception:
        return None


def usb_kind(instance_id):
    """장치 이름에서 "어떤 물건인가"만 뽑는다.

    앞이 USB, 가운데가 물건, 뒤가 꽂힌 자리다. 가운데만 쓴다. 꽂힌 자리는
    USB 포트를 옮기면 바뀌는데, 그걸 기억해 두면 옮긴 순간부터 조용히
    못 알아본다. 한 물건이 여러 몫을 하면 &MI_00 같은 꼬리가 붙는데
    그것도 뗀다.
    """
    parts = instance_id.split(BACKSLASH)
    kind = parts[1] if len(parts) > 1 else instance_id
    return kind.split("&MI_")[0]


def load_usb_watch():
    try:
        data = json.loads(USB_SAVE.read_text(encoding="utf-8"))
        return sorted({str(x) for x in data.get("kinds", []) if x})
    except Exception:
        return []


def save_usb_watch(kinds):
    USB_SAVE.write_text(json.dumps({"kinds": sorted(kinds)}, indent=2),
                        encoding="utf-8")


class Monitor:
    """모니터 전원 상태를 들고 있는다. 바뀌면 알려준다.

    on_change(켜짐여부) 를 주면 켜짐/꺼짐이 뒤집힐 때마다 부른다.
    """

    def __init__(self, on_change=None):
        self.on_change = on_change
        self.state = ON          # 모르면 켜진 것으로 본다. 조명을 함부로 안 끈다
        self.attached = 1        # 같은 이유로 하나는 붙어 있다고 본다
        self.usb_ok = True       # 배운 장치가 붙어 있나
        self.ok = False
        self.error = ""
        self.watch = load_usb_watch()
        self._usb_seen = False   # 이번에 한 번이라도 본 적 있나
        self._wake = threading.Event()   # 장치가 바뀌었으니 지금 세라
        self._thread = None
        self._hwnd = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        threading.Thread(target=self._poll, daemon=True).start()
        return self

    def is_on(self):
        """어두워진 상태(2)는 아직 켜진 것으로 친다. 곧 꺼지지만 지금은 보인다.

        세 신호 중 하나라도 꺼졌다고 하면 꺼진 것이다.
        """
        return self.state != OFF and self.attached != 0 and self.usb_ok

    # ------------------------------------------------------------ 내부

    def _set(self, **kw):
        """신호 하나를 갱신하고, 켜짐 여부가 뒤집혔을 때만 알린다."""
        was_on = self.is_on()
        for k, v in kw.items():
            setattr(self, k, v)
        if self.on_change and self.is_on() != was_on:
            try:
                self.on_change(self.is_on())
            except Exception:
                pass

    def _check_usb(self):
        """배운 장치가 하나라도 붙어 있나. 전원 버튼을 잡는 유일한 길이다.

        ★"하나라도 붙어 있으면 켜진 것"이다. 모두 없어야 꺼진 것으로 본다.
        허브에 꽂아 둔 헤드셋만 빼도 꺼졌다고 판단해 버리면 안 되기 때문이다.

        ★한 번도 본 적 없으면 아무 말도 안 한다. 모니터 USB 선을 아예 안
        꽂았을 수도 있는데, 그걸 "꺼짐"으로 읽으면 조명이 영영 안 켜진다.
        """
        if not self.watch:
            return True
        now = usb_ids()
        if now is None:
            return True                      # 못 읽었으면 판단하지 않는다
        kinds = {usb_kind(x) for x in now}
        if any(k in kinds for k in self.watch):
            self._usb_seen = True
            return True
        return not self._usb_seen            # 본 적 없으면 아직 판단 안 한다

    def _poll(self):
        """물어봐야 아는 신호들.

        평소엔 몇 초마다 세지만, 장치가 꽂히거나 빠졌다는 소식이 오면 그
        자리에서 다시 센다. 세는 시각만 기다리면 모니터를 끄고도 몇 초 동안
        조명이 켜져 있어 굼떠 보인다.
        """
        get = ctypes.windll.user32.GetSystemMetrics
        while True:
            try:
                self._set(attached=get(SM_CMONITORS), usb_ok=self._check_usb())
            except Exception:
                pass
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_POWERBROADCAST and wparam == PBT_POWERSETTINGCHANGE:
            setting = ctypes.cast(
                lparam, ctypes.POINTER(_PowerBroadcastSetting)).contents
            if bytes(setting.PowerSetting) == bytes(GUID_CONSOLE_DISPLAY_STATE):
                self._set(state=setting.Data[0])
            return 1
        if msg == WM_DEVICECHANGE and wparam == DBT_DEVNODES_CHANGED:
            self._wake.set()
            return 1
        # 창이 만들어지는 동안에도 메시지가 들어온다. 그때는 아직 형 지정이
        # 안 끝났을 수 있어서, 기본 처리로 넘길 때 예외를 삼킨다.
        try:
            return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception:
            return 0

    def _run(self):
        try:
            user32 = ctypes.windll.user32
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM)
            # 파이썬이 콜백을 치우지 않게 붙들고 있어야 한다. 안 그러면
            # 윈도우가 부르는 순간 없어진 함수를 부르게 된다.
            self._proc = WNDPROC(self._wndproc)

            class WNDCLASS(ctypes.Structure):
                _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                            ("cbClsExtra", ctypes.c_int),
                            ("cbWndExtra", ctypes.c_int),
                            ("hInstance", wintypes.HINSTANCE),
                            ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                            ("hbrBackground", wintypes.HBRUSH),
                            ("lpszMenuName", wintypes.LPCWSTR),
                            ("lpszClassName", wintypes.LPCWSTR)]

            # ★인자 형을 알려주지 않으면 파이썬이 큰 수를 32비트로 잘라 넘긴다.
            # 64비트 윈도우에서 그러면 창이 안 만들어진다(그냥 NULL 이 온다).
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
            user32.DefWindowProcW.restype = ctypes.c_long
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
            ctypes.windll.kernel32.GetModuleHandleW.restype = wintypes.HMODULE

            wc = WNDCLASS()
            wc.lpfnWndProc = self._proc
            wc.lpszClassName = "RgbControlDisplayWatch"
            wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            if not user32.RegisterClassW(ctypes.byref(wc)):
                raise OSError("창 종류 등록 실패")

            # 진짜 창이지만 보여주지 않는다(ShowWindow 를 안 부른다).
            # WS_EX_TOOLWINDOW 를 주면 작업 표시줄과 Alt+Tab 에도 안 나온다.
            self._hwnd = user32.CreateWindowExW(
                WS_EX_TOOLWINDOW, wc.lpszClassName, "rgb-control",
                WS_OVERLAPPED, 0, 0, 0, 0,
                None, None, wc.hInstance, None)
            if not self._hwnd:
                raise OSError("창 만들기 실패")

            if not user32.RegisterPowerSettingNotification(
                    wintypes.HANDLE(self._hwnd),
                    ctypes.byref(GUID_CONSOLE_DISPLAY_STATE),
                    DEVICE_NOTIFY_WINDOW_HANDLE):
                raise OSError("화면 전원 알림 등록 실패")

            self.ok = True
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            self.ok, self.error = False, str(e)

    def snapshot(self):
        return {"ok": self.ok, "error": self.error, "on": self.is_on(),
                "state": self.state, "attached": self.attached,
                "usb_ok": self.usb_ok, "usb_watch": self.watch}


def learn(timeout=90):
    """모니터를 껐다 켜게 해서, 그때 빠지는 USB 장치를 기억한다."""
    before = usb_ids()
    if before is None:
        print("USB 장치 목록을 못 읽는다. 여기서 멈춘다.")
        return 1
    print(f"지금 USB 장치 {len(before)}개.")
    print()
    print("  이제 모니터를 전원 버튼으로 끄세요. 알아서 잡습니다.")
    print(f"  {timeout}초 안에 안 끄면 그냥 끝냅니다.")
    print()

    gone = set()
    for i in range(timeout):
        time.sleep(1)
        now = usb_ids()
        if now is None:
            continue
        missing = before - now
        if missing:
            gone = missing
            break
        print(f"\r  기다리는 중... {i + 1}초", end="", flush=True)
    print()

    if not gone:
        print("아무 장치도 안 빠졌습니다.")
        print("이 모니터는 USB 허브가 없거나, 허브 선이 컴퓨터에 안 꽂혀 있습니다.")
        print("모니터 뒤 USB 선(네모난 쪽)을 본체에 꽂고 다시 해 보세요.")
        return 1

    kinds = sorted({usb_kind(x) for x in gone})
    print(f"모니터가 꺼질 때 빠지는 장치 {len(gone)}개를 봤습니다:")
    for g in sorted(gone):
        print(f"    {g}")
    print()
    print("이렇게 기억합니다 (꽂은 자리는 빼고 물건만):")
    for k in kinds:
        print(f"    {k}")
    save_usb_watch(kinds)
    print()
    print(f"{USB_SAVE.name} 에 저장했습니다. 이제 모니터를 다시 켜세요.")
    return 0


def main():
    if "--learn" in sys.argv:
        return learn()

    names = {OFF: "꺼짐", ON: "켜짐", DIMMED: "어두워짐"}
    m = Monitor(on_change=lambda on: print(
        f"\n  -> 화면이 {'켜졌다' if on else '꺼졌다'}"))
    m.start()
    time.sleep(1)
    if not m.ok:
        print("감시를 시작하지 못했다:", m.error)
        return 1
    if not m.watch:
        print("※ 전원 버튼은 아직 못 알아봅니다."
              " 'python display.py --learn' 을 한 번 하세요.")
    print("화면 전원을 지켜본다. 모니터를 꺼 보면 바뀐다. 멈추려면 Ctrl+C\n")
    try:
        while True:
            print(f"\r  지금: {names.get(m.state, m.state)}"
                  f" / 모니터 {m.attached}대 / USB {'있음' if m.usb_ok else '없음'}"
                  f" -> {'켜짐' if m.is_on() else '꺼짐'}   ", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
