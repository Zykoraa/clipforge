"""Data models, sanitization helpers, and timeline coordinate solver for ClipForge."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def sanitize_hex_color(value: str, fallback: str = "#000000") -> str:
    v = (value or "").strip()
    if len(v) in (3, 4) and v.lstrip("#") and all(c in "0123456789abcdefABCDEF" for c in v.lstrip("#")):
        raw = v.lstrip("#")
        if len(raw) == 3:
            return "#" + "".join(c * 2 for c in raw).upper()
    if _HEX_COLOR_RE.match(v):
        return "#" + v.lstrip("#").upper()
    return fallback


def sanitize_font_name(name: str, fallback: str = "Arial Black") -> str:
    # Strip ASS CSV delimiters, control chars, and CSS/quote breakers
    cleaned = re.sub(r"[\r\n,;\"'\\{}<>]", "", (name or "").strip())
    return cleaned[:64] if cleaned else fallback


def sanitize_single_line(text: str, fallback: str = "Untitled Project") -> str:
    cleaned = re.sub(r"[\r\n]+", " ", (text or "")).strip()
    return cleaned[:160] if cleaned else fallback


def ensure_even_dimension(value: int, minimum: int = 128, maximum: int = 7680) -> int:
    clamped = max(minimum, min(maximum, int(value)))
    return clamped & ~1


TransitionType = Literal[
    "cut",
    "crossfade",
    "fade",
    "fadeblack",
    "fadewhite",
    "wipeleft",
    "wiperight",
    "slideup",
    "slidedown",
    "circleopen",
    "circleclose",
    "dissolve",
    "pixelize",
]

XFADE_MAP: dict[str, str | None] = {
    "cut": None,
    "crossfade": "fade",
    "fade": "fade",
    "fadeblack": "fadeblack",
    "fadewhite": "fadewhite",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "circleopen": "circleopen",
    "circleclose": "circleclose",
    "dissolve": "dissolve",
    "pixelize": "pixelize",
}


class WordToken(BaseModel):
    word: str
    start_sec: float
    end_sec: float
    probability: float = 1.0


class TranscriptSegment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("seg"))
    start_sec: float
    end_sec: float
    text: str
    words: list[WordToken] = Field(default_factory=list)


class TimeInterval(BaseModel):
    start_sec: float
    end_sec: float
    duration_sec: float
    label: str = ""


class MediaItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("media"))
    path: str
    filename: str
    duration_sec: float
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    video_codec: str = "h264"
    audio_codec: str | None = "aac"
    has_video: bool = True
    has_audio: bool = True
    is_image: bool = False
    file_size_bytes: int = 0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    thumbnail_path: str | None = None
    waveform_peaks: list[float] = Field(default_factory=list)
    silent_segments: list[TimeInterval] = Field(default_factory=list)
    active_segments: list[TimeInterval] = Field(default_factory=list)
    scene_cuts: list[float] = Field(default_factory=list)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    analyzed: bool = False
    transcribed: bool = False

    @property
    def full_transcript_text(self) -> str:
        return " ".join(s.text.strip() for s in self.transcript if s.text.strip())


class TimelineClip(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clip"))
    media_id: str
    label: str = ""
    in_sec: float = 0.0
    out_sec: float = 0.0
    speed: float = 1.0
    volume: float = 1.0
    muted: bool = False
    transition: TransitionType = "cut"
    transition_duration: float = 0.4

    @property
    def source_duration_sec(self) -> float:
        return max(0.04, self.out_sec - self.in_sec)

    @property
    def effective_duration_sec(self) -> float:
        spd = max(0.1, min(16.0, self.speed))
        return max(0.04, self.source_duration_sec / spd)


class ScheduledClip(BaseModel):
    clip: TimelineClip
    index: int
    effective_duration_sec: float
    applied_transition: str | None
    applied_transition_duration: float
    timeline_start_sec: float
    timeline_end_sec: float
    xfade_offset_sec: float


class SubtitleEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sub"))
    start_sec: float
    end_sec: float
    text: str
    words: list[WordToken] = Field(default_factory=list)
    clip_id: str | None = None
    speaker: str | None = None


class AudioOverlay(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sfx"))
    path: str
    label: str = "SFX"
    sfx_id: str | None = None
    start_sec: float = 0.0
    duration_sec: float = 1.5
    volume: float = 1.0
    duck_main_audio: bool = False


MemeTemplateType = Literal[
    "none",
    "pov_top_bar",
    "pov_dark_bar",
    "impact_top_bottom",
    "breaking_news",
    "demotivational",
    "bodycam_hud",
]


class MemeLayoutConfig(BaseModel):
    template: MemeTemplateType = "none"
    top_text: str = ""
    bottom_text: str = ""
    banner_label: str = "BREAKING NEWS"

    @field_validator("top_text", "bottom_text")
    @classmethod
    def _v_meme_text(cls, v: str) -> str:
        return re.sub(r"[\r\n]+", " ", (v or "")).strip()[:220]

    @field_validator("banner_label")
    @classmethod
    def _v_banner(cls, v: str) -> str:
        cleaned = re.sub(r"[\r\n]+", " ", (v or "")).strip()[:48]
        return cleaned or "BREAKING NEWS"


class SubtitleStyle(BaseModel):
    preset: Literal[
        "hormozi",
        "mrbeast",
        "tiktok_clean",
        "meme_impact",
        "gaming_rgb",
        "news_ticker",
        "whisper_red",
        "cinema",
        "minimal",
        "neon_box",
        "custom",
    ] = "hormozi"
    font_name: str = "Arial Black"
    font_size: int = 62
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#00FF66"
    outline_color: str = "#000000"
    back_color: str = "#000000"
    back_opacity: float = 0.0
    bold: bool = True
    italic: bool = False
    uppercase: bool = True
    word_highlight: bool = True
    outline_width: float = 4.5
    shadow_depth: float = 2.0
    alignment: int = 2  # ASS numpad alignment: 1..9 (2=bottom-center, 5=center, 8=top-center)
    margin_v: int = 110
    max_words_per_caption: int = 5

    @field_validator("font_name")
    @classmethod
    def _v_font(cls, v: str) -> str:
        return sanitize_font_name(v)

    @field_validator("primary_color")
    @classmethod
    def _v_pri(cls, v: str) -> str:
        return sanitize_hex_color(v, "#FFFFFF")

    @field_validator("highlight_color")
    @classmethod
    def _v_hi(cls, v: str) -> str:
        return sanitize_hex_color(v, "#00FF66")

    @field_validator("outline_color", "back_color")
    @classmethod
    def _v_dark(cls, v: str) -> str:
        return sanitize_hex_color(v, "#000000")

    @field_validator("alignment")
    @classmethod
    def _v_align(cls, v: int) -> int:
        iv = int(v)
        return iv if 1 <= iv <= 9 else 2

    @field_validator("font_size")
    @classmethod
    def _v_fsize(cls, v: int) -> int:
        return max(12, min(200, int(v)))

    @field_validator("back_opacity")
    @classmethod
    def _v_op(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("outline_width", "shadow_depth")
    @classmethod
    def _v_nonneg(cls, v: float) -> float:
        return max(0.0, min(30.0, float(v)))

    @field_validator("margin_v")
    @classmethod
    def _v_margin(cls, v: int) -> int:
        return max(0, min(800, int(v)))

    @field_validator("max_words_per_caption")
    @classmethod
    def _v_maxw(cls, v: int) -> int:
        return max(1, min(20, int(v)))


STYLE_PRESETS: dict[str, dict] = {
    "hormozi": {
        "preset": "hormozi",
        "font_name": "Arial Black",
        "font_size": 64,
        "primary_color": "#FFFFFF",
        "highlight_color": "#00FF66",
        "outline_color": "#000000",
        "back_color": "#000000",
        "back_opacity": 0.0,
        "bold": True,
        "italic": False,
        "uppercase": True,
        "word_highlight": True,
        "outline_width": 5.0,
        "shadow_depth": 2.5,
        "alignment": 2,
        "margin_v": 130,
        "max_words_per_caption": 4,
    },
    "cinema": {
        "preset": "cinema",
        "font_name": "Segoe UI",
        "font_size": 46,
        "primary_color": "#FFF8E7",
        "highlight_color": "#FFD700",
        "outline_color": "#000000",
        "back_color": "#000000",
        "back_opacity": 0.0,
        "bold": False,
        "italic": False,
        "uppercase": False,
        "word_highlight": False,
        "outline_width": 2.5,
        "shadow_depth": 1.5,
        "alignment": 2,
        "margin_v": 75,
        "max_words_per_caption": 9,
    },
    "minimal": {
        "preset": "minimal",
        "font_name": "Segoe UI Semibold",
        "font_size": 48,
        "primary_color": "#FFFFFF",
        "highlight_color": "#38BDF8",
        "outline_color": "#111111",
        "back_color": "#000000",
        "back_opacity": 0.0,
        "bold": True,
        "italic": False,
        "uppercase": False,
        "word_highlight": True,
        "outline_width": 3.0,
        "shadow_depth": 0.0,
        "alignment": 2,
        "margin_v": 90,
        "max_words_per_caption": 6,
    },
    "neon_box": {
        "preset": "neon_box",
        "font_name": "Impact",
        "font_size": 60,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FF2E93",
        "outline_color": "#09090B",
        "back_color": "#09090B",
        "back_opacity": 0.65,
        "bold": False,
        "italic": False,
        "uppercase": True,
        "word_highlight": True,
        "outline_width": 4.0,
        "shadow_depth": 0.0,
        "alignment": 5,
        "margin_v": 0,
        "max_words_per_caption": 4,
    },
    "mrbeast": {
        "preset": "mrbeast",
        "font_name": "Impact",
        "font_size": 74,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFE600",
        "outline_color": "#000000",
        "back_color": "#000000",
        "back_opacity": 0.0,
        "bold": True,
        "italic": False,
        "uppercase": True,
        "word_highlight": True,
        "outline_width": 6.5,
        "shadow_depth": 3.5,
        "alignment": 2,
        "margin_v": 150,
        "max_words_per_caption": 3,
    },
    "tiktok_clean": {
        "preset": "tiktok_clean",
        "font_name": "Segoe UI Bold",
        "font_size": 52,
        "primary_color": "#FFFFFF",
        "highlight_color": "#22D3EE",
        "outline_color": "#000000",
        "back_color": "#09090B",
        "back_opacity": 0.72,
        "bold": True,
        "italic": False,
        "uppercase": False,
        "word_highlight": True,
        "outline_width": 2.0,
        "shadow_depth": 0.0,
        "alignment": 5,
        "margin_v": 60,
        "max_words_per_caption": 5,
    },
    "meme_impact": {
        "preset": "meme_impact",
        "font_name": "Impact",
        "font_size": 72,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFFFFF",
        "outline_color": "#000000",
        "back_color": "#000000",
        "back_opacity": 0.0,
        "bold": False,
        "italic": False,
        "uppercase": True,
        "word_highlight": False,
        "outline_width": 5.5,
        "shadow_depth": 2.0,
        "alignment": 2,
        "margin_v": 70,
        "max_words_per_caption": 6,
    },
    "gaming_rgb": {
        "preset": "gaming_rgb",
        "font_name": "Arial Black",
        "font_size": 66,
        "primary_color": "#E0F2FE",
        "highlight_color": "#38BDF8",
        "outline_color": "#3B0764",
        "back_color": "#09090B",
        "back_opacity": 0.0,
        "bold": True,
        "italic": True,
        "uppercase": True,
        "word_highlight": True,
        "outline_width": 5.5,
        "shadow_depth": 3.0,
        "alignment": 2,
        "margin_v": 135,
        "max_words_per_caption": 3,
    },
    "news_ticker": {
        "preset": "news_ticker",
        "font_name": "Arial",
        "font_size": 46,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FACC15",
        "outline_color": "#000000",
        "back_color": "#B91C1C",
        "back_opacity": 0.88,
        "bold": True,
        "italic": False,
        "uppercase": True,
        "word_highlight": False,
        "outline_width": 1.5,
        "shadow_depth": 0.0,
        "alignment": 2,
        "margin_v": 55,
        "max_words_per_caption": 8,
    },
    "whisper_red": {
        "preset": "whisper_red",
        "font_name": "Arial Black",
        "font_size": 60,
        "primary_color": "#E5E7EB",
        "highlight_color": "#EF4444",
        "outline_color": "#000000",
        "back_color": "#000000",
        "back_opacity": 0.0,
        "bold": True,
        "italic": False,
        "uppercase": True,
        "word_highlight": True,
        "outline_width": 5.0,
        "shadow_depth": 4.0,
        "alignment": 5,
        "margin_v": 0,
        "max_words_per_caption": 3,
    },
}


class ProjectState(BaseModel):
    id: str = Field(default_factory=lambda: new_id("proj"))
    name: str = "Untitled Project"
    project_path: str = ""
    output_dir: str = ""
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    bg_color: str = "#000000"
    media_bin: list[MediaItem] = Field(default_factory=list)
    timeline: list[TimelineClip] = Field(default_factory=list)
    audio_overlays: list[AudioOverlay] = Field(default_factory=list)
    subtitles: list[SubtitleEntry] = Field(default_factory=list)
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    meme_layout: MemeLayoutConfig = Field(default_factory=MemeLayoutConfig)
    last_render_path: str | None = None
    version: int = 1
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return sanitize_single_line(v)

    @field_validator("width", "height")
    @classmethod
    def _v_dim(cls, v: int) -> int:
        return ensure_even_dimension(v)

    @field_validator("bg_color")
    @classmethod
    def _v_bg(cls, v: str) -> str:
        return sanitize_hex_color(v, "#000000")

    def get_media(self, media_id: str) -> MediaItem | None:
        for m in self.media_bin:
            if m.id == media_id:
                return m
        return None

    def get_clip(self, clip_id: str) -> TimelineClip | None:
        for c in self.timeline:
            if c.id == clip_id:
                return c
        return None

    def compute_timeline_schedule(self) -> list[ScheduledClip]:
        """Compute exact timeline start/end and xfade offsets for every clip."""
        schedule: list[ScheduledClip] = []
        acc_duration = 0.0

        for idx, clip in enumerate(self.timeline):
            eff_dur = round(clip.effective_duration_sec, 4)
            xfade_name = XFADE_MAP.get(clip.transition)

            if idx == 0 or xfade_name is None or clip.transition_duration <= 0.0:
                applied_trans = None
                applied_trans_dur = 0.0
                start_sec = acc_duration
                end_sec = round(start_sec + eff_dur, 4)
                xfade_offset = acc_duration
                acc_duration = end_sec
            else:
                prev_eff = schedule[-1].effective_duration_sec
                max_safe_trans = min(0.45 * acc_duration, 0.45 * prev_eff, 0.45 * eff_dur)
                applied_trans_dur = round(min(clip.transition_duration, max_safe_trans), 4)
                if applied_trans_dur < 0.04:
                    applied_trans = None
                    applied_trans_dur = 0.0
                    start_sec = acc_duration
                    end_sec = round(start_sec + eff_dur, 4)
                    xfade_offset = acc_duration
                    acc_duration = end_sec
                else:
                    applied_trans = xfade_name
                    xfade_offset = round(acc_duration - applied_trans_dur, 4)
                    start_sec = xfade_offset
                    end_sec = round(start_sec + eff_dur, 4)
                    acc_duration = end_sec

            schedule.append(
                ScheduledClip(
                    clip=clip,
                    index=idx,
                    effective_duration_sec=eff_dur,
                    applied_transition=applied_trans,
                    applied_transition_duration=applied_trans_dur,
                    timeline_start_sec=round(start_sec, 4),
                    timeline_end_sec=round(end_sec, 4),
                    xfade_offset_sec=round(xfade_offset, 4),
                )
            )
        return schedule

    @property
    def total_duration_sec(self) -> float:
        sched = self.compute_timeline_schedule()
        return sched[-1].timeline_end_sec if sched else 0.0
