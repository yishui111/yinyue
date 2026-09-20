# -*- coding: utf-8 -*-
"""
GPT-SoVITS 文字转二次元语音 · 自测

做什么：
  1. 检查 9880 端口的 API，没开就自动拉起（会弹出一个新窗口），等它就绪
  2. GET /tts   用 models\\ayaka 的参考音频做零样本克隆，把文字念成二次元音色
  3. 结果写到 输出\\ 下

用法：双击项目根目录的 运行测试.bat
     或命令行：runtime\\py312\\python.exe tests\\test_tts.py [要念的文字]
"""
import subprocess
import sys
import time
from pathlib import Path

import requests
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
PORT = 9880
BASE = "http://127.0.0.1:%d" % PORT
PY = ROOT / "runtime" / "py312" / "python.exe"
OUT_DIR = ROOT / "输出"
REF_AUDIO = ROOT / "models" / "ayaka" / "ref.wav"
REF_TEXT = ROOT / "models" / "ayaka" / "ref_text.txt"
DEFAULT_TEXT = "晚上好，夜风舒畅，会是一个良宵呢。"


# 本机可能配了系统代理（HTTP_PROXY），不绕开的话 127.0.0.1 也会被送去代理，直接 502
HTTP = requests.Session()
HTTP.trust_env = False


def alive():
    """服务在应答就算活着。注意 502 是代理返回的，不算"""
    try:
        return HTTP.get(BASE + "/", timeout=3).status_code < 500
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
    subprocess.Popen(
        [str(PY), "api_v2.py", "-a", "127.0.0.1", "-p", str(PORT),
         "-c", "GPT_SoVITS/configs/tts_infer.yaml"],
        cwd=str(ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)
    for i in range(300):
        if alive():
            print("[OK] 服务已就绪（等了 %d 秒）" % i)
            return True
        time.sleep(1)
    print("[失败] 等了 300 秒服务还没起来，请看弹出的服务窗口里的报错")
    return False


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not REF_AUDIO.is_file():
        print("[失败] 缺少参考音频 %s" % REF_AUDIO)
        return 1

    if not ensure_service():
        return 1

    text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEXT
    prompt_text = REF_TEXT.read_text(encoding="utf-8").strip() if REF_TEXT.is_file() else text

    print("参考音色: %s" % REF_AUDIO.relative_to(ROOT))
    print("参考文本: %s" % prompt_text)
    print("要念的话: %s" % text)

    t0 = time.time()
    r = HTTP.get(BASE + "/tts", params={
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": "models/ayaka/ref.wav",
        "prompt_text": prompt_text,
        "prompt_lang": "zh",
        "media_type": "wav",
        "streaming_mode": "false",
    }, timeout=1800)

    if r.status_code != 200:
        print("[失败] TTS 返回 %d：%s" % (r.status_code, r.text[:500]))
        return 1

    out = OUT_DIR / "tts_out.wav"
    out.write_bytes(r.content)
    a, sr = sf.read(out)
    print("[OK] 合成完成 %.1fs -> %s" % (time.time() - t0, out.relative_to(ROOT)))
    print("     时长 %.2fs @%dHz，大小 %.1f KB" % (len(a) / sr, sr, len(r.content) / 1024))
    print("\n[完成] 去 输出\\ 目录试听：%s" % out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
