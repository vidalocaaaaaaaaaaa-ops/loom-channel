"""Package a finished project: share copy, cover frame, title/caption/hashtags.

The share copy matters more than people expect: TikTok and Reels both re-encode
uploads, and a 90 MB master loses more in that round trip than a 25 MB file
does. So the master stays pristine and a separate `share.mp4` is cut for
upload.
"""
from __future__ import annotations

import json
import os
import subprocess

import numpy as np
from PIL import Image, ImageFilter

from .render import ffmpeg_exe

PLATFORM_LIMITS = {
    "tiktok": dict(seconds=180, mb=72, hashtags=6),
    "reels": dict(seconds=90, mb=48, hashtags=8),
    "shorts": dict(seconds=180, mb=72, hashtags=5),
    "youtube": dict(seconds=3600, mb=256, hashtags=8),
}


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-1500:])
    return p.stdout


def make_share(master, out, crf=20, preset="slow", target_mb=None):
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", master,
           "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", out]
    _run(cmd)
    if target_mb and os.path.getsize(out) / 1e6 > target_mb:
        for c in (22, 24, 26, 28):
            _run([ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", master,
                  "-c:v", "libx264", "-crf", str(c), "-preset", preset,
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                  "-movflags", "+faststart", out])
            if os.path.getsize(out) / 1e6 <= target_mb:
                break
    return out


def grab_frame(master, t, out):
    _run([ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t),
          "-i", master, "-frames:v", "1", "-q:v", "2", out])
    return out


def _score(im):
    g = im.convert("L")
    edges = np.asarray(g.filter(ImageFilter.FIND_EDGES), np.float32) / 255.0
    a = np.asarray(g, np.float32) / 255.0
    detail = float(edges.std())
    lum = float(a.mean())
    light = 1.0 - min(1.0, abs(lum - 0.34) / 0.34)
    # prefer frames whose middle third has a subject, not a flat wall
    mid = a[int(a.shape[0] * 0.25):int(a.shape[0] * 0.7), :]
    subject = float(np.percentile(np.abs(mid - mid.mean()), 92))
    return detail * 0.45 + light * 0.35 + subject * 0.2


def pick_cover(p, master, samples=14):
    """Best-looking frame that has no caption on it, if possible."""
    from .render import Renderer
    from .timeline import Project
    r = Renderer(p, __import__("importlib").import_module(f"loom.scenes.{p.style}"),
                 scale=0.5, ss=1, verbose=False)
    best, best_score, best_t = None, -1, 0
    for i in range(samples):
        t = p.duration * (0.06 + 0.88 * i / max(1, samples - 1))
        _, shot = p.shot_at(t)
        if shot.meta.get("set") == "card":
            continue                     # a title card is not a thumbnail
        busy = bool(r.groups_at(t))
        im = r.still(t)
        s = _score(im) - (0.30 if busy else 0.0)
        if s > best_score:
            best, best_score, best_t = im, s, t
    if best is None:                     # all cards: fall back to the card frame
        best, best_t = r.still(p.duration * 0.5), p.duration * 0.5
    return best, best_t


def _hashtags(p):
    base = ["#fyp", "#storytime", "#horrorstory"] if p.style == "nightline" else \
           ["#fyp", "#learnontiktok", "#explained"]
    out, seen = [], set()
    for t in list(p.data.get("tags") or []) + base:
        t = str(t).strip()
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t if t.startswith("#") else "#" + t)
    return out[:PLATFORM_LIMITS.get(p.platform, {}).get("hashtags", 6)]


def _caption_text(p):
    title = p.data.get("title") or p.name.upper()
    hook = p.data.get("hook")
    if not hook and p.script:
        hook = p.script[0].get("text", "")
    body = (p.data.get("social") or {}).get("body")
    if not body:
        body = hook
    return f"{title}\n\n{body}\n\n" + " ".join(_hashtags(p))


def package(p, mod, master=None, quiet=False):
    master = master or p.p("renders", f"{p.name}.mp4")
    if not os.path.exists(master):
        master = p.p("renders", "master.mp4")
    if not os.path.exists(master):
        raise SystemExit(f"no master render found for {p.name} (run: loom render {p.dir})")
    out_dir = p.ensure("deliver")
    lim = PLATFORM_LIMITS.get(p.platform, PLATFORM_LIMITS["tiktok"])
    share = make_share(master, os.path.join(out_dir, "share.mp4"), target_mb=lim["mb"])

    cover_im, cover_t = pick_cover(p, master)
    # if the chosen frame has captions, take a clean frame 0.4 s earlier
    try:
        cr = __import__("importlib").import_module(f"loom.scenes.{p.style}")
        rr = __import__("loom.render", fromlist=["Renderer"]).Renderer(p, cr, scale=0.5, ss=1,
                                                                      verbose=False)
        for dt in (0.5, 1.0, 1.6):
            if cover_t - dt > 0 and not rr.groups_at(cover_t - dt):
                cover_im, cover_t = rr.still(cover_t - dt), cover_t - dt
                break
    except Exception:
        pass
    cover = os.path.join(out_dir, "cover.jpg")
    cover_im.save(cover, quality=94)

    cap = _caption_text(p)
    with open(os.path.join(out_dir, "caption.txt"), "w") as fh:
        fh.write(cap + "\n")

    info = dict(
        project=p.name, style=p.style, aspect=p.aspect, duration=round(p.duration, 2),
        fps=p.fps, master=os.path.relpath(master, p.dir), share=os.path.relpath(share, p.dir),
        master_mb=round(os.path.getsize(master) / 1e6, 1),
        share_mb=round(os.path.getsize(share) / 1e6, 1),
        cover=os.path.relpath(cover, p.dir), cover_time=round(cover_t, 2),
        caption=cap, hashtags=_hashtags(p),
        platform_limit=lim,
    )
    with open(os.path.join(out_dir, "package.json"), "w") as fh:
        json.dump(info, fh, indent=1)
    if not quiet:
        print(f"  master  {info['master']}  ({info['master_mb']} MB)")
        print(f"  share   {info['share']}  ({info['share_mb']} MB, limit {lim['mb']})")
        print(f"  cover   {info['cover']}  (t={info['cover_time']}s)")
        print(f"  caption {os.path.join('deliver', 'caption.txt')}")
        print("  " + "─" * 46)
        for line in cap.splitlines():
            print("  " + line)
    return info
