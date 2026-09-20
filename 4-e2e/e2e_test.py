# -*- coding: utf-8 -*-
"""
端到端测试：音乐视频 → 二次元音色换声视频（保旋律、只换音色）

流程：
  1. ffmpeg 从视频提取音轨（44.1kHz 单声道 wav）
  2. pymss bs_roformer 人声分离 → 人声干声 + 伴奏
  3. 人声干声 POST 给 so-vits-svc 服务(6843) → 二次元音色人声
  4. ffmpeg 把「二次元人声 + 伴奏」混音
  5. ffmpeg 混流回视频（视频流原样拷贝）→ 输出 mp4

前置：3-so-vits-svc 的换声服务必须已经在跑（去那个目录双击 启动.bat）

用法：双击本目录的 运行测试.bat
     或命令行：runtime\\py312\\python.exe e2e_test.py [输入mp4] [角色名]
输出：输出\\输出_<角色名>.mp4，中间产物在 输出\\中间产物\\
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

ROOT = Path(__file__).resolve().parent
TESTDATA = ROOT / "testdata"
# 本机可能配了系统代理（HTTP_PROXY），不绕开的话 127.0.0.1 也会被送去代理，直接 502
HTTP = requests.Session()
HTTP.trust_env = False
WORK = ROOT / "输出" / "中间产物"
OUT_DIR = ROOT / "输出"
PYMSS_MODEL_DIR = ROOT / "models" / "pymss"
SVC_URL = "http://127.0.0.1:6843"
VOCAL_MODEL_NAME = "bs_roformer_voc_hyperacev2"


def find_ffmpeg():
    """优先用项目自带的 runtime\\ffmpeg，没有就用系统 PATH 里的"""
    local = ROOT / "runtime" / "ffmpeg" / "ffmpeg.exe"
    if local.is_file():
        return str(local)
    which = shutil.which("ffmpeg")
    if which:
        return which
    print("[失败] 没找到 ffmpeg。把 ffmpeg.exe 放到 runtime\\ffmpeg\\ 下，或装进系统 PATH。")
    sys.exit(1)


FFMPEG = find_ffmpeg()


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def cuda_ok():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def pick_input():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    for p in sorted(TESTDATA.glob("*.mp4")):
        return p
    print("[失败] testdata\\ 下没有输入视频")
    sys.exit(1)


def main():
    src = pick_input()
    role = sys.argv[2] if len(sys.argv) > 2 else "furina"
    WORK.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 前置检查：换声服务必须在跑
    try:
        r = HTTP.get(SVC_URL + "/health", timeout=10)
        up = r.status_code == 200 and r.json().get("status") == "ok"
        names = sorted(HTTP.get(SVC_URL + "/models", timeout=10).json()) if up else []
    except Exception:
        up, names = False, []
    if not up:
        print("[失败] 换声服务没开：%s" % SVC_URL)
        print("       请到 ..\\3-so-vits-svc 目录双击 启动.bat，等服务就绪后再跑本测试。")
        print("       （若确认已启动，检查是不是系统代理把 127.0.0.1 也代理了）")
        sys.exit(1)
    if not names:
        print("[失败] 换声服务里没有可用角色模型")
        sys.exit(1)
    if role not in names:
        print("[提示] 角色 %s 不在 %s 里，改用 %s" % (role, names, names[0]))
        role = names[0]

    t_all = time.time()
    print("输入: %s" % src)
    print("角色: %s" % role)

    # 1) 提取音轨
    full_mix = WORK / "01_full_mix.wav"
    run([FFMPEG, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "44100", full_mix],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    audio, sr = sf.read(full_mix, dtype="float32")
    print("[1/5] 音轨: %.2fs @ %dHz" % (len(audio) / sr, sr), flush=True)

    # 2) 人声分离
    print("[2/5] 人声分离(bs_roformer)，首次要加载模型，请稍候...", flush=True)
    from pymss import MSSeparator
    sep = MSSeparator.from_model_name(
        VOCAL_MODEL_NAME, model_dir=str(PYMSS_MODEL_DIR), download=False,
        source="hf-mirror", device="cuda" if cuda_ok() else "cpu",
        output_format="wav", inference_params={"normalize": True},
    )
    t0 = time.time()
    stems = sep.separate(audio, pbar=False, stems=["vocals"])
    vocals = np.asarray(stems["vocals"], dtype="float32")
    if vocals.ndim > 1:
        vocals = vocals.mean(axis=1)
    if len(vocals) < len(audio):
        vocals = np.pad(vocals, (0, len(audio) - len(vocals)))
    inst = audio - vocals
    sf.write(WORK / "02_vocals.wav", vocals, sr)
    sf.write(WORK / "03_instrumental.wav", inst, sr)
    print("      分离完成 %.1fs" % (time.time() - t0), flush=True)
    del sep
    if cuda_ok():
        import torch
        torch.cuda.empty_cache()

    # 3) so-vits 换声
    print("[3/5] so-vits 换声 -> %s ..." % role, flush=True)
    t0 = time.time()
    with open(WORK / "02_vocals.wav", "rb") as f:
        r = HTTP.post(
            SVC_URL + "/svc/change_voice",
            params={"model": role, "transpose": 0, "auto_f0": 1, "cluster_ratio": 0},
            files={"audio": ("vocals.wav", f, "audio/wav")},
            timeout=1800,
        )
    if r.status_code != 200:
        print("[失败] 换声失败: %d %s" % (r.status_code, r.text[:500]))
        sys.exit(1)
    converted = WORK / ("04_vocal_%s.wav" % role)
    converted.write_bytes(r.content)
    print("      换声完成 %.1fs" % (time.time() - t0), flush=True)

    # 4) 混音：二次元人声 + 伴奏
    print("[4/5] 混音...", flush=True)
    mixed = WORK / "05_mixed.wav"
    run([FFMPEG, "-y", "-i", converted, "-i", WORK / "03_instrumental.wav",
         "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[m]",
         "-map", "[m]", "-ar", "44100", mixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 5) 封装回视频（视频流直接拷贝）
    print("[5/5] 封装回视频...", flush=True)
    out = OUT_DIR / ("输出_%s.mp4" % role)
    run([FFMPEG, "-y", "-i", src, "-i", mixed,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", out],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("\n[完成] %s  总耗时 %.1fs" % (out.relative_to(ROOT), time.time() - t_all), flush=True)


if __name__ == "__main__":
    main()
