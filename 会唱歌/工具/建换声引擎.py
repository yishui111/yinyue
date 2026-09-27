# -*- coding: utf-8 -*-
r"""把换声引擎收进会唱歌文件夹（自包含，不再依赖 3-so-vits-svc 的 6843 服务）：

    换声引擎\
    ├── so-vits-svc\   so-vits-svc 4.1 推理代码子集 + pretrain\（vec768l12/vec256/rmvpe）
    └── models\        二次元角色音色（json + pth + kmeans/feature_index）

全部用硬链接从 ..\3-so-vits-svc 收集（同一块盘不额外占磁盘；拷走会唱歌时会实体化成真实文件）。
已收集过的文件跳过，可反复运行。

用法：python 建换声引擎.py [来源目录]   默认 ..\3-so-vits-svc
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 会唱歌
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "3-so-vits-svc"
ENGINE = ROOT / "换声引擎"
CODE_DST = ENGINE / "so-vits-svc"
MODELS_DST = ENGINE / "models"

# 推理代码子集：infer_tool 及其全部内部依赖（上游零改动）
CODE_ITEMS = ["inference", "models.py", "modules", "vdecoder", "vencoder",
              "cluster", "diffusion", "utils.py"]
# 预训练件（nsf_hifigan 增强默认关闭，不需要）
PRETRAIN_ITEMS = ["vec-768-layer-12.onnx", "vec-256-layer-9.onnx", "rmvpe.pt"]


def link_tree(src_root: Path, dst_root: Path, names) -> tuple:
    todo = []
    for name in names:
        s = src_root / name
        if not s.exists():
            print("[警告] 来源缺少 %s（跳过）" % name)
            continue
        if s.is_dir():
            for cur, dirs, files in os.walk(s):
                rel = Path(cur).relative_to(src_root)
                (dst_root / rel).mkdir(parents=True, exist_ok=True)
                for f in files:
                    todo.append((Path(cur) / f, dst_root / rel / f))
        else:
            todo.append((s, dst_root / name))
    n_link = n_skip = 0
    for s, d in todo:
        if d.exists():
            n_skip += 1
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(s, d)
            n_link += 1
        except FileExistsError:
            n_skip += 1
        except OSError:
            import shutil
            shutil.copy2(s, d)
            n_link += 1
    return n_link, n_skip


def job(kind, src_root, dst_root, names):
    n, skip = link_tree(src_root, dst_root, names)
    print("[%s] 链接 %d 个（已存在 %d）" % (kind, n, skip), flush=True)


def main():
    if not (SRC / "svc_service.py").is_file():
        print("[失败] 来源目录不像 3-so-vits-svc：%s" % SRC)
        sys.exit(1)
    ENGINE.mkdir(exist_ok=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=16) as ex:
        f1 = ex.submit(job, "代码", SRC, CODE_DST, CODE_ITEMS)
        f2 = ex.submit(job, "预训练", SRC / "pretrain", CODE_DST / "pretrain", PRETRAIN_ITEMS)
        model_names = [p.name for p in (SRC / "models").iterdir()]
        f3 = ex.submit(job, "角色模型(%d个)" % len(model_names),
                       SRC / "models", MODELS_DST, model_names)
        f1.result(); f2.result(); f3.result()
    n_roles = len(list(MODELS_DST.glob("*.json")))
    print("[完成] 换声引擎就绪：%d 个角色，耗时 %.0fs" % (n_roles, time.time() - t0))


if __name__ == "__main__":
    main()
