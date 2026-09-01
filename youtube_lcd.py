"""유튜브 영상을 Kraken LCD에 재생한다 (소리는 스피커로).

    python youtube_lcd.py "https://youtu.be/..."
    python youtube_lcd.py "재생목록 URL"
    python youtube_lcd.py "URL" --fps 15 --no-audio

CAM의 Web Integration과 같은 발상이다. 모니터 화면을 복사하는 게 아니라
영상을 따로 열어서 LCD로 보낸다. 그래서 화면에 뭘 띄우든 상관없다.

전송 경로
---------
버킷에 GIF를 넣고 두 칸을 번갈아 쓴다. 자세한 이유는 lcd_stream 참고.

요약하면, 버킷을 안 거치는 '빠른 메모리' 경로는 우리 장치(0x300C)에서
전송만 성공하고 화면에는 안 그려진다. 그쪽이 원하는 Q565 압축 코덱이
파이썬에 없다. 대신 버킷 경로에서 느린 부분(버킷 16개 조회, 111ms)을
걷어내니 장당 13ms까지 내려갔다.
"""

import argparse
import subprocess
import sys
import time

from PIL import Image

import lcd_stream

W = H = 640                      # Kraken Elite LCD 해상도
FRAME_BYTES = W * H * 3          # ffmpeg 가 주는 rgb24 는 픽셀당 3바이트
COLORS = 64                      # GIF 팔레트 색 수. 줄일수록 가볍고 빠르다.
CREATE_NO_WINDOW = 0x08000000


def stream_urls(url):
    """유튜브 URL(영상 또는 재생목록)에서 재생할 스트림 주소 목록을 뽑는다."""
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        # LCD가 640이라 원본이 클 필요가 없다. 작을수록 ffmpeg가 가볍다.
        "format": "best[height<=720]/best",
        "noplaylist": False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info["entries"] if info.get("_type") == "playlist" else [info]
    out = []
    for e in entries:
        if not e:
            continue
        direct = e.get("url")
        if direct:
            out.append((e.get("title", "제목 없음"), direct))
    return out


def open_video(stream, fps):
    """영상을 640x640 rgb24 프레임 스트림으로 연다."""
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-i", stream,
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
               f"crop={W}:{H},fps={fps}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW)


def open_audio(stream):
    """같은 주소에서 소리만 재생한다. 영상과 완벽히 동기되진 않는다."""
    cmd = ["ffplay", "-loglevel", "error", "-nodisp", "-autoexit", "-vn", stream]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW)


def read_exact(pipe, n):
    """파이프에서 정확히 n바이트를 모은다.

    파이프는 요청한 만큼 한 번에 주지 않는다. 한 번만 read하면 프레임이
    조각나서 화면이 어긋난다.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = pipe.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def play_one(stream, title, url, fps, want_audio, orientation=0):
    print(f"\n▶ {title}")
    video = open_video(url, fps)
    audio = open_audio(url) if want_audio else None

    sent = dropped = 0
    t_start = time.time()
    budget = 1.0 / fps

    try:
        while True:
            raw = read_exact(video.stdout, FRAME_BYTES)
            if raw is None:
                break  # 영상 끝

            t0 = time.time()
            try:
                img = Image.frombytes("RGB", (W, H), raw)
                # 패널이 돌아간 채로 달려 있어 미리 돌려 보내야 똑바로 나온다.
                img = lcd_stream.fit(img, orientation)
                stream.send(lcd_stream.to_gif(img, COLORS))
                sent += 1
            except Exception as e:
                dropped += 1
                # 장치가 거절하기 시작하면 계속 쏘는 게 위험하다. 연달아 실패하면 멈춘다.
                if dropped > 10 and dropped > sent:
                    raise RuntimeError(f"전송이 계속 실패한다: {e}")

            spent = time.time() - t0
            if spent < budget:
                time.sleep(budget - spent)

            if sent and sent % fps == 0:
                el = time.time() - t_start
                print(f"\r  {el:5.1f}초  전송 {sent}  실패 {dropped}  "
                      f"실측 {sent/el:.1f} fps   ", end="", flush=True)
    finally:
        video.terminate()
        if audio:
            audio.terminate()
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--no-audio", action="store_true")
    args = ap.parse_args()

    print("영상 정보 가져오는 중...")
    items = stream_urls(args.url)
    if not items:
        print("재생할 영상을 못 찾았어.")
        return 1
    print(f"{len(items)}개 영상")

    dev, ctx = lcd_stream.open_device()
    try:
        stream = lcd_stream.Stream(dev)
        for title, url in items:
            play_one(stream, title, url, args.fps, not args.no_audio, dev.orientation)
    except KeyboardInterrupt:
        print("\n\n멈췄어.")
    finally:
        try:
            dev.set_screen("lcd", "liquid", None)
            print("LCD를 액체 온도 표시로 되돌렸어.")
        except Exception:
            pass
        ctx.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
