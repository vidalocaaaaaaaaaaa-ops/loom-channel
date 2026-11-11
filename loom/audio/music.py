"""Procedural scores, one per style. Royalty-free by construction.

Each composer answers a small brief: tempo, key, which layers, how the energy
should move across the video, and where the frame cuts are (so a downbeat or a
riser can land on a cut instead of fighting it).
"""
from __future__ import annotations

import numpy as np

from . import synth as S

SR = S.SR

SCALES = {
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
}


def scale_note(root, scale, degree, octave=0):
    sc = SCALES[scale]
    return root + sc[degree % len(sc)] + 12 * (octave + degree // len(sc))


def _pluck(freq, dur=1.2, amp=0.5, bright=0.5, seed=0):
    """FM pluck: warm, woody, no click."""
    t = np.arange(int(dur * SR)) / SR
    mod = np.sin(2 * np.pi * freq * 2.01 * t) * (1.5 * bright * np.exp(-t * 7))
    car = np.sin(2 * np.pi * freq * t + mod)
    car += 0.35 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-t * 5)
    env = np.minimum(1.0, t / 0.006) * np.exp(-t * 2.4)
    return (car * env * amp).astype(np.float32)


def _pad(freqs, dur, amp=0.3, cutoff=1200, seed=0, attack=0.9, release=1.2):
    n = int((dur + release) * SR)
    out = np.zeros(n, np.float32)
    for i, f in enumerate(freqs):
        for det in (-0.0022, 0.0, 0.0025):
            out += S.osc(f, n / SR, kind="saw", detune=det) / (len(freqs) * 3)
    out = S.lpf(out, cutoff, resonance=0.9, passes=2)
    env = np.ones(n, np.float32)
    a = int(attack * SR)
    r = int(release * SR)
    env[:a] = np.linspace(0, 1, a) ** 1.5
    env[-r:] *= np.linspace(1, 0, r) ** 1.2
    body = np.zeros(n, np.float32)
    body[:int(dur * SR)] = 1.0
    env *= np.maximum(body, 0.0) if False else 1.0
    return (out * env * amp).astype(np.float32)


def _thump(freq=62, dur=0.5, amp=0.5, click=0.0, seed=0):
    t = np.arange(int(dur * SR)) / SR
    f = freq * (1 + 0.55 * np.exp(-t * 26))
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.0)
    env = np.minimum(1.0, t / 0.004)
    out = body * env * amp
    if click:
        out = out + S.noise(0.02, seed=seed) * click * np.exp(-t[:int(0.02 * SR)] * 90) * 0.3
    return out.astype(np.float32)


def _riser(dur, amp=0.25, f0=300, f1=6000, seed=0):
    n = int(dur * SR)
    x = S.noise(dur, seed=seed, pink=True)
    x = S.sweep_lpf(x, f0, f1, q=1.1, blocks=40)
    env = (np.linspace(0, 1, n) ** 2.2)
    return (x * env * amp).astype(np.float32)


def _swell(dur, amp=0.2, seed=0, f0=180, f1=2600):
    n = int(dur * SR)
    x = S.noise(dur, seed=seed)
    x = S.sweep_lpf(x, f0, f1, q=1.4, blocks=30)
    env = np.linspace(0, 1, n) ** 3
    return (x * env * amp).astype(np.float32)


# --------------------------------------------------------------- composers
def compose_nightline(duration, cues=(), seed=7, key=50, bpm=62, intensity=0.5):
    """Sparse, dark, cinematic: drone, heartbeat, piano ghosts, string swells."""
    dur = duration + 1.6
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    rng = np.random.default_rng(seed)

    # --- low drone (two detuned saws, slowly breathing filter)
    drone = np.zeros(n, np.float32)
    for oct_, amp in ((0, 0.5), (-12, 0.35), (7, 0.14)):
        for det in (-0.004, 0.0, 0.0037):
            d = S.osc(S.midi(key + oct_), dur, kind="saw", detune=det)
            drone += d * amp
    drone /= 3.2
    seg = max(1, int(1.0 * SR))
    filt = np.empty(n, np.float32)
    for i in range(0, n, seg):
        k = i / max(1, n - 1)
        fc = 190 + 150 * np.sin(k * 3.0) + 90 * k
        filt[i:i + seg] = S.lpf(drone[i:i + seg], fc, resonance=1.1, passes=2)
    breathe = 0.55 + 0.45 * np.sin(np.linspace(0, 7.0, n))
    out += filt * breathe * 0.32

    # --- heartbeat (sub thumps on a slow pulse, getting louder)
    t = 0.8
    while t < dur - 0.5:
        k = t / dur
        amp = 0.16 + 0.22 * k * (0.5 + intensity)
        for off, a in ((0.0, 1.0), (0.19, 0.62)):
            out = S.place(out, _thump(58, 0.55, amp * a), t + off)
        t += beat * 2

    # --- piano-ish ghosts on the scale, aligned to bars
    degs = [0, 4, 2, 6, 1, 5, 3]
    t = 2.2
    i = 0
    while t < dur - 2.0:
        deg = degs[i % len(degs)]
        oct_ = 12 if rng.random() < 0.6 else 24
        note = scale_note(key + 12, "minor", deg, 0) + (oct_ - 12)
        amp = 0.20 + 0.06 * rng.standard_normal()
        p = _pluck(S.midi(note), 2.6, amp=max(0.08, amp), bright=0.35)
        out = S.place(out, p, t + rng.uniform(-0.03, 0.03))
        t += beat * (2 if i % 2 else 3)
        i += 1

    # --- string swells that peak just before each cue
    for c in cues:
        lead = 1.5
        sv = _swell(min(3.2, max(1.2, c * 0.6)), amp=0.11 + 0.06 * intensity, seed=seed + int(c * 10))
        out = S.place(out, sv, max(0.0, c - lead))

    # --- high tension pad in the last third
    if duration > 12:
        pad = _pad([S.midi(scale_note(key + 12, "minor", d, 0)) for d in (0, 2, 4)],
                   dur * 0.45, amp=0.10 + 0.10 * intensity, cutoff=1500, attack=duration * 0.25)
        out = S.place(out, pad, duration * 0.5)

    # --- final low hit on the last cue
    if cues:
        out = S.place(out, _thump(41, 2.2, 0.42), max(0.0, cues[-1]))

    wet = S.reverb(out, amount=0.42, dur=2.8, decay=2.6, damp=4200, seed=seed)
    wet = S.fade(wet, fin=0.3, fout=1.2)
    return S.normalize(wet, 0.72)


def compose_blueprint(duration, cues=(), seed=11, key=45, bpm=104, intensity=0.6):
    """Bright, rhythmic explainer: kick, arp, pad, soft ticks."""
    dur = duration + 1.0
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    rng = np.random.default_rng(seed)
    prog = [0, 5, 3, 4]

    bar = 0
    t = 0.0
    while t < dur:
        chord_deg = prog[bar % len(prog)]
        # pad
        chord = [scale_note(key + 12, "minor", chord_deg + d, 0) for d in (0, 2, 4)]
        pad = _pad([S.midi(c) for c in chord], beat * 4, amp=0.14, cutoff=2200,
                   attack=0.25, release=0.5)
        out = S.place(out, pad, t)
        # bass
        b = np.sin(2 * np.pi * S.midi(key - 12 + SCALES["minor"][chord_deg % 7]) *
                   np.arange(int(beat * 2 * SR)) / SR)
        b *= S.adsr(len(b), SR, 0.01, 0.2, 0.5, 0.15)
        out = S.place(out, b.astype(np.float32) * 0.2, t)
        out = S.place(out, b.astype(np.float32) * 0.16, t + beat * 2)
        # arpeggio in 8ths
        for k in range(8):
            deg = chord_deg + [0, 2, 4, 7, 4, 2, 7, 9][k]
            note = S.midi(scale_note(key + 24, "minor", deg % 7, 7 * (deg // 7)))
            p = _pluck(note, 0.5, amp=0.16, bright=0.55)
            out = S.place(out, p, t + k * beat / 2)
        # kick
        for k in (0, 2):
            out = S.place(out, _thump(52, 0.35, 0.3), t + k * beat)
        t += beat * 4
        bar += 1

    for c in cues:
        out = S.place(out, _swell(0.9, amp=0.12, seed=seed + int(c)), max(0.0, c - 0.9))
    out = S.lpf(out, 14000)
    wet = S.reverb(out, amount=0.22, dur=1.6, decay=3.4, damp=6000, seed=seed)
    return S.normalize(S.fade(wet, fin=0.15, fout=0.8), 0.66)


def compose_lamplit(duration, cues=(), seed=5, key=57, bpm=88, intensity=0.5):
    """Warm storybook: ukulele-ish plucks, soft shaker, rumbling bass."""
    dur = duration + 1.0
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    rng = np.random.default_rng(seed)
    prog = [0, 3, 4, 3]
    t, bar = 0.0, 0
    while t < dur:
        deg = prog[bar % len(prog)]
        for k, d in enumerate((0, 2, 4)):
            note = S.midi(scale_note(key, "major", deg + d, 0))
            p = _pluck(note, 0.9, amp=0.16, bright=0.3)
            out = S.place(out, p, t + k * beat * 0.5)
        b = np.sin(2 * np.pi * S.midi(key - 24) * np.arange(int(beat * 2 * SR)) / SR)
        b *= S.adsr(len(b), SR, 0.02, 0.3, 0.4, 0.2)
        out = S.place(out, b.astype(np.float32) * 0.18, t)
        for k in range(8):
            sh = S.noise(0.05, seed=seed + k)
            sh = S.hpf(sh, 3800) * np.linspace(1, 0, len(sh)) ** 3
            out = S.place(out, sh * 0.055, t + k * beat / 2)
        t += beat * 4
        bar += 1
    wet = S.reverb(out, amount=0.2, dur=1.4, decay=3.8, damp=7000, seed=seed)
    return S.normalize(S.fade(wet, fin=0.1, fout=0.7), 0.62)


COMPOSERS = {
    "nightline": compose_nightline,
    "blueprint": compose_blueprint,
    "lamplit": compose_lamplit,
    "sunlit": compose_blueprint,
    "stickman": compose_lamplit,
}


def compose(style, duration, cues=(), seed=7, **kw):
    fn = COMPOSERS.get(style, compose_nightline)
    mono = fn(duration, cues=cues, seed=seed, **kw)
    st = S.stereo(mono, width=0.55, seed=seed)
    return st
