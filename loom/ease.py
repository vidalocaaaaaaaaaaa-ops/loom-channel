"""Easing, springs and keyframed animation tracks.

Every animated value in a project is a Track: a sorted list of keys
(t, value, ease). Tracks are the only reason motion in these videos feels
like motion instead of a slideshow, so they are a first-class citizen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .util import clamp, lerp


# ------------------------------------------------------------------ curves
EASES = {}


def _reg(*names):
    def deco(fn):
        for n in names:
            EASES[n] = fn
        return fn
    return deco


@_reg("linear", "none")
def linear(t):
    return t


@_reg("in_sine")
def in_sine(t):
    return 1 - math.cos(t * math.pi / 2)


@_reg("out_sine")
def out_sine(t):
    return math.sin(t * math.pi / 2)


@_reg("in_out_sine", "sine")
def in_out_sine(t):
    return -(math.cos(math.pi * t) - 1) / 2


@_reg("in_quad")
def in_quad(t):
    return t * t


@_reg("out_quad")
def out_quad(t):
    return 1 - (1 - t) ** 2


@_reg("in_out_quad", "quad")
def in_out_quad(t):
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


@_reg("in_cubic")
def in_cubic(t):
    return t**3


@_reg("out_cubic")
def out_cubic(t):
    return 1 - (1 - t) ** 3


@_reg("in_out_cubic", "cubic", "smooth")
def in_out_cubic(t):
    return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


@_reg("out_quart", "snap")
def out_quart(t):
    return 1 - (1 - t) ** 4


@_reg("in_out_quart", "quart")
def in_out_quart(t):
    return 8 * t**4 if t < 0.5 else 1 - (-2 * t + 2) ** 4 / 2


@_reg("out_expo", "expo")
def out_expo(t):
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


@_reg("in_expo")
def in_expo(t):
    return 0.0 if t <= 0 else 2 ** (10 * t - 10)


@_reg("in_out_expo")
def in_out_expo(t):
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return 2 ** (20 * t - 10) / 2 if t < 0.5 else (2 - 2 ** (-20 * t + 10)) / 2


@_reg("out_back", "anticipate_out")
def out_back(t):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


@_reg("in_back")
def in_back(t):
    c1, c3 = 1.70158, 2.70158
    return c3 * t**3 - c1 * t**2


@_reg("out_elastic")
def out_elastic(t):
    if t in (0.0, 1.0):
        return t
    c4 = (2 * math.pi) / 3
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


@_reg("out_bounce")
def out_bounce(t):
    n1, d1 = 7.5625, 2.75
    if t < 1 / d1:
        return n1 * t * t
    if t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


@_reg("hold", "step")
def hold(t):
    return 0.0


def ease(name, t):
    t = clamp(t)
    return EASES.get(name or "in_out_cubic", in_out_cubic)(t)


# ------------------------------------------------------------------ springs
def spring(t, freq=2.2, damp=6.0, start=0.0, end=1.0):
    """Under-damped spring used for overshoot-y UI/card moves."""
    t = clamp(t)
    if t >= 1:
        return end
    x = math.exp(-damp * t) * math.cos(freq * 2 * math.pi * t)
    return start + (end - start) * (1 - x)


# ------------------------------------------------------------------ tracks
@dataclass
class Track:
    """Keyframed scalar. keys: [(t, value, ease_out_of_this_key)]"""
    keys: list = field(default_factory=list)

    def __post_init__(self):
        self.keys = sorted((float(k[0]), float(k[1]), (k[2] if len(k) > 2 else "in_out_cubic"))
                           for k in self.keys)

    @classmethod
    def const(cls, v):
        return cls([(0.0, v)])

    @classmethod
    def ramp(cls, t0, t1, v0, v1, curve="in_out_cubic"):
        return cls([(t0, v0), (t1, v1, curve)])

    def at(self, t):
        if not self.keys:
            return 0.0
        if t <= self.keys[0][0]:
            return self.keys[0][1]
        if t >= self.keys[-1][0]:
            return self.keys[-1][1]
        for i in range(len(self.keys) - 1):
            t0, v0, cv = self.keys[i]
            t1, v1, _ = self.keys[i + 1]
            if t0 <= t <= t1:
                if t1 - t0 <= 1e-9:
                    return v1
                k = (t - t0) / (t1 - t0)
                return lerp(v0, v1, ease(cv, k))
        return self.keys[-1][1]

    def __call__(self, t):
        return self.at(t)

    def shifted(self, dt):
        return Track([(t + dt, v, c) for t, v, c in self.keys])


def track(spec, default=0.0):
    """Coerce JSON (number | list of keys | {'keys': [...]}) into a Track."""
    if isinstance(spec, Track):
        return spec
    if spec is None:
        return Track.const(default)
    if isinstance(spec, (int, float)):
        return Track.const(float(spec))
    if isinstance(spec, list):
        return Track(spec)
    if isinstance(spec, dict) and "keys" in spec:
        return Track(spec["keys"])
    raise TypeError(f"bad track spec: {spec!r}")
