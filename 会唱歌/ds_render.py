# -*- coding: utf-8 -*-
r"""常驻渲染器客户端：把 DiffSinger 渲染放进独立工作进程（ds_render_worker.py，8105）。

为什么要独立进程：DiffSinger 与 so-vits 引擎代码里有同名模块（utils/modules），
同进程导入必然冲突；分开进程各自干净。worker 的模型只加载一次，之后每次合成
只花推理本身的时间（实测 8~30 秒）；空闲 15 分钟自动退出释放显存。

合成失败时抛异常 → sing.run_diffsinger 自动退回老的子进程 infer.py 方式。
"""
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKER = ROOT / "ds_render_worker.py"
PY = ROOT / "runtime" / "py312" / "python.exe"
PORT = 8105
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _alive(timeout=3):
    try:
        with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _ensure_worker():
    if _alive():
        return
    print("[常驻渲染器] 启动渲染工作进程（首次要加载模型 40s~3min）…", flush=True)
    log = open(ROOT / "输出" / "渲染器日志.log", "ab")
    subprocess.Popen([str(PY), "-u", str(WORKER), "-p", str(PORT)], cwd=str(ROOT),
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                     close_fds=True)
    for _ in range(150):  # worker 起服务前就把模型加载好，这里等待最多 ~7.5 分钟
        if _alive():
            return
        time.sleep(3)
    raise RuntimeError("渲染工作进程 8105 未能就绪（详见 输出\\渲染器日志.log）")


def render(ds_params: list, out_wav: Path, key: int = 0, gender=None, seed: int = -1):
    _ensure_worker()
    body = json.dumps({"params": ds_params, "out": str(out_wav), "key": key,
                       "gender": gender, "seed": seed}).encode("utf-8")
    t0 = time.time()
    try:
        with OPENER.open("http://127.0.0.1:%d/render" % PORT, data=body, timeout=1800) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError("常驻渲染失败：%s %s" % (e.code, detail[:300]))
    if not out_wav.is_file():
        raise RuntimeError("常驻渲染没有产出 %s（%s）" % (out_wav, resp))
    print("[常驻渲染器] 合成用时 %.1fs" % (time.time() - t0), flush=True)


def loaded():
    return _alive()
