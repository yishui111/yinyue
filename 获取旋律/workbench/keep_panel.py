"""看门狗助手：确保 GPT-SoVITS 控制页(8550)在线，掉线就拉起。

由 watchdog.bat 每轮调用（进程短命，几乎不会被外部 python 清理命中）。
控制页路径来自 config.json 的 gptsovits_dir。
"""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STOP = ROOT / ".workbench_stop"


def port_up(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    if STOP.exists():
        return
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return
    base = cfg.get("gptsovits_dir", "").strip()
    if not base:
        return
    if port_up(8550):
        return
    panel = Path(base) / "launcher" / "server_gptsovits.py"
    venv_py = Path(base) / ".venv" / "Scripts" / "python.exe"
    if not panel.is_file() or not venv_py.is_file():
        print(time.strftime("[%H:%M:%S] ") + "[keep_panel] 路径不存在，跳过", flush=True)
        return
    print(time.strftime("[%H:%M:%S] ") + "[keep_panel] GPT-SoVITS 控制页掉线，拉起…", flush=True)
    subprocess.Popen([str(venv_py), "-u", str(panel)], cwd=str(base))


if __name__ == "__main__":
    main()
