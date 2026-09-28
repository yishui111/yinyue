"""旋律库：DeepSeek 生成的旋律 JSON 的校验、规范化与读写。

旋律文件放在项目根目录的 melodies/ 文件夹里（用户把 DeepSeek 网页对话
生成的 JSON 存成 .json/.txt/.md 丢进来，或在页面上直接粘贴导入）。

统一内部格式（所有模块都用它）：
{
  "title": "歌名",
  "key": "C major",
  "bpm": 96,
  "lines": [
    {"line_id": 0, "text": "可选", "notes": [
        {"midi": 64, "duration": 0.5, "start": 0.0, "jianpu": "3", "note_name": "E4"}
    ]}
  ]
}
"""
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MELODIES = ROOT / "melodies"
MELODIES.mkdir(exist_ok=True)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
DEGREE = {0: "1", 2: "2", 4: "3", 5: "4", 7: "5", 9: "6", 11: "7"}
LINE_GAP = 0.35   # 句与句之间的换气间隔（秒）


def extract_json(text):
    """从 DeepSeek 回复里抠出第一个 JSON 对象（容忍 ```json 围栏与前后废话）。"""
    if not isinstance(text, str):
        return None, "内容不是文本"
    text = text.strip()
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j <= i:
        return None, "内容里找不到 JSON 对象（{...}）"
    try:
        return json.loads(text[i:j + 1]), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败：{e}"


def normalize_melody(data, default_title="未命名旋律"):
    """校验并规范化 DeepSeek 的旋律 JSON。返回 (melody, errors)。errors 非空即无效。"""
    errors = []
    if not isinstance(data, dict):
        return None, ["顶层必须是一个 JSON 对象"]
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        return None, ["缺少 lines 数组，或 lines 为空"]

    title = str(data.get("title") or default_title).strip() or default_title
    key = str(data.get("key") or "C major").strip()
    try:
        bpm = float(data.get("bpm") or 90)
        if not 20 <= bpm <= 300:
            bpm = 90.0
    except (TypeError, ValueError):
        bpm = 90.0

    out_lines = []
    for k, ln in enumerate(lines):
        if not isinstance(ln, dict):
            errors.append(f"第 {k + 1} 行不是对象")
            continue
        notes_in = ln.get("notes")
        if not isinstance(notes_in, list) or not notes_in:
            errors.append(f"第 {k + 1} 行缺少 notes 数组")
            continue
        out_notes = []
        for j, n in enumerate(notes_in):
            if not isinstance(n, dict):
                errors.append(f"第 {k + 1} 行第 {j + 1} 个音符不是对象")
                continue
            try:
                midi = int(round(float(n.get("midi"))))
            except (TypeError, ValueError):
                errors.append(f"第 {k + 1} 行第 {j + 1} 个音符缺少有效 midi（音高编号）")
                continue
            if not 21 <= midi <= 108:
                errors.append(f"第 {k + 1} 行第 {j + 1} 个音符 midi={midi} 超出人声范围（21~108）")
                continue
            try:
                dur = float(n.get("duration"))
            except (TypeError, ValueError):
                errors.append(f"第 {k + 1} 行第 {j + 1} 个音符缺少有效 duration（时值秒）")
                continue
            dur = min(max(dur, 0.15), 4.0)
            out_notes.append({"midi": midi, "duration": round(dur, 3)})
        if out_notes:
            out_lines.append({"line_id": len(out_lines),
                              "text": str(ln.get("text") or "").strip(),
                              "notes": out_notes})

    if errors:
        return None, errors
    if not out_lines:
        return None, ["没有任何有效音符"]

    melody = {"title": title, "key": key, "bpm": round(bpm, 1),
              "source": str(data.get("source") or "deepseek"),
              "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "lines": out_lines}
    recompute(melody)
    return melody, []


def recompute(melody):
    """重算每句/每音的起始时间（按 bpm 无关的秒制，句间留换气），并标注简谱。"""
    tonic_pc, mode = _parse_key(melody.get("key", "C major"))
    cursor = 0.0
    for idx, ln in enumerate(melody["lines"]):
        ln.setdefault("line_id", idx)
        ln["line_id"] = ln.get("line_id", idx)
        t = cursor
        for n in ln["notes"]:
            n["start"] = round(t, 3)
            t += float(n.get("duration", 0.5))
        cursor = t + LINE_GAP
    _annotate(melody["lines"], tonic_pc, mode)
    return melody


def _parse_key(key):
    parts = (key or "C major").split()
    name = parts[0] if parts[0] in NOTE_NAMES else "C"
    mode = parts[1] if len(parts) > 1 and parts[1] in ("major", "minor") else "major"
    return NOTE_NAMES.index(name), mode


def _annotate(lines, tonic_pc, mode):
    """给每个音符补 note_name 与简谱（相对主音，高八度 ' 低八度 , 升降号 # b）。"""
    sung = [(n["midi"], n["duration"]) for ln in lines for n in ln["notes"]]
    if not sung:
        return
    avg = sum(m * d for m, d in sung) / sum(d for _, d in sung)
    tonic_ref = tonic_pc + 12 * round((avg - tonic_pc) / 12)
    for ln in lines:
        for n in ln["notes"]:
            m = int(n["midi"])
            n["note_name"] = f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"
            iv = m - tonic_ref
            octv = int(np_floor(iv / 12))
            deg = iv - octv * 12
            if deg in DEGREE:
                mark = DEGREE[deg]
            elif deg == 6:
                mark = "#4"
            else:
                upper = min(k for k in DEGREE if k > deg)
                mark = "b" + DEGREE[upper]
            n["jianpu"] = mark + ("'" * octv if octv > 0 else "," * (-octv))


def np_floor(x):
    return int(x // 1)


def safe_name(name):
    return re.sub(r"[^\w\-]+", "_", str(name)).strip("_")[:40] or "melody"


def list_melodies():
    out = []
    for f in sorted(MELODIES.glob("*.json")):
        if f.name.endswith(".filled.json"):
            continue
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
            out.append({"name": f.stem,
                        "title": m.get("title", f.stem),
                        "key": m.get("key"),
                        "bpm": m.get("bpm"),
                        "lines": len(m.get("lines", [])),
                        "notes": sum(len(l.get("notes", [])) for l in m.get("lines", [])),
                        "filled": (MELODIES / (f.stem + ".filled.json")).exists()})
        except Exception:
            out.append({"name": f.stem, "title": f.stem + "（格式损坏）", "broken": True})
    return out


def load_melody(name):
    """优先加载已填词版本（.filled.json），否则原始旋律。返回 (melody, kind)。

    加载时统一重算 start/简谱，保证手写或外部来源的文件字段也完整。
    """
    name = safe_name(name)
    filled = MELODIES / (name + ".filled.json")
    if filled.exists():
        melody = json.loads(filled.read_text(encoding="utf-8"))
        kind = "filled"
    else:
        melody = json.loads((MELODIES / (name + ".json")).read_text(encoding="utf-8"))
        kind = "melody"
    try:
        recompute(melody)
    except Exception:
        pass
    return melody, kind


def save_melody(name, melody):
    name = safe_name(name)
    (MELODIES / (name + ".json")).write_text(
        json.dumps(melody, ensure_ascii=False, indent=1), encoding="utf-8")


def save_filled(name, melody):
    name = safe_name(name)
    recompute(melody)
    (MELODIES / (name + ".filled.json")).write_text(
        json.dumps(melody, ensure_ascii=False, indent=1), encoding="utf-8")


def clear_filled(name):
    name = safe_name(name)
    (MELODIES / (name + ".filled.json")).unlink(missing_ok=True)
