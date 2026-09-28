"""全功能回归测试套件（重构版）：对着运行中的服务逐项验证新流程所有功能。

跑法: .venv\\Scripts\\python test_suite.py
前置: 服务已启动（http://127.0.0.1:17865）。
"""
import io
import json
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).parent
BASE = "http://127.0.0.1:17865"
S = requests.Session()
S.trust_env = False

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), str(detail)))
    print(("PASS  " if ok else "FAIL  ") + name + (("  | " + str(detail)[:150]) if detail else ""), flush=True)


def wait_job(job_id, timeout=600):
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout:
        try:
            last = S.get(f"{BASE}/api/progress/{job_id}", timeout=10).json()
            if last.get("done"):
                return last
        except Exception:
            pass
        time.sleep(4)
    out = dict(last)
    out["done"] = True
    out["error"] = "等待超时"
    return out


def _char_wav(text):
    sr = 22050
    f = 330.0 * 2 ** (((hash(text) % 7) - 3) / 12.0)
    t = np.arange(int(0.25 * sr)) / sr
    y = np.concatenate([np.zeros(int(0.05 * sr)), np.sin(2 * np.pi * f * t) * 0.5,
                        np.zeros(int(0.05 * sr))])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class MockTTS(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        resp = json.dumps({"wav": __import__("base64").b64encode(_char_wav(body.get("text", "?"))).decode()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


DEEPSEEK_MELODY = '''```json
{
  "title": "回归测试旋律",
  "key": "C major",
  "bpm": 95,
  "lines": [
    {"text": "第一句", "notes": [
      {"midi": 60, "duration": 0.5}, {"midi": 62, "duration": 0.5},
      {"midi": 64, "duration": 1.0}, {"midi": 67, "duration": 1.0}]},
    {"text": "第二句", "notes": [
      {"midi": 67, "duration": 0.5}, {"midi": 69, "duration": 0.5},
      {"midi": 67, "duration": 0.5}, {"midi": 64, "duration": 1.5}]}
  ]
}
```'''


def wait_server(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if S.get(BASE + "/", timeout=5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def main():
    # T00 服务在线（最多等 3 分钟，给看门狗拉起时间）
    check("T00 服务在线", wait_server(180))

    # T01 页面
    try:
        t01 = S.get(BASE + "/", timeout=10).status_code == 200
    except Exception:
        t01 = False
    check("T01 页面可访问", t01)
    if not t01:
        print("服务不可用，后续用例跳过。")
        return summary()
    js = S.get(BASE + "/static/app.js", timeout=10).text
    check("T02 前端含新流程代码", all(k in js for k in ("genFillDoc", "applyReply", "btn-sing", "pickMelody")))

    # T03 配置
    c = S.get(BASE + "/api/config", timeout=10).json()
    check("T03 配置含演唱字段", all(k in c for k in ("gptsovits_mode", "gptsovits_url", "gptsovits_voice", "gptsovits_dir")))

    # T04 旋律库（内置示例 + 可能的用户旋律）
    ml = S.get(BASE + "/api/melodies", timeout=10).json()
    check("T04 旋律库非空(含内置示例)", any("小星星" in m.get("title", "") for m in ml), [m["name"] for m in ml])

    # T05 导入：带围栏的 DeepSeek 回复能正常入库
    r = S.post(BASE + "/api/melody/import", json={"name": "", "text": DEEPSEEK_MELODY}, timeout=15)
    ok = r.status_code == 200
    imp_name = r.json().get("name") if ok else None
    check("T05 导入旋律(容忍围栏/前后文本)", ok, r.text[:120])
    # T05b 非法旋律被拒
    r = S.post(BASE + "/api/melody/import", json={"name": "bad", "text": "{\n  \"title\": \"坏\" \n}"}, timeout=15)
    check("T05b 非法旋律被拒", r.status_code == 400)

    # T06 加载旋律：规范化完整（start/简谱/音名）
    m = S.get(f"{BASE}/api/melody?name={imp_name}", timeout=10).json()
    check("T06 加载旋律规范化", len(m["lines"]) == 2
          and all("start" in n and "jianpu" in n and "note_name" in n
                  for ln in m["lines"] for n in ln["notes"])
          and m["lines"][0]["notes"][0]["start"] == 0.0)

    # T07 保存回路
    m.pop("kind", None)
    orig = json.dumps(m, ensure_ascii=False)
    r = S.post(BASE + "/api/melody/save", json={"name": imp_name, "melody": m}, timeout=15)
    m2 = S.get(f"{BASE}/api/melody?name={imp_name}", timeout=10).json()
    m2.pop("kind", None)
    check("T07 保存回路", r.status_code == 200 and json.dumps(m2, ensure_ascii=False) == orig)

    # T08 填词文档生成
    r = S.get(f"{BASE}/api/filldoc", params={"name": imp_name, "story": "测试故事", "extra": "押 ang 韵"}, timeout=15)
    doc = r.json().get("doc", "")
    check("T08 填词文档自动生成", r.status_code == 200 and "硬性规则" in doc and "测试故事" in doc
          and "syllables" in doc and "{{" not in doc)

    # T09 填词 JSON 非法被拒
    r = S.post(BASE + "/api/apply", json={"name": imp_name, "json_text": json.dumps({"bad": 1})}, timeout=15)
    check("T09 填词 JSON 非法被拒", r.status_code == 400 and "lines" in r.text)

    # T10 填词 JSON 合法应用（全部音符逐字）并验证旋律未动
    data = {"lines": []}
    for ln in m["lines"]:
        data["lines"].append({"line_id": ln["line_id"], "chars": ["啊"] * len(ln["notes"])})
    r = S.post(BASE + "/api/apply", json={"name": imp_name, "json_text": json.dumps(data, ensure_ascii=False)}, timeout=30)
    m2 = S.get(f"{BASE}/api/melody?name={imp_name}", timeout=10).json()
    melody_same = all(a["midi"] == b["midi"] and a["duration"] == b["duration"]
                      for la, lb in zip(m["lines"], m2["lines"]) for a, b in zip(la["notes"], lb["notes"]))
    chars_ok = all(n.get("char") == "啊" for ln in m2["lines"] for n in ln["notes"])
    check("T10 填词逐字应用+旋律未动", r.status_code == 200 and chars_ok and melody_same)

    # T11 清除填词
    S.post(BASE + "/api/melody/clearfill", json={"name": imp_name}, timeout=15)
    m3 = S.get(f"{BASE}/api/melody?name={imp_name}", timeout=10).json()
    check("T11 还原原词", m3.get("kind") == "melody" and all(not n.get("char") for ln in m3["lines"] for n in ln["notes"]))

    # T12 melodydoc
    r = S.get(BASE + "/api/melodydoc", timeout=10)
    doc = r.json().get("doc", "")
    check("T12 旋律生成文档", r.status_code == 200 and "只输出一个 JSON 对象" in doc and "【填写区】" in doc)

    # T13~T16 四种导出
    for i, fmt in enumerate(("hum", "midi", "musicxml", "ust"), start=13):
        r = S.post(BASE + "/api/export", json={"name": imp_name, "fmt": fmt}, timeout=120)
        ok, det = r.status_code == 200, ""
        if ok:
            f = S.get(BASE + r.json()["file"], timeout=30)
            ok = f.status_code == 200 and len(f.content) > 80
            det = f"{len(f.content)} bytes"
        check(f"T{i:02d} 导出 {fmt}", ok, det)

    # T17 演唱合成（模拟音色 + 快速试听 15 秒）
    # 用自带歌词的《小星星》：T11 还原原词后 imp_name 已无可唱字符，演唱会被正确拒绝
    sing_name = next((mm["name"] for mm in ml if "小星星" in mm.get("title", "")), imp_name)
    r = S.post(BASE + "/api/sing", json={
        "name": sing_name, "voice": "mock",
        "url": "http://127.0.0.1:18767", "limit_seconds": 15}, timeout=30)
    jr = r.json()
    print("T17 job_id:", jr.get("job_id"), flush=True)
    job = wait_job(jr.get("job_id"), 900)
    if job.get("error") or not job.get("done"):
        print("T17 诊断:", json.dumps({k: job.get(k) for k in ("stage", "detail", "error", "log")},
                                      ensure_ascii=False)[:2500], flush=True)
    wav_ok, size = False, 0
    if not job.get("error"):
        f = S.get(BASE + jr["file"], timeout=30)
        size = len(f.content)
        wav_ok = f.status_code == 200 and size > 20000
    check("T17 演唱合成(快速试听 15 秒)", not job.get("error") and wav_ok, job.get("error") or f"{size} bytes")

    # T18 无音色时报错明确
    r = S.post(BASE + "/api/sing", json={"name": imp_name, "voice": ""}, timeout=15)
    check("T18 未填音色被拒", r.status_code == 400 and "音色" in r.text)

    # T19 进度 404 友好
    r = S.get(BASE + "/api/progress/nonexistent", timeout=10)
    check("T19 进度接口 404 友好", r.status_code == 404 and "任务不存在" in r.text)

    # T20 依赖已瘦身（demucs/faster-whisper/torch 已卸载）
    out = subprocess.run([str(ROOT / ".venv" / "Scripts" / "pip"), "list"], capture_output=True, text=True).stdout.lower()
    check("T20 依赖已瘦身(无音频大模型)", all(k not in out for k in ("demucs", "faster-whisper", "torch")))

    # 清理测试旋律与其产物
    p = ROOT / "melodies" / (imp_name + ".json")
    if p.exists():
        p.unlink()
    pf = ROOT / "melodies" / (imp_name + ".filled.json")
    if pf.exists():
        pf.unlink()
    pe = ROOT / "exports" / imp_name
    if pe.exists():
        import shutil
        shutil.rmtree(pe, ignore_errors=True)

    return summary()


def summary():
    npass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n===== 回归测试结果: {npass}/{len(RESULTS)} 通过 =====", flush=True)
    (ROOT / "tmp_test" / "last_regression.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, ok, det in RESULTS:
        if not ok:
            print("失败项:", name, "|", det[:300])
    return 0 if npass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
