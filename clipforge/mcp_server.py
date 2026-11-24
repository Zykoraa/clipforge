"""MCP (Model Context Protocol) Server for AI-driven Video Editing, Smart Stitching, and Auto-Subtitling."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import urllib.request
import webbrowser
from typing import Any

# Suppress noisy download/progress stdout from HuggingFace/tqdm so MCP stdio framing stays clean
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore

from .cast import CastManager
from .director import expand_meme_prompt_local
from .engine import ProjectEngine
from .generator import (
    CAMERA_PRESETS,
    COMFYUI_DIR,
    COMFYUI_URL,
    DEFAULT_NEGATIVE_PROMPT,
    PROMPT_PRESETS,
    download_manager,
    ensure_comfyui_running,
    generate_image_via_comfyui,
    generate_video_via_comfyui,
    get_model_availability,
    is_comfyui_reachable,
    polish_image_hd as _polish_image_hd,
    resolve_auto_model,
)
from .media import IMAGE_EXTENSIONS
from .models import MemeTemplateType, TransitionType
from .platform_utils import detached_popen_kwargs
from .sfx import list_builtin_sfx as _list_builtin_sfx
from .voice import clone_voice_offline, get_voice_cloner_status

INSTRUCTIONS = """ClipForge MCP — AI-Controllable Non-Linear Video Editor & Offline AI Media Studio.

Workflow recommendations for AI agents:
1. Call `get_project_state` or `configure_project` to inspect/set canvas resolution (e.g. 1920x1080 landscape or 1080x1920 vertical shorts).
2. Call `import_media` with file paths or folder paths to load video, audio, or static meme image files into the Media Bin.
3. For offline AI Image & Video Generation (local ComfyUI, zero refusals):
   - Call `get_video_generator_status` to inspect installed Video (`wan22_5b`, `wan22_i2v`, `wan22_t2v`, `ltx23`) and Image (`flux2_klein`, `flux2_klein_9b`, `z_image_turbo`, `qwen_edit`, `qwen_edit_2511`) models plus available style presets.
   - Call `download_model_bundle` to download any missing model weights in the background into the local ComfyUI models directory (`CLIPFORGE_COMFYUI_DIR`).
   - Call `generate_image` to create photorealistic memes or edit/composite 1-2 friend photos (`flux2_klein`, `flux2_klein_9b`, `z_image_turbo`, `qwen_edit`, `qwen_edit_2511`), optionally adding a 3s still to the timeline.
   - Call `generate_video_clip` to animate any friend photo or generate text-to-video clips (`wan22_5b`, `wan22_i2v`, `wan22_t2v`, `ltx23`) and auto-append to the timeline.
   - Call `list_generated_assets` to browse previously generated images, videos, and uploaded friend photos.
4. For intelligent content-aware editing:
   - Call `analyze_clip` on each clip to detect silent dead-air intervals, visual scene cuts, and full word-level speech transcripts.
   - Or call `extract_clip_frames` to inspect visual snapshots of any clip.
5. To assemble the video:
   - Use `smart_stitch` for automatic dead-air trimming, silence removal, smooth transitions, and auto-subtitling across clips.
   - Or use `build_timeline_from_script` to pass an exact Edit Decision List (EDL) of `[{media_id, in_sec, out_sec, transition, transition_duration, speed, label}]`.
   - Or fine-tune individual clips with `add_timeline_clip`, `update_timeline_clip`, `split_timeline_clip`, `remove_timeline_clip`, and `reorder_timeline_clips`.
6. For subtitles:
   - Call `auto_subtitle_timeline` (presets: 'hormozi', 'cinema', 'minimal', 'neon_box') or `upsert_subtitle` / `set_subtitle_style`.
7. Call `render_video` to compile the timeline (including static meme stills) with FFmpeg (`xfade` transitions + `libass` burned-in subtitles + NVENC/x264) into a finished MP4.
"""

mcp = MCPServer(
    name="clipforge-video-editor",
    title="ClipForge AI Video Editor",
    instructions=INSTRUCTIONS,
)

_engine: ProjectEngine | None = None


def get_engine() -> ProjectEngine:
    global _engine
    if _engine is None:
        _engine = ProjectEngine()
    return _engine


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _is_clipforge_running(port: int) -> bool:
    if not _is_port_open(port):
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("service") == "clipforge"
    except Exception:
        return False


@mcp.tool()
def get_project_state() -> dict[str, Any]:
    """Get the complete current state of the video editor project, including Media Bin, Timeline Schedule, and Subtitles."""
    return get_engine().get_summary_dict()


@mcp.tool()
def configure_project(
    name: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    """Configure project name, resolution (e.g. 1920x1080 landscape, 1080x1920 vertical), FPS, or reset to a blank project."""
    get_engine().configure_project(name=name, width=width, height=height, fps=fps, reset=reset)
    return get_engine().get_summary_dict()


@mcp.tool()
def open_editor_ui(port: int = 8765, launch_browser: bool = True) -> dict[str, Any]:
    """Start the local ClipForge visual timeline editor server (if not already running) and open it in the browser."""
    if not (1024 <= int(port) <= 65535):
        raise ValueError("port must be an unprivileged TCP port in [1024, 65535].")
    url = f"http://127.0.0.1:{port}"

    if _is_port_open(port):
        if not _is_clipforge_running(port):
            raise RuntimeError(
                f"Port {port} is already occupied by a non-ClipForge service. Choose another port."
            )
    else:
        log_path = get_engine().workspace_dir / "web_server.log"
        launch_cmd = (
            [sys.executable, "--port", str(port), "--no-browser"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "clipforge.web_server", "--port", str(port)]
        )
        with open(log_path, "ab") as log_fh:
            subprocess.Popen(
                launch_cmd,
                stdout=log_fh,
                stderr=log_fh,
                env={**os.environ, "CLIPFORGE_WORKSPACE": str(get_engine().workspace_dir)},
                **detached_popen_kwargs(),
            )
    if launch_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return {"ui_url": url, "workspace": str(get_engine().workspace_dir), "status": "running"}


@mcp.tool()
def import_media(paths: list[str]) -> dict[str, Any]:
    """Import one or more video/audio files or directories of clips into the Media Bin.

    Probes duration, resolution, FPS, codecs, generates thumbnail & audio waveform peaks.
    """
    with contextlib.redirect_stdout(sys.stderr):
        items = get_engine().import_media(paths)
    return {
        "imported_count": len(items),
        "imported_media": [m.model_dump() for m in items],
        "total_media_in_bin": len(get_engine().get_state().media_bin),
    }


@mcp.tool()
def analyze_clip(
    media_id: str,
    detect_silence: bool = True,
    detect_scenes: bool = True,
    transcribe: bool = True,
    model_size: str = "base",
    language: str | None = None,
    noise_db: float = -35.0,
    min_silence_sec: float = 0.4,
) -> dict[str, Any]:
    """Run deep intelligence on a clip: detect silent/active intervals, visual scene cuts, and word-level Whisper speech transcript."""
    with contextlib.redirect_stdout(sys.stderr):
        item = get_engine().analyze_clip(
            media_id=media_id,
            detect_silence=detect_silence,
            detect_scenes=detect_scenes,
            transcribe=transcribe,
            model_size=model_size,
            language=language,
            noise_db=noise_db,
            min_silence_sec=min_silence_sec,
        )
    return {
        "media_id": item.id,
        "filename": item.filename,
        "duration_sec": item.duration_sec,
        "active_segments": [s.model_dump() for s in item.active_segments],
        "silent_segments": [s.model_dump() for s in item.silent_segments],
        "scene_cuts": item.scene_cuts,
        "full_transcript_text": item.full_transcript_text,
        "transcript_segments": [s.model_dump() for s in item.transcript],
    }


@mcp.tool()
def extract_clip_frames(
    media_id: str,
    timestamps_sec: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Extract JPEG frame snapshots from a clip at specific timestamps (defaults to 15%, 50%, 85% of duration) so the AI can visually inspect them."""
    with contextlib.redirect_stdout(sys.stderr):
        return get_engine().extract_clip_frames(media_id=media_id, timestamps_sec=timestamps_sec)


@mcp.tool()
def smart_stitch(
    media_ids: list[str] | None = None,
    order_by: str = "custom",
    trim_silence: bool = True,
    split_long_silences: bool = False,
    min_silence_sec: float = 0.55,
    noise_db: float = -35.0,
    padding_sec: float = 0.12,
    transition: TransitionType = "crossfade",
    transition_duration: float = 0.35,
    auto_subtitle: bool = True,
    whisper_model: str = "base",
) -> dict[str, Any]:
    """Intelligently stitch clips into a cohesive timeline.

    - `media_ids`: Optional list of media IDs in desired order (defaults to all clips in Media Bin).
    - `order_by`: 'custom' (preserve `media_ids` order), 'filename', 'chronological', or 'duration'.
    - `trim_silence`: Automatically detect and trim leading/trailing dead air from each clip.
    - `split_long_silences`: Also cut out mid-clip pauses longer than `min_silence_sec`.
    - `transition`: 'cut', 'crossfade', 'fadeblack', 'fadewhite', 'wipeleft', 'wiperight', 'slideup', 'slidedown', 'circleopen', 'dissolve', 'pixelize'.
    - `auto_subtitle`: Automatically transcribe and project word-level subtitles onto the stitched timeline.
    """
    with contextlib.redirect_stdout(sys.stderr):
        return get_engine().smart_stitch(
            media_ids=media_ids,
            order_by=order_by,
            trim_silence=trim_silence,
            split_long_silences=split_long_silences,
            min_silence_sec=min_silence_sec,
            noise_db=noise_db,
            padding_sec=padding_sec,
            transition=transition,
            transition_duration=transition_duration,
            auto_subtitle=auto_subtitle,
            whisper_model=whisper_model,
        )


@mcp.tool()
def build_timeline_from_script(
    segments: list[dict[str, Any]],
    replace_existing: bool = True,
    default_transition: TransitionType = "crossfade",
    default_transition_duration: float = 0.35,
    auto_project_subtitles: bool = True,
) -> dict[str, Any]:
    """Assemble a precision timeline from an Edit Decision List (EDL) of segments."""
    get_engine().build_timeline_from_script(
        segments=segments,
        replace_existing=replace_existing,
        default_transition=default_transition,
        default_transition_duration=default_transition_duration,
        auto_project_subtitles=auto_project_subtitles,
    )
    return get_engine().get_summary_dict()


@mcp.tool()
def add_timeline_clip(
    media_id: str,
    in_sec: float = 0.0,
    out_sec: float | None = None,
    position_index: int | None = None,
    transition: TransitionType = "cut",
    transition_duration: float = 0.4,
    speed: float = 1.0,
    volume: float = 1.0,
    label: str = "",
) -> dict[str, Any]:
    """Add a single trimmed clip to the timeline at `position_index` (or append to end)."""
    clip = get_engine().add_timeline_clip(
        media_id=media_id,
        in_sec=in_sec,
        out_sec=out_sec,
        position_index=position_index,
        transition=transition,
        transition_duration=transition_duration,
        speed=speed,
        volume=volume,
        label=label,
    )
    return {"added_clip": clip.model_dump(), "summary": get_engine().get_summary_dict()}


@mcp.tool()
def update_timeline_clip(
    clip_id: str,
    in_sec: float | None = None,
    out_sec: float | None = None,
    transition: TransitionType | None = None,
    transition_duration: float | None = None,
    speed: float | None = None,
    volume: float | None = None,
    muted: bool | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Modify trim in/out points, transition, speed, volume, or mute state of an existing timeline clip."""
    clip = get_engine().update_timeline_clip(
        clip_id=clip_id,
        in_sec=in_sec,
        out_sec=out_sec,
        transition=transition,
        transition_duration=transition_duration,
        speed=speed,
        volume=volume,
        muted=muted,
        label=label,
    )
    return {"updated_clip": clip.model_dump(), "summary": get_engine().get_summary_dict()}


@mcp.tool()
def split_timeline_clip(
    clip_id: str,
    split_at_source_sec: float | None = None,
    split_at_timeline_sec: float | None = None,
) -> dict[str, Any]:
    """Split a timeline clip into two consecutive clips at a source timestamp or timeline timestamp."""
    c1, c2 = get_engine().split_timeline_clip(
        clip_id=clip_id,
        split_at_source_sec=split_at_source_sec,
        split_at_timeline_sec=split_at_timeline_sec,
    )
    return {
        "part_1": c1.model_dump(),
        "part_2": c2.model_dump(),
        "summary": get_engine().get_summary_dict(),
    }


@mcp.tool()
def remove_timeline_clip(clip_id: str) -> dict[str, Any]:
    """Remove a clip from the timeline by its clip_id."""
    get_engine().remove_timeline_clip(clip_id)
    return get_engine().get_summary_dict()


@mcp.tool()
def reorder_timeline_clips(clip_ids: list[str]) -> dict[str, Any]:
    """Reorder clips on the timeline according to the provided list of clip_ids."""
    get_engine().reorder_timeline_clips(clip_ids)
    return get_engine().get_summary_dict()


@mcp.tool()
def auto_subtitle_timeline(
    model_size: str = "base",
    language: str | None = None,
    style_preset: str | None = "hormozi",
    max_words_per_caption: int | None = None,
    force_retranscribe: bool = False,
) -> dict[str, Any]:
    """Automatically transcribe timeline clips with Whisper and generate word-accurate synced subtitles."""
    with contextlib.redirect_stdout(sys.stderr):
        subs = get_engine().auto_subtitle_timeline(
            model_size=model_size,
            language=language,
            style_preset=style_preset,
            max_words_per_caption=max_words_per_caption,
            force_retranscribe=force_retranscribe,
        )
    return {
        "subtitles_count": len(subs),
        "style": get_engine().get_state().subtitle_style.model_dump(),
        "subtitles": [s.model_dump() for s in subs],
    }


@mcp.tool()
def set_subtitle_style(
    preset: str | None = None,
    font_name: str | None = None,
    font_size: int | None = None,
    primary_color: str | None = None,
    highlight_color: str | None = None,
    outline_color: str | None = None,
    back_color: str | None = None,
    back_opacity: float | None = None,
    bold: bool | None = None,
    uppercase: bool | None = None,
    word_highlight: bool | None = None,
    outline_width: float | None = None,
    shadow_depth: float | None = None,
    alignment: int | None = None,
    margin_v: int | None = None,
    max_words_per_caption: int | None = None,
) -> dict[str, Any]:
    """Customize subtitle appearance or switch presets ('hormozi', 'cinema', 'minimal', 'neon_box')."""
    style = get_engine().set_subtitle_style(
        preset=preset,
        font_name=font_name,
        font_size=font_size,
        primary_color=primary_color,
        highlight_color=highlight_color,
        outline_color=outline_color,
        back_color=back_color,
        back_opacity=back_opacity,
        bold=bold,
        uppercase=uppercase,
        word_highlight=word_highlight,
        outline_width=outline_width,
        shadow_depth=shadow_depth,
        alignment=alignment,
        margin_v=margin_v,
        max_words_per_caption=max_words_per_caption,
    )
    return style.model_dump()


@mcp.tool()
def upsert_subtitle(
    start_sec: float,
    end_sec: float,
    text: str,
    subtitle_id: str | None = None,
) -> dict[str, Any]:
    """Add a new subtitle caption block or update an existing one by `subtitle_id`."""
    entry = get_engine().upsert_subtitle(
        start_sec=start_sec,
        end_sec=end_sec,
        text=text,
        subtitle_id=subtitle_id,
    )
    return entry.model_dump()


@mcp.tool()
def remove_subtitle(subtitle_id: str) -> dict[str, Any]:
    """Delete a subtitle block by its ID."""
    st = get_engine().remove_subtitle(subtitle_id)
    return {"subtitles_count": len(st.subtitles)}


@mcp.tool()
def export_subtitles(output_path: str | None = None, fmt: str = "srt") -> dict[str, Any]:
    """Export timeline subtitles to a standalone .srt or .ass file."""
    path = get_engine().export_subtitles(output_path=output_path, fmt=fmt)
    return {"subtitle_file": path, "format": fmt}


@mcp.tool()
def undo_action() -> dict[str, Any]:
    """Undo the last timeline or subtitle edit."""
    get_engine().undo()
    return get_engine().get_summary_dict()


@mcp.tool()
def redo_action() -> dict[str, Any]:
    """Redo the previously undone edit."""
    get_engine().redo()
    return get_engine().get_summary_dict()


@mcp.tool()
def render_video(
    output_path: str | None = None,
    burn_subtitles: bool = True,
    quality: str = "balanced",
    normalize_audio: bool = True,
    use_hw_accel: bool = True,
) -> dict[str, Any]:
    """Render the stitched timeline with transitions and burned-in styled subtitles to an MP4 file."""
    with contextlib.redirect_stdout(sys.stderr):
        return get_engine().render_video(
            output_path=output_path,
            burn_subtitles=burn_subtitles,
            quality=quality,
            normalize_audio=normalize_audio,
            use_hw_accel=use_hw_accel,
        )


@mcp.tool()
def get_video_generator_status(auto_start: bool = False) -> dict[str, Any]:
    """Check local offline ComfyUI status, installed Video & Image model bundles, active downloads, and style presets."""
    with contextlib.redirect_stdout(sys.stderr):
        if auto_start:
            ensure_comfyui_running()
        return {
            "comfyui_url": COMFYUI_URL,
            "comfyui_dir": str(COMFYUI_DIR),
            "comfyui_running": is_comfyui_reachable(),
            "models": get_model_availability(),
            "presets": PROMPT_PRESETS,
            "camera_presets": CAMERA_PRESETS,
        }


@mcp.tool()
def download_model_bundle(model_id: str) -> dict[str, Any]:
    """Start (or resume) a background HuggingFace download for a local ComfyUI model bundle into CLIPFORGE_COMFYUI_DIR.

    Valid `model_id` values:
    - Video: 'wan22_5b', 'wan22_i2v', 'wan22_t2v', 'ltx23'
    - Image: 'flux2_klein', 'flux2_klein_9b', 'z_image_turbo', 'qwen_edit', 'qwen_edit_2511'
    """
    with contextlib.redirect_stdout(sys.stderr):
        dl_state = download_manager.start_download(model_id)
        avail = get_model_availability()
    return {
        "model_id": model_id,
        "download": dl_state,
        "model_info": avail.get(model_id),
    }


@mcp.tool()
def list_generated_assets(limit: int = 25) -> dict[str, Any]:
    """List recently generated offline images, generated videos, and uploaded friend reference photos."""
    eng = get_engine()
    cap = max(1, min(100, int(limit)))

    def _scan(folder: Any, exts: set[str]) -> list[dict[str, Any]]:
        if not folder.exists():
            return []
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {
                "filename": p.name,
                "path": str(p.resolve()),
                "size_bytes": p.stat().st_size,
            }
            for p in files[:cap]
        ]

    return {
        "generated_images": _scan(eng.workspace_dir / "generated_images", IMAGE_EXTENSIONS),
        "generated_videos": _scan(eng.workspace_dir / "generated", {".mp4", ".webm", ".mkv", ".mov"}),
        "reference_photos": _scan(eng.workspace_dir / "ref_images", IMAGE_EXTENSIONS),
    }


@mcp.tool()
def generate_image(
    prompt: str,
    model: str = "auto",
    image_path: str | None = None,
    image_path_2: str | None = None,
    negative_prompt: str = "",
    style_preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    match_photo_aspect: bool = True,
    steps: int | None = None,
    cfg: float | None = None,
    seed: int = -1,
    batch_size: int = 1,
    add_to_timeline: bool = False,
    transition: TransitionType = "crossfade",
    transition_duration: float = 0.35,
) -> dict[str, Any]:
    """Generate 1-4 photorealistic meme images or edit/composite friend photos offline via local ComfyUI.

    - Supports `@FriendName` mentions from saved Cast profiles (auto-attaches their photos!).
    - `model='auto'` (default): automatically picks the highest-quality ready model (`z_image_turbo` for 0 photos, `flux2_klein_9b`/`flux2_klein` for 1 photo, `qwen_edit_2511`/`qwen_edit` for 2 photos).
    - `model='flux2_klein'`: Ultra-fast 4-step T2I + friend-photo editing (`image_path` optional).
    - `model='flux2_klein_9b'`: 16GB VRAM 4-step HQ upgrade over 4B (`image_path` optional).
    - `model='z_image_turbo'`: 8-step hyper-real candid photography & crisp embedded meme text (T2I).
    - `model='qwen_edit'`: Instruction-based 1-2 friend photo compositor (`image_path` required, `image_path_2` optional; auto-uses 4-step Lightning LoRA if installed).
    - `model='qwen_edit_2511'`: Upgraded 4-step Lightning 1-2 friend photo compositor with tighter multi-person identity lock.
    - `match_photo_aspect=True`: automatically preserves the uploaded photo's aspect ratio to prevent stretched faces.
    - `batch_size`: 1..4 distinct seeds (4-seed meme contact sheet).
    - `style_preset`: Optional preset ('none', 'raw_iphone', 'cctv', 'breaking_news', 'podcast', 'movie_poster', 'meme_reaction', etc.).
    """
    eng = get_engine()
    cm = CastManager(eng.workspace_dir)
    out_dir = eng.workspace_dir / "generated_images"
    with contextlib.redirect_stdout(sys.stderr):
        resolved_prompt, img1, img2, _ = cm.resolve_prompt_mentions(prompt, image_path, image_path_2)
        chosen = resolve_auto_model("image", bool(img1), bool(img2)) if model == "auto" else model
        gen_res = generate_image_via_comfyui(
            prompt=resolved_prompt,
            output_dir=out_dir,
            model=chosen,  # type: ignore[arg-type]
            image_path=img1,
            image_path_2=img2,
            negative_prompt=negative_prompt,
            style_preset=style_preset,
            width=width,
            height=height,
            match_photo_aspect=match_photo_aspect,
            steps=steps,
            cfg=cfg,
            seed=seed,
            batch_size=batch_size,
            auto_start=True,
        )
        media_item = None
        added_clip = None
        if add_to_timeline:
            imported = eng.import_media([gen_res["image_path"]])
            media_item = imported[0]
            cur_tl = eng.get_state().timeline
            use_trans: TransitionType = transition if cur_tl else "cut"
            added_clip = eng.add_timeline_clip(
                media_id=media_item.id,
                transition=use_trans,
                transition_duration=transition_duration if cur_tl else 0.0,
                label=f"{chosen}: {prompt[:28]}",
            )
    return {
        "generation": gen_res,
        "media": media_item.model_dump() if media_item else None,
        "added_clip": added_clip.model_dump() if added_clip else None,
        "summary": eng.get_summary_dict() if add_to_timeline else None,
    }


@mcp.tool()
def generate_video_clip(
    prompt: str,
    model: str = "auto",
    image_path: str | None = None,
    end_image_path: str | None = None,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    style_preset: str | None = None,
    camera_preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    match_photo_aspect: bool = True,
    want_audio: bool = False,
    fast_draft: bool = False,
    num_frames: int | None = None,
    fps: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    seed: int = -1,
    add_to_timeline: bool = True,
    transition: TransitionType = "crossfade",
    transition_duration: float = 0.35,
) -> dict[str, Any]:
    """Generate a video clip completely offline via local ComfyUI (`auto`, `wan22_5b`, `wan22_i2v`, `wan22_t2v`, or `ltx23`).

    - Supports `@FriendName` mentions from saved Cast profiles (auto-attaches their photo!).
    - `model='auto'` (default): picks `ltx23` (when `want_audio=True`), `wan22_i2v` (photo + best likeness), `wan22_t2v` (14B T2V if installed), or `wan22_5b` (fast/T2V).
    - `model='wan22_5b'`: Fast Text-to-Video or Image-to-Video on 8GB VRAM.
    - `model='wan22_i2v'`: Best face likeness & motion for Image-to-Video (requires `image_path`, supports optional `end_image_path` for first->last frame morph!).
    - `model='wan22_t2v'`: HQ dual-expert 14B Text-to-Video + 4-step Lightx2v LoRAs.
    - `model='ltx23'`: Fast 8-step distilled Text-to-Video or Image-to-Video with synchronized native audio/SFX.
    - `style_preset`: Optional preset ('none', 'raw_iphone', 'cctv', 'breaking_news', 'podcast', 'movie_poster', 'meme_reaction', etc.).
    """
    eng = get_engine()
    cm = CastManager(eng.workspace_dir)
    gen_dir = eng.workspace_dir / "generated"
    with contextlib.redirect_stdout(sys.stderr):
        resolved_prompt, img1, _, _ = cm.resolve_prompt_mentions(prompt, image_path, None)
        chosen = (
            resolve_auto_model("video", bool(img1), False, want_audio=want_audio, fast_draft=fast_draft)
            if model == "auto"
            else model
        )
        gen_res = generate_video_via_comfyui(
            prompt=resolved_prompt,
            output_dir=gen_dir,
            model=chosen,  # type: ignore[arg-type]
            image_path=img1,
            end_image_path=end_image_path,
            negative_prompt=negative_prompt,
            style_preset=style_preset,
            camera_preset=camera_preset,
            width=width,
            height=height,
            match_photo_aspect=match_photo_aspect,
            num_frames=num_frames,
            fps=fps,
            steps=steps,
            cfg=cfg,
            seed=seed,
            auto_start=True,
        )
        imported = eng.import_media([gen_res["video_path"]])
        media_item = imported[0]
        added_clip = None
        if add_to_timeline:
            cur_tl = eng.get_state().timeline
            use_trans: TransitionType = transition if cur_tl else "cut"
            added_clip = eng.add_timeline_clip(
                media_id=media_item.id,
                transition=use_trans,
                transition_duration=transition_duration if cur_tl else 0.0,
                label=f"{chosen}: {prompt[:28]}",
            )
    return {
        "generation": gen_res,
        "media": media_item.model_dump(),
        "added_clip": added_clip.model_dump() if added_clip else None,
        "summary": eng.get_summary_dict(),
    }


@mcp.tool()
def list_cast_members() -> list[dict[str, Any]]:
    """List saved friend / cast profiles (reference photos, @handles, and attached voice samples)."""
    return CastManager(get_engine().workspace_dir).list_members()


@mcp.tool()
def save_cast_member(
    name: str,
    photo_path: str,
    voice_path: str | None = None,
    voice_ref_text: str = "",
) -> dict[str, Any]:
    """Save a named friend profile (`@Name`) with a reference photo and optional 5-12s voice sample for instant reuse."""
    with contextlib.redirect_stdout(sys.stderr):
        return CastManager(get_engine().workspace_dir).save_member(
            name=name,
            photo_path=photo_path,
            voice_path=voice_path,
            voice_ref_text=voice_ref_text,
        )


@mcp.tool()
def delete_cast_member(cast_id: str) -> dict[str, Any]:
    """Delete a saved friend / cast profile by its ID."""
    ok = CastManager(get_engine().workspace_dir).delete_member(cast_id)
    return {"deleted": ok}


@mcp.tool()
def polish_image_hd(image_path: str, scale: int = 2) -> dict[str, Any]:
    """Run a 1-click 2x HD Lanczos upscale + micro-contrast detail polish on a generated meme image."""
    eng = get_engine()
    raw_p = Path(image_path).expanduser()
    src = raw_p if raw_p.is_absolute() else (eng.workspace_dir / raw_p)
    with contextlib.redirect_stdout(sys.stderr):
        return _polish_image_hd(image_path=src, output_dir=eng.workspace_dir / "generated_images", scale=scale)


@mcp.tool()
def smooth_clip_fps(clip_id: str, target_fps: float = 32.0) -> dict[str, Any]:
    """Motion-interpolate a 16-24fps timeline video clip up to silky smooth 32-48fps with fast-seek keyframes."""
    with contextlib.redirect_stdout(sys.stderr):
        res = get_engine().smooth_clip_fps(clip_id=clip_id, target_fps=target_fps)
    return {"smooth": res, "summary": get_engine().get_summary_dict()}


@mcp.tool()
def clone_friend_voice(
    text: str,
    cast_id: str | None = None,
    ref_audio_path: str | None = None,
    ref_text: str = "",
    speed: float = 1.0,
    add_to_timeline: bool = True,
    start_sec: float = 0.0,
    duck_main_audio: bool = True,
) -> dict[str, Any]:
    """Synthesize custom speech in a friend's cloned voice offline (F5-TTS on GPU) and optionally drop it onto the SFX/BGM timeline track."""
    eng = get_engine()
    use_ref = ref_audio_path
    use_ref_text = ref_text
    label = "Cloned Voice"
    if cast_id:
        m = CastManager(eng.workspace_dir).get_member(cast_id)
        if not m or not m.get("voice_path"):
            raise ValueError(f"Cast member '{cast_id}' has no voice sample attached.")
        use_ref = m["voice_path"]
        use_ref_text = use_ref_text or m.get("voice_ref_text", "")
        label = f"🎙 {m['name']}: {text[:28]}"
    if not use_ref:
        raise ValueError("Provide either `cast_id` or `ref_audio_path`.")

    with contextlib.redirect_stdout(sys.stderr):
        res = clone_voice_offline(
            text=text,
            ref_audio_path=use_ref,
            output_dir=eng.workspace_dir / "cloned_voices",
            ref_text=use_ref_text,
            speed=speed,
        )
        overlay = None
        if add_to_timeline:
            overlay = eng.add_audio_overlay(
                audio_path=res["audio_path"],
                start_sec=start_sec,
                volume=1.15,
                duck_main_audio=duck_main_audio,
                label=label,
            )
    return {
        "voice": res,
        "voice_status": get_voice_cloner_status(),
        "overlay": overlay.model_dump() if overlay else None,
        "summary": eng.get_summary_dict() if add_to_timeline else None,
    }


@mcp.tool()
def extract_clip_end_frame(clip_id: str) -> dict[str, Any]:
    """Extract the exact final frame of a timeline clip into workspace/ref_images for seamless I2V shot chaining."""
    with contextlib.redirect_stdout(sys.stderr):
        return get_engine().extract_clip_end_frame(clip_id)


@mcp.tool()
def list_builtin_sfx() -> list[dict[str, Any]]:
    """List built-in offline meme SFX soundboard IDs (vine_boom, bass_drop, airhorn, record_scratch, dramatic_hit, alert_siren, whoosh, pop_click)."""
    return _list_builtin_sfx()


@mcp.tool()
def add_audio_overlay(
    sfx_id: str | None = None,
    audio_path: str | None = None,
    start_sec: float = 0.0,
    volume: float = 1.0,
    duck_main_audio: bool = False,
    label: str | None = None,
) -> dict[str, Any]:
    """Drop a built-in meme SFX (`sfx_id`) or custom BGM/audio file (`audio_path`) onto the SFX/BGM overlay track at `start_sec`."""
    with contextlib.redirect_stdout(sys.stderr):
        ov = get_engine().add_audio_overlay(
            sfx_id=sfx_id,
            audio_path=audio_path,
            start_sec=start_sec,
            volume=volume,
            duck_main_audio=duck_main_audio,
            label=label,
        )
    return {"overlay": ov.model_dump(), "summary": get_engine().get_summary_dict()}


@mcp.tool()
def remove_audio_overlay(overlay_id: str) -> dict[str, Any]:
    """Remove an SFX or BGM overlay from the timeline audio overlay track."""
    get_engine().remove_audio_overlay(overlay_id)
    return get_engine().get_summary_dict()


@mcp.tool()
def set_meme_layout(
    template: MemeTemplateType = "none",
    top_text: str | None = None,
    bottom_text: str | None = None,
    banner_label: str | None = None,
) -> dict[str, Any]:
    """Apply a native FFmpeg meme layout overlay ('none', 'pov_top_bar', 'impact_top_bottom', 'breaking_news')."""
    cfg = get_engine().set_meme_layout(
        template=template,
        top_text=top_text,
        bottom_text=bottom_text,
        banner_label=banner_label,
    )
    return {"meme_layout": cfg.model_dump(), "summary": get_engine().get_summary_dict()}


@mcp.tool()
def expand_meme_prompt(
    idea: str,
    mode: str = "image",
    has_friend_photo: bool = False,
    model_id: str | None = None,
    style_preset: str | None = None,
    camera_preset: str | None = None,
    has_second_photo: bool = False,
    has_end_frame: bool = False,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Expand a rough 1-line idea into model-tailored positive & negative prompts, caption, and SFX using local Ollama/LM Studio (or smart fallback)."""
    resolved_model = (
        resolve_auto_model(mode, has_friend_photo, has_second_photo)
        if model_id == "auto"
        else model_id
    )
    return expand_meme_prompt_local(
        idea=idea,
        mode=mode,
        has_friend_photo=has_friend_photo,
        endpoint=endpoint,
        model_id=resolved_model,
        style_preset=style_preset,
        camera_preset=camera_preset,
        has_second_photo=has_second_photo,
        has_end_frame=has_end_frame,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
