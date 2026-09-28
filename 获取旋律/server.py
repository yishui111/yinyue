"""旋律工作台服务端（重构版）。

流程：旋律库（DeepSeek 生成的旋律 JSON）→ 选旋律 → 生成填词文档（复制给
DeepSeek 网页）→ 粘回 JSON → 一键用 GPT-SoVITS 按旋律唱出来。

用法:  python server.py  然后浏览器打开 http://127.0.0.1:17865
"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from workbench import config as cfgmod
from workbench import melodylib
from workbench.docs import build_fill_doc, melody_gen_doc

WEB = ROOT / "web"
EXPORTS = ROOT / "exports"
EXPORTS.mkdir(exist_ok=True)
PORT = 17865

# 启动标记：watchdog 用它判断"已有服务正在启动中"，避免重复拉起
BOOT_MARK = ROOT / ".server_booting"
try:
    BOOT_MARK.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
except Exception:
    pass

app = FastAPI(title="旋律工作台")
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")

JOBS = {}
JOB_LOCK = threading.Lock()


@app.on_event("startup")
def _boot_done():
    try:
        BOOT_MARK.unlink(missing_ok=True)
    except Exception:
        pass


def _start_job(cfg: dict, name: str, first_log: str) -> str:
    """在独立子进程里启动一个任务（崩溃不连累服务端），返回 job_id。"""
    job_id = uuid.uuid4().hex[:8]
    with JOB_LOCK:
        JOBS[job_id] = {
            "stage": "prepare", "detail": "",
            "kind": cfg.get("task", "sing"),
            "log": [time.strftime("[%H:%M:%S] ") + first_log],
            "started_at": time.time(), "done": False,
            "error": None, "name": name,
        }
        done = [k for k, v in JOBS.items() if v["done"]]
        for k in done[:-10]:
            JOBS.pop(k, None)

    args = json.dumps(cfg, ensure_ascii=False)
    p = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "workbench" / "jobrunner.py"), args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    def update(stage, detail):
        with JOB_LOCK:
            j = JOBS.get(job_id)
            if j is None:
                return
            j["stage"] = stage
            j["detail"] = detail
            if detail:
                j["log"].append(time.strftime("[%H:%M:%S] ") + detail)
                if len(j["log"]) > 300:
                    del j["log"][:150]

    def watch():
        err_tail = []

        def drain_err():
            for line in p.stderr:
                err_tail.append(line.rstrip())
                if len(err_tail) > 40:
                    err_tail.pop(0)

        threading.Thread(target=drain_err, daemon=True).start()
        for line in p.stdout:
            if not line.startswith("@@"):
                continue
            try:
                msg = json.loads(line[2:])
            except json.JSONDecodeError:
                continue
            if msg.get("stage") == "saved" or "file" in msg:
                with JOB_LOCK:
                    JOBS[job_id].update(done=True)
                    JOBS[job_id]["log"].append(time.strftime("[%H:%M:%S] ")
                                               + "合成完成，页面开始播放 ✓")
                continue
            update(msg.get("stage", ""), msg.get("detail", ""))
        ret = p.wait()
        with JOB_LOCK:
            j = JOBS.get(job_id)
            if j and not j["done"]:
                j.update(done=True,
                         error=(j["error"] or
                                f"合成进程异常退出（code {ret}）\n" + "\n".join(err_tail[-8:])))

    threading.Thread(target=watch, daemon=True).start()
    return job_id


# ---------------- 页面 ----------------

@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


# ---------------- 配置 ----------------

@app.get("/api/config")
def get_config():
    return cfgmod.load()


@app.post("/api/config")
def set_config(data: dict):
    cfgmod.save(data)
    return {"ok": True}


# ---------------- 旋律库 ----------------

@app.get("/api/melodies")
def list_melodies():
    return melodylib.list_melodies()


@app.get("/api/melody")
def get_melody(name: str):
    try:
        melody, kind = melodylib.load_melody(name)
        melodylib.recompute(melody)  # 容错：手写/外部文件可能缺 start 与简谱
    except FileNotFoundError:
        raise HTTPException(404, f"旋律 {name} 不存在")
    except Exception as e:
        raise HTTPException(500, f"旋律文件损坏：{e}")
    melody["kind"] = kind
    return melody


@app.post("/api/melody/import")
def import_melody(body: dict):
    """把 DeepSeek 回复的文本（或整篇文档）粘贴进来，校验并存入旋律库。"""
    text = body.get("text") or ""
    data, err = melodylib.extract_json(text)
    if err:
        raise HTTPException(400, err)
    name = melodylib.safe_name(body.get("name") or data.get("title") or "")
    data.setdefault("title", name)
    melody, errors = melodylib.normalize_melody(data, default_title=name or "未命名旋律")
    if errors:
        raise HTTPException(400, "旋律校验未通过：" + "；".join(errors[:8]))
    melodylib.save_melody(melody["title"], melody)
    return {"ok": True, "name": melodylib.safe_name(melody["title"]), "melody": melody}


@app.post("/api/melody/save")
def save_melody(body: dict):
    """手工编辑（改音高/时值/字）后保存到当前激活的文件。"""
    name = body["name"]
    melody = body["melody"]
    melodylib.recompute(melody)
    _, kind = melodylib.load_melody(name)
    if kind == "filled":
        melodylib.save_filled(name, melody)
    else:
        melodylib.save_melody(name, melody)
    return {"ok": True}


@app.post("/api/melody/clearfill")
def clear_fill(body: dict):
    melodylib.clear_filled(body["name"])
    return {"ok": True}


# ---------------- DeepSeek 文档 ----------------

@app.get("/api/melodydoc")
def get_melody_doc():
    return {"doc": melody_gen_doc()}


@app.get("/api/filldoc")
def get_fill_doc(name: str, story: str = "", extra: str = ""):
    melody, _ = melodylib.load_melody(name)
    return {"doc": build_fill_doc(melody, story, extra)}


@app.post("/api/apply")
def apply_lyrics(body: dict):
    """把 DeepSeek 填词返回的 JSON 应用到旋律（逐字校验后写入 filled）。"""
    name = body["name"]
    melody, _ = melodylib.load_melody(name)
    data, err = melodylib.extract_json(body.get("json_text") or "")
    if err:
        raise HTTPException(400, err + "｜请让 DeepSeek「只输出 JSON」。")
    rows = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(400, "输出缺少 lines 数组，请让 DeepSeek 重新输出。")
    by_id = {ln["line_id"]: ln for ln in melody["lines"]}
    errs, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        lid = row.get("line_id")
        if lid not in by_id:
            errs.append(f"line_id={lid} 不存在")
            continue
        seen.add(lid)
        chars = row.get("chars")
        notes = by_id[lid]["notes"]
        if not isinstance(chars, list) or len(chars) != len(notes):
            got = len(chars) if isinstance(chars, list) else "非数组"
            errs.append(f"第 {lid} 句：需 {len(notes)} 字，实际 {got}")
            continue
        clean = [("" if c is None else str(c).strip()) or "啊" for c in chars]
        for n, c in zip(notes, clean):
            n["char"] = c
        by_id[lid]["new_text"] = "".join(clean)
    missing = [lid for lid in by_id if lid not in seen]
    if missing:
        errs.append(f"缺少这些行：{missing[:10]}")
    if errs:
        raise HTTPException(400, "校验未通过：" + "；".join(errs[:10])
                            + "｜请把这条错误发给 DeepSeek，让它修正后重新输出 JSON。")
    melodylib.save_filled(name, melody)
    melody["kind"] = "filled"
    return melody


# ---------------- 演唱 / 导出 ----------------

@app.post("/api/sing")
def sing(body: dict):
    cfg = cfgmod.load()
    name = body["name"]
    melody, _ = melodylib.load_melody(name)

    sing_cfg = {
        "mode": body.get("mode") or cfg.get("gptsovits_mode", "panel"),
        "url": (body.get("url") or cfg.get("gptsovits_url", "http://127.0.0.1:8550")).rstrip("/"),
        "voice": body.get("voice") if body.get("voice") is not None else cfg.get("gptsovits_voice", ""),
        "ref_audio": body.get("ref_audio") or cfg.get("gptsovits_ref_audio", ""),
        "prompt_text": body.get("prompt_text") or cfg.get("gptsovits_prompt_text", ""),
        "prompt_lang": cfg.get("gptsovits_prompt_lang", "zh"),
    }
    if sing_cfg["mode"] == "panel" and not sing_cfg["voice"]:
        raise HTTPException(400, "请先填写音色名（你 GPT-SoVITS 控制页里导入的声音模型名称）。")
    if sing_cfg["mode"] == "apiv2" and not sing_cfg["ref_audio"]:
        raise HTTPException(400, "直连 api_v2 模式需要提供参考音频的绝对路径。")
    if not any(n.get("char") or n.get("new_char") for ln in melody["lines"] for n in ln["notes"]):
        raise HTTPException(400, "这段旋律还没有可唱的字：请先填词（DeepSeek 或手动）。")

    exports = EXPORTS / melodylib.safe_name(name)
    exports.mkdir(parents=True, exist_ok=True)
    out_path = exports / "sing.wav"

    try:
        limit_seconds = int(body.get("limit_seconds") or 0)
    except (TypeError, ValueError):
        limit_seconds = 0

    tmp_json = EXPORTS / melodylib.safe_name(name) / "_sing_input.json"
    tmp_json.parent.mkdir(parents=True, exist_ok=True)
    tmp_json.write_text(json.dumps(melody, ensure_ascii=False), encoding="utf-8")

    job_id = _start_job(
        {"task": "sing", "song_json": str(tmp_json),
         "out_path": str(out_path), "sing": sing_cfg,
         "limit_seconds": limit_seconds},
        name, f"开始演唱《{melody.get('title')}》"
              f"（音色：{sing_cfg.get('voice') or sing_cfg.get('ref_audio', 'api_v2')}"
              f"{'，仅前 ' + str(limit_seconds) + ' 秒' if limit_seconds else ''}）")
    return {"job_id": job_id, "file": f"/audio/{melodylib.safe_name(name)}/sing.wav"}


@app.post("/api/export")
def export(body: dict):
    name = body["name"]
    fmt = body.get("fmt", "midi")
    melody, _ = melodylib.load_melody(name)
    d = EXPORTS / melodylib.safe_name(name)
    d.mkdir(parents=True, exist_ok=True)
    from workbench.pipeline import export as exporter
    from workbench.pipeline.hum import render_hum
    if fmt == "hum":
        p = d / "hum.wav"
        render_hum(melody, p)
    elif fmt == "karaoke":
        p = d / "karaoke.mp4"
        audio = d / "hum.wav"
        if not audio.exists():
            render_hum(melody, audio)
        from workbench.pipeline.karaoke import render_karaoke
        render_karaoke(melody, audio, p)
    elif fmt == "midi":
        p = d / "melody.mid"
        exporter.to_midi(melody, p)
    elif fmt == "musicxml":
        p = d / "melody.musicxml"
        exporter.to_musicxml(melody, p)
    elif fmt == "ust":
        p = d / "melody.ust"
        exporter.to_ust(melody, p)
    else:
        raise HTTPException(400, f"未知格式 {fmt}")
    return {"file": f"/audio/{melodylib.safe_name(name)}/{p.name}"}


@app.get("/audio/{name}/{fname:path}")
def audio(name: str, fname: str):
    p = EXPORTS / melodylib.safe_name(name) / fname
    if not p.is_file():
        raise HTTPException(404, fname)
    mt = {".wav": "audio/wav", ".mid": "audio/midi",
          ".musicxml": "application/xml", ".ust": "text/plain"}.get(
        p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=mt)


@app.get("/api/progress/{job_id}")
def get_progress(job_id: str):
    with JOB_LOCK:
        j = JOBS.get(job_id)
        if j is None:
            raise HTTPException(404, "任务不存在（服务可能被重启过）")
        return dict(j)


if __name__ == "__main__":
    import uvicorn
    print(f"旋律工作台: http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT)
