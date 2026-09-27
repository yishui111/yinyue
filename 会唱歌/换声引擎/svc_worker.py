# -*- coding: utf-8 -*-
r"""本地换声工作进程（独立进程，端口 8106）。

为什么独立进程：so-vits 的 onnxruntime(CUDA) 与服务主进程共存时会在角色加载阶段
原生崩溃；独立进程环境干净（与 命令行 svc_local 直跑完全一致），角色模型按需加载、
缓存复用，空闲 15 分钟自动退出释放显存。

接口（仅本机）：
  GET  /health   → {"ok": true, "roles": [...], "loaded_role": "..."}
  POST /convert  → {"in": wav绝对路径, "out": wav绝对路径, "role": "...",
                    "transpose": 0, "auto_f0": true, "cluster_ratio": 0}
由 sing_service（sing.py convert_voice）拉起和调用。

启动：runtime\py312\python.exe 换声引擎\svc_worker.py [-p 8106]
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
IDLE_EXIT_SECS = 900

sys.stdout.reconfigure(encoding="utf-8")
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
import svc_local  # noqa: E402  复用 DLL 补丁/角色扫描/convert

last_hit = {"t": time.time()}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            loaded = svc_local._loaded[0] if svc_local._loaded else None
            return self._json({"ok": True, "roles": svc_local.roles(), "loaded_role": loaded})
        self._json({"error": "no route"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/convert":
            return self._json({"error": "no route"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        src, dst = Path(body["in"]), Path(body["out"])
        try:
            data, sr = svc_local.convert(
                src.read_bytes(), body["role"],
                transpose=int(body.get("transpose") or 0),
                auto_f0=bool(body.get("auto_f0", True)),
                cluster_ratio=float(body.get("cluster_ratio") or 0),
                f0_predictor=body.get("f0_predictor", "rmvpe"))
            dst.write_bytes(data)
            self._json({"ok": True, "sr": sr, "bytes": len(data)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": repr(e)}, 500)


def idle_watch():
    while True:
        time.sleep(60)
        if time.time() - last_hit["t"] > IDLE_EXIT_SECS:
            print("[svc worker] 空闲超过 %d 秒，自动退出释放显存" % IDLE_EXIT_SECS, flush=True)
            os._exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=8106)
    args = ap.parse_args()
    threading.Thread(target=idle_watch, daemon=True).start()
    orig = Handler.do_POST

    def do_POST_with_hit(self):
        last_hit["t"] = time.time()
        orig(self)

    Handler.do_POST = do_POST_with_hit
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("[svc worker] ready on %d，角色目录 %s" % (args.port, svc_local.MODELS_DIR), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
