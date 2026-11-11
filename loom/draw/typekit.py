"""Typography: bundled fonts, balanced wrapping, tracked text, and the caption
engine.

The caption engine's one non-negotiable rule: **layout is fixed for the life of
a caption group**. Words light up in place; nothing reflows, nothing jitters,
nothing jumps. That is the difference between a caption that reads like a
subtitle and one that reads like a slot machine.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import ImageFont

from ..util import clamp, rgb

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")

# family -> (filename, variable?)
FAMILIES = {
    "anton": ("Anton-Regular.ttf", False),
    "barlow": ("BarlowCondensed-Bold.ttf", False),
    "barlow_med": ("BarlowCondensed-Medium.ttf", False),
    "inter": ("Inter-Regular.ttf", True),
    "marker": ("PermanentMarker-Regular.ttf", False),
    "hand": ("PatrickHand-Regular.ttf", False),
    "playfair": ("PlayfairDisplay.ttf", True),
    "mono": ("JetBrainsMono-Bold.ttf", True),
    "oswald": ("Oswald.ttf", True),
}

# Platform UI safe insets as fractions of frame height (9:16 defaults).
SAFE = {
    "tiktok": dict(top=0.075, bottom=0.175, side=0.055, right=0.13),
    "reels": dict(top=0.085, bottom=0.19, side=0.055, right=0.13),
    "shorts": dict(top=0.07, bottom=0.14, side=0.05, right=0.10),
    "generic": dict(top=0.05, bottom=0.06, side=0.05, right=0.05),
}


@lru_cache(maxsize=256)
def font(family="barlow", size=64, weight=None, italic=False):
    fname, variable = FAMILIES.get(family, FAMILIES["barlow"])
    f = ImageFont.truetype(os.path.join(FONT_DIR, fname), int(round(size)))
    if weight and variable:
        try:
            f.set_variation_by_name(weight)
        except Exception:
            try:
                axes = f.get_variation_axes()
                f.set_variation_by_axes([float(weight)] + [a["default"] for a in axes[1:]])
            except Exception:
                pass
    return f


def measure(s, f, tracking=0.0):
    """Width in px including letter tracking (tracking is in em fractions)."""
    if not s:
        return 0.0
    if tracking == 0:
        b = f.getbbox(s)
        return float(b[2] - b[0])
    w = sum(f.getlength(ch) for ch in s) + tracking * f.size * (len(s) - 1)
    return float(w)


def line_metrics(f, tracking=0.0):
    a, d = f.getmetrics()
    return a + d


def wrap(text, f, max_width, tracking=0.0):
    """Greedy wrap that never leaves a one-word last line if it can help it."""
    words = text.split()
    if not words:
        return []
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and measure(trial, f, tracking) > max_width:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    if len(lines) > 1 and len(lines[-1]) == 1 and len(lines[-2]) > 2:
        lines[-1].insert(0, lines[-2].pop())
    return [" ".join(l) for l in lines]


def wrap_balanced(text, f, max_width, tracking=0.0, max_lines=None):
    """Shrink-free balanced wrap: picks the break that minimises raggedness."""
    words = text.split()
    if not words:
        return []
    best, best_cost = None, 1e18
    n = len(words)
    for k in range(1, min(n, (max_lines or n) + 1)):
        # try splitting into k lines at all boundaries (n small, brute force ok)
        for cuts in _cut_sets(n, k):
            groups = []
            i = 0
            for c in cuts:
                groups.append(" ".join(words[i:c]))
                i = c
            if any(measure(g, f, tracking) > max_width for g in groups):
                continue
            cost = sum((max_width - measure(g, f, tracking)) ** 2 for g in groups) / 1000.0
            cost += 900 * sum(1 for g in groups if len(g.split()) == 1)
            if cost < best_cost:
                best, best_cost = groups, cost
    return best or wrap(text, f, max_width, tracking)


def _cut_sets(n, k):
    from itertools import combinations
    for comb in combinations(range(1, n), k - 1):
        yield list(comb) + [n]


def draw_tracked(gfx, xy, s, f, fill, tracking=0.0, anchor="la", alpha=1.0,
                 stroke=0, stroke_fill=(0, 0, 0), shadow=None):
    """Draw text with letter tracking; anchor supports l/m/r + a/t/m/b/s."""
    if not s:
        return
    total = measure(s, f, tracking)
    h = line_metrics(f)
    x, y = xy
    ha, va = anchor[0], anchor[1] if len(anchor) > 1 else "a"
    if ha == "m":
        x -= total / 2
    elif ha == "r":
        x -= total
    asc = f.getmetrics()[0]
    if va == "t":
        y += 0
    elif va == "m":
        y -= h / 2
    elif va == "b":
        y -= h
    elif va == "s":       # baseline-ish
        y -= asc
    if shadow:
        off, col, a2 = shadow
        _draw_chars(gfx, (x + off[0], y + off[1]), s, f, col, tracking, alpha * a2)
    if stroke and stroke_fill:
        # cheap stroke: 8-way offset in the stroke colour
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            _draw_chars(gfx, (x + dx * stroke, y + dy * stroke), s, f, stroke_fill,
                        tracking, alpha)
    _draw_chars(gfx, (x, y), s, f, fill, tracking, alpha)


def _draw_chars(gfx, xy, s, f, fill, tracking, alpha):
    x, y = xy
    c = rgb(fill) + (int(clamp(alpha) * 255),)
    if tracking == 0:
        gfx.d.text((x, y), s, font=f, fill=c)
        return
    for ch in s:
        gfx.d.text((x, y), ch, font=f, fill=c)
        x += f.getlength(ch) + tracking * f.size


# ------------------------------------------------------------------ captions
@dataclass
class CaptionStyle:
    family: str = "barlow"
    weight: str | None = None
    size_h: float = 0.040          # font size as fraction of frame height
    color: str = "#ffffff"
    highlight: str | None = "#ffd400"
    past_color: str | None = None
    uppercase: bool = True
    tracking: float = 0.0
    stroke: float = 0.0
    stroke_color: str = "#000000"
    shadow: float = 0.10
    max_lines: int = 2
    max_chars: int = 22
    words_per_chunk: int = 3
    line_gap: float = 0.22         # in em
    anchor_y: float = 0.72         # fraction of frame height
    plate: str | None = None
    plate_alpha: float = 0.55
    plate_pad: float = 0.55        # em
    plate_radius: float = 0.35     # em
    pop: float = 0.16              # active-word scale pop
    fade_in: float = 0.09
    style: str = "karaoke"         # karaoke | whole | typewriter | none


def chunk_words(words, style: CaptionStyle):
    """Group timed words into caption chunks (max words + max chars + pause split)."""
    groups, cur = [], []
    for i, w in enumerate(words):
        text = w["word"]
        joined = " ".join([c["word"] for c in cur] + [text])
        too_long = len(joined) > style.max_chars * style.max_lines
        gap = cur and (w["start"] - cur[-1]["end"]) > 0.42
        if cur and (len(cur) >= style.words_per_chunk or too_long or gap):
            groups.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?]$", text) and len(cur) >= 2:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    # merge groups that would flash on screen for less than ~0.6 s
    merged = []
    i = 0
    while i < len(groups):
        g = groups[i]
        while (i + 1 < len(groups) and g[-1]["end"] - g[0]["start"] < 0.6
               and len(g) + len(groups[i + 1]) <= style.words_per_chunk + 1):
            g = g + groups[i + 1]
            i += 1
        merged.append(g)
        i += 1
    return merged


def build_caption_lines(group, f, tracking, max_width):
    text = " ".join(w["word"] for w in group)
    if len(text) <= 20:
        return [text]
    return wrap_balanced(text, f, max_width, tracking, max_lines=2)


class CaptionRenderer:
    def __init__(self, W, H, style: CaptionStyle, platform="tiktok"):
        self.W, self.H, self.style = W, H, style
        self.f = font(style.family, H * style.size_h, style.weight)
        self.safe = SAFE.get(platform, SAFE["generic"])
        self._layout_cache = {}

    # ---- layout (cached per group id, independent of time)
    def layout(self, key, group):
        if key in self._layout_cache:
            return self._layout_cache[key]
        st = self.style
        f = self.f
        max_w = self.W * (1 - 2 * self.safe["side"])
        lines = build_caption_lines(group, f, st.tracking, max_w)
        if st.uppercase:
            lines = [l.upper() for l in lines]
        lh = line_metrics(f) + st.line_gap * f.size
        widths = [measure(l, f, st.tracking) for l in lines]
        block_h = lh * len(lines)
        y_top = self.H * st.anchor_y - block_h / 2
        # word boxes: (line_index, x_start, x_end)
        boxes = []
        idx = 0
        for li, line in enumerate(lines):
            x = self.W / 2 - widths[li] / 2
            for word in line.split():
                matches = group[idx: idx + 8]
                target = None
                for m in matches:
                    if m["word"].upper().strip(".,!?;:") .startswith(word.strip(".,!?;:")) or \
                       word.strip(".,!?;:").startswith(m["word"].upper().strip(".,!?;:")) or \
                       word.strip(".,!?;:") == m["word"].upper().strip(".,!?;:"):
                        target = m
                        break
                if target is None:
                    target = group[min(idx, len(group) - 1)]
                idx += 1
                w_ = measure(word, f, st.tracking)
                boxes.append(dict(word=word, line=li, x=x, w=w_, start=target["start"],
                                  end=target["end"]))
                x += w_ + measure(" ", f, st.tracking)
        lay = dict(lines=lines, lh=lh, y_top=y_top, widths=widths, block_h=block_h,
                   boxes=boxes, max_w=max_w)
        self._layout_cache[key] = lay
        return lay

    def draw(self, gfx, t, key, group):
        st = self.style
        if st.style == "none" or not group:
            return
        lay = self.layout(key, group)
        t0 = group[0]["start"]
        t_end = group[-1]["end"]
        out_a = clamp(min((t - t0) / max(1e-3, st.fade_in), (t_end + 0.10 - t) / 0.12))
        if out_a <= 0.01:
            return
        f = self.f

        if st.plate:
            pad = st.plate_pad * f.size
            x0 = self.W / 2 - max(lay["widths"]) / 2 - pad
            x1 = self.W / 2 + max(lay["widths"]) / 2 + pad
            gfx.rect((x0, lay["y_top"] - pad * 0.4, x1, lay["y_top"] + lay["block_h"] + pad * 0.2),
                     fill=st.plate, alpha=st.plate_alpha * out_a,
                     radius=int(st.plate_radius * f.size))

        for b in lay["boxes"]:
            if st.style == "typewriter" and t < b["start"]:
                continue
            if t >= b["start"]:
                active = b["start"] <= t <= b["end"]
                past = t > b["end"]
                col = st.highlight if (active and st.highlight) else (
                    st.past_color or st.color) if past or not st.highlight else st.color
                if st.highlight and not active and not past:
                    col = st.color
                a = clamp((t - b["start"]) / max(1e-3, st.fade_in))
                a = 0.55 + 0.45 * a if st.style == "karaoke" else a
                scale = 1.0
                if active and st.pop:
                    k = clamp((t - b["start"]) / 0.10)
                    scale = 1.0 + st.pop * (1 - k) ** 2
                y = lay["y_top"] + b["line"] * lay["lh"]
                self._word(gfx, b, y, f, col, a * out_a, scale, st)
            else:
                # not yet spoken: draw dim if karaoke reveals ahead of time
                if st.style == "karaoke":
                    y = lay["y_top"] + b["line"] * lay["lh"]
                    self._word(gfx, b, y, f, st.color, 0.22 * out_a, 1.0, st)

    def _word(self, gfx, b, y, f, col, alpha, scale, st):
        x = b["x"]
        if scale != 1.0:
            w = b["w"]
            x = x + w / 2 - w * scale / 2
        if st.shadow:
            draw_tracked(gfx, (x, y), b["word"], f, col, st.tracking, alpha=alpha,
                         stroke=st.stroke, stroke_fill=st.stroke_color,
                         shadow=((0, max(2, f.size * 0.055)), "#000000", st.shadow * 2.2))
        else:
            draw_tracked(gfx, (x, y), b["word"], f, col, st.tracking, alpha=alpha,
                         stroke=st.stroke, stroke_fill=st.stroke_color)
