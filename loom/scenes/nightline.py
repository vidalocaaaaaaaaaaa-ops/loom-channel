"""NIGHTLINE — dim, hand-lit interior thriller. The flagship style.

Look: a real corridor or room built in world units, lit by a few point lights,
haze in the air, faceless figures edged in ember light, yellow captions, a mono
date stamp, film grain and a slow camera. Nothing is a stock image; every frame
is drawn from the same 3 m room, so a pan across three shots keeps its geometry.

The lighting rule that makes it look photographed: albedo is a mid-tone and the
light rig modulates it. Surfaces near a lamp reach their full colour, corners
fall to near black, and haze lifts the far end of the corridor.

Shot vocabulary (a project's script sets `"set": ...`):
  corridor      long hotel corridor, warm ceiling lamps, doors both sides
  corridor_far  same corridor, subject small and far, cold spill at the end
  door          close on a door: brass plate, light leaking underneath
  room          interior with a rain window, cold window light, warm bedside lamp
  card          black card for a line that needs air (title, date, quote)
"""
from __future__ import annotations

import math

from ..camera import Camera, Rig, V3, depth_of
from ..draw import figures, geo
from ..draw.typekit import draw_tracked, font, measure
from ..ease import Track, track
from ..util import clamp, hash01, lerp, mix, rgb

CANVAS_BG = (2, 3, 6)

DEFAULTS = dict(voice="am_onyx", speed=0.93, gap=0.62, lead_in=0.75, tail=1.5,
                music="nightline", platform="tiktok")

GRADE = dict(exposure=1.06, contrast=1.18, saturation=0.85, bloom=0.26, halation=0.18,
             grain=0.030, vignette=0.58, ca=1.0, tonemap="aces", light_blur=1.2,
             scrim=0.34, split=("#2b4a6b", "#ffd9a8", 0.26))

CAPTIONS = dict(family="barlow", size_h=0.043, color="#f3f1ea", highlight="#ffcc33",
                uppercase=True, stroke=0.05, shadow=0.16, words_per_chunk=4,
                max_chars=20, anchor_y=0.755, plate=None, pop=0.14)

# albedo: mid-tones. Light decides how bright they get.
A_WALL = "#5b5852"
A_CEIL = "#37393d"
A_FLOOR = "#43292a"
A_DOOR = "#3f362b"
A_FRAME = "#241d16"
A_SKIRT = "#2b2822"

WARM = "#ffb066"
COLD = "#7ba0ff"


def _corridor_rig(light_z=(3.0, 7.0, 11.0, 15.0, 19.0), dead=(), warm=WARM,
                  far_cold=0.0, z_end=26.0):
    rig = geo.Rig3(ambient="#111a2c", ambient_level=0.20, fog_color="#0c1119",
                   fog=(3.0, 24.0), fog_amount=0.85)
    for i, z in enumerate(light_z):
        if i in dead:
            rig.add((0.0, 2.46, z), warm, power=0.05, radius=1.0)
        else:
            rig.add((0.0, 2.46, z), warm, power=1.15, radius=2.1)
    if far_cold:
        rig.add((0.0, 1.3, z_end - 0.5), COLD, power=far_cold, radius=5.0)
    return rig


def _lamp(canvas, cam, pos, color=WARM, intensity=1.0, radius=0.30):
    sx, sy, d, fog = cam.project(pos)
    if d < 0:
        return
    r = cam.px(radius, d)
    canvas.glow((sx, sy), max(2.0, r * 4.2), color, intensity * 0.22 * (1 - 0.5 * fog), 2.2)
    canvas.glow((sx, sy), max(1.5, r * 1.4), "#fff2d2", intensity * 0.55, 1.3)


def _cone(canvas, cam, pos, half_w=0.55, length=2.3, color=WARM, intensity=0.12):
    """Downward volumetric shaft: three nested polygons read as soft falloff."""
    for k, (w, a) in enumerate(((1.0, 0.5), (0.62, 0.75), (0.30, 1.0))):
        p = [pos,
             (pos[0] - half_w * w, max(0.0, pos[1] - length * (1.02 - 0.1 * k)), pos[2] + half_w * w * 0.85),
             (pos[0] + half_w * w, max(0.0, pos[1] - length * (1.02 - 0.1 * k)), pos[2] + half_w * w * 0.85)]
        pts = [cam.project(q) for q in p]
        if any(q[2] < 0 for q in pts):
            continue
        canvas.light_poly([(q[0], q[1]) for q in pts], color, intensity * a, soft=70)


def _door(canvas, cam, rig, side, z, w=0.95, h=2.06, base=A_DOOR, frame=A_FRAME, t=0.0):
    x = side * 1.105
    inward = -side * 0.012
    nrm = (-side, 0, 0)
    geo.panel(canvas, cam, rig, (x + inward, 0.02, z), (x + inward, 0.02, z + w),
              (x + inward, h, z + w), (x + inward, h, z), nrm, base, texture=0.07)
    # recessed panels on the door
    for (y0, y1) in ((0.16, 0.92), (1.04, 1.94)):
        geo.panel(canvas, cam, rig, (x + inward * 2, y0, z + 0.10), (x + inward * 2, y0, z + w - 0.10),
                  (x + inward * 2, y1, z + w - 0.10), (x + inward * 2, y1, z + 0.10),
                  nrm, mix(base, (0, 0, 0), 0.22), texture=0.09)
    # frame
    fi = -side * 0.022
    for quad in (
        ((x + fi, 0.0, z - 0.055), (x + fi, 0.0, z), (x + fi, h + 0.07, z), (x + fi, h + 0.07, z - 0.055)),
        ((x + fi, 0.0, z + w), (x + fi, 0.0, z + w + 0.055), (x + fi, h + 0.07, z + w + 0.055),
         (x + fi, h + 0.07, z + w)),
        ((x + fi, h, z), (x + fi, h, z + w), (x + fi, h + 0.07, z + w), (x + fi, h + 0.07, z))):
        geo.panel(canvas, cam, rig, *quad, nrm, frame, texture=0.05)


def _side_plate(canvas, cam, rig, side, z, y, base="#8d7a50"):
    x = side * 1.10 - side * 0.016
    p = [(x, y - 0.055, z), (x, y - 0.055, z + 0.21), (x, y + 0.055, z + 0.21), (x, y + 0.055, z)]
    geo.panel(canvas, cam, rig, *p, (-side, 0, 0), base, texture=0.02, extra_light=0.85)


# ------------------------------------------------------------------ sets
def set_corridor(canvas, cam, t, p):
    depth = p.get("depth", 26.0)
    lights = p.get("lights", (3.0, 7.0, 11.0, 15.0, 19.0))
    dead = set(p.get("dead", ()))
    # lamps that die during the shot: "out_at": [[seconds, lamp_index], ...]
    for entry in p.get("out_at", ()):
        t_off, idx = float(entry[0]), int(entry[1])
        if t >= t_off:
            dead.add(idx)
    dead = tuple(sorted(dead))
    warm = p.get("warm", WARM)
    rig = _corridor_rig(lights, dead, warm, p.get("far_cold", 0.0), depth)

    # non-uniform depth sampling: dense panels near the lens, coarse far away
    zs = [0.0, 0.30, 0.62, 0.98, 1.40, 1.88, 2.45, 3.10, 3.90, 4.90, 6.10, 7.60, 9.50,
          11.9, 14.9, 18.6, 23.2, depth]
    zs = [z for z in zs if z <= depth]
    if zs[-1] < depth:
        zs.append(depth)
    vs = [i / 20 for i in range(21)]

    # far wall
    geo.panel(canvas, cam, rig, (-1.15, 0, depth), (1.15, 0, depth),
              (1.15, 2.6, depth), (-1.15, 2.6, depth), (0, 0, -1), "#4a4c52", texture=0.06)
    # ceiling, floor, walls
    geo.surf(canvas, cam, rig, lambda u, v: (-1.15 + 2.3 * v, 2.6, u), zs, vs,
             p.get("ceiling", A_CEIL), (0, -1, 0), texture=0.09)
    geo.surf(canvas, cam, rig, lambda u, v: (-1.15 + 2.3 * v, 0.0, u), zs, vs,
             p.get("floor", A_FLOOR), (0, 1, 0), texture=0.22)
    geo.surf(canvas, cam, rig, lambda u, v: (-1.15, v * 2.6, u), zs, vs,
             p.get("wall", A_WALL), (1, 0, 0), texture=0.06)
    geo.surf(canvas, cam, rig, lambda u, v: (1.15, v * 2.6, u), zs, vs,
             p.get("wall", A_WALL), (-1, 0, 0), texture=0.06)
    # carpet runner down the middle
    geo.surf(canvas, cam, rig, lambda u, v: (-0.82 + 1.64 * v, 0.004, u), zs,
             [0, 0.05, 0.95, 1.0], p.get("runner", "#5c2b2b"), (0, 1, 0), texture=0.24)
    # skirting + picture rail
    for side in (-1, 1):
        geo.surf(canvas, cam, rig, lambda u, v, sd=side: (sd * 1.148, v * 0.11, u), zs,
                 [0, 1], A_SKIRT, (-side, 0, 0), texture=0.05)
        geo.surf(canvas, cam, rig, lambda u, v, sd=side: (sd * 1.146, 2.02 + v * 0.05, u),
                 zs, [0, 1], "#7a766c", (-side, 0, 0), texture=0.04)

    # doors
    doors = p.get("doors", [(1.5, 0), (3.2, 0), (4.9, 1), (6.6, 0), (8.3, 0), (10.0, 0),
                            (11.7, 1), (13.4, 0), (15.1, 0), (16.8, 0), (18.5, 1)])
    for i, (z, side_i) in enumerate(doors):
        side = -1 if side_i == 0 else 1
        _door(canvas, cam, rig, side, z, w=0.95, base=p.get("door", A_DOOR))
        _side_plate(canvas, cam, rig, side, z + 0.60, 1.62)

    # ceiling lamps
    for i, z in enumerate(lights):
        alive = i not in dead
        flick = 1.0 if alive else 0.22 + 0.16 * _flick(t, i)
        pos = (0.0, 2.56, z)
        _cone(canvas, cam, pos, 0.40, 2.15, warm, (0.050 if alive else 0.008) * flick)
        _lamp(canvas, cam, pos, warm, (0.95 if alive else 0.22) * flick, 0.20)
        geo.floor_pool(canvas, cam, 0.0, z, 0.80, 2.4, warm, (0.26 if alive else 0.04) * flick)
        geo.panel(canvas, cam, rig, (-0.15, 2.55, z - 0.15), (0.15, 2.55, z - 0.15),
                  (0.15, 2.62, z - 0.15), (-0.15, 2.62, z - 0.15), (0, 0, -1), "#3e4146",
                  texture=0.03)

    if p.get("cold_end"):
        geo.panel(canvas, cam, rig, (-0.34, 0, depth - 0.03), (0.34, 0, depth - 0.03),
                  (0.34, 2.0, depth - 0.03), (-0.34, 2.0, depth - 0.03), (0, 0, -1),
                  "#a8bdf0", extra_light=0.45)
        _lamp(canvas, cam, (0, 1.2, depth - 0.06), COLD, 0.45, 0.5)
        geo.floor_pool(canvas, cam, 0.0, depth - 1.4, 0.85, 2.8, COLD, 0.10)

    fig = p.get("figure")
    if fig:
        figures.shadow_on_floor(canvas, cam, (fig["x"], 0, fig["z"]), fig.get("h", 1.8), alpha=0.6)
        figures.person(canvas, cam, (fig["x"], 0, fig["z"]), fig.get("h", 1.8),
                       fill="#04060b", rim=p.get("rim", "#ff5b28"),
                       rim_intensity=fig.get("rim", 0.9),
                       rim_from=_nearest_lamp(fig["z"], lights, warm),
                       pose=fig.get("pose"), rim_width=fig.get("rim_width", 3))

    geo.haze(canvas, cam, rig, p.get("haze", 0.5))
    geo.dust(canvas, cam, t, p.get("dust", 70), seed=5, intensity=p.get("dust_amt", 0.13))


def _nearest_lamp(z, lights, warm):
    if not lights:
        return (0.0, 2.46, z + 1.0)
    zz = min(lights, key=lambda v: abs(v - z))
    return (0.0, 2.46, zz)


def set_room(canvas, cam, t, p):
    """Hotel room: rain window, cold window light, warm bedside lamp, one figure."""
    D, W, H = 4.6, 4.2, 2.55
    lamp_pos = tuple(p.get("lamp", (1.45, 1.18, 3.0)))
    rig = geo.Rig3(ambient="#101728", ambient_level=0.20, fog_color="#0a0f18",
                   fog=(1.0, 10.0), fog_amount=0.7)
    rig.add(lamp_pos, "#ffb066", power=1.30, radius=2.2)
    win = p.get("window", (-0.75, 0.95, 0.75, 1.95))
    rig.add(((win[0] + win[2]) / 2, (win[1] + win[3]) / 2, D - 0.1), COLD, power=0.75, radius=3.0)

    # walls / floor / ceiling
    geo.grid(canvas, cam, rig, (-W / 2, 0, D), (W, 0, 0), (0, H, 0), 6, 3, (0, 0, -1),
             p.get("wall", "#5f5a51"), texture=0.05)
    geo.grid(canvas, cam, rig, (-W / 2, 0, 0), (0, 0, D), (0, H, 0), 10, 3, (1, 0, 0),
             p.get("wall", "#5f5a51"), texture=0.05)
    geo.grid(canvas, cam, rig, (W / 2, 0, 0), (0, 0, D), (0, H, 0), 10, 3, (-1, 0, 0),
             p.get("wall", "#5f5a51"), texture=0.05)
    geo.grid(canvas, cam, rig, (-W / 2, 0, 0), (W, 0, 0), (0, 0, D), 6, 14, (0, 1, 0),
             p.get("floor", "#3c2a26"), texture=0.14)
    geo.grid(canvas, cam, rig, (-W / 2, H, 0), (W, 0, 0), (0, 0, D), 4, 12, (0, -1, 0),
             "#43464b", texture=0.08)

    # window in the back wall
    x0, y0, x1, y1 = win
    wp = [(x0, y0, D - 0.015), (x1, y0, D - 0.015), (x1, y1, D - 0.015), (x0, y1, D - 0.015)]
    pts = [cam.project(q) for q in wp]
    if all(q[2] > 0 for q in pts):
        poly = [(q[0], q[1]) for q in pts]
        bx = [min(q[0] for q in pts), min(q[1] for q in pts),
              max(q[0] for q in pts), max(q[1] for q in pts)]
        canvas.poly(poly, "#142033")
        _window_rain(canvas, t, bx, p.get("rain", 1.0))
        canvas.light_poly(poly, COLD, 0.11, soft=16)
        fx, fy = canvas.ss, canvas.ss
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
            canvas.line([poly[a], poly[b]], "#241f19", 6)
        mx = (poly[0][0] + poly[1][0]) / 2
        my = (poly[0][1] + poly[3][1]) / 2
        canvas.line([(mx, poly[0][1]), (mx, poly[3][1])], "#241f19", 5)
        canvas.line([(poly[0][0], my), (poly[1][0], my)], "#241f19", 5)
        # cold wash across the floor and the left wall
        fp = [cam.project(q) for q in
              [(x0 * 0.7, 0.02, 1.2), (x1 * 0.7, 0.02, 1.2), (x1, 0.02, D - 0.1), (x0, 0.02, D - 0.1)]]
        if all(q[2] > 0 for q in fp):
            canvas.light_poly([(q[0], q[1]) for q in fp], COLD, 0.075, soft=26)

    # bed + nightstand + lamp
    if p.get("bed", True):
        geo.box(canvas, cam, rig, (1.30, 0.26, 3.35), (1.70, 0.52, 1.95), "#6b5560", texture=0.10)
        geo.box(canvas, cam, rig, (1.30, 0.62, 2.62), (1.72, 0.26, 0.32), "#8b6d78", texture=0.08)
        geo.box(canvas, cam, rig, (2.30, 0.90, 2.62), (0.10, 0.90, 1.95), "#4a3a40", texture=0.06,
                faces=("left", "front"))
        geo.box(canvas, cam, rig, (0.42, 0.24, 3.35), (0.26, 0.48, 1.95), "#3f3136", texture=0.06,
                faces=("front", "left", "top"))
    if p.get("lamp_on", True):
        geo.box(canvas, cam, rig, (lamp_pos[0], 0.30, lamp_pos[2]), (0.42, 0.60, 0.42),
                "#5b4a3d", texture=0.05)
        _lamp(canvas, cam, (lamp_pos[0], 0.80, lamp_pos[2]), "#ffb066", 0.9, 0.14)
        geo.floor_pool(canvas, cam, lamp_pos[0], lamp_pos[2], 0.8, 1.8, "#ffb066", 0.13)

    fig = p.get("figure")
    if fig:
        figures.shadow_on_floor(canvas, cam, (fig["x"], 0, fig["z"]), fig.get("h", 1.8), alpha=0.55)
        figures.person(canvas, cam, (fig["x"], 0, fig["z"]), fig.get("h", 1.8),
                       fill="#04060b", rim=p.get("rim", COLD),
                       rim_intensity=fig.get("rim", 0.75),
                       rim_from=((win[0] + win[2]) / 2, (win[1] + win[3]) / 2, D - 0.2),
                       pose=fig.get("pose"), rim_width=fig.get("rim_width", 3))

    geo.haze(canvas, cam, rig, p.get("haze", 0.4))
    geo.dust(canvas, cam, t, 60, seed=9, intensity=0.13)


def _window_rain(canvas, t, box, amount=1.0):
    x0, y0, x1, y1 = box
    canvas.d.rectangle([x0 * canvas.ss, y0 * canvas.ss, x1 * canvas.ss, y1 * canvas.ss],
                       fill=(14, 22, 38, 90))
    geo.rain(canvas, t, int(120 * amount), seed=11, color="#cfe0ff",
             intensity=0.5, wind=0.09, area=(x0, y0, x1, y1), speed=1.5)
    # faint city glow at the bottom of the glass
    canvas.vgrad((x0, y1 - (y1 - y0) * 0.35, x1, y1), "#1b2a44", "#050a12", alpha=0.35, steps=10)


def set_door(canvas, cam, t, p):
    """Close on a sealed door: brass plate, tape across it, light underneath."""
    dist = float(p.get("dist", 2.35))
    door_c = p.get("door_c", "#66543f")
    rig = geo.Rig3(ambient="#151a24", ambient_level=0.30, fog_color="#090d14",
                   fog=(1.0, 8.0), fog_amount=0.6)
    rig.add((-0.9, 2.30, dist - 1.2), "#ffb066", power=1.15, radius=2.7)
    rig.add((0.0, 0.04, dist - 0.06), p.get("spill", "#ff8a3c"), power=0.8, radius=1.3)
    nrm = (0, 0, -1)
    x0, x1, top, bot = -0.62, 0.62, 2.16, 0.02

    # wall around the door, in one plane at the same depth
    geo.grid(canvas, cam, rig, (-1.9, 0, dist), (3.8, 0, 0), (0, 2.75, 0), 12, 12,
             nrm, p.get("wall_c", "#4f4b44"), texture=0.06)
    # door leaf
    geo.panel(canvas, cam, rig, (x0, bot, dist - 0.01), (x1, bot, dist - 0.01),
              (x1, top, dist - 0.01), (x0, top, dist - 0.01), nrm, door_c, texture=0.09)
    # two recessed panels, bevelled
    for (py0, py1) in ((0.20, 1.00), (1.14, 2.04)):
        bx0, bx1 = x0 + 0.10, x1 - 0.10
        geo.panel(canvas, cam, rig, (bx0, py0, dist - 0.014), (bx1, py0, dist - 0.014),
                  (bx1, py1, dist - 0.014), (bx0, py1, dist - 0.014), nrm,
                  mix(door_c, (0, 0, 0), 0.24), texture=0.10)
        for quad in (((bx0, py0, dist - 0.006), (bx1, py0, dist - 0.006),
                      (bx1, py0 + 0.022, dist - 0.006), (bx0, py0 + 0.022, dist - 0.006)),
                     ((bx0, py1 - 0.022, dist - 0.006), (bx1, py1 - 0.022, dist - 0.006),
                      (bx1, py1, dist - 0.006), (bx0, py1, dist - 0.006)),
                     ((bx0, py0, dist - 0.006), (bx0 + 0.022, py0, dist - 0.006),
                      (bx0 + 0.022, py1, dist - 0.006), (bx0, py1, dist - 0.006)),
                     ((bx1 - 0.022, py0, dist - 0.006), (bx1, py0, dist - 0.006),
                      (bx1, py1, dist - 0.006), (bx1 - 0.022, py1, dist - 0.006))):
            geo.panel(canvas, cam, rig, *quad, nrm, mix(door_c, (255, 240, 210), 0.16),
                      texture=0.05)
    # frame
    for quad in (((-0.72, 0, dist - 0.03), (x0, 0, dist - 0.03), (x0, 2.34, dist - 0.03),
                  (-0.72, 2.34, dist - 0.03)),
                 ((x1, 0, dist - 0.03), (0.72, 0, dist - 0.03), (0.72, 2.34, dist - 0.03),
                  (x1, 2.34, dist - 0.03)),
                 ((x0, top, dist - 0.03), (x1, top, dist - 0.03), (x1, 2.34, dist - 0.03),
                  (x0, 2.34, dist - 0.03))):
        geo.panel(canvas, cam, rig, *quad, nrm, A_FRAME, texture=0.05)
    # brass plate + number
    geo.panel(canvas, cam, rig, (-0.16, 1.52, dist - 0.02), (0.16, 1.52, dist - 0.02),
              (0.16, 1.77, dist - 0.02), (-0.16, 1.77, dist - 0.02), nrm,
              "#bda378", texture=0.03, extra_light=0.10)
    _num_plate(canvas, cam, (0.0, 1.560, dist - 0.026), p.get("number", "402"),
               "#241a06", h=0.125)
    # sealed tape across the door (the story detail)
    for ang, yy in ((0.030, 1.06), (-0.022, 1.185)):
        tp = [(x0 - 0.03, yy, dist - 0.006), (x1 + 0.03, yy + ang, dist - 0.006),
              (x1 + 0.03, yy + ang + 0.038, dist - 0.006), (x0 - 0.03, yy + 0.038, dist - 0.006)]
        pts = [cam.project(q) for q in tp]
        if all(q[2] > 0 for q in pts):
            canvas.poly([(q[0], q[1]) for q in pts], "#a08f68", 0.45)
    # handle
    hp = [cam.project(q) for q in
          [(0.38, 1.00, dist - 0.06), (0.53, 1.00, dist - 0.06),
           (0.53, 1.065, dist - 0.06), (0.38, 1.065, dist - 0.06)]]
    if all(q[2] > 0 for q in hp):
        poly = [(q[0], q[1]) for q in hp]
        canvas.poly(poly, "#8e8163")
        canvas.light_poly(poly, "#ffd9a0", 0.16, soft=8)
    # light under the door + spill on the floor
    lp = [cam.project(q) for q in
          [(x0, bot, dist - 0.012), (x1, bot, dist - 0.012),
           (x1, bot + 0.022, dist - 0.012), (x0, bot + 0.022, dist - 0.012)]]
    if all(q[2] > 0 for q in lp):
        canvas.light_poly([(q[0], q[1]) for q in lp], p.get("spill", "#ff8a3c"),
                          p.get("spill_amt", 1.2), soft=9)
    sp = [cam.project(q) for q in
          [(x0 - 0.1, 0.001, dist - 0.02), (x1 + 0.1, 0.001, dist - 0.02),
           (x1 + 0.7, 0.001, dist - 1.7), (x0 - 0.7, 0.001, dist - 1.7)]]
    if all(q[2] > 0 for q in sp):
        canvas.light_poly([(q[0], q[1]) for q in sp], p.get("spill", "#ff8a3c"),
                          p.get("spill_amt", 1.2) * 0.20, soft=44)
    geo.haze(canvas, cam, rig, 0.40)
    geo.dust(canvas, cam, t, 30, seed=13, intensity=0.14,
             area=(0, 0.6, dist - 1.4, dist - 0.2))


def _num_plate(canvas, cam, pos, text, color="#241a08", h=0.11):
    sx, sy, d, fog = cam.project(pos)
    if d <= 0:
        return
    size = cam.px(h, d)
    f = _scaled_font(font("mono", max(8, int(size))), canvas.ss)
    w = f.getlength(text)
    canvas.d.text((sx * canvas.ss - w / 2 * canvas.ss, sy * canvas.ss - size * 0.42 * canvas.ss),
                  text, font=f, fill=rgb(color) + (200,))


def _scaled_font(f, s):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(f.path, int(round(f.size * s)))
    except Exception:
        return f


def set_card(canvas, cam, t, p):
    """Black card with air, and a slow breathing glow so the frame is never frozen."""
    canvas.rect((0, 0, canvas.W, canvas.H), p.get("bg", "#050609"))
    for i in range(3):
        x = (hash01(i, 4) + 0.012 * math.sin(t * 0.5 + i)) * canvas.W
        y = canvas.H * (0.45 + 0.02 * math.sin(t * 0.31 + i * 2))
        canvas.glow((x, y), canvas.H * (0.75 + 0.05 * math.sin(t * 0.4 + i)),
                    "#16213408"[:7], 0.22, 2.4)


SETS = {"corridor": set_corridor, "corridor_far": set_corridor, "room": set_room,
        "door": set_door, "card": set_card}


def _flick(t, i):
    return 0.5 + 0.5 * math.sin(t * 21.0 + i * 3.1) * math.sin(t * 7.3 + i)


# ------------------------------------------------------------------ camera
DEFAULT_CAM = {
    "corridor": dict(pos=(0.0, 1.58, 0.6), z=[(0, 0.6), (4.2, 2.3)], pitch=[(0, 0.0), (4, -0.015)],
                     yaw=[(0, 0.0), (4, 0.01)], handheld=0.22, fov=58),
    "corridor_far": dict(pos=(0.0, 1.58, 0.4), z=[(0, 0.4), (5.0, 1.0)],
                         pitch=[(0, 0.02), (5, 0.01)], handheld=0.18, fov=52),
    "door": dict(pos=(0.0, 1.30, 0.0), z=[(0, 0.0), (4.0, 0.45)], yaw=[(0, 0.02), (4, -0.02)],
                 handheld=0.28, fov=55, pitch=[(0, 0.0), (4, 0.02)]),
    "room": dict(pos=(0.35, 1.48, 1.15), z=[(0, 1.15), (4.5, 1.70)], yaw=[(0, -0.03), (4.5, 0.06)],
                 handheld=0.18, fov=58),
    "card": dict(pos=(0.0, 1.6, 0.0), handheld=0.05, fov=55),
}


def camera_for(shot, ctx, tl):
    spec = dict(DEFAULT_CAM.get(shot.meta.get("set", "corridor"), DEFAULT_CAM["corridor"]))
    spec.update(shot.meta.get("cam", {}))
    rig = Rig(ctx["W"], ctx["H"], spec, seed=ctx["seed"] + abs(hash(shot.name)) % 97)
    return rig.camera(tl + shot.start, t_local=tl)


# ------------------------------------------------------------------ paint
def paint(shot, canvas, cam, tl, ctx):
    name = shot.meta.get("set", "corridor")
    fn = SETS.get(name, set_corridor)
    p = dict(shot.meta.get("set_params", {}))
    if name == "corridor_far":
        p.setdefault("figure", {"x": 0.0, "z": 13.0, "rim": 1.25})
        p.setdefault("cold_end", 0.6)
    fn(canvas, cam, tl, p)


# ------------------------------------------------------------------ graphics
def gfx(shot, G, tl, ctx):
    W, H = G.W, G.H
    meta = shot.meta
    if meta.get("set") == "card":
        _draw_card(G, tl, shot.dur, meta, W, H)
    stamp = meta.get("date")
    if stamp:
        f = font("mono", H * 0.0195, "Bold")
        a = clamp(tl / 0.5) * 0.92
        draw_tracked(G, (W * 0.085, H * 0.112), stamp, f, "#d8cdb4", tracking=0.18,
                     alpha=a, shadow=((0, 2), "#000000", 0.6))
    label = meta.get("label")
    if label:
        f = font("barlow", H * 0.021, "SemiBold")
        a = clamp(tl / 0.4) * 0.9
        draw_tracked(G, (W * 0.085, H * 0.150), label.upper(), f, "#a9a49a",
                     tracking=0.24, alpha=a)


def _draw_card(G, tl, dur, meta, W, H):
    """Title card as a measured vertical stack: kicker, title, rule, subtitle.

    The stack is centred as a block, so a one-line and a two-line title both sit
    correctly and the kicker can never collide with the numeral.
    """
    title = meta.get("title")
    sub = meta.get("subtitle")
    kicker = meta.get("kicker")
    a_in = clamp(tl / 0.55)
    a_out = clamp((dur - tl) / 0.45)
    a = min(a_in, a_out)
    if a <= 0.01:
        return

    f_kick = font("mono", H * 0.0185, "Bold")
    lines = [l for l in (title or "").upper().split("\n") if l]
    longest = max((len(l) for l in lines), default=0)
    t_size = H * (0.115 if longest <= 6 else 0.092 if longest <= 10 else 0.072)
    f_title = font("anton", t_size)
    f_sub = font("barlow_med", H * 0.027)

    blocks = []
    if kicker:
        blocks.append(("text", kicker.upper(), f_kick, "#8d8a80", H * 0.030, 0.30, "mm"))
    for ln in lines:
        blocks.append(("text", ln, f_title, "#f3f1ea", t_size * 1.02, 0.0, "mm"))
    if sub:
        blocks.append(("rule", None, None, "#c8341f", H * 0.030, 0.0, None))
        for ln in sub.split("\n"):
            blocks.append(("text", ln, f_sub, "#c9c4b8", H * 0.036, 0.06, "mm"))

    total = sum(b[4] for b in blocks)
    y = H * 0.47 - total / 2
    for kind, txt, f, col, height, tracking, anchor in blocks:
        if kind == "rule":
            G.rect((W / 2 - W * 0.055, y + height * 0.30, W / 2 + W * 0.055,
                    y + height * 0.30 + max(3, H * 0.004)), fill=col, alpha=a)
        else:
            draw_tracked(G, (W / 2, y + height / 2), txt, f, col, tracking=tracking,
                         anchor=anchor, alpha=a,
                         shadow=((0, 4), "#000000", 0.5) if f is f_title else None)
        y += height


# ------------------------------------------------------------------ build
def build(ctx):
    """Lines -> shots. One line per shot; cuts land in the pauses."""
    from ..timeline import Shot
    lines = ctx["lines"]
    data = ctx["data"]
    pre = 0.16
    shots = []
    open_card = data.get("open_card")
    if open_card:
        d = float(open_card.get("hold", 1.8))
        shots.append(Shot(name="open", start=0.0, end=d,
                          paint=lambda c, cam, tl, cx: set_card(c, cam, tl, open_card),
                          transition="cut", transition_dur=0.0, grade=dict(GRADE),
                          meta=dict(set="card", title=open_card.get("title"),
                                    kicker=open_card.get("kicker"),
                                    subtitle=open_card.get("subtitle"))))
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        start = max(0.0, line.start - pre)
        end = (lines[i + 1].start - pre) if not is_last else line.end + float(
            data.get("tail", DEFAULTS["tail"]))
        meta = dict(line.meta)
        meta.setdefault("set", "corridor")
        prev_set = shots[-1].meta.get("set") if shots else None
        same_set = prev_set == meta["set"]
        tr = meta.get("transition") or ("cut" if same_set else data.get("transition", "dissolve"))
        td = float(meta.get("transition_dur", 0.42))
        if not shots and open_card:
            tr, td = "dissolve", 0.7
        shots.append(Shot(name=line.id, start=start, end=max(start + 0.6, end),
                          paint=paint, transition=("cut" if not shots else tr),
                          transition_dur=td if shots else 0.0,
                          grade=dict(GRADE), meta=meta))
    end_card = data.get("end_card")
    if end_card:
        st = shots[-1].end
        d = float(end_card.get("hold", 2.4))
        shots.append(Shot(name="end", start=st - 0.55, end=st + d,
                          paint=lambda c, cam, tl, cx: set_card(c, cam, tl, {"bg": "#040508"}),
                          transition="dip", transition_dur=0.6, grade=dict(GRADE),
                          meta=dict(set="card", title=end_card.get("title"),
                                    kicker=end_card.get("kicker"),
                                    subtitle=end_card.get("subtitle"))))
    return shots


# ------------------------------------------------------------------ sound design
def sfx_events(project):
    """Sound on the moments that matter: doors, phones, impacts on cards."""
    ev = []
    for i, s in enumerate(project.shots):
        m = s.meta
        st = m.get("set")
        if st == "card":
            ev.append(dict(name="swell_low", t=max(0.0, s.start + 0.05), amp=0.22, dur=1.8))
            if m.get("title"):
                ev.append(dict(name="impact", t=s.start + 0.35, amp=0.30, dur=1.6))
            continue
        if st == "door":
            ev.append(dict(name="reverse_swell", t=max(0.0, s.start - 0.55), amp=0.12, dur=0.7))
        if st in ("corridor", "corridor_far") and i:
            ev.append(dict(name="whoosh", t=max(0.0, s.start - 0.22), amp=0.055, dur=0.55))
    # the phone rings once, under the first line
    if len(project.lines) > 0:
        l0 = project.lines[0]
        ev.append(dict(name="phone", t=max(0.0, l0.start - 0.9), amp=0.16, dur=0.95))
    return ev
