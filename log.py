"""로그 한 줄 쓰기. 대시보드와 트레이가 같이 쓴다.

★크기를 제한하는 이유
    한 줄씩 쌓기만 하면 루프가 한 번 어긋났을 때 로그가 순식간에 부푼다.
    실제로 영상이 초당 한 번씩 다시 시작하는 버그가 다섯 시간 돌아 3MB 가
    됐고, 정작 왜 그러는지 찾을 때는 그 스팸을 헤치고 봐야 했다.

★파이썬의 비명(stderr)까지 여기서 맡는 이유
    창 없이 도는 프로그램(pythonw)은 stderr 가 갈 데가 없어서, 터져도
    이유가 아무데도 안 남는다. 그래서 같은 파일로 돌린다.

    그런데 윈도우는 열려 있는 파일의 이름을 못 바꾼다. 즉 파일을 붙들고
    있는 쪽과 갈아 끼우는 쪽이 같아야 "닫고 -> 바꾸고 -> 다시 연다"는
    순서를 지킬 수 있다. 그래서 둘을 한 곳에 뒀다.
"""

import faulthandler
import sys
import time
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024


def writer(path, capture_stderr=False):
    """그 파일에 쓰는 say 함수를 만들어 돌려준다."""
    path = Path(path)
    held = {"f": None}

    def attach():
        if not capture_stderr:
            return
        try:
            held["f"] = path.open("a", encoding="utf-8", buffering=1)
            sys.stderr = held["f"]
            faulthandler.enable(sys.stderr)
        except Exception:
            pass

    def detach():
        f, held["f"] = held["f"], None
        if f is None:
            return
        try:
            faulthandler.disable()   # 닫은 파일에 스택을 쏟지 않게 먼저 뗀다
            sys.stderr = sys.__stderr__
            f.close()
        except Exception:
            pass

    def rotate():
        """넘치면 지난 판 하나만 남기고 새로 시작한다.

        두 판까지만 둔다. 더 오래된 것은 지금까지 한 번도 쓸모가 없었다.
        """
        try:
            if not path.exists() or path.stat().st_size <= MAX_BYTES:
                return
        except Exception:
            return
        detach()
        try:
            old = path.with_suffix(path.suffix + ".1")
            old.unlink(missing_ok=True)
            path.rename(old)
        except Exception:
            pass      # 누가 붙들고 있으면 이번엔 넘어간다. 다음 줄에서 또 본다
        attach()

    def say(msg):
        line = f"{time.strftime('%m-%d %H:%M:%S')}  {msg}"
        print(line)
        try:
            rotate()
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    rotate()
    attach()
    return say
