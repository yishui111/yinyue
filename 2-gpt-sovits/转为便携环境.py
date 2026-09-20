# -*- coding: utf-8 -*-
"""
把本项目的 Python 环境变成「自带解释器」的免安装形态：runtime\py312

原理：venv 里只有第三方包，解释器本体靠 pyvenv.cfg 指向系统 Python（换台电脑就废）。
      这里把系统 Python 的 python.exe / DLLs / 标准库 / include 并进来，删掉 pyvenv.cfg，
      之后整个 runtime\py312 拷到哪都能直接跑。

用法：在本项目目录下执行  python 转为便携环境.py
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOP_FILES = ["python.exe", "pythonw.exe", "python3.dll", "python312.dll",
             "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"]
TOP_DIRS = ["DLLs", "libs", "tcl"]


def find_base():
    """找到系统里的 Python 3.12 安装目录"""
    import subprocess
    for cmd in (["py", "-3.12", "-c", "import sys;print(sys.executable)"],
                [sys.executable, "-c", "import sys;print(sys._base_executable or sys.executable)"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
        except Exception:
            continue
        for line in out.splitlines()[::-1]:
            p = Path(line.strip().strip('"'))
            if p.is_file() and p.name.lower() == "python.exe":
                return p.parent
    env = os.environ.get("PYTHON312_HOME")
    if env and Path(env).is_dir():
        return Path(env)
    return None


def merge(src, dst, skip=None):
    skip = skip or set()
    dst.mkdir(parents=True, exist_ok=True)
    added = 0
    for e in os.scandir(src):
        if e.name in skip:
            continue
        target = dst / e.name
        try:
            if e.is_dir(follow_symlinks=False):
                added += merge(Path(e.path), target)
            else:
                if target.exists():
                    continue
                shutil.copy2(e.path, target)
                added += 1
        except OSError as ex:
            print("  [跳过] %s (%s)" % (e.path, ex))
    return added


def main():
    # 目标目录：优先 runtime\py312，其次 venv
    target = ROOT / "runtime" / "py312"
    if not target.is_dir():
        venv = ROOT / "venv"
        if venv.is_dir():
            target = venv
        else:
            print("[失败] 既没有 runtime\py312 也没有 venv，请先运行 安装环境.bat")
            return 1

    base = find_base()
    if base is None:
        print("[失败] 找不到系统 Python 3.12，无法取解释器本体")
        return 1
    print("系统 Python: %s" % base)
    print("目标环境:   %s" % target)

    for f in TOP_FILES:
        src, dst = base / f, target / f
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst)
            print("  + %s" % f)
    for d in TOP_DIRS:
        src, dst = base / d, target / d
        if src.is_dir() and not dst.exists():
            shutil.copytree(src, dst)
            print("  + %s/" % d)

    n = merge(base / "include", target / "Include")
    print("  + include -> Include (%d 个文件)" % n)
    n = merge(base / "Lib", target / "Lib", skip={"site-packages"})
    print("  + Lib 标准库 (%d 个文件)" % n)

    cfg = target / "pyvenv.cfg"
    if cfg.exists():
        cfg.unlink()
        print("  - pyvenv.cfg（不再依赖系统 Python 路径）")
    for f in ("python.exe", "pythonw.exe"):
        p = target / "Scripts" / f
        if p.exists():
            p.unlink()
            print("  - Scripts\%s" % f)

    # venv -> runtime\py312
    final = ROOT / "runtime" / "py312"
    if target != final:
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            print("  ! %s 已存在，保留原样" % final.name)
        else:
            target.rename(final)
            print("  > venv -> runtime\py312")

    print("[完成] 现在 runtime\py312 可以整个拷到别的电脑上直接用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
