# -*- coding: utf-8 -*-
r"""训练流水线：把素材训练成会唱歌可用的二次元音色（so-vits-svc 4.1 格式）。

步骤：素材 → 重采样 44.1k → 文件列表/配置（vec768l12）→ 特征提取(f0) → 训练 → 导出到 换声引擎\models

用法（在 会唱歌\训练\ 目录下）：
  runtime python 训练流水线.py 全流程 <角色名> <素材目录> [--f0 rmvpe] [--train-timeout 秒] [--no-train] [--restart]
  runtime python 训练流水线.py 导出 <角色名>          # 训练完成后（手动停也行）导出到换声引擎
  runtime python 训练流水线.py 继续 <角色名>          # 从上次的 checkpoint 接着训

说明：
- 素材目录：放着该角色的干净人声（wav/mp3/flac），3~10 分钟以上效果更好；
  若给的是散文件目录，会先把音频硬链接进 素材\<角色名>\ 再训练。
- 底模：底模\G_0.pth / D_0.pth（官方 vec768l12 预训练底模）会在首次训练时复制为
  so-vits-svc\logs\44k\G_0.pth / D_0.pth，之后中断重跑自动断点续训。
- 训练是长任务（小时级）；--train-timeout 用于冒烟测试（到时停止并视为通过）。
- 训练完成后（或随时）用「导出」把最新 G 权重 + 配置放进 换声引擎\models\，页面立即可选。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TRAIN_ROOT = Path(__file__).resolve().parent
REPO = TRAIN_ROOT / "so-vits-svc"
RUNTIME_PY = TRAIN_ROOT.parent / "runtime" / "py312" / "python.exe"
ENGINE_MODELS = TRAIN_ROOT.parent / "换声引擎" / "models"
BASE_DIR = TRAIN_ROOT / "底模"
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

sys.stdout.reconfigure(encoding="utf-8")


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def run(cmd, timeout=None):
    log("$ " + " ".join(str(c) for c in cmd))
    p = subprocess.run([str(RUNTIME_PY)] + [str(c) for c in cmd], cwd=str(REPO),
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                       timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("步骤失败（退出码 %d）：%s" % (p.returncode, cmd))
    return p


def collect_material(role: str, material_dir: Path) -> Path:
    r"""把散落的音频归位到 素材\<角色名>\（同盘硬链接，不占空间）"""
    role_dir = TRAIN_ROOT / "素材" / role
    audio = [p for p in material_dir.rglob("*")
             if p.is_file() and p.suffix.lower() in AUDIO_EXT]
    if not audio:
        raise RuntimeError("素材目录里没有音频文件（支持 wav/mp3/flac/ogg/m4a）：%s" % material_dir)
    role_dir.mkdir(parents=True, exist_ok=True)
    for p in audio:
        d = role_dir / p.name
        if d.exists():
            continue
        try:
            os.link(p, d)
        except OSError:
            shutil.copy2(p, d)
    log("素材就位：%d 个文件 → %s" % (len(audio), role_dir))
    return role_dir


def latest_ckpt(model_dir: Path, prefix="G_"):
    cks = sorted(model_dir.glob(prefix + "*.pth"), key=lambda p: p.stat().st_mtime)
    return cks[-1] if cks else None


def main():
    ap = argparse.ArgumentParser(description="训练流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)
    full = sub.add_parser("全流程", help="素材 → 重采样 → 配置 → 特征 → 训练")
    full.add_argument("角色名")
    full.add_argument("素材目录")
    full.add_argument("--f0", default="rmvpe", help="f0 提取器：rmvpe(默认)/pm/crepe...")
    full.add_argument("--train-timeout", type=int, default=None,
                      help="训练到该秒数后停止（冒烟测试用）；缺省训到完成（小时级）")
    full.add_argument("--no-train", action="store_true", help="只做训练前的准备步骤")
    full.add_argument("--restart", action="store_true", help="清空该角色已有 checkpoint 从头训")
    exp = sub.add_parser("导出", help="把最新 G 权重+配置导出到 换声引擎\\models\\")
    exp.add_argument("角色名")
    args = ap.parse_args()

    if args.cmd == "导出":
        export(args.角色名)
        return

    role = args.角色名.strip()
    if not role or any(c in role for c in '\\/:*?"<>| '):
        raise RuntimeError("角色名不能为空，且不能含空格或 \\/:*?\"<>| 字符")
    material = Path(args.素材目录)
    # 相对路径依次尝试：当前目录 / 训练目录 / 会唱歌根目录
    for base in (Path.cwd(), TRAIN_ROOT, TRAIN_ROOT.parent):
        cand = material if material.is_absolute() else base / material
        if cand.is_dir():
            material = cand.resolve()
            break

    model_dir = REPO / "logs" / "44k"
    t0 = time.time()
    log("=== 角色：%s ===" % role)

    # 1) 素材归位 + 重采样 44.1k
    role_dir = collect_material(role, material)
    run(["resample.py", "--in_dir", role_dir.parent, "--out_dir2", "dataset/44k", "--sr2", 44100])
    out_data = REPO / "dataset" / "44k" / role
    n = len(list(out_data.glob("*"))) if out_data.is_dir() else 0
    if n == 0:
        raise RuntimeError("重采样后没有产出数据，请检查素材是否为可解码的音频")
    log("重采样完成：%d 个训练文件" % n)

    # 2) 文件列表 + 训练配置（vec768l12 编码器，与本换声引擎一致）
    for d in ("filelists", "configs"):
        (REPO / d).mkdir(exist_ok=True)
    run(["preprocess_flist_config.py", "--train_list", "filelists/train.txt",
         "--val_list", "filelists/val.txt", "--source_dir", "dataset/44k",
         "--speech_encoder", "vec768l12-onnx"])

    # 3) 底模就位（首次从底模微调；--restart 清掉旧 checkpoint）
    if args.restart:
        for f in model_dir.glob("G_*.pth"):
            f.unlink()
        for f in model_dir.glob("D_*.pth"):
            f.unlink()
    model_dir.mkdir(parents=True, exist_ok=True)
    marker = model_dir / "上次训练角色.txt"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() != role and not args.restart:
        raise RuntimeError("logs$k 里是「%s」的 checkpoint；换角色请加 --restart（会清掉旧进度）"
                           % marker.read_text(encoding="utf-8").strip())
    existing = latest_ckpt(model_dir, "G_")
    base_g, base_d = BASE_DIR / "G_0.pth", BASE_DIR / "D_0.pth"
    if existing is None:
        if not base_g.is_file() or not base_d.is_file():
            raise RuntimeError("缺官方底模：%s / %s（下载方式见 训练\\说明.md）" % (base_g, base_d))
        shutil.copy2(base_g, model_dir / "G_0.pth")
        shutil.copy2(base_d, model_dir / "D_0.pth")
        log("底模已就位（从官方 vec768l12 底模微调）")
    else:
        log("发现已有 checkpoint %s，断点续训" % existing.name)

    # 4) 特征提取（content + f0）。worker 里 CUDA 初始化吃提交内存，机器紧张时自动转 CPU 单进程
    try:
        run(["preprocess_hubert_f0.py", "--f0_predictor", args.f0, "--num_processes", 2])
    except (RuntimeError, subprocess.TimeoutExpired):
        log("GPU 多进程提取失败，转 CPU 单进程重试……")
        run(["preprocess_hubert_f0.py", "--f0_predictor", args.f0,
             "--num_processes", 1, "-d", "cpu"])

    # 5) 训练（长任务）
    if not args.no_train:
        train_cmd = ["train.py", "-c", "configs/config.json", "-m", "44k"]
        if args.train_timeout:
            log("冒烟模式：训练 %d 秒后停止（不等待训练完成）" % args.train_timeout)
            try:
                run(train_cmd, timeout=args.train_timeout)
            except subprocess.TimeoutExpired:
                log("到时停止（训练进程已结束，冒烟通过）")
        else:
            log("开始训练（小时级）。中断后重跑「继续」可断点续训；随时可「导出」当前进度")
            run(train_cmd)

    marker.write_text(role, encoding="utf-8")

    # 6) 导出
    export(role)
    log("=== 全流程结束，总用时 %.0f 秒 ===" % (time.time() - t0))


def export(role: str):
    model_dir = REPO / "logs" / "44k"
    g = latest_ckpt(model_dir, "G_")
    cfg = REPO / "configs" / "config.json"
    if g is None or not cfg.is_file():
        raise RuntimeError("还没有可导出的模型：先跑训练（logs\\44k 下没有 G 权重）")
    ENGINE_MODELS.mkdir(parents=True, exist_ok=True)
    dst_json = ENGINE_MODELS / ("%s.json" % role)
    dst_pth = ENGINE_MODELS / ("%s_G.pth" % role)
    shutil.copy2(cfg, dst_json)
    shutil.copy2(g, dst_pth)
    log("已导出到换声引擎：%s + %s（%.0f MB）——页面角色下拉框立即可选"
        % (dst_json.name, dst_pth.name, dst_pth.stat().st_size / 1e6))


if __name__ == "__main__":
    main()
