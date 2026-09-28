# -*- coding: utf-8 -*-
"""
做音乐 · 本地网页服务

双击 启动.bat 启动(自动打开浏览器),双击 停止.bat 关闭。
页面功能:粘贴 DeepSeek 生成的歌词/曲谱 → 合成整首歌 → 页面试听;也可自检环境、浏览历史作品。
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parent
WORKS = ROOT / "作品"
# 合成子进程必须与网页服务用同一个 Python(同一个 torch 环境)
PY = Path(sys.executable)
PORT = int(os.environ.get("YUE2_PORT", "7866"))
CONFIG = ROOT / "config.json"
MELODIES = ROOT / "旋律库"
SINGLE_JOB_LOCK = threading.Lock()

app = Flask(__name__)
JOBS = {}  # job_id -> {proc, lines, state, folder, start, end, stop}


def _safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "", (name or "").strip()) or ""
    return name[:50]


def _start_job(folder: Path):
    if not SINGLE_JOB_LOCK.acquire(blocking=False):
        raise RuntimeError("已有一首歌正在合成(显存一次只能跑一首),请等它完成或先停止。")
    job_id = uuid.uuid4().hex[:12]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONFAULTHANDLER": "1"}
    log_file = folder / "合成日志.txt"
    job = {"proc": None, "lines": [], "state": "合成中", "folder": str(folder),
           "start": time.time(), "end": None, "stop": False}

    def _target():
        with open(log_file, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(PY), str(ROOT / "sing.py"), str(folder)],
                cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env,
            )
            job["proc"] = proc
            for line in proc.stdout:
                job["lines"].append(line.rstrip())
                del job["lines"][:-300]
                log.write(line)
                log.flush()
            code = proc.wait()
            if job.get("stop"):
                job["state"] = "已停止"
            elif code == 0:
                job["state"] = "完成"
            else:
                job["state"] = "失败"
                job["lines"].append(f"[服务] 子进程退出码 {code},完整日志见 {log_file.name}")
            log.write(f"[服务] 任务结束: {job['state']}\n")
            job["end"] = time.time()
            job["proc"] = None
            SINGLE_JOB_LOCK.release()

    JOBS[job_id] = job
    # 只保留最近 20 个任务记录,防止长期运行内存膨胀
    done = [k for k, v in JOBS.items() if v["state"] != "合成中"]
    for k in done[:max(0, len(JOBS) - 20)]:
        JOBS.pop(k, None)
    threading.Thread(target=_target, daemon=True).start()
    return job_id


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/check")
def api_check():
    r = subprocess.run([str(PY), str(ROOT / "sing.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env={**os.environ, "PYTHONUTF8": "1"}, timeout=120)
    return jsonify({"text": (r.stdout or "") + (r.stderr or "")})


@app.get("/api/constraint_doc")
def api_constraint_doc():
    """下载『发给 DeepSeek 的约束词』文档。"""
    return send_from_directory(
        ROOT / "文档", "约束文档-故事转歌词与旋律.md",
        as_attachment=True, download_name="发给DeepSeek的约束词.md",
    )


@app.get("/api/health")
def api_health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------- DeepSeek 词曲生成
def _deepseek_key():
    if CONFIG.is_file():
        try:
            return (json.loads(CONFIG.read_text(encoding="utf-8")) or {}).get("deepseek_key", "")
        except Exception:
            return ""
    return ""


def _parse_llm_output(text: str):
    """从 DeepSeek 回复中提取 ```json 与 ```abc 两段;json 做语法校验。"""
    js = re.search(r"```json\s*(.+?)```", text, re.S)
    ab = re.search(r"```abc\s*(.*?)```", text, re.S)
    song_raw = js.group(1).strip() if js else ""
    abc = ab.group(1).strip() if ab else ""
    if song_raw:
        i, j = song_raw.find("{"), song_raw.rfind("}")
        if 0 <= i < j:
            song_raw = song_raw[i:j + 1]
        json.loads(song_raw)
    else:
        raise ValueError("没有找到 ```json 代码块")
    return song_raw, abc


def _validate_abc(native_text: str):
    """进程内调用官方 abc_tools 解析器校验,返回 (是否通过, 错误信息)。"""
    try:
        sys.path.insert(0, str((ROOT / "YuE" / "skills" / "yue2-music" / "scripts")))
        import abc_tools
        abc_tools.parse_abc(native_text)
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


def _call_deepseek(messages, temperature=1.3, max_tokens=8192):
    key = _deepseek_key()
    if not key:
        return None, (400, "还没有保存 DeepSeek API 密钥,请先在上方填入并点「保存密钥」")
    body = json.dumps({"model": "deepseek-chat", "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return None, (502, f"DeepSeek 接口返回 {e.code}:{detail}")
    except Exception as e:
        return None, (502, f"调用 DeepSeek 失败:{e}")
    text = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if not text:
        return None, (502, "DeepSeek 返回了空内容")
    return text, None


@app.get("/api/llm/key")
def api_llm_key_get():
    key = _deepseek_key()
    return jsonify({"has_key": bool(key), "tail": key[-4:] if key else ""})


@app.post("/api/llm/key")
def api_llm_key_set():
    data = request.get_json(force=True, silent=True) or {}
    key = (data.get("key") or "").strip()
    CONFIG.write_text(json.dumps({"deepseek_key": key}, ensure_ascii=False), encoding="utf-8")
    return jsonify({"saved": bool(key)})


@app.get("/api/melodies")
def api_melodies():
    items = []
    if MELODIES.is_dir():
        for p in sorted(MELODIES.glob("*.abc")):
            m = re.search(r"Q:1/4=(\d+)", p.read_text(encoding="utf-8"))
            items.append({"name": p.stem, "bpm": int(m.group(1)) if m else None})
    return jsonify({"melodies": items, "dir": str(MELODIES)})


@app.get("/api/melodies/<name>")
def api_melody(name):
    p = MELODIES / (_safe_name(name) + ".abc")
    if not p.is_file():
        return jsonify({"error": "曲库里没有这份曲谱"}), 404
    return jsonify({"name": p.stem, "abc": p.read_text(encoding="utf-8")})


@app.post("/api/llm/generate")
def api_llm_generate():
    data = request.get_json(force=True, silent=True) or {}
    story = (data.get("story") or "").strip()
    if not story:
        return jsonify({"error": "请先填写故事"}), 400
    key = _deepseek_key()
    if not key:
        return jsonify({"error": "还没有保存 DeepSeek API 密钥,请先在上方填入并点「保存密钥」"}), 400
    melody = _safe_name(data.get("melody") or "")
    abc_content = ""
    if melody:
        mpath = MELODIES / (melody + ".abc")
        if not mpath.is_file():
            return jsonify({"error": f"旋律库里没有 {melody}"}), 400
        abc_content = mpath.read_text(encoding="utf-8")
    doc = (ROOT / "文档" / "约束文档-故事转歌词与旋律.md").read_text(encoding="utf-8")
    if abc_content:
        sys_prompt = (doc + "\n\n本次旋律已由用户指定,严格不要再输出 ```abc 代码块,"
                      "只输出一个 ```json 代码块(字段 id/style/lyrics/cot/seed)。"
                      "cot 用 \"melody\";style 以语言开头,乐器情绪按故事定,但结尾 BPM 必须"
                      "与曲谱 Q: 完全一致;lyrics 的段落与行数对应曲谱的 % 注释段落,"
                      "每行汉字数尽量等于该行旋律音符数(中文一字对一音)。")
        user_content = "这是我的故事,请据此为给定旋律填词:\n" + story + \
                       "\n\n【用户指定的旋律曲谱】\n" + abc_content
    else:
        sys_prompt = (doc + "\n\n你是严格按上述约束文档工作的作词作曲助手。"
                              "只输出两个代码块(```json 和 ```abc),不要输出任何其他文字。")
        user_content = "这是我的故事,请据此创作歌曲:\n" + story
    text, err = _call_deepseek([
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ])
    if err:
        code, msg = err
        return jsonify({"error": msg}), code
    try:
        song_raw, abc = _parse_llm_output(text)
    except Exception as e:
        return jsonify({"error": f"输出不符合约束文档格式({e}),下面是原文,可手动复制使用", "raw": text}), 422
    song = json.loads(song_raw)
    if abc_content:
        if song.get("cot") not in ("full", "melody"):
            song["cot"] = "full"
        return jsonify({"name": melody,
                        "song_json": json.dumps(song, ensure_ascii=False, indent=2),
                        "score_abc": abc_content})
    name = _safe_name(song.get("id") or "新歌") or "新歌"
    return jsonify({"name": name,
                    "song_json": json.dumps(song, ensure_ascii=False, indent=2),
                    "score_abc": abc})


@app.post("/api/llm/melody")
def api_llm_melody():
    """曲谱工坊:让 DeepSeek 写一段全新原创旋律,官方校验通过后存入旋律库。"""
    data = request.get_json(force=True, silent=True) or {}
    desc = (data.get("desc") or "").strip()
    name = _safe_name(data.get("name") or "")
    if not desc:
        return jsonify({"error": "请描述想要的旋律(风格/情绪/拍号/速度等)"}), 400
    if not name:
        return jsonify({"error": "请给旋律起个名字(将用作文件名)"}), 400
    doc = (ROOT / "文档" / "约束文档-故事转歌词与旋律.md").read_text(encoding="utf-8")
    sys_prompt = (doc + "\n\n你是作曲助手。只输出一个 ```abc 代码块(X:1 开头,T: 行留空),"
                  "严格按文档的方言规范:头部两行 V: 声部声明、K: 调式;"
                  "每 1~4 小节一组交替 V: Vocal(引号和弦+人声旋律)与 V: Ins(休止 Z)。"
                  "写一段 8~16 小节的全新原创旋律,不许模仿任何现有歌曲;"
                  "拍号/调式/BPM 按用户描述定。不要输出任何其他文字。")
    user_prompt = f"旋律名字:{name}\n旋律描述:{desc}"
    text = ""
    last_err = ""
    for attempt in range(2):
        msgs = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}]
        if attempt == 1 and last_err:
            msgs[1]["content"] += ("\n\n注意:你上一次的输出未通过校验:" + last_err +
                                   "\n请修正后重新输出完整 ```abc 代码块。")
        text, err = _call_deepseek(msgs, temperature=1.4)
        if err:
            code, msg = err
            return jsonify({"error": msg}), code
        ab = re.search(r"```abc\s*(.*?)```", text, re.S)
        if not ab:
            last_err = "输出中没有 ```abc 代码块"
            continue
        native = ab.group(1).strip() + "\n"
        ok, verr = _validate_abc(native)
        if ok:
            out = MELODIES / (name + ".abc")
            k = 2
            while out.exists():
                out = MELODIES / (f"{name}-{k}.abc")
                k += 1
            out.write_text(native, encoding="utf-8")
            return jsonify({"saved": True, "name": out.stem, "abc": native})
        last_err = verr
    return jsonify({"error": f"两次生成的旋律都没能通过官方校验(最后一次:{last_err})。",
                    "raw": text}), 422


@app.get("/api/doc/extract")
def api_doc_extract():
    """下载『旋律提取约束词』:教 DeepSeek 把一首歌变成曲库曲谱。"""
    return send_from_directory(ROOT / "文档", "旋律提取约束文档.md", as_attachment=True,
                               download_name="给DeepSeek-旋律提取约束词.md")


@app.get("/api/doc/lyrics")
def api_doc_lyrics():
    """下载『按旋律填词约束词』:选定旋律 + 故事 → DeepSeek 只写歌词。"""
    return send_from_directory(ROOT / "文档", "按旋律填词约束文档.md", as_attachment=True,
                               download_name="给DeepSeek-按旋律填词约束词.md")


@app.post("/api/melodies/upload")
def api_melodies_upload():
    """从文件入库:校验通过才收,重名自动加序号。"""
    data = request.get_json(force=True, silent=True) or {}
    name = _safe_name(data.get("name") or "")
    content = (data.get("abc") or "").strip()
    if not name or not content:
        return jsonify({"error": "需要文件名与曲谱内容"}), 400
    if not content.lstrip().startswith("X:") or re.search(r"^w:", content, re.M):
        return jsonify({"error": "不是受支持的 ABC 曲谱(应以 X:1 开头,且不含 w: 歌词行)"}), 400
    ok, err = _validate_abc(content + "\n")
    if not ok:
        return jsonify({"error": f"官方校验未通过:{err}"}), 422
    out = MELODIES / (name + ".abc")
    k = 2
    while out.exists():
        out = MELODIES / (f"{name}-{k}.abc")
        k += 1
    out.write_text(content + "\n", encoding="utf-8")
    return jsonify({"saved": True, "name": out.stem})


@app.get("/api/example")
def api_example():
    src = ROOT / "测试" / "案例1-中文词曲完整流程"
    data = {"name": "示例-雪夜小狐狸"}
    for key, fname in (("song_json", "song.json"), ("score_abc", "score.abc")):
        p = src / fname
        data[key] = p.read_text(encoding="utf-8") if p.exists() else ""
    return jsonify(data)


@app.post("/api/sing")
def api_sing():
    data = request.get_json(force=True, silent=True) or {}
    name = _safe_name(data.get("name"))
    if not name:
        return jsonify({"error": "请先填写歌名"}), 400
    try:
        song = json.loads(data.get("song_json") or "")
    except json.JSONDecodeError as exc:
        return jsonify({"error": f"歌词 JSON 解析失败:{exc}"}), 400
    if not isinstance(song, dict) or not song.get("lyrics") or not song.get("style"):
        return jsonify({"error": "歌词 JSON 里必须有 style 和 lyrics 字段(对照约束文档检查)"}), 400

    abc = (data.get("score_abc") or "").strip()
    if abc and song.get("cot") not in ("full", "melody"):
        song["cot"] = "full"

    folder = WORKS / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "song.json").write_text(json.dumps(song, ensure_ascii=False, indent=2), encoding="utf-8")
    if abc:
        (folder / "score.abc").write_text(abc + "\n", encoding="utf-8")
    else:
        (folder / "score.abc").unlink(missing_ok=True)

    try:
        job_id = _start_job(folder)
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "folder": str(folder)}), 409
    return jsonify({"job": job_id, "folder": str(folder)})


@app.get("/api/status/<job_id>")
def api_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    elapsed = (job["end"] or time.time()) - job["start"]
    return jsonify({"state": job["state"], "elapsed": round(elapsed),
                    "lines": job["lines"][-40:], "folder": job["folder"]})


@app.post("/api/stop/<job_id>")
def api_stop(job_id):
    job = JOBS.get(job_id)
    if not job or not job["proc"]:
        return jsonify({"error": "没有正在运行的任务"}), 404
    job["stop"] = True
    job["proc"].terminate()
    return jsonify({"ok": True})


@app.get("/api/works")
def api_works():
    items = []
    if WORKS.is_dir():
        for d in sorted(WORKS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            audio = d / "audio.flac"
            item = {"name": d.name, "singed": audio.is_file(),
                    "mtime": int(d.stat().st_mtime), "audio_url": None,
                    "seconds": None, "has_abc": (d / "score.abc").is_file()}
            if audio.is_file():
                item["audio_url"] = f"/works/{d.name}/audio.flac"
                result = d / "result.json"
                if result.is_file():
                    try:
                        item["seconds"] = json.loads(result.read_text(encoding="utf-8")).get("audio_seconds")
                    except Exception:
                        pass
            items.append(item)
    return jsonify({"works": items, "root": str(WORKS)})


@app.get("/works/<path:relpath>")
def works_file(relpath):
    return send_from_directory(WORKS, relpath)


if __name__ == "__main__":
    import faulthandler
    import traceback
    try:
        WORKS.mkdir(exist_ok=True)
        log_path = ROOT / "服务日志.txt"
        if log_path.is_file() and log_path.stat().st_size > 10 * 2**20:
            log_path.replace(ROOT / "服务日志-旧.txt")   # 日志超 10MB 轮转
        (ROOT / ".server.pid").write_text(str(os.getpid()), encoding="ascii")
        # 无窗口运行(pythonw)时 stdout/stderr 不存在,统一重定向到服务日志
        log = open(ROOT / "服务日志.txt", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        faulthandler.enable(log)
        print(f"===== 服务启动 {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} =====")
        print(f"[做音乐] 页面 http://127.0.0.1:{PORT}  (用 停止.bat 关闭)", flush=True)
        app.run(host="127.0.0.1", port=PORT, threaded=True)
    except Exception:
        (ROOT / "服务崩溃.txt").write_text(
            time.strftime('%Y-%m-%d %H:%M:%S') + "\n" + traceback.format_exc(), encoding="utf-8")
        raise
