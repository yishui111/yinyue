# -*- coding: utf-8 -*-
r"""
so-vits-svc 唱歌换声服务（在官方 4.1-Stable 之上封装，上游源码零改动）

功能：
- GET  /                  前端控制台页面（web/index.html，与下面三个接口一一对应）
- 自动扫描 models/ 目录里的角色模型（json + pth + kmeans/feature_index）
- POST /svc/change_voice  上传干声 wav，返回换成角色音色后的 wav（保留旋律，只换音色）
- GET  /models            已加载可用角色列表
- GET  /health            健康检查

启动：双击本目录的 启动.bat（等价于 runtime\py312\python.exe svc_service.py -p 6843）
测试：双击本目录的 运行测试.bat
     curl -X POST -F "audio=@test.wav" "http://127.0.0.1:6843/svc/change_voice?model=furina&transpose=0&auto_f0=1" -o out.wav
"""
import argparse
import io
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import torch

# onnxruntime-gpu(CUDA11) 需要 cuDNN8/cuBLAS11 DLL：nvidia-* pip 包 + torch/lib 都挂进搜索路径
_exe = Path(sys.executable)
_site = _exe.parent / "Lib" / "site-packages"          # 便携布局 runtime/py312/python.exe
if not _site.is_dir():
    _site = _exe.parent.parent / "Lib" / "site-packages"  # 传统布局 venv/Scripts/python.exe
_dll_dirs = [_site / "torch" / "lib"] + sorted((_site / "nvidia").glob("*" + os.sep + "bin"))
for _d in _dll_dirs:
    if _d.is_dir():
        os.add_dll_directory(str(_d))
        os.environ["PATH"] = str(_d) + os.pathsep + os.environ.get("PATH", "")

import soundfile
import torchaudio
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

from inference.infer_tool import Svc

logging.getLogger('numba').setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "models"
WEB_DIR = PROJECT_ROOT / "web"

app = Flask(__name__)
CORS(app)

_loaded = {}  # name -> (Svc, json_path, pth_path)


@app.route("/")
def index():
    """前端控制台页面：三个功能区分别对应 /health、/models、/svc/change_voice"""
    return send_file(WEB_DIR / "index.html")


def scan_models():
    """扫描 models/ 目录，按文件名前缀配对 (角色.json, 角色*.pth, 角色_kmeans.pt / 角色_feature_and_index.pkl)"""
    found = {}
    for cfg in sorted(MODELS_DIR.glob("*.json")):
        stem = cfg.stem
        pth = None
        for cand in MODELS_DIR.glob(stem + "*.pth"):
            if cand.name.endswith("_G.pth") or cand.stem.startswith(stem):
                pth = cand
                break
        if pth is None:
            continue
        kmeans = MODELS_DIR / f"{stem}_kmeans.pt"
        feat = MODELS_DIR / f"{stem}_feature_and_index.pkl"
        found[stem] = {"config": cfg, "pth": pth,
                       "cluster": kmeans if kmeans.is_file() else None,
                       "feature": feat if feat.is_file() else None}
    return found


def load_model(name):
    if name in _loaded:
        return _loaded[name]
    all_models = scan_models()
    if name not in all_models:
        raise FileNotFoundError(f"model not found: {name}; available: {list(all_models)}")
    info = all_models[name]
    use_feature_retrieval = info["feature"] is not None
    cluster_path = str(info["feature"]) if use_feature_retrieval else str(info["cluster"] or "")
    model = Svc(str(info["pth"]), str(info["config"]),
                cluster_model_path=cluster_path or None,
                feature_retrieval=use_feature_retrieval,
                device="cuda" if torch.cuda.is_available() else "cpu")
    # 同显存策略：一次只留一个角色模型
    _loaded.clear()
    _loaded[name] = (model, info)
    return _loaded[name]


@app.route("/health")
def health():
    return jsonify({"status": "ok", "cuda": torch.cuda.is_available(),
                    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""})


@app.route("/models")
def models():
    result = {}
    for stem, info in scan_models().items():
        try:
            cfg = json.loads(info["config"].read_text(encoding="utf-8"))
            spk = list(cfg.get("spk", {}).keys())
        except Exception:
            spk = []
        result[stem] = {"speakers": spk,
                        "feature_retrieval": info["feature"] is not None,
                        "loaded": stem in _loaded}
    return jsonify(result)


@app.route("/svc/change_voice", methods=["POST"])
def change_voice():
    """
    form-data:
      audio        必填，干声 wav
      model        角色名（models/ 下的 json 前缀，如 furina / nahida41）
      transpose    变调半音数，整数，默认 0
      auto_f0      1=自动预测音高（唱歌默认推荐），0=跟随原曲音高
      cluster_ratio 聚类/特征检索比例 0~1，默认 0（1=最像角色本人）
      f0_predictor  rmvpe / crepe / pm，默认 rmvpe
    """
    f = request.values  # 同时兼容 URL query 和 form-data 传参
    file = request.files.get("audio")
    if file is None:
        return jsonify({"error": "missing audio file field 'audio'"}), 400
    name = f.get("model", "")
    transpose = int(float(f.get("transpose", 0)))
    auto_f0 = f.get("auto_f0", "1") not in ("0", "false", "False")
    cluster_ratio = float(f.get("cluster_ratio", 0))
    f0_predictor = f.get("f0_predictor", "rmvpe")

    try:
        model, info = load_model(name)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404

    spk_names = list(model.spk2id.keys())
    speaker = f.get("speaker", spk_names[0])
    if speaker not in model.spk2id and not str(speaker).isdigit():
        return jsonify({"error": f"speaker '{speaker}' not in {spk_names}"}), 400

    input_bytes = io.BytesIO(file.read())
    audio, _audio_len, _n_frames = model.infer(speaker, transpose, input_bytes,
                            cluster_infer_ratio=cluster_ratio,
                            auto_predict_f0=auto_f0,
                            noice_scale=0.4,
                            f0_predictor=f0_predictor)
    out = io.BytesIO()
    if hasattr(audio, "cpu"):
        audio = audio.cpu().numpy()
    soundfile.write(out, audio, model.target_sample, format="wav")
    out.seek(0)
    return send_file(out, download_name=f"{name}_converted.wav", as_attachment=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=6843)
    parser.add_argument("-a", "--host", type=str, default="127.0.0.1")
    args = parser.parse_args()
    print(f"so-vits-svc service on http://{args.host}:{args.port}  models dir: {MODELS_DIR}", flush=True)
    app.run(port=args.port, host=args.host, debug=False, threaded=False)
