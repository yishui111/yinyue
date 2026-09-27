# -*- coding: utf-8 -*-
r"""把 so-vits-svc 4.1 的训练代码与依赖收进 会唱歌\训练\so-vits-svc\（硬链接，不占额外空间）。

收集内容：
  - 训练/推理全部 python 代码（resample/preprocess_*/train/data_utils/models/modules/...）
  - configs_template\（生成训练配置的模板）
  - pretrain\：vec768l12/vec256l9 编码器 + rmvpe（来自 ..\换声引擎\so-vits-svc\pretrain）
  - pretrain\nsf_hifigan\：训练时验证用声码器（来自 ..\diffsinger\checkpoints\nsf_hifigan）

来源目录默认 ..\..\3-so-vits-svc（本仓库的训练引擎），可传参覆盖。
已收集过的文件跳过，可反复运行。

用法：python 建训练环境.py [来源目录]
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TRAIN_ROOT = Path(__file__).resolve().parent.parent / "训练"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else TRAIN_ROOT.parent.parent / "3-so-vits-svc"
REPO_DST = TRAIN_ROOT / "so-vits-svc"
SVC_ENGINE_PRETRAIN = TRAIN_ROOT.parent / "换声引擎" / "so-vits-svc" / "pretrain"
DIFFSINGER_NSF = TRAIN_ROOT.parent / "diffsinger" / "checkpoints" / "nsf_hifigan"

TRAIN_CODE = [
    "resample.py", "preprocess_flist_config.py", "preprocess_hubert_f0.py",
    "train.py", "train_index.py", "train_diff.py", "data_utils.py", "utils.py",
    "models.py", "compress_model.py", "spkmix.py",
    "inference", "modules", "vdecoder", "vencoder", "cluster", "diffusion",
    "configs_template",
]
PRETRAIN_ITEMS = ["vec-768-layer-12.onnx", "vec-256-layer-9.onnx", "rmvpe.pt"]
NSF_ITEMS = {"model": "model.ckpt", "config.json": "config.json"}


def link_one(s: Path, d: Path) -> str:
    if d.exists():
        return "skip"
    d.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(s, d)
        return "link"
    except FileExistsError:
        return "skip"
    except OSError:
        import shutil
        shutil.copy2(s, d)
        return "copy"


def main():
    if not (SRC / "train.py").is_file():
        print("[失败] 来源目录不像 so-vits-svc 仓库：%s" % SRC)
        sys.exit(1)
    t0 = time.time()
    stats = {"link": 0, "skip": 0, "copy": 0}

    jobs = [(SRC, REPO_DST, TRAIN_CODE)]

    def run_job(src_root, dst_root, names):
        for name in names:
            s, d = src_root / name, dst_root / name
            if not s.exists():
                print("[警告] 来源缺少 %s（跳过）" % name)
                continue
            if s.is_dir():
                for cur, dirs, files in os.walk(s):
                    rel = Path(cur).relative_to(src_root)
                    for f in files:
                        r = link_one(Path(cur) / f, dst_root / rel / f)
                        stats[r] = stats.get(r, 0) + 1
            else:
                r = link_one(s, dst_root / name)
                stats[r] = stats.get(r, 0) + 1

    with ThreadPoolExecutor(max_workers=8) as ex:
        f1 = ex.submit(run_job, SRC, REPO_DST, TRAIN_CODE)
        f2 = ex.submit(run_job, SVC_ENGINE_PRETRAIN, REPO_DST / "pretrain", PRETRAIN_ITEMS)
        for src_name, dst_name in NSF_ITEMS.items():
            s = DIFFSINGER_NSF / src_name
            if s.is_file():
                r = link_one(s, REPO_DST / "pretrain" / "nsf_hifigan" / dst_name)
                stats[r] = stats.get(r, 0) + 1
        f1.result(); f2.result()

    ok = (REPO_DST / "pretrain" / "rmvpe.pt").is_file() \
        and (REPO_DST / "pretrain" / "vec-768-layer-12.onnx").is_file()
    print("[完成] 链接 %d / 跳过 %d / 复制 %d，耗时 %.0fs；pretrain %s"
          % (stats.get("link", 0), stats.get("skip", 0), stats.get("copy", 0),
             time.time() - t0, "齐全" if ok else "缺失（检查来源）"))


if __name__ == "__main__":
    main()
