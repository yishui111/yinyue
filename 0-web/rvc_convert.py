# -*- coding: utf-8 -*-
r"""
RVC 换声辅助：把任意干声 wav 用 1-rvc 的推理管线换成指定音色（与 WebUI 同一套管线）。

总控页的「RVC 换声」板块用子进程调本脚本，不占用 web 服务进程。
用法：python rvc_convert.py <输入.wav> <音色pth名> <输出.wav> [变调半音]
例：  python rvc_convert.py in.wav Nahida.pth out.wav 0
"""
import os
import sys
import time
from pathlib import Path

RVC_ROOT = Path(__file__).resolve().parent.parent / "1-rvc"
os.environ.setdefault("weight_root", str(RVC_ROOT / "assets" / "weights"))
os.environ.setdefault("index_root", str(RVC_ROOT / "assets" / "indices"))
os.environ.setdefault("rmvpe_root", str(RVC_ROOT / "assets" / "rmvpe"))
os.environ["RVC_CUDA_GRAPH"] = "0"
sys.path.insert(0, str(RVC_ROOT))

import soundfile as sf


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    src, weight, dst = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    pitch = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    wpath = RVC_ROOT / "assets" / "weights" / weight
    if not wpath.is_file():
        print("[失败] assets\\weights 下没有 %s" % weight)
        sys.exit(1)
    index = RVC_ROOT / "assets" / "indices" / (wpath.stem + ".index")

    from configs.config import Config
    from infer.vc.modules import VC

    vc = VC(Config())
    t0 = time.time()
    vc.get_vc(weight)
    print("[rvc_convert] 模型加载 %.1fs" % (time.time() - t0), flush=True)

    t0 = time.time()
    info, (sr_out, audio) = vc.vc_single(
        0, str(src), pitch, "rmvpe",
        str(index) if index.is_file() else "",
        0.7,   # 索引检索比例
        0,     # 重采样 0=用模型采样率
        0.33,  # rms 混合率
        0.33,  # 保护清音
    )
    print(info, flush=True)
    if audio is None or len(audio) == 0:
        print("[失败] 换声没有输出")
        sys.exit(1)
    sf.write(dst, audio, sr_out)
    print("[rvc_convert] 完成 %.1fs -> %s" % (time.time() - t0, dst), flush=True)


if __name__ == "__main__":
    main()
