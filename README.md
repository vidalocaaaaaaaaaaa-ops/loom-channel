# faceless-videos v3

Narrated faceless videos, built from code on your own machine. Local voice, procedural score,
measured QC, $0, no API keys, no GPU, no Node, no headless browser.

Two styles ship with it:

| style | what you get | aspect | example project |
|---|---|---|---|
| **NIGHTLINE** | cinematic true-crime / horror. A lit corridor and a hotel room built in world units, faceless figures edged in ember light, karaoke captions, mono date stamps, film grain, procedural score with a heartbeat. | 9:16 · 16:9 | `projects/room-402` (42 s) |
| **BLUEPRINT** | data / explainer. Flat typographic boards: numbers that count up, bars that grow, line charts that draw, timelines, pull-quotes, a HUD frame. | 16:9 · 9:16 | `projects/blueprint-demo` (18 s) |

## Install

```bash
cd faceless-videos-v3
bash scripts/setup.sh      # venv + deps + Kokoro voice (~360 MB)   -> prints READY
bash scripts/selftest.sh   # builds 2 tiny videos end to end        -> prints SELFTEST PASSED
```

Requirements: Python 3.9+, ~1.5 GB of disk, any CPU. First render takes minutes; after that
`qc` is seconds and a draft render is under a minute.

## Make a video

```bash
cp -r projects/room-402 projects/my-story
$EDITOR projects/my-story/project.json      # the script IS the timeline

python -m loom.cli voice   projects/my-story   # local TTS per line + word timings
python -m loom.cli build   projects/my-story   # shots + score + sound design -> data/mix.wav
python -m loom.cli qc      projects/my-story   # measured gate + contact sheet
python -m loom.cli render  projects/my-story   # renders/master.mp4
python -m loom.cli package projects/my-story   # deliver/share.mp4 + cover.jpg + caption.txt
```

`python -m loom.cli styles`, `voices`, and `doctor` list what is available.

## What is in the box

```
SKILL.md              what an agent follows (workflow, script rules, delivery)
loom/                 the engine
  camera.py           pinhole camera, world->screen, near-plane clipping, handheld rig
  ease.py             easing curves, springs, keyframed tracks
  noise.py            value noise / fBm (camera float, flicker, particles)
  timeline.py         project + shot model (one JSON = one video)
  voice.py            per-line TTS, pacing, word alignment
  render.py           frame loop -> ffmpeg pipe, transitions, stills, draft mode
  qc.py               measured quality gates + contact sheet
  package.py          share copy, cover frame, caption + hashtags
  draw/
    canvas.py         supersampled canvas, additive light buffer, film finish
    geo.py            lit surfaces in world space, dust, rain, haze
    figures.py        faceless people with directional rim light
    typekit.py        fonts, balanced wrapping, karaoke caption engine, safe areas
  audio/
    tts.py            Kokoro voices with plain-English character notes
    align.py          known-text word alignment (no transcription needed)
    music.py          procedural scores per style
    sfx.py            phone-speaker-safe sound design
    mix.py            ducking, LUFS, true-peak limiting
  scenes/
    nightline.py      the corridor/room/door/card sets
    blueprint.py      the data-viz boards
projects/             complete, renderable examples
docs/                 STYLE-PACK.md, QC.md, COMPARISON.md
```

## Design rules the engine enforces

- **Text is the timeline.** You write sentences; the engine derives shots, cuts, captions,
  score cues and sound design. Re-pacing the video means re-wording a line, not moving clips.
- **Nothing is a stock asset.** Sets, people, light, music and sound effects are code.
- **One grade for the whole film, one albedo palette per set.** Light modulates albedo; it
  never fakes brightness with opacity.
- **Captions never reflow.** A caption's layout is fixed for its lifetime; words light up in
  place. That is why it reads like a subtitle instead of a slot machine.
- **The QC gate is measured, not vibes.** Reading speed, contrast against the real frame,
  safe areas, LUFS, true peak, black and frozen frames. A `fail` blocks delivery.

## Costs and licences

$0 to run. Kokoro-82M (Apache-2.0) is downloaded once at setup. All fonts are bundled under
the SIL OFL / Apache-2.0 — see `LICENSES.md`. Everything this skill draws or synthesises is
original and free to use in your own videos.
