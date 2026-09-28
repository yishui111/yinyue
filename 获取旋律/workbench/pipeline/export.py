"""导出：把旋律 JSON 写成 MIDI / MusicXML / UST（OpenUtau 可直接导入）。"""
import re
from xml.sax.saxutils import escape

TPB = 480  # 每拍 tick 数


def _ascii_text(s):
    """MIDI 元数据只认 latin-1，中文标题替换成 ASCII，避免 mido 编码崩溃。"""
    return "".join(ch for ch in str(s) if 32 <= ord(ch) < 127) or "melody"



def all_notes(song):
    for ln in song["lines"]:
        for n in ln["notes"]:
            yield n


def to_midi(song, path):
    from mido import MidiFile, MidiTrack, Message, MetaMessage, bpm2tempo
    bpm = song.get("bpm") or 100.0
    mid = MidiFile()
    tr = MidiTrack()
    mid.tracks.append(tr)
    tr.append(MetaMessage("set_tempo", tempo=bpm2tempo(bpm), time=0))
    tr.append(MetaMessage("track_name", name=_ascii_text(song.get("title", "melody")), time=0))
    tps = TPB * bpm / 60.0
    ev = []
    for n in all_notes(song):
        if n.get("midi") is None:
            continue
        s, d = n["start"], max(n["duration"], 0.05)
        ev.append((s, 1, n["midi"]))
        ev.append((s + d, 0, n["midi"]))
    ev.sort(key=lambda e: (round(e[0] * tps), e[1]))
    last = 0
    for s, kind, m in ev:
        tick = int(round(s * tps))
        tr.append(Message("note_on" if kind else "note_off", note=m,
                          velocity=90 if kind else 0, time=tick - last))
        last = tick
    mid.save(str(path))


_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _pitch(midi):
    name = _NAMES[midi % 12]
    return name[0], (1 if "#" in name else 0), midi // 12 - 1


def _note_type(beats):
    for thr, t in ((3.4, "whole"), (1.7, "half"), (0.85, "quarter"),
                   (0.42, "eighth"), (0.21, "16th")):
        if beats >= thr:
            return t
    return "16th"


def to_musicxml(song, path):
    """每行歌词一个小节（含旋律+歌词）。给 MuseScore/OpenUtau 参考用。"""
    bpm = song.get("bpm") or 100.0
    div = 4
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<score-partwise version="3.1">',
           '  <part-list><score-part id="P1"><part-name>Melody</part-name></score-part></part-list>',
           '  <part id="P1">']
    for mi, ln in enumerate(song["lines"], start=1):
        out.append(f'    <measure number="{mi}">')
        if mi == 1:
            out.append('      <attributes><divisions>4</divisions>'
                       '<time><beats>4</beats><beat-type>4</beat-type></time>'
                       '<clef><sign>G</sign><line>2</line></clef></attributes>')
            out.append(f'      <direction placement="above"><direction-type>'
                       f'<metronome><beat-unit>quarter</beat-unit>'
                       f'<per-minute>{bpm}</per-minute></metronome></direction-type></direction>')
        for n in ln["notes"]:
            beats = max(n["duration"], 0.1) * bpm / 60.0
            dur = max(1, int(round(beats * div)))
            ntype = _note_type(beats)
            if n.get("midi") is None:
                out.append(f'      <note><rest/><duration>{dur}</duration>'
                           f'<voice>1</voice><type>{ntype}</type></note>')
                continue
            step, alter, octv = _pitch(n["midi"])
            pitch = (f"<pitch><step>{step}</step>"
                     + (f"<alter>{alter}</alter>" if alter else "")
                     + f"<octave>{octv}</octave></pitch>")
            lyric = escape(str(n.get("new_char") or n.get("char") or ""))
            out.append(f'      <note>{pitch}<duration>{dur}</duration>'
                       f'<voice>1</voice><type>{ntype}</type>'
                       f'<lyric><text>{lyric}</text></lyric></note>')
        out.append('    </measure>')
    out.append('  </part>')
    out.append('</score-partwise>')
    path.write_text("\n".join(out), encoding="utf-8")


def to_ust(song, path):
    """UST 文本格式，OpenUtau/UTAU 可导入；新词优先写入 Lyric。"""
    bpm = song.get("bpm") or 100.0
    tps = TPB * bpm / 60.0
    notes = [n for n in all_notes(song)]
    notes.sort(key=lambda n: n["start"])
    body, t = [], 0.0
    for n in notes:
        s, d = n["start"], max(n["duration"], 0.05)
        if s - t > 0.02:
            body.append((None, s - t))
        body.append((n, d))
        t = max(t, s + d)

    txt = ["[#VERSION=3]", "[#SETTING]",
           f"Tempo={bpm}", "Tracks=1",
           f"ProjectName={song.get('title', 'workbench')}"]
    for i, (n, d) in enumerate(body):
        length = max(1, int(round(d * tps)))
        if n is None or n.get("midi") is None:
            lyric, num = "R", 60
        else:
            lyric = str(n.get("new_char") or n.get("char") or "ら")
            num = n["midi"]
        txt.append(f"[#{i:04d}]")
        txt.append(f"Length={length}")
        txt.append(f"Lyric={lyric}")
        txt.append(f"NoteNum={num}")
        txt.append("Velocity=64")
        txt.append("Intensity=100")
        txt.append("Modulation=0")
    txt.append("[#TRACKEND]")
    path.write_text("\n".join(txt) + "\n", encoding="utf-8")
