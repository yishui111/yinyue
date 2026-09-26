# -*- coding: utf-8 -*-
r"""
会唱歌 HTTP 服务（8102）：给「获取旋律」工作台页（或其他调用方）一个唱歌接口。

接口：
  GET  /                → 工作台页面（static\index.html）
  GET  /static/<文件>    → 页面静态资源
  GET  /health          → {"status":"ok","model":...,"model_ready":...,"svc_roles":[...]}
  GET  /api/demo        → {"song": 小星星 song.json, "lyrics": 示例填词}
  POST /sing            → 请求体 JSON：
        {"song": {...song.json 原样...},
         "lyrics": {"lines":[{"line_id":0,"text":"弯弯月亮像小船"}]},   ← text 或 chars 均可；
                    整项省略则唱 song 里的原字
         "role": "furina",      ← 可选，6843 的角色，填了就再换二次元音色
         "key": 0, "gender": 0, "seed": -1}
        返回 audio/wav（同步推理，长歌要等几十秒；错误返回 JSON）
  逐条警告放在响应头 X-Sing-Warnings（urlencoded，多行用 | 分隔）

只做编排（.ds 生成 + 子进程推理 + 6843 转发），不起任何模型。
用法：runtime\py312\python.exe sing_service.py [-a 127.0.0.1] [-p 8102]
"""
import argparse
import json
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sing

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
TESTDATA = ROOT / "testdata"
SPEC_DOC = ROOT / "DeepSeek生成songjson要求文档.md"
RENDER_LOCK = threading.Lock()

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
                 ".ico": "image/x-icon", ".wav": "audio/wav", ".json": "application/json; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args), flush=True)

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path, download_name=""):
        if not path.is_file():
            return self.send_json({"error": "文件不存在: %s" % path.name}, 404)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send_file(STATIC_DIR / "index.html")
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            if "/" in name or ".." in name:
                return self.send_json({"error": "bad path"}, 400)
            return self.send_file(STATIC_DIR / name)
        if path == "/api/demo":
            return self.send_json({
                "song": json.loads((TESTDATA / "小星星.json").read_text(encoding="utf-8-sig")),
                "lyrics": json.loads((TESTDATA / "填词示例.json").read_text(encoding="utf-8-sig")),
            })
        if path == "/api/spec":
            # 下载「DeepSeek 生成 song.json 要求文档」
            if not SPEC_DOC.is_file():
                return self.send_json({"error": "要求文档不存在"}, 404)
            data = SPEC_DOC.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s"
                             % urllib.parse.quote(SPEC_DOC.name))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/health":
            roles = []
            try:
                with sing.OPENER.open(sing.SVC_URL + "/models", timeout=4) as r:
                    roles = json.loads(r.read().decode("utf-8"))
            except Exception:
                pass
            return self.send_json({
                "status": "ok",
                "model": sing.EXP_NAME,
                "model_ready": (sing.DIFFSINGER / "checkpoints" / sing.EXP_NAME).is_dir()
                               and sing.RUNTIME_PY.is_file(),
                "svc_roles": roles,
            })
        self.send_json({"error": "no route: %s" % path}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/sing":
            return self.send_json({"error": "no route: %s" % path}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            return self.send_json({"error": "请求体不是合法 JSON: %r" % e}, 400)

        song = req.get("song")
        if not song or not song.get("lines"):
            return self.send_json({"error": "缺少 song（获取旋律 工作台的 song.json 结构）"}, 400)

        warnings = []
        try:
            with RENDER_LOCK:
                title = (song.get("title") or "song").strip() or "song"
                safe = "".join(c for c in title if c not in '\\/:*?"<>|') or "song"
                with tempfile.TemporaryDirectory(prefix="sing_") as td:
                    tdp = Path(td)
                    ds_path = tdp / ("%s.ds" % safe)
                    import ds_builder
                    ds = ds_builder.build_ds(song, req.get("lyrics"), warnings)
                    ds_path.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
                    dry = tdp / ("%s_干声.wav" % safe)
                    sing.run_diffsinger(ds_path, dry,
                                        key=int(req.get("key") or 0),
                                        gender=req.get("gender"),
                                        seed=int(req.get("seed", -1)))
                    final = dry
                    role = (req.get("role") or "").strip()
                    if role:
                        final = tdp / ("%s_%s.wav" % (safe, role))
                        sing.convert_voice(dry, role, final)
                    data = final.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            if warnings:
                self.send_header("X-Sing-Warnings",
                                 urllib.parse.quote("|".join(warnings)))
            fname = urllib.parse.quote("%s_唱歌.wav" % safe)
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s" % fname)
            self.end_headers()
            self.wfile.write(data)
        except ValueError as e:
            # 歌词字数不匹配等用户输入问题：把逐条警告一起带回
            return self.send_json({"error": str(e), "warnings": warnings}, 400)
        except Exception as e:
            return self.send_json({"error": repr(e), "warnings": warnings}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-a", "--host", default="127.0.0.1")
    ap.add_argument("-p", "--port", type=int, default=8102)
    a = ap.parse_args()
    sing.OUT_DIR.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("会唱歌服务 http://%s:%d  （POST /sing，GET /health；模型 %s）"
          % (a.host, a.port, sing.EXP_NAME), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
