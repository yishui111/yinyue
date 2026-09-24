# -*- coding: utf-8 -*-
r"""
把「旋律 + 歌词」真正唱出来：
  song.json + 填词 JSON → ds_builder 生成 .ds → DiffSinger 本地推理出干声
  → （可选 --role）调 3-so-vits-svc(6843) 换成二次元角色音色 → 输出 wav

用法：
  runtime\py312\python.exe sing.py song.json [填词.json] [-o 输出.wav]
       [--role furina] [--key 0] [--gender 0] [--seed -1]

模型：checkpoints\0211_opencpop_ds1000_keyshift（openvpi 官方发布，中文，
      Opencpop+DS-1000 训练，仅限非商业用途）+ nsf_hifigan 声码器。
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
EXP_NAME = "0211_opencpop_ds1000_keyshift"
OUT_DIR = ROOT / "输出"
SVC_URL = "http://127.0.0.1:6843"

# 绕开系统代理（同 0-web 的历史坑：127.0.0.1 被送代理会 502）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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
    out_dir = out_wav.parent
    title = out_wav.stem
    cmd = [str(RUNTIME_PY), "scripts/infer.py", "acoustic", str(ds_path),
           "--exp", EXP_NAME, "--out", str(out_dir), "--title", title,
           "--key", str(key)]
    if gender is not None:
        cmd += ["--gender", str(gender)]
    if seed >= 0:
        cmd += ["--seed", str(seed)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    print("[2/3] DiffSinger 推理中（首次加载模型要几十秒）…", flush=True)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=str(DIFFSINGER), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=1800)
    if p.returncode != 0 or not out_wav.is_file():
        tail = ((p.stderr or "") + (p.stdout or ""))[-1500:]
        raise RuntimeError("DiffSinger 推理失败:\n%s" % tail)
    print("      推理完成，用时 %.1fs → %s" % (time.time() - t0, out_wav), flush=True)


def convert_voice(in_wav: Path, role: str, out_wav: Path):
    """调 3-so-vits-svc(6843) 把干声换成角色音色（接口同 0-web 总控页）"""
    boundary = "----sing" + str(int(time.time() * 1000))
    fdata = in_wav.read_bytes()
    parts = [
        ("--" + boundary).encode(), b'Content-Disposition: form-data; name="model"', b"", role.encode(),
        ("--" + boundary).encode(), b'Content-Disposition: form-data; name="transpose"', b"", b"0",
        ("--" + boundary).encode(), b'Content-Disposition: form-data; name="auto_f0"', b"", b"1",
        ("--" + boundary).encode(), b'Content-Disposition: form-data; name="cluster_ratio"', b"", b"0",
        ("--" + boundary).encode(),
        ('Content-Disposition: form-data; name="audio"; filename="vocal.wav"').encode(),
        b"Content-Type: application/octet-stream", b"", fdata,
        ("--" + boundary + "--").encode(),
    ]
    body = b"\r\n".join(parts) + b"\r\n"
    req = urllib.request.Request(
        SVC_URL + "/svc/change_voice", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    print("[3/3] 6843 换声（角色 %s）…" % role, flush=True)
    with OPENER.open(req, timeout=1800) as r:
        data = r.read()
    if data[:4] != b"RIFF":
        raise RuntimeError("换声失败，6843 返回的不是 wav: %s" % data[:200])
    out_wav.write_bytes(data)
    print("      换声完成 → %s" % out_wav, flush=True)


def main():
    ap = argparse.ArgumentParser(description="旋律+歌词 → DiffSinger 唱出来（可再换二次元音色）")
    ap.add_argument("song", help="song.json（获取旋律 工作台导出）")
    ap.add_argument("lyrics", nargs="?", help="DeepSeek 填词 JSON；缺省用 song 里的原歌词字")
    ap.add_argument("-o", "--out", default="", help="输出 wav 路径（默认 输出\\<歌名>_唱歌.wav）")
    ap.add_argument("--role", default="", help="6843 里的角色名，填了就再换一次二次元音色")
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
