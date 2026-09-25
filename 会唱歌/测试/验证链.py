# -*- coding: utf-8 -*-
"""验证链：sing 合成 → 启动自检 → 完整套件（供脱离会话的独立进程运行）"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / "runtime" / "py312" / "python.exe")
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def run(label, args):
    print("\n===== %s =====" % label, flush=True)
    t0 = time.time()
    p = subprocess.run([PY] + args, cwd=str(ROOT), env=ENV)
    print("%s exit=%d 用时 %.0fs" % (label, p.returncode, time.time() - t0), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run("1) sing.py 合成验证",
        ["-u", "sing.py", "testdata/小星星.json", "testdata/填词示例.json", "-o", "输出/复现测试.wav"])
    run("2) 启动自检", ["测试/启动自检.py"])
    run("3) 完整测试套件", ["-u", "测试/运行全部测试.py"])
    print("\n===== 验证链结束 =====", flush=True)
