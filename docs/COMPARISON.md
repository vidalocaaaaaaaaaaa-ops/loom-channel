# v2 → v3: what changed and why

Written from the v2 `SKILL.md` / `README.md` (the code was not part of the hand-off), so this
compares **design decisions**, not line counts. Measured numbers are from a 2-vCPU Linux box
with 2 GB RAM — a normal laptop is 5-8× faster at the render step.

## The short version

v2 is a set of five hand-tuned films you copy and re-skin. v3 is a **rendering engine with two
styles on top of it**, plus a **measured QC gate** and an assertion that the whole thing works
on the target machine before you make anything.

| | v2 | v3 |
|---|---|---|
| Runtime stack | Node 22 + headless Chrome + three.js + `uv` + Python | Python only |
| Install | ~1 GB (Kokoro 340 MB + Whisper small.en 0.5 GB + env) | ~360 MB (Kokoro only) + 5 pip packages |
| First proof it works | `selftest.sh`, 5-8 min for 3 clips | `selftest.sh`, 85 s for 2 full videos incl. QC |
| Word timings | Whisper **transcription** (drifts; mishears names and numbers) | **alignment of the known script** to its own waveform (no model, deterministic) |
| Captions | styled text per shot | chunked karaoke engine: fixed layout, per-word highlight, safe-area + contrast aware |
| Caption quality check | human eyeball on the contact sheet | measured chars/s, WCAG contrast against the real frame, platform UI zones |
| Audio | Kokoro + music + numpy SFX | + ducking curve, ITU-style LUFS measurement, lookahead true-peak limiter, voice-over-bed ratio gate |
| Motion | three.js scenes / per-style code | camera rig (handheld fBm + shake impulses + keyframed push), springs for 2-D |
| Re-pacing | rewrite the shot list | rewrite a sentence; shots, cuts, cues, SFX re-derive |
| New look | fork an example project | one 150-400 line style module (see `docs/STYLE-PACK.md`) |
| Delivery | master + share copy + cover + caption | same, with platform size/limit presets and automatic cover-frame choice |
| Quality gate | "look at every frame" | 15 measured gates; a `fail` blocks delivery |

## The five changes that matter

**1. Word timings come from the script, not from a transcription.**
Whisper on a 24 kHz Kokoro render will happily hear "the kid came" for "the call came", and
its timestamps drift up to a second across a 6-second line — which is visible on a caption
that highlights the word being spoken. v3 synthesises line by line (so line boundaries are
exact by construction), detects speech runs from the energy envelope, distributes words by
syllable weight inside each run, then snaps every boundary to the quietest frame nearby.
Numbers are expanded to how they are spoken (`2:14` → "two fourteen", `1994` → "nineteen
ninety four") before counting syllables. Deterministic, no model, ~10 ms per line, and it
self-reports a confidence score.

**2. Captions are a layout, not a string.** A caption group is laid out once and never
reflows; words light up in place, in yellow, with a small pop on the active word. Chunking is
by words + characters + pause length, so a group never outlives its sentence. `qc` then
checks reading speed (chars/s), WCAG contrast against the pixels actually behind the words,
and whether the whole band sits above TikTok's/Reels'/Shorts' UI.

**3. Light is a model, not a filter.** Surfaces have an albedo and are subdivided into panels
that are shaded by a real rig (ambient + point lights with inverse-square falloff and a cosine
term), mixed toward haze by depth. Glows, shafts and rims go into an additive light buffer
that is occluded by anything registered as a silhouette — so a figure standing in a shaft
actually blocks it — and is then bloomed and tonemapped like a lens. The result is pools of
light and real falloff instead of a flat vignette.

**4. The iteration loop is seconds.** `still --t 8 --scale 0.6 --ss 1` gives you a frame in
about a second; `qc` gives you a contact sheet and 15 measured gates in 8-12 s; `render
--draft` is a half-size cut. You can see and measure every change without a coffee break,
which is the only reason the visuals in here could be tuned 30+ times.

**5. Delivery is a gate, not a hope.** A `fail` in QC stops the pipeline. That includes the
things that quietly ruin a short: 26 chars/s captions, words under the TikTok button bar,
a mix 6 dB below platform loudness, a frozen shot in the middle, three black frames in a row.

## What v2 still has that v3 does not

- **Five finished styles** (Lamplit Ink, Red Ghost, Sunlit Explainer, Stickman, Clay Atlas)
  against two here. v3 ships the engine plus two styles that go in opposite directions —
  a lit 3-D world and a flat type board — because those two prove the toolkit covers the
  range; the other three are style packs to write, not engine work.
- **A three.js pipeline**, which brings cheap PBR-ish materials and glTF assets if you want
  to drop in real models. v3 has no asset importer: everything is drawn.
- **Clay Atlas's depth-camera trick** for stills, which produces genuinely photographic
  texture that procedural drawing cannot. If you want photographic plates, you need an image
  tool; v3 deliberately stays 100 % code.

## What was deliberately rejected

- **Mixing AI image generation in.** It makes the output unrepeatable and drags in
  per-image costs. Both v3 styles are code-only, so a re-render in six months looks the same.
- **A model for alignment.** It was the single biggest source of "the captions are off"
  problems in the transcription approach, and it is not needed when you wrote the words.
- **A GUI.** The timeline is a JSON file and the script is the timeline; an agent can edit
  both, a human can read both in a diff.
