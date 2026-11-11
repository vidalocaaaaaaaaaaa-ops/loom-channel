"""Project + timeline model. One JSON file is the single source of truth;
everything else (voice, words, shots, music, captions, QC) is derived from it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

ASPECTS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "3:4": (1080, 1440),
}


@dataclass
class Shot:
    name: str
    start: float
    end: float
    paint: Callable            # paint(canvas, t_local, ctx) -> None
    gfx: Callable | None = None  # post-grade graphics hook(gfx, t_local, ctx)
    rig: dict = field(default_factory=dict)
    transition: str = "dissolve"
    transition_dur: float = 0.35
    grade: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    @property
    def dur(self):
        return self.end - self.start


@dataclass
class Line:
    """One narration sentence = one shot by default."""
    id: str
    text: str
    start: float
    end: float
    words: list = field(default_factory=list)
    shot: str | None = None
    meta: dict = field(default_factory=dict)


class Project:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        with open(self.path) as fh:
            self.data = json.load(fh)
        self.name = self.data.get("name", os.path.basename(self.dir))
        self.style = self.data.get("style", "nightline")
        self.aspect = self.data.get("aspect", "9:16")
        self.W, self.H = ASPECTS.get(self.aspect, ASPECTS["9:16"])
        self.fps = int(self.data.get("fps", 30))
        self.seed = int(self.data.get("seed", 7))
        self.platform = self.data.get("platform", "tiktok")
        self.script = self.data.get("script", [])
        self.words = []
        self.lines: list[Line] = []
        self.shots: list[Shot] = []
        self.audio_cache = self.data.get("audio", {})

    # ---------------------------------------------------------------- paths
    def p(self, *parts):
        return os.path.join(self.dir, *parts)

    def ensure(self, *parts):
        d = self.p(*parts)
        os.makedirs(d, exist_ok=True)
        return d

    # ---------------------------------------------------------------- words
    def load_words(self):
        wp = self.p("data", "words.json")
        if os.path.exists(wp):
            with open(wp) as fh:
                d = json.load(fh)
            self.words = d["words"]
            self.lines = []
            by_id = {}
            for w in self.words:
                by_id.setdefault(w["line"], []).append(w)
            order = [s.get("id") for s in self.script] or sorted(by_id)
            for sid in order:
                ws = by_id.get(sid, [])
                if not ws:
                    continue
                scr = next((s for s in self.script if s.get("id") == sid), {})
                self.lines.append(Line(
                    id=sid, text=scr.get("text", " ".join(w["word"] for w in ws)),
                    start=ws[0]["start"], end=ws[-1]["end"], words=ws,
                    shot=scr.get("shot"), meta={k: v for k, v in scr.items()
                                                if k not in ("id", "text", "shot")}))
            return self
        return self

    @property
    def narration_duration(self):
        return self.lines[-1].end if self.lines else 0.0

    def full_text(self):
        return " ".join(s.get("text", "") for s in self.script)

    # ---------------------------------------------------------------- build
    def build(self, module):
        """Ask a style module to turn lines into shots, then stitch the timeline."""
        ctx = dict(project=self, W=self.W, H=self.H, seed=self.seed,
                   style=self.style, data=self.data, lines=self.lines,
                   words=self.words, meta=self.data.get("scenes", {}))
        self.shots = module.build(ctx)
        return self

    @property
    def duration(self):
        return self.shots[-1].end if self.shots else 0.0

    def shot_at(self, t):
        for i, s in enumerate(self.shots):
            if s.start <= t < s.end:
                return i, s
        return len(self.shots) - 1, self.shots[-1]

    def caption_words(self):
        return [w for w in self.words if not w.get("silent")]

    def save_meta(self, extra: dict):
        self.data.setdefault("_meta", {}).update(extra)
        with open(self.path, "w") as fh:
            json.dump(self.data, fh, indent=2)
