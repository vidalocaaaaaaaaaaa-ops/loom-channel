#!/usr/bin/env python3
"""loom — one command-line entry point for the whole pipeline.

  python -m loom.cli <command> ...

  doctor                      check the machine
  voices | styles             lists
  new <style> <name>          copy the style's example project
  voice <project>             narration + word timings
  build <project>             timeline + music + sfx + mix -> data/mix.wav
  still <project> --t 3.5     one PNG frame (for looking at)
  render <project> [--draft]  the MP4
  qc <project>                objective quality gates (+ contact sheet)
  package <project>           share copy, cover frame, title/caption/hashtags
  all <project>               voice -> build -> qc -> render -> package
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from loom import render as R  # noqa: E402
from loom.timeline import Line, Project  # noqa: E402


def style_module(name):
    return importlib.import_module(f"loom.scenes.{name}")


def open_project(path):
    if not path.endswith(".json"):
        path = os.path.join(path, "project.json")
    p = Project(path)
    return p


def defaults_of(mod):
    return getattr(mod, "DEFAULTS", {})


# ------------------------------------------------------------------ commands
def cmd_doctor(args):
    import shutil
    from loom.audio import tts
    ok = True
    print("loom doctor")
    print(f"  python        {sys.version.split()[0]}")
    try:
        import numpy, PIL
        print(f"  numpy         {numpy.__version__}")
        print(f"  pillow        {PIL.__version__}")
    except Exception as e:
        ok = False
        print(f"  numpy/pillow  MISSING ({e})")
    try:
        exe = R.ffmpeg_exe()
        print(f"  ffmpeg        {exe}")
    except Exception:
        ok = False
        print("  ffmpeg        MISSING — pip install imageio-ffmpeg")
    onnx, voices = tts.model_paths()
    if os.path.exists(onnx) and os.path.exists(voices):
        print(f"  kokoro        {onnx} ({os.path.getsize(onnx)//1_000_000} MB)")
    else:
        ok = False
        print("  kokoro        MISSING — bash scripts/setup.sh --voice")
    try:
        import scipy  # noqa
        print(f"  scipy         {scipy.__version__} (fast filters)")
    except Exception:
        print("  scipy         absent (numpy fallback filters)")
    print(f"  fonts         {len(os.listdir(os.path.join(HERE, 'fonts')))} bundled")
    print("  status        " + ("READY" if ok else "NOT READY"))
    return 0 if ok else 1


def cmd_styles(args):
    print("styles:")
    for name in sorted(os.listdir(os.path.join(HERE, "scenes"))):
        if name.endswith(".py") and not name.startswith("_"):
            mod = style_module(name[:-3])
            d = defaults_of(mod)
            print(f"  {name[:-3]:<12} voice={d.get('voice','-'):<10} gap={d.get('gap','-'):<5} "
                  f"music={d.get('music','-')}")
    return 0


def cmd_voices(args):
    from loom.audio import tts
    for line in tts.list_voices():
        print("  " + line)
    return 0


def cmd_new(args):
    from loom.audio import tts
    src = os.path.join(HERE, "..", "projects", args.example or "_template")
    dst = os.path.abspath(args.name)
    import json, shutil
    os.makedirs(dst, exist_ok=True)
    mod = style_module(args.style)
    tpl = dict(name=os.path.basename(dst), style=args.style, aspect="9:16", fps=30,
               seed=7, platform="tiktok", title="UNTITLED",
               voice=dict(name=defaults_of(mod).get("voice", "am_michael"),
                          speed=defaults_of(mod).get("speed", 1.0)),
               captions=getattr(mod, "CAPTIONS", {}), grade=getattr(mod, "GRADE", {}),
               script=[dict(id="l1", text="Write your first line here.", set="corridor")])
    with open(os.path.join(dst, "project.json"), "w") as fh:
        json.dump(tpl, fh, indent=2)
    print(f"created {dst}/project.json — edit the script, then: loom all {dst}")
    return 0


def cmd_voice(args):
    p = open_project(args.project)
    mod = style_module(p.style)
    from loom.voice import build_narration
    build_narration(p, defaults_of(mod), force=args.force)
    return 0


def cmd_build(args):
    p = open_project(args.project)
    mod = style_module(p.style)
    p.load_words()
    if not p.words:
        print("no words.json — run: loom voice <project>")
        return 2
    p.build(mod)
    from loom.audio.build import build_mix
    build_mix(p, mod, quiet=args.quiet)
    print(f"  timeline: {p.duration:.1f}s, {len(p.shots)} shots")
    return 0


def cmd_still(args):
    p = open_project(args.project)
    mod = style_module(p.style)
    p.load_words().build(mod)
    r = R.Renderer(p, mod, scale=args.scale, ss=args.ss, verbose=False)
    os.makedirs(p.p("review"), exist_ok=True)
    times = [float(x) for x in args.t.split(",")]
    for t in times:
        im = r.still(t)
        out = p.p("review", f"still_{t:05.2f}.png".replace(".", "_", 1))
        out = p.p("review", f"still_{str(t).replace('.', 'p')}.png")
        im.save(out)
        print("  wrote", out)
    return 0


def cmd_render(args):
    p = open_project(args.project)
    mod = style_module(p.style)
    p.load_words().build(mod)
    scale = 0.5 if args.draft else args.scale
    ss = 1 if args.draft else args.ss
    r = R.Renderer(p, mod, scale=scale, ss=ss)
    os.makedirs(p.p("renders"), exist_ok=True)
    name = args.out or ("draft" if args.draft else f"{p.name}")
    out = p.p("renders", name + (".mp4" if not name.endswith(".mp4") else ""))
    mix = p.p("data", "mix.wav")
    audio = mix if os.path.exists(mix) else None
    if audio is None:
        print("  (no data/mix.wav — rendering silent)")
    print(f"  rendering {p.duration:.1f}s at {scale:.2f}x to {out}")
    r.encode(out, audio=audio, crf=args.crf, preset=args.preset)
    print(f"  done: {out}  ({os.path.getsize(out)//1024//1024} MB)")
    return 0


def cmd_qc(args):
    p = open_project(args.project)
    mod = style_module(p.style)
    p.load_words().build(mod)
    from loom import qc
    rep = qc.run(p, mod, scale=args.scale, ss=args.ss, contact=not args.no_sheet)
    return 0 if rep["pass_"] else 1


def cmd_package(args):
    p = open_project(args.project)
    mod = style_module(p.style)
    p.load_words().build(mod)
    from loom import package as pk
    pk.package(p, mod)
    return 0


def cmd_all(args):
    for step in (cmd_voice, cmd_build, cmd_qc, cmd_render, cmd_package):
        print(f"\n== {step.__name__.replace('cmd_', '')} ==")
        rc = step(args)
        if rc:
            print(f"  stopped at {step.__name__}")
            return rc
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="loom", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("styles").set_defaults(fn=cmd_styles)
    sub.add_parser("voices").set_defaults(fn=cmd_voices)

    n = sub.add_parser("new")
    n.add_argument("style")
    n.add_argument("name")
    n.add_argument("--example", default=None)
    n.set_defaults(fn=cmd_new)

    v = sub.add_parser("voice")
    v.add_argument("project")
    v.add_argument("--force", action="store_true")
    v.set_defaults(fn=cmd_voice)

    b = sub.add_parser("build")
    b.add_argument("project")
    b.add_argument("--quiet", action="store_true")
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("still")
    s.add_argument("project")
    s.add_argument("--t", default="1.0")
    s.add_argument("--scale", type=float, default=1.0)
    s.add_argument("--ss", type=int, default=2)
    s.set_defaults(fn=cmd_still)

    r = sub.add_parser("render")
    r.add_argument("project")
    r.add_argument("--draft", action="store_true")
    r.add_argument("--scale", type=float, default=1.0)
    r.add_argument("--ss", type=int, default=2)
    r.add_argument("--crf", type=int, default=18)
    r.add_argument("--preset", default="medium")
    r.add_argument("--out", default=None)
    r.set_defaults(fn=cmd_render)

    q = sub.add_parser("qc")
    q.add_argument("project")
    q.add_argument("--scale", type=float, default=0.5)
    q.add_argument("--ss", type=int, default=1)
    q.add_argument("--no-sheet", action="store_true")
    q.set_defaults(fn=cmd_qc)

    pk = sub.add_parser("package")
    pk.add_argument("project")
    pk.set_defaults(fn=cmd_package)

    a = sub.add_parser("all")
    a.add_argument("project")
    a.add_argument("--draft", action="store_true")
    a.add_argument("--scale", type=float, default=1.0)
    a.add_argument("--ss", type=int, default=2)
    a.add_argument("--crf", type=int, default=18)
    a.add_argument("--preset", default="medium")
    a.add_argument("--out", default=None)
    a.add_argument("--no-sheet", action="store_true")
    a.set_defaults(fn=cmd_all)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
