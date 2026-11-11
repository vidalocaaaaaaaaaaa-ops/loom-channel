#!/usr/bin/env python3
"""Build an upload manifest for a project that is already rendered.

The queue in `state.json` starts at Part 4, because Parts 1-3 were made before this
automation existed. If you still need to put those on YouTube, point this at the
finished project folder and it writes the same manifest `make_episode.py` would,
without re-rendering anything.

    python channel/manifest_for.py projects/room-402-part3
    python channel/manifest_for.py projects/room-402-part2 --series room402 --part 2
    python channel/manifest_for.py projects/room-402 --privacy unlisted

Then:
    python channel/upload_youtube.py --manifest channel/pending/<slug>.json --dry-run
    python channel/upload_youtube.py --manifest channel/pending/<slug>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CH = os.path.join(ROOT, "channel")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="project folder, e.g. projects/room-402-part3")
    ap.add_argument("--series", help="series slug used in state.json (guessed from project.json)")
    ap.add_argument("--part", type=int, help="part number (defaults to series.part in project.json)")
    ap.add_argument("--privacy", default=None, choices=["public", "unlisted", "private"])
    ap.add_argument("--dry-run", action="store_true", help="print the manifest, do not write it")
    args = ap.parse_args(argv)

    pdir = args.project
    if not os.path.isabs(pdir):
        pdir = os.path.join(ROOT, pdir)
    pjson = os.path.join(pdir, "project.json")
    if not os.path.exists(pjson):
        raise SystemExit(f"no project.json in {pdir}")
    data = load(pjson)
    master = os.path.join(pdir, "renders", "master.mp4")
    if not os.path.exists(master):
        raise SystemExit(f"no master render at {master} (run: loom render {os.path.relpath(pdir, ROOT)})")

    plan = load(os.path.join(CH, "plan.json"), {}) or {}
    defaults = plan.get("defaults", {})
    series_slug = args.series
    episodes = {}
    for slug in plan.get("rotation", []):
        s = load(os.path.join(CH, "series", slug + ".json"), {}) or {}
        if not series_slug and s.get("title", "").lower() == str(data.get("series", {}).get("of", "")).lower():
            series_slug = slug
        episodes[slug] = s
    series_slug = series_slug or "room402"
    series = episodes.get(series_slug, {})

    part = args.part or int((data.get("series") or {}).get("part") or 1)
    ep = next((e for e in series.get("episodes", []) if e.get("part") == part), None)
    ep_title = (ep or {}).get("title") or data.get("title", "EPISODE")
    hook = data.get("hook") or (ep or {}).get("hook", "")
    body = ((data.get("social") or {}).get("body")) or hook
    tags = [t for t in (data.get("tags") or series.get("tags") or [])]
    title = f"{data.get('series', {}).get('of', 'ROOM 402')} — Part {part}: " \
            f"{ep_title.title()} #shorts"

    qc_file = os.path.join(pdir, "data", "qc.json")
    qc = "unknown"
    rep = load(qc_file, {}) or {}
    items = rep.get("items", [])
    if items:
        c = {k: sum(1 for i in items if i.get("status") == k) for k in ("pass", "warn", "fail")}
        dur = next((i.get("detail", "") for i in items if i.get("gate") == "duration"), "")
        qc = f"{c['pass']} pass / {c['warn']} warn / {c['fail']} fail" + (
            f" · {dur.split(',')[0]}" if dur else "")

    desc = [body, ""]
    if hook:
        desc += [hook, ""]
    if data.get("fiction") or series.get("fiction"):
        desc += [("Fiction. Every number in it is invented for the story."
                  if series.get("style") == "blueprint"
                  else "Fiction. Original story, written for this channel."), ""]
    desc += [f"Series: {data.get('series', {}).get('of', 'ROOM 402')}", "", " ".join(tags)]

    manifest = {
        "slug": data.get("name", os.path.basename(pdir)),
        "series": series_slug,
        "series_title": data.get("series", {}).get("of", "ROOM 402"),
        "part": part,
        "episode_title": ep_title,
        "video": os.path.relpath(master, ROOT),
        "video_bytes": os.path.getsize(master),
        "cover": os.path.relpath(os.path.join(pdir, "deliver", "cover.jpg"), ROOT)
        if os.path.exists(os.path.join(pdir, "deliver", "cover.jpg")) else None,
        "caption": os.path.relpath(os.path.join(pdir, "deliver", "caption.txt"), ROOT)
        if os.path.exists(os.path.join(pdir, "deliver", "caption.txt")) else None,
        "youtube": {
            "title": title[:100],
            "description": "\n".join(desc).strip()[:4900],
            "tags": [t.lstrip("#") for t in tags],
            "privacy": args.privacy or defaults.get("privacy", "public"),
            "made_for_kids": bool(defaults.get("made_for_kids", False)),
            "category_id": str(defaults.get("category_id", "24")),
            "playlist_name": series.get("playlist_name", data.get("series", {}).get("of", "ROOM 402")),
        },
        "qc": qc,
        "fiction": bool(data.get("fiction") or series.get("fiction")),
        "rendered_at": None,
        "backfilled": True,
    }

    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0

    out_dir = os.path.join(CH, "pending")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, manifest["slug"] + ".json")
    with open(out, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    state_path = os.path.join(CH, "state.json")
    state = load(state_path, {}) or {}
    state.setdefault("pending", [])
    if manifest["slug"] not in state["pending"]:
        state["pending"].append(manifest["slug"])
    with open(state_path, "w") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")

    print(f"wrote {os.path.relpath(out, ROOT)}")
    print(f"video   {manifest['video']}  ({manifest['video_bytes']/1e6:.1f} MB)")
    print(f"title   {manifest['youtube']['title']}")
    print(f"privacy {manifest['youtube']['privacy']}")
    print(f"qc      {qc}")
    print(f"\nnext: python channel/upload_youtube.py --manifest {os.path.relpath(out, ROOT)} --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
