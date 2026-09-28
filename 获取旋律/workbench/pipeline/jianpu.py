"""调性检测 + 简谱标注：把 MIDI 音高翻译成「哆来咪」（简谱记法）。

调性用 Krumhansl-Schmuckler 音级权重相关法估计；
简谱数字相对主音计算，高八度加 '，低八度加 ,，变化音加 #。
"""
import numpy as np

MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52,
                          5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54,
                          4.75, 3.98, 2.69, 3.34, 3.17])
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
DEGREE = {0: "1", 2: "2", 4: "3", 5: "4", 7: "5", 9: "6", 11: "7"}


def note_name(midi):
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def collect_notes(song_lines):
    return [(n["midi"], n["duration"])
            for ln in song_lines for n in ln["notes"]
            if n.get("midi") is not None]


def detect_key(song_lines):
    items = collect_notes(song_lines)
    if not items:
        return "C major"
    hist = np.zeros(12)
    for midi, dur in items:
        hist[midi % 12] += dur
    best, best_score = ("C", "major"), -2.0
    for tonic in range(12):
        for mode, prof in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            score = np.corrcoef(np.roll(hist, -tonic), prof)[0, 1]
            if score > best_score:
                best_score, best = score, (NOTE_NAMES[tonic], mode)
    return f"{best[0]} {best[1]}"


def annotate_jianpu(song_lines, key):
    tonic_name, mode = (key.split() + ["major"])[:2]
    tonic_pc = NOTE_NAMES.index(tonic_name)
    items = collect_notes(song_lines)
    if not items:
        return
    total_w = sum(d for _, d in items)
    avg = sum(m * d for m, d in items) / total_w
    tonic_ref = tonic_pc + 12 * round((avg - tonic_pc) / 12)

    for ln in song_lines:
        for n in ln["notes"]:
            m = n.get("midi")
            if m is None:
                n["note_name"] = None
                n["jianpu"] = "0"
                continue
            n["note_name"] = note_name(m)
            iv = m - tonic_ref
            octv = int(np.floor(iv / 12))
            deg_iv = int(iv - octv * 12)
            if deg_iv in DEGREE:
                mark = DEGREE[deg_iv]
            elif deg_iv == 6:
                mark = "#4"
            else:
                upper = min(k for k in DEGREE if k > deg_iv)
                mark = "b" + DEGREE[upper]
            if octv > 0:
                mark += "'" * octv
            elif octv < 0:
                mark += "," * (-octv)
            n["jianpu"] = mark
