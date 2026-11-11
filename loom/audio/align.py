"""Word-level alignment of known script text to its own waveform.

Why not just transcribe? Because Whisper mis-hears names and numbers and its
timestamps drift by up to a second on short clips — and on a caption-driven
short, a quarter-second of drift is visible. We already know the exact words,
so we only need to find *when* each one happens.

Method (deterministic, no model download):
  1. frame energy -> speech runs (hysteresis threshold + morphological close)
  2. distribute words across runs by syllable weight (so "extraordinarily"
     gets more time than "the")
  3. snap internal boundaries to local energy minima (the quietest millisecond
     between two words is the gap between them)
  4. borrow the punctuation's real pause length for the gap after it

Optional upgrade: `--align whisper` uses whisper word timings as anchors where
it agrees with the script (diff-match), keeping our timings elsewhere.
"""
from __future__ import annotations

import re

import numpy as np

SR = 24000
HOP = 240          # 10 ms
WIN = 720          # 30 ms

VOWELS = "aeiouy"

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
         "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def spoken_form(word: str) -> str:
    """Expand digits so syllable counts match what the voice actually says.
    '2:14' -> 'two fourteen', '1994' -> 'nineteen ninety four', '$4.2m' -> 'four point two million'."""
    w = word.lower().replace(",", "").replace("_", " ").strip("$£€")
    w = re.sub(r"([\d.]+)\s*(m|bn|b|k)\b", lambda m: m.group(1) + {"m": " million", "bn": " billion",
              "b": " billion", "k": " thousand"}[m.group(2)], w)
    if ":" in w:                                  # a clock time
        a, _, b = w.partition(":")
        out = []
        for part in (a, b):
            part = re.sub(r"\D", "", part)
            if part:
                out.append(_num_words(int(part)) if int(part) else "oh")
        return " ".join(out)
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?", w)
    if m:
        whole, frac = m.group(1), m.group(2)
        s = _num_words(int(whole))
        if frac:
            s += " point " + " ".join(_num_words(int(c)) for c in frac)
        return s
    return w


def _num_words(n: int) -> str:
    if 1100 <= n <= 2099:                      # years are read in pairs
        hi, lo = divmod(n, 100)
        if lo == 0:
            return _num_words(hi) + " hundred"
        if lo < 10:
            return _num_words(hi) + " oh " + _ONES[lo]
        return _num_words(hi) + " " + _num_words(lo) if lo < 100 else _num_words(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, r = divmod(n, 10)
        return _TENS[t - 2] + ((" " + _ONES[r]) if r else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + ((" " + _num_words(r)) if r else "")
    if n < 1_000_000:
        th, r = divmod(n, 1000)
        return _num_words(th) + " thousand" + ((" " + _num_words(r)) if r else "")
    return str(n)


def _syl_token(tok: str) -> int:
    w = re.sub(r"[^a-z]", "", tok)
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith("es") and len(w) > 4 and n > 1:
        n -= 1
    return max(1, n)


def syllables(word: str) -> int:
    toks = spoken_form(word).split()
    if not toks:
        return 1
    return max(1, sum(_syl_token(t) for t in toks))


def _pauses(word: str) -> float:
    """Relative silence bonus after a word, in syllable-equivalents."""
    if re.search(r"[.!?]$", word):
        return 1.6
    if re.search(r"[,;:]$", word):
        return 0.8
    if re.search(r"[-—]$", word):
        return 0.6
    return 0.0


def envelope(a: np.ndarray):
    n = max(1, (len(a) - WIN) // HOP + 1)
    pad = np.concatenate([a, np.zeros(max(0, (n - 1) * HOP + WIN - len(a)), np.float32)])
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = pad[idx]
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    return db


def speech_runs(db, floor_margin=9.0, rel_floor_db=-46.0):
    lo = max(rel_floor_db, np.percentile(db, 8) + floor_margin)
    hi = lo + 7.0
    mask = db > lo
    strong = db > hi
    # hysteresis closing: fill short gaps between strong regions
    idx = np.where(strong)[0]
    if len(idx) == 0:
        return [(0, len(db))]
    gap = int(0.22 * SR / HOP)
    runs, start, last = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - last > gap:
            runs.append((start, last))
            start = i
        last = i
    runs.append((start, last))
    # extend to the looser threshold
    out = []
    for (s, e) in runs:
        while s > 0 and mask[s - 1]:
            s -= 1
        while e < len(db) - 1 and mask[e + 1]:
            e += 1
        out.append((s, e + 1))
    return out


def align_line(words: list[str], audio: np.ndarray, sr=SR):
    """words -> [{'word', 'start', 'end'}] in seconds relative to `audio`."""
    n = len(words)
    if n == 0:
        return []
    db = envelope(audio)
    total = len(audio) / sr
    runs = speech_runs(db)
    if not runs:
        runs = [(0, len(db))]

    # ---- weight per word
    wts = np.array([syllables(w) + _pauses(w) for w in words], np.float32)
    # silence at the end of a word belongs to the following gap, not the word
    speak = np.array([syllables(w) for w in words], np.float32)

    # ---- assign words to runs, proportionally to spoken weight
    run_len = np.array([(e - s) for s, e in runs], np.float32)
    split = np.zeros(n + 1, np.int32)
    if len(runs) > 1:
        cuts = np.cumsum(speak) / speak.sum() * run_len.sum()
        acc = np.cumsum(run_len)
        k = 0
        assign = []
        for r in range(len(runs)):
            target_end = acc[r]
            j = int(np.searchsorted(cuts, target_end - 1e-6))
            j = min(max(j + 1, 0), n)
            assign.append(min(n, j))
        prev = 0
        for r in range(len(runs)):
            end = max(assign[r], prev + 1) if r < len(runs) - 1 else n
            split[r] = prev
            prev = min(end, n)
            split[r + 1] = prev
        split[len(runs)] = n
    else:
        split[0], split[1] = 0, n

    out = []
    for r, (s, e) in enumerate(runs):
        i0, i1 = int(split[r]), int(split[r + 1] if r + 1 < len(split) else n)
        if i1 <= i0:
            continue
        seg = words[i0:i1]
        seg_w = wts[i0:i1]
        t0, t1 = s * HOP / sr, min(total, e * HOP / sr)
        span = max(1e-3, t1 - t0)
        cum = np.cumsum(seg_w) / seg_w.sum()
        start = t0
        for k, w in enumerate(seg):
            end = t0 + span * cum[k]
            # snap the boundary to the quietest frame nearby (keeps it honest)
            if k < len(seg) - 1:
                lo = int(max(s, (end - 0.09) * sr / HOP))
                hi = int(min(e - 1, (end + 0.09) * sr / HOP))
                if hi > lo + 1:
                    win = db[lo:hi]
                    # prefer the quietest point, biased toward the estimate
                    bias = np.linspace(-1.5, 1.5, hi - lo)
                    j = int(np.argmin(win + bias))
                    end = (lo + j) * HOP / sr
            syl = syllables(w)
            dur = end - start
            if dur < 0.055 * syl:            # never shorter than ~55 ms/syllable
                end = start + 0.055 * syl
            out.append({"word": w, "start": round(start, 4), "end": round(end, 4)})
            start = end
        if out:
            out[-1]["end"] = round(max(out[-1]["end"], t1), 4)
    # guarantees
    for i in range(1, len(out)):
        if out[i]["start"] < out[i - 1]["end"] - 1e-3:
            out[i]["start"] = out[i - 1]["end"]
        if out[i]["end"] <= out[i]["start"]:
            out[i]["end"] = out[i]["start"] + 0.08
    return out


def confidence(words, audio, sr=SR):
    """Rough 0..1 score: do word boundaries sit in quiet frames?"""
    db = envelope(audio)
    hits = []
    for w in words[:-1]:
        i = int(w["end"] * sr / HOP)
        lo, hi = max(0, i - 2), min(len(db), i + 3)
        if hi > lo:
            hits.append(1.0 if db[lo:hi].min() < np.percentile(db, 45) else 0.0)
    return float(np.mean(hits)) if hits else 1.0
