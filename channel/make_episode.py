#!/usr/bin/env python3
"""Turn the next planned episode into a rendered, QC-gated video.

This is the only script the scheduled job needs. It reads the channel plan,
picks the next episode, writes `projects/<slug>/project.json`, runs the whole
loom pipeline (voice -> build -> qc -> render -> package), and leaves a
manifest in `channel/pending/` describing what should be uploaded.

Nothing here talks to YouTube. Publishing is a separate script so that a human
can look at the result first.

    python channel/make_episode.py --next                 # render the next one
    python channel/make_episode.py --series site9 --part 2
    python channel/make_episode.py --next --plan-only     # write project.json, stop
    python channel/make_episode.py --next --draft         # half-scale smoke test
    python channel/make_episode.py --list                 # what is queued

Exit codes: 0 ok, 2 bad input, 3 QC failed, 4 render failed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNEL = os.path.join(ROOT, "channel")
STATE = os.path.join(CHANNEL, "state.json")
PLAN = os.path.join(CHANNEL, "plan.json")
SERIES_DIR = os.path.join(CHANNEL, "series")
PENDING = os.path.join(CHANNEL, "pending")


# --------------------------------------------------------------------- io
def load_json(path, default=None):
    if not os.path.exists(path):
        if default is None:
            raise SystemExit(f"missing file: {path}")
        return default
    with open(path) as fh:
        return json.load(fh)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------- plan
def load_plan():
    plan = load_json(PLAN)
    series = {}
    for slug in plan["rotation"]:
        path = os.path.join(SERIES_DIR, slug + ".json")
        if not os.path.exists(path):
            raise SystemExit(f"plan lists series '{slug}' but {path} does not exist")
        series[slug] = load_json(path)
    return plan, series


def load_state():
    return load_json(STATE, {"released": {}, "pending": [], "history": [], "cursor": 0})


def available_episodes(series, state):
    """Episodes not released and not already rendered-or-waiting."""
    out = []
    done = set(state.get("released", {}).get(series["slug"], []))
    waiting = set(state.get("pending", []))
    for ep in series["episodes"]:
        if ep["part"] in done or ep["slug"] in waiting:
            continue
        out.append(ep)
    return sorted(out, key=lambda e: e["part"])


def pick_next(plan, series, state):
    """Round-robin across the rotation, starting after the last series used."""
    order = plan["rotation"]
    start = int(state.get("cursor", 0)) % max(1, len(order))
    tried = []
    for i in range(len(order)):
        slug = order[(start + i) % len(order)]
        eps = available_episodes(series[slug], state)
        tried.append(f"{slug}: {len(eps)} ready")
        if eps:
            return slug, eps[0], (start + i) % len(order)
    raise SystemExit("nothing left in the queue — add episodes to channel/series/*.json\n  "
                     + "\n  ".join(tried))


# ---------------------------------------------------------------- project
def assemble(series, ep):
    """Series-level look + episode-level content -> a normal loom project.json."""
    proj = {
        "name": ep["slug"],
        "title": ep["title"],
        "style": series["style"],
        "aspect": series.get("aspect", "9:16"),
        "fps": series.get("fps", 30),
        "seed": int(series.get("seed_base", 7)) + int(ep["part"]),
        "platform": series.get("platform", "youtube"),
        "series": {"part": ep["part"], "of": series["title"]},
        "voice": series["voice"],
        "transition": series.get("transition", "dissolve"),
        "grade": series.get("grade"),
        "captions": series.get("captions"),
        "script": ep["script"],
        "hook": ep.get("hook", ""),
        "social": ep.get("social", {}),
        "tags": series.get("tags", []),
    }
    for k in ("open_card", "end_card"):
        if ep.get(k):
            proj[k] = ep[k]
    if series.get("fiction"):
        proj["fiction"] = True
    if series.get("scripts_note"):
        proj["note"] = series["scripts_note"]
    return {k: v for k, v in proj.items() if v is not None}


def validate(series, ep, strict=False):
    problems = []
    for i, line in enumerate(ep["script"], 1):
        if not line.get("id"):
            problems.append(f"line {i}: missing id")
        if not line.get("text"):
            problems.append(f"line {i}: missing text")
        if series["style"] == "nightline" and not line.get("set"):
            problems.append(f"line {i}: nightline lines need a set")
        if series["style"] == "blueprint":
            viz = line.get("viz", "statement")
            if viz in ("stat", "bars", "line") and not line.get("source"):
                msg = f"line {i}: {viz} has no source line"
                (problems if strict and not series.get("fiction") else []).append(msg)
                if not (strict and not series.get("fiction")):
                    print(f"    note: {msg}")
    if len(ep["script"]) < 4:
        problems.append("an episode needs at least 4 lines")
    if problems:
        raise SystemExit("script problems:\n  " + "\n  ".join(problems))


# ---------------------------------------------------------------- pipeline
def run(cmd, label):
    print(f"\n$ {' '.join(cmd)}", flush=True)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT)
    print(f"  {label}: {time.time() - t0:.0f}s  (exit {p.returncode})", flush=True)
    return p.returncode


def loom(*args):
    return [sys.executable, "-m", "loom.cli", *args]


def describe_shot_table(project_dir, style):
    """A readable shot table for script.md, derived from the built timeline."""
    sys.path.insert(0, ROOT)
    try:
        import importlib
        from loom.timeline import Project
        p = Project(os.path.join(project_dir, "project.json")).load_words()
        p.build(importlib.import_module(f"loom.scenes.{style}"))
        rows = ["| shot | start | end | length |", "|---|---|---|---|"]
        for s in p.shots:
            rows.append(f"| {s.name} | {s.start:.2f} | {s.end:.2f} | {s.dur:.2f} |")
        rows.append("")
        rows.append(f"total {p.duration:.2f} s, {len(p.shots)} shots")
        return "\n".join(rows)
    except Exception as exc:            # never let documentation kill a render
        return f"(shot table unavailable: {exc})"


def write_script_md(project_dir, series, ep, qc_summary):
    table = describe_shot_table(project_dir, series["style"])
    lines = [f"# {series['title']} — Part {ep['part']}: {ep['title']}", ""]
    lines.append(ep.get("hook", ""))
    lines.append("")
    lines.append("## Lines")
    lines.append("")
    for line in ep["script"]:
        extra = line.get("set") or line.get("viz", "statement")
        lines.append(f"{line['id']}  [{extra}]  {line['text']}")
    lines += ["", "## Shot table", "", table, "", "## QC", "", qc_summary, ""]
    if series.get("fiction"):
        lines += ["## Note", "", "This is fiction. Every number in it is invented for the story.", ""]
    with open(os.path.join(project_dir, "script.md"), "w") as fh:
        fh.write("\n".join(lines))


def qc_summary(project_dir):
    rep = load_json(os.path.join(project_dir, "data", "qc.json"), {})
    items = rep.get("items", []) if rep else []
    if not items:
        return "qc.json not found"
    count = {k: sum(1 for c in items if c.get("status") == k) for k in ("pass", "warn", "fail")}
    dur = next((c.get("detail", "") for c in items if c.get("gate") == "duration"), "")
    loud = next((c.get("detail", "") for c in items if c.get("gate") == "loudness"), "")
    bits = [f"{count['pass']} pass / {count['warn']} warn / {count['fail']} fail"]
    if dur:
        bits.append(dur.split(",")[0])
    if loud:
        bits.append(loud.split("(")[0].strip())
    return " · ".join(bits)


def youtube_meta(series, ep, plan):
    d = plan.get("defaults", {})
    body = (ep.get("social", {}) or {}).get("body") or ep.get("hook", "")
    tags = [t.lstrip("#") for t in (ep.get("tags") or series.get("tags", []))]
    title = f"{series['title']} — Part {ep['part']}: {ep['title'].title()} #shorts"
    desc = [body, ""]
    if ep.get("hook"):
        desc += [ep["hook"], ""]
    if series.get("fiction"):
        desc += [("Fiction. Every number in it is invented for the story." if series["style"] == "blueprint"
                  else "Fiction. Original story, written for this channel."), ""]
    desc += ["Series: " + series["title"], ""]
    desc += [" ".join(ep.get("tags") or series.get("tags", []))]
    return {
        "title": title[:100],
        "description": "\n".join(desc).strip()[:4900],
        "tags": tags,
        "privacy": d.get("privacy", "public"),
        "made_for_kids": bool(d.get("made_for_kids", False)),
        "category_id": str(d.get("category_id", "24")),
        "playlist_name": series.get("playlist_name", series["title"]),
    }


# -------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--next", action="store_true", help="take the next episode from the rotation")
    ap.add_argument("--series", help="series slug, e.g. room402")
    ap.add_argument("--part", type=int, help="episode part number")
    ap.add_argument("--list", action="store_true", help="print the queue and exit")
    ap.add_argument("--plan-only", action="store_true", help="write project.json, do not render")
    ap.add_argument("--draft", action="store_true", help="half scale, fast")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--ss", type=int, default=2)
    ap.add_argument("--crf", type=int, default=22)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--strict", action="store_true", help="fail if a chart line lacks a source")
    ap.add_argument("--skip-qc", action="store_true", help=argparse.SUPPRESS)  # deprecated: a fail always blocks
    ap.add_argument("--gh-output", action="store_true", help="write outputs for GitHub Actions")
    args = ap.parse_args(argv)

    plan, series = load_plan()
    state = load_state()
    os.makedirs(PENDING, exist_ok=True)

    if args.list:
        for slug in plan["rotation"]:
            s = series[slug]
            ready = available_episodes(s, state)
            rel = state.get("released", {}).get(slug, [])
            released = ", ".join(f"p{n}" for n in rel) if rel else "—"
            print(f"{s['title']:<14} released {released:<12} queued "
                  + (", ".join(f"p{e['part']} {e['title']}" for e in ready) or "—"))
        print(f"\npending approval: {state.get('pending') or '—'}")
        return 0

    if args.series and args.part:
        s = series.get(args.series)
        if not s:
            raise SystemExit(f"unknown series '{args.series}' (have: {', '.join(series)})")
        ep = next((e for e in s["episodes"] if e["part"] == args.part), None)
        if not ep:
            raise SystemExit(f"{args.series} has no part {args.part}")
        slug, cursor = args.series, state.get("cursor", 0)
    elif args.next:
        slug, ep, cursor = pick_next(plan, series, state)
    else:
        ap.error("pass --next, or --series X --part N, or --list")

    s = series[slug]
    print(f"episode: {s['title']} · part {ep['part']} · {ep['title']}")
    validate(s, ep, strict=args.strict)

    proj = assemble(s, ep)
    project_dir = os.path.join(ROOT, "projects", proj["name"])
    os.makedirs(project_dir, exist_ok=True)
    save_json(os.path.join(project_dir, "project.json"), proj)
    print(f"wrote {os.path.relpath(os.path.join(project_dir, 'project.json'), ROOT)}")

    if args.plan_only:
        print("plan-only: stopping before voice")
        return 0

    # 1. voice + mix
    for stage in ("voice", "build"):
        rc = run(loom(stage, os.path.relpath(project_dir, ROOT)), stage)
        if rc != 0:
            return 3

    # 2. QC — a fail stops the pipeline here, before any render time is spent
    rc = run(loom("qc", os.path.relpath(project_dir, ROOT)), "qc")
    summary = qc_summary(project_dir)
    print(f"  qc: {summary}")
    if rc != 0:                   # loom exits 1 when any gate fails
        print("  QC FAILED — not rendering. Fix the script and re-run.")
        print("  details: " + os.path.join(os.path.relpath(project_dir, ROOT), "data", "qc.json"))
        return 3

    # 3. render
    os.makedirs(os.path.join(project_dir, "renders"), exist_ok=True)
    cmd = loom("render", os.path.relpath(project_dir, ROOT), "--out", "master",
               "--crf", str(args.crf), "--preset", args.preset)
    if args.draft:
        cmd.append("--draft")
    else:
        cmd += ["--scale", str(args.scale), "--ss", str(args.ss)]
    rc = run(cmd, "render")
    if rc != 0:
        return 4

    # 4. package (deliver/ must exist first — the packager does not create it
    #    before it starts writing, which is a foot-gun we hit the hard way)
    os.makedirs(os.path.join(project_dir, "deliver"), exist_ok=True)
    rc = run(loom("package", os.path.relpath(project_dir, ROOT)), "package")
    if rc != 0:
        print("  package failed — the master exists, you can package it later")
        return 4

    master = os.path.join(project_dir, "renders", "master.mp4")
    if not os.path.exists(master):
        print("  no master.mp4 — render claimed success but wrote nothing")
        return 4

    write_script_md(project_dir, s, ep, summary)

    # 5. manifest for the uploader
    meta = youtube_meta(s, ep, plan)
    manifest = {
        "slug": proj["name"],
        "series": slug,
        "series_title": s["title"],
        "part": ep["part"],
        "episode_title": ep["title"],
        "video": os.path.relpath(master, ROOT),
        "video_bytes": os.path.getsize(master),
        "cover": os.path.relpath(os.path.join(project_dir, "deliver", "cover.jpg"), ROOT)
        if os.path.exists(os.path.join(project_dir, "deliver", "cover.jpg")) else None,
        "caption": os.path.relpath(os.path.join(project_dir, "deliver", "caption.txt"), ROOT)
        if os.path.exists(os.path.join(project_dir, "deliver", "caption.txt")) else None,
        "youtube": meta,
        "qc": summary,
        "fiction": bool(s.get("fiction")),
        "rendered_at": now(),
        "draft": bool(args.draft),
    }
    # a draft is a smoke test, not a release: it must not touch the ledger, or
    # the next real run would skip this episode and move on to the following one
    name = ("draft-" + proj["name"]) if args.draft else proj["name"]
    manifest_path = os.path.join(PENDING, f"{name}.json")
    save_json(manifest_path, manifest)

    if args.draft:
        print("\ndraft: manifest written, state.json untouched, publish job will skip this run")
    else:
        state.setdefault("pending", [])
        if proj["name"] not in state["pending"]:
            state["pending"].append(proj["name"])
        state["cursor"] = cursor
        state.setdefault("history", []).append(
            {"slug": proj["name"], "series": slug, "part": ep["part"],
             "rendered_at": manifest["rendered_at"], "status": "awaiting-approval"})
        save_json(STATE, state)

    rel_manifest = os.path.relpath(manifest_path, ROOT)
    print(f"\nMANIFEST {rel_manifest}")
    print(f"video    {manifest['video']}  ({manifest['video_bytes'] / 1e6:.1f} MB)")
    print(f"title    {meta['title']}")
    print(f"privacy  {meta['privacy']}  (not published yet — needs approval)")
    print(f"qc       {summary}")
    if args.gh_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"manifest={rel_manifest}\n")
            fh.write(f"slug={proj['name']}\n")
            fh.write(f"title={meta['title']}\n")
            fh.write(f"draft={'true' if args.draft else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
