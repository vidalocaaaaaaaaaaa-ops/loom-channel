#!/usr/bin/env python3
"""Optional Supabase mirror for the queue. Off unless credentials are set.

    export SUPABASE_URL=https://xxxx.supabase.co
    export SUPABASE_SERVICE_KEY=service_role_key
    python channel/store.py sync
    python channel/store.py show

state.json in the repo stays the source of truth — this only mirrors it so a
dashboard can read the queue without cloning the repo.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CH = os.path.join(ROOT, "channel")
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")


def call(path, method="GET", body=None, prefer=None):
    if not URL or not KEY:
        raise SystemExit("set SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_KEY)")
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        print(f"  {method} {path} -> {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        raise


def sync():
    state_path = os.path.join(CH, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    call("/rest/v1/channel_state", "POST",
         {"id": "current", "data": state, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                     time.gmtime())},
         prefer="resolution=merge-duplicates")
    rows = []
    pending_dir = os.path.join(CH, "pending")
    for name in sorted(os.listdir(pending_dir)) if os.path.isdir(pending_dir) else []:
        if not name.endswith(".json"):
            continue
        m = json.load(open(os.path.join(pending_dir, name)))
        rows.append({
            "slug": m["slug"], "series": m["series"], "series_title": m.get("series_title"),
            "part": m["part"], "title": m.get("episode_title"), "status": "rendered",
            "video_path": m.get("video"), "cover_path": m.get("cover"), "qc": m.get("qc"),
            "youtube": m.get("youtube"), "rendered_at": m.get("rendered_at"),
        })
    for row in state.get("history", []):
        if row.get("status") == "published" and row.get("slug") not in {r["slug"] for r in rows}:
            rows.append({"slug": row["slug"], "series": row["series"], "part": row["part"],
                         "status": "published", "video_id": row.get("video_id"),
                         "video_url": f"https://youtu.be/{row['video_id']}"
                         if row.get("video_id") else None,
                         "published_at": row.get("published_at")})
    if rows:
        call("/rest/v1/episodes", "POST", rows, prefer="resolution=merge-duplicates")
    print(f"synced: state + {len(rows)} episode rows")


def show():
    rows = call("/rest/v1/episodes?select=series,part,title,status,video_url&order=series,part")
    for r in rows or []:
        print(f"{r['series']:<10} p{r['part']:<3} {str(r.get('title'))[:24]:<26} "
              f"{r['status']:<10} {r.get('video_url') or ''}")
    print(len(rows or []), "rows")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "sync":
        sync()
    elif cmd == "show":
        show()
    else:
        raise SystemExit("usage: store.py [sync|show]")
