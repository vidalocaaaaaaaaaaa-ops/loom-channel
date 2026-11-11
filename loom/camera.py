"""A tiny pinhole camera. Every style paints in world space; the camera
supplies push-ins, parallax, handheld float and shake for free.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import noise
from .ease import Track, track
from .util import clamp, lerp, smoothstep


@dataclass
class V3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, o):
        return V3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o):
        return V3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __mul__(self, s):
        return V3(self.x * s, self.y * s, self.z * s)

    def as_tuple(self):
        return (self.x, self.y, self.z)


@dataclass
class Camera:
    """Pinhole camera. Angles in degrees, world units are metres."""
    W: int
    H: int
    pos: V3 = field(default_factory=lambda: V3(0, 1.6, 0))
    yaw: float = 0.0          # + = look right
    pitch: float = 0.0        # + = look up
    roll: float = 0.0         # degrees
    fov: float = 55.0         # vertical field of view
    near: float = 0.08

    # -- projection ---------------------------------------------------
    @property
    def focal(self):
        return (self.H * 0.5) / math.tan(math.radians(self.fov) * 0.5)

    def project(self, p: V3 | tuple, fog=(0.0, 12.0)):
        """World point -> (sx, sy, depth, fog01). depth <= 0 means behind."""
        if not isinstance(p, V3):
            p = V3(*p)
        dx, dy, dz = p.x - self.pos.x, p.y - self.pos.y, p.z - self.pos.z
        cy, sy_ = math.cos(-self.yaw), math.sin(-self.yaw)
        dx, dz = dx * cy + dz * sy_, -dx * sy_ + dz * cy
        cp, sp = math.cos(-self.pitch), math.sin(-self.pitch)
        dy, dz = dy * cp + dz * sp, -dy * sp + dz * cp
        if self.roll:
            cr, sr = math.cos(math.radians(-self.roll)), math.sin(math.radians(-self.roll))
            dx, dy = dx * cr - dy * sr, dx * sr + dy * cr
        if dz <= self.near:
            depth = self.near
            behind = True
        else:
            depth = dz
            behind = False
        sx = self.W * 0.5 + self.focal * dx / depth
        sy = self.H * 0.5 - self.focal * dy / depth
        f = smoothstep(fog[0], fog[1], depth)
        return (sx, sy, depth, f) if not behind else (sx, sy, -1.0, f)

    def project_poly(self, pts, fog=(0.0, 12.0)):
        out = [self.project(p, fog) for p in pts]
        if any(o[2] < 0 or o[2] == -1.0 for o in out):
            return None
        return [(o[0], o[1]) for o in out]

    def px(self, world_units, depth):
        """Convert a world length at a depth into pixels."""
        return world_units * self.focal / max(depth, 1e-4)

    def billboard(self, p: V3, w_units: float, h_units: float, fog=(0.0, 12.0)):
        """Screen-space box for a billboarded quad. -> (x, y, w_px, h_px, depth, fog01)"""
        sx, sy, depth, f = self.project(p, fog)
        if depth < 0:
            return (sx, sy, 0, 0, -1, f)
        return (sx, sy, self.px(w_units, depth), self.px(h_units, depth), depth, f)


# ------------------------------------------------------------------ rigs
class Rig:
    """Builds a Camera per frame from tracks + procedural drift + shake."""

    def __init__(self, W, H, spec: dict | None = None, seed: int = 0):
        spec = spec or {}
        self.W, self.H = W, H
        self.base_pos = V3(*spec.get("pos", (0.0, 1.6, 0.0)))
        self.yaw = track(spec.get("yaw"), 0.0)
        self.pitch = track(spec.get("pitch"), 0.0)
        self.roll = track(spec.get("roll"), 0.0)
        self.fov = track(spec.get("fov"), spec.get("fov_default", 55.0))
        self.pos_x = track(spec.get("x"), self.base_pos.x)
        self.pos_y = track(spec.get("y"), self.base_pos.y)
        self.pos_z = track(spec.get("z"), self.base_pos.z)
        self.hand = spec.get("handheld", 0.0)
        self.drift = noise.Drift(seed=seed, speed=spec.get("handheld_speed", 0.35))
        self.shakes = [self._mk_shake(s) for s in spec.get("shakes", [])]

    @staticmethod
    def _mk_shake(s):
        t0 = float(s.get("at", 0.0))
        return (t0, float(s.get("amount", 0.12)), float(s.get("decay", 5.0)),
                float(s.get("freq", 17.0)), int(s.get("seed", 1)))

    def camera(self, t, t_local=None):
        tl = t if t_local is None else t_local
        pos = V3(self.pos_x(tl), self.pos_y(tl), self.pos_z(tl))
        yaw, pitch, roll = self.yaw(tl), self.pitch(tl), self.roll(tl)
        fov = self.fov(tl)
        if self.hand:
            hx, hy, hr, hz, _, _ = self.drift.handheld(t)
            a = self.hand
            yaw += hx * 0.45 * a
            pitch += hy * 0.40 * a
            roll += hr * 1.4 * a
            pos = pos + V3(hx * 0.02 * a, hy * 0.015 * a, hz * 0.01 * a)
        for (t0, amt, decay, freq, seed) in self.shakes:
            dt = tl - t0
            if 0 <= dt < 3.0:
                k = amt * math.exp(-decay * dt)
                yaw += k * 9.0 * noise.noise1(dt * freq, seed)
                pitch += k * 9.0 * noise.noise1(dt * freq + 5.0, seed + 3)
                roll += k * 6.0 * noise.noise1(dt * freq + 9.0, seed + 7)
        return Camera(self.W, self.H, pos=pos, yaw=yaw, pitch=pitch, roll=roll, fov=fov)


class FlatRig:
    """2-D camera for flat styles: zoom/pan around a focus point."""

    def __init__(self, W, H, spec: dict | None = None):
        spec = spec or {}
        self.W, self.H = W, H
        self.zoom = track(spec.get("zoom"), 1.0)
        self.cx = track(spec.get("cx"), 0.5)   # normalised focus
        self.cy = track(spec.get("cy"), 0.5)
        self.rot = track(spec.get("rot"), 0.0)
        self.shake = track(spec.get("shake"), 0.0)

    def view(self, t):
        z = self.zoom(t)
        cx, cy = self.cx(t), self.cy(t)
        # top-left of the source rect that fills the frame
        ox = cx * self.W - self.W / (2 * z)
        oy = cy * self.H - self.H / (2 * z)
        return (ox, oy, z, self.rot(t), self.shake(t))


# ------------------------------------------------------------------ clipping
def _to_cam(cam: Camera, p):
    if not isinstance(p, V3):
        p = V3(*p)
    dx, dy, dz = p.x - cam.pos.x, p.y - cam.pos.y, p.z - cam.pos.z
    cy, sy = math.cos(-cam.yaw), math.sin(-cam.yaw)
    dx, dz = dx * cy + dz * sy, -dx * sy + dz * cy
    cp, sp = math.cos(-cam.pitch), math.sin(-cam.pitch)
    dy, dz = dy * cp + dz * sp, -dy * sp + dz * cp
    if cam.roll:
        cr, sr = math.cos(math.radians(-cam.roll)), math.sin(math.radians(-cam.roll))
        dx, dy = dx * cr - dy * sr, dx * sr + dy * cr
    return (dx, dy, dz)


def _proj_cam(cam: Camera, c):
    x, y, z = c
    z = max(z, cam.near)
    return (cam.W * 0.5 + cam.focal * x / z, cam.H * 0.5 - cam.focal * y / z, z)


def clip_poly(cam: Camera, pts3):
    """Project a world-space polygon, clipping against the near plane.
    Returns screen-space points, or None if entirely behind the camera."""
    cam_pts = [_to_cam(cam, p) for p in pts3]
    if all(c[2] <= cam.near for c in cam_pts):
        return None
    if all(c[2] > cam.near for c in cam_pts):
        return [(p[0], p[1]) for p in (_proj_cam(cam, c) for c in cam_pts)]
    out, n = [], len(cam_pts)
    for i in range(n):
        a, b = cam_pts[i], cam_pts[(i + 1) % n]
        ain, bin_ = a[2] > cam.near, b[2] > cam.near
        if ain:
            out.append(a)
        if ain != bin_:
            t = (cam.near - a[2]) / (b[2] - a[2])
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, cam.near))
    if len(out) < 3:
        return None
    return [(p[0], p[1]) for p in (_proj_cam(cam, c) for c in out)]


def depth_of(cam: Camera, p):
    return _to_cam(cam, p)[2]
