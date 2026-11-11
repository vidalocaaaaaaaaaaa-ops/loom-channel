---
name: faceless-videos
description: Make narrated faceless videos (YouTube, TikTok, Reels, Shorts) that are rendered from code on the user's own machine, with a local AI voice, for $0 and no API keys. Two built-in styles — NIGHTLINE (cinematic true-crime / horror: lit corridors and rooms, faceless figures edged in ember light, yellow karaoke captions, mono date stamps) and BLUEPRINT (data / explainer: flat typographic boards with counting numbers, bars, lines, timelines) — plus a small style-pack API for new looks. Ships a measured QC gate (caption reading speed, WCAG caption contrast against the actual frames, platform safe areas, LUFS, true peak, black/frozen frames), a procedural score and sound design, and a packaging step. Use whenever the user wants a faceless video or channel, a narrated story short, a true-crime or horror reconstruction, a "what happened" explainer, a data/stat video, a video like Fern, Zack D. Films, or any "make me a video about X" where the visuals should be built, not stock-footaged.
---

# Faceless Videos (v3)

You do the work. The user picks a topic and a style, approves one plan, and gets a finished
MP4 with voice, score, sound design, captions and a cover — plus a QC report that either
passes or tells you exactly what to fix.

**Everything below is verified by running it, not by describing it.** If a command fails,
read the error, fix it, re-run. Never show the user a frame you have not looked at.

```
SKILL      = the folder this file is in
PROJECT    = <SKILL>/projects/<short-name>/     (one project.json = one video)
```

---

## 0. First run on a machine

```bash
bash <SKILL>/scripts/setup.sh          # venv + deps + voice model (~360 MB), prints READY
bash <SKILL>/scripts/selftest.sh       # builds 2 tiny videos end-to-end, prints SELFTEST PASSED
```

`setup.sh` is idempotent and installs only: `numpy`, `pillow`, `soundfile`,
`imageio-ffmpeg` (bundles ffmpeg — no system ffmpeg needed), `kokoro-onnx` (+ onnxruntime)
and the Kokoro-82M voice. Optional: `scipy` (faster audio filters), `faster-whisper`
(only if the user wants transcription-based alignment instead of the default).
No Node, no Chrome, no three.js, no GPU. It works offline after setup.

If anything is missing later: `python -m loom.cli doctor` prints a READY / NOT READY line
per dependency.

## 1. Ask at most one question

If the brief does not already answer it, ask **once**, with both options described in one
line each:

- **NIGHTLINE** — a true-crime / horror / "something is wrong here" story. Corridors at
  night, doors that leak light, a figure at the end of the hall.
- **BLUEPRINT** — an explainer, a stat video, a "how X actually works". Numbers that count,
  bars that grow, one idea per board.

Anything else (survival cartoons, stick figures, clay documentaries) is a **new style
pack** — see `docs/STYLE-PACK.md`. Offer that only if the user asks for a look that is
neither of the two; it is a 150-line job, not a rewrite.

Do not ask about voice, music, length or aspect in the same breath — take the defaults
from the style, and put the real decisions in the plan screen (step 3) where the user can
see what they are choosing.

## 2. Intake (one message, defaults pre-filled)

Ask for what is still unknown, in ONE message:

1. topic, or "you pick 3 ideas" (then offer three one-line pitches with a hook each)
2. a link to a video whose *format* they like (optional — take structure and pacing only)
3. true story or fiction
4. length: `30s` / `45s` / `60s` (shorts) or `3-5 min` (long-form)
5. aspect: `9:16` / `16:9` / `1:1`
6. the handle / end-card line, if any

`"just go"` means: pick the best idea, 40-45 s, 9:16, the style's default voice.

Then **write the script before you touch any code**, and show it as a plan.

## 3. The plan screen — one message, then wait

Show exactly this, short enough to read on a phone:

```
TITLE
style · aspect · target length · voice · score

SCRIPT (one line per shot, with the shot's set in brackets)
 1  [corridor]  The phone rang at two fourteen in the morning.
 2  [door]      The call came from room four oh two.
 ...
DATA  (only if the script makes claims): each number, and its source
LOOK  three adjectives, and what the user will see in the first second
TIME  ~2 min of your time, ~6 min of render
```

Ask **“Build it?”** and stop. Do not render before the answer.

## 4. Script rules (this is most of the quality)

- **Write for the ear.** One idea per sentence. 6-14 words. If a sentence needs a comma
  splice to survive, split it.
- **Numbers the way they are said.** `2:14` → write "two fourteen". `1996` → "nineteen
  ninety six". `$4.2m` → "four point two million". The voice reads what you write, and the
  captions show what the voice says; if they disagree, the video looks broken.
- **A hook inside the first 1.5 s.** Nine shapes that work, pick one and commit: a claim
  that sounds impossible ("Room four oh two has been sealed for thirty years."); a clock
  ("At 2:14 in the morning…"); a direct contradiction ("Everyone in the building was
  asleep. The phone was not."); a number that needs explaining; a question the user cannot
  answer; a rule ("Never answer the phone after midnight."); an object ("There is one
  handprint on the mirror."); a countdown; a confession in first person.
- **One open loop per 15 s.** Say something the viewer needs resolved, and resolve it
  later. Never resolve it in the same line.
- **Cut on the sentence.** Every sentence is a cut point. No shot longer than ~8 s.
- **Land the payoff at 85-95% of the runtime**, then one line of aftermath, then out.
- **Last line should be the most quotable line.** That is what gets shared and what makes
  the loop work.
- **True stories get sources.** Every number, date and name goes in a `source` field on
  the script line and in the plan. If you cannot verify it, cut it or label it as fiction.
  Fiction gets labelled as a story on the opening card.
- **No gore, no injury on screen, no faces on real people.** Every style is faceless by
  design; keep it that way even when the story is documented.

## 5. Build it

```bash
cd <SKILL>
export LOOM_MODEL_DIR=~/.cache/loom/models          # setup.sh wrote this for you

# start from a working example (copies project.json + keeps the engine shared)
python -m loom.cli new nightline my-video           # or: cp -r projects/room-402 projects/my-video
$EDITOR projects/my-video/project.json              # script, per-line set/viz, voice, cards

python -m loom.cli voice  projects/my-video         # TTS per line + word timings (data/words.json)
python -m loom.cli build  projects/my-video         # timeline + score + sound design -> data/mix.wav
python -m loom.cli still  projects/my-video --t 2,8,14   # LOOK AT THESE
python -m loom.cli qc     projects/my-video         # measured gate + contact sheet
python -m loom.cli render projects/my-video         # renders/master.mp4
python -m loom.cli package projects/my-video        # deliver/share.mp4 + cover.jpg + caption.txt
```

`--draft` on `render` gives a half-size 12 fps-ish check in ~1/6 the time. `qc` always runs at
half scale and takes seconds, so run it after every change to the script.

### The one file that matters

`project.json` is the single source of truth. Everything else is derived and disposable:
delete `data/words.json` and re-run `voice`, delete `data/mix.wav` and re-run `build`.
That means pacing is edited as **text**, not by moving clips around.

```jsonc
{
  "name": "room-402", "style": "nightline", "aspect": "9:16", "fps": 30, "seed": 11,
  "platform": "tiktok",                        // drives safe areas + packaging limits
  "voice": { "name": "am_onyx", "speed": 0.92, "gap": 0.62 },
  "open_card": { "kicker": "A NIGHT CLERK'S ACCOUNT", "title": "ROOM\n402", "hold": 2.3 },
  "end_card":  { "title": "ROOM 402", "subtitle": "Part Two: The Register" },
  "grade":    { "exposure": 0.92, "scrim": 0.42, "split": ["#2b4a6b", "#ffd9a8", 0.30] },
  "captions": { "size_h": 0.043, "anchor_y": 0.755, "highlight": "#ffcc33" },
  "script": [
    { "id": "l1", "text": "The phone rang at two fourteen in the morning.",
      "set": "corridor", "date": "2:14 A.M.",
      "set_params": { "lights": [2.6, 6.4, 10.2], "dead": [2], "cold_end": 0.35 } },
    { "id": "l2", "text": "The call came from room four oh two.",
      "set": "door", "set_params": { "number": "402", "dist": 3.9 } }
  ]
}
```

Voice: `python -m loom.cli voices` lists 13 named voices with character notes.
Styles: `python -m loom.cli styles`.

## 6. Look at it before the user does

`qc` writes `review/contact_sheet.jpg` (36 frames) and `data/qc.json`. Open the sheet, then
open the 2-3 frames that matter as full-size PNGs (`--t` on `still`). Ask of each frame:

1. Does it obey the style's look (palette, light, type)?
2. Does it say what the narration says *at that moment*?
3. Is every word on screen spelled right, true, and readable on a phone?
4. Is the subject in frame, in focus, and not fighting the caption?

The gates are measured, so trust them over taste for these: caption reading speed ≤ 19
chars/s, caption contrast ≥ 4.5:1 against the real frame, captions inside the platform's
safe area, mean frame luminance 6-42 %, ≥ 9 dB of voice over the bed, -14 LUFS / -1 dBTP.
A `fail` blocks delivery. A `warn` needs a decision you can defend.

## 7. Deliver

`package` produces `deliver/share.mp4` (platform size limit respected automatically),
`deliver/cover.jpg` (best frame that has no caption on it), `deliver/caption.txt` (title +
hook + hashtags) and `deliver/package.json`. Then:

- Open `deliver/share.mp4` for the user, and show 2-3 stills from it.
- Give the numbers: duration, size, LUFS, QC verdict.
- Offer one round of precise changes ("slower on the twist", "different voice",
  "cut 3 s off the middle") and re-render only what changed.


## 8. Running it as a channel (automatic posting)

`channel/` turns the skill into a scheduled show. Full setup in `channel/README.md`;
the short version:

```bash
python channel/make_episode.py --list      # what is queued across series
python channel/make_episode.py --next      # render the next episode, end to end
python channel/queue.py status             # pending / published / video links
python channel/upload_youtube.py --manifest channel/pending/<slug>.json --dry-run
```

- `channel/plan.json` — series rotation and default upload metadata.
- `channel/series/*.json` — shared look + every episode's lines. **Adding an episode
  object is the only maintenance task.** Six are queued ahead.
- `channel/state.json` — what has been released; a released part is never re-rendered.
- `.github/workflows/short.yml` — weekly cron: render job, then a publish job that
  waits on the `youtube-approval` environment. The upload job only receives the OAuth
  secrets after a human approves.

Two rules that are not negotiable when automating: **a failed QC gate stops the run
before the render**, and **the uploader refuses `--privacy public` unless the manifest
says `0 fail`**. Automation without those two is how a channel fills up with videos
nobody would post by hand.

## Never

- Never generate video or images with an AI model. Everything is drawn in code.
- Never spend the user's money or credits; no API keys are needed and none should be added.
- Never copy another creator's script, shots or frames. Take structure, write your own words.
- Never overwrite an existing project folder without asking.
- Never deliver a render whose `qc` failed, or that you have not looked at.
- Never run two full renders at once on a 4 GB machine; render `--draft` while iterating.
- Never publish an unsourced number in a true story. Fictional series must say so in the description.
