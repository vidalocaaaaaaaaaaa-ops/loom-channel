"""Faceless people, assembled from primitives and lit by rim light.

Every style in this skill is faceless by design: no eyes, no mouth, no identity.
The face reads as a person through silhouette, weight and rim light, which is
also why the same figure works at 4 k or at 1/8th scale.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..util import clamp, hash01, lerp, mix, rgb


def _limb(p0, p1, p2, t0, t1, t2):
    """A tapered two-segment limb (shoulder-elbow-wrist / hip-knee-ankle)."""
    def nrm(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        return (-dy / L, dx / L)
    n0, n1, n2 = nrm(p0, p1), nrm(p0, p2), nrm(p1, p2)
    poly = [
        (p0[0] + n0[0] * t0, p0[1] + n0[1] * t0),
        (p1[0] + n1[0] * t1, p1[1] + n1[1] * t1),
        (p2[0] + n2[0] * t2, p2[1] + n2[1] * t2),
        (p2[0] - n2[0] * t2, p2[1] - n2[1] * t2),
        (p1[0] - n1[0] * t1, p1[1] - n1[1] * t1),
        (p0[0] - n0[0] * t0, p0[1] - n0[1] * t0),
    ]
    return [("poly", poly)]


def _body(cam, pos, height, pose):
    """Normalised, anatomically-plausible body -> [('poly'|'ellipse', points)].

    Proportions are H-relative so the same figure works at any height: shoulder
    width 0.26 H, head r 0.062 H, hip 0.50 H, knee 0.27 H.
    """
    sx, sy, d, fog = cam.project(pos)
    if d < 0:
        return []
    H = cam.px(height, d)
    if H < 6:
        return []

    def P(nx, ny):
        """nx in units of height (0 = centre line), ny fraction of height."""
        return (sx + nx * H, sy - ny * H)

    stance = pose.get("stance", 0.030)
    lean = pose.get("lean", 0.0)
    arms = pose.get("arms", 0.0)
    hand_up = pose.get("hand_up", 0.0)
    head_tilt = pose.get("head_tilt", 0.0)
    sh_y, hip_y, knee_y, ankle_y = 0.825, 0.500, 0.270, 0.030
    sh_x = 0.115
    tilt = lean * 0.030

    shapes = []
    # --- head + neck
    hr = 0.062 * H
    hx = sx + (tilt * 2.2 + head_tilt * 0.5) * H
    hy = sy - (0.930 - abs(head_tilt) * 0.006) * H
    shapes.append(("ellipse", (hx - hr * 0.92, hy - hr * 1.06, hx + hr * 0.92, hy + hr * 1.02)))
    shapes.append(("poly", [P(-0.030 + tilt, 0.855), P(0.030 + tilt, 0.855),
                            P(0.036 + tilt * 1.4, 0.905), P(-0.036 + tilt * 1.4, 0.905)]))
    # --- torso: shoulders -> waist -> hips
    shapes.append(("poly", [
        P(-sh_x + tilt, sh_y - 0.016), P(-sh_x * 0.55 + tilt, sh_y + 0.004),
        P(sh_x * 0.55 + tilt, sh_y + 0.004), P(sh_x + tilt, sh_y - 0.016),
        P(sh_x * 1.02 + tilt, sh_y - 0.02),
        P(0.098 + tilt * 0.8, 0.640), P(0.104 + tilt * 0.6, hip_y + 0.02),
        P(0.112 + tilt * 0.4, hip_y - 0.035), P(0.070 + tilt * 0.3, hip_y - 0.055),
        P(-0.070 + tilt * 0.3, hip_y - 0.055), P(-0.112 + tilt * 0.4, hip_y - 0.035),
        P(-0.104 + tilt * 0.6, hip_y + 0.02), P(-0.098 + tilt * 0.8, 0.640),
        P(-sh_x * 1.02 + tilt, sh_y - 0.02)]))
    # --- arms: shoulder -> elbow -> wrist, tapered, with round joints
    for side in (-1, 1):
        sxp = side * sh_x + tilt * 0.9
        ex = side * (0.132 + 0.085 * arms)
        ey = 0.635 - 0.075 * arms
        wx = side * (0.150 + 0.150 * arms)
        wy = 0.455 + 0.02 * arms
        if side > 0 and hand_up > 0:
            ex = side * (0.155 + 0.03 * hand_up)
            ey = 0.690 + 0.03 * hand_up
            wx = side * (0.150 + 0.022 * hand_up)
            wy = 0.690 + 0.19 * hand_up
        p0, p1, p2 = P(sxp, sh_y - 0.012), P(ex, ey), P(wx, wy)
        shapes += _limb(p0, p1, p2, 0.032 * H, 0.025 * H, 0.018 * H)
        shapes.append(("ellipse", (p1[0] - 0.024 * H, p1[1] - 0.024 * H,
                                   p1[0] + 0.024 * H, p1[1] + 0.024 * H)))
        shapes.append(("ellipse", (p2[0] - 0.020 * H, p2[1] - 0.030 * H,
                                   p2[0] + 0.020 * H, p2[1] + 0.030 * H)))
    # --- legs: hip -> knee -> ankle
    for side in (-1, 1):
        kx = side * (0.058 + stance * 0.55)
        ax = side * (0.062 + stance)
        p0 = P(side * 0.062 + tilt * 0.2, hip_y - 0.01)
        p1 = P(kx, knee_y)
        p2 = P(ax, ankle_y)
        shapes += _limb(p0, p1, p2, 0.042 * H, 0.030 * H, 0.020 * H)
        shapes.append(("ellipse", (p1[0] - 0.029 * H, p1[1] - 0.029 * H,
                                   p1[0] + 0.029 * H, p1[1] + 0.029 * H)))
        # foot
        shapes.append(("poly", [P(ax - 0.018, ankle_y + 0.012), P(ax + 0.030, ankle_y + 0.012),
                                P(ax + 0.034, 0.0), P(ax - 0.030, 0.0)]))
    return shapes


def person(canvas, cam, pos, height=1.75, fill="#04060b", rim=None, rim_intensity=1.0,
           rim_from=None, pose=None, seed=0, occlude=True, rim_width=3, rim_falloff=1.15,
           alpha=1.0):
    """Draw a faceless figure at a world position.

    rim: colour of the edge light (usually the strongest light in the room).
    rim_from: world position of that light, so the rim lands on the correct side.
    """
    pose = pose or {}
    shapes = _body(cam, pos, height, pose)
    if not shapes:
        return
    # directional rim: in screen space, away from the light
    direction = (1.0, -0.2)
    if rim_from is not None:
        lx, ly, ld, _ = cam.project(rim_from)
        px_, py_, pd, _ = cam.project(pos)
        if ld > 0 and pd > 0:
            vx, vy = lx - px_, ly - py_
            m = math.hypot(vx, vy) or 1.0
            direction = (vx / m, vy / m)
    c = rgb(fill)
    for kind, pts in shapes:
        if kind == "poly":
            canvas.poly(pts, c, alpha)
        else:
            canvas.ellipse(pts, c, alpha)

    # masks for rim light + occlusion
    mask = Image.new("L", (canvas.lw, canvas.lh), 0)
    md = ImageDraw.Draw(mask)
    for kind, pts in shapes:
        if kind == "poly":
            md.polygon([(q[0] * canvas.ls, q[1] * canvas.ls) for q in pts],
                       fill=int(255 * alpha))
        else:
            x0, y0, x1, y1 = [v * canvas.ls for v in pts]
            md.ellipse([x0, y0, x1, y1], fill=int(255 * alpha))
    if occlude:
        canvas.occlude_mask(mask, 0.94)
    if rim:
        canvas.rim_light(mask, rim, rim_intensity * alpha, direction=direction,
                         width=rim_width, falloff=rim_falloff)


def shadow_on_floor(canvas, cam, pos, height=1.75, color="#000000", alpha=0.5, spread=1.9):
    """Soft elliptical contact shadow (screen space, additive-darkening)."""
    sx, sy, d, fog = cam.project((pos[0], 0.01, pos[2]))
    if d < 0:
        return
    w = cam.px(height * spread, d)
    h = cam.px(height * spread * 0.30, d)
    p = cam.project((pos[0], 0.0, pos[2] + height * 0.35))
    canvas.ellipse((sx - w / 2, sy - h / 2, sx + w / 2, sy + h / 2),
                   color, alpha * (0.35 + 0.65 * (1 - fog)))
