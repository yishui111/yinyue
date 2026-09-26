# -*- coding: utf-8 -*-
r"""本地换声封装：把干声 wav 换成 换声引擎\models\ 里的二次元角色音色。

等价于 3-so-vits-svc 的 6843 HTTP 接口，但直接在本进程内调 so-vits-svc 推理代码，
不再依赖外部服务。角色模型扫描 换声引擎\models\（json + pth + kmeans/feature_index），
一次只保留一个已加载角色（换角色时释放显存，与上游服务同策略）。

用法（sing.py / sing_service.py 内部调用）：
    import svc_local
    wav_bytes, sr = svc_local.convert(干声bytes, "furina")
命令行自测：
    runtime\py312\python.exe 换声引擎\svc_local.py 干声.wav 输出.wav furina
"""
import gc
import io
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
REPO = ENGINE / "so-vits-svc"
MODELS_DIR = ENGINE / "models"

logging.getLogger("numba").setLevel(logging.WARNING)

# onnxruntime(CUDA11) 需要 cuDNN8/cuBLAS11 DLL：nvidia-* pip 包 + torch/lib 挂进搜索路径
_exe = Path(sys.executable)
_site = _exe.parent / "Lib" / "site-packages"
if not _site.is_dir():
    _site = _exe.parent.parent / "Lib" / "site-packages"
for _d in [_site / "torch" / "lib"] + sorted((_site / "nvidia").glob("*" + os.sep + "bin")):
    if _d.is_dir():
        os.add_dll_directory(str(_d))
        os.environ["PATH"] = str(_d) + os.pathsep + os.environ.get("PATH", "")

_lock = threading.Lock()
_loaded = None  # (role, model, spk_names)

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # so-vits-svc 推理代码（inference/models/vdecoder/...）


def scan_models():
    """角色名 -> {config, pth, cluster, feature}（json + pth + kmeans/feature_index 配对）"""
    found = {}
    for cfg in sorted(MODELS_DIR.glob("*.json")):
        stem = cfg.stem
        pth = None
        for cand in sorted(MODELS_DIR.glob(stem + "*.pth")):
            if not cand.name.endswith("_G.pth"):
                pth = cand
                break
        if pth is None:
            g_files = sorted(MODELS_DIR.glob(stem + "_G*.pth"),
                             key=lambda p: p.stat().st_size, reverse=True)
            pth = g_files[0] if g_files else None
        if pth is None:
            continue
        kmeans = MODELS_DIR / f"{stem}_kmeans.pt"
        feat = MODELS_DIR / f"{stem}_feature_and_index.pkl"
        found[stem] = {"config": cfg, "pth": pth,
                       "cluster": kmeans if kmeans.is_file() else None,
                       "feature": feat if feat.is_file() else None}
    return found


def roles():
    """可用角色名列表（按名字排序）"""
    return sorted(scan_models().keys())


def _get_model(name):
    """加载角色模型（调用方需已 chdir 到 REPO，pretrain\ 相对路径才解析得到）"""
    global _loaded
    if _loaded is not None and _loaded[0] == name:
        return _loaded[1], _loaded[2]
    all_models = scan_models()
    if name not in all_models:
        raise FileNotFoundError("角色 %s 不在 %s（可用：%s）"
                                % (name, MODELS_DIR, list(all_models)))
    info = all_models[name]
    use_feature = info["feature"] is not None
    cluster_path = str(info["feature"]) if use_feature else str(info["cluster"] or "")
    import torch
    from inference.infer_tool import Svc
    model = Svc(str(info["pth"]), str(info["config"]),
                cluster_model_path=cluster_path or None,
                feature_retrieval=use_feature,
                device="cuda" if torch.cuda.is_available() else "cpu")
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    spk_names = list(model.spk2id.keys())
    _loaded = (name, model, spk_names)
    return model, spk_names


def convert(in_bytes: bytes, role: str, transpose: int = 0, auto_f0: bool = True,
            cluster_ratio: float = 0.0, f0_predictor: str = "rmvpe") -> tuple:
    """干声 wav bytes → (角色音色 wav bytes, 采样率)。线程安全（内部串行）。"""
    with _lock:
        import soundfile
        import torch
        # so-vits 代码在加载与推理时都用相对路径找 pretrain\，整个过程 chdir 到引擎仓库
        old_cwd = os.getcwd()
        tmp = Path(os.path.expandvars(r"%TEMP%")) / ("svc_in_%d.wav" % time.time_ns())
        try:
            tmp.write_bytes(in_bytes)
            os.chdir(REPO)
            model, spk_names = _get_model(role)
            speaker = spk_names[0] if spk_names else role
            # torchaudio 2.7 对 BytesIO 原生分派会崩（上游 runtime 是旧版 torchaudio），
            # 所以传磁盘路径而不是内存流（上游 infer 的 raw_path 两者都兼容）
            audio, _n, _f = model.infer(
                speaker, int(transpose), str(tmp),
                cluster_infer_ratio=float(cluster_ratio),
                auto_predict_f0=bool(auto_f0),
                noice_scale=0.4,
                f0_predictor=f0_predictor)
        finally:
            os.chdir(old_cwd)
            tmp.unlink(missing_ok=True)
        if hasattr(audio, "cpu"):
            audio = audio.cpu().numpy()
        out = io.BytesIO()
        soundfile.write(out, audio, model.target_sample, format="wav")
        return out.getvalue(), model.target_sample


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法：python svc_local.py 干声.wav 输出.wav 角色名 [transpose]")
        print("可用角色：%s" % roles())
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    src, dst, role = sys.argv[1], sys.argv[2], sys.argv[3]
    t0 = time.time()
    data, sr = convert(Path(src).read_bytes(), role,
                       transpose=int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    Path(dst).write_bytes(data)
    print("[完成] %s → %s（%d Hz，%.1fs）" % (src, dst, sr, time.time() - t0))
