"""Kraken Elite LCD 를 작은 화면처럼 쓴다.

    python lcd_monitor.py mirror            마우스 주변을 실시간으로 비춘다
    python lcd_monitor.py mirror --box 500  비추는 정사각형 한 변 (기본 640)
    python lcd_monitor.py mirror --at 100,200   따라다니지 않고 그 자리 고정
    python lcd_monitor.py image 그림.png     그림 한 장 띄우기
    python lcd_monitor.py image 그림.png --hq  풀컬러로 (느리지만 제일 곱다)
    python lcd_monitor.py stats             CPU·GPU 상태판
    python lcd_monitor.py text 안녕하세요     큰 글자
    python lcd_monitor.py off               장치 기본 화면으로 되돌리기

화질과 속도
    GIF 256색   장당 16ms (초당 62장)  <- 기본. 글자·화면 비추기에 충분하다
    RGBA 무압축 장당 425ms (초당 2.4장) <- 사진 한 장 곱게 띄울 때만

    예전에 64색을 쓰다가 "영상은 못 볼 정도"라는 말을 들었다. 원인은 전송
    속도가 아니라 색 수였다. 256색으로 올려도 장당 16ms 라 손해가 없다.

화면이 둥글다
    패널은 640x640 사각형인데 보이는 건 그 안의 원이다. 네 귀퉁이는 잘려
    안 보이므로, 글자나 중요한 것은 가운데 원 안에 넣어야 한다.

★CAM 과 같이 못 쓴다
    NZXT CAM 이 켜져 있으면 장치를 못 연다. cam_off_quiet.bat 으로 내리고
    쓴 다음 cam_on_quiet.bat 으로 되살린다. 전송 도중에 강제로 끊으면
    HID 통로가 굳어서 재부팅해야 하는 일이 있으니, Ctrl+C 로 얌전히 끝내라.
"""

import argparse
import math
import sys
import time

from PIL import Image, ImageDraw, ImageFont

import owner
import lcd_stream as L

RES = 640
FONT_PATHS = ["malgunbd.ttf", "malgun.ttf", "arial.ttf"]


def font(size):
    for name in FONT_PATHS:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def centered(draw, text, y, size, fill):
    """가운데 정렬해서 한 줄 그린다. 둥근 화면이라 가운데가 안전하다."""
    f = font(size)
    w = draw.textbbox((0, 0), text, font=f)[2]
    draw.text(((RES - w) // 2, y), text, font=f, fill=fill)


# ----------------------------------------------------------------- 화면 비추기

def grab_region(sct, box, at=None):
    """화면에서 정사각형 한 조각을 떠온다.

    at 이 없으면 마우스를 따라간다. 마우스가 있는 곳이 지금 보고 있는 곳이라
    가장 쓸모 있는 조각이다.
    """
    mon = sct.monitors[1]
    if at is None:
        try:
            import ctypes
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            cx, cy = pt.x, pt.y
        except Exception:
            cx = mon["left"] + mon["width"] // 2
            cy = mon["top"] + mon["height"] // 2
    else:
        cx, cy = at

    half = box // 2
    left = min(max(cx - half, mon["left"]), mon["left"] + mon["width"] - box)
    top = min(max(cy - half, mon["top"]), mon["top"] + mon["height"] - box)
    shot = sct.grab({"left": left, "top": top, "width": box, "height": box})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def cmd_mirror(args):
    import mss

    dev, ctx = L.open_device()
    stream = L.Stream(dev)
    delay = 1.0 / args.fps
    n = 0
    t0 = time.time()
    try:
        with mss.mss() as sct:
            print(f"비추는 중 (한 변 {args.box}px, 최대 {args.fps}fps). 멈추려면 Ctrl+C")
            while True:
                img = grab_region(sct, args.box, args.at)
                stream.send(L.to_gif(L.fit(img, dev.orientation)))
                n += 1
                if n % 20 == 0:
                    fps = n / (time.time() - t0)
                    print(f"\r  {n}장  초당 {fps:.1f}장   ", end="", flush=True)
                time.sleep(delay)
    except KeyboardInterrupt:
        print("\n멈춤")
    finally:
        finish(dev, ctx)


# ----------------------------------------------------------------- 진단용

def draw_spin(t):
    """검은 바탕에 도는 선 하나. 초당 한 바퀴.

    ★내용이 거의 없어서 압축하면 아주 작아진다(수 KB). 전송량이 원인이라면
    이건 매끄러워야 한다. 이것마저 끊기면 원인은 데이터 양이 아니라
    장치가 실제로 그려 주는 속도다. 둘을 가르려고 만들었다.
    """
    import math

    img = Image.new("RGB", (RES, RES), (0, 0, 0))
    d = ImageDraw.Draw(img)
    c = RES // 2
    d.ellipse([20, 20, RES - 20, RES - 20], outline=(30, 40, 55), width=2)
    a = (t % 1.0) * 2 * math.pi - math.pi / 2
    d.line([c, c, c + math.cos(a) * 280, c + math.sin(a) * 280],
           fill=(255, 255, 255), width=10)
    # 12시 방향 표시 - 한 바퀴가 언제 도는지 눈으로 세기 쉽게
    d.ellipse([c - 12, 18, c + 12, 42], fill=(255, 80, 80))
    return img


def draw_sync(hexcolor):
    """조명과 같은 색으로 화면을 채운다.

    가운데는 밝고 가장자리로 갈수록 어두워지게 해서 밋밋한 원판이 아니라
    빛나는 것처럼 보이게 했다. 둥근 화면이라 이 모양이 잘 맞는다.
    """
    t = (hexcolor or "9bd7ff").lstrip("#")
    r, g, b = (int(t[i:i + 2], 16) for i in (0, 2, 4))

    img = Image.new("RGB", (RES, RES), (0, 0, 0))
    d = ImageDraw.Draw(img)
    steps = 26
    for i in range(steps, 0, -1):
        k = i / steps
        rr = int(RES / 2 * k)
        # 바깥으로 갈수록 어둡게. 0.25 를 바닥으로 둬서 테두리가 죽지 않게.
        f = 0.25 + 0.75 * (1 - k) ** 1.4
        d.ellipse([RES // 2 - rr, RES // 2 - rr, RES // 2 + rr, RES // 2 + rr],
                  fill=(int(r * f), int(g * f), int(b * f)))
    return img


# ----------------------------------------------------------------- 상태판

def draw_stats():
    import psutil

    img = Image.new("RGB", (RES, RES), (8, 10, 16))
    d = ImageDraw.Draw(img)

    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    gpu = gpu_stats()

    # 바깥 테두리 - 화면이 둥글다는 걸 이용해 원으로 두른다.
    d.ellipse([6, 6, RES - 6, RES - 6], outline=(40, 60, 80), width=3)

    centered(d, time.strftime("%H:%M"), 70, 120, (230, 240, 255))
    ring(d, 200, cpu, "CPU", f"{cpu:.0f}%", (90, 190, 255))
    if gpu:
        ring(d, 330, gpu["util"], "GPU", f"{gpu['temp']}°C", (255, 140, 90))
        centered(d, f"{gpu['util']}%  {gpu['name'][:22]}", 455, 26, (120, 140, 160))
    ring(d, 460 if not gpu else 500, mem, "RAM", f"{mem:.0f}%", (160, 220, 160))
    return img


def ring(d, y, pct, label, value, color):
    """가로 막대 하나. 왼쪽에 이름, 오른쪽에 값."""
    x0, x1 = 120, RES - 120
    d.text((x0, y - 34), label, font=font(28), fill=(120, 140, 160))
    f = font(30)
    w = d.textbbox((0, 0), value, font=f)[2]
    d.text((x1 - w, y - 36), value, font=f, fill=(200, 215, 235))
    d.rounded_rectangle([x0, y, x1, y + 14], 7, fill=(28, 34, 46))
    fill_w = int((x1 - x0) * max(0.0, min(100.0, pct)) / 100)
    if fill_w > 4:
        d.rounded_rectangle([x0, y, x0 + fill_w, y + 14], 7, fill=color)


_gpu_cache = {"at": 0.0, "data": None}


def gpu_stats():
    """nvidia-smi 를 2초에 한 번만 부른다. 매 프레임 부르면 창이 깜빡인다."""
    import subprocess

    now = time.time()
    if now - _gpu_cache["at"] < 2.0:
        return _gpu_cache["data"]
    data = None
    try:
        si = None
        if hasattr(subprocess, "STARTUPINFO"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=0x08000000, startupinfo=si)
        if r.returncode == 0 and r.stdout.strip():
            name, temp, util = (x.strip() for x in r.stdout.strip().splitlines()[0].split(","))
            data = {"name": name, "temp": int(temp), "util": int(util)}
    except Exception:
        data = None
    _gpu_cache.update(at=now, data=data)
    return data


def cmd_stats(args):
    dev, ctx = L.open_device()
    stream = L.Stream(dev)
    try:
        print("상태판 표시 중. 멈추려면 Ctrl+C")
        while True:
            stream.send(L.to_gif(L.fit(draw_stats(), dev.orientation)))
            time.sleep(1.0 / args.fps)
    except KeyboardInterrupt:
        print("\n멈춤")
    finally:
        finish(dev, ctx)


# ----------------------------------------------------------------- 그림 / 글자

def cmd_image(args):
    dev, ctx = L.open_device()
    try:
        img = L.fit(Image.open(args.path), dev.orientation)
        stream = L.Stream(dev)
        if args.hq:
            stream.send(L.to_rgba(img), L.KIND_RGBA)
            print("풀컬러로 띄움")
        else:
            stream.send(L.to_gif(img))
            print("256색으로 띄움")
        # 화면에 남겨두고 손만 뗀다. 되돌리려면 off 를 쓴다.
        ctx.__exit__(None, None, None)
    except Exception:
        finish(dev, ctx)
        raise


def cmd_text(args):
    dev, ctx = L.open_device()
    try:
        img = Image.new("RGB", (RES, RES), (0, 0, 0))
        d = ImageDraw.Draw(img)
        words = args.words
        # 둥근 화면이라 가로로 길면 잘린다. 글자 크기를 폭에 맞춰 줄인다.
        size = 150
        while size > 24:
            f = font(size)
            if d.textbbox((0, 0), words, font=f)[2] < RES - 120:
                break
            size -= 6
        centered(d, words, (RES - size) // 2, size, (255, 255, 255))
        L.Stream(dev).send(L.to_gif(img))
        print(f"글자 크기 {size}로 띄움")
        ctx.__exit__(None, None, None)
    except Exception:
        finish(dev, ctx)
        raise


def cmd_off(args):
    dev, ctx = L.open_device()
    finish(dev, ctx)
    print("장치 기본 화면으로 되돌림")


def finish(dev, ctx):
    """화면을 장치 기본(액체 온도)으로 돌리고 USB 를 놓는다.

    이걸 안 하면 마지막 프레임이 얼어붙은 채 남고, CAM 도 화면을 못 가져간다.
    """
    try:
        dev._delete_all_buckets()
    except Exception:
        pass
    try:
        ctx.__exit__(None, None, None)
    except Exception:
        pass


def main():
    owner.require_free("LCD 를 직접 만지기")
    ap = argparse.ArgumentParser(add_help=False)
    sub = ap.add_subparsers(dest="cmd")

    m = sub.add_parser("mirror")
    m.add_argument("--box", type=int, default=640)
    m.add_argument("--at", type=lambda s: tuple(int(x) for x in s.split(",")), default=None)
    m.add_argument("--fps", type=float, default=30)
    m.set_defaults(fn=cmd_mirror)

    s = sub.add_parser("stats")
    s.add_argument("--fps", type=float, default=2)
    s.set_defaults(fn=cmd_stats)

    i = sub.add_parser("image")
    i.add_argument("path")
    i.add_argument("--hq", action="store_true")
    i.set_defaults(fn=cmd_image)

    t = sub.add_parser("text")
    t.add_argument("words", nargs="+")
    t.set_defaults(fn=cmd_text)

    o = sub.add_parser("off")
    o.set_defaults(fn=cmd_off)

    args = ap.parse_args()
    if not getattr(args, "fn", None):
        print(__doc__)
        return 1
    if args.cmd == "text":
        args.words = " ".join(args.words)
    try:
        args.fn(args)
    except Exception as e:
        print(f"실패: {e!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
