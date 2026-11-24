"""Shared ProjectEngine for atomic disk persistence, cross-process undo/redo, AI smart stitching, and subtitling."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from .media import (
    MEDIA_EXTENSIONS,
    detect_scene_changes,
    detect_silence_and_active_segments,
    extract_frame,
    probe_media_file,
    transcribe_media_file,
)
from .models import (
    STYLE_PRESETS,
    XFADE_MAP,
    AudioOverlay,
    MediaItem,
    MemeLayoutConfig,
    MemeTemplateType,
    ProjectState,
    SubtitleEntry,
    SubtitleStyle,
    TimelineClip,
    TransitionType,
    WordToken,
    ensure_even_dimension,
    new_id,
)
from .renderer import render_project_to_mp4
from .sfx import ensure_builtin_sfx_file
from .subtitles import project_timeline_subtitles, write_subtitle_file


def _resolve_default_workspace() -> Path:
    env_ws = os.environ.get("CLIPFORGE_WORKSPACE", "").strip()
    if env_ws:
        return Path(env_ws).expanduser()
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # When launched from <repo>/dist/ClipForge/ClipForge(.exe), share <repo>/workspace with MCP
        repo_root = exe_dir.parent.parent
        if (repo_root / "pyproject.toml").exists():
            return repo_root / "workspace"
        if os.access(exe_dir, os.W_OK):
            return exe_dir / "workspace"
        # System-wide read-only installs (e.g. /opt/clipforge) fall back to user data dir
        if sys.platform == "win32":
            local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            return Path(local_app) / "ClipForge" / "workspace"
        xdg_data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(xdg_data) / "clipforge" / "workspace"
    return Path(__file__).resolve().parent.parent / "workspace"


DEFAULT_WORKSPACE = _resolve_default_workspace()
MAX_HISTORY_DEPTH = 40


class ProjectEngine:
    """Thread-safe and process-safe video editing engine shared by MCP and Web UI."""

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self.workspace_dir = Path(workspace_dir or DEFAULT_WORKSPACE).resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir = self.workspace_dir / "assets"
        self.renders_dir = self.workspace_dir / "renders"
        self.sfx_dir = self.workspace_dir / "sfx"
        self.history_dir = self.workspace_dir / ".history"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

        self.project_file = self.workspace_dir / "project.json"
        self.history_file = self.history_dir / "history.json"
        self.lock_file = self.workspace_dir / "project.json.lock"
        self._lock = FileLock(str(self.lock_file), timeout=30)

        with self._lock:
            if not self.project_file.exists():
                initial = ProjectState(
                    name="ClipForge Project",
                    project_path=str(self.project_file),
                    output_dir=str(self.renders_dir),
                )
                self._write_unlocked(initial, record_undo=False)

    def _atomic_write_text(self, target: Path, content: str) -> None:
        tmp = target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)

    def _read_history_unlocked(self) -> tuple[list[str], list[str]]:
        if not self.history_file.exists():
            return [], []
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
            undo_list = data.get("undo", [])
            redo_list = data.get("redo", [])
            if isinstance(undo_list, list) and isinstance(redo_list, list):
                return undo_list, redo_list
        except Exception:
            pass
        return [], []

    def _write_history_unlocked(self, undo_stack: list[str], redo_stack: list[str]) -> None:
        payload = json.dumps(
            {
                "undo": undo_stack[-MAX_HISTORY_DEPTH:],
                "redo": redo_stack[-MAX_HISTORY_DEPTH:],
            }
        )
        self._atomic_write_text(self.history_file, payload)

    def _read_unlocked(self) -> ProjectState:
        if not self.project_file.exists():
            return ProjectState(
                name="ClipForge Project",
                project_path=str(self.project_file),
                output_dir=str(self.renders_dir),
            )
        raw = self.project_file.read_text(encoding="utf-8")
        return ProjectState.model_validate_json(raw)

    def _write_unlocked(self, state: ProjectState, record_undo: bool = True) -> ProjectState:
        disk_version = 0
        if self.project_file.exists():
            try:
                prev_raw = self.project_file.read_text(encoding="utf-8")
                prev_obj = json.loads(prev_raw)
                disk_version = int(prev_obj.get("version", 0))
                if record_undo:
                    undo_stack, redo_stack = self._read_history_unlocked()
                    if not undo_stack or undo_stack[-1] != prev_raw:
                        undo_stack.append(prev_raw)
                    redo_stack = []
                    self._write_history_unlocked(undo_stack, redo_stack)
            except Exception:
                pass

        # Strictly monotonic version across all writes, including undo/redo, so WS sync never drops updates
        state.version = max(disk_version, state.version) + 1
        state.updated_at = datetime.now(timezone.utc).isoformat()
        state.project_path = str(self.project_file)
        if not state.output_dir:
            state.output_dir = str(self.renders_dir)

        self._atomic_write_text(self.project_file, state.model_dump_json(indent=2))
        return state

    def get_state(self) -> ProjectState:
        with self._lock:
            return self._read_unlocked()

    def save_state(self, state: ProjectState, record_undo: bool = True) -> ProjectState:
        with self._lock:
            return self._write_unlocked(state, record_undo=record_undo)

    def undo(self) -> ProjectState:
        with self._lock:
            undo_stack, redo_stack = self._read_history_unlocked()
            if not undo_stack:
                return self._read_unlocked()
            if self.project_file.exists():
                redo_stack.append(self.project_file.read_text(encoding="utf-8"))
            prev_raw = undo_stack.pop()
            self._write_history_unlocked(undo_stack, redo_stack)
            restored = ProjectState.model_validate_json(prev_raw)
            return self._write_unlocked(restored, record_undo=False)

    def redo(self) -> ProjectState:
        with self._lock:
            undo_stack, redo_stack = self._read_history_unlocked()
            if not redo_stack:
                return self._read_unlocked()
            if self.project_file.exists():
                undo_stack.append(self.project_file.read_text(encoding="utf-8"))
            next_raw = redo_stack.pop()
            self._write_history_unlocked(undo_stack, redo_stack)
            restored = ProjectState.model_validate_json(next_raw)
            return self._write_unlocked(restored, record_undo=False)

    def get_summary_dict(self) -> dict[str, Any]:
        with self._lock:
            state = self._read_unlocked()
            undo_stack, redo_stack = self._read_history_unlocked()
        schedule = state.compute_timeline_schedule()
        return {
            "project": state.model_dump(),
            "schedule": [
                {
                    "clip_id": s.clip.id,
                    "media_id": s.clip.media_id,
                    "label": s.clip.label,
                    "index": s.index,
                    "in_sec": s.clip.in_sec,
                    "out_sec": s.clip.out_sec,
                    "speed": s.clip.speed,
                    "volume": s.clip.volume,
                    "muted": s.clip.muted,
                    "transition": s.clip.transition,
                    "transition_duration": s.clip.transition_duration,
                    "effective_duration_sec": s.effective_duration_sec,
                    "applied_transition": s.applied_transition,
                    "applied_transition_duration": s.applied_transition_duration,
                    "timeline_start_sec": s.timeline_start_sec,
                    "timeline_end_sec": s.timeline_end_sec,
                    "xfade_offset_sec": s.xfade_offset_sec,
                }
                for s in schedule
            ],
            "total_duration_sec": state.total_duration_sec,
            "can_undo": len(undo_stack) > 0,
            "can_redo": len(redo_stack) > 0,
        }

    # -------------------------------------------------------------------------
    # Project Configuration
    # -------------------------------------------------------------------------
    def configure_project(
        self,
        name: str | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        bg_color: str | None = None,
        reset: bool = False,
    ) -> ProjectState:
        with self._lock:
            state = (
                ProjectState(
                    project_path=str(self.project_file),
                    output_dir=str(self.renders_dir),
                )
                if reset
                else self._read_unlocked()
            )
            if name is not None:
                state.name = name
            if width is not None:
                state.width = ensure_even_dimension(width)
            if height is not None:
                state.height = ensure_even_dimension(height)
            if fps is not None:
                state.fps = max(1.0, min(120.0, float(fps)))
            if bg_color is not None:
                state.bg_color = bg_color
            # Re-validate field validators cleanly
            state = ProjectState.model_validate(state.model_dump())
            return self._write_unlocked(state)

    # -------------------------------------------------------------------------
    # Media Bin Operations & Deep Analysis
    # -------------------------------------------------------------------------
    def import_media(self, paths: list[str]) -> list[MediaItem]:
        resolved_files: list[Path] = []
        for raw in paths:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                for child in sorted(p.iterdir()):
                    if child.is_file() and child.suffix.lower() in MEDIA_EXTENSIONS:
                        resolved_files.append(child)
            elif p.is_file():
                resolved_files.append(p)
            else:
                raise FileNotFoundError(f"Path not found: {raw}")

        if not resolved_files:
            raise ValueError("No supported video or audio files found at the provided path(s).")

        # Snapshot already-imported paths briefly under lock
        with self._lock:
            snapshot = self._read_unlocked()
            existing_paths = {Path(m.path).resolve(): m for m in snapshot.media_bin}

        # Run slow ffprobe / thumbnail / waveform extraction OUTSIDE FileLock
        probed_new: dict[Path, MediaItem] = {}
        for fpath in resolved_files:
            if fpath not in existing_paths and fpath not in probed_new:
                probed_new[fpath] = probe_media_file(fpath, assets_dir=self.assets_dir)

        # Acquire lock briefly to merge & commit atomically
        imported: list[MediaItem] = []
        with self._lock:
            state = self._read_unlocked()
            current_by_path = {Path(m.path).resolve(): m for m in state.media_bin}
            changed = False
            for fpath in resolved_files:
                if fpath in current_by_path:
                    imported.append(current_by_path[fpath])
                else:
                    item = probed_new[fpath]
                    state.media_bin.append(item)
                    current_by_path[fpath] = item
                    imported.append(item)
                    changed = True
            if changed:
                self._write_unlocked(state)
        return imported

    def remove_media(self, media_id: str) -> ProjectState:
        with self._lock:
            state = self._read_unlocked()
            state.media_bin = [m for m in state.media_bin if m.id != media_id]
            state.timeline = [c for c in state.timeline if c.media_id != media_id]
            return self._write_unlocked(state)

    def analyze_clip(
        self,
        media_id: str,
        detect_silence: bool = True,
        detect_scenes: bool = True,
        transcribe: bool = True,
        model_size: str = "base",
        language: str | None = None,
        noise_db: float = -35.0,
        min_silence_sec: float = 0.4,
    ) -> MediaItem:
        state = self.get_state()
        media = state.get_media(media_id)
        if not media:
            raise ValueError(f"Media '{media_id}' not found in Media Bin.")

        silent_segs = media.silent_segments
        active_segs = media.active_segments
        scenes = media.scene_cuts
        transcript = media.transcript
        transcribed = media.transcribed

        if detect_silence and media.has_audio:
            silent_segs, active_segs = detect_silence_and_active_segments(
                media.path,
                media.duration_sec,
                noise_db=noise_db,
                min_silence_sec=min_silence_sec,
            )
        if detect_scenes and media.has_video:
            scenes = detect_scene_changes(media.path)
        if transcribe and media.has_audio:
            transcript = transcribe_media_file(
                media.path,
                model_size=model_size,
                language=language,
            )
            transcribed = True

        with self._lock:
            state = self._read_unlocked()
            target = state.get_media(media_id)
            if not target:
                raise ValueError(f"Media '{media_id}' not found.")
            target.silent_segments = silent_segs
            target.active_segments = active_segs
            target.scene_cuts = scenes
            target.transcript = transcript
            target.analyzed = True
            target.transcribed = transcribed
            self._write_unlocked(state)
            return target

    def extract_clip_frames(
        self,
        media_id: str,
        timestamps_sec: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        state = self.get_state()
        media = state.get_media(media_id)
        if not media:
            raise ValueError(f"Media '{media_id}' not found.")
        if not media.has_video:
            raise ValueError(f"Media '{media.filename}' is audio-only and has no video frames.")

        dur = media.duration_sec
        if not timestamps_sec:
            timestamps_sec = [
                round(dur * 0.15, 2),
                round(dur * 0.50, 2),
                round(dur * 0.85, 2),
            ]

        outputs: list[dict[str, Any]] = []
        for ts in timestamps_sec:
            clamped = max(0.0, min(dur - 0.05, float(ts)))
            out_jpg = self.assets_dir / f"{media.id}_frame_{int(clamped * 1000)}ms.jpg"
            extract_frame(media.path, clamped, out_jpg, width=640)
            outputs.append(
                {
                    "media_id": media.id,
                    "timestamp_sec": round(clamped, 3),
                    "image_path": str(out_jpg),
                }
            )
        return outputs

    # -------------------------------------------------------------------------
    # Timeline Editing & Intelligent Stitching
    # -------------------------------------------------------------------------
    def add_timeline_clip(
        self,
        media_id: str,
        in_sec: float = 0.0,
        out_sec: float | None = None,
        position_index: int | None = None,
        transition: TransitionType = "cut",
        transition_duration: float = 0.4,
        speed: float = 1.0,
        volume: float = 1.0,
        label: str = "",
    ) -> TimelineClip:
        if transition not in XFADE_MAP:
            raise ValueError(f"Unsupported transition '{transition}'. Valid: {sorted(XFADE_MAP.keys())}")
        if speed <= 0:
            raise ValueError("Clip speed must be > 0.")
        if volume < 0:
            raise ValueError("Clip volume must be >= 0.")

        with self._lock:
            state = self._read_unlocked()
            media = state.get_media(media_id)
            if not media:
                raise ValueError(f"Media '{media_id}' not found.")

            in_s = round(max(0.0, min(media.duration_sec - 0.05, float(in_sec))), 3)
            out_s = (
                round(max(in_s + 0.05, min(media.duration_sec, float(out_sec))), 3)
                if out_sec is not None and out_sec > 0
                else media.duration_sec
            )
            clip = TimelineClip(
                id=new_id("clip"),
                media_id=media.id,
                label=label or media.filename,
                in_sec=in_s,
                out_sec=out_s,
                speed=max(0.1, min(16.0, float(speed))),
                volume=max(0.0, min(4.0, float(volume))),
                transition=transition,
                transition_duration=max(0.0, min(5.0, float(transition_duration))),
            )
            if position_index is None or position_index >= len(state.timeline):
                state.timeline.append(clip)
            else:
                state.timeline.insert(max(0, int(position_index)), clip)

            self._write_unlocked(state)
            return clip

    def update_timeline_clip(
        self,
        clip_id: str,
        in_sec: float | None = None,
        out_sec: float | None = None,
        transition: TransitionType | None = None,
        transition_duration: float | None = None,
        speed: float | None = None,
        volume: float | None = None,
        muted: bool | None = None,
        label: str | None = None,
    ) -> TimelineClip:
        if transition is not None and transition not in XFADE_MAP:
            raise ValueError(f"Unsupported transition '{transition}'.")
        if speed is not None and speed <= 0:
            raise ValueError("Clip speed must be > 0.")
        if volume is not None and volume < 0:
            raise ValueError("Clip volume must be >= 0.")

        with self._lock:
            state = self._read_unlocked()
            clip = state.get_clip(clip_id)
            if not clip:
                raise ValueError(f"Timeline clip '{clip_id}' not found.")
            media = state.get_media(clip.media_id)
            max_dur = media.duration_sec if media else 36000.0

            if in_sec is not None:
                clip.in_sec = round(max(0.0, min(max_dur - 0.05, float(in_sec))), 3)
            if out_sec is not None:
                clip.out_sec = round(max(clip.in_sec + 0.05, min(max_dur, float(out_sec))), 3)
            if clip.out_sec <= clip.in_sec:
                clip.out_sec = round(min(max_dur, clip.in_sec + 0.1), 3)
            if transition is not None:
                clip.transition = transition
            if transition_duration is not None:
                clip.transition_duration = round(max(0.0, min(5.0, float(transition_duration))), 3)
            if speed is not None:
                clip.speed = round(max(0.1, min(16.0, float(speed))), 3)
            if volume is not None:
                clip.volume = round(max(0.0, min(4.0, float(volume))), 3)
            if muted is not None:
                clip.muted = bool(muted)
            if label is not None:
                clip.label = label

            self._write_unlocked(state)
            return clip

    def split_timeline_clip(
        self,
        clip_id: str,
        split_at_source_sec: float | None = None,
        split_at_timeline_sec: float | None = None,
    ) -> tuple[TimelineClip, TimelineClip]:
        with self._lock:
            state = self._read_unlocked()
            schedule = state.compute_timeline_schedule()
            sched_item = next((s for s in schedule if s.clip.id == clip_id), None)
            if not sched_item:
                raise ValueError(f"Timeline clip '{clip_id}' not found.")

            clip = sched_item.clip
            if split_at_source_sec is not None:
                src_split = float(split_at_source_sec)
            elif split_at_timeline_sec is not None:
                rel_tl = float(split_at_timeline_sec) - sched_item.timeline_start_sec
                src_split = clip.in_sec + rel_tl * clip.speed
            else:
                src_split = (clip.in_sec + clip.out_sec) / 2.0

            src_split = round(src_split, 3)
            if src_split <= clip.in_sec + 0.08 or src_split >= clip.out_sec - 0.08:
                raise ValueError(
                    f"Split point {src_split}s must be strictly inside [{clip.in_sec}s, {clip.out_sec}s]."
                )

            orig_out = clip.out_sec
            clip.out_sec = src_split
            second_clip = TimelineClip(
                id=new_id("clip"),
                media_id=clip.media_id,
                label=f"{clip.label} (Part 2)",
                in_sec=src_split,
                out_sec=orig_out,
                speed=clip.speed,
                volume=clip.volume,
                muted=clip.muted,
                transition="cut",
                transition_duration=0.0,
            )
            state.timeline.insert(sched_item.index + 1, second_clip)
            self._write_unlocked(state)
            return clip, second_clip

    def remove_timeline_clip(self, clip_id: str) -> ProjectState:
        with self._lock:
            state = self._read_unlocked()
            state.timeline = [c for c in state.timeline if c.id != clip_id]
            return self._write_unlocked(state)

    def reorder_timeline_clips(self, clip_ids: list[str]) -> ProjectState:
        with self._lock:
            state = self._read_unlocked()
            by_id = {c.id: c for c in state.timeline}
            new_tl: list[TimelineClip] = []
            for cid in clip_ids:
                if cid in by_id:
                    new_tl.append(by_id.pop(cid))
            for c in state.timeline:
                if c.id in by_id:
                    new_tl.append(c)
            state.timeline = new_tl
            return self._write_unlocked(state)

    def clear_timeline(self, clear_subtitles: bool = True, clear_overlays: bool = True) -> ProjectState:
        with self._lock:
            state = self._read_unlocked()
            state.timeline = []
            if clear_subtitles:
                state.subtitles = []
            if clear_overlays:
                state.audio_overlays = []
            return self._write_unlocked(state)

    def extract_clip_end_frame(self, clip_id: str) -> dict[str, Any]:
        """Extract the final frame of a timeline clip into workspace/ref_images for seamless I2V shot chaining."""
        state = self.get_state()
        clip = state.get_clip(clip_id)
        if not clip:
            raise ValueError(f"Timeline clip '{clip_id}' not found.")
        media = state.get_media(clip.media_id)
        if not media or not media.has_video:
            raise ValueError("Selected clip does not have a video/image stream.")

        refs_dir = (self.workspace_dir / "ref_images").resolve()
        refs_dir.mkdir(parents=True, exist_ok=True)
        fname = f"continue_{clip.id}_{uuid.uuid4().hex[:6]}.png"
        out_png = refs_dir / fname

        if media.is_image:
            shutil.copyfile(media.path, out_png)
        else:
            ts = max(0.0, clip.out_sec - 0.06)
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-ss",
                f"{ts:.3f}",
                "-i",
                media.path,
                "-frames:v",
                "1",
                str(out_png),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0 or not out_png.exists():
                # Fallback to near-EOF seek
                cmd_fb = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-sseof",
                    "-0.15",
                    "-i",
                    media.path,
                    "-frames:v",
                    "1",
                    str(out_png),
                ]
                subprocess.run(cmd_fb, capture_output=True, text=True, check=True)

        return {
            "clip_id": clip.id,
            "filename": fname,
            "image_path": str(out_png),
            "preview_url": f"/api/generate/ref/{fname}",
        }

    def smooth_clip_fps(self, clip_id: str, target_fps: float = 32.0) -> dict[str, Any]:
        """Motion-interpolate a choppy 16-24fps generated clip to silky smooth 32-48fps with fast-seek keyframes."""
        state = self.get_state()
        clip = state.get_clip(clip_id)
        if not clip:
            raise ValueError(f"Timeline clip '{clip_id}' not found.")
        media = state.get_media(clip.media_id)
        if not media or not media.has_video or media.is_image:
            raise ValueError("Smooth FPS requires a video clip.")

        fps_val = max(24.0, min(60.0, float(target_fps)))
        smooth_dir = (self.workspace_dir / "generated").resolve()
        smooth_dir.mkdir(parents=True, exist_ok=True)
        out_mp4 = smooth_dir / f"{Path(media.filename).stem}_{int(fps_val)}fps_{uuid.uuid4().hex[:6]}.mp4"

        vf = f"minterpolate=fps={fps_val:.2f}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            media.path,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-g",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0 or not out_mp4.exists():
            raise RuntimeError(f"Smooth FPS interpolation failed: {(res.stderr or '')[-500:]}")

        new_media = self.import_media([str(out_mp4)])[0]
        with self._lock:
            st = self._read_unlocked()
            target_clip = st.get_clip(clip_id)
            if target_clip:
                target_clip.media_id = new_media.id
                target_clip.out_sec = min(target_clip.out_sec, new_media.duration_sec)
                if not target_clip.label.endswith("fps)"):
                    target_clip.label = f"{target_clip.label[:24]} ({int(fps_val)}fps)"
                self._write_unlocked(st)
        return {
            "clip_id": clip_id,
            "media": new_media.model_dump(),
            "output_path": str(out_mp4),
            "target_fps": fps_val,
        }

    # -------------------------------------------------------------------------
    # Audio Overlays (Meme SFX / BGM + Auto-Ducking) & Meme Layout Templates
    # -------------------------------------------------------------------------
    def add_audio_overlay(
        self,
        sfx_id: str | None = None,
        audio_path: str | None = None,
        start_sec: float = 0.0,
        volume: float = 1.0,
        duck_main_audio: bool = False,
        label: str | None = None,
    ) -> AudioOverlay:
        if sfx_id:
            wav_path, spec = ensure_builtin_sfx_file(sfx_id, self.sfx_dir)
            resolved_path = str(wav_path)
            dur = float(spec["duration_sec"])
            final_label = label or f"{spec['emoji']} {spec['label']}"
        elif audio_path:
            p = Path(audio_path).expanduser().resolve()
            if not p.exists() or not p.is_file():
                raise FileNotFoundError(f"Audio overlay file not found: {p}")
            probed = probe_media_file(p, assets_dir=None)
            if not probed.has_audio:
                raise ValueError(f"File '{p.name}' has no audio stream.")
            resolved_path = str(p)
            dur = probed.duration_sec
            final_label = label or p.name
        else:
            raise ValueError("Provide either `sfx_id` or `audio_path`.")

        ov = AudioOverlay(
            id=new_id("sfx"),
            path=resolved_path,
            label=final_label[:64],
            sfx_id=sfx_id,
            start_sec=round(max(0.0, float(start_sec)), 3),
            duration_sec=round(max(0.05, dur), 3),
            volume=round(max(0.0, min(3.0, float(volume))), 3),
            duck_main_audio=bool(duck_main_audio),
        )
        with self._lock:
            state = self._read_unlocked()
            state.audio_overlays.append(ov)
            state.audio_overlays.sort(key=lambda x: x.start_sec)
            self._write_unlocked(state)
        return ov

    def update_audio_overlay(
        self,
        overlay_id: str,
        start_sec: float | None = None,
        volume: float | None = None,
        duck_main_audio: bool | None = None,
        label: str | None = None,
    ) -> AudioOverlay:
        with self._lock:
            state = self._read_unlocked()
            ov = next((x for x in state.audio_overlays if x.id == overlay_id), None)
            if not ov:
                raise ValueError(f"Audio overlay '{overlay_id}' not found.")
            if start_sec is not None:
                ov.start_sec = round(max(0.0, float(start_sec)), 3)
            if volume is not None:
                ov.volume = round(max(0.0, min(3.0, float(volume))), 3)
            if duck_main_audio is not None:
                ov.duck_main_audio = bool(duck_main_audio)
            if label is not None:
                ov.label = label.strip()[:64] or ov.label
            state.audio_overlays.sort(key=lambda x: x.start_sec)
            self._write_unlocked(state)
            return ov

    def remove_audio_overlay(self, overlay_id: str) -> ProjectState:
        with self._lock:
            state = self._read_unlocked()
            state.audio_overlays = [x for x in state.audio_overlays if x.id != overlay_id]
            return self._write_unlocked(state)

    def set_meme_layout(
        self,
        template: MemeTemplateType | None = None,
        top_text: str | None = None,
        bottom_text: str | None = None,
        banner_label: str | None = None,
    ) -> MemeLayoutConfig:
        with self._lock:
            state = self._read_unlocked()
            data = state.meme_layout.model_dump()
            if template is not None:
                data["template"] = template
            if top_text is not None:
                data["top_text"] = top_text
            if bottom_text is not None:
                data["bottom_text"] = bottom_text
            if banner_label is not None:
                data["banner_label"] = banner_label
            state.meme_layout = MemeLayoutConfig(**data)
            self._write_unlocked(state)
            return state.meme_layout

    def build_timeline_from_script(
        self,
        segments: list[dict[str, Any]],
        replace_existing: bool = True,
        default_transition: TransitionType = "crossfade",
        default_transition_duration: float = 0.35,
        auto_project_subtitles: bool = True,
    ) -> ProjectState:
        """Build or append an Edit Decision List (EDL) from AI-selected segments."""
        if default_transition not in XFADE_MAP:
            raise ValueError(f"Unsupported default_transition '{default_transition}'.")

        with self._lock:
            state = self._read_unlocked()
            built_clips: list[TimelineClip] = [] if replace_existing else list(state.timeline)

            for idx, seg in enumerate(segments):
                if "media_id" not in seg:
                    raise ValueError(f"Segment at index {idx} is missing required 'media_id'.")
                media_id = str(seg["media_id"])
                media = state.get_media(media_id)
                if not media:
                    raise ValueError(f"Media '{media_id}' not found in Media Bin.")

                in_s = round(max(0.0, float(seg.get("in_sec", 0.0))), 3)
                if in_s >= media.duration_sec - 0.05:
                    raise ValueError(
                        f"Segment {idx} in_sec ({in_s}s) exceeds media '{media.filename}' duration ({media.duration_sec}s)."
                    )
                raw_out = seg.get("out_sec")
                if raw_out is not None:
                    out_s = round(min(media.duration_sec, float(raw_out)), 3)
                    if out_s <= in_s + 0.04:
                        raise ValueError(
                            f"Segment {idx} out_sec ({out_s}s) must be greater than in_sec ({in_s}s)."
                        )
                else:
                    out_s = media.duration_sec

                speed = float(seg.get("speed", 1.0))
                if speed <= 0 or speed > 16.0:
                    raise ValueError(f"Segment {idx} speed ({speed}) must be within (0, 16].")
                volume = float(seg.get("volume", 1.0))
                if volume < 0 or volume > 4.0:
                    raise ValueError(f"Segment {idx} volume ({volume}) must be within [0, 4].")

                trans = seg.get("transition") or ("cut" if not built_clips else default_transition)
                if trans not in XFADE_MAP:
                    raise ValueError(f"Segment {idx} has unsupported transition '{trans}'.")
                tdur = max(0.0, min(5.0, float(seg.get("transition_duration", default_transition_duration))))

                built_clips.append(
                    TimelineClip(
                        id=new_id("clip"),
                        media_id=media.id,
                        label=str(seg.get("label") or media.filename),
                        in_sec=in_s,
                        out_sec=out_s,
                        speed=max(0.1, min(16.0, speed)),
                        volume=volume,
                        muted=bool(seg.get("muted", False)),
                        transition=trans,  # type: ignore[arg-type]
                        transition_duration=tdur,
                    )
                )

            state.timeline = built_clips

            if auto_project_subtitles:
                any_transcribed = any(
                    (state.get_media(c.media_id) and state.get_media(c.media_id).transcribed)
                    for c in state.timeline
                )
                if any_transcribed:
                    manual_subs = [s for s in state.subtitles if s.clip_id is None]
                    auto_subs = project_timeline_subtitles(state)
                    state.subtitles = sorted(manual_subs + auto_subs, key=lambda s: s.start_sec)

            return self._write_unlocked(state)

    def smart_stitch(
        self,
        media_ids: list[str] | None = None,
        order_by: str = "custom",
        trim_silence: bool = True,
        split_long_silences: bool = False,
        min_silence_sec: float = 0.55,
        noise_db: float = -35.0,
        padding_sec: float = 0.12,
        transition: TransitionType = "crossfade",
        transition_duration: float = 0.35,
        auto_subtitle: bool = False,
        whisper_model: str = "base",
    ) -> dict[str, Any]:
        """Intelligently analyze, trim dead air, stitch clips atomically with transitions, and optionally subtitle."""
        if transition not in XFADE_MAP:
            raise ValueError(f"Unsupported transition '{transition}'.")

        state = self.get_state()
        if media_ids is not None:
            missing = [mid for mid in media_ids if state.get_media(mid) is None]
            if missing:
                raise ValueError(f"Unknown media_id(s): {', '.join(missing)}")
            items = [state.get_media(mid) for mid in media_ids]
            items = [m for m in items if m is not None]
        else:
            items = list(state.media_bin)

        if not items:
            raise ValueError("No media items found to stitch. Import media first.")

        if order_by == "filename":
            items.sort(key=lambda m: m.filename.lower())
        elif order_by == "chronological":
            items.sort(
                key=lambda m: (
                    Path(m.path).stat().st_mtime if Path(m.path).exists() else 0.0,
                    m.filename.lower(),
                )
            )
        elif order_by == "duration":
            items.sort(key=lambda m: m.duration_sec)

        # Compute all heavy analysis/transcription OUTSIDE FileLock; commit in ONE atomic write
        analysis_updates: dict[str, dict[str, Any]] = {}
        new_clips: list[TimelineClip] = []
        raw_total_dur = 0.0

        for m in items:
            raw_total_dur += m.duration_sec
            silent_segs = m.silent_segments
            active_segs = m.active_segments
            transcript = m.transcript
            transcribed = m.transcribed

            if trim_silence and m.has_audio:
                silent_segs, active_segs = detect_silence_and_active_segments(
                    m.path,
                    m.duration_sec,
                    noise_db=noise_db,
                    min_silence_sec=min_silence_sec,
                    padding_sec=padding_sec,
                )

            if auto_subtitle and m.has_audio and not m.transcribed:
                transcript = transcribe_media_file(m.path, model_size=whisper_model)
                transcribed = True

            analysis_updates[m.id] = {
                "silent_segments": silent_segs,
                "active_segments": active_segs,
                "transcript": transcript,
                "transcribed": transcribed,
            }

            if trim_silence and active_segs:
                if split_long_silences:
                    for seg_idx, act in enumerate(active_segs):
                        if act.duration_sec < 0.25:
                            continue
                        new_clips.append(
                            TimelineClip(
                                id=new_id("clip"),
                                media_id=m.id,
                                label=f"{m.filename} #{seg_idx + 1}" if len(active_segs) > 1 else m.filename,
                                in_sec=act.start_sec,
                                out_sec=act.end_sec,
                                transition="cut" if not new_clips else transition,
                                transition_duration=0.0 if not new_clips else transition_duration,
                            )
                        )
                else:
                    in_s = active_segs[0].start_sec
                    out_s = active_segs[-1].end_sec
                    if out_s - in_s < 0.25:
                        in_s, out_s = 0.0, m.duration_sec
                    new_clips.append(
                        TimelineClip(
                            id=new_id("clip"),
                            media_id=m.id,
                            label=m.filename,
                            in_sec=in_s,
                            out_sec=out_s,
                            transition="cut" if not new_clips else transition,
                            transition_duration=0.0 if not new_clips else transition_duration,
                        )
                    )
            else:
                new_clips.append(
                    TimelineClip(
                        id=new_id("clip"),
                        media_id=m.id,
                        label=m.filename,
                        in_sec=0.0,
                        out_sec=m.duration_sec,
                        transition="cut" if not new_clips else transition,
                        transition_duration=0.0 if not new_clips else transition_duration,
                    )
                )

        # Single atomic commit under FileLock (clean undo step + single WS broadcast)
        with self._lock:
            state = self._read_unlocked()
            for mid, upd in analysis_updates.items():
                target_m = state.get_media(mid)
                if target_m:
                    target_m.silent_segments = upd["silent_segments"]
                    target_m.active_segments = upd["active_segments"]
                    target_m.analyzed = True
                    if upd["transcribed"]:
                        target_m.transcript = upd["transcript"]
                        target_m.transcribed = True
            state.timeline = new_clips
            if auto_subtitle or any(m.transcribed for m in state.media_bin):
                state.subtitles = project_timeline_subtitles(state)
            state = self._write_unlocked(state)

        stitched_dur = state.total_duration_sec
        return {
            "clips_count": len(state.timeline),
            "raw_duration_sec": round(raw_total_dur, 3),
            "stitched_duration_sec": round(stitched_dur, 3),
            "saved_dead_air_sec": round(max(0.0, raw_total_dur - stitched_dur), 3),
            "subtitles_count": len(state.subtitles),
            "timeline": [c.model_dump() for c in state.timeline],
        }

    # -------------------------------------------------------------------------
    # Subtitling & Caption Styling
    # -------------------------------------------------------------------------
    def auto_subtitle_timeline(
        self,
        model_size: str = "base",
        language: str | None = None,
        style_preset: str | None = None,
        max_words_per_caption: int | None = None,
        force_retranscribe: bool = False,
    ) -> list[SubtitleEntry]:
        state = self.get_state()
        if not state.timeline:
            raise ValueError("Timeline is empty — add clips to the timeline before generating subtitles.")

        unique_media_ids = list(dict.fromkeys(c.media_id for c in state.timeline))
        new_transcripts: dict[str, list] = {}
        for mid in unique_media_ids:
            media = state.get_media(mid)
            if not media or not media.has_audio:
                continue
            if force_retranscribe or not media.transcribed:
                new_transcripts[mid] = transcribe_media_file(
                    media.path,
                    model_size=model_size,
                    language=language,
                )

        with self._lock:
            state = self._read_unlocked()
            for mid, tr in new_transcripts.items():
                target = state.get_media(mid)
                if target:
                    target.transcript = tr
                    target.transcribed = True

            if style_preset and style_preset in STYLE_PRESETS:
                state.subtitle_style = SubtitleStyle(**STYLE_PRESETS[style_preset])
            if max_words_per_caption is not None:
                state.subtitle_style.max_words_per_caption = max(1, min(20, int(max_words_per_caption)))

            state.subtitles = project_timeline_subtitles(
                state,
                max_words_per_caption=state.subtitle_style.max_words_per_caption,
            )
            self._write_unlocked(state)
            return state.subtitles

    def set_subtitle_style(self, **kwargs: Any) -> SubtitleStyle:
        with self._lock:
            state = self._read_unlocked()
            preset = kwargs.get("preset")
            if preset and preset in STYLE_PRESETS:
                base_dict = dict(STYLE_PRESETS[preset])
            else:
                base_dict = state.subtitle_style.model_dump()

            non_preset_overrides = False
            for k, v in kwargs.items():
                if v is not None and k in base_dict:
                    if k != "preset" and base_dict[k] != v:
                        non_preset_overrides = True
                    base_dict[k] = v

            if non_preset_overrides and (preset is None or preset in STYLE_PRESETS):
                # Mark preset as 'custom' whenever caller overrides properties away from preset defaults
                if base_dict.get("preset") in STYLE_PRESETS:
                    ref = STYLE_PRESETS[base_dict["preset"]]
                    if any(base_dict.get(k) != ref.get(k) for k in ref if k != "preset"):
                        base_dict["preset"] = "custom"

            old_max_words = state.subtitle_style.max_words_per_caption
            state.subtitle_style = SubtitleStyle(**base_dict)

            # Re-chunk auto-generated captions without wiping manually authored captions (clip_id is None)
            if (
                state.subtitle_style.max_words_per_caption != old_max_words
                and any(m.transcribed for m in state.media_bin)
            ):
                manual_subs = [s for s in state.subtitles if s.clip_id is None]
                auto_subs = project_timeline_subtitles(
                    state,
                    max_words_per_caption=state.subtitle_style.max_words_per_caption,
                )
                state.subtitles = sorted(manual_subs + auto_subs, key=lambda s: s.start_sec)

            self._write_unlocked(state)
            return state.subtitle_style

    def upsert_subtitle(
        self,
        start_sec: float,
        end_sec: float,
        text: str,
        subtitle_id: str | None = None,
        words: list[dict[str, Any]] | None = None,
    ) -> SubtitleEntry:
        clean_txt = (text or "").strip()
        if not clean_txt:
            raise ValueError("Subtitle text cannot be empty.")

        with self._lock:
            state = self._read_unlocked()
            s_sec = round(max(0.0, float(start_sec)), 3)
            e_sec = round(max(s_sec + 0.1, float(end_sec)), 3)

            word_tokens: list[WordToken] = []
            if words:
                word_tokens = [WordToken(**w) for w in words]
            else:
                raw_toks = [t for t in clean_txt.split() if t]
                if raw_toks:
                    step = (e_sec - s_sec) / len(raw_toks)
                    for i, tok in enumerate(raw_toks):
                        word_tokens.append(
                            WordToken(
                                word=tok,
                                start_sec=round(s_sec + i * step, 3),
                                end_sec=round(s_sec + (i + 1) * step, 3),
                            )
                        )

            existing = next((s for s in state.subtitles if s.id == subtitle_id), None) if subtitle_id else None
            if existing:
                existing.start_sec = s_sec
                existing.end_sec = e_sec
                existing.text = clean_txt
                existing.words = word_tokens
                existing.clip_id = None  # Mark manually edited so style re-chunking preserves it
                entry = existing
            else:
                entry = SubtitleEntry(
                    id=subtitle_id or new_id("sub"),
                    start_sec=s_sec,
                    end_sec=e_sec,
                    text=clean_txt,
                    words=word_tokens,
                    clip_id=None,
                )
                state.subtitles.append(entry)

            state.subtitles.sort(key=lambda s: s.start_sec)
            self._write_unlocked(state)
            return entry

    def remove_subtitle(self, subtitle_id: str) -> ProjectState:
        with self._lock:
            state = self._read_unlocked()
            state.subtitles = [s for s in state.subtitles if s.id != subtitle_id]
            return self._write_unlocked(state)

    def clear_subtitles(self) -> ProjectState:
        with self._lock:
            state = self._read_unlocked()
            state.subtitles = []
            return self._write_unlocked(state)

    def export_subtitles(self, output_path: str | None = None, fmt: str = "srt") -> str:
        state = self.get_state()
        ext = ".ass" if fmt.lower() == "ass" else ".srt"
        out = Path(output_path) if output_path else (self.renders_dir / f"subtitles{ext}")
        saved = write_subtitle_file(state, out, fmt=fmt)
        return str(saved)

    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------
    def render_video(
        self,
        output_path: str | None = None,
        burn_subtitles: bool = True,
        quality: str = "balanced",
        normalize_audio: bool = True,
        use_hw_accel: bool = True,
    ) -> dict[str, Any]:
        state = self.get_state()
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in state.name).strip("_") or "render"
            out_file = self.renders_dir / f"{safe_name}_{ts}.mp4"
        else:
            out_file = Path(output_path).expanduser().resolve()

        result = render_project_to_mp4(
            state,
            output_path=out_file,
            burn_subtitles=burn_subtitles,
            quality=quality,
            normalize_audio=normalize_audio,
            use_hw_accel=use_hw_accel,
        )

        with self._lock:
            st = self._read_unlocked()
            st.last_render_path = result["output_path"]
            self._write_unlocked(st, record_undo=False)

        return result
