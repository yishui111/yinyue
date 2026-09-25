# -*- coding: utf-8 -*-
r"""汇总 分步结果.json → 测试\测试报告.md（供 分步验证.py report 子命令调用）"""
import sys
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "测试"


def wav_info(path: Path):
    w = wave.open(str(path))
    return "%.2f 秒 @ %d Hz" % (w.getnframes() / w.getframerate(), w.getframerate())


def gpu_name():
    try:
        import subprocess
        p = subprocess.run([str(ROOT / "runtime" / "py312" / "python.exe"),
                            "-c", "import torch;print(torch.cuda.get_device_name(0))"],
                           capture_output=True, text=True, timeout=600)
        return (p.stdout or "").strip()
    except Exception:
        return "未知"


def write_report(rows):
    sys.stdout.reconfigure(encoding="utf-8")

    def esc(s):
        return str(s).replace("|", "\\|")

    lines = ["# 会唱歌 · 功能测试报告\n"]
    lines.append("- 测试时间：%s（分步跑通后汇总）" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("- 机器：Windows 10 / %s" % gpu_name())
    lines.append("- 模型：DiffSinger v2.5.1 + openvpi `0211_opencpop_ds1000_keyshift`"
                 "（已用 迁移旧模型.py 迁到新版格式）+ NSF-HiFiGAN 声码器")
    lines.append("- 测试歌曲：《小星星》2 行 14 音符，示例填词「弯弯月亮像小船，载我梦里去银河」")
    lines.append("- 复跑：`runtime\\py312\\python.exe 测试\\运行全部测试.py`（一把跑完）"
                 "或 `测试\\分步验证.py unit|http|cli|err` + `report`（机器忙时分步跑）\n")
    lines.append("| 分组 | 用例 | 结果 | 耗时(s) | 说明 |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        lines.append("| %s | %s | %s | %.1f | %s |" %
                     (esc(r["group"]), esc(r["name"]), "✅ 通过" if r["ok"] else "❌ 失败",
                      float(r["secs"]), esc(r["detail"])))
    n_fail = sum(1 for r in rows if not r["ok"])
    lines.append("\n**结论：%d 项测试，%d 通过，%d 失败。**\n" % (len(rows), len(rows) - n_fail, n_fail))

    lines.append("## 产物（测试\\产物\\）\n")
    lines.append("| 文件 | 来源 | 内容 |")
    lines.append("|---|---|---|")
    names = {
        "CLI_小星星.wav": ("sing.py 命令行", "《小星星》旋律 + 示例新词，DiffSinger 干声"),
        "服务_小星星.wav": ("POST /sing 接口", "同上，走 HTTP 服务（8123 测试端口）"),
    }
    for f in sorted((TESTS / "产物").glob("*")):
        src, desc = names.get(f.name, ("其他", f.name))
        try:
            info = wav_info(f) if f.suffix == ".wav" else "%.0f KB" % (f.stat().st_size / 1024)
        except Exception:
            info = "%.0f KB" % (f.stat().st_size / 1024)
        lines.append("| %s | %s | %s（%s） |" % (esc(f.name), esc(src), esc(desc), info))

    lines += ["", "## 说明\n",
              "- 换声（--role / 页面角色下拉框）依赖 3-so-vits-svc 的 6843 服务在线；"
              "接口与总控页同款，本次未启动 6843 故未覆盖换声链路。",
              "- 服务日志：`输出\\服务日志.log`（8102 常驻服务）、`输出\\推理日志.log`（每次推理落盘）。",
              "- 模型仅限非商业用途（Opencpop 语料 CC-BY-NC 4.0）。"]
    out = TESTS / "测试报告.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("报告已写入 测试\\测试报告.md（%d 项，%d 失败）" % (len(rows), n_fail))


if __name__ == "__main__":
    import json
    state = json.loads((TESTS / "分步结果.json").read_text(encoding="utf-8"))
    write_report(state["rows"])
