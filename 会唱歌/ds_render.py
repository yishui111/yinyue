# -*- coding: utf-8 -*-
r"""常驻 DiffSinger 渲染器。

之前每次合成都要新起 infer.py 子进程，重复付「import torch（40s~3min）+
读 800MB checkpoint」的开销，这是合成慢的主因。本模块在进程内把模型
常驻（懒加载：第一次合成时加载，之后复用），后续合成只花推理本身的时间。

失败自动回退：sing.run_diffsinger 在本模块抛异常时退回老的子进程方式。
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT / "diffsinger"
EXP_NAME = "0211_opencpop_ds1000_keyshift"

_infer = None
_load_secs = 0.0


def _bootstrap():
    """加载模型（进程内只做一次）。需要 chdir 到 diffsinger 仓库跑。"""
    global _infer, _load_secs
    if _infer is not None:
        return _infer
    t0 = time.time()
    old_cwd = os.getcwd()
    old_argv = sys.argv
    # infer.py 的启动方式就是改 sys.argv 后 set_hparams()，这里照搬
    sys.argv = [str(REPO / "scripts" / "infer.py"), "--exp_name", EXP_NAME, "--infer"]
    try:
        os.chdir(REPO)
        from utils.hparams import set_hparams
        set_hparams()
        from inference.ds_acoustic import DiffSingerAcousticInfer
        _infer = DiffSingerAcousticInfer(load_vocoder=True)
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    _load_secs = time.time() - t0
    print("[常驻渲染器] 模型加载完成，用时 %.1fs（之后复用）" % _load_secs, flush=True)
    return _infer


def render(ds_params: list, out_wav: Path, key: int = 0, gender=None, seed: int = -1):
    """ds_params：ds_builder 生成的分段列表 → 渲染写 out_wav（等价 infer.py acoustic）。"""
    infer_ins = _bootstrap()
    params = ds_params
    if key:
        from utils.infer_utils import trans_key
        params = trans_key(params, key)
    if gender is not None:
        for param in params:
            param["gender"] = gender
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    old_cwd = os.getcwd()
    try:
        os.chdir(REPO)
        t0 = time.time()
        infer_ins.run_inference(params, out_dir=out_wav.parent, title=out_wav.stem,
                                num_runs=1, seed=seed if seed >= 0 else -1)
    finally:
        os.chdir(old_cwd)
    if not out_wav.is_file():
        raise RuntimeError("常驻渲染器没有产出 %s" % out_wav)
    print("[常驻渲染器] 合成用时 %.1fs" % (time.time() - t0), flush=True)


def loaded():
    return _infer is not None
