"""Local text-to-speech (Kokoro, Apache-2.0) with a disk cache.

Voices are listed with plain-English character notes so the agent can pick one
for a story without listening to 50 samples.
"""
from __future__ import annotations

import hashlib
import os
import wave

import numpy as np

MODEL_DIR = os.environ.get("LOOM_MODEL_DIR", os.path.expanduser("~/.cache/loom/models"))
SR = 24000

VOICES = {
    # American
    "am_michael": "warm American male, steady, documentary narrator (default)",
    "am_onyx": "deep American male, slow and heavy, true-crime",
    "am_fenrir": "low American male, gravelly, menacing",
    "am_puck": "bright American male, energetic, explainer",
    "am_echo": "neutral American male, news-anchor clean",
    "af_heart": "soft American female, intimate, ASMR-adjacent",
    "af_bella": "warm American female, conversational, fast-paced explainer",
    "af_nicole": "low American female, calm, unsettling",
    "af_sarah": "clear American female, friendly teacher",
    # British
    "bm_george": "British male, literary, measured (great for horror)",
    "bm_fable": "British male, storyteller, slightly wry",
    "bf_emma": "British female, crisp, documentary",
    "bf_isabella": "British female, soft and eerie",
}

DEFAULT_SPEED = {"nightline": 0.94, "lamplit": 1.02, "blueprint": 1.06,
                 "sunlit": 1.10, "stickman": 1.04}


def _cache_dir():
    d = os.path.join(MODEL_DIR, "..", "tts")
    os.makedirs(d, exist_ok=True)
    return d


def model_paths():
    onnx = os.path.join(MODEL_DIR, "kokoro-v1.0.onnx")
    voices = os.path.join(MODEL_DIR, "voices-v1.0.bin")
    return onnx, voices


_K = None


def _kokoro():
    global _K
    if _K is None:
        from kokoro_onnx import Kokoro
        onnx, voices = model_paths()
        if not os.path.exists(onnx):
            raise SystemExit("Kokoro model missing. Run: bash scripts/setup.sh --voice")
        _K = Kokoro(onnx, voices)
    return _K


def list_voices():
    return [f"{k:<12} {v}" for k, v in VOICES.items()]


def synthesize(text: str, voice="am_michael", speed=1.0, lang="en-us", cache=True):
    """Return float32 mono audio at 24 kHz."""
    key = hashlib.sha1(f"{voice}|{speed}|{lang}|{text}".encode()).hexdigest()[:16]
    path = os.path.join(_cache_dir(), key + ".wav")
    if cache and os.path.exists(path):
        with wave.open(path) as w:
            return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    k = _kokoro()
    samples, sr = k.create(text, voice=voice, speed=speed, lang=lang)
    a = np.asarray(samples, np.float32)
    if sr != SR:
        a = resample(a, sr, SR)
    if cache:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    return a


def resample(a, sr_from, sr_to):
    if sr_from == sr_to:
        return a
    n = int(round(len(a) * sr_to / sr_from))
    x_new = np.linspace(0, len(a) - 1, n)
    return np.interp(x_new, np.arange(len(a)), a).astype(np.float32)


def trim_silence(a, thresh_db=-42.0, pad=0.05):
    """Trim leading/trailing silence; returns (audio, lead_trim, tail_trim)."""
    hop = 256
    n = len(a) // hop
    if n < 2:
        return a, 0.0, 0.0
    frames = a[: n * hop].reshape(n, hop)
    rms = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    idx = np.where(rms > thresh_db)[0]
    if len(idx) == 0:
        return a, 0.0, 0.0
    pad_n = int(pad * SR)
    start = max(0, idx[0] * hop - pad_n)
    end = min(len(a), (idx[-1] + 1) * hop + pad_n)
    return a[start:end], start / SR, (len(a) - end) / SR
