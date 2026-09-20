# -*- coding: utf-8 -*-
"""
so-vits-svc 唱歌换声服务 · 自测

做什么：
  1. 检查 6843 端口的服务，没开就自动拉起（会弹出一个新窗口），等它就绪
  2. GET  /models             列出 models/ 下可用的二次元角色
  3. POST /svc/change_voice   把 tests/testdata 里的干声换成角色音色，写到 输出/

用法：双击项目根目录的 运行测试.bat
     或命令行：runtime\\py312\\python.exe tests\\test_svc.py [角色名]
"""
import subprocess
import sys
import time
from pathlib import Path

import requests
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
PORT = 6843
BASE = "http://127.0.0.1:%d" % PORT
PY = ROOT / "runtime" / "py312" / "python.exe"
OUT_DIR = ROOT / "输出"
TESTDATA = ROOT / "tests" / "testdata"

# 本机可能配了系统代理（HTTP_PROXY），不绕开的话 127.0.0.1 也会被送去代理，直接 502
HTTP = requests.Session()
HTTP.trust_env = False


def alive():
    """确认是本项目的服务在应答（光有响应不算，代理会回 502）"""
    try:
        r = HTTP.get(BASE + "/health", timeout=3)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def ensure_service():
    if alive():
        print("[OK] 服务已在运行 %s" % BASE)
        return True
    if not PY.is_file():
        print("[失败] 没找到运行环境 runtime\\py312\\python.exe，请先运行 安装环境.bat")
        return False
    print("服务没开，正在拉起（会弹出一个新窗口，别关它）...")
    subprocess.Popen([str(PY), "svc_service.py", "-p", str(PORT)],
                     cwd=str(ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)
    for i in range(240):
        if alive():
            print("[OK] 服务已就绪（等了 %d 秒）" % i)
            return True
        time.sleep(1)
    print("[失败] 等了 240 秒服务还没起来，请看弹出的服务窗口里的报错")
    return False


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wavs = sorted(TESTDATA.glob("*.wav"))
    if not wavs:
        print("[失败] tests\\testdata 下没有测试用 wav")
        return 1
    src = wavs[0]

    if not ensure_service():
        return 1

    models = HTTP.get(BASE + "/models", timeout=20).json()
    if not models:
        print("[失败] models\\ 下没扫描到角色模型（需要 角色.json + 角色*.pth）")
        return 1
    print("[OK] 可用角色: %s" % ", ".join(sorted(models)))

    name = sys.argv[1] if len(sys.argv) > 1 else sorted(models)[0]
    if name not in models:
        print("[失败] 没有角色 %s，可选：%s" % (name, ", ".join(sorted(models))))
        return 1
    print("本次用角色: %s" % name)

    t0 = time.time()
    with open(src, "rb") as f:
        r = HTTP.post(
            BASE + "/svc/change_voice",
            params={"model": name, "transpose": 0, "auto_f0": 1, "cluster_ratio": 0},
            files={"audio": (src.name, f, "audio/wav")},
            timeout=1800,
        )
    if r.status_code != 200:
        print("[失败] 换声返回 %d：%s" % (r.status_code, r.text[:500]))
        return 1

    out = OUT_DIR / ("%s_%s.wav" % (src.stem, name))
    out.write_bytes(r.content)
    print("[OK] 换声完成 %.1fs" % (time.time() - t0))

    a, sr_a = sf.read(src)
    b, sr_b = sf.read(out)
    print("     输入 %.2fs @%dHz -> 输出 %.2fs @%dHz" % (len(a) / sr_a, sr_a, len(b) / sr_b, sr_b))
    print("\n[完成] 去 输出\\ 目录试听：%s" % out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
