"""껐다 켜도 설정이 그대로 있게 한다.

컴퓨터를 켜면 대시보드가 저절로 뜨는데(작업 스케줄러), 그때마다 조명이
기본값으로 돌아가면 매번 다시 골라야 한다. 마지막으로 고른 것을
settings.json 에 적어 두고 뜰 때 그대로 되돌린다.

왜 이렇게 하나
    ★적어 둔 값을 그대로 믿고 쓰면 안 된다. 파일이 깨졌거나, 예전 판에서
    쓰던 값이 남아 있거나, 손으로 고쳐 놨을 수 있다. 이상한 값 하나가
    대시보드를 못 뜨게 만들면 조명이 통째로 죽는다. 그래서 아는 이름만,
    아는 모양일 때만 받아들이고 나머지는 조용히 버린다.

    ★쓰는 도중에 전원이 나가도 반쪽짜리 파일이 남으면 안 된다. 옆에 새로
    쓰고 다 됐을 때 이름을 바꾼다(그 순간은 쪼개지지 않는다).
"""

import json
import os
import pathlib

SAVE = pathlib.Path(__file__).with_name("settings.json")

LCD_MODES = ("off", "stats", "sync", "mirror", "video", "spin")
PUMP_MODES = ("curve", "fixed")


def _num(v, lo, hi, whole=False):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:                      # NaN 은 비교가 다 거짓이라 따로 걸러낸다
        return None
    x = max(lo, min(hi, x))
    return int(round(x)) if whole else x


def _one_of(v, allowed):
    return v if v in allowed else None


def _text(v, limit):
    return str(v)[:limit] if isinstance(v, str) else None


# 이름 -> 그 값을 검사하는 법. 여기 없는 이름은 저장도 복원도 안 한다.
LIGHT_RULES = {
    "mode": lambda v: _text(v, 30),
    "resume_mode": lambda v: _text(v, 30),
    "speed": lambda v: _num(v, 0.1, 5.0),
    "color": lambda v: _text(v, 6),
    "sync_all": lambda v: bool(v),
    "sync_ram": lambda v: bool(v),
    "sync_solid": lambda v: bool(v),
    "off_with_monitor": lambda v: bool(v),
}

KRAKEN_RULES = {
    "enabled": lambda v: bool(v),
    "pump_mode": lambda v: _one_of(v, PUMP_MODES),
    "pump_duty": lambda v: _num(v, 20, 100, whole=True),
    "lcd_mode": lambda v: _one_of(v, LCD_MODES),
    "mirror_box": lambda v: _num(v, 200, 1440, whole=True),
    "video_url": lambda v: _text(v, 500),
    "video_audio": lambda v: bool(v),
    "play_list": lambda v: None if v is None else _text(v, 40),
    "lcd_off_with_monitor": lambda v: bool(v),
}


def _clean(raw, rules):
    """아는 이름만, 검사를 통과한 것만 남긴다."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, check in rules.items():
        if key not in raw:
            continue
        value = check(raw[key])
        if value is not None:
            out[key] = value
    return out


def load():
    """저장해 둔 설정. 없거나 깨졌으면 빈 것을 준다 - 그럼 기본값이 쓰인다."""
    try:
        raw = json.loads(SAVE.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    return (_clean(raw.get("light"), LIGHT_RULES),
            _clean(raw.get("kraken"), KRAKEN_RULES))


def save(light, kraken):
    """지금 설정을 적어 둔다. 실패해도 조용히 넘어간다.

    설정을 못 적는 것은 불편할 뿐이지만, 여기서 예외가 터지면 조명을 바꾸는
    일 자체가 실패한다. 그건 훨씬 나쁘다.
    """
    try:
        body = json.dumps({"light": _clean(light, LIGHT_RULES),
                           "kraken": _clean(kraken, KRAKEN_RULES)},
                          indent=2, ensure_ascii=False)
        tmp = SAVE.with_suffix(".json.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, SAVE)       # 이 바꿔치기는 쪼개지지 않는다
        return True
    except Exception:
        return False
