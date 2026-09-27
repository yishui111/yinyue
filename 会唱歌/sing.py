# -*- coding: utf-8 -*-
r"""
把「旋律 + 歌词」真正唱出来：
  song.json + 填词 JSON → ds_builder 生成 .ds → DiffSinger 本地推理出干声
  → （可选 --role）用本地换声引擎换成二次元角色音色 → 输出 wav

用法：
  runtime\py312\python.exe sing.py song.json [填词.json] [-o 输出.wav]
       [--role furina] [--key 0] [--gender 0] [--seed -1]

模型：checkpoints\0211_opencpop_ds1000_keyshift（openvpi 官方发布，中文，
      Opencpop+DS-1000 训练，仅限非商业用途）+ nsf_hifigan 声码器。
角色音色：换声引擎\models\（so-vits-svc 本地换声，见 换声引擎\svc_local.py）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME_PY = ROOT / "runtime" / "py312" / "python.exe"
DIFFSINGER = ROOT / "diffsinger"
ENGINE = ROOT / "换声引擎"
EXP_NAME = "0211_opencpop_ds1000_keyshift"
OUT_DIR = ROOT / "输出"


def build_ds_file(song_path: Path, lyrics_path, ds_path: Path):
    sys.path.insert(0, str(ROOT))
    import ds_builder
    song = json.loads(song_path.read_text(encoding="utf-8-sig"))
    lyrics = None
    if lyrics_path:
        lyrics = json.loads(Path(lyrics_path).read_text(encoding="utf-8-sig"))
    warnings = []
    ds = ds_builder.build_ds(song, lyrics, warnings)
    for w in warnings:
        print("[警告] %s" % w, flush=True)
    ds_path.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
    print("[1/3] .ds 已生成: %s（%d 段）" % (ds_path.name, len(ds)), flush=True)
    return song


def run_diffsinger(ds_path: Path, out_wav: Path, key=0, gender=None, seed=-1):
    if not RUNTIME_PY.is_file():
        raise RuntimeError("缺 runtime\\py312\\python.exe，先跑 安装环境.bat")
    if not (DIFFSINGER / "checkpoints" / EXP_NAME).is_dir():
        raise RuntimeError("缺模型 checkpoints\\%s，先跑 安装环境.bat 或看 说明.md" % EXP_NAME)
    # 首选：常驻渲染器（模型进程内只加载一次，第二次合成起只要推理本身的时间）
    try:
        import ds_render
        print("[2/3] DiffSinger 推理中（常驻渲染器%s）…" %
              ("已就绪" if ds_render.loaded() else "首次要加载模型 40s~3min"), flush=True)
        ds_params = json.loads(ds_path.read_text(encoding="utf-8"))
        ds_render.render(ds_params, out_wav, key=key, gender=gender, seed=seed)
        return
    except Exception as e:
        print("      常驻渲染器异常，退回子进程方式：%r" % (e,), flush=True)
    # 回退：子进程推理（输出直接落日志文件，进程意外退出也能看到死前的输出）
    out_dir = out_wav.parent
    title = out_wav.stem
    cmd = [str(RUNTIME_PY), "-u", "scripts/infer.py", "acoustic", str(ds_path),
           "--exp", EXP_NAME, "--out", str(out_dir), "--title", title,
           "--key", str(key)]
    if gender is not None:
        cmd += ["--gender", str(gender)]
    if seed >= 0:
        cmd += ["--seed", str(seed)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    print("[2/3] DiffSinger 推理中（子进程，首次加载模型要几十秒）…", flush=True)
    # 推理输出直接落日志文件：不走管道，进程意外退出也能看到死前的输出
    log_path = OUT_DIR / "推理日志.log"
    last_err = ""
    for attempt in (1, 2):
        t0 = time.time()
        with open(log_path, "ab") as log:
            log.write(("\n==== %s 第 %d 次尝试 ====\n"
                       % (time.strftime("%H:%M:%S"), attempt)).encode("utf-8"))
            log.flush()
            p = subprocess.run(cmd, cwd=str(DIFFSINGER), env=env,
                               stdout=log, stderr=subprocess.STDOUT,
                               timeout=1800)
        if p.returncode == 0 and out_wav.is_file():
            print("      推理完成，用时 %.1fs → %s" % (time.time() - t0, out_wav), flush=True)
            return
        last_err = "infer.py 退出码 %s，输出见 %s" % (p.returncode, log_path.name)
        if attempt == 1:
            print("      第 1 次推理异常（%s），自动重试一次…" % last_err, flush=True)
            time.sleep(3)
    raise RuntimeError("DiffSinger 推理失败: %s" % last_err)


def convert_voice(in_wav: Path, role: str, out_wav: Path):
    r"""本地换声：经 换声引擎\svc_worker.py（8106，独立进程）调 so-vits 推理。

    独立进程的原因：so-vits 的 onnxruntime(CUDA) 在服务主进程里加载角色会原生崩溃；
    独立后与命令行直跑环境一致。角色模型按需加载缓存复用，worker 空闲 15 分钟自退。
    """
    worker_port = 8106
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def alive():
        try:
            with opener.open("http://127.0.0.1:%d/health" % worker_port, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    if not alive():
        print("[3/3] 启动本地换声引擎（首次加载角色模型 20~100s）…", flush=True)
        log = open(OUT_DIR / "换声引擎日志.log", "ab")
        subprocess.Popen(
            [str(RUNTIME_PY), "-u", str(ENGINE / "svc_worker.py"), "-p", str(worker_port)],
            cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True)
        for _ in range(40):
            if alive():
                break
            time.sleep(2)
        else:
            raise RuntimeError("换声引擎进程未能就绪（详见 输出\换声引擎日志.log）")
    print("[3/3] 本地换声（角色 %s）…" % role, flush=True)
    import tempfile
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="svc_") as td:
        src = Path(td) / "干声.wav"
        dst = Path(td) / "换声.wav"
        src.write_bytes(in_wav.read_bytes())
        body = json.dumps({"in": str(src), "out": str(dst), "role": role}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:%d/convert" % worker_port,
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        opener2 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener2.open(req, timeout=1200) as r:
            resp = json.loads(r.read().decode("utf-8"))
        if not dst.is_file():
            raise RuntimeError("换声没有产出：%s" % resp)
        out_wav.write_bytes(dst.read_bytes())
    print("      换声完成，用时 %.1fs → %s" % (time.time() - t0, out_wav), flush=True)


def main():
    ap = argparse.ArgumentParser(description="旋律+歌词 → DiffSinger 唱出来（可再换二次元音色）")
    ap.add_argument("song", help="song.json（获取旋律 工作台导出）")
    ap.add_argument("lyrics", nargs="?", help="DeepSeek 填词 JSON；缺省用 song 里的原歌词字")
    ap.add_argument("-o", "--out", default="", help="输出 wav 路径（默认 输出\\<歌名>_唱歌.wav）")
    ap.add_argument("--role", default="", help=r"换声引擎\models\ 里的角色名，填了就再换一次二次元音色")
    ap.add_argument("--key", type=int, default=0, help="整体升降调（半音，正升负降）")
    ap.add_argument("--gender", type=float, default=None, help="-1~1 音色男女调整（0 不动）")
    ap.add_argument("--seed", type=int, default=-1, help="扩散采样随机种子")
    a = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    song_path = Path(a.song)
    song = json.loads(song_path.read_text(encoding="utf-8-sig"))
    title = song.get("title") or song_path.stem

    ds_path = OUT_DIR / ("%s.ds" % title)
    build_ds_file(song_path, a.lyrics or None, ds_path)

    final_wav = Path(a.out) if a.out else OUT_DIR / ("%s_唱歌.wav" % title)
    dry_wav = OUT_DIR / ("%s_干声.wav" % title)
    run_diffsinger(ds_path, dry_wav, key=a.key, gender=a.gender, seed=a.seed)

    if a.role:
        convert_voice(dry_wav, a.role, final_wav)
    else:
        final_wav.write_bytes(dry_wav.read_bytes())
    print("[完成] %s" % final_wav, flush=True)


if __name__ == "__main__":
    main()
