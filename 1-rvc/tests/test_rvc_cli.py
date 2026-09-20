# -*- coding: utf-8 -*-
"""
RVC 换声自测（命令行，走的是 WebUI 同一套推理管线，不需要先开服务）

做什么：加载 assets/weights 里已训练的音色，把 tests/testdata 里的干声换成该音色，
        结果写到 输出/ 下。跑通即说明模型和环境都正常。

用法：双击项目根目录的 运行测试.bat
     或命令行：runtime\\py312\\python.exe tests\\test_rvc_cli.py [音色pth名]
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("weight_root", str(ROOT / "assets" / "weights"))
os.environ.setdefault("index_root", str(ROOT / "assets" / "indices"))
os.environ.setdefault("outside_index_root", str(ROOT / "assets" / "indices"))
os.environ.setdefault("rmvpe_root", str(ROOT / "assets" / "rmvpe"))
os.environ.setdefault("weight_pymss_root", str(ROOT / "assets" / "pymss_weights"))
os.environ["RVC_CUDA_GRAPH"] = "0"
sys.path.insert(0, str(ROOT))

import soundfile as sf

from configs.config import Config
from infer.vc.modules import VC

OUT_DIR = ROOT / "输出"
TESTDATA = ROOT / "tests" / "testdata"

WEIGHT = sys.argv[1] if len(sys.argv) > 1 else "Nahida.pth"
INDEX = ROOT / "assets" / "indices" / (Path(WEIGHT).stem + ".index")


def pick_input():
    wavs = sorted(TESTDATA.glob("*.wav"))
    if not wavs:
        print("[失败] tests\\testdata 下没有测试用 wav")
        sys.exit(1)
    return wavs[0]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src = pick_input()
    if not (ROOT / "assets" / "weights" / WEIGHT).is_file():
        print("[失败] assets\\weights 下没有 %s" % WEIGHT)
        print("       现有的：%s" % ", ".join(p.name for p in (ROOT / "assets" / "weights").glob("*.pth")))
        sys.exit(1)

    print("音色: %s" % WEIGHT)
    print("输入: %s" % src.relative_to(ROOT))
    if INDEX.is_file():
        print("索引: %s" % INDEX.relative_to(ROOT))

    config = Config()
    vc = VC(config)
    t0 = time.time()
    vc.get_vc(WEIGHT)
    print("[OK] 模型加载 %.1fs, 目标采样率 %s" % (time.time() - t0, vc.tgt_sr))

    t0 = time.time()
    info, (sr_out, audio_out) = vc.vc_single(
        0,                                  # sid
        str(src),                           # 输入 wav
        0,                                  # 变调半音
        "rmvpe",                            # 音高提取方式
        str(INDEX) if INDEX.is_file() else "",
        0.7,                                # 索引检索比例
        0,                                  # 重采样(0=用模型采样率)
        0.33,                               # rms 混合率
        0.33,                               # 保护清音
    )
    print(info)

    if audio_out is None or len(audio_out) == 0:
        print("[失败] 换声没有输出")
        sys.exit(1)

    out = OUT_DIR / ("%s_%s.wav" % (src.stem, Path(WEIGHT).stem))
    sf.write(out, audio_out, sr_out)
    a, sr_a = sf.read(src)
    print("[OK] 换声完成 %.1fs -> %s" % (time.time() - t0, out.relative_to(ROOT)))
    print("     输入 %.2fs @%dHz -> 输出 %.2fs @%dHz" % (len(a) / sr_a, sr_a, len(audio_out) / sr_out, sr_out))
    print("\n[完成] 去 输出\\ 目录试听：%s" % out.name)


if __name__ == "__main__":
    main()
