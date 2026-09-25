# -*- coding: utf-8 -*-
r"""ds_builder 单元测试：注音、时长、f0 对齐、字数校验、休止处理。
用 runtime\py312\python.exe 直接运行（无需 pytest）。"""
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ds_builder  # noqa: E402

TESTDATA = ROOT / "testdata"
RESULTS = []


def case(name, fn):
    t0 = time.time()
    try:
        detail = fn() or ""
        RESULTS.append((name, True, detail, time.time() - t0))
        print("[通过] %s (%.1fs) %s" % (name, time.time() - t0, detail))
    except Exception as e:
        RESULTS.append((name, False, repr(e), time.time() - t0))
        print("[失败] %s (%.1fs) %r" % (name, time.time() - t0, e))


def seg_f0(seg):
    return [float(x) for x in seg["f0_seq"].split()]


def t_phonemes():
    song = json.loads((TESTDATA / "小星星.json").read_text(encoding="utf-8-sig"))
    lyr = {"lines": [{"line_id": 0, "text": "弯弯月亮像小船"}]}
    ds = ds_builder.build_ds(song, lyr)
    ph = ds[0]["ph_seq"].split()
    expect = ["w", "an", "w", "an", "y", "ve", "l", "iang", "x", "iang", "x", "iao", "ch", "uan"]
    assert ph[:-1] == expect and ph[-1] == "SP", "音素序列 %s" % ph   # 句尾补 SP
    return "12 个音素与字典逐一匹配（含 月→y ve、船→ch uan），句尾 SP"


def t_duration_f0_consistency():
    song = json.loads((TESTDATA / "小星星.json").read_text(encoding="utf-8-sig"))
    ds = ds_builder.build_ds(song, None)
    for seg in ds:
        durs = [float(x) for x in seg["ph_dur"].split()]
        total = sum(durs)
        n_f0 = len(seg_f0(seg))
        assert abs(total - n_f0 * ds_builder.F0_DT) < 1.5 * ds_builder.F0_DT, \
            "段长 %.3f 与 f0 帧数 %d 不一致" % (total, n_f0)
        assert len(seg["ph_seq"].split()) == len(durs), "ph_seq 与 ph_dur 数量不一致"
    return "2 段的 ph/ph_dur/f0 帧数互相对齐"


def t_timing_alignment():
    song = json.loads((TESTDATA / "小星星.json").read_text(encoding="utf-8-sig"))
    ds = ds_builder.build_ds(song, None)
    f0_1, f0_2 = seg_f0(ds[0]), seg_f0(ds[1])
    first_voiced_1 = next(i for i, v in enumerate(f0_1) if v > 0)
    first_voiced_2 = next(i for i, v in enumerate(f0_2) if v > 0)
    # 行1 offset=0（首音符在 0，lead SP 被截短）
    assert abs(ds[0]["offset"] + first_voiced_1 * 0.01 - 0.0) < 0.02, "行1 首个有声帧不在 0s"
    # 行2 首音符在 6.0s，offset = 6.0-0.12 = 5.88，lead SP 0.12 → 有声帧应在 6.00s
    assert abs(ds[1]["offset"] + first_voiced_2 * 0.01 - 6.0) < 0.02, "行2 首个有声帧不在 6.0s"
    return "行1 首声 0.00s / 行2 首声 6.00s，f0 与音素时间线一致"


def t_pitch_range():
    song = json.loads((TESTDATA / "小星星.json").read_text(encoding="utf-8-sig"))
    ds = ds_builder.build_ds(song, None)
    voiced = [v for v in seg_f0(ds[0]) if v > 0]
    assert abs(min(voiced) - 261.63) < 1 and abs(max(voiced) - 440.0) < 1, \
        "音高范围 %.1f~%.1f 不是 C4~A4" % (min(voiced), max(voiced))
    # 行2 应从 F4(349.23) 下行到 C4
    voiced2 = [v for v in seg_f0(ds[1]) if v > 0]
    assert abs(max(voiced2) - 349.23) < 1 and abs(min(voiced2) - 261.63) < 1
    return "行1 C4~A4、行2 F4~C4，与旋律 MIDI 一致"


def t_char_count_mismatch():
    song = json.loads((TESTDATA / "小星星.json").read_text(encoding="utf-8-sig"))
    bad = {"lines": [{"line_id": 0, "chars": ["多", "一", "个", "字", "的", "歌", "词", "！"]}]}
    try:
        ds_builder.build_ds(song, bad)
    except ValueError as e:
        assert "数量不相等" in str(e)
        return "8 字 vs 7 音符 → 正确报错：%s" % e
    raise AssertionError("字数不匹配竟没有报错")


def t_text_lyrics_with_punct():
    song = json.loads((TESTDATA / "小星星.json").read_text(encoding="utf-8-sig"))
    lyr = {"lines": [{"line_id": 1, "text": "载我梦里去银河！"}]}   # 带标点
    ds = ds_builder.build_ds(song, lyr)
    ph = ds[1]["ph_seq"].split()
    assert "z" in ph and "ai" in ph and "h" in ph and "e" in ph, "文本歌词未正确注音"
    return "text 格式歌词 + 感叹号自动剔除"


def t_rest_sp_ap():
    song = {"title": "t", "bpm": 100, "lines": [{"line_id": 0, "notes": [
        {"i": 0, "char": "弯", "midi": 60, "start": 0.0, "duration": 0.5},
        {"i": 1, "char": "弯", "midi": 62, "start": 0.8, "duration": 0.5},   # 间隔 0.3s → 只 SP
        {"i": 2, "char": "月", "midi": 64, "start": 1.9, "duration": 0.5},   # 间隔 0.6s → AP+SP（换气）
    ]}]}
    ws = []
    events, _ = ds_builder.build_line_events(song["lines"][0], None, ws)
    kinds = [e["kind"] for e in events]
    assert kinds == ["note", "sp", "note", "ap", "sp", "note"], "事件序列 %s" % kinds
    return "0.3s 休止→SP，≥0.5s 休止→AP+SP（换气）"


def t_null_midi_rest():
    song = {"title": "t", "bpm": 100, "lines": [{"line_id": 0, "notes": [
        {"i": 0, "char": "弯", "midi": 60, "start": 0.0, "duration": 0.5},
        {"i": 1, "char": "啊", "midi": None, "start": 0.5, "duration": 0.3},
        {"i": 2, "char": "月", "midi": 64, "start": 0.8, "duration": 0.5},
    ]}]}
    ws = []
    ds = ds_builder.build_ds(song, None, ws)
    assert any("无音高" in w for w in ws), "null-midi 没有给出警告"
    ph = ds[0]["ph_seq"].split()
    assert "SP" in ph, "null-midi 音符未按休止处理"
    return "midi=null 的音符按休止处理并给出警告"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("== ds_builder 单元测试 ==")
    case("注音与音素序列", t_phonemes)
    case("时长与f0帧数一致性", t_duration_f0_consistency)
    case("音素与f0时间线对齐", t_timing_alignment)
    case("音高与旋律一致", t_pitch_range)
    case("字数不匹配报错", t_char_count_mismatch)
    case("text格式歌词+标点剔除", t_text_lyrics_with_punct)
    case("行内休止 SP/换气 AP", t_rest_sp_ap)
    case("midi=null 休止处理", t_null_midi_rest)
    n_fail = sum(1 for _, ok, _, _ in RESULTS if not ok)
    print("== 结果：%d 通过 / %d 失败 ==" % (len(RESULTS) - n_fail, n_fail))
    sys.exit(1 if n_fail else 0)
