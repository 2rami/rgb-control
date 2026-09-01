"""유튜브 로그인 쿠키를 cookies.txt 로 뽑아 둔다.

    python export_cookies.py            브라우저에서 뽑기 (크롬은 꺼야 함)
    python export_cookies.py --check    지금 쓸 수 있는지 확인만

왜 필요한가
    로그인이 있어야 열리는 것들이 있다 - 나이 제한 영상, 멤버십 전용,
    내 비공개 재생목록, '나중에 볼 동영상'.

★크롬은 켜져 있으면 못 뽑는다
    쿠키 파일을 독점으로 잠근다(오류 32). 그리고 크롬 127 이후는 쿠키를
    앱 전용 암호화로 묶어서, 파일을 얻어도 다른 프로그램은 못 푼다.
    이 컴퓨터 크롬은 152 라 그 방식이다. 즉 크롬을 꺼도 안 될 수 있다.

그럴 때는 손으로 한 번만
    크롬 확장 "Get cookies.txt LOCALLY" 를 깔고 youtube.com 에서 내보낸 뒤,
    받은 파일을 이 폴더에 cookies.txt 라는 이름으로 두면 된다.
    한 번 두면 계속 쓰이고 크롬이 켜져 있든 말든 상관없다.
"""

import sys
from pathlib import Path

OUT = Path(__file__).with_name("cookies.txt")
BROWSERS = ("firefox", "chrome", "edge", "whale")


def netscape_lines(jar):
    """yt-dlp 가 읽는 Netscape 형식으로 적는다."""
    yield "# Netscape HTTP Cookie File"
    yield "# export_cookies.py 가 만들었다"
    for c in jar:
        if "youtube" not in (c.domain or "") and "google" not in (c.domain or ""):
            continue
        flag = "TRUE" if (c.domain or "").startswith(".") else "FALSE"
        secure = "TRUE" if c.secure else "FALSE"
        yield "\t".join([c.domain or "", flag, c.path or "/", secure,
                         str(int(c.expires or 0)), c.name or "", c.value or ""])


def main():
    if "--check" in sys.argv:
        import video
        print("지금 상태:", video.login_status())
        if OUT.exists():
            print(f"  {OUT.name} 있음 ({OUT.stat().st_size} 바이트)")
        return 0

    from yt_dlp.cookies import load_cookies

    for name in BROWSERS:
        try:
            jar = load_cookies(None, (name, None, None, None), None)
        except Exception as e:
            print(f"  {name:8s} 실패: {str(e)[:70]}")
            continue
        yt = [c for c in jar if "youtube" in (c.domain or "")]
        if not yt:
            print(f"  {name:8s} 열렸지만 유튜브 쿠키 없음 (로그인 안 돼 있음)")
            continue
        OUT.write_text("\n".join(netscape_lines(jar)) + "\n", encoding="utf-8")
        print(f"\n성공: {name} 에서 유튜브 쿠키 {len(yt)}개를 {OUT.name} 에 저장했다")
        return 0

    print("\n어느 브라우저에서도 못 뽑았다.")
    print(__doc__.split("그럴 때는 손으로 한 번만")[1].rstrip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
