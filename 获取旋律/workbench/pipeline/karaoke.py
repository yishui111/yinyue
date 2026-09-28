"""卡拉OK视频：把旋律+演唱音频渲染成「钢琴卷帘 + 逐字高亮 + 播放头」的 MP4。

依赖: opencv-python（写视频）、Pillow（中文字渲染）、系统 ffmpeg（音视频合成）。
"""
import subprocess
import wave
from pathlib import Path

import numpy as np

FONT_CANDIDATES = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                   "C:/Windows/Fonts/simsun.ttc"]
BG = (18, 20, 26)
ROLL_BG = (30, 34, 44)
NOTE_ON = (80, 170, 255)
NOTE_CUR = (255, 200, 80)
NOTE_OFF = (90, 100, 120)
PLAYHEAD = (255, 90, 90)
TEXT = (235, 238, 245)


def _load_fonts(sizes):
    from PIL import ImageFont
    for fp in FONT_CANDIDATES:
        try:
            return {s: ImageFont.truetype(fp, s) for s in sizes}
        except Exception:
            continue
    return {s: ImageFont.load_default() for s in sizes}


def render_karaoke(melody, audio_path, out_mp4, progress=None, fps=15, size=(1280, 720)):
    import cv2
    from PIL import Image, ImageDraw

    # 音频总长
    with wave.open(str(audio_path), "rb") as w:
        sr = w.getframerate()
        total = w.getnframes() / sr

    # 音符与时间范围
    notes = []
    for ln in melody["lines"]:
        for n in ln["notes"]:
            ch = (n.get("new_char") or n.get("char") or "").strip()
            notes.append({"start": float(n["start"]), "duration": max(float(n["duration"]), 0.08),
                          "midi": int(n["midi"]), "char": ch,
                          "jianpu": n.get("jianpu", ""), "note_name": n.get("note_name", "")})
    notes.sort(key=lambda n: n["start"])
    if not notes:
        raise RuntimeError("没有可渲染的音符")
    t0 = max(0.0, notes[0]["start"] - 0.5)
    t1 = max(total, notes[-1]["start"] + notes[-1]["duration"]) + 0.8

    lo = min(n["midi"] for n in notes) - 2
    hi = max(n["midi"] for n in notes) + 3
    W, H = size
    roll_x0, roll_x1 = 70, W - 70
    roll_y0, roll_y1 = 90, H - 160

    def x_of(t):
        return int(roll_x0 + (t - t0) / (t1 - t0) * (roll_x1 - roll_x0))

    def y_of(midi):
        return int(roll_y1 - (midi - lo) / max(1, hi - lo) * (roll_y1 - roll_y0 - 30) - 15)

    fonts = _load_fonts([28, 40, 72])

    def draw_frame(now):
        img = Image.new("RGB", size, BG)
        d = ImageDraw.Draw(img)
        d.rectangle([roll_x0, roll_y0, roll_x1, roll_y1], fill=ROLL_BG)
        # 每句分隔与句词
        for ln in melody["lines"]:
            first = ln["notes"][0] if ln.get("notes") else None
            if first:
                x = x_of(float(first["start"]))
                d.line([x, roll_y0, x, roll_y1], fill=(70, 76, 92), width=2)
                d.text((x + 6, roll_y0 + 4), ln.get("text") or f"#{ln['line_id']}",
                       font=fonts[28], fill=(150, 158, 175))
        cur_char, cur_note = "", None
        for n in notes:
            x1, x2 = x_of(n["start"]), x_of(n["start"] + n["duration"])
            y1, y2 = y_of(n["midi"]) - 16, y_of(n["midi"]) + 16
            active = n["start"] <= now < n["start"] + n["duration"]
            past = now >= n["start"] + n["duration"]
            color = NOTE_CUR if active else (NOTE_ON if (past and False) else
                                             (NOTE_ON if now < n["start"] else NOTE_OFF))
            if active:
                color = NOTE_CUR
            elif past:
                color = (120, 150, 220)
            else:
                color = NOTE_ON
            d.rectangle([x1, y1, x2, y2], fill=color)
            if n["char"]:
                d.text(((x1 + x2) / 2 - 8, (y1 + y2) / 2 - 14), n["char"],
                       font=fonts[28], fill=(20, 24, 34))
            if active:
                cur_char, cur_note = n["char"], n
        # 播放头
        px = x_of(now)
        d.line([px, roll_y0, px, roll_y1], fill=PLAYHEAD, width=3)
        # 当前字大字
        if cur_char:
            d.text((W / 2 - 36, roll_y1 + 18), cur_char, font=fonts[72], fill=TEXT)
        if cur_note:
            d.text((W / 2 + 60, roll_y1 + 40),
                   f"{cur_note['jianpu']}  {cur_note['note_name']}",
                   font=fonts[28], fill=(160, 168, 185))
        d.text((20, 12), f"{melody.get('title', '')}  ·  {melody.get('key', '')}  ·  {melody.get('bpm', '')} BPM",
               font=fonts[28], fill=(130, 138, 155))
        return np.array(img)[:, :, ::-1].copy()  # RGB→BGR

    tmp_video = Path(out_mp4).with_suffix(".tmp.mp4")
    writer = cv2.VideoWriter(str(tmp_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    frames = int(total * fps) + 1
    for f in range(frames):
        writer.write(draw_frame(f / fps))
        if progress and f % (fps * 2) == 0:
            try:
                progress("sing", f"卡拉OK视频渲染中… {f * 100 // frames}%")
            except Exception:
                pass
    writer.release()

    # 合成音轨
    out = Path(out_mp4)
    tmp_out = out.with_suffix(".mux.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", str(tmp_video), "-i", str(audio_path),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", str(tmp_out)], check=True)
    tmp_out.replace(out)
    tmp_video.unlink(missing_ok=True)
    return str(out)
