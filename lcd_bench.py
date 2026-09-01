"""두 전송 방식을 같은 조건에서 재서 어느 쪽이 나은지 가린다.

    python lcd_bench.py            둘 다 30장씩
    python lcd_bench.py 60         장수 지정

무엇을 비교하나
    버킷 방식 (GIF)   한 장마다 HID 왕복 7번 + 작은 데이터(38KB)
    빠른 경로 (Q565)  한 장마다 HID 왕복 2번 + 큰 데이터(139KB)

    책상 위 계산으로는 GIF 가 빨라 보인다. 하지만 HID 왕복 하나가 얼마나
    비싼지는 재봐야 알고, 무엇보다 ★버킷 방식은 장치를 지치게 만든다.
    초당 15장을 넘겨 보내면 통로가 망가져 전원을 끊어야 살아난다.
    빠른 경로가 그 문제를 없애 준다면 조금 느려도 그쪽이 맞다.

    그래서 속도만 보지 않고, 중간에 수온을 읽어 통로가 멀쩡한지도 본다.
    다 보내고 나서 수온이 계속 읽히면 그 방식은 장치를 안 괴롭힌 것이다.

★대시보드가 떠 있으면 못 돌린다 (owner.py 가 막는다).
  stop.bat 으로 내리고 돌린 다음 다시 켜라.
"""

import sys
import time

from PIL import Image

import owner
import lcd_stream as L


def make_frames(n, circle):
    """서로 다른 그림 n 장. 같은 그림만 보내면 압축이 유리해져 재는 뜻이 없다."""
    from PIL import ImageDraw

    out = []
    for i in range(n):
        img = Image.new("RGB", L.RES, (0, 0, 0))
        d = ImageDraw.Draw(img)
        for y in range(0, L.RES[1], 8):
            c = ((y + i * 7) % 256, (i * 13) % 256, (255 - y // 3) % 256)
            d.rectangle([0, y, L.RES[0], y + 7], fill=c)
        d.ellipse([100 + i * 3, 200, 300 + i * 3, 400], fill=(255, 255, 255))
        out.append(L.crop_circle(img) if circle else img)
    return out


def alive(dev):
    """수온이 읽히면 HID 통로가 멀쩡하다는 뜻이다."""
    try:
        for k, v, _ in dev.get_status():
            if "liquid" in k.lower():
                return float(v)
    except Exception:
        return None
    return None


def run(dev, name, frames, send, settle=0.0):
    print(f"\n[{name}]  {len(frames)}장")
    sizes = []
    t0 = time.time()
    sent = 0
    try:
        for img in frames:
            data = send(img)
            sizes.append(len(data))
            sent += 1
            if settle:
                time.sleep(settle)
    except Exception as e:
        print(f"  ★{sent}장에서 실패: {e}")
    dt = time.time() - t0
    if sent:
        print(f"  {sent}장 / {dt:.2f}초 = 초당 {sent/dt:5.1f}장  "
              f"(장당 {dt/sent*1000:5.1f}ms, 평균 {sum(sizes)/len(sizes)/1024:.0f}KB)")
    t = alive(dev)
    print(f"  보낸 뒤 수온 읽기: {'OK  ' + str(t) + '도' if t else '★실패 - 통로가 상했다'}")
    return sent == len(frames) and t is not None


def main():
    owner.require_free("속도 재기")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    dev, ctx = L.open_device()
    try:
        o = dev.orientation
        print(f"화면 방향 {o}, 그림 {n}장 준비 중...")
        frames = make_frames(n, circle=True)
        frames = [L.fit(f, o) for f in frames]

        t = alive(dev)
        print(f"시작 전 수온: {t}도")

        stream = L.Stream(dev)

        def bucket_gif(img):
            data = L.to_gif(img)
            stream.send(data, L.KIND_GIF)
            return data

        def fast_q565(img):
            data = L.to_q565(img)
            L.send_fast(dev, data, L.KIND_Q565)
            return data

        ok1 = run(dev, "버킷 방식 (GIF 256색)", frames, bucket_gif)
        time.sleep(2)
        ok2 = run(dev, "빠른 경로 (Q565)", frames, fast_q565)

        print()
        if ok2:
            print("빠른 경로가 살아 있다. 이쪽이 장치에 부드럽다.")
        else:
            print("빠른 경로가 실패했다. 버킷 방식을 유지해야 한다.")
    finally:
        try:
            dev._delete_all_buckets()
        except Exception:
            pass
        ctx.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
