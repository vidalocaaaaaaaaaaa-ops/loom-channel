# The QC gates

`python -m loom.cli qc <project>` renders 36 frames at half scale, measures them, and writes
`review/contact_sheet.jpg` + `data/qc.json`. Exit code is non-zero if any gate `fail`s.

Every number below is measured from the actual render or the actual mix. Nothing is an
opinion. A `warn` is a decision to defend; a `fail` blocks delivery.

## Story structure

| gate | measures | passes when |
|---|---|---|
| duration | runtime, shot count, line count | 8-92 s |
| line length | per-line narration length | longest ≤ 8.5 s |
| cut rate | shots per minute | 4-40 cuts/min |

A 42 s short with 11 shots is 15.7 cuts/min: a new picture every 3.8 s, which is what keeps
a thumb from moving.

## Captions

| gate | measures | passes when | fix |
|---|---|---|---|
| caption density | characters on screen per second | ≤ 19 (warn ≤ 24) | cut words |
| caption chunking | words per group, group duration | none > 6 words, none < 0.55 s | raise `words_per_chunk` |
| caption size | font px as % of frame height | ≥ 3.0 % | raise `captions.size_h` |
| caption safe area | caption band vs the platform's UI zones | band above the bottom UI | raise `anchor_y` |
| text fits frame | longest measured line vs wrap width | ≤ 102 % | shorter sentences |
| caption contrast | WCAG ratio of caption colour vs the sampled caption band | ≥ 4.5:1 | add `plate` or raise `scrim` |

Platform UI zones are per platform (`tiktok`, `reels`, `shorts`, `generic` in
`draw/typekit.py: SAFE`): the bottom third of a 9:16 frame is where the app puts its buttons,
so captions live above it.

## Audio

| gate | measures | passes when |
|---|---|---|
| loudness | integrated LUFS (K-weighted, gated, ITU-R BS.1770 style) | -14 ± 1.5 LUFS |
| true peak | 4× oversampled peak | ≤ -0.9 dBTP |
| clipping | share of samples at full scale | < 0.001 % |
| opening sound | silence before the first sound | ≤ 0.45 s |
| voice over music | voice RMS vs residual bed during speech | ≥ 9 dB |
| dc offset | mean of the mix | < 0.002 |

-14 LUFS is where the platforms normalise to, so mastering to it means nothing gets turned
down after upload.

## Picture

| gate | measures | passes when |
|---|---|---|
| frame luminance | mean luma over sampled frames | 6-42 % (dark but readable) |
| black frames | frames with mean luma < 4.5 % | ≤ 2 of 36 |
| highlight clipping | share of pixels above 98.5 % luma | < 2 % |
| motion | consecutive identical samples (64×64 luma delta) | ≤ 15 % of samples |

## Reading the report

```
✓ loudness                     -14.2 LUFS (target -14)
!  caption contrast             3.6:1 against the caption band (WCAG AA needs 4.5:1)
      fix: add a plate/scrim behind captions or lift the grade
✗  caption density              26.4 chars/s on screen (limit 17-19, hard 24)
      fix: cut words: the eye cannot read faster than ~17 chars/s
```

`!` caption contrast in that example is a warning you can accept *if* the words are short and
the shot is calm — but on a moving background it will lose the viewer. Raising `scrim` from
0.42 to 0.55 costs nothing and fixes it.
