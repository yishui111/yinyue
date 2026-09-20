# -*- coding: utf-8 -*-
r"""
把 1-rvc（或 4-e2e）的 runtime\py312 用硬链接克隆一份到本项目。

总控页服务只用 Python 标准库，克隆完整环境只是为了和其他项目保持同一形态：
整个文件夹拷到新电脑、双击 启动.bat 就能跑，不用装任何东西。
硬链接不额外占磁盘；拷到别的盘/别的机器时会实体化成真实文件。

用法：python 克隆运行环境.py [来源目录]
默认来源：..\1-rvc\runtime\py312（没有就用 ..\4-e2e\runtime\py312）
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def clone_dir(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    n_files = n_skip = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            s, d = Path(root) / name, dst / rel / name
            if d.exists():
                n_skip += 1
                continue
            try:
                os.link(s, d)
                n_files += 1
            except OSError:
                # 跨盘等硬链接不可用的场景退回复制
                import shutil
                shutil.copy2(s, d)
                n_files += 1
    return n_files, n_skip


def main():
    src_root = ROOT.parent
    candidates = [Path(sys.argv[1])] if len(sys.argv) > 1 else \
        [src_root / "1-rvc" / "runtime" / "py312", src_root / "4-e2e" / "runtime" / "py312"]
    src = next((c for c in candidates if (c / "python.exe").is_file()), None)
    if not src:
        print(r"[失败] 没找到可克隆的 runtime\py312（试过：%s）"
              % "、".join(str(c) for c in candidates))
        sys.exit(1)
    dst = ROOT / "runtime" / "py312"
    if (dst / "python.exe").is_file():
        print(r"[提示] 本项目已有 runtime\py312，不用克隆。")
        return
    print("克隆 %s -> %s （硬链接，不占磁盘）" % (src, dst), flush=True)
    t0 = time.time()
    n, skip = clone_dir(src, dst)
    print("[完成] 链接 %d 个文件（已存在跳过 %d），耗时 %.1fs"
          % (n, skip, time.time() - t0), flush=True)
    print("验证：", subprocess_run(dst / "python.exe"))


def subprocess_run(py: Path):
    import subprocess
    p = subprocess.run([str(py), "-c", "import sys;print(sys.prefix)"],
                       capture_output=True, text=True, timeout=60)
    return (p.stdout or p.stderr).strip()


if __name__ == "__main__":
    main()
