# -*- coding: utf-8 -*-
r"""sing_service HTTP 接口测试（自带服务实例，端口 8123，不占用正式的 8102）。
需要先由运行器把服务起起来，或单独运行时自动拉起/关闭。"""
import json
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 8123
BASE = "http://127.0.0.1:%d" % PORT
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
RESULTS = []


def req(path, data=None, timeout=600):
    r = OPENER.open(BASE + path, data=data, timeout=timeout)
    return r.status, r.headers, r.read()


def case(name, fn):
    t0 = time.time()
    try:
        detail = fn() or ""
        RESULTS.append((name, True, detail, time.time() - t0))
        print("[通过] %s (%.1fs) %s" % (name, time.time() - t0, detail))
    except Exception as e:
        RESULTS.append((name, False, repr(e), time.time() - t0))
        print("[失败] %s (%.1fs) %r" % (name, time.time() - t0, e))


def t_page():
    st, hd, body = req("/")
    assert st == 200, "GET / 状态 %d" % st
    html = body.decode("utf-8")
    assert "会唱歌" in html and "<!DOCTYPE html>" in html, "页面内容不对"
    assert "text/html" in hd.get("Content-Type", ""), "Content-Type 不对"
    return "工作台页面 %d 字节，标题/结构齐全" % len(body)


def t_demo():
    st, hd, body = req("/api/demo")
    assert st == 200
    d = json.loads(body)
    assert len(d["song"]["lines"]) == 2 and len(d["song"]["lines"][0]["notes"]) == 7
    return "示例歌曲 2 行 14 音符，含示例填词"


def t_health():
    st, hd, body = req("/health")
    assert st == 200
    h = json.loads(body)
    assert h["status"] == "ok" and h["model_ready"] is True, "health: %s" % h
    return "model=%s model_ready=True" % h["model"]


def t_sing_ok():
    song = json.loads((ROOT / "testdata" / "小星星.json").read_text(encoding="utf-8-sig"))
    body = json.dumps({"song": song,
                       "lyrics": {"lines": [{"line_id": 0, "text": "弯弯月亮像小船"},
                                            {"line_id": 1, "text": "载我梦里去银河"}]}}).encode()
    st, hd, wav_bytes = req("/sing", body, timeout=900)
    assert st == 200, "状态 %d: %s" % (st, wav_bytes[:300])
    assert wav_bytes[:4] == b"RIFF", "返回的不是 wav"
    out = Path(__file__).resolve().parent / "产物" / "服务_小星星.wav"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(wav_bytes)
    w = wave.open(str(out))
    dur = w.getnframes() / w.getframerate()
    assert dur > 10.5, "时长 %.2fs 不对" % dur
    return "合成 %.2f 秒 / %.0f KB → 测试\\产物\\服务_小星星.wav" % (dur, len(wav_bytes) / 1024)


def t_sing_bad_count():
    song = json.loads((ROOT / "testdata" / "小星星.json").read_text(encoding="utf-8-sig"))
    body = json.dumps({"song": song,
                       "lyrics": {"lines": [{"line_id": 0, "text": "多了好几个字的歌词"}]}}).encode()
    try:
        st, hd, data = req("/sing", data=body, timeout=300)
    except urllib.error.HTTPError as e:
        st, data = e.code, e.read()
    assert st == 400, "应返回 400，实际 %d" % st
    d = json.loads(data)
    assert "数量不相等" in d.get("error", ""), "报错信息不对: %s" % d
    return "字数不匹配 → 400 +「%s」" % d["error"][:30]


def t_static_404():
    try:
        st, hd, data = req("/static/nope.js", timeout=30)
    except urllib.error.HTTPError as e:
        st, data = e.code, e.read()
    assert st == 404, "不存在的静态文件应 404"
    try:
        st, _, _ = req("/static/../sing.py", timeout=30)
    except urllib.error.HTTPError as e:
        st = e.code
    except Exception:
        st = 0
    assert st in (400, 404), "路径穿越应被拒绝，实际 %d" % st
    return "404 与路径穿越防护正常"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("== sing_service HTTP 测试（端口 %d）==" % PORT)
    case("工作台页面 GET /", t_page)
    case("示例接口 GET /api/demo", t_demo)
    case("健康检查 GET /health", t_health)
    case("合成接口 POST /sing（正常）", t_sing_ok)
    case("合成接口 POST /sing（字数错误）", t_sing_bad_count)
    case("静态资源 404/穿越防护", t_static_404)
    n_fail = sum(1 for _, ok, _, _ in RESULTS if not ok)
    print("== 结果：%d 通过 / %d 失败 ==" % (len(RESULTS) - n_fail, n_fail))
    sys.exit(1 if n_fail else 0)
