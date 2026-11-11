# ROOM 402 — Part Three: "THE GUEST"

Series part 3 of 4. 47.6 s · 1080×1920 · 30 fps · 9 narration lines · 11 shots · −14.2 LUFS / −1.0 dBTP.

## Story

Part 2 ended with tonight's page carrying two names: his, and the one already inside
room 402. Part 3 is him going in. The guest has been waiting since the night of the fire,
knows his name without turning around, and does not need the pen — the second name is
already on the page, in his own handwriting, from an angle he could never have written
from. He signs anyway. Somebody in the corridor says *see you at checkout*.

Original fiction. Presented as a story, not as testimony.

## Shot table

| # | id | time | set | on screen |
|---|----|------|-----|-----------|
| — | open | 0.00–2.20 | card | PART THREE / THE GUEST |
| 1 | l1 | 2.83–7.14 | corridor | `2:41 A.M.` chip, one dead lamp |
| 2 | l2 | 7.14–11.58 | door wide | THE FOURTH FLOOR, 402, no keyhole |
| 3 | l3 | 11.58–16.35 | card | TONIGHT'S PAGE / THE GUEST / "no arrival time written" |
| 4 | l4 | 16.35–20.71 | room | man at the window, back to the door, cold rim |
| 5 | l5 | 20.71–25.21 | door tight | `2:41 A.M.`, slow push, hand-held drift |
| 6 | l6 | 25.21–30.29 | room + rain | he turns, one hand up, nightstand in frame |
| 7 | l7 | 30.29–35.35 | corridor_far | figure at z=12, warm rim, cold end |
| 8 | l8 | 35.35–39.53 | corridor | lamps die in sequence, guest rim-lit, one lamp left |
| 9 | l9 | 39.53–45.02 | card | CHECK-IN / 2:41 A.M. / "the fourth floor light came on" |
| — | end | 44.47–47.62 | card | ROOM 402 — Part Four: Checkout |

## Continuity with Parts 1 & 2

- Voice: `am_onyx`, speed 0.92, gap 0.62 — identical to Parts 1 and 2.
- Grade, caption style, caption band (`anchor_y` 0.755), transitions: unchanged.
- Timestamp chips continue the same clock: Part 1 3:05 → Part 2 2:14 → Part 3 2:41
  (the register keeps its own time; the chips are the room's clock, not the narrator's).
- The register, room 402, the fourth floor and the sealed door are all reused props.

## Re-shoot notes (what I changed and why)

1. **l4 was written as "a man sat on the bed".** The room set has a bed but
   `figures.person()` only speaks standing poses, so a first pass put a standing figure
   at x=0.95/z=3.35 — it filled the right third and clipped out of frame. Fixed by moving
   him to the proved composition (x=0.62, z=3.9) and rewriting the line to
   "stood with his back to the door". Visual and narration now agree. Shot still reads by
   the window with a hard cold rim.
2. **l8 used to go fully black.** All six lamps died by t=1.9 s, leaving ~2 s of
   near-black. Now only lamps 0–4 die (0.5–1.7 s), the far lamp stays, and the guest is
   placed at z=9 with a warm rim — so the beat ends on a lit silhouette instead of a
   black screen. Near-black frames went from a wall of them to the intended dip.
3. **Card layout** uses the block-stack from Part 2 (`_draw_card`): kicker → title lines →
   red rule → subtitle, block-centred at H·0.47. No collisions at 2-line numerals.

## QC

17 pass / 3 warn / 0 fail.

- warn: 4 caption groups under 0.55 s
- warn: 11/36 sampled frames near black (the lamps-out shot and two dips — intentional)
- warn: 7/35 identical motion samples (held wide in l7)

No gate failed, so the render is deliverable.

## Deliverables

```
renders/master.mp4     1080x1920, crf 22 single pass, tune film
deliver/preview.mp4    720-wide, crf 26
deliver/share.mp4      crf 25 (~16 MB)
deliver/cover.jpg      auto-picked from a clean, caption-free frame
deliver/caption.txt    hook + hashtags
```
