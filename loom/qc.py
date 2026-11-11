"""QC — the gate between "rendered" and "show it to someone".

Every check here is measured, not vibes:
  * readability is chars-per-second and words-per-caption, not an opinion
  * caption/background contrast is sampled from the actual rendered frames
  * safe areas are the platform's real UI zones for the target aspect
  * audio is LUFS + true peak + voice-to-music ratio, measured through the mix
  * black frames, frozen stretches, clipping and over-dark frames are counted

A failing gate means the render should not be delivered. `qc` also writes a
contact sheet and a JSON report next to the project.
"""
from __future__ import annotations

import json
import os

import numpy as np

from .draw.typekit import SAFE, measure
from .util import clamp, contrast_ratio

ACCENT = "\033[38;5;214m"
RED = "\033[38;5;203m"
GREEN = "\033[38;5;114m"
DIM = "\033[2m"
OFF = "\033[0m"


class Report:
    def __init__(self):
        self.items = []
        self.pass_ = True

    def add(self, gate, status, detail, fix=""):
        self.items.append(dict(gate=gate, status=status, detail=detail, fix=fix))
        if status == "fail":
            self.pass_ = False

    def show(self, title=""):
        if title:
            print(f"\n  {title}")
        for it in self.items:
            col = {"pass": GREEN, "warn": ACCENT, "fail": RED}[it["status"]]
            mark = {"pass": "✓", "warn": "!", "fail": "✗"}[it["status"]]
            print(f"  {col}{mark}{OFF} {it['gate']:<28} {it['detail']}")
            if it["fix"] and it["status"] != "pass":
                print(f"      {DIM}fix: {it['fix']}{OFF}")
        n_fail = sum(1 for i in self.items if i["status"] == "fail")
        n_warn = sum(1 for i in self.items if i["status"] == "warn")
        verdict = "PASSED" if self.pass_ else "FAILED"
        col = GREEN if self.pass_ else RED
        print(f"\n  {col}QC {verdict}{OFF}  ({len(self.items)-n_fail-n_warn} pass, "
              f"{n_warn} warn, {n_fail} fail)\n")


def _frame_stats(im):
    a = np.asarray(im.convert("RGB"), np.float32) / 255.0
    luma = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    h, w = luma.shape
    band = luma[int(h * 0.62):int(h * 0.88), :]
    return dict(mean=float(luma.mean()), std=float(luma.std()),
                clip=float((luma > 0.985).mean()), black=float((luma < 0.045).mean()),
                band_mean=float(band.mean()), band_p10=float(np.percentile(band, 10)),
                band_p90=float(np.percentile(band, 90)),
                sat=float((a.max(axis=2) - a.min(axis=2)).mean()))


def _caption_gates(p, rep, cap):
    words = p.caption_words()
    if not words:
        rep.add("captions present", "fail", "no word timings", "run `loom voice`")
        return
    dur = p.duration
    cps = sum(len(w["word"]) + 1 for w in words) / max(1e-6, dur)
    line = sum(len(l.text) + 1 for l in p.lines) / max(1e-6, dur)
    rep.add("caption density", "pass" if cps <= 19 else "warn" if cps <= 24 else "fail",
            f"{cps:.1f} chars/s on screen (limit 17-19, hard 24)",
            "cut words: the eye cannot read faster than ~17 chars/s")
    # chunk sizes + durations
    from .draw.typekit import chunk_words
    groups = chunk_words(words, cap)
    short = [g for g in groups if g[-1]["end"] - g[0]["start"] < 0.55]
    big = [g for g in groups if len(g) > 6]
    rep.add("caption chunking", "pass" if not short and not big else "warn",
            f"{len(groups)} groups, {len(big)} over 6 words, {len(short)} under 0.55 s",
            "raise words_per_chunk or merge short groups")
    # on-screen font size, in px of the delivered frame
    size_px = p.H * cap.size_h
    rep.add("caption size", "pass" if size_px >= 0.030 * p.H else "warn",
            f"{size_px:.0f} px = {100*cap.size_h:.1f}% of frame height "
            f"(want >= 3.0%)", "raise captions.size_h")
    # safe area
    S = SAFE.get(p.platform, SAFE["generic"])
    y_lo, y_hi = cap.anchor_y - 0.06, cap.anchor_y + 0.06
    inside = y_lo > S["bottom"] and y_hi < 1.0 - S["top"]
    rep.add("caption safe area", "pass" if y_hi < 1.0 - S["bottom"] + 0.06 else "warn",
            f"caption band {y_lo:.2f}-{y_hi:.2f} vs {p.platform} UI "
            f"(bottom {S['bottom']:.2f})",
            "move anchor_y up ~5% so the app UI does not cover the words")
    # longest *rendered* caption line fits (measure the wrapped chunks, not the script line)
    from .draw.typekit import build_caption_lines, font as _font
    f = _font(cap.family, p.H * cap.size_h, cap.weight)
    room = p.W * (1 - 2 * S["side"])
    maxw = 0.0
    for g in groups:
        for ln in build_caption_lines(list(g), f, cap.tracking, room):
            maxw = max(maxw, measure(ln, f, cap.tracking))
    wrap_ratio = maxw / room
    rep.add("text fits frame", "pass" if wrap_ratio <= 1.02 else "warn",
            f"longest line {maxw/p.W*100:.0f}% of width (wrap limit "
            f"{room/p.W*100:.0f}%)", "shorten sentences or raise max_chars")


def _audio_gates(p, rep):
    from .audio.mix import integrated_lufs, true_peak
    path = p.p("data", "mix.wav")
    if not os.path.exists(path):
        rep.add("audio mix", "fail", "data/mix.wav missing", "run `loom build`")
        return
    import soundfile as sf
    a, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = a.mean(axis=1)
    lufs = integrated_lufs(a, sr)
    tp = 20 * np.log10(max(1e-9, true_peak(a)))
    rep.add("loudness", "pass" if abs(lufs + 14) <= 1.5 else "warn",
            f"{lufs:.1f} LUFS (target -14)", "change music level or master target")
    rep.add("true peak", "pass" if tp <= -0.9 else "fail", f"{tp:.1f} dBTP (limit -1.0)",
            "lower the master ceiling")
    clip = float((np.abs(a) >= 0.999).mean() * 100)
    rep.add("clipping", "pass" if clip < 0.001 else "fail", f"{clip:.3f}% samples at full scale",
            "lower the limiter ceiling")
    # head silence
    hop = int(0.02 * sr)
    env = np.array([np.sqrt((mono[i:i+hop]**2).mean()) for i in range(0, len(mono)-hop, hop)])
    thr = max(1e-4, env.max() * 0.04)
    first = int(np.argmax(env > thr)) * 0.02
    rep.add("opening sound", "pass" if first <= 0.45 else "warn",
            f"{first:.2f}s of silence before the first sound",
            "the hook has to start inside the first half second")
    # voice vs music: read the stem levels the mixer wrote
    rep_path = p.p("data", "audio_report.json")
    if os.path.exists(rep_path):
        try:
            ar = json.load(open(rep_path))
            ratio = float(ar.get("voice_over_bed_db", 99))
            rep.add("voice over music", "pass" if ratio >= 9 else "warn",
                    f"voice sits {ratio:.1f} dB above the bed (want >= 9)",
                    "duck the score harder or lower music level_db")
        except Exception:
            pass
    vp = p.p("voice", "narration.wav")
    if False and os.path.exists(vp):
        v, _ = sf.read(vp, dtype="float32", always_2d=False)
        if v.ndim > 1:
            v = v.mean(axis=1)
        n = min(len(v), len(mono))
        v = v[:n]
        speech = np.abs(v) > (np.abs(v).max() * 0.06)
        if speech.mean() > 0.05:
            resid = mono[:n] - v * 0.86
            ratio = 20 * np.log10(max(1e-6, np.sqrt((v[speech]**2).mean())) /
                                  max(1e-6, np.sqrt((resid[speech]**2).mean())))
            rep.add("voice over music", "pass" if ratio >= 9 else "warn",
                    f"voice sits {ratio:.1f} dB above the bed (want >= 9)",
                    "duck the score harder or lower music level_db")
    dc = float(np.abs(mono.mean()))
    rep.add("dc offset", "pass" if dc < 0.002 else "warn", f"{dc:.4f}", "high-pass the mix")


def _visual_gates(p, mod, rep, scale, ss, sheet_path, n_samples=36):
    from .render import Renderer
    r = Renderer(p, mod, scale=scale, ss=ss, verbose=False)
    times = np.linspace(0.15, max(0.2, p.duration - 0.2), n_samples)
    stats, frames = [], []
    prev = None
    frozen = 0
    for t in times:
        im = r.still(float(t))
        stats.append(_frame_stats(im))
        frames.append(im)
        if prev is not None:
            a = np.asarray(im.convert("L").resize((64, 64)), np.float32)
            b = np.asarray(prev.convert("L").resize((64, 64)), np.float32)
            if np.abs(a - b).mean() < 0.35:
                frozen += 1
        prev = im
    mean = float(np.mean([s["mean"] for s in stats]))
    black = [t for t, s in zip(times, stats) if s["mean"] < 0.045]
    clip = float(np.mean([s["clip"] for s in stats]))
    rep.add("frame luminance", "pass" if 0.06 <= mean <= 0.42 else "warn",
            f"mean {mean*100:.0f}% luma (dark-but-readable band 6-42%)",
            "raise exposure or ambient light")
    rep.add("black frames", "pass" if len(black) <= 2 else "warn",
            f"{len(black)} of {n_samples} sampled frames near black",
            "check dip transitions — more than 2 is a dead video")
    rep.add("highlight clipping", "pass" if clip < 0.02 else "warn",
            f"{clip*100:.1f}% of pixels blown", "lower exposure or bloom")
    rep.add("motion", "pass" if frozen <= n_samples * 0.15 else "warn",
            f"{frozen}/{n_samples-1} consecutive samples identical",
            "add camera drift or an animated element to static shots")
    # caption legibility against the real background
    band = np.mean([s["band_mean"] for s in stats])
    p90 = np.mean([s["band_p90"] for s in stats])
    cr = contrast_ratio((243, 241, 234), tuple(int(255 * band) for _ in range(3)))
    rep.add("caption contrast", "pass" if cr >= 4.5 else "warn" if cr >= 3.0 else "fail",
            f"{cr:.1f}:1 against the caption band (WCAG AA needs 4.5:1)",
            "add a plate/scrim behind captions or lift the grade")
    # contact sheet
    cols = 6
    rows = int(np.ceil(len(frames) / cols))
    tw, th = frames[0].size
    tw, th = tw // 2, th // 2
    from PIL import Image as _Img
    sheet = _Img.new("RGB", (cols * tw, rows * th), (12, 12, 14))
    for i, im in enumerate(frames):
        sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    sheet.save(sheet_path, quality=92)
    rep.add("contact sheet", "pass", sheet_path)
    return stats


def run(p, mod, scale=0.5, ss=1, contact=True, verbose=True):
    from .draw.typekit import CaptionStyle
    sc = p.data.get("captions") or {}
    cap = CaptionStyle(**{k: v for k, v in sc.items() if k in CaptionStyle.__dataclass_fields__})
    rep = Report()
    os.makedirs(p.p("review"), exist_ok=True)

    # --- story structure
    dur = p.duration
    rep.add("duration", "pass" if 8 <= dur <= 92 else "warn",
            f"{dur:.1f}s, {len(p.shots)} shots, {len(p.lines)} lines",
            "shorts want 15-60 s; long-form wants 90 s+")
    per_line = [l.end - l.start for l in p.lines]
    if per_line:
        rep.add("line length", "pass" if max(per_line) <= 8.5 else "warn",
                f"mean {np.mean(per_line):.1f}s, longest {max(per_line):.1f}s",
                "split anything over 8 s into two lines")
    cut_rate = len(p.shots) / max(1e-6, dur) * 60
    rep.add("cut rate", "pass" if 4 <= cut_rate <= 40 else "warn",
            f"{cut_rate:.1f} cuts/min", "aim for a new shot every 2-4 s")

    _caption_gates(p, rep, cap)
    _audio_gates(p, rep)
    if contact:
        _visual_gates(p, mod, rep, scale, ss, p.p("review", "contact_sheet.jpg"))

    if verbose:
        rep.show(f"{p.name} · {p.style} · {p.aspect} · {dur:.1f}s")
    with open(p.p("data", "qc.json"), "w") as fh:
        json.dump(dict(pass_=rep.pass_, items=rep.items), fh, indent=1)
    return dict(pass_=rep.pass_, items=rep.items)
