# -*- coding: utf-8 -*-
r"""测试总入口：跑 单元测试(ds_builder) + HTTP 服务测试 + CLI 端到端，
自动生成 测试\测试报告.md。产物 wav 落在 测试\产物\。

用法：runtime\py312\python.exe 测试\运行全部测试.py
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "测试"
OUT = TESTS / "产物"
PY = ROOT / "runtime" / "py312" / "python.exe"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

sys.stdout.reconfigure(encoding="utf-8")
ROWS = []          # (group, name, ok, detail, seconds)
# Windows 上给子进程传精简 env 会缺 SystemRoot，Winsock 直接初始化失败（WinError 10106），
# 必须在完整 os.environ 基础上追加变量
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def parse_cases(group, output):
    for m in re.finditer(r"^\[(通过|失败)\] (.+?) \(([\d.]+)s\) (.*)$", output, re.M):
        ok = m.group(1) == "通过"
        ROWS.append((group, m.group(2), ok, m.group(4), float(m.group(3))))


def run_step(title, cmd, timeout=1800):
    print("\n>>> %s\n    %s" % (title, " ".join(str(c) for c in cmd[1:])), flush=True)
    t0 = time.time()
    p = subprocess.run([str(PY)] + cmd, cwd=str(ROOT), env=ENV,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-3000:] if p.returncode else out[-1200:], flush=True)
    return p, out, time.time() - t0


def gpu_name():
    try:
        p = subprocess.run([str(PY), "-c", "import torch;print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"],
                           capture_output=True, text=True, timeout=600)
        return (p.stdout or "").strip() or "未知"
    except Exception:
        return "未知"


def wav_info(path: Path):
    w = wave.open(str(path))
    return "%.2f 秒 @ %d Hz" % (w.getnframes() / w.getframerate(), w.getframerate())


def main():
    OUT.mkdir(exist_ok=True)
    print("会唱歌 功能测试  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("GPU:", gpu_name(), flush=True)

    # 1) 单元测试
    p, out, secs = run_step("ds_builder 单元测试", ["测试/test_ds_builder.py"])
    parse_cases("ds_builder 单元测试", out)
    unit_ok = p.returncode == 0

    # 2) HTTP 服务测试（测试专用端口 8123）
    print("\n>>> 启动测试服务（8123）…", flush=True)
    svc = subprocess.Popen([str(PY), "-u", "sing_service.py", "-p", "8123"], cwd=str(ROOT),
                           env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = False
        for _ in range(30):
            try:
                with OPENER.open("http://127.0.0.1:8123/health", timeout=3) as r:
                    up = r.status == 200
                    break
            except Exception:
                time.sleep(1)
        if not up:
            ROWS.append(("HTTP 服务测试", "服务启动", False, "8123 未就绪", 0))
        else:
            p, out, secs = run_step("HTTP 服务测试", ["测试/test_service.py"], timeout=1800)
            parse_cases("HTTP 服务测试", out)
    finally:
        svc.terminate()
        try:
            svc.wait(timeout=15)
        except Exception:
            svc.kill()

    # 3) CLI 端到端
    print("\n>>> CLI 端到端：sing.py 小星星 + 示例填词", flush=True)
    t0 = time.time()
    p = subprocess.run([str(PY), "sing.py", "testdata/小星星.json", "testdata/填词示例.json",
                        "-o", "测试/产物/CLI_小星星.wav"], cwd=str(ROOT),
                       env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=1800)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-1500:], flush=True)
    cli_secs = time.time() - t0
    cli_wav = OUT / "CLI_小星星.wav"
    cli_ok = p.returncode == 0 and cli_wav.is_file() and cli_wav.read_bytes()[:4] == b"RIFF"
    detail = wav_info(cli_wav) if cli_ok else (out[-200:] or "无输出")
    ROWS.append(("CLI 端到端", "sing.py 小星星+示例填词 → wav", cli_ok, detail, cli_secs))

    # 4) 字数校验错误路径（不走模型，快）
    print("\n>>> 错误路径：字数不匹配", flush=True)
    t0 = time.time()
    bad = {"lines": [{"line_id": 0, "chars": ["多", "一", "个", "字", "的", "歌", "词", "！"]}]}
    (TESTS / "_bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([str(PY), "ds_builder.py", "testdata/小星星.json", "测试/_bad.json",
                        "-o", "测试/_bad.ds"], cwd=str(ROOT), env=ENV,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    out = ((p.stdout or "") + (p.stderr or ""))
    bad_ok = p.returncode != 0 and "数量不相等" in out
    ROWS.append(("错误路径", "8 字歌词 vs 7 音符 → 应拒绝", bad_ok,
                 "报错含「数量不相等」" if bad_ok else out[-200:], time.time() - t0))
    (TESTS / "_bad.json").unlink(missing_ok=True)
    (TESTS / "_bad.ds").unlink(missing_ok=True)

    # 生成报告
    write_report()
    n_fail = sum(1 for r in ROWS if not r[2])
    print("\n== 全部完成：%d 项通过 / %d 项失败，报告见 测试\\测试报告.md =="
          % (len(ROWS) - n_fail, n_fail))
    return 1 if (n_fail or not unit_ok) else 0


def write_report():
    def esc(s):
        return str(s).replace("|", "\\|")
    lines = []
    lines.append("# 会唱歌 · 功能测试报告\n")
    lines.append("- 测试时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("- 机器：Windows 10 / %s" % gpu_name())
    lines.append("- 模型：DiffSinger v2.5.1 + openvpi `0211_opencpop_ds1000_keyshift`"
                 "（已用 迁移旧模型.py 迁到新版格式）+ NSF-HiFiGAN 声码器")
    lines.append("- 测试歌曲：《小星星》2 行 14 音符，示例填词「弯弯月亮像小船，载我梦里去银河」")
    lines.append("- 复跑方式：`runtime\\py312\\python.exe 测试\\运行全部测试.py`\n")
    lines.append("| 分组 | 用例 | 结果 | 耗时(s) | 说明 |")
    lines.append("|---|---|---|---|---|")
    for group, name, ok, detail, secs in ROWS:
        lines.append("| %s | %s | %s | %.1f | %s |" %
                     (esc(group), esc(name), "✅ 通过" if ok else "❌ 失败", secs, esc(detail)))
    n_fail = sum(1 for r in ROWS if not r[2])
    lines.append("\n**结论：%d 项测试，%d 通过，%d 失败。**\n" % (len(ROWS), len(ROWS) - n_fail, n_fail))
    lines.append("## 产物（测试\\产物\\）\n")
    lines.append("| 文件 | 来源 | 内容 |")
    lines.append("|---|---|---|")
    names = {
        "CLI_小星星.wav": ("sing.py 命令行", "《小星星》旋律 + 示例新词，DiffSinger 干声"),
        "服务_小星星.wav": ("POST /sing 接口", "同上，走 HTTP 服务（8123 测试端口）"),
    }
    for f in sorted(OUT.glob("*")):
        src = names.get(f.name, ("", ""))[0] or "其他"
        desc = names.get(f.name, ("", ""))[1] or f.name
        try:
            info = wav_info(f) if f.suffix == ".wav" else "%.0f KB" % (f.stat().st_size / 1024)
        except Exception:
            info = "%.0f KB" % (f.stat().st_size / 1024)
        lines.append("| %s | %s | %s（%s） |" % (esc(f.name), esc(src), esc(desc), info))
    lines.append("\n## 说明\n")
    lines.append("- 换声（--role / 页面角色下拉框）依赖 3-so-vits-svc 的 6843 服务在线；"
                 "本次测试时 6843 %s，换声链路的接口与总控页同款。" %
                 ("未启动" if not any("svc_roles" in r[3] for r in ROWS) else "有角色"))
    lines.append("- 字数校验、休止换气、null-midi 处理等规则见 `ds_builder.py` 顶部注释与 `说明.md` 第五节。")
    lines.append("- 模型仅限非商业用途（Opencpop 语料 CC-BY-NC 4.0）。")
    (TESTS / "测试报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n报告已写入 测试\\测试报告.md", flush=True)


if __name__ == "__main__":
    sys.exit(main())
