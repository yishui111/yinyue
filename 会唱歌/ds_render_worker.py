# -*- coding: utf-8 -*-
r"""常驻 DiffSinger 渲染工作进程（独立进程，端口 8105）。

为什么独立进程：DiffSinger 与 so-vits 的代码里有同名模块（utils/modules），
同进程导入必然冲突；分开进程后各自干净，且模型常驻本进程、只加载一次。

接口（仅本机）：
  GET  /health               → {"loaded": bool}
  POST /render               → {"params":[...], "out":"绝对路径.wav", "key":0, "gender":0, "seed":-1}
  空闲 15 分钟自动退出（释放显存/内存）；由 sing_service 的 ds_render 客户端拉起。

启动：runtime\py312\python.exe ds_render_worker.py [-p 8105]
"""
import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT / "diffsinger"
EXP_NAME = "0211_opencpop_ds1000_keyshift"
IDLE_EXIT_SECS = 900

sys.stdout.reconfigure(encoding="utf-8")


class Renderer:
    def __init__(self):
        t0 = time.time()
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))  # diffsinger 的 utils/modules 包
        old_cwd, old_argv = os.getcwd(), sys.argv
        sys.argv = [str(REPO / "scripts" / "infer.py"), "--exp_name", EXP_NAME, "--infer"]
        try:
            os.chdir(REPO)
            from utils.hparams import set_hparams
            set_hparams()
            from inference.ds_acoustic import DiffSingerAcousticInfer
            self.infer_ins = DiffSingerAcousticInfer(load_vocoder=True)
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)
        print("[worker] 模型加载完成，用时 %.1fs" % (time.time() - t0), flush=True)
        self.loaded_at = time.time()


def render(r: Renderer, body):
    params = body["params"]
    key = int(body.get("key") or 0)
    if key:
        from utils.infer_utils import trans_key
        params = trans_key(params, key)
    gender = body.get("gender")
    if gender is not None:
        for p in params:
            p["gender"] = gender
    out = Path(body["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    old_cwd = os.getcwd()
    try:
        os.chdir(REPO)
        r.infer_ins.run_inference(params, out_dir=out.parent, title=out.stem,
                                  num_runs=1, seed=int(body.get("seed", -1)))
    finally:
        os.chdir(old_cwd)
    if not out.is_file():
        raise RuntimeError("渲染没有产出 %s" % out)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 安静模式：渲染日志走模型自己的输出

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        import urllib.parse
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            return self._json({"loaded": RENDER.get("r") is not None})
        self._json({"error": "no route"}, 404)

    def do_POST(self):
        import urllib.parse
        path = urllib.parse.urlparse(self.path).path
        if path != "/render":
            return self._json({"error": "no route"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        try:
            t0 = time.time()
            render(RENDER["r"], body)
            self._json({"ok": True, "secs": round(time.time() - t0, 1)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": repr(e)}, 500)


RENDER = {"r": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=8105)
    args = ap.parse_args()
    RENDER["r"] = Renderer()  # 启动即加载（工作进程就是干这个的）
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("[worker] ready on %d" % args.port, flush=True)

    last_hit = {"t": time.time()}

    def idle_watch():
        while True:
            time.sleep(60)
            if time.time() - last_hit["t"] > IDLE_EXIT_SECS:
                print("[worker] 空闲超过 %d 秒，自动退出释放显存" % IDLE_EXIT_SECS, flush=True)
                os._exit(0)

    import threading
    threading.Thread(target=idle_watch, daemon=True).start()
    orig = Handler.do_POST

    def do_POST_with_hit(self):
        last_hit["t"] = time.time()
        orig(self)

    Handler.do_POST = do_POST_with_hit
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
