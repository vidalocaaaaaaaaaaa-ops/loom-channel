#!/usr/bin/env python3
"""One-time OAuth consent -> a refresh token you can paste into repo secrets.

Run this on your own machine (not in CI). It opens Google, catches the redirect
on 127.0.0.1, and prints the three values the uploader needs.

    python channel/youtube_auth.py --client-id XXX.apps.googleusercontent.com \
                                   --client-secret YYY

What you need first (about 10 minutes, free):
  1. console.cloud.google.com -> new project
  2. "YouTube Data API v3" -> Enable
  3. OAuth consent screen -> External -> fill app name + your email as support
  4. Publish the app (status must be "In production", not "Testing" — in Testing
     every refresh token dies after 7 days, which breaks scheduled uploads)
  5. Credentials -> Create credentials -> OAuth client ID -> type "Desktop app"
     (a "Web application" client also works; then add
      http://127.0.0.1:8765/ as an authorised redirect URI)

The scope requested is https://www.googleapis.com/auth/youtube — full control of
your channel, which is what uploading needs. Nothing else.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube"
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/"

_result = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):        # keep the console readable
        pass

    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        if "code" in params:
            _result["code"] = params["code"][0]
            body = b"<h2>Loom: authorised.</h2><p>Close this tab and go back to the terminal.</p>"
        else:
            _result["error"] = params.get("error", ["unknown"])[0]
            body = b"<h2>Loom: not authorised.</h2><p>Check the terminal.</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client-id", default=os.environ.get("YT_CLIENT_ID"))
    ap.add_argument("--client-secret", default=os.environ.get("YT_CLIENT_SECRET"))
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", default="channel/.secrets/youtube.json",
                    help="where to save the token (gitignored)")
    args = ap.parse_args(argv)

    if not args.client_id or not args.client_secret:
        print(__doc__)
        print("error: pass --client-id/--client-secret or set YT_CLIENT_ID/YT_CLIENT_SECRET",
              file=sys.stderr)
        return 2

    global REDIRECT
    if args.port != PORT:
        REDIRECT = f"http://127.0.0.1:{args.port}/"

    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": args.client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",     # this is what returns a refresh_token
        "prompt": "consent",          # force it even on re-consent
        "include_granted_scopes": "true",
    })
    print("\n1. Opening Google's consent screen.")
    print("   If your app is unverified you will see 'Google hasn't verified this app'")
    print("   -> Advanced -> Go to <your app> (unsafe). That is expected for a personal app.\n")
    print("   " + url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"2. Waiting for the redirect on {REDIRECT} (2 minutes)...")
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        t.join(timeout=120)

    if "code" not in _result:
        print("error: no authorisation code came back (" + str(_result.get("error")) + ")")
        return 2

    body = urllib.parse.urlencode({
        "code": _result["code"],
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())

    if "refresh_token" not in data:
        print("error: no refresh_token in the response:")
        print(json.dumps(data, indent=2))
        print("\nUsually means this client was already authorised once. Either revoke it at")
        print("myaccount.google.com/permissions and retry, or keep using the old token.")
        return 2

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"client_id": args.client_id,
                   "client_secret": args.client_secret,
                   "refresh_token": data["refresh_token"]}, fh, indent=2)
    os.chmod(args.out, 0o600)

    print("\n3. Done. Three repo secrets to add (Settings -> Secrets and variables -> Actions):")
    print("\n   YT_CLIENT_ID     " + args.client_id)
    print("   YT_CLIENT_SECRET " + args.client_secret)
    print("   YT_REFRESH_TOKEN " + data["refresh_token"][:12] + "…  (full value in "
          + args.out + ")")
    print("\n   Best way to add them without pasting into a terminal:")
    print("   gh secret set YT_CLIENT_ID --body ...    (or use the web UI)")
    print("\n   Then test locally:  python channel/upload_youtube.py \\")
    print("        --manifest channel/pending/<episode>.json --privacy unlisted --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
