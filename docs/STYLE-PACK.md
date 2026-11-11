# Writing a new style pack

A style is a Python module in `loom/scenes/` that turns a project's lines into shots. The
engine gives you the camera, the canvas, the light buffer, the type, the score and the QC —
you only describe the look. Expect 150-400 lines for a convincing style.

## The contract

A module must define:

```python
CANVAS_BG = (0, 0, 0)            # what the frame starts as
DEFAULTS  = dict(voice="am_onyx", speed=0.95, gap=0.55, lead_in=0.6, tail=1.2,
                 music="nightline", platform="tiktok")
GRADE     = dict(exposure=0.95, contrast=1.2, bloom=0.3, grain=0.03, vignette=0.55,
                 scrim=0.4, split=("#2b4a6b", "#ffd9a8", 0.3))
CAPTIONS  = dict(family="barlow", size_h=0.043, anchor_y=0.755, highlight="#ffcc33")

def camera_for(shot, ctx, tl):  ...   # -> Camera (3-D) or FlatRig (2-D)
def paint(shot, canvas, cam, tl, ctx): ...   # draw the world, pre-grade
def gfx(shot, G, tl, ctx):     ...           # optional: post-grade type/cards
def build(ctx):                ...           # -> list[Shot]
def sfx_events(project):       ...           # optional: list[{name, t, amp}]
```

`ctx` carries `project, W, H, scale, seed, shot, style, draft, t_abs, module`.

## Two ways to paint

**World space (3-D).** Say where things are in metres, and let the projection do perspective,
parallax and fog. Use it for interiors, streets, machines, anything with depth.

```python
from loom.draw import geo, figures
rig = geo.Rig3(ambient="#121826", ambient_level=0.15, fog_color="#0a0f18", fog=(3, 24))
rig.add((0, 2.45, 6.0), "#ffb066", power=1.1, radius=2.2)        # a point light

zs = [0, .3, .6, 1.0, 1.4, 2.0, 2.8, 4.0, 6.0, 9.0, 13.0, 18.0]  # dense near the lens
geo.surf(canvas, cam, rig, lambda u, v: (1.2, v * 2.6, u), zs,
         [i / 20 for i in range(21)], "#5b5852", (1, 0, 0), texture=0.06)
figures.person(canvas, cam, (0.0, 0, 7.0), 1.8, fill="#04060b",
               rim="#ff5b28", rim_intensity=0.9, rim_from=(0, 2.45, 6.0))
```

**Flat space (2-D).** Draw in pixels, animate with springs, and use `FlatRig` for a slow
zoom/pan. Use it for typography, charts, cards, infographics — see `blueprint.py`.

```python
from loom.ease import spring
k = spring(clamp(tl / 0.8), freq=1.6, damp=6.5)
G.rect((x, y, x + w * k, y + h), fill="#ffc247")
```

## Rules that keep a style from looking cheap

1. **Albedo is mid-tone, light does the work.** Never pre-darken a surface to fake shadow;
   give it a real albedo and put a light near it. `shade()` saturates at 255 by design, so a
   base colour is "fully lit", and everything else falls off from there.
2. **Subdivide finely where the gradient is steep.** Panel shading is flat per panel; a 1 m
   panel next to a lamp will band. Use a non-uniform parameter list that is dense near the
   camera and near lights.
3. **One dominant light per shot.** Two equal lights read as flat. Warm key + cold fill is
   the whole trick in NIGHTLINE.
4. **Never let type sit on a busy background without help.** Use `scrim` in the grade or a
   `plate` in the caption style; QC measures the real contrast and will tell you.
5. **Move something in every shot.** Slow push, drift, flicker, dust, rain, a growing bar.
   QC counts frozen stretches.
6. **Sound design is part of the look.** `sfx_events()` puts a whoosh on the cut, a thud on
   the reveal, a phone where the phone is. Keep everything below ~9 kHz and off the harsh
   transients: these videos are watched on phone speakers.
7. **Register the style** in `loom/audio/music.py` (`COMPOSERS`) with a score that matches
   the palette, then set `DEFAULTS["music"]`.

## Test loop

```bash
python -m loom.cli still <project> --t 1,4,9 --scale 0.6 --ss 1   # 1 s per frame
python -m loom.cli qc    <project>                                # gates + contact sheet
python -m loom.cli render <project> --draft                       # half size, quick
```

Look at every frame of the contact sheet. If a frame is flat, add a light; if it is noisy,
take one away.
