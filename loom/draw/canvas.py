"""Supersampled canvas + physically-plausible-ish light finishing.

Two buffers:
  * albedo  — geometry drawn with PIL at ss× resolution (crisp, anti-aliased on downsample)
  * light   — float32 additive buffer at half of output resolution, holds glows,
              light shafts and specular hits. It gets blurred into a bloom pass and
              is occluded by anything registered as a silhouette, so a person
              standing in a light shaft really does block it.

finish() is the "camera": exposure, filmic tonemap, grade, halation, bloom,
chromatic aberration, vignette, grain, letterbox.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..util import clamp, rgb


def _pil(c):
    return rgb(c)


class Canvas:
    def __init__(self, W, H, ss=2, bg=(0, 0, 0), light_res=2):
        self.W, self.H, self.ss = W, H, ss
        self.iw, self.ih = int(round(W * ss)), int(round(H * ss))
        self.img = Image.new("RGB", (self.iw, self.ih), _pil(bg))
        self.d = ImageDraw.Draw(self.img, "RGBA")
        self.ls = 1.0 / max(1, light_res)          # light buffer scale vs output
        self.lw, self.lh = max(1, int(W * self.ls)), max(1, int(H * self.ls))
        self.light = np.zeros((self.lh, self.lw, 3), np.float32)
        self.occ = Image.new("L", (self.lw, self.lh), 0)   # light occluders
        self.occd = ImageDraw.Draw(self.occ)
        self.tmp_layers = []

    # ------------------------------------------------------------ helpers
    def s(self, v):
        return v * self.ss

    def pts(self, points):
        s = self.ss
        return [(p[0] * s, p[1] * s) for p in points]

    # ------------------------------------------------------------ albedo ops
    def poly(self, points, color, alpha=1.0, outline=None, width=0):
        if len(points) < 3:
            return
        c = _pil(color)
        a = int(clamp(alpha) * 255)
        self.d.polygon(self.pts(points), fill=c + (a,))
        if outline:
            self.d.line(self.pts(points) + [self.pts(points)[0]],
                        fill=_pil(outline) + (a,), width=max(1, int(self.s(width))))

    def rect(self, box, color, alpha=1.0, outline=None, width=0, radius=0):
        x0, y0, x1, y1 = box
        s = self.ss
        b = [x0 * s, y0 * s, x1 * s, y1 * s]
        c = _pil(color)
        a = int(clamp(alpha) * 255)
        if radius:
            self.d.rounded_rectangle(b, radius * s, fill=c + (a,))
        else:
            self.d.rectangle(b, fill=c + (a,))
        if outline:
            ow = max(1, int(width * s))
            if radius:
                self.d.rounded_rectangle(b, radius * s, outline=_pil(outline) + (a,), width=ow)
            else:
                self.d.rectangle(b, outline=_pil(outline) + (a,), width=ow)

    def ellipse(self, box, color, alpha=1.0, outline=None, width=0):
        x0, y0, x1, y1 = [v * self.ss for v in box]
        c = _pil(color)
        a = int(clamp(alpha) * 255)
        self.d.ellipse([x0, y0, x1, y1], fill=c + (a,))
        if outline:
            self.d.ellipse([x0, y0, x1, y1], outline=_pil(outline) + (a,),
                           width=max(1, int(width * self.ss)))

    def line(self, pts, color, width=2, alpha=1.0, joint="curve"):
        self.d.line(self.pts(pts), fill=_pil(color) + (int(clamp(alpha) * 255),),
                    width=max(1, int(width * self.ss)), joint=joint)

    def polyline(self, pts, color, width=2, alpha=1.0):
        self.line(pts, color, width, alpha)

    def vgrad(self, box, top, bottom, alpha=1.0, steps=24, gamma=1.0):
        """Vertical gradient rectangle, banded smoothly (no visible steps at ss>1)."""
        x0, y0, x1, y1 = box
        h = max(1.0, y1 - y0)
        c1, c2 = _pil(top), _pil(bottom)
        a = int(clamp(alpha) * 255)
        for i in range(steps):
            k0, k1 = i / steps, (i + 1) / steps
            t = ((k0 + k1) * 0.5) ** gamma
            col = (int(c1[0] + (c2[0] - c1[0]) * t),
                   int(c1[1] + (c2[1] - c1[1]) * t),
                   int(c1[2] + (c2[2] - c1[2]) * t))
            s = self.ss
            self.d.rectangle([x0 * s, (y0 + h * k0) * s - 1,
                              x1 * s, (y0 + h * k1) * s + 1], fill=col + (a,))

    def hgrad(self, box, left, right, alpha=1.0, steps=24):
        x0, y0, x1, y1 = box
        w = max(1.0, x1 - x0)
        c1, c2 = _pil(left), _pil(right)
        a = int(clamp(alpha) * 255)
        for i in range(steps):
            k0, k1 = i / steps, (i + 1) / steps
            t = (k0 + k1) * 0.5
            col = (int(c1[0] + (c2[0] - c1[0]) * t),
                   int(c1[1] + (c2[1] - c1[1]) * t),
                   int(c1[2] + (c2[2] - c1[2]) * t))
            s = self.ss
            self.d.rectangle([(x0 + w * k0) * s - 1, y0 * s,
                              (x0 + w * k1) * s + 1, y1 * s], fill=col + (a,))

    def image(self, im: Image.Image, box=None, alpha=1.0):
        """Paste a PIL image into the albedo buffer, scaled to box (x0,y0,x1,y1)."""
        if box:
            x0, y0, x1, y1 = box
            w, h = int((x1 - x0) * self.ss), int((y1 - y0) * self.ss)
            if w <= 0 or h <= 0:
                return
            im = im.convert("RGB").resize((w, h), Image.LANCZOS)
            pos = (int(x0 * self.ss), int(y0 * self.ss))
        else:
            pos = (0, 0)
        if alpha < 1.0:
            im = im.convert("RGB")
            base = self.img.crop((pos[0], pos[1], pos[0] + im.width, pos[1] + im.height))
            im = Image.blend(base, im, alpha)
        self.img.paste(im.convert("RGB"), pos)

    def blur_region(self, box, radius):
        """Soft-focus a region of the albedo buffer (used for out-of-focus backgrounds)."""
        x0, y0, x1, y1 = [int(v * self.ss) for v in box]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.iw, x1), min(self.ih, y1)
        if x1 <= x0 or y1 <= y0:
            return
        region = self.img.crop((x0, y0, x1, y1)).filter(
            ImageFilter.GaussianBlur(max(1, radius * self.ss)))
        self.img.paste(region, (x0, y0))

    # ------------------------------------------------------------ light ops
    def _light_bbox(self, pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def light_poly(self, points, color, intensity=1.0, soft=0):
        """Additive light from a world-space polygon."""
        if len(points) < 3:
            return
        mask = Image.new("L", (self.lw, self.lh), 0)
        ImageDraw.Draw(mask).polygon(
            [(p[0] * self.ls, p[1] * self.ls) for p in points], fill=255)
        if soft:
            mask = mask.filter(ImageFilter.GaussianBlur(max(0.6, soft * self.ls)))
        m = np.asarray(mask, np.float32) / 255.0
        m *= intensity
        for i in range(3):
            self.light[:, :, i] += m * _pil(color)[i] / 255.0

    def glow(self, center, radius, color, intensity=1.0, falloff=2.0):
        """Radial glow (screen-space px). Falloff > 1 = tighter core."""
        cx, cy = center[0] * self.ls, center[1] * self.ls
        r = max(1.0, radius * self.ls)
        x0, x1 = int(max(0, cx - r)), int(min(self.lw, cx + r + 2))
        y0, y1 = int(max(0, cy - r)), int(min(self.lh, cy + r + 2))
        if x1 <= x0 or y1 <= y0:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        f = np.clip(1.0 - d, 0.0, 1.0) ** falloff
        c = _pil(color)
        for i in range(3):
            self.light[y0:y1, x0:x1, i] += f * intensity * c[i] / 255.0

    def light_cone(self, apex, spread_pts, color, intensity=1.0, soft=6.0):
        """A volumetric shaft: apex + far edge points; softened edges."""
        self.light_poly([apex] + list(spread_pts), color, intensity, soft=soft)

    def occlude_poly(self, points, strength=1.0):
        """Register a silhouette that blocks light (drawn after the light it blocks)."""
        ImageDraw.Draw(self.occ).polygon(
            [(p[0] * self.ls, p[1] * self.ls) for p in points],
            fill=int(clamp(strength) * 255))

    def occlude_ellipse(self, box, strength=1.0):
        x0, y0, x1, y1 = [v * self.ls for v in box]
        ImageDraw.Draw(self.occ).ellipse([x0, y0, x1, y1], fill=int(clamp(strength) * 255))

    def occlude_mask(self, mask: Image.Image, strength=1.0):
        """Register an arbitrary silhouette mask as a light occluder."""
        m = mask
        if m.size != (self.lw, self.lh):
            m = m.resize((self.lw, self.lh), Image.BILINEAR)
        if strength < 1.0:
            m = m.point(lambda v: int(v * strength))
        self.occ = ImageChops.lighter(self.occ, m)
        self.occd = ImageDraw.Draw(self.occ)

    def rim_light(self, mask: Image.Image, color="#ff5a2b", intensity=1.0,
                  direction=(1.0, 0.0), width=3, falloff=2.4):
        """Add a directional rim/edge light to the light buffer from a silhouette
        mask. This is what makes a black shape read as a person in a dark room."""
        if mask.size != (self.lw, self.lh):
            mask = mask.resize((self.lw, self.lh), Image.BILINEAR)
        k = max(1, width | 1)
        eroded = mask.filter(ImageFilter.MinFilter(k * 2 + 1))
        edge = ImageChops.subtract(mask, eroded)
        e = np.asarray(edge, np.float32) / 255.0
        bbox = mask.getbbox()
        if e.max() <= 0.0 or not bbox:
            return
        dx, dy = direction
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        w, h = mask.size
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        x0, y0, x1, y1 = bbox
        nx = (xx - x0) / max(1.0, (x1 - x0))
        ny = (yy - y0) / max(1.0, (y1 - y0))
        d = ((nx - 0.5) * dx + (ny - 0.5) * dy) * 2.0      # -1 .. 1 across the bbox
        ramp = np.clip(d * 1.35 + 0.22, 0, 1) ** max(1.0, falloff)
        w_ = e * ramp * intensity
        c = _pil(color)
        for i in range(3):
            self.light[:, :, i] += w_ * c[i] / 255.0

    def bloom_source(self, im: Image.Image, alpha=1.0):
        """Feed an image region into the light buffer (for glowing screens, neon)."""
        small = im.convert("RGB").resize((self.lw, self.lh), Image.BILINEAR)
        arr = np.asarray(small, np.float32) / 255.0
        self.light += arr * alpha

    # ------------------------------------------------------------ finish
    def finish(self, fp=None, *, exposure=1.0, contrast=1.08, saturation=1.0,
               bloom=0.55, halation=0.18, grain=0.030, vignette=0.45,
               ca=0.0, tint=None, gamma=1.0, letterbox=0.0, tonemap="aces",
               bloom_radius=18, light_blur=1.6, scrim=0.0, scrim_top=0.0,
               scrim_color=(0, 0, 0), split=None):
        """Grade the frame and return a PIL RGB image at output resolution."""
        fp = 0 if fp is None else fp
        rgbimg = self.img.resize((self.W, self.H), Image.LANCZOS)
        base = np.asarray(rgbimg, np.float32) / 255.0

        # ---- light buffer -> occlusion -> bloom
        light = self.light
        if self.occ.getbbox() is not None:
            o = np.asarray(self.occ.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255.0
            light = light * (1.0 - 0.92 * o[:, :, None])
        if light_blur:
            li = Image.fromarray(np.clip(light * 255.0, 0, 255).astype(np.uint8))
            li = li.filter(ImageFilter.GaussianBlur(light_blur))
            light = np.asarray(li, np.float32) / 255.0
        light_full = np.asarray(
            Image.fromarray(np.clip(light * 255, 0, 255).astype(np.uint8))
            .resize((self.W, self.H), Image.BILINEAR), np.float32) / 255.0

        add = light_full * exposure
        img = base * exposure + add

        if bloom > 0:
            src = Image.fromarray(np.clip(add * 255 * 2.0, 0, 255).astype(np.uint8))
            b = src.resize((max(1, self.W // 4), max(1, self.H // 4)), Image.BILINEAR)
            b = b.filter(ImageFilter.GaussianBlur(max(1.0, bloom_radius / 4)))
            b = b.resize((self.W, self.H), Image.BILINEAR)
            img = img + np.asarray(b, np.float32) / 255.0 * bloom

        if halation > 0:
            lum = img.max(axis=2)
            hot = np.clip((lum - 0.72) / 0.28, 0, 1)[:, :, None]
            h = Image.fromarray((hot[:, :, 0] * 255).astype(np.uint8))
            h = h.filter(ImageFilter.GaussianBlur(max(2.0, self.W / 90)))
            hh = np.asarray(h, np.float32) / 255.0
            img = img + hh[:, :, None] * halation * np.array([1.0, 0.42, 0.22], np.float32)

        # ---- tonemap
        img = np.clip(img, 0, None)
        if tonemap == "aces":
            img = (img * (2.51 * img + 0.03)) / (img * (2.43 * img + 0.59) + 0.14)
        elif tonemap == "reinhard":
            img = img / (1.0 + img)
        img = np.clip(img, 0, 1)

        # ---- grade: contrast around 0.5, saturation, tint
        img = (img - 0.5) * contrast + 0.5
        if gamma != 1.0:
            img = np.clip(img, 0, 1) ** (1.0 / gamma)
        if saturation != 1.0:
            l = (img * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(axis=2, keepdims=True)
            img = l + (img - l) * saturation
        if tint:
            t = np.array(_pil(tint), np.float32) / 255.0
            img = img * (0.82 + 0.18 * t * 2.0)

        # ---- split toning: cool shadows, warm highlights (film, not digital)
        if split:
            sh_c, hl_c, amt = split
            L = img.mean(axis=2, keepdims=True)
            sh_t = np.array(_pil(sh_c), np.float32) / 255.0 - 0.5
            hl_t = np.array(_pil(hl_c), np.float32) / 255.0 - 0.5
            w_sh = (1.0 - L) ** 2.0
            w_hl = L ** 2.0
            img = img + sh_t * w_sh * amt + hl_t * w_hl * amt

        # ---- lens: chromatic aberration on the edges
        if ca > 0:
            img = _chromatic(img, ca)

        # ---- caption scrim: a soft dark wash where the words will sit
        if scrim > 0 or scrim_top > 0:
            yy = np.linspace(0.0, 1.0, self.H, dtype=np.float32)[:, None]
            v = np.ones((self.H, self.W), np.float32)
            if scrim > 0:
                k = np.clip((yy - 0.46) / 0.42, 0, 1) ** 1.35
                v *= (1.0 - scrim * k)
            if scrim_top > 0:
                k2 = np.clip((0.30 - yy) / 0.30, 0, 1) ** 1.35
                v *= (1.0 - scrim_top * k2)
            t = np.array(_pil(scrim_color), np.float32) / 255.0
            img = img * v[:, :, None] + (1.0 - v[:, :, None]) * t * 0.9

        # ---- vignette
        if vignette > 0:
            yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
            cx, cy = self.W * 0.5, self.H * 0.5
            r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / 1.4142
            v = np.clip(1.0 - vignette * (r ** 2.2) * 1.25, 0.0, 1.0)
            img = img * v[:, :, None]

        # ---- grain (film-like, chroma-keyed to midtones)
        if grain > 0:
            rng = np.random.default_rng(1000 + fp)
            n = rng.normal(0.0, 1.0, (self.H, self.W, 1)).astype(np.float32)
            n = np.repeat(n, 3, axis=2)
            mid = 1.0 - np.abs(img.mean(axis=2, keepdims=True) - 0.45) * 1.4
            img = img + n * grain * np.clip(mid, 0.25, 1.0)

        img = np.clip(img, 0, 1)
        out = Image.fromarray((img * 255 + 0.5).astype(np.uint8))

        if letterbox > 0:
            bar = int(self.H * letterbox)
            d = ImageDraw.Draw(out)
            d.rectangle([0, 0, self.W, bar], fill=(0, 0, 0))
            d.rectangle([0, self.H - bar, self.W, self.H], fill=(0, 0, 0))
        return out


def _chromatic(img, amount):
    """Shift R and B radially for cheap lens fringing."""
    h, w, _ = img.shape
    out = img.copy()
    shift = max(1, int(round(amount)))
    out[:, shift:, 0] = img[:, :-shift, 0]
    out[:, :-shift, 2] = img[:, shift:, 2]
    return out


class Gfx:
    """Graphics pass: runs at output resolution, after the grade, so captions
    and cards stay crisp and are never eaten by grain or aberration."""

    def __init__(self, im: Image.Image):
        self.im = im
        self.d = ImageDraw.Draw(im, "RGBA")
        self.W, self.H = im.size

    def text(self, xy, s, font, fill, anchor="la", stroke=0, stroke_fill=None,
             alpha=1.0, spacing=0):
        fill = _pil(fill) + (int(clamp(alpha) * 255),)
        sf = None
        if stroke and stroke_fill:
            sf = _pil(stroke_fill) + (int(clamp(alpha) * 255),)
        if spacing:
            s = (" " * spacing).join(list(s)) if spacing > 0 else s
        self.d.text(xy, s, font=font, fill=fill, anchor=anchor,
                    stroke_width=int(stroke), stroke_fill=sf)

    def rect(self, box, fill=(0, 0, 0), alpha=1.0, radius=0):
        x0, y0, x1, y1 = box
        c = _pil(fill) + (int(clamp(alpha) * 255),)
        if radius:
            self.d.rounded_rectangle([x0, y0, x1, y1], radius, fill=c)
        else:
            self.d.rectangle([x0, y0, x1, y1], fill=c)

    def blend(self, other: Image.Image, alpha=1.0):
        if alpha >= 1.0:
            self.im.paste(other, (0, 0))
        else:
            self.im.paste(Image.blend(self.im, other.convert("RGB"), alpha), (0, 0))


def text_size(draw, s, font):
    b = draw.textbbox((0, 0), s, font=font)
    return b[2] - b[0], b[3] - b[1], b


def soft_shadow(canvas: Canvas, draw_fn, radius=18, alpha=0.55, offset=(0, 6), color=(0, 0, 0)):
    """Render draw_fn into a mask, blur it, composite under the subject."""
    layer = Image.new("L", (canvas.lw, canvas.lh), 0)
    draw_fn(ImageDraw.Draw(layer), 255)
    layer = layer.filter(ImageFilter.GaussianBlur(max(1.0, radius * canvas.ls)))
    arr = np.asarray(layer, np.float32) / 255.0 * alpha
    arr = np.asarray(Image.fromarray((arr * 255).astype(np.uint8))
                     .resize((canvas.W, canvas.H), Image.BILINEAR), np.float32) / 255.0
    shadow = Image.new("RGB", (canvas.W, canvas.H), _pil(color))
    mask = Image.fromarray((arr * 255).astype(np.uint8))
    canvas.img.paste(shadow, (0, 0), mask)
