"""哼鸣试听：不装任何歌声合成模型，用带颤音的复合正弦波把旋律「唱」出来。

用途：填完新词后立刻听一遍「音高和节奏对不对位」，正式人声再交给 DiffSinger/OpenUtau。
"""
import wave

import numpy as np


def render_hum(song, path, sr=22050):
    events = []
    end = 1.0
    for ln in song["lines"]:
        for n in ln["notes"]:
            if n.get("midi") is None:
                continue
            events.append((n["start"], max(n["duration"], 0.08), n["midi"]))
            end = max(end, n["start"] + n["duration"] + 0.6)

    buf = np.zeros(int(end * sr) + sr)
    for start, dur, midi in events:
        f0 = 440.0 * 2 ** ((midi - 69) / 12.0)
        ns = int(dur * sr)
        if ns < 16:
            continue
        t = np.arange(ns) / sr
        depth = 0.006 * np.clip((t - 0.25 * dur) / (0.4 * dur), 0, 1)
        vib = 1 + depth * np.sin(2 * np.pi * 5.5 * t)
        phase = 2 * np.pi * f0 * np.cumsum(vib) / sr
        sig = (np.sin(phase) + 0.35 * np.sin(2 * phase)
               + 0.12 * np.sin(3 * phase) + 0.05 * np.sin(4 * phase))
        env = np.clip(t / 0.02, 0, 1) * np.clip((dur - t) / 0.05, 0, 1)
        i0 = int(start * sr)
        buf[i0:i0 + ns] += sig * env * 0.5

    peak = float(np.max(np.abs(buf)))
    if peak > 0:
        buf = buf / peak * 0.85
    data = (buf * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
