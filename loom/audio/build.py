"""Audio assembly: voice + score + sound design -> data/mix.wav.

Order matters. The score is composed against the *shot list* (so cuts and cues
are known), then the voice is laid in, then the score is ducked under it, then
sound design is placed on the frames that need weight, and only then does the
mix get normalised and limited.
"""
from __future__ import annotations

import os

import numpy as np

from . import music, sfx
from .mix import SR, build_voice, duck_gain, integrated_lufs, limiter, master, true_peak, write_wav
from .synth import place


def _cues(project):
    """Moments worth scoring: shot starts after the first, and card endings."""
    cues = []
    for i, s in enumerate(project.shots):
        if i == 0:
            continue
        cues.append(round(s.start, 3))
    return cues


def build_mix(project, style_module, quiet=False, music_level_db=None, target_lufs=-14.0):
    dur = project.duration
    d = getattr(style_module, "DEFAULTS", {})
    md = project.data.get("music") or {}
    style = md.get("style") or d.get("music") or project.style
    enabled = md.get("enabled", True)

    n_total = int(dur * SR)

    def _fit(x, n):
        y = np.zeros(n, np.float32)
        if x is None:
            return y
        k = min(n, len(x))
        y[:k] = x[:k]
        return y

    # ---- voice
    vp = project.p("voice", "narration.wav")
    voice = np.zeros(n_total, np.float32)
    if os.path.exists(vp):
        import soundfile as sf
        a, sr = sf.read(vp, dtype="float32", always_2d=False)
        if a.ndim > 1:
            a = a.mean(axis=1)
        voice = _fit(a, n_total)
    else:
        if not quiet:
            print("  (no narration.wav — building a silent voice track)")

    # ---- music
    cues = _cues(project)
    lvl = music_level_db if music_level_db is not None else md.get("level_db", -19.0)
    if enabled and dur > 1:
        score = music.compose(style, dur, cues=cues, seed=project.seed)
        n = n_total
        bed = np.zeros((n, 2), np.float32)
        k = min(n, len(score))
        bed[:k] = score[:k]
        bed *= 10 ** (lvl / 20.0) / max(1e-9, float(np.abs(bed).max()))
        duck = duck_gain(voice, SR, amount=0.6)
        dg = np.interp(np.arange(n), np.arange(len(duck)), duck)
        bed *= (1.0 - 0.42 * (1.0 - dg))[:, None]
        if not quiet:
            print(f"  score: {style} @ {lvl:.1f} dBFS, {len(cues)} cues")
    else:
        bed = np.zeros((n_total, 2), np.float32)

    # ---- sound design declared by the style module
    sfx_track = np.zeros((n_total, 2), np.float32)
    events = []
    if hasattr(style_module, "sfx_events"):
        events = style_module.sfx_events(project) or []
    for ev in events:
        name = ev.get("name")
        if name not in sfx.LIB:
            continue
        a = sfx.get(name, amp=ev.get("amp", 0.4), seed=ev.get("seed", 3),
                    **{k: v for k, v in ev.items() if k in
                       ("dur", "f0", "f1", "close", "up")})
        st = np.stack([a, a], axis=1) if a.ndim == 1 else a
        sfx_track = place(sfx_track, st, float(ev["t"]), float(ev.get("gain", 1.0)))
    if events and not quiet:
        print(f"  sfx: {len(events)} events")

    # ---- stem report (QC reads this instead of guessing from the mix)
    def _rms(x):
        return float(np.sqrt(np.mean(np.square(x)) + 1e-12))
    speech = np.abs(voice) > (np.abs(voice).max() * 0.06)
    v_rms = _rms(voice[speech]) if speech.any() else 1e-6
    b_rms = _rms(bed[speech, 0]) if speech.any() else 1e-6
    import json as _json
    _json.dump(dict(voice_rms_db=round(20*np.log10(v_rms), 2),
                    bed_rms_db=round(20*np.log10(b_rms), 2),
                    voice_over_bed_db=round(20*np.log10(max(1e-9, v_rms)/max(1e-9, b_rms)), 2),
                    music_level_db=lvl, cues=len(cues), sfx_events=len(events)),
               open(project.p("data", "audio_report.json"), "w"), indent=1)

    # ---- sum
    v3 = np.stack([voice, voice], axis=1)
    mix = v3 * 0.86 + bed + sfx_track
    mix = master(mix, SR, target_lufs=target_lufs)
    # a little headroom trim if the limiter had to work hard
    if true_peak(mix) > 0.98:
        mix = limiter(mix, SR, -1.4)
    out = project.p("data", "mix.wav")
    write_wav(out, mix, SR)
    if not quiet:
        print(f"  mix: {dur:.1f}s  {integrated_lufs(mix, SR):.1f} LUFS  "
              f"peak {20*np.log10(max(1e-9, true_peak(mix))):.1f} dBTP -> {out}")
    return out
