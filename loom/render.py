"""Frame loop. Paints shots into the canvas, blends transitions, writes frames
straight into ffmpeg over a pipe (no PNG spill, no intermediate files).

Speed: a 1080x1920 frame costs ~120-200 ms at ss=2 on one core, so a 45 s
vertical short is a 3-5 minute render, or ~35 s in --draft. Frames are pure
functions of (project, t), so the output is bit-identical on every machine.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

from . import qc
from .draw.canvas import Canvas, Gfx
from .draw.typekit import CaptionRenderer, CaptionStyle
from .ease import Track, track
from .util import clamp, mix


def ffmpeg_exe():
    exe = os.environ.get("LOOM_FFMPEG")
    if exe and os.path.exists(exe):
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _interp(a, b, k):
    if isinstance(a, Image.Image):
        return Image.blend(a, b, k)
    return a + (b - a) * k


TRANSITIONS = {"cut", "dissolve", "dip", "flash", "whip", "slide_up", "blur_dissolve"}


def _blend_frames(fa, fb, k, kind, W=None, H=None):
    """fa = outgoing, fb = incoming, k in 0..1. Sizes come from the frames, so
    this works identically at draft scale and at full size."""
    W, H = fa.size
    if kind == "cut":
        return fb if k > 0.5 else fa
    if kind == "dissolve":
        return Image.blend(fa, fb, k)
    if kind == "blur_dissolve":
        b = Image.blend(fa, fb, k)
        from PIL import ImageFilter
        r = 12 * math.sin(math.pi * k)
        return b.filter(ImageFilter.GaussianBlur(r)) if r > 0.5 else b
    if kind == "dip":
        if k < 0.5:
            return Image.blend(fa, Image.new("RGB", (W, H), (0, 0, 0)), k * 2)
        return Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), fb, (k - 0.5) * 2)
    if kind == "flash":
        f = math.sin(math.pi * k) ** 2
        base = fa if k < 0.5 else fb
        return Image.blend(base, Image.new("RGB", (W, H), (255, 246, 230)), f * 0.85)
    if kind == "slide_up":
        out = Image.new("RGB", (W, H))
        off = int(H * k)
        out.paste(fa, (0, -off))
        out.paste(fb, (0, H - off))
        return out
    if kind == "whip":
        out = Image.new("RGB", (W, H))
        off = int(W * 0.18 * math.sin(math.pi * k))
        out.paste(fa, (-off, 0))
        out.paste(fb, (W - off - int(W * k * 0.15), 0))
        from PIL import ImageFilter
        return out.filter(ImageFilter.GaussianBlur(3 + 9 * math.sin(math.pi * k)))
    return Image.blend(fa, fb, k)


class Renderer:
    def __init__(self, project, style_module, scale=1.0, ss=2, still=False, verbose=True):
        self.p = project
        self.mod = style_module
        self.scale = scale
        self.ss = ss
        self.still_mode = still
        self.verbose = verbose
        self.W = self.p.W
        self.H = self.p.H
        self.draft = scale < 1.0
        sc = project.data.get("captions") or {}
        self.cap_style = CaptionStyle(**{k: v for k, v in sc.items()
                                         if k in CaptionStyle.__dataclass_fields__})
        self.caption = CaptionRenderer(self.W, self.H, self.cap_style, project.platform)
        self.grade = project.data.get("grade", {})
        self._cap_index = None

    # ---------------------------------------------------------------- helpers
    def sized(self):
        return int(round(self.W * self.scale)), int(round(self.H * self.scale))

    def caption_groups(self):
        """Chunk the word list once; groups are shared by every frame."""
        if self._cap_index is None:
            from .draw.typekit import chunk_words
            words = self.p.caption_words()
            self._cap_index = []
            for gi, g in enumerate(chunk_words(words, self.cap_style)):
                self._cap_index.append((f"g{gi}", g))
        return self._cap_index

    def groups_at(self, t, pad=0.0):
        out = []
        for key, g in self.caption_groups():
            if g[0]["start"] - pad <= t <= g[-1]["end"] + 0.25 + pad:
                out.append((key, g))
        return out

    # ---------------------------------------------------------------- shots
    def paint_shot(self, shot, tl):
        canvas = Canvas(self.sized()[0], self.sized()[1], ss=self.ss,
                        bg=self.mod.CANVAS_BG if hasattr(self.mod, "CANVAS_BG") else (0, 0, 0))
        ctx = dict(project=self.p, W=self.sized()[0], H=self.sized()[1],
                   scale=self.scale, seed=self.p.seed, shot=shot, style=self.mod,
                   draft=self.draft, t_abs=shot.start + tl, module=self.mod)
        cam = self.mod.camera_for(shot, ctx, tl)
        ctx["camera"] = cam
        self.mod.paint(shot, canvas, cam, tl, ctx)
        g = dict(self.grade)
        g.update(shot.grade or {})
        im = canvas.finish(fp=int(round((shot.start + tl) * self.p.fps)), **g)
        if getattr(self.mod, "FLAT", False) and not self.draft:
            # flat styles get a real camera move by scaling + cropping the painted frame
            try:
                ox, oy, z, rot, _ = cam.view(tl)
                if z and abs(z - 1.0) > 1e-3:
                    W, H = im.size
                    im = im.resize((W, H), Image.LANCZOS,
                                   box=(ox, oy, ox + W / z, oy + H / z))
            except Exception:
                pass
        return im, ctx

    def frame(self, t):
        i, shot = self.p.shot_at(t)
        im, ctx = self.paint_shot(shot, t - shot.start)
        # transition with the previous shot
        if i > 0 and shot.transition not in ("cut",) and shot.transition_dur > 0:
            prev = self.p.shots[i - 1]
            d = shot.transition_dur
            if t - shot.start < d:
                k = clamp((t - shot.start) / d)
                pim, pctx = self.paint_shot(prev, max(0.0, t - prev.start))
                im = _blend_frames(pim, im, k, shot.transition, self.W, self.H)
        gfx = Gfx(im)
        # shot graphics (dates, titles, cards)
        if shot.gfx:
            shot.gfx(gfx, t - shot.start, ctx)
        if self.mod.gfx:
            self.mod.gfx(shot, gfx, t - shot.start, ctx)
        # captions — only the newest group is drawn. Two groups are "live" for up
        # to 0.25 s after their last word (that tail is what stops captions
        # flickering off early), and drawing both stacks two blocks on top of
        # each other at the same anchor.
        caps = self.groups_at(t)
        if caps:
            key, grp = caps[-1]
            self.caption.draw(gfx, t, key, grp)
        return im

    # ---------------------------------------------------------------- encode
    def _encode_part(self, out_path, audio, crf, preset, fps, f0, f1, tune=None,
                     threads=2, part_idx=0):
        """Encode frames [f0, f1) to one mp4 part."""
        W, H = self.sized()
        n = f1 - f0
        cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
               "-i", "-", "-an",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
               "-pix_fmt", "yuv420p", "-g", str(fps * 2), "-bf", "2",
               "-threads", str(threads),
               "-x264-params", "rc-lookahead=16:sync-lookahead=0:ref=2"]
        if tune:
            cmd += ["-tune", tune]
        cmd += [out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        t0 = time.time()
        ok = True
        for fi in range(n):
            t = (f0 + fi) / fps
            im = self.frame(t)
            if im.size != (W, H):
                im = im.resize((W, H), Image.LANCZOS)
            try:
                proc.stdin.write(im.tobytes())
            except (BrokenPipeError, ValueError):
                ok = False
                break
            if self.verbose and (fi % max(1, n // 10) == 0 or fi == n - 1):
                el = time.time() - t0
                eta = el / (fi + 1) * (n - fi - 1)
                sys.stdout.write(f"\r  part {part_idx}  {fi+1}/{n} frames  "
                                 f"{el:5.1f}s  eta {eta:5.1f}s      ")
                sys.stdout.flush()
        try:
            proc.stdin.close()
        except Exception:
            pass
        err = proc.stderr.read().decode(errors="ignore")
        rc = proc.wait()
        if self.verbose:
            print()
        if not ok or rc != 0:
            raise RuntimeError(f"encoder died on frames {f0}-{f1} (rc={rc}): {err[-600:]}")
        return out_path

    def encode(self, out_path, audio=None, crf=18, preset="medium", from_t=0.0, to_t=None,
               fps=None, tune=None, chunk_seconds=12.0, resume=True):
        """Render in parts, then concatenate.

        Parts exist because a single x264 process on a 1080x1920 stream can grow to
        well over a gigabyte on a small machine, and an OOM kills the whole render.
        Chunking bounds the memory, and because parts are files on disk a render
        that dies at 80% resumes instead of restarting.
        """
        W, H = self.sized()
        fps = fps or self.p.fps
        dur = self.p.duration if to_t is None else to_t
        total = max(1, int(round((dur - from_t) * fps)))
        f0 = int(round(from_t * fps))
        chunk = max(24, int(chunk_seconds * fps))
        parts_dir = os.path.join(os.path.dirname(os.path.abspath(out_path)), "_parts")
        os.makedirs(parts_dir, exist_ok=True)
        base = os.path.basename(out_path).replace(".mp4", "")
        parts, done = [], 0
        i = 0
        while done < total:
            a = f0 + done
            b = min(f0 + total, a + chunk)
            part = os.path.join(parts_dir, f"{base}_{i:04d}.mp4")
            if not (resume and os.path.exists(part) and os.path.getsize(part) > 1024):
                try:
                    self._encode_part(part, audio, crf, preset, fps, a, b, tune,
                                      part_idx=i)
                except RuntimeError as e:
                    if self.verbose:
                        print(f"  retrying frames {a}-{b} with a lighter preset ({e})")
                    self._encode_part(part, audio, crf + 1, "veryfast", fps, a, b, tune,
                                      threads=1, part_idx=i)
            parts.append(part)
            done = b - f0
            i += 1
            if self.verbose:
                print(f"  {done}/{total} frames  ({done/max(1,total)*100:4.1f}%)")

        # concatenate (stream copy: no re-encode, no quality loss)
        listfile = os.path.join(parts_dir, f"{base}_list.txt")
        with open(listfile, "w") as fh:
            for pt in parts:
                fh.write(f"file '{os.path.abspath(pt)}'\n")
        if audio:
            cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "concat", "-safe", "0", "-i", listfile, "-i", audio,
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                   "-movflags", "+faststart", out_path]
        else:
            cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "concat", "-safe", "0", "-i", listfile,
                   "-c", "copy", "-movflags", "+faststart", out_path]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"concat failed: {p.stderr[-800:]}")
        return out_path

    # ---------------------------------------------------------------- stills
    def still(self, t):
        return self.frame(t)


def draft_audio_note(p):
    return p.p("data", "mix.wav")
