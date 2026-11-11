"""BLUEPRINT — a data/explainer style. Flat, typographic, chart-driven, 16:9 or 9:16.

The opposite end of the range from NIGHTLINE: no world, no camera, no figures.
Just a grid, huge numerals, bars and lines that animate on the beat of the
script, and a HUD frame. Everything is drawn in the post-grade graphics pass so
type stays razor sharp at any output size.

Per-line vocabulary (`"viz": ...` in the script):
  stat       one big number, counting up, with a unit and a source line
  bars       horizontal bars that grow, values labelled
  line       a line chart drawn left to right with a moving head
  compare    two columns against each other
  timeline   dates across a rail
  quote      a pull-quote in serif
  statement  big type only (default)
"""
from __future__ import annotations

import math

from ..camera import FlatRig
from ..draw.typekit import draw_tracked, font, measure, wrap_balanced
from ..ease import spring, track
from ..util import clamp, hash01, lerp, mix

CANVAS_BG = (10, 13, 20)

DEFAULTS = dict(voice="af_bella", speed=1.06, gap=0.34, lead_in=0.45, tail=0.9,
                music="blueprint", platform="youtube")

GRADE = dict(exposure=1.0, contrast=1.06, saturation=1.0, bloom=0.16, halation=0.06,
             grain=0.016, vignette=0.30, ca=0.0, tonemap="reinhard", light_blur=1.0)

CAPTIONS = dict(family="inter", weight="Medium", size_h=0.035, color="#f2f4f8",
                highlight=None, uppercase=False, stroke=0.0, shadow=0.0,
                words_per_chunk=6, max_chars=30, anchor_y=0.86, plate="#0a0d14",
                plate_alpha=0.55, pop=0.0)

PALETTE = dict(bg="#0a0d14", grid="#16202e", ink="#f2f4f8", dim="#8d99ad",
               accent="#ffc247", accent2="#4fd1c5", bad="#ef6f6c")

BG = CANVAS_BG
FLAT = True          # tells the renderer to apply the flat camera (scale + crop)


def camera_for(shot, ctx, tl):
    spec = dict(zoom=[(0, 1.02), (5, 1.10)], cx=[(0, 0.5), (5, 0.5)], cy=[(0, 0.5), (5, 0.485)])
    spec.update(shot.meta.get("cam", {}))
    rig = FlatRig(ctx["W"], ctx["H"], spec)
    return rig  # flat styles consume `.view(t)` instead of project()


def paint(shot, canvas, cam, tl, ctx):
    """Background: deep panel + faint engineering grid + a slow sweep of light."""
    W, H = canvas.W, canvas.H
    ox, oy, z, rot, shake = cam.view(tl)
    canvas.rect((0, 0, W, H), PALETTE["bg"])
    # grid, drifting with the camera (gives the flat frame some life)
    step = W / 26
    off = (ox * 0.8) % step
    for i in range(-2, 30):
        x = i * step - off
        canvas.line([(x, 0), (x, H)], PALETTE["grid"], 1, alpha=0.55)
    for j in range(-2, 26):
        y = j * step - (oy * 0.8) % step
        canvas.line([(0, y), (W, y)], PALETTE["grid"], 1, alpha=0.55)
    # corner marks
    m, l = int(W * 0.028), int(W * 0.014)
    for (cx, cy, dx, dy) in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1),
                             (W - m, H - m, -1, -1)):
        canvas.line([(cx, cy), (cx + dx * l, cy)], PALETTE["dim"], 2, alpha=0.5)
        canvas.line([(cx, cy), (cx, cy + dy * l)], PALETTE["dim"], 2, alpha=0.5)
    canvas.glow((W * 0.5, H * 0.15), H * 0.9, "#1b2b3f", 0.22, 2.6)
    # a slow sweep of light across the board: keeps the frame alive between beats
    sx = ((t_sweep := tl * 0.16) % 1.0) * W * 1.6 - W * 0.3
    canvas.glow((sx, H * 0.42), H * 0.55, "#23384f", 0.10, 2.0)


# ------------------------------------------------------------------ graphics
def gfx(shot, G, tl, ctx):
    W, H = G.W, G.H
    m = shot.meta
    viz = m.get("viz", "statement")
    a_in = clamp(tl / 0.35)
    fn = {"stat": _viz_stat, "bars": _viz_bars, "line": _viz_line, "compare": _viz_compare,
          "timeline": _viz_timeline, "quote": _viz_quote}.get(viz, _viz_statement)
    _kicker(G, m.get("kicker"), a_in, W, H)
    fn(G, m, tl, a_in, W, H)
    if m.get("source"):
        f = font("inter", H * 0.017, "Regular")
        draw_tracked(G, (W * 0.055, H * 0.935), m["source"].upper(), f, PALETTE["dim"],
                     tracking=0.14, alpha=clamp((tl - 0.3) / 0.5) * 0.9)


def _kicker(G, s, a, W, H):
    if not s:
        return
    f = font("inter", H * 0.020, "SemiBold")
    draw_tracked(G, (W * 0.055, H * 0.075), s.upper(), f, PALETTE["accent"], tracking=0.26,
                 alpha=a)
    G.rect((W * 0.055, H * 0.108, W * 0.055 + W * 0.07 * a, H * 0.108 + max(2, H * 0.0035)),
           fill=PALETTE["accent"], alpha=a)


def _big(s, W, H, k=1.0):
    base = H * 0.30 if len(s) < 7 else H * 0.20 if len(s) < 12 else H * 0.13
    return font("anton", base * k)


def _fit_block(text, W, H, max_lines=3, width=0.86):
    """Pick the largest tracked type size whose wrapped block still fits.

    The old code sized type from frame *height* alone, which is right for 16:9
    and catastrophic for 9:16: a 0.30*H face on a 1080x1920 frame is a 576 px
    font inside a 929 px column, so long statements overflowed the sides and
    ran under the kicker. Shrinking until it fits keeps both aspects honest and
    leaves the 16:9 boards pixel-identical (their size already fits).
    """
    size = _big(text, W, H).size
    floor = H * 0.045
    f = font("anton", size)
    lines = wrap_balanced(text.upper(), f, W * width, max_lines=max_lines)
    for _ in range(28):
        widest = max((measure(ln, f) for ln in lines), default=0.0)
        if len(lines) <= max_lines and widest <= W * width:
            return f, lines
        size *= 0.93
        if size < floor:
            break
        f = font("anton", size)
        lines = wrap_balanced(text.upper(), f, W * width, max_lines=max_lines)
    return f, lines


def _viz_statement(G, m, tl, a, W, H):
    text = m.get("title") or m.get("line") or ""
    if not text:
        return
    f, lines = _fit_block(text, W, H)
    y = H * 0.44 - (len(lines) - 1) * f.size * 0.5
    for i, ln in enumerate(lines):
        k = spring(clamp((tl - i * 0.09) / 0.6), freq=1.7, damp=7.0)
        dy = (1 - k) * H * 0.04
        draw_tracked(G, (W * 0.055, y + i * f.size * 1.03 + dy), ln, f, PALETTE["ink"],
                     alpha=a * min(1.0, k * 1.6))


def _viz_stat(G, m, tl, a, W, H):
    """Editorial stat: numeral on the left, label block on the right."""
    val = float(m.get("value", 0))
    unit = m.get("unit", "")
    label = m.get("label", "")
    k = spring(clamp(tl / 0.9), freq=1.5, damp=6.5)
    shown = val * k
    txt = (f"{shown:,.{int(m['decimals'])}f}" if m.get("decimals")
           else f"{int(round(shown)):,}")
    size = H * (0.34 if len(txt) <= 2 else 0.27 if len(txt) <= 4 else 0.20)
    size = min(size, W * 0.62 / max(1.0, 0.60 * len(txt)))
    f = font("anton", size)
    y = H * 0.50 - size * 0.42
    draw_tracked(G, (W * 0.055, y), txt, f, PALETTE["ink"], alpha=a)
    tw = measure(txt, f)
    if unit:
        fu = font("barlow", size * 0.34)
        draw_tracked(G, (W * 0.055 + tw + W * 0.012, y + size * 0.10), unit, fu,
                     PALETTE["accent"], alpha=a)
    if label:
        if H > W:                      # portrait: the label goes under the numeral
            lx, ly, wrap_w = W * 0.055, H * 0.60, W * 0.86
        else:
            lx = W * 0.055 if len(txt) > 5 else W * 0.52
            ly = H * 0.52 if len(txt) > 5 else H * 0.44
            wrap_w = W * (0.40 if len(txt) <= 5 else 0.62)
        fl = font("inter", H * 0.032, "Medium")
        lines = wrap_balanced(label, fl, wrap_w, max_lines=3)
        G.rect((lx, ly - H * 0.035, lx + W * 0.045, ly - H * 0.032),
               fill=PALETTE["accent"], alpha=a)
        yy = ly
        for ln in lines:
            draw_tracked(G, (lx, yy), ln, fl, PALETTE["dim"], alpha=a * 0.95)
            yy += H * 0.045


def _viz_bars(G, m, tl, a, W, H):
    rows = m.get("rows") or []
    if not rows:
        return _viz_statement(G, m, tl, a, W, H)
    top = max(float(r.get("value", 0)) for r in rows) or 1.0
    fb = font("inter", H * 0.030, "Medium")
    fv = font("barlow", H * 0.042)
    portrait = H > W

    # reserve room for the value label before drawing the bars, otherwise a
    # full-width bar pushes "11 km" straight off the right edge
    vstrs = [f"{float(r.get('value', 0)):,.{int(r.get('decimals', 0))}f}{r.get('unit', '')}"
             for r in rows]
    vspace = max(measure(v_, fv) for v_ in vstrs) + W * 0.025

    if portrait:
        x0, x1 = W * 0.055, W * 0.92 - vspace
        y = H * 0.30
        gap = min(H * 0.16, (H * 0.46) / max(1, len(rows)))
        for i, r in enumerate(rows):
            k = spring(clamp((tl - i * 0.13) / 0.75), freq=1.6, damp=6.0)
            val = float(r.get("value", 0))
            draw_tracked(G, (x0, y), str(r.get("label", "")), fb, PALETTE["ink"],
                         alpha=a * min(1.0, k * 2))
            by, h = y + H * 0.042, H * 0.030
            w = (x1 - x0) * (val / top) * k
            col = PALETTE["accent"] if r.get("accent", i == 0) else "#2b3a4d"
            G.rect((x0, by, x0 + max(1, w), by + h), fill=col, alpha=a)
            if r.get("accent", i == 0):
                G.rect((x0, by, x0 + max(1, w), by + max(2, h * 0.10)),
                       fill="#fff3d0", alpha=a * 0.5)
            draw_tracked(G, (x0 + max(1, w) + W * 0.020, by + h * 0.10), vstrs[i], fv,
                         PALETTE["dim"], alpha=a * min(1.0, k * 2))
            y += gap
        return

    x0, x1 = W * 0.36, W * 0.92 - vspace
    y = H * 0.34
    gap = min(H * 0.10, (H * 0.5) / max(1, len(rows)))
    for i, r in enumerate(rows):
        k = spring(clamp((tl - i * 0.13) / 0.75), freq=1.6, damp=6.0)
        val = float(r.get("value", 0))
        draw_tracked(G, (W * 0.055, y + gap * 0.18), str(r.get("label", "")), fb,
                     PALETTE["ink"], alpha=a * min(1.0, k * 2))
        w = (x1 - x0) * (val / top) * k
        h = gap * 0.34
        col = PALETTE["accent"] if r.get("accent", i == 0) else "#2b3a4d"
        G.rect((x0, y, x0 + max(1, w), y + h), fill=col, alpha=a)
        if r.get("accent", i == 0):
            G.rect((x0, y, x0 + max(1, w), y + max(2, h * 0.10)), fill="#fff3d0",
                   alpha=a * 0.5)
        draw_tracked(G, (x0 + max(1, w) + W * 0.012, y + h * 0.10), vstrs[i], fv,
                     PALETTE["dim"], alpha=a * min(1.0, k * 2))
        y += gap


def _viz_line(G, m, tl, a, W, H):
    pts = m.get("points") or []
    if len(pts) < 2:
        return _viz_statement(G, m, tl, a, W, H)
    x0, x1 = W * 0.08, W * 0.92
    y0, y1 = H * 0.68, H * 0.30
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    k = clamp(tl / max(1.2, shot_len(tl, m)))
    xy = [(x0 + (x1 - x0) * i / (len(pts) - 1),
           y0 - (y0 - y1) * ((v - lo) / rng)) for i, v in enumerate(pts)]
    n = max(2, int(len(xy) * k))
    drawn = xy[:n]
    if len(drawn) >= 2:
        G.d.line([(p[0], p[1]) for p in drawn], fill=PALETTE["accent"] + "", width=max(3, int(H * 0.006)),
                 joint="curve")
    for i, p in enumerate(xy):
        if i < n:
            G.d.ellipse([p[0] - H * 0.008, p[1] - H * 0.008, p[0] + H * 0.008, p[1] + H * 0.008],
                        fill=PALETTE["accent2"])
    if drawn:
        head = drawn[-1]
        G.d.ellipse([head[0] - H * 0.014, head[1] - H * 0.014,
                     head[0] + H * 0.014, head[1] + H * 0.014], fill="#ffffff")
    for lab, xx in zip(m.get("labels", []), [p[0] for p in xy]):
        f = font("inter", H * 0.018, "Medium")
        draw_tracked(G, (xx, y0 + H * 0.035), str(lab).upper(), f, PALETTE["dim"],
                     anchor="ma", tracking=0.1, alpha=a)


def shot_len(tl, m):
    return float(m.get("draw_seconds", 2.4))


def _viz_compare(G, m, tl, a, W, H):
    left, right = m.get("left") or {}, m.get("right") or {}
    for i, (side, xx) in enumerate(((left, 0.055), (right, 0.545))):
        k = spring(clamp((tl - i * 0.16) / 0.7), freq=1.6, damp=6.5)
        col = PALETTE["accent"] if i == 0 else PALETTE["accent2"]
        G.rect((W * xx, H * 0.30, W * (xx + 0.40), H * 0.30 + max(2, H * 0.004)),
               fill=col, alpha=a * min(1, k * 2))
        f = font("anton", H * 0.20 * (0.7 + 0.3 * k))
        draw_tracked(G, (W * xx, H * 0.36), str(side.get("value", "")), f, PALETTE["ink"],
                     alpha=a)
        fl = font("inter", H * 0.028, "Medium")
        draw_tracked(G, (W * xx, H * 0.60), str(side.get("label", "")), fl, PALETTE["dim"],
                     alpha=a)


def _viz_timeline(G, m, tl, a, W, H):
    items = m.get("items") or []
    if not items:
        return _viz_statement(G, m, tl, a, W, H)
    k = clamp(tl / 0.8)
    fd = font("mono", H * 0.024, "Bold")
    ft = font("inter", H * 0.024, "Medium")

    if H > W:
        # portrait: four dates across 0.62 * 1080 px collide, so run the rail
        # vertically — date left of the dot, entry text to the right of it
        x = W * 0.30
        y0, y1 = H * 0.30, H * 0.72
        G.rect((x, y0, x + max(2, W * 0.005), y0 + (y1 - y0) * k),
               fill=PALETTE["accent"], alpha=a * 0.7)
        for i, it in enumerate(items):
            frac = i / max(1, len(items) - 1)
            yy = y0 + (y1 - y0) * frac
            on = k >= frac - 0.05
            G.d.ellipse([x - H * 0.009, yy - H * 0.009, x + H * 0.009, yy + H * 0.009],
                        fill=PALETTE["accent"] if on else PALETTE["grid"])
            draw_tracked(G, (x - W * 0.05, yy), str(it.get("date", "")), fd,
                         PALETTE["ink"] if on else PALETTE["dim"], anchor="rm", alpha=a)
            lines = wrap_balanced(str(it.get("text", "")), ft, W * 0.40, max_lines=2)
            lines = lines[:2]
            start_y = yy - (len(lines) - 1) * H * 0.016
            for j, ln in enumerate(lines):
                draw_tracked(G, (x + W * 0.05, start_y + j * H * 0.032), ln, ft,
                             PALETTE["dim"], anchor="lm", alpha=a * (1 if on else 0.4))
        return

    y = H * 0.52
    x0, x1 = W * 0.08, W * 0.92
    G.rect((x0, y, x0 + (x1 - x0) * k, y + max(2, H * 0.004)), fill=PALETTE["grid"],
           alpha=a)
    G.rect((x0, y, x0 + (x1 - x0) * k, y + max(2, H * 0.004)), fill=PALETTE["accent"],
           alpha=a * 0.7)
    for i, it in enumerate(items):
        xx = x0 + (x1 - x0) * (i / max(1, len(items) - 1))
        on = k >= (i / max(1, len(items) - 1)) - 0.05
        G.d.ellipse([xx - H * 0.012, y - H * 0.010, xx + H * 0.012, y + H * 0.014],
                    fill=PALETTE["accent"] if on else PALETTE["grid"])
        draw_tracked(G, (xx, y - H * 0.045), str(it.get("date", "")), fd,
                     PALETTE["ink"] if on else PALETTE["dim"], anchor="mb", alpha=a)
        lines = wrap_balanced(str(it.get("text", "")), ft, W * 0.20, max_lines=3)
        yy = y + H * 0.035
        for ln in lines:
            draw_tracked(G, (xx, yy), ln, ft, PALETTE["dim"], anchor="ma",
                         alpha=a * (1 if on else 0.4))
            yy += H * 0.031


def _viz_quote(G, m, tl, a, W, H):
    text = m.get("quote") or m.get("line") or ""
    qsize = min(H * 0.075, W * 0.115)
    f = font("playfair", qsize, "Medium")
    lines = wrap_balanced(text, f, W * 0.70, max_lines=4)
    y = H * 0.42 - len(lines) * f.size * 0.5
    G.rect((W * 0.055, y - H * 0.02, W * 0.055 + max(2, W * 0.004),
            y + len(lines) * f.size * 1.15), fill=PALETTE["accent"], alpha=a)
    for i, ln in enumerate(lines):
        draw_tracked(G, (W * 0.085, y + i * f.size * 1.15), ln, f, PALETTE["ink"],
                     alpha=a * clamp((tl - i * 0.12) / 0.4))
    if m.get("attribution"):
        fa = font("inter", H * 0.022, "SemiBold")
        draw_tracked(G, (W * 0.085, y + len(lines) * f.size * 1.15 + H * 0.03),
                     m["attribution"].upper(), fa, PALETTE["dim"], tracking=0.18, alpha=a)


# ------------------------------------------------------------------ build
def build(ctx):
    from ..timeline import Shot
    lines = ctx["lines"]
    data = ctx["data"]
    pre = 0.12
    shots = []
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        start = max(0.0, line.start - pre)
        end = (lines[i + 1].start - pre) if not is_last else line.end + float(
            data.get("tail", DEFAULTS["tail"]))
        meta = dict(line.meta)
        meta.setdefault("viz", "statement")
        meta.setdefault("line", line.text)
        # give a chart shot enough time to finish drawing
        if meta["viz"] in ("line", "timeline"):
            meta.setdefault("draw_seconds", max(1.2, end - start - 0.4))
        shots.append(Shot(name=line.id, start=start, end=max(start + 0.5, end), paint=paint,
                          gfx=None, transition=("cut" if i == 0 else meta.get(
                              "transition", data.get("transition", "cut"))),
                          transition_dur=0.0 if i == 0 else float(meta.get("transition_dur", 0.18)),
                          grade=dict(GRADE), meta=meta))
    return shots


def sfx_events(project):
    ev = []
    for i, s in enumerate(project.shots):
        if i == 0:
            continue
        ev.append(dict(name="whoosh", t=max(0.0, s.start - 0.14), amp=0.05, dur=0.30))
        if s.meta.get("viz") in ("stat", "bars"):
            ev.append(dict(name="thud", t=s.start + 0.06, amp=0.14, dur=0.4))
    return ev
