"""Sound design library. Small, phone-speaker-safe sounds only.

Hard rule that comes from how these videos are watched: nothing harsh. No
clicks, ticks, beeps, hats or high square blips — a phone speaker turns them
into a hiss that sounds like a broken file. Everything here is filtered below
~9 kHz and has at least a 4 ms attack.
"""
from __future__ import annotations

import numpy as np

from . import synth as S

SR = S.SR


def whoosh(dur=0.5, amp=0.5, seed=1, up=True):
    x = S.noise(dur, seed=seed, pink=True)
    x = S.sweep_lpf(x, 340 if up else 2600, 2600 if up else 340, q=1.2, blocks=26)
    n = len(x)
    env = np.sin(np.linspace(0, np.pi, n)) ** 1.4
    return S.fade((x * env * amp).astype(np.float32), fin=0.02, fout=0.04)


def impact(dur=1.4, amp=0.6, seed=2):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 46 * (1 + 1.1 * np.exp(-t * 22))
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.2)
    body = S.biquad(S.noise(dur, seed=seed), "low", 260, q=0.9) * np.exp(-t * 9) * 0.6
    out = (sub + body) * amp
    out[:int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    return out.astype(np.float32)


def riser(dur=2.0, amp=0.4, seed=3, f0=260, f1=5200):
    n = int(dur * SR)
    x = S.noise(dur, seed=seed, pink=True)
    x = S.sweep_lpf(x, f0, f1, q=1.1, blocks=48)
    env = (np.linspace(0, 1, n) ** 2.4)
    return S.fade((x * env * amp).astype(np.float32), fin=0.05, fout=0.03)


def reverse_swell(dur=1.2, amp=0.35, seed=4):
    x = riser(dur, amp, seed, 200, 3400)
    return x[::-1].copy()


def thud(dur=0.6, amp=0.5, seed=5):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 92 * (1 + 0.7 * np.exp(-t * 30))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 12)
    knock = S.biquad(S.noise(0.12, seed=seed), "band", 320, q=1.4) * np.exp(-t[:int(0.12 * SR)] * 30) * 0.4
    out = body * amp
    out[:len(knock)] += knock * amp
    return out.astype(np.float32)


def door(dur=1.1, amp=0.4, seed=6, close=True):
    """Creak / latch: filtered noise sweep + low knock."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    creak = S.noise(dur, seed=seed, pink=True)
    creak = S.biquad(creak, "band", 700, q=6.0) * (0.4 + -0.4 * np.cos(np.pi * t / dur)) * 0.7
    out = creak * amp
    if close:
        k = thud(0.4, amp * 1.1, seed + 1)
        out = S.place(out, k, dur * 0.55)
    return out.astype(np.float32)


def phone(dur=0.9, amp=0.35, seed=7):
    """Old handset ring, softened."""
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    for i in range(3):
        tone = S.osc(440.0, 0.16, kind="sine") * 0.5 + S.osc(480.0, 0.16, kind="sine") * 0.4
        tone *= S.adsr(len(tone), SR, 0.008, 0.02, 0.9, 0.03)
        out = S.place(out, tone * amp, i * 0.26)
    return S.lpf(out, 3600)


def static(dur=1.0, amp=0.22, seed=8):
    x = S.noise(dur, seed=seed)
    x = S.biquad(x, "band", 2200, q=0.8)
    gate = 0.55 + 0.45 * np.sin(np.linspace(0, 40, len(x))) ** 2
    return (x * gate * amp).astype(np.float32)


def room_tone(dur, amp=0.1, seed=9):
    x = S.biquad(S.noise(dur, seed=seed, pink=True), "low", 420, q=0.7)
    return (x * amp).astype(np.float32)


def drip(dur=0.5, amp=0.3, seed=10):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 900 * (1 - 0.6 * np.minimum(1, t / 0.06))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 40)
    return S.lpf((x * amp).astype(np.float32), 4200)


def paper(dur=0.45, amp=0.25, seed=11):
    x = S.noise(dur, seed=seed)
    x = S.biquad(x, "band", 3000, q=1.2)
    env = (np.abs(S.biquad(S.noise(dur, seed=seed + 1, pink=True), "low", 40)) > 0.5) * 1.0
    env = 0.35 + 0.65 * env
    return S.lpf((x * env * amp).astype(np.float32), 9000)


def swell_low(dur=2.0, amp=0.3, seed=12):
    """Sub swell under a reveal (feels like a held breath)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 30 + 12 * (t / dur)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR)
    env = np.linspace(0, 1, n) ** 1.6
    env[-int(0.25 * SR):] *= np.linspace(1, 0, int(0.25 * SR))
    return (x * env * amp).astype(np.float32)


LIB = {
    "whoosh": whoosh, "whoosh_back": lambda **k: whoosh(up=False, **k),
    "impact": impact, "riser": riser, "reverse_swell": reverse_swell,
    "thud": thud, "door": door, "phone": phone, "static": static,
    "room_tone": room_tone, "drip": drip, "paper": paper, "swell_low": swell_low,
}


def get(name, **kw):
    return LIB[name](**kw)
