# -*- coding: utf-8 -*-
r"""训练工作台（8103）：页面上训练自己的二次元唱歌音色。

  GET  /              → 页面（填角色名 + 素材文件夹 → 开始训练 → 实时日志 → 导出）
  GET  /api/status    → {"running":..., "role":..., "log":最后若干行, "voices":[...]}
  POST /api/start     → {"role":"新角色", "material":"素材目录"}  开始训练（已有一个任务在跑则拒绝）
  POST /api/stop      → 结束当前训练任务
  POST /api/export    → {"role":"角色"} 把最新权重导出到 换声引擎\models\（页面立即可选）
  GET  /health

只做编排：训练走 训练流水线.py 子进程，日志落 训练\日志\<角色>.log。
用法：runtime\py312\python.exe 训练\训练工作台.py [-p 8103]
"""
import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TRAIN_ROOT = Path(__file__).resolve().parent
STATIC_DIR = TRAIN_ROOT / "static"
LOG_DIR = TRAIN_ROOT / "日志"
PY = TRAIN_ROOT.parent / "runtime" / "py312" / "python.exe"
sys.path.insert(0, str(TRAIN_ROOT.parent / "换声引擎"))
import svc_local  # 角色列表来自 换声引擎\models\

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
JOB_LOCK = threading.Lock()
JOB = {"proc": None, "role": "", "log": "", "t_start": 0.0, "t_end": 0.0}


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

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            f = STATIC_DIR / "index.html"
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES[".html"])
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/health":
            return self.send_json({"status": "ok", "running": self.job_running(),
                                   "role": JOB["role"]})
        if path == "/api/status":
            tail = ""
            lp = Path(JOB["log"])
            if lp.is_file():
                with open(lp, "rb") as f:
                    raw = f.read()[-4000:]
                tail = raw.decode("utf-8", "replace")
            return self.send_json({"running": self.job_running(), "role": JOB["role"],
                                   "elapsed": round((JOB["t_end"] or time.time()) - JOB["t_start"])
                                   if JOB["t_start"] else 0,
                                   "log": tail[-3500:], "voices": svc_local.roles()})
        self.send_json({"error": "no route: %s" % path}, 404)

    @staticmethod
    def job_running():
        with JOB_LOCK:
            return JOB["proc"] is not None and JOB["proc"].poll() is None

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self.send_json({"error": "请求体不是合法 JSON"}, 400)

        if path == "/api/start":
            if self.job_running():
                return self.send_json({"error": "已有训练任务在跑（角色：%s）" % JOB["role"]}, 409)
            role = (req.get("role") or "").strip()
            material = (req.get("material") or "").strip()
            f0 = (req.get("f0") or "rmvpe").strip()
            if not role or any(c in role for c in '\\/:*?"<>| '):
                return self.send_json({"error": "角色名不能为空，且不能含空格和 \\/:*?\"<>|"}, 400)
            mdir = Path(material)
            if not mdir.is_dir():
                return self.send_json({"error": "素材文件夹不存在：%s" % material}, 400)
            args = ["-u", "训练流水线.py", "全流程", role, material, "--f0", f0]
            LOG_DIR.mkdir(exist_ok=True)
            logfile = LOG_DIR / ("%s.log" % role)
            with JOB_LOCK:
                logf = open(logfile, "ab")
                proc = subprocess.Popen(
                    [str(PY)] + args, cwd=str(TRAIN_ROOT),
                    env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                    stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
                JOB.update(proc=proc, role=role, log=str(logfile),
                           t_start=time.time(), t_end=0.0)
            return self.send_json({"ok": True, "msg": "训练已开始（日志：%s）" % logfile})

        if path == "/api/stop":
            with JOB_LOCK:
                if JOB["proc"] is None or JOB["proc"].poll() is not None:
                    return self.send_json({"error": "当前没有训练任务"}, 400)
                JOB["proc"].terminate()
                JOB["t_end"] = time.time()
            return self.send_json({"ok": True, "msg": "已发送停止信号；断点已保留，可重新开始续训"})

        if path == "/api/export":
            role = (req.get("role") or "").strip()
            if not role:
                return self.send_json({"error": "缺少角色名"}, 400)
            try:
                p = subprocess.run([str(PY), "训练流水线.py", "导出", role], cwd=str(TRAIN_ROOT),
                                   env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=600)
                if p.returncode != 0:
                    return self.send_json({"error": (p.stderr or p.stdout or "")[-400:]}, 500)
                return self.send_json({"ok": True, "msg": (p.stdout or "")[-300:]})
            except Exception as e:
                return self.send_json({"error": repr(e)}, 500)

        self.send_json({"error": "no route: %s" % path}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=8103)
    args = ap.parse_args()
    LOG_DIR.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("训练工作台 http://127.0.0.1:%d（角色输出 → 换声引擎\\models\\）"
          % args.port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
