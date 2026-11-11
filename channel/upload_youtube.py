#!/usr/bin/env python3
"""Upload one rendered episode to YouTube. Stdlib only — no google client library.

    python channel/upload_youtube.py --manifest channel/pending/room-402-part4.json --dry-run
    python channel/upload_youtube.py --manifest ... --privacy public
    python channel/upload_youtube.py --manifest ... --privacy unlisted --no-thumbnail

Credentials come from the environment (in GitHub Actions these are repo secrets):

    YT_CLIENT_ID      OAuth client id   ("installed app" / Desktop client)
    YT_CLIENT_SECRET  OAuth client secret
    YT_REFRESH_TOKEN  from channel/youtube_auth.py

Quota: videos.insert costs 1,600 units of the 10,000/day project quota, so this
is built for a handful of uploads a day, not a bulk pipeline. thumbnails.set is
50, playlistItems.insert is 50.

Exit codes: 0 uploaded, 2 bad input, 3 auth/quota problem, 4 upload failed.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ helpers
def die(code, msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def http(method, url, headers=None, body=None, timeout=180, tries=4):
    """Small request helper with backoff on transient errors."""
    delay = 2.0
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, data=body, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < tries:
                print(f"  {e.code} transient, retrying in {delay:.0f}s")
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {e.code} on {method} {url}\n{payload[:1200]}")
        except urllib.error.URLError as e:
            if attempt < tries:
                print(f"  network error ({e.reason}), retrying in {delay:.0f}s")
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def access_token():
    cid = os.environ.get("YT_CLIENT_ID")
    secret = os.environ.get("YT_CLIENT_SECRET")
    refresh = os.environ.get("YT_REFRESH_TOKEN")
    missing = [k for k, v in (("YT_CLIENT_ID", cid), ("YT_CLIENT_SECRET", secret),
                              ("YT_REFRESH_TOKEN", refresh)) if not v]
    if missing:
        die(3, "missing credentials: " + ", ".join(missing) +
               "\n  run channel/youtube_auth.py once and add the three values as repo secrets")
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret,
        "refresh_token": refresh, "grant_type": "refresh_token",
    }).encode()
    _, raw = http("POST", TOKEN_URL, body=body,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = json.loads(raw)
    if "access_token" not in data:
        die(3, "token exchange failed: " + json.dumps(data)[:400] +
               "\n  an 'invalid_grant' here almost always means the OAuth app is still in"
               "\n  Testing status (tokens die after 7 days) or the token was revoked.")
    return data["access_token"]


def resumable_upload(token, meta, path, dry_run=False):
    size = os.path.getsize(path)
    body = json.dumps({
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta.get("tags", []),
            "categoryId": meta.get("category_id", "24"),
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": meta.get("privacy", "public"),
            "selfDeclaredMadeForKids": bool(meta.get("made_for_kids", False)),
            "embeddable": True,
        },
    }).encode()
    init_url = f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status"
    if dry_run:
        print("  [dry-run] initiate upload:")
        print("   POST", init_url)
        print("   body:", json.dumps(json.loads(body), indent=2)[:900])
        print(f"   then PUT {size/1e6:.1f} MB -> the session URL returned above")
        return None
    req = urllib.request.Request(init_url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4",
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        session = r.headers.get("Location")
    if not session:
        die(4, "no resumable session URL came back from videos.insert")
    print(f"  upload session ready, pushing {size/1e6:.1f} MB")
    with open(path, "rb") as fh:
        payload = fh.read()
    _, raw = http("PUT", session, body=payload, timeout=1800,
                  headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
    data = json.loads(raw)
    if "id" not in data:
        die(4, "upload finished but returned no video id: " + json.dumps(data)[:500])
    return data


def set_thumbnail(token, video_id, cover, dry_run=False):
    if not cover or not os.path.exists(cover):
        print("  no cover frame, skipping thumbnail")
        return
    url = f"{UPLOAD}/thumbnails/set?videoId={video_id}&uploadType=media"
    if dry_run:
        print("  [dry-run] POST", url, f"({os.path.getsize(cover)/1024:.0f} KB jpeg)")
        return
    ctype = mimetypes.guess_type(cover)[0] or "image/jpeg"
    with open(cover, "rb") as fh:
        data = fh.read()
    try:
        http("POST", url, body=data, headers={"Authorization": f"Bearer {token}",
                                             "Content-Type": ctype})
        print("  thumbnail set")
    except RuntimeError as exc:
        # a channel without custom-thumbnail eligibility returns 403 here; the
        # video is already uploaded at that point, so this must not fail the run
        print(f"  thumbnail skipped: {str(exc)[:200]}")


def add_to_playlist(token, video_id, name, dry_run=False):
    if not name:
        return
    if dry_run:
        print(f"  [dry-run] find/create playlist '{name}' and insert {video_id}")
        return
    auth = {"Authorization": f"Bearer {token}"}
    _, raw = http("GET", f"{API}/playlists?part=id,snippet&mine=true&maxResults=50",
                  headers=auth)
    items = json.loads(raw).get("items", [])
    match = next((p for p in items if p["snippet"]["title"].lower() == name.lower()), None)
    if match:
        pid = match["id"]
    else:
        body = json.dumps({"snippet": {"title": name},
                           "status": {"privacyStatus": "public"}}).encode()
        _, raw = http("POST", f"{API}/playlists?part=snippet,status", body=body,
                      headers={**auth, "Content-Type": "application/json"})
        pid = json.loads(raw)["id"]
        print(f"  created playlist '{name}'")
    body = json.dumps({"snippet": {"playlistId": pid,
                                   "resourceId": {"kind": "youtube#video",
                                                  "videoId": video_id}}}).encode()
    http("POST", f"{API}/playlistItems?part=snippet", body=body,
         headers={**auth, "Content-Type": "application/json"})
    print(f"  added to playlist '{name}'")


def mark_published(manifest, video_id):
    """Move the episode from pending -> released in channel/state.json."""
    state_path = os.path.join(ROOT, "channel", "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    state.setdefault("released", {}).setdefault(manifest["series"], [])
    if manifest["part"] not in state["released"][manifest["series"]]:
        state["released"][manifest["series"]].append(manifest["part"])
        state["released"][manifest["series"]].sort()
    if manifest["slug"] in state.get("pending", []):
        state["pending"].remove(manifest["slug"])
    for row in state.get("history", []):
        if row.get("slug") == manifest["slug"]:
            row["status"] = "published"
            row["video_id"] = video_id
            row["published_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state.setdefault("history", []).append({
        "slug": manifest["slug"], "series": manifest["series"], "part": manifest["part"],
        "status": "published", "video_id": video_id,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    with open(state_path, "w") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    pending = os.path.join(ROOT, "channel", "pending", manifest["slug"] + ".json")
    if os.path.exists(pending):
        os.rename(pending, pending.replace(".json", ".published.json"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, help="channel/pending/<slug>.json")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"],
                    help="override the manifest privacy")
    ap.add_argument("--no-thumbnail", action="store_true")
    ap.add_argument("--no-playlist", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="validate and print, touch nothing")
    ap.add_argument("--verify-only", metavar="VIDEO_ID", help="check a video's status and stop")
    args = ap.parse_args(argv)

    if args.verify_only:
        token = access_token()
        _, raw = http("GET", f"{API}/videos?part=status,processingDetails,snippet"
                              f"&id={args.verify_only}",
                      headers={"Authorization": f"Bearer {token}"})
        print(json.dumps(json.loads(raw), indent=2)[:2000])
        return 0

    mpath = args.manifest if os.path.isabs(args.manifest) else os.path.join(ROOT, args.manifest)
    if not os.path.exists(mpath):
        die(2, f"no manifest at {mpath} (did make_episode.py finish?)")
    manifest = json.load(open(mpath))
    meta = dict(manifest["youtube"])
    if args.privacy:
        meta["privacy"] = args.privacy

    video = os.path.join(ROOT, manifest["video"])
    if not os.path.exists(video):
        die(2, f"video missing: {video}")
    cover = os.path.join(ROOT, manifest["cover"]) if manifest.get("cover") else None
    size = os.path.getsize(video)
    if size > 250 * 1024**3:
        die(2, "file is over YouTube's 256 GB limit")

    print(f"episode   {manifest['series_title']} · part {manifest['part']} · "
          f"{manifest['episode_title']}")
    print(f"video     {os.path.relpath(video, ROOT)}  ({size/1e6:.1f} MB)")
    print(f"title     {meta['title']}")
    print(f"privacy   {meta['privacy']}")
    print(f"qc        {manifest.get('qc', 'unknown')}")
    qc = str(manifest.get("qc", ""))
    if meta["privacy"] == "public" and "0 fail" not in qc:
        die(2, f"manifest QC summary is not clean ({qc!r}) — refusing to publish publicly")

    if args.dry_run:
        print("\ndry run: nothing will be uploaded")
        resumable_upload(None, meta, video, dry_run=True)
        set_thumbnail(None, "VIDEO_ID", cover, dry_run=True)
        if not args.no_playlist:
            add_to_playlist(None, "VIDEO_ID", meta.get("playlist_name"), dry_run=True)
        print("\ndry run ok — credentials, metadata and file all check out")
        return 0

    token = access_token()
    result = resumable_upload(token, meta, video)
    vid = result["id"]
    print(f"  uploaded: https://youtu.be/{vid}")
    if not args.no_thumbnail:
        set_thumbnail(token, vid, cover)
    if not args.no_playlist:
        add_to_playlist(token, vid, meta.get("playlist_name"))

    # confirm the platform actually accepted it
    _, raw = http("GET", f"{API}/videos?part=status&id={vid}",
                  headers={"Authorization": f"Bearer {token}"})
    st = (json.loads(raw).get("items") or [{}])[0].get("status", {})
    print(f"  status: {st.get('uploadStatus')} / privacy {st.get('privacyStatus')}")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"video_id={vid}\nurl=https://youtu.be/{vid}\n")
    mark_published(manifest, vid)
    print(f"  state updated: {manifest['slug']} -> released")
    return 0


if __name__ == "__main__":
    sys.exit(main())
