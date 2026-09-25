# -*- coding: utf-8 -*-
r"""分步验证：机器高负载时整套测试跑不完一个时间片，按部分逐个跑，结果累积在
测试\分步结果.json，最后 report 子命令汇总生成 测试报告.md。

用法：runtime\py312\python.exe 测试\分步验证.py unit|http|cli|err|report
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / "runtime" / "py312" / "python.exe")
STATE = ROOT / "测试" / "分步结果.json"
sys.stdout.reconfigure(encoding="utf-8")


def load():
    if STATE.is_file():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"rows": []}


def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def run_case(state, group, name, args, timeout, cwd=ROOT, expect_fail=False):
    t0 = time.time()
    p = subprocess.run([PY] + args, cwd=str(cwd), env={**__import__("os").environ,
                       "PYTHONIOENCODING": "utf-8"}, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    ok = (p.returncode != 0) if expect_fail else (p.returncode == 0)
    state["rows"].append({"group": group, "name": name, "ok": ok,
                          "secs": round(time.time() - t0, 1),
                          "detail": " ".join(out.split())[-260:]})
    print("[通过] %s (%.1fs)" % (name, time.time() - t0) if ok
          else "[失败] %s\n%s" % (name, out[-1200:]), flush=True)
    save(state)
    return ok


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else ""
    state = load()
    if part == "unit":
        # 借用 test_ds_builder.py 的用例（它自己打印 [通过]/[失败]），拆成逐条记录
        p = subprocess.run([PY, "测试/test_ds_builder.py"], cwd=str(ROOT),
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        import re
        for m in re.finditer(r"^\[(通过|失败)\] (.+?) \(([\d.]+)s\) (.*)$", p.stdout or "", re.M):
            state["rows"].append({"group": "ds_builder 单元测试", "name": m.group(2),
                                  "ok": m.group(1) == "通过", "secs": float(m.group(3)),
                                  "detail": m.group(4)})
        save(state)
        print("unit 完成：%s" % ("全部通过" if p.returncode == 0 else "有用例失败"))
    elif part == "http":
        svc = subprocess.Popen([PY, "-u", "sing_service.py", "-p", "8123"], cwd=str(ROOT),
                               env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import urllib.request
            up = False
            for _ in range(40):
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})) \
                            .open("http://127.0.0.1:8123/health", timeout=3) as r:
                        up = r.status == 200
                        break
                except Exception:
                    time.sleep(1)
            if not up:
                state["rows"].append({"group": "HTTP 服务测试", "name": "测试服务启动(8123)",
                                      "ok": False, "secs": 40, "detail": "未就绪"})
                save(state)
                sys.exit(1)
            p = subprocess.run([PY, "测试/test_service.py"], cwd=str(ROOT),
                               env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=1500)
            import re
            for m in re.finditer(r"^\[(通过|失败)\] (.+?) \(([\d.]+)s\) (.*)$", p.stdout or "", re.M):
                state["rows"].append({"group": "HTTP 服务测试", "name": m.group(2),
                                      "ok": m.group(1) == "通过", "secs": float(m.group(3)),
                                      "detail": m.group(4)})
            save(state)
            print("http 完成：%s" % ("全部通过" if p.returncode == 0 else "有用例失败"))
        finally:
            svc.terminate()
    elif part == "cli":
        run_case(state, "CLI 端到端", "sing.py 小星星+示例填词 → wav",
                 ["-u", "sing.py", "testdata/小星星.json", "testdata/填词示例.json",
                  "-o", "测试/产物/CLI_小星星.wav"], 1500)
    elif part == "err":
        ok = run_case(state, "错误路径", "8 字歌词 vs 7 音符 → 应拒绝",
                      ["ds_builder.py", "testdata/小星星.json", "testdata/填词示例错字数.json",
                       "-o", "测试/_bad.ds"], 300, cwd=ROOT, expect_fail=True)
        row = state["rows"][-1]
        row["detail"] = ("拒绝并报错：" + row["detail"][-80:]) if ok else "竟然没拒绝"
        save(state)
    elif part == "report":
        from 测试报告生成 import write_report  # noqa
        write_report(state["rows"])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
