"""Narration: per-line TTS -> trimmed -> paced -> aligned -> words.json.

Doing this line by line (instead of one long read) is what makes the rest of the
engine reliable: line starts are exact, gaps are deliberate, and word timings
only have to be correct inside a 3-5 second window, where onset-anchored
syllable weighting is as good as forced alignment but needs no model.
"""
from __future__ import annotations

import json
import os

import numpy as np

from .audio import align, tts
from .audio.mix import SR
from .audio.tts import resample


def _norm_gap(text: str, base: float) -> float:
    t = text.strip()
    if t.endswith(("?", "!")):
        return base * 1.15
    if t.endswith((".", "…")):
        return base
    if t.endswith((",", ";")):
        return base * 0.75
    return base * 0.9


def build_narration(project, style_defaults=None, force=False, quiet=False):
    d = dict(style_defaults or {})
    voice = project.data.get("voice") or {}
    vname = voice.get("name") or d.get("voice", "am_michael")
    speed = float(voice.get("speed") or d.get("speed", 1.0))
    gap = float(voice.get("gap") or d.get("gap", 0.5))
    # an opening card is part of the timeline: push the narration behind it
    card = project.data.get("open_card") or {}
    lead = float(d.get("lead_in", 0.4)) + float(card.get("hold", 0.0) or 0.0)
    tail = float(d.get("tail", 1.0))

    words_path = project.p("data", "words.json")
    voice_path = project.p("voice", "narration.wav")
    project.ensure("data")
    project.ensure("voice")
    if os.path.exists(words_path) and not force:
        if not quiet:
            print("  narration already built (use --force to redo)")
        return project.load_words()

    pieces, words, lines_meta = [], [], []
    cursor = lead
    total_speech = 0.0
    for idx, entry in enumerate(project.script):
        sid = entry.get("id") or f"l{idx+1}"
        text = (entry.get("text") or "").strip()
        if not text:
            hold = float(entry.get("hold", 1.2))
            lines_meta.append(dict(id=sid, text="", start=cursor, end=cursor + hold, silent=True))
            cursor += hold
            continue
        if not quiet:
            print(f"  voice [{idx+1}/{len(project.script)}] {text[:58]}")
        audio = tts.synthesize(text, voice=vname, speed=speed)
        audio, trim_l, trim_r = tts.trim_silence(audio)
        audio = resample(audio, tts.SR, SR)
        start = cursor
        pieces.append((audio, start))
        dur = len(audio) / SR
        ws = align.align_line(text.split(), audio, SR)
        for w in ws:
            words.append(dict(word=w["word"], start=round(start + w["start"], 4),
                              end=round(start + w["end"], 4), line=sid))
        lines_meta.append(dict(id=sid, text=text, start=start, end=start + dur,
                               words=len(ws), conf=round(align.confidence(ws, audio, SR), 3)))
        total_speech += dur
        cursor += dur + _norm_gap(text, gap)

    # trim the trailing gap down to the requested tail
    end = cursor - _norm_gap(project.script[-1].get("text", ""), gap) + tail if words else tail

    n = int(max(1.0, end) * SR)
    nv = np.zeros(n, np.float32)
    for a, t in pieces:
        i = int(t * SR)
        k = min(len(a), n - i)
        if k > 0:
            nv[i:i + k] += a[:k]
    from .audio.synth import fade
    nv = fade(nv, SR, fin=0.01, fout=0.35)
    from .audio.mix import write_wav
    write_wav(voice_path, nv, SR)

    payload = dict(voice=vname, speed=speed, sr=SR, duration=round(n / SR, 3),
                   speech_seconds=round(total_speech, 2),
                   lines=lines_meta, words=words)
    with open(words_path, "w") as fh:
        json.dump(payload, fh, indent=1)
    if not quiet:
        cov = total_speech / max(1e-6, n / SR)
        print(f"  narration: {n/SR:.1f}s, {len(words)} words, speech {cov*100:.0f}% of the cut")
    project.load_words()
    return project
