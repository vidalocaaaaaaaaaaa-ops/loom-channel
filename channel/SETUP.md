# Do this now — full setup, click by click

Everything below is done once. After Phase 9 the channel runs itself: one rendered
episode every Monday, waiting for your click, then live.

**Total: 35–45 min** of your time (plus ~20 min of unattended rendering in Phase 8).

| # | phase | time | you need |
|---|---|---|---|
| 1 | Google Cloud: API + OAuth client | 10 min | a browser, your Google account |
| 2 | Mark the OAuth app "in production" | 2 min | — |
| 3 | Put the code on your machine | 3 min | this workspace's zip |
| 4 | Local install + self-test | 10 min (unattended) | Python 3.9+ |
| 5 | Get your refresh token | 3 min | a browser on the same machine |
| 6 | Create the GitHub repo and push | 5 min | GitHub account |
| 7 | Add three repo secrets | 3 min | the values from phase 5 |
| 8 | Create the approval gate + smoke test | 10 min | — |
| 9 | First real publish | 25 min, mostly waiting | — |

Do them in order. Each phase ends with a ✅ checkpoint — if it does not match, stop
there and read the troubleshooting table at the bottom before continuing.

---

## Phase 1 — Google Cloud: API + OAuth client (10 min)

Sign in as the Google account **that owns the YouTube channel** (or has manager
access to it). Using a different account is the single most common mistake.

**1.1** Open <https://console.cloud.google.com/projectcreate>
→ Project name: `loom-channel` → **Create**. Wait ~10 s, then make sure the
project selector at the top of the page says `loom-channel`.

**1.2** Go to <https://console.cloud.google.com/apis/library/youtube.googleapis.com>
→ **Enable**. (If it already says *Manage*, it is enabled — good.)

**1.3** Go to <https://console.cloud.google.com/apis/credentials/consent>
→ User type: **External** → **Create**.
Fill only what is required:

| field | value |
|---|---|
| App name | `loom` (anything) |
| User support email | your email |
| Developer contact email | your email |

→ **Save and continue** → skip *Scopes* (**Save and continue**) → skip *Test users*
(**Save and continue**) → **Back to dashboard**.

> Ignore the "needs verification" warnings. You are the only user; verification is
> not required for personal use.

**1.4** Go to <https://console.cloud.google.com/apis/credentials>
→ **+ Create credentials** → **OAuth client ID**
→ Application type: **Desktop app** → Name: `loom desktop` → **Create**.

A dialog shows **Client ID** and **Client secret**.

✅ **Checkpoint:** you have two long strings, one ending in
`.apps.googleusercontent.com` (ID) and a 35-character secret. Keep this tab open.

---

## Phase 2 — Mark the OAuth app "in production" (2 min)

This is the step people skip, and then the automation dies on day 8.

Go back to <https://console.cloud.google.com/apis/credentials/consent>
→ under **Publishing status** it currently says **Testing** → click **Publish app** →
**Confirm**.

> **Why:** while an app is in *Testing*, Google expires every refresh token after
> **7 days**. Your weekly run would work twice and then fail with `invalid_grant`.
> In *production* (even unverified) tokens last until you revoke them or stop using
> them for 6 months. Unverified production apps are capped at 100 users — you are user #1.

✅ **Checkpoint:** Publishing status reads **In production**. It may also say
"Verification not required" or "Needs verification" — either is fine, ignore it.

---

## Phase 3 — Put the code on your machine (3 min)

**3.1** In this workspace, download **`faceless-videos-v3.zip`** (top-right download
button in the viewer) and unzip it. You get a folder `faceless-videos-v3/`.

The folder you push to GitHub must be the one that *directly* contains `SKILL.md`,
`loom/`, `channel/` and `.github/`. If you see `faceless-videos-v3/faceless-videos-v3/`,
you unzipped one level too deep — move the inner folder out.

**3.2** Check it looks right:

```bash
cd faceless-videos-v3
ls        # macOS / Linux
```
```powershell
cd faceless-videos-v3
dir       # Windows PowerShell
```

You should see: `SKILL.md  README.md  LICENSES.md  requirements.txt  loom  channel  docs  projects  scripts  .github`

> `.github` is hidden on macOS/Linux. Confirm with `ls -a` — if it is missing, the
> workflow will never run. Re-unzip rather than recreating it by hand.

✅ **Checkpoint:** `ls -a` lists `.github`, `channel`, `loom`, `SKILL.md`.

---

## Phase 4 — Local install + self-test (10 min, unattended)

Only needed to render locally and to run the auth script. Skip to Phase 5 if you
plan to render exclusively in GitHub Actions — but the auth script still needs Python,
so: install anyway. It is also your insurance if Actions ever breaks.

**macOS / Linux**

```bash
python3 --version        # need 3.9 or newer
bash scripts/setup.sh    # ~360 MB download: python env, ffmpeg, fonts, voice model
```

**Windows (PowerShell, from the `faceless-videos-v3` folder)**

```powershell
py -3 --version
py -3 -m pip install -r requirements.txt
py -3 -m pip install imageio-ffmpeg kokoro-onnx
```

Then, in both cases, prove the engine works:

```bash
bash scripts/selftest.sh      # macOS / Linux; builds 2 short videos end to end
```

```powershell
py -3 -m loom.cli doctor      # Windows: expect READY
```

✅ **Checkpoint:** `setup.sh` prints **All set** / `doctor` prints **READY**, and the
self-test ends with **SELFTEST PASSED** (macOS/Linux). First run takes ~10 min because it
renders two small videos.

> **Optional but recommended:** `python3 channel/make_episode.py --list` should print
> the two series and six queued episodes. That means the queue is wired up correctly.

---

## Phase 5 — Get your refresh token (3 min)

Still in the `faceless-videos-v3` folder, with a browser on **the same machine**:

```bash
python3 channel/youtube_auth.py --client-id "PASTE_ID.apps.googleusercontent.com" --client-secret "PASTE_SECRET"
```
```powershell
py -3 channel/youtube_auth.py --client-id "PASTE_ID.apps.googleusercontent.com" --client-secret "PASTE_SECRET"
```

What happens:

1. A browser opens on Google's consent screen.
2. Because the app is unverified you see **"Google hasn't verified this app"** →
   click **Advanced** → **Go to loom (unsafe)**. This is expected — you are warning
   yourself about your own app.
3. Choose the channel's Google account → **Continue** through the permissions
   (it asks for one scope: manage your YouTube account).
4. The tab says **"Loom: authorised. Close this tab."** — done.
5. The terminal prints three lines: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`,
   `YT_REFRESH_TOKEN`, and saves `channel/.secrets/youtube.json` (chmod 600, gitignored).

✅ **Checkpoint:** the terminal shows a `YT_REFRESH_TOKEN` starting with `1//`.
Copy all three values somewhere safe for the next phase. If instead you see
*"no refresh_token in the response"*, revoke the app at
<https://myaccount.google.com/permissions> and run the command again.

> Never commit `channel/.secrets/`. It is already in `channel/.gitignore`.

---

## Phase 6 — Create the GitHub repo and push (5 min)

Make it **public**. On GitHub Free, public repos get unlimited Actions minutes *and*
environment protection rules (private repos need a paid plan for required reviewers).
Nothing sensitive is in the repo — the secrets from Phase 5 are stored by GitHub, not in
the files. Repo name suggestion: `room-402-channel`.

**Option A — web UI**

1. <https://github.com/new> → name `room-402-channel` → **Public** →
   *do not* add a README/.gitignore/licence → **Create repository**.
2. In a terminal, inside `faceless-videos-v3`:

```bash
git init
git add .
git commit -m "loom channel: engine + automation"
git branch -M main
git remote add origin https://github.com/YOURNAME/room-402-channel.git
git push -u origin main
```

When asked for a password, use a **personal access token** (Settings → Developer
settings → Tokens (classic) → Generate new token → scope `repo`), not your password.

**Option B — GitHub CLI** (skips the token dance)

```bash
gh auth login
gh repo create room-402-channel --public --source=. --push
```

✅ **Checkpoint:** the repo page shows `loom/`, `channel/`, `.github/` at the top
level, and the **Actions** tab lists a workflow named **short**. If Actions is empty,
`.github/` did not get pushed — `git add .github` and push again.

---

## Phase 7 — Add three repo secrets (3 min)

**CLI**

```bash
gh secret set YT_CLIENT_ID     --body "PASTE_ID"
gh secret set YT_CLIENT_SECRET --body "PASTE_SECRET"
gh secret set YT_REFRESH_TOKEN --body "PASTE_TOKEN"
```

**Web UI:** repo → **Settings** → *Secrets and variables* → **Actions** →
**New repository secret**, three times. Names must be exactly:

```
YT_CLIENT_ID
YT_CLIENT_SECRET
YT_REFRESH_TOKEN
```

✅ **Checkpoint:** Settings → Secrets and variables → Actions lists exactly those three.

---

## Phase 8 — Create the approval gate, then smoke test (10 min)

**8.1** Repo → **Settings** → **Environments** → **New environment** →
name it exactly **`youtube-approval`** → **Configure environment**.

**8.2** Tick **Required reviewers** → add your own account → **Save protection rules**.

Optional but nice: **Deployment branches** → *Selected branches* → add `main`, so only
main can publish.

> This is the whole safety design: the publish job runs *inside* this environment, so it
> cannot see the secrets until a human approves it. An unreviewed render is inert.

**8.3** Smoke test — half scale, no upload:

```bash
gh workflow run short -f draft=true -f publish=false
gh run watch            # follow it live
```
or in the browser: **Actions → short → Run workflow** → tick *draft* → **Run**.

It renders the next episode (ROOM 402 Part 4: Checkout) at half resolution in ~4–8 min.
Watch for these lines in the render job log:

```
episode: ROOM 402 · part 4 · CHECKOUT
  narration: ...
  mix: ... -14.2 LUFS  peak -1.0 dBTP
  QC PASSED  (17 pass, 3 warn, 0 fail)
  done: .../renders/master.mp4
MANIFEST channel/pending/draft-room-402-part4.json   <- 'draft-' prefix = smoke test
```

✅ **Checkpoint:** the run finishes green in ~8 min and the run page has an artifact
named **episode** holding `master.mp4`, `cover.jpg`, `caption.txt`, `script.md` and the
manifest. Download it and watch it.

A draft deliberately writes `channel/pending/draft-<slug>.json` and does **not** touch
`state.json`, so a smoke test cannot consume an episode or skip it in the rotation.

> Because it is a draft it does **not** enter the publish path — that is intentional, so
> a smoke test can never post.

---

## Phase 9 — First real publish (25 min, mostly waiting)

**9.1** Start a real run:

```bash
gh workflow run short        # or Actions -> short -> Run workflow (leave the boxes alone)
```

**9.2** ~15–25 min later the run shows two jobs: **render + QC** ✅ and
**publish (needs approval)** 🟡 with a banner: *"This job is waiting for approval"*.

**9.3** Click **Review deployments** → select `youtube-approval` → **Approve and deploy**.

Within a minute or two the publish job prints:

```
uploaded: https://youtu.be/XXXXXXXXXXX
  thumbnail set
  added to playlist 'ROOM 402'
  status: uploaded / privacy public
  state updated: room-402-part4 -> released
```

and commits `channel/state.json` back to the repo (commit message `release: room-402-part4`).

**9.4** Open the URL. The Shorts player crops hard — check that the captions are not
under the UI. They sit at 70–81 % of the frame height, which is inside the safe band.

✅ **Checkpoint:** video is public on your channel, in the playlist, with the cover as
thumbnail, and the repo has a new commit marking it released.

**If you would rather not publish blind:** run once with `--privacy unlisted`. Either
edit the workflow's `--privacy public` to `unlisted` for one run, or publish locally
(see "Manual publish" below), look at it, then flip it to public in YouTube Studio.

---

## Phase 10 — What happens from now on

- **Every Monday 17:00 UTC** (18:00 Casablanca in winter) the cron runs: render →
  wait for approval → publish. The rotation alternates **ROOM 402** and **SITE NINE**.
- You get an email when a run needs approval (GitHub notifications).
- Six episodes are already written, so this runs for six weeks. To extend it, add an
  episode object to `channel/series/room402.json` (the shape is in
  `channel/README.md` §5) and push.
- Nothing renders twice: `state.json` remembers what was released.
- To pause everything: **Actions → short → ⋯ → Disable workflow**.

### Manual publish (Parts 1–3, or any episode, without the scheduler)

You already have three finished films. Manifests are built from the renders — no
re-render:

```bash
python3 channel/manifest_for.py projects/room-402          # Part 1
python3 channel/manifest_for.py projects/room-402-part2    # Part 2
python3 channel/manifest_for.py projects/room-402-part3    # Part 3 (already written for you)

python3 channel/upload_youtube.py --manifest channel/pending/room-402-part3.json --dry-run
python3 channel/upload_youtube.py --manifest channel/pending/room-402-part3.json
```

`--dry-run` validates credentials, metadata and the file without touching YouTube.
Add `--privacy unlisted` for a first check, and `--no-thumbnail` if you would rather
pick the frame yourself in Studio.

To drop a pending episode instead of publishing it:

```bash
python3 channel/queue.py skip room-402-part3
```

---

## Troubleshooting

| what you see | what it means | fix |
|---|---|---|
| `invalid_grant` when refreshing the token | OAuth app is still in **Testing** (tokens die at 7 days) | Phase 2, then re-run `youtube_auth.py` and update the secret |
| consent screen says *"Access blocked: authorisation error"* | redirect mismatch | make sure the client is type **Desktop app**, or add `http://127.0.0.1:8765/` as an authorised redirect URI if you used a Web client |
| run renders, then sits forever | nobody approved the environment | open the run, **Review deployments → Approve** |
| `403 quotaExceeded` | more than ~6 uploads in one day on default quota | wait until midnight Pacific |
| `403` on thumbnail but upload succeeded | channel not yet eligible for custom thumbnails (needs phone verification) | harmless; the video is live, set the thumbnail in Studio |
| `nothing left in the queue` | every episode released | add episodes to `channel/series/*.json` |
| `missing credentials: YT_REFRESH_TOKEN` | secret not set, or set on the wrong repo | Phase 7, exact names |
| Actions tab empty | `.github/` was not pushed | `git add -f .github && git commit -m ci && git push` |
| workflow disabled itself after ~2 months | GitHub disables cron on inactive repos | **Actions → short → Enable workflow** (a publish commit prevents this) |
| `captions unreadable` / QC fail in CI | script edit broke a gate | the run stops before rendering; read `data/qc.json` in the log for the exact gate |
| `ModuleNotFoundError: kokoro_onnx` locally | env reset / venv not active | `bash scripts/setup.sh` again |

## What the safety rails actually guarantee

1. **A failed QC gate stops the run before the render.** No video is produced, no
   artifact is kept, nothing can be uploaded.
2. **The uploader refuses `--privacy public` unless the manifest says `0 fail`.**
3. **The publish job has no secrets until a human approves the environment.**
4. **A released part never renders again** — `state.json` is the ledger.

The one thing nothing can protect you from is approving a video you did not watch.
The artifact on the run page is there for exactly that.
