"""LCD가 실제로 부드럽게 움직이는지 눈으로 확인한다.

    python lcd_anim.py [초]

돌아가는 원호와 초당 프레임 수를 함께 그린다. 숫자가 화면에서 직접
읽히므로 별도 계측 없이 실제 성능을 볼 수 있다.
"""

import math
import sys
import time

from PIL import Image, ImageDraw, ImageFont

import lcd_fast

FONT = r"C:\Windows\Fonts\malgunbd.ttf"
RES = lcd_fast.RES


def make_frame(t, fps, big, small):
    img = Image.new("RGB", RES, (6, 8, 16))
    d = ImageDraw.Draw(img)

    # 바깥 궤도를 도는 원호
    ang = (t * 200) % 360
    d.arc((14, 14, 626, 626), ang, ang + 70, fill=(120, 200, 255), width=16)
    d.arc((14, 14, 626, 626), ang + 180, ang + 250, fill=(255, 140, 70), width=16)

    # 도는 것이 눈에 더 잘 띄도록 안쪽에 점 하나
    r = 210
    cx = 320 + r * math.cos(math.radians(ang))
    cy = 320 + r * math.sin(math.radians(ang))
    d.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), fill=(255, 255, 255))

    text = f"{fps:.0f}"
    b = d.textbbox((0, 0), text, font=big)
    d.text((320 - (b[2] - b[0]) / 2 - b[0], 250), text, font=big, fill=(255, 255, 255))

    b2 = d.textbbox((0, 0), "FPS", font=small)
    d.text((320 - (b2[2] - b2[0]) / 2 - b2[0], 400), "FPS", font=small, fill=(120, 200, 255))
    return img


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    big = ImageFont.truetype(FONT, 150)
    small = ImageFont.truetype(FONT, 56)

    dev, ctx = lcd_fast.open_device()
    try:
        start = time.time()
        frames = 0
        fps = 0.0
        last = start
        while time.time() - start < seconds:
            t = time.time() - start
            img = make_frame(t, fps, big, small)
            data = lcd_fast.to_rgb565(img)
            if frames == 0:
                # 첫 장을 넣은 뒤 화면 모드를 돌린다. 안 돌리면 전송은 성공해도
                # 화면은 계속 예전 것을 그린다.
                lcd_fast.start_stream(dev, data)
            else:
                lcd_fast.send_frame(dev, data)
            frames += 1
            now = time.time()
            if now - last >= 0.5:
                fps = frames / (now - start)
                last = now
        total = time.time() - start
        print(f"{frames}장 / {total:.1f}초 = 평균 초당 {frames/total:.1f}장")
    finally:
        ctx.__exit__(None, None, None)


if __name__ == "__main__":
    sys.exit(main())
