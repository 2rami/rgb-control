"""영상(유튜브·파일)을 640x640 그림으로 계속 뽑아 주는 것.

    python video.py "https://youtu.be/..."      혼자 돌려 속도만 재본다

크라켄 LCD 에 영상을 틀기 위해 만들었다. 화면 담당 루프는 "다음 장 줘"만
부르면 되고, 내려받기·디코딩은 여기서 알아서 한다.

왜 스레드를 따로 두나
    ffmpeg 파이프에서 한 장 읽는 것은 막히는(blocking) 일이다. 화면 루프가
    그걸 직접 읽으면, 네트워크가 잠깐 느려질 때 LCD 도 같이 멎고 냉각 상태
    읽기까지 밀린다. 그래서 읽는 것은 뒤에서 돌리고, 화면 루프는 "가장 최근
    장" 한 칸만 집어 간다. 늦으면 몇 장 건너뛰지만 멎지는 않는다.

소리
    영상 소리는 ffplay 로 따로 스피커에 내보낸다. LCD 는 소리를 못 낸다.
    덤으로, 그 소리가 스피커로 나가므로 audio.py 의 루프백에 잡힌다.
    즉 LCD 로 영상을 틀면서 조명이 그 소리에 맞춰 움직이게 할 수 있다.

화면이 둥글다
    가운데를 정사각형으로 잘라 쓴다. 위아래 검은 띠를 남기면 둥근 화면에서
    보이는 부분이 더 줄어든다.
"""

import pathlib
import subprocess
import sys
import threading
import time

from PIL import Image

W = H = 640
FRAME_BYTES = W * H * 3          # rgb24 는 픽셀당 3바이트
CREATE_NO_WINDOW = 0x08000000


def hidden():
    """콘솔 창이 튀어나오지 않게 한다. 대시보드는 창 없이 도는 프로그램이다."""
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


# 재생목록에서 한 번에 가져올 최대 개수. 유튜브 믹스(RD...)는 끝이 없어서
# 제한이 없으면 주소를 푸는 데만 한참 걸린다.
PLAYLIST_MAX = 40

# ★유튜브 로그인 쓰기.
#
# 로그인이 있어야 열리는 것들이 있다 - 나이 제한 영상, 멤버십 전용,
# 내 비공개 재생목록, '나중에 볼 동영상'. 없으면 그런 주소에서
# "Sign in to confirm your age" 같은 게 뜨고 아무것도 안 나온다.
#
# 방법 두 가지를 순서대로 본다.
#
# 1) cookies.txt  <- 권장
#    이 폴더에 cookies.txt 를 두면 그걸 쓴다. 한 번만 만들어 두면 계속
#    쓰이고, 크롬이 켜져 있든 말든 상관없다.
#
# 2) 브라우저에서 직접 뽑기
#    ★크롬은 사실상 안 된다. 실측으로 확인한 것:
#      - 크롬이 켜져 있으면 쿠키 파일을 독점으로 잠근다(오류 32
#        ERROR_SHARING_VIOLATION). 공유 읽기로도 못 연다.
#      - 크롬 127 이후는 쿠키를 앱 전용 암호화(app-bound)로 묶는다.
#        파일을 얻어도 다른 프로그램은 못 푼다. 이 PC 는 152 다.
#    파이어폭스는 켜져 있어도 읽힌다. 그래서 파이어폭스를 먼저 본다.
COOKIE_FILE = pathlib.Path(__file__).with_name("cookies.txt")
COOKIE_BROWSERS = ("firefox", "chrome", "edge", "whale")
_cookie_choice = {"opt": None, "how": "", "tried": False}


def cookie_option():
    """yt-dlp 에 넘길 로그인 설정 조각. 없으면 빈 딕셔너리.

    한 번 정해지면 기억한다. 브라우저 쿠키를 뒤지는 데 몇 초 걸리기 때문에
    영상마다 다시 하면 안 된다.
    """
    if _cookie_choice["tried"]:
        return dict(_cookie_choice["opt"] or {})
    _cookie_choice["tried"] = True

    # 크기로 판단하지 않는다. 크기는 내용이 쓸모 있는지와 상관이 없고,
    # 문턱을 잘못 잡으면 멀쩡한 파일을 무시해 놓고 "로그인 안 씀"이라고
    # 거짓말하게 된다. 유튜브 쿠키 줄이 하나라도 있는지를 본다.
    if COOKIE_FILE.exists():
        try:
            body = COOKIE_FILE.read_text(encoding="utf-8", errors="replace")
            rows = [l for l in body.splitlines()
                    if l.strip() and not l.startswith("#") and "youtube" in l]
        except Exception:
            rows = []
        if rows:
            _cookie_choice.update(opt={"cookiefile": str(COOKIE_FILE)},
                                  how=f"cookies.txt ({len(rows)}줄)")
            return dict(_cookie_choice["opt"])

    try:
        from yt_dlp.cookies import load_cookies
    except Exception:
        return {}

    for name in COOKIE_BROWSERS:
        try:
            jar = load_cookies(None, (name, None, None, None), None)
            if any("youtube" in (c.domain or "") for c in jar):
                _cookie_choice.update(opt={"cookiesfrombrowser": (name,)},
                                      how=f"{name} 브라우저")
                return dict(_cookie_choice["opt"])
        except Exception:
            continue
    return {}


def login_status():
    """대시보드에 보여줄 한 줄."""
    cookie_option()
    return _cookie_choice["how"] or "안 씀 (공개 영상만)"


def forget_cookies():
    """cookies.txt 를 새로 넣었을 때 다시 보게 한다."""
    _cookie_choice.update(opt=None, how="", tried=False)


# ffmpeg 이 바로 읽을 수 있는 것들. 유튜브처럼 주소를 풀 필요가 없다.
# Giphy 의 media.giphy.com/...gif 나 .mp4 링크가 여기 해당한다.
DIRECT_EXT = (".gif", ".mp4", ".webm", ".mkv", ".mov", ".m4v", ".apng", ".webp")


def is_direct(url):
    """유튜브를 안 거치고 ffmpeg 에 그대로 줘도 되는 주소인가."""
    low = url.lower().split("?")[0]
    if low.endswith(DIRECT_EXT):
        return True
    # giphy 는 페이지 주소가 아니라 media 주소여야 바로 읽힌다.
    return "media" in low and "giphy.com" in low


def resolve(url):
    """주소 하나에서 실제 스트림 주소와 제목을 뽑는다.

    이미 재생 가능한 주소나 파일 경로면 그대로 돌려준다.
    """
    if not url.startswith("http") or is_direct(url):
        return url, url.rsplit("/", 1)[-1].split("?")[0] or url
    try:
        import yt_dlp
    except ImportError:
        return url, url

    opts = {
        "quiet": True,
        "no_warnings": True,
        # LCD 가 640 이라 원본이 클 이유가 없다. 작을수록 디코딩이 가볍다.
        "format": "best[height<=720]/best",
        "noplaylist": True,
        **cookie_option(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if "entries" in info:
            info = next(e for e in info["entries"] if e)
        return info["url"], info.get("title", url)


def playlist_items(url):
    """재생목록이면 그 안의 주소들을, 아니면 자기 자신 하나를 돌려준다.

    ★주소만 뽑고 스트림 주소는 안 푼다(extract_flat).
    유튜브 스트림 주소는 수명이 짧다. 40개를 미리 다 풀어 두면 뒤쪽 곡은
    차례가 왔을 때 이미 만료돼 있다. 곡마다 그때그때 푼다.
    """
    if not url.startswith("http") or "list=" not in url or is_direct(url):
        return [url]
    try:
        import yt_dlp
    except ImportError:
        return [url]

    opts = {"quiet": True, "no_warnings": True,
            "extract_flat": "in_playlist", "playlistend": PLAYLIST_MAX,
            **cookie_option()}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = [e for e in (info.get("entries") or []) if e]
        out = [e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
               for e in entries]
        return out or [url]
    except Exception:
        return [url]


class Player:
    """영상 한 편을 재생하며 최신 프레임 한 장을 들고 있는다.

    fps 는 ffmpeg 에게 "초당 몇 장으로 뽑아 달라"고 하는 값이다. 원본이
    그보다 느리면 원본 속도가 상한이 된다. LCD 는 초당 30장 넘게 받으므로
    여기가 병목이 되지 않도록 30 으로 둔다.
    """

    def __init__(self, url, fps=30, audio=True, items=None):
        # items 를 주면 그것을 그대로 튼다(대시보드의 재생목록).
        # 안 주면 url 이 재생목록인지 보고 알아서 펼친다(유튜브 믹스 등).
        self.items = list(items) if items else None
        self.url = url
        self.fps = fps
        self.want_audio = audio
        self.title = url
        self.error = ""
        self.done = False
        self.frames = 0
        self.index = 0      # 지금 몇 번째 곡인지
        self.total = 1
        self._fails = 0     # 한 장도 못 뽑고 끝난 곡이 연달아 몇 개인지
        # 곡 제목을 알아내면 이걸 부른다. 재생목록이 제목을 채우는 데 쓴다.
        self.on_title = None

        self._img = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._vproc = None
        self._aproc = None
        self._thread = None
        # ★띄운 프로세스를 전부 여기에 모은다.
        # _vproc/_aproc 만 들고 있으면, 곡을 넘기는 사이에 멈춤이 오면
        # "그때는 죽일 게 없었고 그 뒤에 태어난 것"은 아무도 안 죽인다.
        # 실제로 그렇게 ffplay 가 둘 남아 소리가 겹쳤다.
        self._procs = []

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """멈춘다. 여러 번 불러도 안전하다."""
        self._stop.set()
        self._kill_all()

    def _kill_all(self):
        with self._lock:
            procs, self._procs = list(self._procs), []
        for p in procs:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass
        self._vproc = self._aproc = None

    def _spawn(self, cmd, **kw):
        """프로세스를 띄우고 목록에 넣는다.

        ★띄우기 직전에 멈춤을 한 번 더 본다. 주소를 푸는 데 몇 초 걸리는데
        그 사이에 멈춤이 올 수 있다. 확인 안 하면 멈춘 뒤에 새로 태어난다.
        """
        if self._stop.is_set():
            return None
        pr = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW,
                              startupinfo=hidden(), **kw)
        with self._lock:
            self._procs.append(pr)
        if self._stop.is_set():      # 띄우는 사이에 왔을 수도 있다
            try:
                pr.kill()
            except Exception:
                pass
            return None
        return pr

    def latest(self):
        """가장 최근 한 장. 아직 없으면 None."""
        with self._lock:
            return self._img

    def _run(self):
        """재생목록이면 한 곡씩 이어서 튼다. 끝나면 처음으로 돌아간다."""
        try:
            items = self.items or playlist_items(self.url)
        except Exception as e:
            self.error = f"목록을 못 읽었다: {e}"
            self.done = True
            return
        self.total = len(items)

        idx = 0
        while not self._stop.is_set():
            self.index = idx + 1
            before = self.frames
            try:
                self._play_one(items[idx])
            except Exception as e:
                self.error = f"재생 실패: {e}"
            if self._stop.is_set():
                break

            # ★한 장도 못 뽑았으면 쉬었다 간다.
            # 안 쉬면 못 여는 주소 하나로 ffmpeg 와 유튜브 요청이 끝없이
            # 쏟아진다. 지워진 영상 하나를 초당 몇 번씩 두드린 끝에
            # 유튜브가 이 PC 를 봇으로 보고 막은 적이 있다.
            # 쉬는 시간은 2초에서 시작해 배로 늘리고 1분에서 멈춘다.
            # 한 곡이라도 제대로 나오면 처음부터 다시 센다.
            if self.frames == before:
                self._fails += 1
                self._stop.wait(min(60.0, 2.0 * 2 ** min(self._fails - 1, 5)))
            else:
                self._fails = 0
            idx = (idx + 1) % len(items)
        self._kill_all()      # 남은 것이 없게 한 번 더
        self.done = True

    def _play_one(self, one):
        if self._stop.is_set():
            return
        try:
            stream, title = resolve(one)
            self.title = title
            if self.on_title:
                try:
                    self.on_title(one, title)
                except Exception:
                    pass
        except Exception as e:
            self.error = f"주소를 못 풀었다: {e}"
            return      # 쉬는 것은 _run 이 한 곳에서 맡는다
        # 주소 푸는 데 몇 초 걸린다. 그 사이에 멈춤이 왔을 수 있다.
        if self._stop.is_set():
            return

        # 화면을 꽉 채운다. 16:9 영상이면 좌우가 잘리지만, 둥근 화면에
        # 검은 띠를 남기는 것보다 크게 보이는 쪽이 낫다는 거노 판단이다.
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},fps={self.fps}")
        # GIF 는 몇 초짜리라 그냥 두면 금방 끝난다. 무한 반복으로 돌린다.
        loop = ["-stream_loop", "-1"] if is_direct(self.url) else []
        cmd = (["ffmpeg", "-loglevel", "error"] + loop +
               ["-re", "-i", stream,
                "-an", "-vf", vf, "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        try:
            # ★stderr 를 버리면 안 된다. ffmpeg 가 주소를 못 열거나 형식을
            # 거부해도 조용히 아무것도 안 뱉을 뿐이라, 왜 화면이 안 나오는지
            # 알 길이 없어진다. 실제로 한 번 이것 때문에 헤맸다.
            self._vproc = self._spawn(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
        except FileNotFoundError:
            self.error = "ffmpeg 를 못 찾았다 (PATH 에 없음)"
            self.done = True
            return
        if self._vproc is None:
            return                    # 그 사이에 멈춤이 왔다
        threading.Thread(target=self._watch_errors, daemon=True).start()

        if self.want_audio:
            try:
                self._aproc = self._spawn(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", stream],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                pass   # 소리는 없어도 영상은 나온다

        pipe = self._vproc.stdout
        while not self._stop.is_set():
            raw = _read_exact(pipe, FRAME_BYTES)
            if raw is None:
                break
            img = Image.frombytes("RGB", (W, H), raw)
            with self._lock:
                self._img = img
            if self.frames == 0:
                self.error = ""     # 잘 나오기 시작했으면 앞선 경고는 지운다
            self.frames += 1

        # 한 곡이 끝난 것뿐이다. 다음 곡은 _run 이 이어서 튼다.
        # 소리(ffplay)는 영상보다 늦게 끝나는 일이 잦아서 반드시 같이 죽인다.
        self._kill_all()


    def _watch_errors(self):
        """ffmpeg 가 뱉는 말을 모아 둔다. 마지막 줄이 대개 진짜 원인이다."""
        try:
            for line in iter(self._vproc.stderr.readline, b""):
                text = line.decode("utf-8", "replace").strip()
                if text:
                    self.error = text[:200]
        except Exception:
            pass


def _read_exact(pipe, n):
    """정확히 n 바이트를 읽는다.

    파이프는 요청한 만큼을 한 번에 안 줄 때가 많다. 한 번 읽고 말면 프레임이
    반쯤 잘려 화면이 찢어진다. 예전에 이걸로 한 번 당했다.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = pipe.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    p = Player(sys.argv[1], audio="--no-audio" not in sys.argv).start()
    time.sleep(3)
    if p.error:
        print("실패:", p.error)
        return 1
    print(f"재생 중: {p.title}")
    t0, last = time.time(), 0
    try:
        while not p.done and time.time() - t0 < 20:
            time.sleep(1)
            print(f"\r  {p.frames}장  초당 {(p.frames-last):.0f}장   ", end="", flush=True)
            last = p.frames
    except KeyboardInterrupt:
        pass
    p.stop()
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
