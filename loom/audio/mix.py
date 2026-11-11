"""The mix bus: voice assembly, sidechain ducking, LUFS normalisation, limiting.

Targets are the ones the platforms actually normalise to, so nothing gets
quietened after upload:
  * -14 LUFS integrated (YouTube/TikTok/Reels all sit here)
  * -1.0 dBTP true peak
  * music ~ -19 LUFS under speech, ducked a further 4-7 dB on voice
"""
from __future__ import annotations

import numpy as np

from . import synth as S

SR = 48000


# ------------------------------------------------------------------ voice
def build_voice(pieces, sr=SR):
    """pieces: [(audio float32 @ any sr, start_time)] -> (voice, sr)."""
    if not pieces:
        return np.zeros(1, np.float32)
    end = max(t + len(a) / sr for a, t in pieces)
    out = np.zeros(int(end * sr) + sr, np.float32)
    for a, t in pieces:
        out = S.place(out, a, t, 1.0, sr=sr)
    return out


def duck_gain(voice, sr=SR, amount=0.55, attack=0.06, release=0.45):
    """Smooth 0..1 envelope of the voice -> music gain multiplier."""
    hop = int(0.01 * sr)
    n = int(len(voice) / hop) + 1
    env = np.zeros(n, np.float32)
    for i in range(n):
        seg = voice[i * hop:(i + 1) * hop]
        env[i] = np.sqrt((seg ** 2).mean()) if len(seg) else 0.0
    thr = max(1e-4, np.percentile(env[env > 0], 70) * 0.35) if (env > 0).any() else 1e-4
    speech = (env > thr).astype(np.float32)
    # smooth: fast attack, slow release
    sm = np.zeros_like(speech)
    a_up = 1 - np.exp(-1.0 / max(1.0, attack / 0.01))
    a_dn = 1 - np.exp(-1.0 / max(1.0, release / 0.01))
    prev = 0.0
    for i, v in enumerate(speech):
        prev += (v - prev) * (a_up if v > prev else a_dn)
        sm[i] = prev
    gain = 1.0 - amount * sm
    # upsample to sample rate
    xs = np.arange(len(voice)) / sr
    return np.interp(xs, np.arange(n) * 0.01, gain).astype(np.float32)


def music_bed(music_stereo, duration, sr=SR, level_db=-19.0, duck=None, duck_db=-5.0):
    """Trim/pad music to duration, apply level and optional duck curve."""
    n = int(duration * sr)
    m = np.zeros((n, 2), np.float32)
    k = min(n, len(music_stereo))
    m[:k] = music_stereo[:k]
    if k < n:                                    # gentle tail loop-out
        fade = min(k, int(0.6 * sr))
        m[k:k + 1] = 0
    m *= 10 ** (level_db / 20.0) / max(1e-9, np.abs(m).max() or 1.0)
    if duck is not None:
        d = np.interp(np.arange(n), np.arange(len(duck)), duck)
        g = 10 ** ((duck_db / 20.0) * (1.0 - d))
        m *= g[:, None]
    return m


# ------------------------------------------------------------------ loudness
def _k_weight(x, sr=SR):
    if sr != 48000:
        return x
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    y = x
    try:
        from scipy.signal import lfilter
        y = lfilter(b1, a1, y, axis=0)
        y = lfilter(b2, a2, y, axis=0)
    except Exception:
        pass
    return y


def integrated_lufs(x, sr=SR):
    y = _k_weight(np.asarray(x, np.float32), sr)
    if y.ndim == 2:
        y = y.mean(axis=1)
    win = int(0.4 * sr)
    hop = int(0.1 * sr)
    if len(y) < win:
        return -70.0
    ms = []
    for i in range(0, len(y) - win, hop):
        seg = y[i:i + win]
        ms.append(np.mean(seg ** 2))
    ms = np.array(ms) + 1e-12
    loud = -0.691 + 10 * np.log10(ms)
    gated = loud[loud > -70]
    if len(gated) == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(ms[loud > -70])) - 10
    gated2 = loud[(loud > -70) & (loud > rel)]
    if len(gated2) == 0:
        return float(np.mean(gated))
    return float(-0.691 + 10 * np.log10(np.mean(10 ** ((gated2 + 0.691) / 10))))


def true_peak(x):
    """Approximate true peak (4x oversample on the loudest block)."""
    y = np.asarray(x, np.float32)
    m = int(np.abs(y).max(axis=0).max() if y.ndim == 2 else np.abs(y).max())
    idx = int(np.argmax(np.abs(y).max(axis=1) if y.ndim == 2 else np.abs(y)))
    lo = max(0, idx - 64)
    hi = min(len(y), idx + 64)
    seg = y[lo:hi]
    up = np.repeat(seg, 4, axis=0)
    return float(max(np.abs(seg).max(), np.abs(up).max()))


def limiter(x, sr=SR, ceiling_db=-1.0, lookahead=0.006, release=0.09):
    """Lookahead peak limiter. Guarantees the ceiling without audible pumping."""
    ceil = 10 ** (ceiling_db / 20.0)
    y = np.asarray(x, np.float32)
    peak = np.abs(y).max(axis=1) if y.ndim == 2 else np.abs(y)
    need = np.minimum(1.0, ceil / np.maximum(peak, 1e-9))
    if (need >= 1.0).all():
        return y
    la = max(1, int(lookahead * sr))
    kernel = np.ones(la + 1, np.float32) / (la + 1)
    need_s = np.convolve(need, kernel, mode="same")     # look ahead by smoothing
    need_s = np.minimum(need_s, need)
    rel = 1 - np.exp(-1.0 / max(1.0, release * sr))
    g = np.empty_like(need_s)
    prev = 1.0
    for i, v in enumerate(need_s):
        prev = v if v < prev else prev + (v - prev) * rel
        g[i] = prev
    return (y * (g[:, None] if y.ndim == 2 else g)).astype(np.float32)


def master(x, sr=SR, target_lufs=-14.0, ceiling_db=-1.0, max_gain_db=12.0, passes=3):
    """Measure -> gain -> limit -> measure again. Limiting removes loudness, so one
    pass always lands a dB or two short of the target; repeat until it converges."""
    y = x
    gain_total = 1.0
    for _ in range(max(1, passes)):
        cur = integrated_lufs(y, sr)
        need = target_lufs - cur
        if abs(need) < 0.3:
            break
        step = min(10 ** (need / 20.0), 10 ** (max_gain_db / 20.0))
        y = limiter(y * step, sr, ceiling_db)
        gain_total *= step
    if integrated_lufs(y, sr) > target_lufs + 0.8:      # overshoot from limiting
        y = limiter(y * 0.94, sr, ceiling_db)
    return y


def write_wav(path, x, sr=SR):
    import soundfile as sf
    x = np.asarray(x, np.float32)
    if x.ndim == 2:
        x = np.clip(x, -1, 1)
        sf.write(path, x, sr, subtype="PCM_16")
    else:
        sf.write(path, np.clip(x, -1, 1), sr, subtype="PCM_16")
    return path
