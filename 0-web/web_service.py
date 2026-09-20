# -*- coding: utf-8 -*-
r"""
总控页服务：一个页面把 1-rvc / 2-gpt-sovits / 3-so-vits-svc / 4-e2e 一一对应起来。

只做三件事：
  1. 提供总控页静态页面（static\index.html）
  2. 汇总 3 个服务（6843 / 9880 / 7865）的健康状态
  3. 反代各服务的推理接口（换声 / 文字转语音 / RVC 换声 / 端到端视频）

页面与本服务同源，浏览器不会有跨域问题；本服务对上游的访问全部绕开系统代理
（本机设了 HTTP_PROXY 时 127.0.0.1 也会被送代理返回 502，历史坑，见 1-rvc 说明）。

只用 Python 标准库，任何一份 runtime\py312（或系统 Python 3.12+）都能跑：
  python web_service.py [-a 127.0.0.1] [-p 8100]
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
DIR_RVC = BASE / "1-rvc"
DIR_TTS = BASE / "2-gpt-sovits"
DIR_SVC = BASE / "3-so-vits-svc"
DIR_E2E = BASE / "4-e2e"

SVC_URL = "http://127.0.0.1:6843"
TTS_URL = "http://127.0.0.1:9880"
RVC_URL = "http://127.0.0.1:7865"

STATIC_DIR = ROOT / "static"
OUT_DIR = ROOT / "输出"
UPLOAD_DIR = OUT_DIR / "uploads"
E2E_LOG = OUT_DIR / "e2e_job.log"
MAX_BODY = 800 * 1024 * 1024  # 上传上限 800MB（够放长视频）

# 绕开系统代理：不这么干 127.0.0.1 会被送进代理直接 502
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch(url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with OPENER.open(req, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get("Content-Type", "")


# ---------------------------------------------------------------- multipart
def parse_multipart(body: bytes, ctype: str):
    """手工解析 multipart/form-data，返回 (fields, files)；files[name]=(filename, bytes)"""
    m = re.search(r'boundary="?([^";,]+)"?', ctype)
    if not m:
        raise ValueError("请求不是 multipart/form-data")
    bnd = ("--" + m.group(1)).encode()
    fields, files = {}, {}
    for raw in body.split(bnd):
        if raw in (b"", b"--", b"--\r\n"):
            continue
        if raw.startswith(b"\r\n"):
            raw = raw[2:]
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        head, sep, payload = raw.partition(b"\r\n\r\n")
        if not sep:
            continue
        disp = b""
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-disposition"):
                disp = line
        name = re.search(r'name="([^"]*)"', disp.decode("utf-8", "replace"))
        if not name:
            continue
        fname = re.search(r'filename="([^"]*)"', disp.decode("utf-8", "replace"))
        if fname:
            files[name.group(1)] = (fname.group(1), payload)
        else:
            fields[name.group(1)] = payload.decode("utf-8", "replace")
    return fields, files


def build_multipart(fields: dict, file_field: str, filename: str, file_bytes: bytes):
    """构造发给上游 6843 的 multipart/form-data"""
    bnd = "----zongkong" + str(int(time.time() * 1000))
    parts = []
    for k, v in fields.items():
        parts.append(("--" + bnd).encode())
        parts.append(('Content-Disposition: form-data; name="%s"' % k).encode())
        parts.append(b"")
        parts.append(str(v).encode("utf-8"))
    parts.append(("--" + bnd).encode())
    parts.append(('Content-Disposition: form-data; name="%s"; filename="%s"'
                  % (file_field, filename)).encode())
    parts.append(b"Content-Type: application/octet-stream")
    parts.append(b"")
    parts.append(file_bytes)
    parts.append(("--" + bnd + "--").encode())
    body = b"\r\n".join(parts) + b"\r\n"
    return body, "multipart/form-data; boundary=" + bnd


# ---------------------------------------------------------------- 角色清单
def tts_roles():
    r"""扫 2-gpt-sovits\models\ 下的角色目录（ref.wav + ref_text.txt + ckpt/pth 四件套）"""
    roles = []
    models = DIR_TTS / "models"
    if not models.is_dir():
        return roles
    for d in sorted(models.iterdir()):
        if not d.is_dir() or not (d / "ref.wav").is_file():
            continue
        ckpts = sorted(d.glob("*.ckpt"))
        pths = sorted(d.glob("*.pth"))
        prompt = ""
        rtext = d / "ref_text.txt"
        if rtext.is_file():
            raw = rtext.read_bytes()
            for enc in ("utf-8-sig", "gbk"):
                try:
                    prompt = raw.decode(enc).strip()
                    break
                except UnicodeDecodeError:
                    continue
        roles.append({
            "name": d.name,
            "ref_audio": "models/%s/ref.wav" % d.name,
            "prompt_text": prompt,
            "gpt": str(ckpts[0]) if ckpts else "",
            "sovits": str(pths[0]) if pths else "",
        })
    return roles


def rvc_roles():
    r"""扫 1-rvc\assets\weights\ 下已训练音色（.pth）"""
    w = DIR_RVC / "assets" / "weights"
    if not w.is_dir():
        return []
    return sorted(p.name for p in w.glob("*.pth"))


# ---------------------------------------------------------------- 服务状态
def service_status():
    items = []

    svc_up = False
    svc_detail = "未启动"
    try:
        st, data, _ = fetch(SVC_URL + "/health", timeout=6)
        # 必须校验 JSON status=="ok"，只看"有响应"会被代理 502 骗过（历史坑）
        svc_up = st == 200 and json.loads(data.decode("utf-8", "replace")).get("status") == "ok"
        if svc_up:
            _, mdata, _ = fetch(SVC_URL + "/models", timeout=10)
            n = len(json.loads(mdata.decode("utf-8", "replace")))
            svc_detail = "%d 个角色" % n
    except Exception:
        pass
    items.append({"id": "svc", "name": "so-vits 唱歌换声", "dir": "3-so-vits-svc",
                  "url": SVC_URL, "port": 6843, "up": svc_up, "detail": svc_detail})

    tts_up, tts_detail = False, "未启动"
    try:
        st, _, _ = fetch(TTS_URL + "/docs", timeout=6)
        tts_up = st == 200
        if tts_up:
            tts_detail = "%d 个角色" % len(tts_roles())
    except Exception:
        pass
    items.append({"id": "tts", "name": "GPT-SoVITS 文字转语音", "dir": "2-gpt-sovits",
                  "url": TTS_URL, "port": 9880, "up": tts_up, "detail": tts_detail})

    rvc_up = False
    try:
        st, _, _ = fetch(RVC_URL + "/", timeout=6)
        rvc_up = st == 200
    except Exception:
        pass
    items.append({"id": "rvc", "name": "RVC 换声/训练 WebUI", "dir": "1-rvc",
                  "url": RVC_URL, "port": 7865, "up": rvc_up,
                  "detail": ("%d 个音色" % len(rvc_roles())) if rvc_up else "未启动"})

    e2e_ok = (svc_up and (DIR_E2E / "runtime" / "py312" / "python.exe").is_file()
              and (DIR_E2E / "e2e_test.py").is_file())
    items.append({"id": "e2e", "name": "端到端视频换声", "dir": "4-e2e", "url": "",
                  "port": 0, "up": e2e_ok,
                  "detail": "就绪（依赖 6843）" if e2e_ok else "缺 6843 服务或 4-e2e 运行环境"})
    return items


# ---------------------------------------------------------------- GPT-SoVITS
TTS_LOCK = threading.Lock()
_tts_loaded = None  # (gpt_path, sovits_path) 9880 当前已加载的权重


def tts_synthesize(role_name, text):
    roles = {r["name"]: r for r in tts_roles()}
    if not roles:
        raise RuntimeError("2-gpt-sovits\\models\\ 下没有角色（需要 ref.wav 四件套）")
    r = roles.get(role_name) or next(iter(roles.values()))
    if not (r["gpt"] and r["sovits"]):
        raise RuntimeError("角色 %s 缺 ckpt/pth 权重文件" % r["name"])

    global _tts_loaded
    with TTS_LOCK:
        if _tts_loaded != (r["gpt"], r["sovits"]):
            # yaml 里 custom 段默认是底模权重，必须先切到角色自己的权重再合成
            fetch(TTS_URL + "/set_gpt_weights", timeout=300,
                  data=urllib.parse.urlencode({"weights_path": r["gpt"]}).encode())
            fetch(TTS_URL + "/set_sovits_weights", timeout=300,
                  data=urllib.parse.urlencode({"weights_path": r["sovits"]}).encode())
            _tts_loaded = (r["gpt"], r["sovits"])
        payload = {
            "text": text, "text_lang": "zh",
            "ref_audio_path": r["ref_audio"],
            "prompt_text": r["prompt_text"], "prompt_lang": "zh",
            "text_split_method": "cut5", "media_type": "wav", "streaming_mode": False,
        }
        st, data, ctype = fetch(
            TTS_URL + "/tts", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, timeout=600)
    if st != 200 or ctype.startswith("application/json"):
        raise RuntimeError("TTS 失败: %s" % data.decode("utf-8", "replace")[:300])
    return data


# ---------------------------------------------------------------- RVC 换声
def rvc_convert(in_wav: Path, weight: str, out_wav: Path):
    """用 1-rvc 的同款推理管线换声（加载一次模型 10~20s，走子进程不占本服务）"""
    py = DIR_RVC / "runtime" / "py312" / "python.exe"
    if not py.is_file():
        raise RuntimeError("没找到 1-rvc 的运行环境")
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [str(py), str(ROOT / "rvc_convert.py"), str(in_wav), weight, str(out_wav)],
        cwd=str(DIR_RVC), env=env, timeout=900, capture_output=True, text=True)
    if p.returncode != 0 or not out_wav.is_file():
        tail = (p.stderr or p.stdout or "")[-500:]
        raise RuntimeError("RVC 换声失败:\n%s" % tail)


# ---------------------------------------------------------------- 端到端任务
E2E_LOCK = threading.Lock()
E2E = {"state": "idle", "role": "", "video": "", "out": "", "log": "",
       "t_start": 0.0, "t_end": 0.0}


def e2e_start(role, video_path: Path):
    with E2E_LOCK:
        if E2E["state"] == "running":
            return False, "已有端到端任务在跑，请等它结束"
        E2E.update(state="running", role=role, video=str(video_path), out="",
                   log="", t_start=time.time(), t_end=0.0)
        threading.Thread(target=_e2e_worker, args=(role, video_path), daemon=True).start()
        return True, "已开始"


def _e2e_worker(role, video_path: Path):
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        with open(E2E_LOG, "w", encoding="utf-8", errors="replace") as f:
            p = subprocess.run(
                [str(DIR_E2E / "runtime" / "py312" / "python.exe"),
                 "e2e_test.py", str(video_path), role],
                cwd=str(DIR_E2E), env=env, stdout=f, stderr=subprocess.STDOUT)
        E2E["state"] = "done" if p.returncode == 0 else "failed"
    except Exception as e:
        E2E["state"] = "failed"
        try:
            with open(E2E_LOG, "a", encoding="utf-8", errors="replace") as f:
                f.write("\n[总控] 调度异常: %r" % e)
        except Exception:
            pass
    finally:
        E2E["t_end"] = time.time()
        out = DIR_E2E / "输出" / ("输出_%s.mp4" % role)
        E2E["out"] = str(out) if out.is_file() else ""
        try:
            E2E["log"] = E2E_LOG.read_text(encoding="utf-8", errors="replace")[-2000:]
        except Exception:
            pass


# ---------------------------------------------------------------- HTTP 服务
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
                 ".ico": "image/x-icon", ".wav": "audio/wav", ".mp4": "video/mp4",
                 ".json": "application/json; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args), flush=True)

    # -- 基础输出 --
    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data: bytes, ctype: str, filename: str = ""):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s"
                             % urllib.parse.quote(filename))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path, download_name=""):
        if not path.is_file():
            return self.send_json({"error": "文件不存在: %s" % path}, 404)
        self.send_bytes(path.read_bytes(),
                        CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                        download_name)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise RuntimeError("上传内容超过 %dMB 上限" % (MAX_BODY // 1024 // 1024))
        remain, chunks = n, []
        while remain > 0:
            chunk = self.rfile.read(min(remain, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remain -= len(chunk)
        return b"".join(chunks)

    # -- 路由 --
    def do_GET(self):
        try:
            self.route_get()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.send_json({"error": repr(e)}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            self.route_post()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.send_json({"error": repr(e)}, 500)
            except Exception:
                pass

    def route_get(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send_file(STATIC_DIR / "index.html")
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            if "/" in name or ".." in name:
                return self.send_json({"error": "bad path"}, 400)
            return self.send_file(STATIC_DIR / name)

        if path == "/api/status":
            return self.send_json(service_status())

        if path == "/api/svc/models":
            _, data, _ = fetch(SVC_URL + "/models", timeout=15)
            return self.send_bytes(data, CONTENT_TYPES[".json"])

        if path == "/api/tts/roles":
            return self.send_json(tts_roles())

        if path == "/api/rvc/roles":
            return self.send_json(rvc_roles())

        if path == "/api/e2e/status":
            info = dict(E2E)
            info["elapsed"] = round((E2E["t_end"] or time.time()) - E2E["t_start"], 1) \
                if E2E["t_start"] else 0
            info["default_video"] = str((DIR_E2E / "testdata" / "输入.mp4"))
            return self.send_json(info)

        if path == "/api/e2e/video":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            role = (q.get("role") or [""])[0] or E2E.get("role") or "furina"
            out = DIR_E2E / "输出" / ("输出_%s.mp4" % role)
            return self.send_file(out, download_name="输出_%s.mp4" % role)

        self.send_json({"error": "no route: %s" % path}, 404)

    def route_post(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/svc/change":
            body = self.read_body()
            fields, files = parse_multipart(body, self.headers.get("Content-Type", ""))
            if "audio" not in files:
                return self.send_json({"error": "没收到音频文件"}, 400)
            fname, fdata = files["audio"]
            up, ctype = build_multipart(
                {"model": fields.get("model", "furina"),
                 "transpose": fields.get("transpose", "0"),
                 "auto_f0": fields.get("auto_f0", "1"),
                 "cluster_ratio": "0"},
                "audio", fname or "input.wav", fdata)
            st, data, _ = fetch(SVC_URL + "/svc/change_voice", data=up,
                                headers={"Content-Type": ctype}, timeout=1800)
            if st != 200:
                return self.send_json({"error": "换声失败 %d: %s"
                                       % (st, data.decode("utf-8", "replace")[:300])}, 502)
            role = fields.get("model", "furina")
            return self.send_bytes(data, "audio/wav", filename="换声_%s.wav" % role)

        if path == "/api/tts":
            body = self.read_body()
            req = json.loads(body.decode("utf-8") or "{}")
            text = (req.get("text") or "").strip()
            if not text:
                return self.send_json({"error": "要合成的文本不能为空"}, 400)
            data = tts_synthesize(req.get("role", ""), text)
            return self.send_bytes(data, "audio/wav", filename="语音_合成.wav")

        if path == "/api/rvc/convert":
            body = self.read_body()
            fields, files = parse_multipart(body, self.headers.get("Content-Type", ""))
            if "audio" not in files:
                return self.send_json({"error": "没收到音频文件"}, 400)
            fname, fdata = files["audio"]
            weight = fields.get("weight", "")
            if weight not in rvc_roles():
                return self.send_json({"error": "音色 %s 不在 1-rvc\\assets\\weights" % weight}, 400)
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            in_wav = UPLOAD_DIR / ("rvc_in_%d.wav" % int(time.time() * 1000))
            out_wav = UPLOAD_DIR / ("rvc_out_%d.wav" % int(time.time() * 1000))
            in_wav.write_bytes(fdata)
            try:
                rvc_convert(in_wav, weight, out_wav)
            finally:
                in_wav.unlink(missing_ok=True)
            return self.send_file(out_wav, download_name="RVC_%s.wav" % Path(weight).stem)

        if path == "/api/e2e/run":
            body = self.read_body()
            fields, files = parse_multipart(body, self.headers.get("Content-Type", "")) \
                if "multipart" in self.headers.get("Content-Type", "") \
                else ({}, {})
            role = fields.get("role", "furina")
            # 角色必须是 6843 真实存在的，避免白跑几分钟
            _, mdata, _ = fetch(SVC_URL + "/models", timeout=15)
            names = json.loads(mdata.decode("utf-8", "replace"))
            if names and role not in names:
                return self.send_json({"error": "角色 %s 不在 6843 的角色表 %s 里" % (role, names)}, 400)
            if "video" in files:
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                fname, fdata = files["video"]
                suffix = Path(fname or "input.mp4").suffix or ".mp4"
                video = UPLOAD_DIR / ("e2e_%d%s" % (int(time.time() * 1000), suffix))
                video.write_bytes(fdata)
            else:
                video = DIR_E2E / "testdata" / "输入.mp4"
                if not video.is_file():
                    return self.send_json({"error": "没上传视频且 testdata\\输入.mp4 不存在"}, 400)
            ok, msg = e2e_start(role, video)
            return self.send_json({"ok": ok, "msg": msg}, 200 if ok else 409)

        self.send_json({"error": "no route: %s" % path}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-a", "--host", default="127.0.0.1")
    ap.add_argument("-p", "--port", type=int, default=8100)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("总控页服务 http://%s:%d  （对应 1-rvc / 2-gpt-sovits / 3-so-vits-svc / 4-e2e）"
          % (args.host, args.port), flush=True)
    print("上游：%s / %s / %s" % (SVC_URL, TTS_URL, RVC_URL), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
