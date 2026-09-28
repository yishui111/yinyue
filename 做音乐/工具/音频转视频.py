# -*- coding: utf-8 -*-
"""把一首歌变成带封面卡的 MP4 视频(用于快速试听/分享)。

用法:
    python 音频转视频.py <音频文件> [标题] [副标题]

输出:与音频同目录的同名 .mp4。
依赖:Pillow + imageio-ffmpeg(自带 ffmpeg,无需单独安装)。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FONT = "C:/Windows/Fonts/msyh.ttc"


def make_card(out: Path, title: str, sub: str):
    img = Image.new("RGB", (W, H), (16, 22, 41))
    d = ImageDraw.Draw(img)
    for y in range(H):                       # 顶部到深处的夜色渐变
        k = y / H
        d.line([(0, y), (W, y)], fill=(16 + int(14 * k), 22 + int(16 * k), 41 + int(22 * k)))
    for cx, cy, r, a in ((200, 160, 130, 26), (1050, 520, 170, 22), (900, 140, 90, 18)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(46, 80, 160, a) if False else (46, 80, 160))
    f_big = ImageFont.truetype(FONT, 64)
    f_sub = ImageFont.truetype(FONT, 30)
    f_tag = ImageFont.truetype(FONT, 22)
    tw = d.textlength(title, font=f_big)
    d.text(((W - tw) / 2, 268), title, font=f_big, fill=(240, 244, 255))
    sw = d.textlength(sub, font=f_sub)
    d.text(((W - sw) / 2, 380), sub, font=f_sub, fill=(150, 170, 220))
    tag = "做音乐 · YuE2 本地合成"
    tw2 = d.textlength(tag, font=f_tag)
    d.text(((W - tw2) / 2, H - 70), tag, font=f_tag, fill=(110, 125, 170))
    img.save(out)


def main():
    if len(sys.argv) < 2:
        print("用法: python 音频转视频.py <音频文件> [标题] [副标题]")
        sys.exit(1)
    audio = Path(sys.argv[1]).resolve()
    if not audio.is_file():
        print(f"音频不存在: {audio}")
        sys.exit(1)
    title = sys.argv[2] if len(sys.argv) > 2 else audio.stem
    sub = sys.argv[3] if len(sys.argv) > 3 else ""
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as td:
        card = Path(td) / "card.png"
        make_card(card, title, sub)
        out = audio.with_suffix(".mp4")
        cmd = [ffmpeg, "-y", "-loop", "1", "-i", str(card), "-i", str(audio),
               "-c:v", "libx264", "-tune", "stillimage", "-r", "2",
               "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
               "-shortest", "-movflags", "+faststart", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out.is_file():
            print(r.stderr[-800:])
            sys.exit(1)
        print(f"视频已生成: {out} ({out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
