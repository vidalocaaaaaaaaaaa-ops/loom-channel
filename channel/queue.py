#!/usr/bin/env python3
"""Look at and edit the channel queue.

    python channel/queue.py status
    python channel/queue.py list
    python channel/queue.py approve room-402-part4     # print the publish command
    python channel/queue.py skip room-402-part4        # drop it from pending
    python channel/queue.py reset --series room402     # put episodes back in the queue

Approving does not upload anything by itself — it prints the exact command, so
a typo cannot publish to your channel. In GitHub Actions, approval is the
'youtube-approval' environment gate instead (see channel/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CH = os.path.join(ROOT, "channel")


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def save(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("list")
    a = sub.add_parser("approve")
    a.add_argument("slug")
    a.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    s = sub.add_parser("skip")
    s.add_argument("slug")
    r = sub.add_parser("reset")
    r.add_argument("--series", required=True)
    args = ap.parse_args(argv)

    state_path = os.path.join(CH, "state.json")
    state = load(state_path, {"released": {}, "pending": [], "history": [], "cursor": 0})
    plan = load(os.path.join(CH, "plan.json"), {"rotation": []})
    pending_dir = os.path.join(CH, "pending")

    if args.cmd in ("status", "list"):
        print("series          released            waiting for approval")
        for slug in plan.get("rotation", []):
            path = os.path.join(CH, "series", slug + ".json")
            series = load(path, {"title": slug, "episodes": []})
            rel = state.get("released", {}).get(slug, [])
            rel_txt = ", ".join(f"p{n}" for n in rel) or "—"
            ready = [e for e in series["episodes"]
                     if e["part"] not in rel and e["slug"] not in state.get("pending", [])]
            print(f"{series['title']:<15} {rel_txt:<19} "
                  + (", ".join(f"p{e['part']}" for e in ready) if ready else "—"))
        print("\npending:")
        if not state.get("pending"):
            print("  (nothing)")
        for slug in state.get("pending", []):
            mpath = os.path.join(pending_dir, slug + ".json")
            m = load(mpath, {})
            size = ""
            v = m.get("video")
            if v and os.path.exists(os.path.join(ROOT, v)):
                size = f"{os.path.getsize(os.path.join(ROOT, v)) / 1e6:.1f} MB"
            print(f"  {slug:<22} {m.get('episode_title', ''):<22} {size:<10} "
                  f"qc {m.get('qc', '?')}")
            if m.get("youtube"):
                print(f"    title: {m['youtube']['title']}")
        print("\nhistory:")
        for row in state.get("history", [])[-6:]:
            when = row.get("published_at") or row.get("rendered_at", "")
            print(f"  {when}  {row.get('slug', ''):<22} {row.get('status', ''):<18}"
                  + (f" https://youtu.be/{row['video_id']}" if row.get("video_id") else ""))
        return 0

    if args.cmd == "approve":
        if args.slug not in state.get("pending", []):
            print(f"error: '{args.slug}' is not pending (run: queue.py status)", file=sys.stderr)
            return 2
        print("approved. publish with:\n")
        print(f"  python channel/upload_youtube.py --manifest channel/pending/{args.slug}.json "
              f"--privacy {args.privacy}\n")
        print("or, from GitHub Actions, run the 'short' workflow with publish=true and")
        print("approve the 'youtube-approval' environment when it asks.")
        return 0

    if args.cmd == "skip":
        if args.slug in state.get("pending", []):
            state["pending"].remove(args.slug)
            save(state_path, state)
        mpath = os.path.join(pending_dir, args.slug + ".json")
        if os.path.exists(mpath):
            os.rename(mpath, mpath.replace(".json", ".skipped.json"))
        print(f"skipped {args.slug} (the project folder is untouched)")
        return 0

    if args.cmd == "reset":
        if args.series in state.get("released", {}):
            state["released"][args.series] = []
        save(state_path, state)
        print(f"reset released list for {args.series} — it will be rendered again")
        return 0


if __name__ == "__main__":
    sys.exit(main())
