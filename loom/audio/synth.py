"""A very small synth toolkit: oscillators, envelopes, filters, reverb.

Everything is numpy, so a full score renders in a second or two and the skill
needs no audio API, no sample pack and no licensing questions.
"""
from __future__ import annotations

import numpy as np

SR = 48000


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12.0)


def _t(dur, sr=SR):
    return np.arange(int(dur * sr), dtype=np.float32) / sr


def adsr(n, sr, a=0.01, d=0.12, s=0.6, r=0.2, curve=2.0):
    a_n, d_n, r_n = int(a * sr), int(d * sr), int(r * sr)
    a_n = max(1, min(a_n, n))
    env = np.zeros(n, np.float32)
    env[:a_n] = np.linspace(0, 1, a_n) ** (1 / curve)
    d_n = min(d_n, max(0, n - a_n))
    if d_n:
        env[a_n:a_n + d_n] = 1 + (s - 1) * np.linspace(0, 1, d_n) ** curve
    rest = n - a_n - d_n
    if rest > 0:
        env[a_n + d_n:] = s
    if r_n and r_n < n:
        env[-r_n:] *= np.linspace(1, 0, r_n) ** curve
    return env


def osc(freq, dur, sr=SR, kind="sine", detune=0.0, phase=0.0):
    n = int(dur * sr)
    t = np.arange(n, dtype=np.float32) / sr
    f = freq * (1.0 + detune)
    ph = 2 * np.pi * (f * t + phase)
    if kind == "sine":
        return np.sin(ph).astype(np.float32)
    if kind == "tri":
        return (2 / np.pi * np.arcsin(np.sin(ph))).astype(np.float32)
    if kind == "saw":
        return (2 * ((f * t + phase) % 1.0) - 1.0).astype(np.float32)
    if kind == "square":
        return np.sign(np.sin(ph)).astype(np.float32) * 0.8
    raise ValueError(kind)


def noise(dur, sr=SR, seed=0, pink=False):
    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    w = rng.standard_normal(n).astype(np.float32)
    if pink:
        # 1/f via cascaded one-pole smoothing
        w = lowpass(w, 900, sr) * 0.7 + lowpass(w, 240, sr) * 0.5
        w /= max(1e-6, np.abs(w).max())
    return w


def _coeffs(mode, fc, sr, q):
    w0 = 2 * np.pi * min(fc, sr * 0.45) / sr
    alpha = np.sin(w0) / (2 * q)
    cw = np.cos(w0)
    if mode == "low":
        b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
    elif mode == "high":
        b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
    else:
        b0, b1, b2 = alpha, 0.0, -alpha
    a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
    return (b0 / a0, b1 / a0, b2 / a0), (1.0, a1 / a0, a2 / a0)


try:                                     # fast path
    from scipy.signal import lfilter as _lfilter
except Exception:
    _lfilter = None


def _apply(x, b, a):
    if _lfilter is not None:
        return _lfilter(b, a, x).astype(np.float32)
    # numpy fallback: frequency-domain filtering
    n = len(x) + 4096
    N = 1 << (n - 1).bit_length()
    w = 2 * np.pi * np.fft.rfftfreq(N)
    z1 = np.exp(-1j * w)
    H = (b[0] + b[1] * z1 + b[2] * z1 ** 2) / (a[0] + a[1] * z1 + a[2] * z1 ** 2)
    y = np.fft.irfft(np.fft.rfft(x, N) * H, N)[:len(x)]
    return y.astype(np.float32)


def biquad(x, mode="low", fc=1000.0, sr=SR, q=0.707, passes=1):
    """RBJ biquad, applied `passes` times. Uses scipy when present."""
    y = np.asarray(x, np.float32)
    b, a = _coeffs(mode, fc, sr, q)
    for _ in range(passes):
        y = _apply(y, b, a)
    return y


def lowpass(x, cutoff, sr=SR, order=1):
    return biquad(x, "low", cutoff, sr, 0.707, max(1, order))


def lpf(x, cutoff, sr=SR, resonance=0.7, passes=2):
    return biquad(x, "low", cutoff, sr, resonance, passes)


def hpf(x, cutoff, sr=SR, resonance=0.7, passes=1):
    return biquad(x, "high", cutoff, sr, resonance, passes)


def bandpass(x, lo, hi, sr=SR, passes=2):
    return biquad(biquad(x, "high", lo, sr, 0.707), "low", hi, sr, 0.707, passes)


def sweep_lpf(x, f0, f1, sr=SR, q=0.7, blocks=32):
    """Time-varying low-pass, block-wise (cheap, smooth enough)."""
    n = len(x)
    out = np.empty(n, np.float32)
    bs = max(64, n // blocks)
    for i in range(0, n, bs):
        k = i / max(1, n - 1)
        fc = f0 * (f1 / f0) ** k
        seg = biquad(x[i:i + bs], "low", fc, sr, q)
        out[i:i + bs] = seg
    return out


def make_ir(dur=2.4, sr=SR, decay=3.2, damp=5200, seed=5, stereo=True):
    """Synthetic impulse response: decaying, damped noise + a few early reflections."""
    n = int(dur * sr)
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    env = np.exp(-decay * t).astype(np.float32)
    ir = rng.standard_normal(n).astype(np.float32) * env
    ir = biquad(ir, "low", damp, sr, 0.7)
    for k, (dt, g) in enumerate([(0.011, 0.5), (0.019, 0.4), (0.031, 0.3), (0.047, 0.22)]):
        i = int(dt * sr)
        if i < n:
            ir[i] += g
    ir[:32] *= 0.1
    ir /= max(1e-6, np.abs(ir).max())
    return ir


def convolve(x, ir):
    """FFT convolution (numpy only), returns same length as x + tail."""
    n = len(x) + len(ir) - 1
    N = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(ir, N), N)[:n]
    return y.astype(np.float32)


def reverb(x, sr=SR, amount=0.3, dur=2.2, decay=3.0, damp=5000, seed=5, width=0.8):
    ir = make_ir(dur, sr, decay, damp, seed)
    wet = convolve(x, ir)
    wet /= max(1e-6, np.abs(wet).max())
    dry = np.zeros_like(wet)
    dry[:len(x)] = x
    return (dry * (1 - amount * 0.4) + wet * amount).astype(np.float32)


def delay(x, sr=SR, time=0.28, fb=0.32, mix=0.25, pingpong=False):
    d = int(time * sr)
    y = x.copy()
    buf = np.zeros(len(x) + d * 8, np.float32)
    buf[:len(x)] = x
    for k in range(1, 7):
        idx = k * d
        if idx >= len(buf):
            break
        buf[idx:] += x[:len(buf) - idx] * (fb ** k) * mix
    return buf[:len(x)]


def place(dest, src, at, gain=1.0, sr=SR):
    """Mix src into dest (mono or stereo) at time `at` seconds."""
    i = int(at * sr)
    if i >= dest.shape[0]:
        return dest
    n = min(len(src), dest.shape[0] - i)
    if src.ndim == 1:
        if dest.ndim == 2:
            dest[i:i + n] += (src[:n] * gain)[:, None]
        else:
            dest[i:i + n] += src[:n] * gain
    else:
        if dest.ndim == 1:
            dest[i:i + n] += (src[:n].mean(axis=1) * gain)
        else:
            dest[i:i + n] += src[:n] * gain
    return dest


def stereo(x, width=0.5, seed=0):
    """Mono -> stereo with a touch of decorrelation (Haas + gain)."""
    d = int(0.006 * SR)
    left = x
    right = np.concatenate([np.zeros(d, np.float32), x[:-d]]) * (1 - width * 0.2)
    return np.stack([left, right], axis=1).astype(np.float32)


def normalize(x, peak=0.9):
    m = np.abs(x).max()
    return x if m < 1e-9 else (x / m * peak).astype(np.float32)


def fade(x, sr=SR, fin=0.02, fout=0.05):
    y = x.copy()
    a = int(fin * sr)
    b = int(fout * sr)
    if a:
        y[:a] *= np.linspace(0, 1, a)[:, None] if y.ndim == 2 else np.linspace(0, 1, a)
    if b:
        ramp = np.linspace(1, 0, b)
        if y.ndim == 2:
            y[-b:] *= ramp[:, None]
        else:
            y[-b:] *= ramp
    return y
