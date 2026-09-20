# -*- coding: utf-8 -*-
"""
总控页自测：起一个临时总控服务（随机端口），逐项验证它与 4 个项目的接口是否对得上。

前置：三个引擎服务（6843 / 9880 / 7865）必须已经在跑；
      没跑的话对应项会失败并提示先去该项目 启动.bat。

用法：runtime\py312\python.exe tests\selftest.py
"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import web_service as ws

HOST, PORT = "127.0.0.1", 0  # 0 = 随机空闲端口
# 走本机回环必须绕开系统代理（HTTP_PROXY 会把 127.0.0.1 也送代理返回 502）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PASS, FAIL = "✓", "✗"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s %s%s" % (PASS if ok else FAIL, name, ("  —— " + detail) if detail else ""))


def get(base, path, timeout=60):
    with OPENER.open(base + path, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get("Content-Type", "")


def main():
    srv = ws.ThreadingHTTPServer((HOST, PORT), ws.Handler)
    base = "http://%s:%d" % srv.server_address[:2]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("临时总控服务：%s\n" % base)

    # 0) 总控页本体
    try:
        st, data, ctype = get(base, "/")
        check("总控页页面可打开（/ 返回 HTML）",
              st == 200 and "text/html" in ctype and "总控" in data.decode("utf-8", "replace"))
    except Exception as e:
        check("总控页页面可打开", False, repr(e))

    # 1) /api/status 汇总四个项目
    try:
        items = json.loads(get(base, "/api/status", timeout=30)[1])
        ids = [i["id"] for i in items]
        check("/api/status 返回 4 项，与 4 个目录一一对应",
              ids == ["svc", "tts", "rvc", "e2e"], str(ids))
        for it in items:
            print("   [%s] %-22s %-16s %s" % ("在" if it["up"] else "停", it["name"], it["dir"], it["detail"]))
    except Exception as e:
        check("/api/status", False, repr(e))
        items = []

    up = {i["id"]: i["up"] for i in items}

    # 2) so-vits（6843）：角色列表就是服务 /models 的原样转发
    if up.get("svc"):
        try:
            names = json.loads(get(base, "/api/svc/models", timeout=30)[1])
            check("so-vits 角色列表非空", bool(names), "角色: %s" % ", ".join(names))
        except Exception as e:
            check("so-vits 角色列表", False, repr(e))
    else:
        check("so-vits（6843）", False, "服务没开，去 3-so-vits-svc 双击 启动.bat")

    # 3) GPT-SoVITS（9880）：models 目录四件套角色
    if up.get("tts"):
        try:
            roles = json.loads(get(base, "/api/tts/roles", timeout=30)[1])
            ok = bool(roles) and all(r["gpt"] and r["sovits"] and r["ref_audio"] for r in roles)
            check("GPT-SoVITS 角色四件套齐全", ok,
                  "角色: %s" % ", ".join(r["name"] for r in roles))
        except Exception as e:
            check("GPT-SoVITS 角色列表", False, repr(e))
    else:
        check("GPT-SoVITS（9880）", False, "服务没开，去 2-gpt-sovits 双击 启动.bat")

    # 4) RVC（7865）：weights 目录音色
    if up.get("rvc"):
        try:
            names = json.loads(get(base, "/api/rvc/roles", timeout=30)[1])
            check("RVC 音色列表非空", bool(names), "音色: %s" % ", ".join(names[:5]) + ("..." if len(names) > 5 else ""))
        except Exception as e:
            check("RVC 音色列表", False, repr(e))
    else:
        check("RVC（7865）", False, "服务没开，去 1-rvc 双击 启动.bat")

    # 5) 端到端：依赖检查 + 任务状态接口
    try:
        s = json.loads(get(base, "/api/e2e/status", timeout=30)[1])
        check("端到端任务状态接口可用", s.get("state") in ("idle", "running", "done", "failed"),
              "state=%s" % s.get("state"))
    except Exception as e:
        check("端到端状态接口", False, repr(e))
    if not up.get("e2e"):
        check("端到端就绪", False, "依赖的 6843 没开或 4-e2e 运行环境缺失")

    # 6) 实测一项推理：TTS 最快、最能代表"页面连的是真服务"
    if up.get("tts"):
        try:
            req = urllib.request.Request(
                base + "/api/tts", data=json.dumps(
                    {"role": "", "text": "总控页自测。"}, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=600) as r:
                data, ctype = r.read(), r.headers.get("Content-Type", "")
            check("实测文字转语音（走 9880 真合成）",
                  r.status == 200 and ctype == "audio/wav" and len(data) > 10000,
                  "返回 %d 字节 %s" % (len(data), ctype))
        except Exception as e:
            check("实测文字转语音", False, repr(e))

    srv.shutdown()
    n_ok = sum(results)
    print("\n%d/%d 项通过。" % (n_ok, len(results)))
    sys.exit(0 if n_ok == len(results) else 1)


if __name__ == "__main__":
    main()
