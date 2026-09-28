# -*- coding: utf-8 -*-
"""
曲谱转换入库:从 TheSession(thesession.org 社区曲谱数据,收录的是传统曲目的公有领域旋律)
批量挑选曲谱,转换成 YuE2 原生 ABC 方言,经官方 abc_tools 校验通过后存入 旋律库\\。

用法(在本目录或项目根目录执行):
    python 曲谱转换入库.py                # 首次会自动下载数据(~24MB),默认入库 8 首
    python 曲谱转换入库.py --count 12     # 指定目标入库数量
    python 曲谱转换入库.py --refresh      # 强制重新下载最新数据

说明:
- 只收录 4/4(C)、3/4、6/8 拍,键名限 C/G/D/A/E 大调与 Am/Em/Bm/Dm 小调或对应多利安调式;
- 自动展开反复记号、去掉装饰音,音域自动移八度到人声区(C4~G5);
- 传统曲谱一般不带和弦,这类入库后生成时用 cot="melody"(伴奏自由发挥);
- 旋律本身是传统曲目(公有领域),转谱来自社区,仅供个人学习使用。
"""
import json
import os
import random
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LIB = ROOT / "旋律库"
CACHE = HERE / "缓存" / "thesession_tunes.json"
TOOLS = ROOT / "YuE" / "skills" / "yue2-music" / "scripts" / "abc_tools.py"
DATA_URL = "https://raw.githubusercontent.com/adactio/TheSession-data/main/json/tunes.json"
SYS_PY = r"C:\Users\dapanji\AppData\Local\Programs\Python\Python312\python.exe"

METER_UNITS = {"4/4": 16, "3/4": 12, "6/8": 12, "2/4": 8}
DOR_RELATIVE = {"A": "G", "B": "A", "C": "B", "D": "C", "E": "D", "F": "E", "G": "F"}
KEY_OK = {"C", "G", "D", "A", "E", "Am", "Em", "Bm", "Dm"}
TYPE_ZH = {"reel": "里尔舞曲", "jig": "吉格舞曲", "waltz": "圆舞曲", "hornpipe": "号笛舞曲",
           "polka": "波尔卡", "slip jig": "滑步吉格", "barndance": "谷仓舞",
           "mazurka": "玛祖卡", "strathspey": "斯特拉斯佩", "three two": "三二舞曲"}
TEMPO = {"reel": 110, "hornpipe": 110, "jig": 100, "slip jig": 100, "waltz": 90,
         "mazurka": 100, "polka": 115, "barndance": 105, "strathspey": 100, "three two": 105}

PITCH = {l: 60 + i for i, l in enumerate("CDEFGAB")}
PITCH.update({l: 72 + i for i, l in enumerate("CDEFGAB".lower())})


def download(force=False):
    if CACHE.is_file() and not force:
        return
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    print("下载数据(~24MB,首次需要)……")
    proxy = os.environ.get("YUE2_FETCH_PROXY", "http://127.0.0.1:7897")
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    opener = urllib.request.build_opener(handler)
    with opener.open(DATA_URL, timeout=300) as r:
        CACHE.write_bytes(r.read())
    print("下载完成:", CACHE)


def parse_key(k):
    k = k.strip()
    m = re.match(r"^([A-G])([#b]?)(maj|major|dor|dorian|min|minor|m|mix|mixolydian|M)?", k, re.I)
    if not m:
        return None
    letter = m.group(1).upper()
    mode = (m.group(3) or "").lower()
    if mode.startswith("dor"):
        letter = DOR_RELATIVE.get(letter, "")
        mode = "maj"
    elif mode.startswith("mix"):
        return None
    if m.group(2) == "#":
        letter = {"F": "F#", "C": "C#", "G": "G#", "D": "D#", "A": "A#"}.get(letter, "")
    if m.group(2) == "b":
        letter = {"B": "Bb", "E": "Eb", "A": "Ab", "D": "Db", "G": "Gb", "C": "Cb", "F": "Fb"}.get(letter, "")
    if not letter:
        return None
    minor = mode in ("m", "min", "minor")
    cand = letter + ("m" if minor else "")
    return cand if cand in KEY_OK else None


def clean_and_expand(lines):
    out = []
    for ln in lines:
        ln = re.sub(r"%.*", "", ln).strip()
        if not ln:
            continue
        if re.search(r"\((3|5)|<<|>>|&|\{", ln):
            return None, "含连音/装饰/多声部"
        ln = re.sub(r"~|(?<=\w)\.(?=\w)|!", "", ln)   # 装饰音/断奏记号
        ln = re.sub(r"\{[^}]*\}", "", ln)             # 装饰音群
        out.append(ln)
    if not out:
        return None, "空"
    body = " ".join(out)
    for _ in range(3):
        body2 = re.sub(r"\|:([^:]*):\|", r"\1 \1", body)
        if body2 == body:
            break
        body = body2
    if "|:" in body or ":|" in body:
        return None, "未支持的反复写法"
    if re.search(r"\[[12]", body) or "[|" in body:
        return None, "含一二次房子"
    return body, ""


def translate_durations(body):
    """源谱 L:1/8 → 目标 L:1/16:所有时值 ×2;切分节奏 E>F → E3F(3:1)、E<F → EF3(1:3)。
    引号内的和弦名不做改写。"""
    parts = re.split(r'("[^"]*")', body)
    out_parts = []
    for part in parts:
        if part.startswith('"'):
            out_parts.append(part)
            continue
        toks = re.findall(r"[A-Ga-gz][,']*\d*|>|<|\||-|\S", part)
        out = []
        i = 0
        while i < len(toks):
            m = re.fullmatch(r"([A-Ga-gz][,']*)(\d*)", toks[i])
            if (m and i + 2 < len(toks) and toks[i + 1] in "><"
                    and re.fullmatch(r"[A-Ga-gz][,']*\d*", toks[i + 2])):
                m2 = re.fullmatch(r"([A-Ga-gz][,']*)(\d*)", toks[i + 2])
                if toks[i + 1] == ">":
                    out.append(m.group(1) + "3" + m2.group(1) + "1")
                else:
                    out.append(m.group(1) + "1" + m2.group(1) + "3")
                i += 3
                continue
            if m:
                d = int(m.group(2) or "1") * 2
                out.append(m.group(1) + (str(d) if d > 1 else ""))
                i += 1
                continue
            out.append(toks[i])
            i += 1
        out_parts.append("".join(out))
    return "".join(out_parts)


def body_bars(body):
    parts = [p for p in body.split("|") if p.strip()]
    return parts, len(parts)


def pitches_of(body):
    return [PITCH[n[0]] + 12 * n.count("'") - 12 * n.count(",")
            for n in re.findall(r"[A-Ga-g][,']*", body)]


def range_shift(body, up):
    def shift(m):
        note = m.group(0)
        if up:
            return note.upper() + "'" if note.islower() else note + ","
        return note[0] if note.endswith(",") else note.lower()
    return re.sub(r"[A-Ga-g][,']*", shift, body)


def convert(setting_abc, meter, mode, bpm=105):
    meter = meter if meter in METER_UNITS else ""
    if not meter:
        return None, "拍号不支持"
    key = parse_key(mode or "")
    if not key:
        return None, "调式不支持"
    body, why = clean_and_expand(setting_abc.splitlines())
    if body is None:
        return None, why
    body = translate_durations(body)
    if "<" in body or ">" in body:
        return None, "未支持的切分节奏写法"
    body = body.replace("||", "|")
    _, nbar = body_bars(body)
    if not (8 <= nbar <= 40):
        return None, f"小节数 {nbar} 不合适"
    pitches = pitches_of(body)
    if not pitches:
        return None, "无音符"
    if min(pitches) < 60:
        body = range_shift(body, True)
        pitches = pitches_of(body)
    if max(pitches) > 79:
        body = range_shift(body, False)
        pitches = pitches_of(body)
    if min(pitches) < 55 or max(pitches) > 84:
        return None, "音域超出人声区"

    body = body.rstrip("|")
    bars = [p.strip() for p in body.split("|") if p.strip()]
    groups = [bars[i:i + 4] for i in range(0, len(bars), 4)]
    blocks = []
    for g in groups:
        blocks.append("V: Vocal\n" + "|".join(g) + "|")
        blocks.append("V: Ins\n" + (f"Z{len(g)}|" if len(g) > 1 else "Z|"))
    body_text = "\n".join(blocks) + "\n"
    return (f"X:1\nT:\nM:{meter}\nL:1/16\nQ:1/4={bpm}\n"
            f"V: Vocal clef=treble name=\"Vocal Melody\" snm=\"Vocal\"\n"
            f"V: Ins clef=treble name=\"Ins Melody\" snm=\"Inst.\"\n"
            f"K:{key}\n% 传统曲转换(无和弦,建议 cot=melody)\n"
            f"{body_text}"), ""


def safe_filename(s):
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff-]+", "-", s).strip("-")
    return s[:60] or "传统曲"


def validate_text(native_text):
    """进程内直接调用官方 abc_tools 的解析器校验(纯标准库,无需子进程)。"""
    try:
        sys.path.insert(0, str(TOOLS.parent))
        import abc_tools  # noqa: 插入 path 后导入官方校验器
        abc_tools.parse_abc(native_text)
        return True
    except Exception:
        return False


def main():
    args = sys.argv[1:]
    count = int(args[args.index("--count") + 1]) if "--count" in args else 8
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args else 2026
    refresh = "--refresh" in args
    download(refresh)
    tunes = json.loads(CACHE.read_text(encoding="utf-8"))
    random.Random(seed).shuffle(tunes)
    LIB.mkdir(exist_ok=True)
    kept = 0
    reasons = {}
    seen_ids = set()
    for t in tunes:
        if kept >= count:
            break
        tid = t.get("tune_id")
        if tid in seen_ids:
            continue
        ttype = (t.get("type") or "").lower()
        title = (t.get("name") or "").strip()
        abc = t.get("abc") or ""
        if not abc:
            continue
        bpm = TEMPO.get(ttype, 105)
        native, why = convert(abc, t.get("meter") or "", t.get("mode") or "", bpm)
        if native is None:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        if not validate_text(native):
            reasons["官方校验未过"] = reasons.get("官方校验未过", 0) + 1
            continue
        name = safe_filename(f"{TYPE_ZH.get(ttype, '传统曲')}-{title}")
        out = LIB / f"{name}.abc"
        k = 2
        while out.exists():
            out = LIB / f"{name}-{k}.abc"
            k += 1
        out.write_text(native, encoding="utf-8")
        seen_ids.add(tid)
        print(f"[入库] {out.name}", flush=True)
        kept += 1
    print(f"完成:本次入库 {kept} 首,目标 {count}")
    print("跳过原因统计:", json.dumps(reasons, ensure_ascii=False))


if __name__ == "__main__":
    main()
