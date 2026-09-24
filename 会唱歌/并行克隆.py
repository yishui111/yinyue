# -*- coding: utf-8 -*-
r"""并行硬链接克隆 runtime（加速 克隆运行环境.py 的单线程版本，跳过已存在文件可断点续跑）

用法：python 并行克隆.py [来源目录] [目标目录]
默认：..\1-rvc\runtime\py312 -> .\runtime\py312
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "1-rvc" / "runtime" / "py312"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "runtime" / "py312"


def list_files(root: Path):
    out = []
    for cur, dirs, files in os.walk(root):
        for f in files:
            out.append(Path(cur) / f)
    return out


def link_one(s: Path, dst_root: Path):
    d = dst_root / s.relative_to(SRC)
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
        try:
            shutil.copy2(s, d)
            return "copy"
        except FileExistsError:
            return "skip"


def main():
    files = list_files(SRC)
    print("源文件数:", len(files), flush=True)
    n = {"link": 0, "skip": 0, "copy": 0}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=48) as ex:
        for i, r in enumerate(ex.map(lambda s: link_one(s, DST), files)):
            n[r] += 1
            if (i + 1) % 5000 == 0:
                print("  %d/%d  %s" % (i + 1, len(files), n), flush=True)
    print("[完成] %s 用时 %.0fs" % (n, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
