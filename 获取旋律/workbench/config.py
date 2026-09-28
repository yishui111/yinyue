"""全局配置：读/写项目根目录的 config.json"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",
    "whisper_model": "small",
    "whisper_language": "zh",
    "separate_vocals": True,
    # 演唱合成（GPT-SoVITS）
    "gptsovits_mode": "panel",            # panel=你的控制页(8550) / apiv2=直连官方API
    "gptsovits_url": "http://127.0.0.1:8550",
    "gptsovits_dir": "",                  # 你的 GPT-SoVITS 项目目录（看门狗守护控制页用）
    "gptsovits_voice": "",                # panel 模式：控制页里导入的音色名
    "gptsovits_ref_audio": "",            # apiv2 模式：参考音频绝对路径
    "gptsovits_prompt_text": "",
    "gptsovits_prompt_lang": "zh",
}


def load():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(update: dict):
    cfg = load()
    cfg.update({k: v for k, v in update.items() if v not in (None, "")})
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg
