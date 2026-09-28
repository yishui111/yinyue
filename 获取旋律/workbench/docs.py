"""按所选旋律自动生成「填词约束文档」，供用户复制到 DeepSeek 网页对话框。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILL_TEMPLATE = ROOT / "prompts" / "填词约束模板.md"
MELODY_DOC = ROOT / "prompts" / "旋律生成文档.md"


def melody_gen_doc():
    """「让 DeepSeek 生成旋律」的约束文档全文（用户复制去网页对话框）。"""
    return MELODY_DOC.read_text(encoding="utf-8")


def build_fill_doc(melody, story="", extra=""):
    """把所选旋律注入填词约束模板，产出可直接复制的完整文档。"""
    compact, counts = [], []
    for ln in melody["lines"]:
        notes = []
        for n in ln["notes"]:
            item = {"midi": n["midi"], "duration": n["duration"]}
            if n.get("char"):
                item["char"] = n["char"]
            notes.append(item)
        compact.append({"line_id": ln["line_id"], "syllables": len(notes), "notes": notes})
        counts.append(f"第 {ln['line_id']} 句：{len(notes)} 字")
    tpl = FILL_TEMPLATE.read_text(encoding="utf-8")
    return (tpl
            .replace("{{MELODY_JSON}}", json.dumps({"lines": compact}, ensure_ascii=False, indent=1))
            .replace("{{LINE_COUNTS}}", "；".join(counts))
            .replace("{{STORY}}", story.strip() or "（未填写，请自由创作一个动人的故事）")
            .replace("{{EXTRA}}", extra.strip() or "无"))
