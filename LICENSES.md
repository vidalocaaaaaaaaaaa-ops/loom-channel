# Third-party components

## Bundled in this repo

**Fonts** (`loom/fonts/`), all from Google Fonts, all redistributable:

| file | family | licence |
|---|---|---|
| `Anton-Regular.ttf` | Anton | SIL Open Font License 1.1 |
| `BarlowCondensed-Bold.ttf`, `BarlowCondensed-Medium.ttf` | Barlow Condensed | SIL OFL 1.1 |
| `Inter-Regular.ttf` (variable) | Inter | SIL OFL 1.1 |
| `Oswald.ttf` (variable) | Oswald | SIL OFL 1.1 |
| `PlayfairDisplay.ttf` (variable) | Playfair Display | SIL OFL 1.1 |
| `JetBrainsMono-Bold.ttf` (variable) | JetBrains Mono | SIL OFL 1.1 |
| `PermanentMarker-Regular.ttf` | Permanent Marker | Apache License 2.0 |
| `PatrickHand-Regular.ttf` | Patrick Hand | SIL OFL 1.1 |

**Code** in `loom/` is original, written for this skill. Use it, fork it, ship videos made
with it — no attribution required, no strings.

**Example scripts, sets, drawings and characters** (`projects/room-402`,
`projects/blueprint-demo`) are original fiction / illustrative examples. Free to use, remix
and publish. The blueprint example's numbers are labelled as illustrative: replace them with
sourced figures before publishing.

## Downloaded on first use (not bundled)

- **Kokoro-82M** voice model — Apache License 2.0, via
  [`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx) (MIT), downloaded by
  `scripts/setup.sh` into `~/.cache/loom/models`.
- **onnxruntime** (MIT) — inference for the voice model.
- **imageio-ffmpeg** (BSD-2) — ships a static **FFmpeg** build (LGPL/GPL depending on build
  flags) so no system ffmpeg is required. If you prefer your own binary, set `LOOM_FFMPEG`.
- **numpy** (BSD-3), **Pillow** (MIT-CMU), **soundfile** (BSD-3).
- Optional: **scipy** (BSD-3) for faster IIR filters; **faster-whisper** + a Whisper model
  (MIT) only if you ask for transcription-based alignment.

## Not used, deliberately

No stock footage, no stock music, no stock SFX, no AI image or video generation, no paid
API, no telemetry, no network calls at render time. Every frame and every sample in a
finished video is produced locally by the code in this folder.
