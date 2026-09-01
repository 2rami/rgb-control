"""유튜브 로그인 쿠키를 대시보드에서 넣고 빼는 것.

대시보드 화면에서 다 되게 하려고 따로 뺐다. 창구는 셋뿐이다.
    save(text)      붙여넣은 쿠키를 저장
    clear()         지우기
    from_browser()  브라우저에서 직접 뽑아 보기

왜 로그인이 필요한가
    나이 제한 영상, 멤버십 전용, 내 비공개 재생목록, '나중에 볼 동영상'은
    로그인 없이는 안 열린다. 그런 주소를 넣으면 화면이 그냥 안 나온다.

★크롬에서 자동으로 뽑는 것은 사실상 안 된다 (실측)
    - 크롬이 켜져 있으면 쿠키 파일을 독점으로 잠근다.
      공유 읽기로 열어도 오류 32(ERROR_SHARING_VIOLATION).
    - 크롬 127 이후는 쿠키를 앱 전용 암호화로 묶는다. 파일을 얻어도
      다른 프로그램은 못 푼다. 이 컴퓨터 크롬은 152 다.
    파이어폭스는 켜져 있어도 읽히니 그쪽은 자동으로 된다.

    그래서 크롬을 쓰면 확장으로 한 번 내보내 붙여넣는 게 유일한 길이다.
    한 번만 하면 계속 쓰인다.
"""

import json

import video

TAB = "\t"
NL = "\n"
HEADER = "# Netscape HTTP Cookie File"

# 이 확장이 내보낸 것을 그대로 받는다. 다른 확장 것도 형식만 같으면 된다.
EXTENSION = "Get cookies.txt LOCALLY"


def _row(domain, path, secure, expires, name, value):
    """yt-dlp 가 읽는 Netscape 한 줄."""
    return TAB.join([
        domain,
        "TRUE" if domain.startswith(".") else "FALSE",
        path or "/",
        "TRUE" if secure else "FALSE",
        str(int(expires or 0)),
        name or "",
        value or "",
    ])


def _from_json(text):
    """확장이 JSON 으로 준 것을 Netscape 로 바꾼다.

    확장마다 내보내는 형식이 다르다. 어떤 것은 Netscape 텍스트, 어떤 것은
    JSON 배열이다. 사람이 형식을 신경 쓰지 않게 둘 다 받는다.
    """
    items = json.loads(text)
    if isinstance(items, dict):
        items = items.get("cookies") or []
    rows = [HEADER]
    for c in items:
        dom = c.get("domain") or ""
        if not dom:
            continue
        rows.append(_row(dom, c.get("path"), c.get("secure"),
                         c.get("expirationDate") or c.get("expires"),
                         c.get("name"), c.get("value")))
    return NL.join(rows) + NL


def save(text):
    """붙여넣은 내용을 cookies.txt 로 저장한다. (성공여부, 할 말)"""
    text = (text or "").strip()
    if not text:
        return False, "빈 내용이야"

    if text[:1] in "[{":
        try:
            text = _from_json(text)
        except Exception as e:
            return False, f"JSON 을 못 읽었어: {e}"

    if "youtube" not in text:
        return False, ("유튜브 쿠키가 안 보여. youtube.com 을 연 상태에서 "
                       f"'{EXTENSION}' 으로 내보낸 것인지 확인해줘")

    rows = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if not rows:
        return False, "쿠키 줄이 하나도 없어"

    video.COOKIE_FILE.write_text(
        text if text.endswith(NL) else text + NL, encoding="utf-8")
    video.forget_cookies()
    return True, f"쿠키 {len(rows)}줄 저장했어. 이제 로그인이 필요한 영상도 열려"


def clear():
    if video.COOKIE_FILE.exists():
        video.COOKIE_FILE.unlink()
    video.forget_cookies()
    return True, "지웠어. 이제 공개 영상만 봐"


def from_browser():
    """브라우저에서 직접 뽑아 본다. 크롬은 대개 실패한다."""
    try:
        from yt_dlp.cookies import load_cookies
    except Exception:
        return False, "yt-dlp 가 없어"

    why = []
    for name in video.COOKIE_BROWSERS:
        try:
            jar = load_cookies(None, (name, None, None, None), None)
        except Exception as e:
            why.append(f"{name}: {str(e)[:34]}")
            continue

        yt = [c for c in jar if "youtube" in (c.domain or "")]
        if not yt:
            why.append(f"{name}: 로그인 안 돼 있음")
            continue

        rows = [HEADER]
        for c in jar:
            dom = c.domain or ""
            if "youtube" in dom or "google" in dom:
                rows.append(_row(dom, c.path, c.secure, c.expires, c.name, c.value))
        video.COOKIE_FILE.write_text(NL.join(rows) + NL, encoding="utf-8")
        video.forget_cookies()
        return True, f"{name} 에서 유튜브 쿠키 {len(yt)}개 가져왔어"

    return False, "못 가져왔어 - " + " / ".join(why[:3])


def status():
    return {
        "how": video.login_status(),
        "has_file": video.COOKIE_FILE.exists(),
        "extension": EXTENSION,
    }
