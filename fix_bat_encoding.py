"""배치 파일을 한국어 윈도우 cmd 가 제대로 읽는 형태로 저장한다.

    python fix_bat_encoding.py

무슨 문제였나
  파일은 UTF-8 + LF 로 저장돼 있고, 안에서 `chcp 65001` 로 코드페이지를
  바꾸고 있었다. cmd 는 배치 파일을 한 줄 실행할 때마다 파일을 다시 열어
  '바이트 위치'로 되돌아가는데, 그 위치를 현재 코드페이지 기준으로 센다.
  중간에 코드페이지가 바뀌면 셈이 어긋나서 엉뚱한 바이트부터 읽는다.
  그래서 `echo 관리자로...` 한 줄이 조각나 'ESULT:' 같은 파편이 명령어로
  실행되고 "명령이 아닙니다" 오류가 쏟아진다.

어떻게 고치나
  1. 인코딩을 CP949(한국어 윈도우 기본)로 바꾼다. 그러면 chcp 가 필요 없다.
  2. `chcp 65001` 줄을 지운다. 코드페이지가 안 바뀌면 위치도 안 어긋난다.
  3. 줄바꿈을 CRLF 로 바꾼다. cmd 는 LF 만 있는 파일에서 goto·괄호 블록을
     엉뚱하게 처리하는 경우가 있다.

CP949 에 없는 글자가 있으면 그 파일은 건드리지 않고 알려준다.
"""

import re
import sys
from pathlib import Path

CHCP = re.compile(r"^[ \t]*chcp 65001[^\n]*\n", re.MULTILINE)


def main():
    done, skipped = [], []
    for f in sorted(Path(".").glob("*.bat")):
        raw = f.read_bytes()
        if raw[:3] == b"\xef\xbb\xbf":
            raw = raw[3:]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append((f.name, "UTF-8 이 아님 - 이미 CP949 인 듯"))
            continue

        text = CHCP.sub("", text)
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        try:
            data = text.encode("cp949")
        except UnicodeEncodeError as e:
            skipped.append((f.name, f"CP949 에 없는 글자: {e.object[e.start:e.end]!r}"))
            continue

        f.write_bytes(data)
        done.append(f.name)

    for n in done:
        print(f"  변환   {n}")
    for n, why in skipped:
        print(f"  건너뜀 {n}  ({why})")
    print(f"\n총 {len(done)}개 변환")
    return 0


if __name__ == "__main__":
    sys.exit(main())
