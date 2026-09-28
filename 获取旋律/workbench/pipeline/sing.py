"""用 GPT-SoVITS 把「保留的旋律 + 新词」真正唱出来。

原理：逐字 TTS 得到每个字的语音 → 修剪静音 → 变调到该音符的目标音高 →
时长拉伸对齐音符时值 → 按音符起始时间拼进整首歌的音轨。

支持两种后端（config.json 的 sing 段）：
- mode="panel"：用户已有的 GPT-SoVITS 控制页（POST {url}/api/tts，
  {"voice","text","speed"} → {"wav": base64}），音色=控制页里导入的声音模型
  （用原曲人声训练的模型即"原唱声"，换别的模型即"换人唱"）。
- mode="apiv2"：直连官方 api_v2（POST {url}/tts，json，返回原始 wav），
  需提供 ref_audio_path / prompt_text。
"""
import base64
import hashlib
import io
import json
import time
import wave

import numpy as np
import requests

from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "tts_cache"
CACHE_DIR.mkdir(exist_ok=True)

_SKIP_CHARS = set("—-")


def _tts_char(text, sing, cache):
    """调 GPT-SoVITS 合成单个字，返回 (float32 mono, sr)。带内存与磁盘缓存。"""
    if text in cache:
        return cache[text]
    # 持久缓存：同一音色+同一字的合成结果跨任务复用
    key = hashlib.sha1(json.dumps(
        [sing.get("mode"), sing.get("url"), sing.get("voice") or sing.get("ref_audio"), text],
        ensure_ascii=False).encode("utf-8")).hexdigest()[:20]
    cache_file = CACHE_DIR / (key + ".wav")
    if cache_file.exists():
        import soundfile as sf
        y, sr = sf.read(str(cache_file), dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        cache[text] = (y, sr)
        return y, sr

    # 127.0.0.1 必须绕过系统代理（这台机器配了全局代理，会被截走）
    proxies = {"http": None, "https": None}
    if sing.get("mode", "panel") == "panel":
        r = requests.post(
            sing["url"].rstrip("/") + "/api/tts",
            json={"voice": sing.get("voice", ""), "text": text, "speed": 1.0},
            proxies=proxies, timeout=600)  # 首次调用要等 api_v2 加载权重，留足超时
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"GPT-SoVITS 返回错误：{data['error']}")
        wav_bytes = base64.b64decode(data["wav"])
    else:
        r = requests.post(
            sing["url"].rstrip("/") + "/tts",
            json={"text": text, "text_lang": "zh",
                  "ref_audio_path": sing.get("ref_audio", ""),
                  "prompt_text": sing.get("prompt_text", ""),
                  "prompt_lang": sing.get("prompt_lang", "zh"),
                  "media_type": "wav", "streaming_mode": False},
            proxies=proxies, timeout=120)
        r.raise_for_status()
        wav_bytes = r.content

    cache_file.write_bytes(wav_bytes)
    import soundfile as sf
    y, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    cache[text] = (y, sr)
    return y, sr

    import soundfile as sf
    y, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    cache[text] = (y, sr)
    return y, sr


def _trim(y, sr, top_db=40):
    import librosa
    yt, _ = librosa.effects.trim(y, top_db=top_db)
    return yt if len(yt) > 32 else y


def _to_note(y, sr, midi, duration, fmin=80.0, fmax=600.0):
    """把一个字的语音变成：目标音高 + 目标时长。"""
    import librosa
    y = _trim(y, sr)

    # 时长对齐
    target_n = max(int(duration * sr), int(0.08 * sr))
    if len(y) > 64 and target_n > 64:
        rate = len(y) / target_n
        if 0.25 < rate < 4.0:
            try:
                y = librosa.effects.time_stretch(y, rate=rate)
            except Exception:
                pass
    if len(y) > target_n:
        y = y[:target_n]

    # 音高对齐：测当前基频中位数，整体变调到目标 midi
    try:
        if len(y) >= 512:
            f0 = librosa.yin(y, fmin=fmin, fmax=fmax, sr=sr,
                             frame_length=1024 if len(y) >= 1024 else 512)
            f0 = f0[np.isfinite(f0) & (f0 > 0)]
            if len(f0):
                cur_midi = float(librosa.hz_to_midi(float(np.median(f0))))
                steps = float(midi) - cur_midi
                if 0.3 < abs(steps) < 24:
                    y = librosa.effects.pitch_shift(y, sr=sr, n_steps=steps)
    except Exception:
        pass

    # 首尾淡入淡出，避免拼接爆音
    n = len(y)
    if n > 64:
        fade_in = int(0.012 * sr)
        fade_out = int(0.04 * sr)
        env = np.ones(n)
        env[:fade_in] = np.linspace(0, 1, fade_in)
        env[-fade_out:] = np.linspace(1, 0, fade_out)
        y = y * env
    return y


def _collect_notes(song):
    out = []
    for ln in song["lines"]:
        for n in ln["notes"]:
            ch = (n.get("new_char") or n.get("char") or "").strip()
            if n.get("midi") is None or not ch or ch in _SKIP_CHARS:
                continue
            out.append((float(n["start"]), float(n["duration"]), int(n["midi"]), ch))
    out.sort(key=lambda x: x[0])
    return out


def synth_song(song_json_path, out_path, sing, progress=None, limit_seconds=0):
    import json
    import wave as wavemod

    import soundfile as sf

    song = json.loads(open(str(song_json_path), encoding="utf-8").read())
    # 容错：手写/外部来源的旋律文件可能缺 start 与简谱，先规范化
    from workbench import melodylib
    melodylib.recompute(song)
    notes = _collect_notes(song)

    def report(msg):
        if progress:
            try:
                progress("sing", msg)
            except Exception:
                pass

    if limit_seconds and limit_seconds > 0:
        notes = [n for n in notes if n[0] < float(limit_seconds)]
        report(f"快速试听模式：只合成前 {limit_seconds} 秒（{len(notes)} 个音）")
    if not notes:
        raise RuntimeError("没有可演唱的音符（请先填词：每个音符至少要有字）")

    report(f"待合成 {len(notes)} 个音，逐字调用 GPT-SoVITS…")
    cache = {}
    sr = None
    total_end = max(s + d for s, d, _, _ in notes) + 1.0
    buf = None

    for i, (start, dur, midi, ch) in enumerate(notes):
        y, clip_sr = None, None
        last_err = None
        for attempt in range(3):  # 外部环境偶发清理进程，单字失败自动重试
            try:
                y, clip_sr = _tts_char(ch, sing, cache)
                break
            except Exception as e:
                last_err = e
                report(f"「{ch}」第 {attempt + 1}/3 次合成失败：{e}")
                time.sleep(5 + attempt * 10)
        if y is None:
            raise RuntimeError(f"「{ch}」连续 3 次合成失败：{last_err}")
        if sr is None:
            sr = clip_sr
            buf = np.zeros(int(total_end * sr) + sr, dtype=np.float32)
        elif clip_sr != sr:
            import librosa
            y = librosa.resample(y, orig_sr=clip_sr, target_sr=sr)
        y = _to_note(y, sr, midi, dur)
        i0 = int(start * sr)
        end = min(i0 + len(y), len(buf))
        buf[i0:end] += y[:end - i0]
        if i % 10 == 0 or i == len(notes) - 1:
            report(f"已合成 {i + 1}/{len(notes)} 音（{ch}）")

    peak = float(np.max(np.abs(buf)))
    if peak > 0:
        buf = buf / peak * 0.89
    sf.write(str(out_path), buf, sr, subtype="PCM_16")
    report(f"演唱合成完成：{out_path}")
    return str(out_path)
