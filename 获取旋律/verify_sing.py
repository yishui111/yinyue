"""T17 演唱合成的独立验证：提交→轮询→失败自动重试（应对被外部清理的机器环境）。

跑法: .venv\\Scripts\\python verify_sing.py
"""
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
BASE = "http://127.0.0.1:17865"
S = requests.Session()
S.trust_env = False

# 测试旋律名（test_suite 导入失败时会留不下，则改用内置示例）
MELODY = "回归测试旋律"


def wait_server(timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if S.get(BASE + "/", timeout=5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def main():
    if not wait_server(300):
        print("服务 5 分钟内未上线（看门狗可能也被清理）——请双击 启动工作台.bat 后重试")
        return 1
    global MELODY
    names = [m["name"] for m in S.get(BASE + "/api/melodies", timeout=10).json()]
    if MELODY not in names:
        MELODY = next((n for n in names if "小星星" in n), names[0] if names else None)
    if not MELODY:
        print("曲库为空")
        return 1
    print("用旋律:", MELODY)

    for attempt in range(1, 4):
        print(f"--- 第 {attempt}/3 轮提交 ---")
        r = S.post(BASE + "/api/sing", json={
            "name": MELODY, "voice": "mock",
            "url": "http://127.0.0.1:18767", "limit_seconds": 15}, timeout=30)
        if r.status_code != 200:
            print("提交失败:", r.text[:120])
            time.sleep(20)
            continue
        jr = r.json()
        t0 = time.time()
        done, error = False, None
        while time.time() - t0 < 420:
            try:
                j = S.get(f"{BASE}/api/progress/{jr['job_id']}", timeout=10).json()
                if j.get("done"):
                    done, error = True, j.get("error")
                    break
                if j.get("detail"):
                    print("  ", j["detail"][:60], flush=True)
            except Exception:
                pass
            time.sleep(5)
        if done and not error:
            f = S.get(BASE + jr["file"], timeout=30)
            print(f"PASS ✓ 演唱合成成功: {jr['file']} ({len(f.content)} bytes)")
            return 0
        print("本轮失败:", (error or "超时")[:150])
        time.sleep(30)
    print("3 轮均被环境打断——请在机器空闲（其他 AI 程序/安装结束）后重跑 test_suite.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
