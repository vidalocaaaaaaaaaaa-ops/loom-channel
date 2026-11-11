"""Deterministic value noise + fBm, used for handheld cameras, dust, rain, flicker."""
from __future__ import annotations

import math

from .util import hash01, lerp


def _grad1(i, seed):
    return hash01(i, seed) * 2.0 - 1.0


def noise1(x, seed=0):
    """Smooth 1-D value noise in [-1, 1]."""
    i = math.floor(x)
    f = x - i
    u = f * f * (3 - 2 * f)
    return lerp(_grad1(i, seed), _grad1(i + 1, seed), u)


def noise2(x, y, seed=0):
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    ux = fx * fx * (3 - 2 * fx)
    uy = fy * fy * (3 - 2 * fy)
    a = hash01(ix, iy, seed)
    b = hash01(ix + 1, iy, seed)
    c = hash01(ix, iy + 1, seed)
    d = hash01(ix + 1, iy + 1, seed)
    return lerp(lerp(a, b, ux), lerp(c, d, ux), uy) * 2.0 - 1.0


def fbm1(x, octaves=4, seed=0, lac=2.0, gain=0.5):
    amp, freq, total, norm = 1.0, 1.0, 0.0, 0.0
    for o in range(octaves):
        total += amp * noise1(x * freq, seed + o * 17)
        norm += amp
        amp *= gain
        freq *= lac
    return total / max(norm, 1e-9)


def fbm2(x, y, octaves=4, seed=0, lac=2.0, gain=0.5):
    amp, freq, total, norm = 1.0, 1.0, 0.0, 0.0
    for o in range(octaves):
        total += amp * noise2(x * freq, y * freq, seed + o * 31)
        norm += amp
        amp *= gain
        freq *= lac
    return total / max(norm, 1e-9)


class Drift:
    """Smooth pseudo-random wander in [-1,1] on several channels.

    handheld(t) gives 6 numbers: x, y, roll, zoom, and two extra channels.
    Deterministic, so re-renders are identical frame for frame.
    """

    def __init__(self, seed=0, speed=0.35):
        self.seed = seed
        self.speed = speed

    def ch(self, t, i=0):
        return fbm1(t * self.speed + i * 9.13, octaves=3, seed=self.seed + i * 101)

    def handheld(self, t):
        return (self.ch(t, 0), self.ch(t, 1), self.ch(t, 2) * 0.35,
                self.ch(t, 3) * 0.5, self.ch(t, 4), self.ch(t, 5))


class Flicker:
    """Lamp / neon / fluorescent flicker: mostly steady with rare stutters."""

    def __init__(self, seed=3, rate=11.0, depth=0.35):
        self.seed, self.rate, self.depth = seed, rate, depth

    def at(self, t):
        n = noise1(t * self.rate, self.seed)
        spike = max(0.0, noise1(t * self.rate * 0.31, self.seed + 7) - 0.55) * 3.0
        return 1.0 - self.depth * (0.5 + 0.5 * n) * (0.25 + spike)
