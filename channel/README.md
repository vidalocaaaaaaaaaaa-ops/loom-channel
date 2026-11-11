# Automatic posting — ROOM 402 + SITE NINE

Run this once and the channel renders a new episode every week, holds it for your
approval, and publishes it after you click Approve. No server, no paid API, $0/month
on a public repo.

```
cron (Mon 17:00 UTC)
      │
      ▼
[render job]  make_episode.py  →  voice → build → QC gate → render → package
      │                                  │
     │                       a FAILED gate stops here (no video, no upload)
      ▼
  artifact (mp4 + cover + manifest)
      │
      ▼
[publish job] ── waits on the "youtube-approval" environment ──► you click Approve
      │
      ▼
upload_youtube.py  → videos.insert → thumbnail → playlist → state.json commit
```

The pipe between the two jobs is `channel/pending/<episode>.json`. The upload job has
**no credentials** until it is approved, so an unreviewed render can never go live.

---

**New here? Read `channel/SETUP.md` instead** — it is the same thing as a click-by-click
walkthrough with checkpoints, expected log output and a troubleshooting table.

## 1. What you need (10 minutes)

| thing | why |
|---|---|
| a GitHub repo containing this folder | the scheduler runs in Actions |
| a Google Cloud project with **YouTube Data API v3** enabled | the upload API |
| an OAuth **Desktop** client + a refresh token | your channel's permission |
| the repo environment **`youtube-approval`** with you as required reviewer | the gate |

Make the repo **public** if you are on GitHub Free: public repos get unlimited Actions
minutes *and* environment protection rules (private repos need Pro for required
reviewers). Secrets and the token are never in the repo.

---

## 2. Google side (one time)

1. <https://console.cloud.google.com> → new project.
2. **APIs & Services → Library → YouTube Data API v3 → Enable.**
3. **OAuth consent screen** → User type **External** → app name + your email.
4. **Audience → Publish app.** Status must read **In production**, not *Testing*.
   In Testing Google kills every refresh token after **7 days**, which silently breaks
   a weekly schedule. Unverified is fine — you will see "Google hasn't verified this
   app" once and click *Advanced → Go to…*.
5. **Credentials → Create credentials → OAuth client ID → Desktop app.**

Then, on your own machine (not in CI):

```bash
cd faceless-videos-v3
python channel/youtube_auth.py --client-id XXX.apps.googleusercontent.com --client-secret YYY
```

It opens the consent screen, catches the redirect on `127.0.0.1:8765`, and saves
`channel/.secrets/youtube.json` (gitignored) plus prints the three values.

---

## 3. GitHub side

```bash
# repo secrets (paste when prompted)
gh secret set YT_CLIENT_ID
gh secret set YT_CLIENT_SECRET
gh secret set YT_REFRESH_TOKEN
```

Then create the approval gate:

> **Settings → Environments → New environment → `youtube-approval`**
> → *Required reviewers* → add yourself → Save.

Optional: under the environment, add a **deployment branch rule** (`main`) so only
main can publish.

Push the folder as the repo root (`SKILL.md`, `loom/`, `channel/`, `.github/`). The
workflow is already at `.github/workflows/short.yml`.

---

## 4. First run

Do a smoke test before trusting the schedule:

```bash
gh workflow run short -f draft=true -f publish=false     # half-scale, no upload
```

That renders the next episode at half resolution in a few minutes and stops. Check the
artifact on the run page. Then a real one:

```bash
gh workflow run short
```

The render job runs ~15–25 min, then the run pauses with a yellow **"Waiting for
review"** banner. Approve it at the run page → the upload happens → `state.json` is
committed and the episode is marked released.

Local equivalents:

```bash
python channel/make_episode.py --list            # queue and what is left
python channel/make_episode.py --next            # render the next episode
python channel/queue.py status                   # pending / history / video links
python channel/upload_youtube.py --manifest channel/pending/<slug>.json --dry-run
python channel/upload_youtube.py --manifest channel/pending/<slug>.json --privacy unlisted

# a film you rendered before this automation existed:
python channel/manifest_for.py projects/room-402-part3
```

---

## 5. Writing episodes

`channel/plan.json` says which series alternate. `channel/series/<slug>.json` holds the
shared look (voice, grade, captions) **and** every episode's lines.

Adding an episode is the only thing you have to do to keep the channel fed:

```json
{
  "part": 7,
  "slug": "room-402-part7",
  "title": "THE CALL",
  "open_card": { "kicker": "PART SEVEN", "title": "THE\nCALL", "hold": 2.2 },
  "end_card":  { "title": "ROOM 402", "subtitle": "Part Eight: Guests", "hold": 2.6 },
  "hook": "Part 7 of ROOM 402.",
  "social": { "body": "One line for the description." },
  "script": [
    { "id": "l1", "text": "…", "set": "corridor", "date": "5:05 A.M.",
      "set_params": { "lights": [2.6, 6.4, 10.2, 14.0], "haze": 0.6 } }
  ]
}
```

Rules the pipeline enforces for you:

- **QC is a gate, not a report.** A failed check (caption speed, contrast, loudness,
  clipping, safe areas, black frames…) exits the job before the render, so a bad script
  costs seconds instead of 20 minutes.
- **`0 fail` must appear in the manifest** or the uploader refuses to publish publicly.
- **A published part is never re-rendered**: `state.json` keeps `released` per series.
- **Rotation**: `room402` → `site9` → `room402` …, skipping series with an empty queue.

Two series ship with six episodes queued (ROOM 402 parts 4–6, SITE NINE logs 1–3), so
the channel runs for six weeks before you have to write anything.

---

## 6. What it costs

| item | cost |
|---|---|
| GitHub Actions (public repo) | $0, unlimited minutes |
| Actions (private repo) | ~80 min/month of the 2,000 free — still $0 |
| YouTube Data API | $0 (`videos.insert` ≈1,600 of 10,000 daily units, so ~6 uploads/day max — one is plenty) |
| Voice model | 350 MB, downloaded once and cached between runs |

---

## 7. When something breaks

| symptom | cause | fix |
|---|---|---|
| `invalid_grant` on token refresh | OAuth app still in **Testing** | publish the app, re-run `youtube_auth.py`, update the secret |
| run renders then never uploads | nobody approved the environment | approve at the run page; or `gh run list` → the run |
| `403 quotaExceeded` | >6 uploads in a day on the default quota | wait for midnight PT |
| upload `403`, thumbnail skipped | channel not eligible for custom thumbnails | harmless — the video is live, YouTube picked a frame |
| QC fail `caption density` | line too wordy | shorten the line; limit is 19 chars/s |
| QC fail `loudness` | mix changed | re-run `make_episode.py` (it re-mixes) |
| nothing left in the queue | every episode released | add episodes to `channel/series/*.json` |
| two runs racing | — | `concurrency: group: short` already serialises them |

---

## 8. Optional: Supabase mirror

If you want the queue visible in a dashboard instead of `state.json`, `channel/store.py`
mirrors state into Supabase (`channel/supabase.sql` creates the table). It is entirely
optional and off unless `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` are set.

```bash
python channel/store.py sync      # push state.json + pending manifests
python channel/store.py show      # read it back
```

---

## 9. Honest limits

- The scheduler is GitHub's; a scheduled run can be delayed by a few minutes at peak
  times, and scheduled workflows are disabled automatically after 60 days of no commits
  (the weekly state commit resets that, as long as something publishes).
- Episodes are written by a human or an agent — the automation renders, gates and
  publishes; it does not invent new story. That is deliberate: it is what stops the feed
  filling with things you would not put your name on.
- Uploads are public immediately after approval. Use `--privacy unlisted` on the first
  couple to check how the Shorts player crops them.
