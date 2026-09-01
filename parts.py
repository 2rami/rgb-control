"""부품별 색 덮어쓰기와 "이 자리 어디야?" 찾기.

대시보드에서 케이스 그림을 눌러 부품 하나만 다른 색으로 만들거나,
어느 팬이 어느 채널인지 눈으로 확인할 때 쓴다.

부품 이름
    top1, left1 ...  케이스 그림의 팬 자리
    top1#in          그 팬의 안쪽 링만
    top1#out         그 팬의 바깥 테두리만
    ram              램 두 짝
    gpu              그래픽카드 (Razer 컨트롤러)
    speaker          스피커

★유니팬 SL Infinity 는 링이 둘이다
    안쪽 링과 바깥 테두리가 서로 다른 채널이라 따로 색을 줄 수 있다.
    짝수 채널이 안쪽, 홀수 채널이 바깥이다 (실측으로 확인).
    이름 뒤에 #in / #out 을 붙이면 그 링만 바뀌고, 안 붙이면 둘 다 바뀐다.

덮어쓴 색은 layout.json 에 남는다. 껐다 켜도 그대로다.
"""

import json
import time
from pathlib import Path

from openrgb.utils import RGBColor

import fan

SAVE = Path(__file__).with_name("layout.json")

# 케이스 그림의 자리 이름 -> 팬 자리. 처음에는 순서대로 짐작해 두고,
# 사람이 대시보드에서 "찾기"를 눌러 실제와 맞춘다.
DEFAULT_MAP = {
    "top1": "f00", "top2": "f01", "top3": "f02",
    "left1": "f10", "right1": "f20", "right2": "f30",
}

DEVICE_PARTS = ("ram", "gpu", "speaker")

# 찾기 표시는 이 색으로 몇 초 깜빡인다. 어떤 배색에서도 눈에 띈다.
FIND_COLOR = RGBColor(255, 255, 255)
FIND_SECONDS = 4.0

# 자리 열두 개를 한 번에 구분하려고 쓰는 색. fan.all_slots() 순서와 짝이다.
#   f00 f01 f02 | f10 f11 f12 | f20 f21 f22 | f30 f31 f32
# 사진 한 장으로 가릴 수 있게 서로 최대한 먼 색을 골랐다.
LABEL_COLORS = [
    (255, 0, 0),     (0, 255, 0),     (0, 80, 255),      # 빨강 초록 파랑
    (255, 255, 0),   (0, 255, 255),   (255, 0, 255),     # 노랑 청록 보라
    (255, 120, 0),   (255, 255, 255), (140, 0, 255),     # 주황 하양 남보라
    (0, 255, 140),   (255, 105, 180), (120, 90, 40),     # 민트 분홍 갈색
]
LABEL_NAMES = ["빨강", "초록", "파랑", "노랑", "청록", "보라",
               "주황", "하양", "남보라", "민트", "분홍", "갈색"]


def _blank():
    return {"map": dict(DEFAULT_MAP), "colors": {}}


def load():
    try:
        data = json.loads(SAVE.read_text(encoding="utf-8"))
    except Exception:
        return _blank()
    out = _blank()
    if isinstance(data.get("map"), dict):
        out["map"].update({k: v for k, v in data["map"].items()
                           if fan.parse_slot(v)})
    if isinstance(data.get("colors"), dict):
        out["colors"] = {k: v for k, v in data["colors"].items()
                         if isinstance(v, str) and len(v.lstrip("#")) == 6}
    return out


def save(state):
    try:
        SAVE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return True
    except Exception:
        return False


def hex_to_rgb(text):
    t = text.lstrip("#")
    return RGBColor(int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))


class Parts:
    """부품별 색과 찾기 상태를 들고 있는다.

    조명 루프가 매 프레임 apply() 를 부른다. 아무것도 안 정해져 있으면
    그냥 넘어가므로 비용이 거의 없다.
    """

    def __init__(self):
        st = load()
        self.map = st["map"]          # 자리이름 -> 팬 자리(f00 등)
        self.colors = st["colors"]    # 부품이름 -> "rrggbb"
        self.finding = None           # 지금 깜빡이는 부품
        self.find_until = 0.0

    # ------------------------------------------------------------ 설정

    def set_color(self, part, hexcolor):
        """색을 정한다. hexcolor 가 None 이면 해제(효과를 따라간다).

        팬 전체(top1)를 정하면 그 팬의 링별 설정은 지운다. 안 그러면
        "전체를 빨강으로 했는데 테두리만 파랑"인 상태가 남아 헷갈린다.
        """
        if hexcolor:
            self.colors[part] = str(hexcolor).lstrip("#").lower()
            if "#" not in part:
                self.colors.pop(f"{part}#in", None)
                self.colors.pop(f"{part}#out", None)
        else:
            self.colors.pop(part, None)
            if "#" not in part:
                self.colors.pop(f"{part}#in", None)
                self.colors.pop(f"{part}#out", None)
        self._persist()

    def set_slot(self, spot, slot):
        """케이스 그림의 자리에 어떤 팬 자리를 붙일지 정한다."""
        if spot in self.map and fan.parse_slot(slot):
            self.map[spot] = slot
            self._persist()
            return True
        return False

    @staticmethod
    def base_spot(part):
        """top1#out -> top1. 자리 이름만 떼어낸다."""
        return part.split("#", 1)[0]

    def next_slot(self, spot, step=1):
        """다음 팬 자리로 넘긴다. 어느 팬인지 찾을 때 하나씩 돌려 본다."""
        slots = fan.all_slots()
        cur = self.map.get(spot, slots[0])
        i = (slots.index(cur) + step) % len(slots) if cur in slots else 0
        self.map[spot] = slots[i]
        self._persist()
        return slots[i]

    def label_all(self, seconds=240.0):
        """열두 자리를 저마다 다른 색으로 칠한다.

        어느 자리에 팬이 실제로 물려 있는지, 그리고 그게 케이스 어디인지를
        한 번에 알아내려고 만들었다. 하나씩 켜 보면 열두 번을 물어야 한다.
        """
        self.labeling_until = time.time() + seconds

    def labeling(self):
        return time.time() < getattr(self, "labeling_until", 0.0)

    def stop_labeling(self):
        self.labeling_until = 0.0

    def find(self, part, seconds=FIND_SECONDS):
        """그 부품을 잠깐 하얗게 만든다. 눈으로 찾으라고."""
        self.finding = part
        self.find_until = time.time() + seconds

    def _persist(self):
        save({"map": self.map, "colors": self.colors})

    def snapshot(self):
        return {
            "map": dict(self.map),
            "colors": dict(self.colors),
            "finding": self.finding if time.time() < self.find_until else None,
            "labeling": self.labeling(),
            "labels": {sid: LABEL_NAMES[i]
                       for i, sid in enumerate(fan.all_slots())},
            "slots": fan.all_slots(),
        }

    # ------------------------------------------------------------ 칠하기

    def _active_find(self):
        if self.finding and time.time() < self.find_until:
            return self.finding
        self.finding = None
        return None

    def apply_fans(self, colors):
        """팬 색 배열에 부품별 색과 찾기 표시를 덮어쓴다."""
        if self.labeling():
            total = len(colors)
            for i, sid in enumerate(fan.all_slots()):
                port, daisy = fan.parse_slot(sid)
                c = RGBColor(*LABEL_COLORS[i % len(LABEL_COLORS)])
                for j in fan.slot_leds(port, daisy):
                    if j < total:
                        colors[j] = c
            return colors

        finding = self._active_find()
        if not self.colors and not finding:
            return colors

        total = len(colors)
        for spot, slot in self.map.items():
            parsed = fan.parse_slot(slot)
            if not parsed:
                continue
            # 링마다 따로 본다. 0 = 안쪽, 1 = 바깥 테두리.
            for ring, tag in ((0, "in"), (1, "out")):
                key = f"{spot}#{tag}"
                want = None
                if finding in (spot, key):
                    want = FIND_COLOR
                elif key in self.colors:
                    want = hex_to_rgb(self.colors[key])
                elif spot in self.colors:
                    want = hex_to_rgb(self.colors[spot])
                if want is None:
                    continue
                for i in fan.slot_leds(*parsed, ring=ring):
                    if i < total:
                        colors[i] = want
        return colors

    def device_color(self, part):
        """램·글카·스피커에 쓸 색. 정한 게 없으면 None."""
        if self._active_find() == part:
            return FIND_COLOR
        c = self.colors.get(part)
        return hex_to_rgb(c) if c else None
