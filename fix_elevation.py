"""배치 파일의 '관리자 승격' 부분을 무한 반복 안 하게 고친다.

    python fix_elevation.py

원래 코드는 이랬다.

    net session >nul 2>&1
    if %errorlevel% neq 0 (
        powershell -Command "Start-Process '%~f0' -Verb RunAs -WindowStyle Hidden"
        exit /b
    )

net session 은 Server 서비스가 꺼져 있으면 관리자여도 실패한다. 그러면
관리자로 올라간 자기 자신이 또 자기를 띄우고, 그게 또 띄운다. UAC 가
조용히 통과되는 계정이면 프롬프트도 없이 무한 증식해서 컴퓨터가 멈춘다.
실제로 2026-09-02 에 그것 때문에 멈췄다.

고친 뒤에는 두 겹으로 막는다.
  1. fltmc 로 확인한다. Server 서비스와 무관하게 관리자만 성공한다.
  2. 그래도 못 믿으니 재실행할 때 표식을 붙인다. 표식을 달고 왔는데도
     관리자가 아니면 멈추고 사람에게 알린다. 두 번은 절대 안 돈다.

한 번 고친 파일은 다시 고치지 않는다. 여러 번 돌려도 안전하다.
"""

import re
import sys
from pathlib import Path

MARK = "__elevated__"

OLD = re.compile(
    r"net session >nul 2>&1\s*\n"
    r"if %errorlevel% neq 0 \(\s*\n"
    r"(?:[^\n]*\n)*?"                       # 사이에 echo 같은 줄이 있어도 통과
    r"[ \t]*powershell[^\n]*Start-Process[^\n]*-Verb RunAs(?P<hidden>[^\n\"]*)\"\s*\n"
    r"[ \t]*exit /b\s*\n"
    r"\)\s*\n"
)


def new_block(hidden):
    style = " -WindowStyle Hidden" if "WindowStyle Hidden" in hidden else ""
    return f"""REM ---- 관리자 확인 (무한 반복 방지) ----
REM net session 은 Server 서비스가 꺼져 있으면 관리자여도 실패한다. 그러면
REM 관리자로 올라간 자기 자신이 또 자기를 띄워 끝없이 증식하고 컴퓨터가 멈춘다.
REM fltmc 로 확인하고, 재실행에는 표식을 붙여 딱 한 번만 시도한다.
fltmc >nul 2>&1
if not errorlevel 1 goto _is_admin
if /i "%~1"=="{MARK}" (
    echo.
    echo 관리자로 다시 실행했는데도 관리자가 아닙니다.
    echo 무한 반복을 막기 위해 여기서 멈춥니다.
    echo 이 파일을 오른쪽 클릭 - "관리자 권한으로 실행" 해주세요.
    pause
    exit /b 1
)
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '{MARK}' -Verb RunAs{style}"
exit /b
:_is_admin
"""


def main():
    fixed, skipped = [], []
    for f in sorted(Path(".").glob("*.bat")):
        text = f.read_text(encoding="utf-8")
        if MARK in text:
            skipped.append((f.name, "이미 고쳐짐"))
            continue
        m = OLD.search(text)
        if not m:
            skipped.append((f.name, "승격 코드 없음"))
            continue
        f.write_text(OLD.sub(lambda mm: new_block(mm.group("hidden")), text, count=1),
                     encoding="utf-8")
        fixed.append(f.name)

    for name in fixed:
        print(f"  고침   {name}")
    for name, why in skipped:
        print(f"  건너뜀 {name}  ({why})")
    print(f"\n총 {len(fixed)}개 고침")
    return 0


if __name__ == "__main__":
    sys.exit(main())
