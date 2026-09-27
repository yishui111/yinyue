# -*- coding: utf-8 -*-
r"""
把「旋律 + 歌词」变成 DiffSinger 可推理的 .ds 文件。

输入（与 获取旋律 工作台的格式对齐）：
  song   = {"title": ..., "bpm": ..., "lines": [{"line_id": 0, "notes": [
              {"i": 0, "char": "你", "midi": 60, "start": 0.5, "duration": 0.4}, ...]}]}
  lyrics = {"lines": [{"line_id": 0, "chars": ["新","词",...]}]}   ← DeepSeek 填词结果
  （lyrics 缺省时直接用 song 里每个 note 的 char 当歌词）

输出：一个 .ds JSON（分段列表），每行歌词一段：
  {"offset": 秒, "ph_seq": "SP b a ...", "ph_dur": "0.12 0.14 ...",
   "f0_seq": "0 0 440 ...", "f0_timestep": 0.01}
- 注音：pypinyin 无调拼音 → diffsinger/dictionaries/opencpop-extension.txt 查音素
- 音素时长：声母取音符时值的 28%（0.05~0.24s 夹紧），韵母吃剩下的
- f0：每 10ms 一帧；音符内恒定在 MIDI 音高上，相邻音间 40ms 线性滑音，
  声母段保持在音高上（与 opencpop 标注习惯一致），休止为 0
- 休止：行内空隙 ≥0.1s 记 SP（≥0.5s 先 AP 后 SP）；midi 为 null 的音符按休止处理
"""
import json
import pathlib
import re

DICT_PATH = pathlib.Path(__file__).resolve().parent / "diffsinger" / "dictionaries" / "opencpop-extension.txt"

F0_DT = 0.01          # f0 曲线步长（秒）
GLIDE = 0.04          # 相邻音符间的滑音时长（秒）
LEAD_SP = 0.12        # 句首静音
TAIL_SP = 0.30        # 句尾静音
MIN_GAP_SP = 0.10     # 行内空隙达到该时长才插 SP，否则并进前一个音
AP_MIN = 0.50         # 空隙达到该时长先换气（AP）
AP_DUR = 0.30
ONSET_MIN = 0.05      # 声母最短时长
ONSET_MAX = 0.24      # 声母最长时长
ONSET_RATIO = 0.28

_pinyin_cache = {}
_dict_cache = None

# 与工作台页面计数规则一致：这些标点/空白不算字
STRIP_RE = re.compile(r'[，。！？、：；…—,.!?;:\s"\'`()（）【】\[\]《》<>·~－-]')


def text_to_chars(text):
    return [c for c in (text or "") if not STRIP_RE.match(c)]


def load_dict():
    global _dict_cache
    if _dict_cache is None:
        table = {}
        for line in DICT_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip() or "\t" not in line:
                continue
            py, ph = line.split("\t", 1)
            table[py.strip()] = ph.strip()
        _dict_cache = table
    return _dict_cache


def pinyins_of(text):
    """整行歌词 → 无调拼音列表（只保留汉字，其余字符给出警告）"""
    if text not in _pinyin_cache:
        from pypinyin import lazy_pinyin, Style
        _pinyin_cache[text] = lazy_pinyin(text, style=Style.NORMAL, errors="ignore")
    return _pinyin_cache[text]


def split_initial_final(phonemes):
    """字典里一个拼音对应 1~2 个音素；返回 (声母, 韵母)，无声母时声母为 None"""
    if len(phonemes) >= 2:
        return phonemes[0], phonemes[1]
    return None, phonemes[0]


def onset_duration(note_dur):
    return max(ONSET_MIN, min(ONSET_MAX, note_dur * ONSET_RATIO))


def midi_to_hz(m):
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


def note_name(m):
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return "%s%d" % (names[m % 12], m // 12 - 1)


def build_line_events(line, chars, warnings):
    """一行 → 事件列表 [{kind: note/ap/sp, t0, dur, midi, ph, char}]；chars 与 notes 按下标一一对应"""
    notes = sorted(line["notes"], key=lambda n: n["start"])
    if chars is None:
        chars = [n.get("char") or "" for n in notes]
    if len(chars) != len(notes):
        raise ValueError(
            "第 %s 行歌词 %d 字，音符 %d 个，数量不相等（DeepSeek 约束 R1 应保证相等）"
            % (line.get("line_id", "?"), len(chars), len(notes)))

    voiced = []           # 有音高的音符
    rests = []            # midi 为 null 的音符当休止
    for n, c in zip(notes, chars):
        if n.get("midi") is None:
            if c:
                warnings.append("行%s 第%s字「%s」落在无音高音符上，按休止处理"
                                % (line.get("line_id", "?"), n.get("i", "?"), c))
            rests.append(n)
        else:
            voiced.append((n, c))

    table = load_dict()
    events = []
    cursor = None  # 上一个有音高音符的结束时刻
    for n, c in voiced:
        gap = 0.0 if cursor is None else n["start"] - cursor
        if cursor is not None and gap >= MIN_GAP_SP:
            sp_len = gap
            if sp_len >= AP_MIN:
                ap = min(AP_DUR, sp_len - 0.1)
                events.append({"kind": "ap", "t0": cursor, "dur": ap})
                sp_len -= ap
            events.append({"kind": "sp", "t0": cursor + (events[-1]["dur"] if events[-1]["kind"] == "ap" else 0),
                           "dur": sp_len})
        note_dur = max(float(n.get("duration") or 0.05), 0.05)
        if 0 < gap < MIN_GAP_SP and events and events[-1]["kind"] == "note":
            events[-1]["dur"] += gap          # 微小空隙并进前一个音
        if not c:
            raise ValueError("行%s 音符（%s, %.2fs）没有对应的字" %
                             (line.get("line_id", "?"), note_name(int(n["midi"])), n["start"]))
        py_list = pinyins_of(c)
        if not py_list:
            raise ValueError("行%s 的字「%s」不是汉字，无法注音" % (line.get("line_id", "?"), c))
        py = py_list[0]
        ph = table.get(py)
        if ph is None:
            raise ValueError("字「%s」的拼音 %s 不在 opencpop-extension 字典里" % (c, py))
        initial, final = split_initial_final(ph.split())
        on = onset_duration(note_dur) if initial else 0.0
        events.append({"kind": "note", "t0": n["start"], "dur": note_dur, "midi": int(n["midi"]),
                       "initial": initial, "final": final, "on": on, "char": c})
        cursor = n["start"] + note_dur
    return events, rests


def build_f0_curve(events, t_origin, n_frames):
    """f0 逐帧序列（Hz）。第 k 帧对应绝对时间 t_origin + k*F0_DT；含 40ms 音间滑音"""
    f0 = [0.0] * n_frames
    notes = [e for e in events if e["kind"] == "note"]
    for e in notes:
        i0 = max(0, int(round((e["t0"] - t_origin) / F0_DT)))
        i1 = min(n_frames, int(round((e["t0"] + e["dur"] - t_origin) / F0_DT)))
        hz = midi_to_hz(e["midi"])
        for i in range(i0, i1):
            f0[i] = hz
    # 音符之间线性滑音（仅相邻都有音高的地方）
    for a, b in zip(notes, notes[1:]):
        boundary = b["t0"] - t_origin
        i0 = int(round((boundary - GLIDE / 2) / F0_DT))
        i1 = int(round((boundary + GLIDE / 2) / F0_DT))
        i0, i1 = max(0, i0), min(n_frames - 1, i1)
        if i1 <= i0:
            continue
        for i in range(i0, i1 + 1):
            w = (i - i0) / (i1 - i0)
            f0[i] = midi_to_hz(a["midi"]) * (1 - w) + midi_to_hz(b["midi"]) * w
    return ["%.2f" % v for v in f0]


def events_to_segment(events, offset):
    """事件列表 → DS 段。段起点 = offset（秒），音素时间线从 offset 起算：
    句首 SP（first_t<LEAD_SP 时截短）→ 音符/行内休止 → 句尾 SP；
    f0 第 k 帧对应 offset + k*F0_DT，与 ph 时间线严格一致。"""
    first_t = min(e["t0"] for e in events)
    lead = min(LEAD_SP, max(first_t - offset, 0.0))
    ph_seq, ph_dur = [], []
    if lead >= 0.01:
        ph_seq.append("SP")
        ph_dur.append(round(lead, 3))
    for e in events:
        if e["kind"] == "sp":
            if e["dur"] >= 0.02:
                ph_seq.append("SP")
                ph_dur.append(round(e["dur"], 3))
        elif e["kind"] == "ap":
            ph_seq.append("AP")
            ph_dur.append(round(e["dur"], 3))
        else:
            if e["initial"]:
                ph_seq.append(e["initial"])
                ph_dur.append(round(e["on"], 3))
                ph_seq.append(e["final"])
                ph_dur.append(round(e["dur"] - e["on"], 3))
            else:
                ph_seq.append(e["final"])
                ph_dur.append(round(e["dur"], 3))
    ph_seq.append("SP")
    ph_dur.append(TAIL_SP)

    ph_dur = [max(d, 0.02) for d in ph_dur]
    total = sum(ph_dur)
    f0 = build_f0_curve(events, offset, int(round(total / F0_DT)))
    if len(f0) < int(round(total / F0_DT)):
        f0 += [f0[-1]] * (int(round(total / F0_DT)) - len(f0))
    return {"offset": round(offset, 3), "ph_seq": " ".join(ph_seq),
            "ph_dur": " ".join("%.3f" % d for d in ph_dur),
            "f0_seq": " ".join(f0), "f0_timestep": F0_DT}


def build_ds(song, lyrics=None, warnings=None):
    """song.json + DeepSeek 填词 → .ds 结构（分段列表）"""
    warnings = warnings if warnings is not None else []
    lines = sorted(song["lines"], key=lambda l: min(n["start"] for n in l["notes"]))
    lyric_map = {}
    if lyrics:
        for l in lyrics.get("lines", []):
            if isinstance(l.get("chars"), list):
                lyric_map[l.get("line_id")] = l.get("chars")
            else:
                # 页面/DeepSeek 给的整行文本（text 或 new_text）：去标点后逐字对位
                text = l.get("text") or l.get("new_text") or ""
                lyric_map[l.get("line_id")] = text_to_chars(text)
    segments = []
    for line in lines:
        lid = line.get("line_id")
        chars = lyric_map.get(lid)
        events, _ = build_line_events(line, chars, warnings)
        first_t = min(e["t0"] for e in events)
        offset = max(first_t - LEAD_SP, 0.0)
        segments.append(events_to_segment(events, offset))
    return segments


def main():
    import argparse
    ap = argparse.ArgumentParser(description="song.json + 歌词 → DiffSinger .ds")
    ap.add_argument("song", help="song.json（获取旋律 工作台导出的旋律结构）")
    ap.add_argument("lyrics", nargs="?", help="DeepSeek 填词结果 JSON（lines[].line_id/chars），缺省用 song 里的原字")
    ap.add_argument("-o", "--out", required=True, help="输出的 .ds 文件路径")
    a = ap.parse_args()

    song = json.loads(pathlib.Path(a.song).read_text(encoding="utf-8-sig"))
    lyrics = None
    if a.lyrics:
        lyrics = json.loads(pathlib.Path(a.lyrics).read_text(encoding="utf-8-sig"))
    warnings = []
    ds = build_ds(song, lyrics, warnings)
    for w in warnings:
        print("[警告] %s" % w)
    out = pathlib.Path(a.out)
    out.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
    n_notes = sum(len(l["notes"]) for l in song["lines"])
    print("[完成] %d 行 %d 段 → %s（共 %d 个音符）" % (len(song["lines"]), len(ds), out, n_notes))


if __name__ == "__main__":
    main()
