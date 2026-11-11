"""Small numeric + colour helpers shared by the whole engine."""
from __future__ import annotations

import math

# ---------------------------------------------------------------- numbers


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def inv_lerp(a, b, x):
    return 0.0 if b == a else (x - a) / (b - a)


def remap(x, a, b, c, d, clamped=True):
    t = inv_lerp(a, b, x)
    if clamped:
        t = clamp(t)
    return lerp(c, d, t)


def smoothstep(a, b, x):
    t = clamp(inv_lerp(a, b, x))
    return t * t * (3.0 - 2.0 * t)


def ease_out_quad(t):
    return 1 - (1 - t) ** 2


def ease_in_quad(t):
    return t * t


def hash01(*args):
    """Deterministic float in [0,1) from any tuple of numbers/strings."""
    h = 2166136261
    for a in args:
        if isinstance(a, str):
            for ch in a:
                h = (h ^ ord(ch)) * 16777619 & 0xFFFFFFFF
        else:
            h = (h ^ (int(a * 1000003) & 0xFFFFFFFF)) * 16777619 & 0xFFFFFFFF
    return ((h >> 8) & 0xFFFFFF) / 16777216.0


# ---------------------------------------------------------------- colour

def rgb(c):
    """Accept '#rrggbb', 'rrggbb', (r,g,b) or (r,g,b,a) -> (r,g,b) ints."""
    if isinstance(c, str):
        c = c.lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    return (int(c[0]), int(c[1]), int(c[2]))


def rgba(c, a=255):
    c = rgb(c)
    return (c[0], c[1], c[2], int(clamp(a, 0, 255)))


def mix(c1, c2, t):
    a, b = rgb(c1), rgb(c2)
    return (int(lerp(a[0], b[0], t)), int(lerp(a[1], b[1], t)), int(lerp(a[2], b[2], t)))


def shade(c, amount):
    """amount > 0 lightens toward white, < 0 darkens toward black."""
    a = rgb(c)
    if amount >= 0:
        return mix(a, (255, 255, 255), amount)
    return mix(a, (0, 0, 0), -amount)


def lum(c):
    r, g, b = rgb(c)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def luminance_hex(c):
    """WCAG relative luminance of a colour tuple or hex string."""
    def chan(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(c)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(c1, c2):
    l1, l2 = luminance_hex(c1), luminance_hex(c2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def hexstr(c):
    c = rgb(c)
    return "#%02x%02x%02x" % c


# ---------------------------------------------------------------- geometry

def dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return (x, y)


def poly_area(points):
    a = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) * 0.5
