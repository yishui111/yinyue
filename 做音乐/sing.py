# -*- coding: utf-8 -*-
"""
唱出来:把 DeepSeek 生成的 song.json(+ score.abc)交给本地 YuE2 合成整首歌。

用法(一般直接把作品文件夹拖到 唱歌.bat 上即可):
    python sing.py <作品文件夹> [--fp8] [--budget 16] [--offload-ar]
    python sing.py --check        环境自检(不占 GPU、不出声)

作品文件夹里放:
    song.json   歌词 + 风格(YuE2 请求格式,DeepSeek 按《约束文档》产出)
    score.abc   旋律曲谱(可选;存在则严格按曲谱演唱)

输出(写在同一文件夹):
    audio.flac  成品歌曲(人声+伴奏,48kHz 立体声)
    score.abc   模型最终采用的曲谱(含自己作旋律时的成果)
    plan.json / result.json 等生成记录
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent


def _resolve_home():
    r"""权重位置:环境变量 > 本机固态缓存 D:\yue2(快) > 项目文件夹内(便携形态)。"""
    env = os.environ.get("YUE2_HOME")
    if env:
        return Path(env)
    if (Path(r"D:/yue2") / "weights" / "YuE2-3B" / "model.safetensors").is_file():
        return Path(r"D:/yue2")
    return ROOT


WEIGHTS = _resolve_home() / "weights"


def check():
    """环境自检:不加载模型、不出声,确认链路各环节都在。"""
    ok = True

    def show(name, good, detail=""):
        nonlocal ok
        ok = ok and good
        print(f"  [{'OK' if good else 'FAIL'}] {name} {detail}")

    import importlib.metadata
    print("== YuE2 唱歌环境自检 ==")
    show(f"Python {sys.version.split()[0]}", True)
    try:
        import torch
        show(f"torch {torch.__version__}", True)
        if torch.cuda.is_available():
            prop = torch.cuda.get_device_properties(0)
            show("CUDA 可用", True, f"{prop.name} {prop.total_memory/2**30:.0f}GiB")
        else:
            show("CUDA 可用", False, "torch 看不到显卡,请检查驱动")
    except Exception as exc:
        show("torch 导入", False, str(exc))

    try:
        ver = importlib.metadata.version("yue2-infer")
        show(f"yue2 包 {ver}", True)
    except Exception as exc:
        show("yue2 包", False, str(exc))

    need = [
        (WEIGHTS / "YuE2-3B" / "model.safetensors", 7261441640),
        (WEIGHTS / "YuE2-3B" / "qwen.tiktoken", None),
        (WEIGHTS / "YuE2-Vae" / "model.safetensors", 530512720),
        (WEIGHTS / "YuE2-Vae" / "config.json", None),
    ]
    for path, size in need:
        good = path.is_file() and (size is None or path.stat().st_size == size)
        detail = f"{path.stat().st_size/2**20:.0f}MiB" if path.is_file() else "缺失"
        show(f"权重 {path.parent.name}/{path.name}", good, detail)

    print("== 自检%s ==" % ("通过,可以唱歌" if ok else "未通过,按上面 FAIL 项处理"))
    return 0 if ok else 1


def parse_args(argv):
    """返回 (workdir 文件夹或 None, 选项 dict);workdir 为 None 表示需要交互输入。"""
    opts = {"--fp8": False, "--offload-ar": False, "--budget": None}
    folder = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--fp8":
            opts["--fp8"] = True
        elif a == "--offload-ar":
            opts["--offload-ar"] = True
        elif a == "--budget":
            i += 1
            opts["--budget"] = float(argv[i])
        elif a == "--check":
            opts["check"] = True
        elif a.startswith("-"):
            print(f"未知参数: {a}")
            sys.exit(2)
        elif folder is None:
            folder = a
        else:
            print(f"多余的参数: {a}")
            sys.exit(2)
        i += 1
    return folder, opts


def main():
    folder, opts = parse_args(sys.argv[1:])
    if opts.get("check"):
        sys.exit(check())

    if not folder:
        print("把作品文件夹拖到本窗口,或直接输入路径后回车(文件夹里应有 song.json):")
        folder = input().strip().strip('"')
    workdir = Path(folder.strip().strip('"')).resolve()
    if not workdir.is_dir():
        print(f"文件夹不存在: {workdir}")
        sys.exit(1)
    req_path = workdir / "song.json"
    if not req_path.exists():
        print(f"缺少 {req_path}(让 DeepSeek 按约束文档生成)")
        sys.exit(1)

    request = json.loads(req_path.read_text(encoding="utf-8"))
    abc_path = workdir / "score.abc"
    cot = request.get("cot", "full")
    if abc_path.exists() and cot in ("full", "melody"):
        request["abc"] = abc_path.read_text(encoding="utf-8")
        print(f"[1/3] 已加载曲谱 score.abc({len(request['abc'])} 字符,cot={cot},将严格按曲谱演唱)")
    else:
        request.pop("abc", None)
        print("[1/3] 未提供 score.abc,由模型自己作旋律(结果曲谱会保存在输出里)")

    import torch
    from yue2 import YuE2Pipeline

    # Windows 版 torch 没有编译 flash-attention 内核,但 op 注册存在,
    # 官方 auto 探测会误判导致运行时报错;这里按官方回退顺序强制 cudnn/sdpa。
    import yue2.cuda_graph as _cg
    _orig_ginit = _cg.GraphAR.__init__

    def _ginit(self, *args, **kwargs):
        if kwargs.get("attention_backend", "auto") == "auto":
            kwargs["attention_backend"] = "cudnn" if torch.backends.cudnn.is_available() else "sdpa"
        return _orig_ginit(self, *args, **kwargs)

    _cg.GraphAR.__init__ = _ginit

    t0 = time.time()
    kwargs = {}
    if opts["--fp8"]:
        kwargs["quantization"] = "fp8"
        print("      使用 fp8 量化加载 AR 模型")
    if opts["--budget"]:
        kwargs["memory_budget_gib"] = opts["--budget"]
        print(f"      显存预算 {opts['--budget']:.0f} GiB")
    if opts["--offload-ar"]:
        kwargs["offload_ar"] = True
        print("      开启 AR 模型分阶段卸载")
    pipe = YuE2Pipeline.from_pretrained(
        str(WEIGHTS / "YuE2-3B"),
        vae=str(WEIGHTS / "YuE2-Vae"),
        device="cuda",
        **kwargs,
    )
    print(f"[2/3] 模型加载完成,用时 {time.time()-t0:.0f}s,"
          f"显存峰值 {torch.cuda.max_memory_allocated()/2**30:.1f} GiB")

    t0 = time.time()
    try:
        with pipe:
            song = pipe(**request)
    except torch.cuda.OutOfMemoryError:
        print("显存不足(OOM)。对策:换 Q8 量化运行时(audio.cpp),或缩短歌词/减少段落。")
        raise
    gen = time.time() - t0

    song.save_artifacts(str(workdir))
    peak = torch.cuda.max_memory_allocated() / 2**30
    print(f"[3/3] 合成完成,用时 {gen:.0f}s,显存峰值 {peak:.1f} GiB,truncated={song.truncated}")
    print(f"成品: {workdir / 'audio.flac'}")
    trunc = song.truncated
    if isinstance(trunc, dict):
        trunc = any(trunc.values())
    if trunc:
        print("注意:本次生成触发了长度上限,歌曲可能被截断,可精简歌词后重试。")


if __name__ == "__main__":
    main()
