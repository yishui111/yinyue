"""在独立进程里跑演唱合成：原生库崩溃不会连累服务端。

用法: python -u workbench/jobrunner.py '<json参数>'
进度以 "@@" 开头的 JSON 行打到 stdout，由服务端读取转发给页面。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    cfg = json.loads(sys.argv[1])

    def cb(stage, detail=""):
        print("@@" + json.dumps({"stage": stage, "detail": detail},
                                ensure_ascii=False), flush=True)

    from workbench.pipeline.sing import synth_song
    synth_song(Path(cfg["song_json"]), Path(cfg["out_path"]),
               cfg["sing"], progress=cb,
               limit_seconds=cfg.get("limit_seconds", 0))
    print("@@" + json.dumps({"stage": "saved", "ok": True},
                            ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
