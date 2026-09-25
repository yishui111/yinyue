# -*- coding: utf-8 -*-
r"""启动自检：确认服务在 8102 上活着、页面和接口都通。
结果写入 测试\启动自检结果.txt（每次覆盖，带时间戳）。
用法：runtime\py312\python.exe 测试\启动自检.py   （或双击 运行测试.bat）"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8102"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
sys.stdout.reconfigure(encoding="utf-8")

LINES = []


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn() or ""
        LINES.append(("✅ 通过", name, detail, time.time() - t0))
        print("[通过] %s %s" % (name, detail))
    except Exception as e:
        LINES.append(("❌ 失败", name, repr(e), time.time() - t0))
        print("[失败] %s %r" % (name, e))


def c_port():
    # netstat 输出是 GBK，不能用默认 utf-8 解码
    out = subprocess.run(["netstat", "-ano"], capture_output=True,
                         text=True, encoding="gbk", errors="replace").stdout
    m = re.search(r"127\.0\.0\.1:8102\s+\S+\s+LISTENING\s+(\d+)", out or "")
    assert m, "8102 没有进程在监听（先双击 启动.bat）"
    return "服务进程 PID %s" % m.group(1)


def c_page():
    with OPENER.open(BASE + "/", timeout=10) as r:
        body = r.read().decode("utf-8")
        assert r.status == 200 and "会唱歌" in body, "页面状态 %d" % r.status
    return "工作台页面 %d 字节" % len(body)


def c_health():
    with OPENER.open(BASE + "/health", timeout=15) as r:
        h = json.loads(r.read())
    assert h.get("status") == "ok" and h.get("model_ready"), "health=%s" % h
    return "模型 %s 就绪，6843 角色 %d 个" % (h["model"], len(h.get("svc_roles") or []))


def c_demo():
    with OPENER.open(BASE + "/api/demo", timeout=15) as r:
        d = json.loads(r.read())
    assert len(d["song"]["lines"]) == 2, "示例歌曲不对"
    return "示例《%s》2 行 %d 音符" % (d["song"]["title"],
                                     sum(len(l["notes"]) for l in d["song"]["lines"]))


def c_files():
    assert (ROOT / "runtime" / "py312" / "python.exe").is_file(), "缺 runtime"
    ckpt = ROOT / "diffsinger" / "checkpoints" / "0211_opencpop_ds1000_keyshift" / "model_ckpt_steps_360000.ckpt"
    voc = ROOT / "diffsinger" / "checkpoints" / "nsf_hifigan" / "model"
    assert ckpt.is_file(), "缺声学模型 ckpt"
    assert voc.is_file(), "缺声码器"
    return "runtime / 声学模型(799MB) / 声码器 齐全"


if __name__ == "__main__":
    print("== 会唱歌 启动自检  %s ==" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    check("服务文件齐全", c_files)
    check("端口 8102 监听中", c_port)
    check("工作台页面 GET /", c_page)
    check("模型健康 GET /health", c_health)
    check("示例接口 GET /api/demo", c_demo)

    n_fail = sum(1 for r in LINES if r[0].startswith("❌"))
    txt = ["会唱歌 · 启动自检结果",
           "时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "页面地址：http://127.0.0.1:8102",
           "结论：%d 项检查，%d 通过，%d 失败" % (len(LINES), len(LINES) - n_fail, n_fail),
           "",
           "| 结果 | 检查项 | 说明 | 耗时(s) |",
           "|---|---|---|---|"]
    for res, name, detail, secs in LINES:
        txt.append("| %s | %s | %s | %.1f |" % (res, name, detail, secs))
    if n_fail == 0:
        txt += ["", "服务正在运行。浏览器打开 http://127.0.0.1:8102 即可操作：",
                "载入示例/上传 song.json → 逐行填词 → 点「🎤 唱出来」试听下载。"]
    else:
        txt += ["", "有失败项：若端口未监听，先双击 启动.bat；依赖缺失先跑 安装环境.bat，模型缺失看 说明.md 第二节。"]
    out = ROOT / "测试" / "启动自检结果.txt"
    out.write_text("\n".join(txt), encoding="utf-8")
    print("\n结果已写入 测试\\启动自检结果.txt（%d 通过 / %d 失败）" % (len(LINES) - n_fail, n_fail))
    sys.exit(1 if n_fail else 0)
