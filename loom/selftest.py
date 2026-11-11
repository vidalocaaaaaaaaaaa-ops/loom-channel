"""selftest — prove the whole pipeline works on this machine, in about two minutes.

Builds one tiny video per style (real TTS, real mix, real frames, real QC) and
fails loudly if any stage or gate breaks.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from loom import qc, render  # noqa: E402
from loom.audio.build import build_mix  # noqa: E402
from loom.timeline import Project  # noqa: E402
from loom.voice import build_narration  # noqa: E402

CASES = {
    "nightline": dict(
        aspect="9:16", seed=3,
        script=[
            dict(id="l1", text="The corridor was empty. The light was not.",
                 set="corridor", set_params={"lights": [2.6, 6.4],
                                             "figure": {"x": 0.0, "z": 6.0}}),
            dict(id="l2", text="Room four oh two was warm.", set="door"),
        ]),
    "blueprint": dict(
        aspect="16:9", seed=4,
        script=[
            dict(id="l1", text="Nine out of ten of these never ship.", viz="statement",
                 kicker="SELFTEST"),
            dict(id="l2", text="The tenth one does.", viz="stat", value=10, unit="%",
                 label="of projects that get finished", kicker="THE ODD ONE"),
        ]),
}


def run(style, spec, tmp):
    import importlib
    mod = importlib.import_module(f"loom.scenes.{style}")
    d = os.path.join(tmp, style)
    os.makedirs(d, exist_ok=True)
    data = dict(name=style, style=style, fps=24, platform="generic", **spec)
    with open(os.path.join(d, "project.json"), "w") as fh:
        json.dump(data, fh, indent=1)
    p = Project(os.path.join(d, "project.json"))
    t0 = time.time()
    build_narration(p, getattr(mod, "DEFAULTS", {}), force=True, quiet=True)
    p.load_words().build(mod)
    build_mix(p, mod, quiet=True)
    t_audio = time.time() - t0

    t1 = time.time()
    rep = qc.run(p, mod, scale=0.5, ss=1, contact=True, verbose=False)
    t_qc = time.time() - t1

    t2 = time.time()
    r = render.Renderer(p, mod, scale=0.5, ss=1, verbose=False)
    out = os.path.join(d, "renders", "selftest.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r.encode(out, audio=p.p("data", "mix.wav"), crf=26, preset="veryfast", fps=24)
    t_render = time.time() - t2

    n_fail = sum(1 for i in rep["items"] if i["status"] == "fail")
    n_warn = sum(1 for i in rep["items"] if i["status"] == "warn")
    mb = os.path.getsize(out) / 1e6
    print(f"  {style:<11} {p.duration:5.1f}s  {len(p.shots)} shots  "
          f"audio {t_audio:4.1f}s  qc {t_qc:4.1f}s  render {t_render:5.1f}s  "
          f"{mb:4.1f} MB   qc: {'PASS' if rep['pass_'] else 'FAIL'} "
          f"({n_warn} warn, {n_fail} fail)")
    for it in rep["items"]:
        if it["status"] == "fail":
            print(f"      ✗ {it['gate']}: {it['detail']}")
    return rep["pass_"], out, p.p("review", "contact_sheet.jpg")


def main():
    tmp = tempfile.mkdtemp(prefix="loom-selftest-")
    print(f"loom selftest — scratch dir {tmp}")
    ok = True
    for style, spec in CASES.items():
        try:
            passed, mp4, sheet = run(style, spec, tmp)
            ok = ok and passed
            print(f"      clip   {mp4}")
            print(f"      sheet  {sheet}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  {style:<11} FAILED: {e}")
            ok = False
    if ok:
        print("\n  SELFTEST PASSED — open the clips and the contact sheets above, look at them.")
        print("  If they look right, the machine is ready.\n")
        return 0
    print("\n  SELFTEST FAILED — see the errors above.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
