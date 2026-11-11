"""World-space painting: lit panels, boxes, dust, and depth fog.

The trick that makes this look like a place instead of flat shapes: surfaces are
subdivided into panels and each panel is shaded by a real light rig
(ambient + point lights with inverse-square falloff and a cosine term), then
mixed toward a haze colour by depth. It is per-panel lighting, which is all a
2 cm panel needs to read as a smooth gradient.
"""
from __future__ import annotations

import math

import numpy as np

from ..camera import clip_poly, depth_of
from ..util import clamp, hash01, lerp, mix, rgb


def norm3(v):
    m = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / m, v[1] / m, v[2] / m)


def sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add3(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul3(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


class Light:
    def __init__(self, pos, color="#ffb168", power=1.0, radius=6.0, ambient=False):
        self.pos, self.color, self.power, self.radius = pos, rgb(color), power, radius
        self.ambient = ambient


class Rig3:
    """A light rig + fog for one set."""

    def __init__(self, ambient="#0a0c14", ambient_level=0.55, fog_color="#0a0d14",
                 fog=(2.0, 20.0), fog_amount=1.0, bounce=0.10):
        self.ambient = rgb(ambient)
        self.ambient_level = ambient_level
        self.fog_color = rgb(fog_color)
        self.fog = fog
        self.fog_amount = fog_amount
        self.bounce = bounce
        self.lights: list[Light] = []

    def add(self, pos, color="#ffb168", power=1.0, radius=6.0):
        self.lights.append(Light(pos, color, power, radius))
        return self.lights[-1]

    def shade(self, point, normal, depth):
        """-> (r,g,b) 0..255 for a surface point with a normal at a depth."""
        acc = [self.ambient[0] * self.ambient_level,
               self.ambient[1] * self.ambient_level,
               self.ambient[2] * self.ambient_level]
        n = norm3(normal)
        for L in self.lights:
            d = sub3(L.pos, point)
            dist2 = max(0.05, dot3(d, d))
            dir_ = mul3(d, 1.0 / math.sqrt(dist2))
            cos = max(0.0, dot3(n, dir_))
            if cos <= 0.0:
                continue
            fall = L.power / (1.0 + dist2 / (L.radius * L.radius))
            k = fall * (0.25 + 0.75 * cos)
            for i in range(3):
                acc[i] += L.color[i] * k
        f = clamp((depth - self.fog[0]) / max(1e-6, self.fog[1] - self.fog[0])) ** 1.6
        f *= self.fog_amount
        out = []
        for i in range(3):
            v = lerp(acc[i], self.fog_color[i] * (0.35 + 0.65 * (1 - f)) + acc[i] * 0.25, f * 0.9)
            out.append(int(clamp(v, 0, 255)))
        return tuple(out)


def panel(canvas, cam, rig, p00, p10, p11, p01, normal, base="#808080", alpha=1.0,
          texture=None, extra_light=0.0, drop_if_back=False):
    """Draw one lit quad. Returns the screen polygon (or None)."""
    pts = clip_poly(cam, [p00, p10, p11, p01])
    if not pts or (drop_if_back and len(pts) < 4):
        return None
    cx = (p00[0] + p11[0]) * 0.5
    cy = (p00[1] + p11[1]) * 0.5
    cz = (p00[2] + p11[2]) * 0.5
    depth = depth_of(cam, (cx, cy, cz))
    if depth <= 0.05:
        return None
    lit = rig.shade((cx, cy, cz), normal, depth)
    b = rgb(base)
    col = tuple(int(clamp(lit[i] / 255.0 * b[i] * (1.0 + extra_light), 0, 255)) for i in range(3))
    if texture:
        j = 1.0 + (hash01(cx * 7.3, cy * 5.1, cz * 3.7) - 0.5) * texture
        col = tuple(int(clamp(c * j, 0, 255)) for c in col)
    canvas.poly(pts, col, alpha)
    return pts


def grid(canvas, cam, rig, origin, u, v, nu, nv, normal, base="#808080", texture=0.05,
         extra_light=0.0):
    """Subdivide a parallelogram into nu×nv lit panels (walls, floor, ceiling)."""
    for i in range(nu):
        for j in range(nv):
            a = add3(origin, add3(mul3(u, i / nu), mul3(v, j / nv)))
            b = add3(origin, add3(mul3(u, (i + 1) / nu), mul3(v, j / nv)))
            c = add3(origin, add3(mul3(u, (i + 1) / nu), mul3(v, (j + 1) / nv)))
            d = add3(origin, add3(mul3(u, i / nu), mul3(v, (j + 1) / nv)))
            panel(canvas, cam, rig, a, b, c, d, normal, base, texture=texture,
                  extra_light=extra_light)


def surf(canvas, cam, rig, fn, us, vs, base="#808080", normal=None, texture=0.05,
         extra_light=0.0, flip=False):
    """Shade an arbitrary parametric surface.

    fn(u, v) -> world point. `us`/`vs` are the parameter samples (e.g. a
    non-uniform list of depths so panels are dense near the camera and coarse
    far away — that is what keeps wall shading smooth without extra polygons).
    """
    for i in range(len(us) - 1):
        for j in range(len(vs) - 1):
            u0, u1 = us[i], us[i + 1]
            v0, v1 = vs[j], vs[j + 1]
            a, b = fn(u0, v0), fn(u1, v0)
            c, d = fn(u1, v1), fn(u0, v1)
            if flip:
                b, d = d, b
            n = normal
            if n is None:
                du = sub3(b, a)
                dv = sub3(d, a)
                n = norm3(cross3(du, dv))
            panel(canvas, cam, rig, a, b, c, d, n, base, texture=texture,
                  extra_light=extra_light)


def box(canvas, cam, rig, center, size, base="#808080", texture=0.02, extra_light=0.0,
        faces=("front", "left", "right", "top")):
    """Axis-aligned box, faces sorted back-to-front."""
    cx, cy, cz = center
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    P = {
        "fbl": (cx - hx, cy - hy, cz - hz), "fbr": (cx + hx, cy - hy, cz - hz),
        "ftl": (cx - hx, cy + hy, cz - hz), "ftr": (cx + hx, cy + hy, cz - hz),
        "bbl": (cx - hx, cy - hy, cz + hz), "bbr": (cx + hx, cy - hy, cz + hz),
        "btl": (cx - hx, cy + hy, cz + hz), "btr": (cx + hx, cy + hy, cz + hz),
    }
    defs = {
        "front": (("fbl", "fbr", "ftr", "ftl"), (0, 0, -1)),
        "back": (("bbl", "bbr", "btr", "btl"), (0, 0, 1)),
        "left": (("fbl", "bbl", "btl", "ftl"), (-1, 0, 0)),
        "right": (("fbr", "bbr", "btr", "ftr"), (1, 0, 0)),
        "top": (("ftl", "ftr", "btr", "btl"), (0, 1, 0)),
    }
    order = [f for f in faces if f in defs]
    order.sort(key=lambda f: -depth_of(cam, P[defs[f][0][0]]))
    for f in order:
        keys, nrm = defs[f]
        panel(canvas, cam, rig, *[P[k] for k in keys], nrm, base, texture=texture,
              extra_light=extra_light)


def dust(canvas, cam, t, count=90, seed=3, color="#ffe6c0", intensity=0.35, area=(0, 1.0, 0.4, 6.0)):
    """Airborne motes; brightness follows depth so they layer believably."""
    x0, y0, z0, z1 = area
    for i in range(count):
        h1, h2, h3 = hash01(i, seed), hash01(i, seed + 1), hash01(i, seed + 2)
        z = z0 + (z1 - z0) * ((h3 + t * 0.02) % 1.0)
        x = (h1 - 0.5) * 2.2
        y = y0 + (h2 + t * 0.012) % 1.0
        p = cam.project((x, y, z))
        if p[2] < 0:
            continue
        sx, sy, d, fog = p
        if not (0 <= sx <= cam.W and 0 <= sy <= cam.H):
            continue
        r = cam.px(0.004, d) + 0.7
        a = intensity * (0.20 + 0.80 * (1 - fog)) * (0.35 + 0.65 * hash01(i, seed + 9))
        canvas.glow((sx, sy), max(1.0, r * 2.6), color, a * 0.42, falloff=2.6)


def haze(canvas, cam, rig, strength=0.5, color=None):
    """Depth haze overlay: brighter near the light sources, subtle overall."""
    c = rgb(color or rig.fog_color)
    canvas.vgrad((0, 0, canvas.W, canvas.H), mix(c, (0, 0, 0), 0.72),
                 mix(c, (0, 0, 0), 0.94), alpha=strength * 0.16, steps=16)


def floor_reflection(canvas, cam, pos, size=(0.9, 2.2), color="#ffb168", intensity=0.5,
                     y_floor=0.0):
    """Fake a wet-floor light smear: an elongated glow beneath a light."""
    x, y, z = pos
    p = cam.project((x, y_floor + 0.02, z + size[1] * 0.25))
    if p[2] < 0:
        return
    sx, sy, d, fog = p
    w = cam.px(size[0], d)
    h = cam.px(size[1], d)
    canvas.glow((sx, sy), max(w, h) * 0.8, color, intensity * (1 - 0.6 * fog), falloff=1.6)


def rain(canvas, t, count=260, seed=5, color="#c9d8ff", intensity=0.20, wind=0.18,
         area=None, speed=2.4):
    """Screen-space rain streaks (used outside windows / in the street)."""
    W, H = canvas.W, canvas.H
    area = area or (0, 0, W, H)
    x0, y0, x1, y1 = area
    for i in range(count):
        h1, h2, h3 = hash01(i, seed), hash01(i, seed + 1), hash01(i, seed + 2)
        dy = ((h2 + t * speed * (0.6 + 0.8 * h3)) % 1.0)
        y = y0 + dy * (y1 - y0)
        x = x0 + ((h1 + dy * wind) % 1.0) * (x1 - x0)
        ln = 22 + 34 * h3
        y_end = min(y1 - 2, y + ln)
        if y_end <= y + 1:
            continue
        x_end = x + wind * (y_end - y) * 0.35
        a = intensity * (0.35 + 0.65 * h1)
        canvas.line([(x, y), (x_end, y_end)], mix(color, (0, 0, 0), 0.2),
                    width=max(1, 1.2 + 1.5 * h3), alpha=a)


def floor_pool(canvas, cam, x, z, half_w=0.9, length=1.6, color="#ffb066", intensity=0.3,
               y=0.015, steps=7):
    """Elongated pool of light on the floor (falls off along z) — reads as a
    lamp's reflection on carpet, and keeps the floor from going flat black."""
    for i in range(steps):
        k = i / (steps - 1)
        zz = z - length * 0.5 + length * k
        a = intensity * (1.0 - abs(k - 0.5) * 1.4) ** 1.6
        if a <= 0:
            continue
        p = cam.project((x, y, zz))
        if p[2] < 0:
            continue
        sx, sy, d, fog = p
        w = cam.px(half_w * 2.0, d)
        canvas.glow((sx, sy), max(2.0, w * 0.85), color, a * (1 - 0.55 * fog), falloff=2.0)
