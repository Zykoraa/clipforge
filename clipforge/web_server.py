"""Hardened FastAPI + WebSocket server for the ClipForge Visual Timeline Editor with live MCP sync."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hmac
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .cast import CastManager
from .civitai import (
    CURATED_CIVITAI_PICKS,
    civitai_download_manager,
    get_civitai_key_status,
    inspect_civitai_url,
    load_civitai_api_key,
    save_civitai_api_key,
    search_civitai_models,
)
from .director import (
    discover_local_llm,
    expand_meme_prompt_local,
    ollama_pull_manager,
    plan_song_from_idea,
    plan_storyboard_beats_local,
)
from .engine import ProjectEngine
from .face_swapper import swap_faces_in_image
from .generator import (
    CAMERA_PRESETS,
    COMFYUI_DIR,
    COMFYUI_URL,
    DEFAULT_NEGATIVE_PROMPT,
    GenerationCanceledError,
    MODEL_SPECS,
    PROMPT_PRESETS,
    detail_faces_in_image,
    download_manager,
    ensure_comfyui_running,
    generate_image_via_comfyui,
    generate_music_via_comfyui,
    generate_video_via_comfyui,
    get_model_availability,
    get_starter_packs,
    interpolate_video_rife_via_comfyui,
    is_comfyui_reachable,
    job_manager,
    list_available_loras,
    list_custom_checkpoints,
    polish_image_hd,
    read_asset_metadata,
    resolve_auto_model,
    save_lora_trigger,
    write_asset_metadata,
)
from .media import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS, VIDEO_EXTENSIONS
from .models import MemeTemplateType, TransitionType
from .platform_utils import detect_gpu_info
from .sfx import ensure_builtin_sfx_file, list_builtin_sfx
from .voice import clone_voice_offline, get_voice_cloner_status, synthesize_speech_offline

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a"}


def _resolve_static_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        cand = meipass / "clipforge" / "static"
        if cand.exists():
            return cand
    return Path(__file__).parent / "static"


STATIC_DIR = _resolve_static_dir()
engine = ProjectEngine()

_voice_status_cache: dict[str, Any] = {"ts": 0.0, "val": None}
_director_status_cache: dict[str, Any] = {"ts": 0.0, "val": None}


def get_cast_manager() -> CastManager:
    return CastManager(engine.workspace_dir)


def _cached_voice_status() -> dict[str, Any]:
    now = time.monotonic()
    if _voice_status_cache["val"] is None or (now - _voice_status_cache["ts"]) > 30.0:
        _voice_status_cache["val"] = get_voice_cloner_status()
        _voice_status_cache["ts"] = now
    return _voice_status_cache["val"]


def _cached_director_status(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    pull_st = ollama_pull_manager.get_state()
    ttl = 2.0 if pull_st.get("status") == "pulling" else 15.0
    if force or _director_status_cache["val"] is None or (now - _director_status_cache["ts"]) > ttl:
        _director_status_cache["val"] = discover_local_llm()
        _director_status_cache["ts"] = now
    else:
        _director_status_cache["val"]["pull"] = pull_st
    return _director_status_cache["val"]

# Cryptographic per-process CSRF/session token (honors pre-shared CLIPFORGE_SESSION_TOKEN for native desktop shell)
_env_tok = os.environ.get("CLIPFORGE_SESSION_TOKEN", "").strip()
SESSION_TOKEN = _env_tok if len(_env_tok) >= 32 else secrets.token_urlsafe(32)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB safety cap per uploaded file
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _is_loopback_host_header(host_header: str, client_host: str | None) -> bool:
    if not host_header:
        return False
    # Strip port (handling IPv6 bracketed form)
    if host_header.startswith("["):
        hostname = host_header.split("]", 1)[0] + "]"
    else:
        hostname = host_header.split(":", 1)[0].lower()
    if hostname in _LOOPBACK_HOSTS:
        return True
    # Permit Starlette in-process TestClient only when transport is genuinely testclient
    if hostname == "testserver" and client_host == "testclient":
        return True
    return False


def _is_allowed_origin(origin_header: str, request_host: str) -> bool:
    if not origin_header:
        return True
    parsed = urlparse(origin_header)
    if parsed.scheme not in ("http", "https"):
        return False
    host_only = (parsed.hostname or "").lower()
    if host_only not in ("127.0.0.1", "localhost", "::1"):
        return False
    # Require origin netloc to match the Host header port when both specify a port
    if parsed.netloc.lower() == request_host.lower():
        return True
    return parsed.hostname in ("127.0.0.1", "localhost") and (
        request_host.lower().startswith("127.0.0.1") or request_host.lower().startswith("localhost")
    )


def _valid_token(provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(provided, SESSION_TOKEN)


def _sanitize_upload_filename(raw_filename: str | None) -> tuple[str, str]:
    """Strip all POSIX/Windows path components, validate media extension, and build a safe filename."""
    candidate = (raw_filename or "").strip()
    # Strip both Windows and POSIX directory traversal components
    base = PureWindowsPath(candidate).name
    base = PurePosixPath(base).name
    if not base or base in (".", ".."):
        raise ValueError("Invalid upload filename.")

    ext = Path(base).suffix.lower()
    if ext not in MEDIA_EXTENSIONS:
        raise ValueError(
            f"Unsupported media file extension '{ext or '(none)'}'. Allowed: {sorted(MEDIA_EXTENSIONS)}"
        )

    stem = _SAFE_STEM_RE.sub("_", Path(base).stem).strip("._-") or "clip"
    stem = stem[:64]
    unique_name = f"{stem}_{uuid.uuid4().hex[:8]}{ext}"
    return unique_name, ext


def _resolve_safe_render_path(raw_path: str | None) -> str | None:
    """Restrict HTTP render output_path strictly inside workspace/renders with .mp4 suffix."""
    if not raw_path or not raw_path.strip():
        return None
    renders_root = engine.renders_dir.resolve()
    p = Path(raw_path.strip())
    target = (renders_root / p).resolve() if not p.is_absolute() else p.resolve()
    try:
        target.relative_to(renders_root)
    except ValueError as exc:
        raise ValueError(
            f"HTTP render output_path must stay inside '{renders_root}'."
        ) from exc
    if target.suffix.lower() != ".mp4":
        target = target.with_suffix(".mp4")
    return str(target)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


ws_manager = ConnectionManager()


async def _watch_project_file() -> None:
    """Poll project.json off the event loop every 200ms so external MCP edits push instantly to the UI."""
    last_mtime = 0.0
    last_version = -1
    while True:
        try:
            if engine.project_file.exists():
                mtime = engine.project_file.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    summary = await asyncio.to_thread(engine.get_summary_dict)
                    ver = summary["project"]["version"]
                    if ver != last_version:
                        last_version = ver
                        await ws_manager.broadcast({"type": "state_updated", "data": summary})
        except Exception:
            pass
        await asyncio.sleep(0.2)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    watcher_task = asyncio.create_task(_watch_project_file())
    try:
        yield
    finally:
        watcher_task.cancel()


app = FastAPI(title="ClipForge Video Editor", lifespan=lifespan)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Defend localhost API against DNS rebinding, cross-origin CSRF, and unauthorized cross-tab access."""
    host_hdr = request.headers.get("host", "")
    client_host = request.client.host if request.client else None
    if not _is_loopback_host_header(host_hdr, client_host):
        return JSONResponse(status_code=403, content={"detail": "Forbidden Host header."})

    origin_hdr = request.headers.get("origin", "")
    if origin_hdr and not _is_allowed_origin(origin_hdr, host_hdr):
        return JSONResponse(status_code=403, content={"detail": "Cross-origin requests are blocked."})

    path = request.url.path
    if path.startswith("/api/") and path != "/api/health":
        token = request.headers.get("x-clipforge-token") or request.query_params.get("token")
        if not _valid_token(token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid ClipForge session token."},
            )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# -------------------------------------------------------------------------
# Request Schemas
# -------------------------------------------------------------------------
class ConfigureRequest(BaseModel):
    name: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    reset: bool = False


class ImportPathsRequest(BaseModel):
    paths: list[str]


class AnalyzeRequest(BaseModel):
    detect_silence: bool = True
    detect_scenes: bool = True
    transcribe: bool = True
    model_size: str = "base"
    language: str | None = None


class AddClipRequest(BaseModel):
    media_id: str
    in_sec: float = 0.0
    out_sec: float | None = None
    position_index: int | None = None
    transition: TransitionType = "cut"
    transition_duration: float = 0.4
    speed: float = 1.0
    volume: float = 1.0
    label: str = ""


class UpdateClipRequest(BaseModel):
    in_sec: float | None = None
    out_sec: float | None = None
    transition: TransitionType | None = None
    transition_duration: float | None = None
    speed: float | None = None
    volume: float | None = None
    muted: bool | None = None
    label: str | None = None


class SplitClipRequest(BaseModel):
    split_at_source_sec: float | None = None
    split_at_timeline_sec: float | None = None


class ReorderRequest(BaseModel):
    clip_ids: list[str]


class SmartStitchRequest(BaseModel):
    media_ids: list[str] | None = None
    order_by: str = "custom"
    trim_silence: bool = True
    split_long_silences: bool = False
    min_silence_sec: float = 0.55
    noise_db: float = -35.0
    padding_sec: float = 0.12
    transition: TransitionType = "crossfade"
    transition_duration: float = 0.35
    auto_subtitle: bool = False
    whisper_model: str = "base"


class AutoSubtitleRequest(BaseModel):
    model_size: str = "base"
    language: str | None = None
    style_preset: str | None = None
    max_words_per_caption: int | None = None
    force_retranscribe: bool = False


class SubtitleStyleRequest(BaseModel):
    preset: str | None = None
    font_name: str | None = None
    font_size: int | None = None
    primary_color: str | None = None
    highlight_color: str | None = None
    outline_color: str | None = None
    back_color: str | None = None
    back_opacity: float | None = None
    bold: bool | None = None
    uppercase: bool | None = None
    word_highlight: bool | None = None
    outline_width: float | None = None
    shadow_depth: float | None = None
    alignment: int | None = None
    margin_v: int | None = None
    max_words_per_caption: int | None = None


class UpsertSubtitleRequest(BaseModel):
    subtitle_id: str | None = None
    start_sec: float
    end_sec: float
    text: str


class RenderRequest(BaseModel):
    output_path: str | None = None
    burn_subtitles: bool = True
    quality: str = "balanced"
    normalize_audio: bool = True
    use_hw_accel: bool = True


class GenerateVideoRequest(BaseModel):
    prompt: str
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    style_preset: str | None = None
    camera_preset: str | None = None
    model: str = "auto"
    intent: str | None = None
    image_path: str | None = None
    end_image_path: str | None = None
    audio_path: str | None = None
    parent_video: str | None = None
    width: int | None = None
    height: int | None = None
    match_photo_aspect: bool = False
    want_audio: bool = False
    fast_draft: bool = False
    auto_enhance: bool = False
    auto_smooth_fps: bool = False
    num_frames: int | None = None
    fps: int | None = None
    steps: int | None = None
    cfg: float | None = None
    seed: int = -1
    loras: list[dict[str, Any]] = []
    add_to_timeline: bool = True
    transition: TransitionType = "crossfade"
    transition_duration: float = 0.35


class GenerateImageRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    style_preset: str | None = None
    model: str = "auto"
    intent: str | None = None
    checkpoint_override: str | None = None
    image_path: str | None = None
    image_path_2: str | None = None
    pose_image_path: str | None = None
    mask_path: str | None = None
    mask_data_url: str | None = None
    parent_image: str | None = None
    width: int | None = None
    height: int | None = None
    match_photo_aspect: bool = False
    auto_enhance: bool = False
    auto_polish: bool = False
    auto_face_swap: bool = False
    steps: int | None = None
    cfg: float | None = None
    denoise: float = 1.0
    seed: int = -1
    batch_size: int = 1
    loras: list[dict[str, Any]] = []
    add_to_timeline: bool = False
    transition: TransitionType = "crossfade"
    transition_duration: float = 0.35


class CivitaiInspectRequest(BaseModel):
    url_or_id: str


class CivitaiInstallRequest(BaseModel):
    version_id: int | None = None
    url_or_id: str | None = None
    download_url: str | None = None
    filename: str | None = None
    name: str | None = None
    model_type: str | None = None
    base_model: str | None = None
    target_subdir: str | None = None
    trained_words: list[str] | None = None
    size_mb: float = 0.0


class CivitaiApiKeyRequest(BaseModel):
    api_key: str = ""


class StitchVaultRequest(BaseModel):
    filenames: list[str]


class PolishImageRequest(BaseModel):
    scale: int = 2
    prefer_ai: bool = True


class FaceDetailRequest(BaseModel):
    prompt: str = "sharp realistic natural facial features, crisp eyes, authentic natural skin texture"
    cast_id: str | None = None
    denoise: float = 0.38
    model: str = "auto"


class LoraTriggerRequest(BaseModel):
    name: str
    trigger: str = ""


class TalkVideoRequest(BaseModel):
    cast_id: str
    text: str
    prompt: str = ""
    style_preset: str | None = None
    voice_preset: str = "auto"
    speed: float = 1.0
    add_to_timeline: bool = True


class FaceSwapRequest(BaseModel):
    cast_ids: list[str] = []
    face_paths: list[str] = []


class PlanSongRequest(BaseModel):
    idea: str
    instrumental: bool = False
    explicit: bool = True
    variations: int = 2
    duration_sec: float = 60.0
    custom_style: str = ""
    custom_lyrics: str = ""
    custom_bpm: int | None = None


class GenerateMusicRequest(BaseModel):
    idea: str = ""
    tags: str = ""
    lyrics: str = ""
    title: str = ""
    instrumental: bool = False
    explicit: bool = True
    strict_lyrics: bool = False
    quality: str = "studio"
    master_audio: bool = True
    variations: int = 2
    duration_sec: float = 60.0
    bpm: int | None = None
    keyscale: str = ""
    language: str = "en"
    steps: int | None = None
    cfg: float = 1.0
    seed: int = -1
    add_to_timeline: bool = False
    volume: float = 0.85


class SpeakTextRequest(BaseModel):
    text: str
    cast_id: str | None = None
    voice_preset: str = "auto"
    speed: float = 1.0
    title: str = ""
    add_to_timeline: bool = False
    start_sec: float = 0.0
    volume: float = 1.15
    duck_main_audio: bool = True


class StoryboardPlanRequest(BaseModel):
    concept: str
    num_beats: int = 3
    style_preset: str | None = None
    has_friend_photo: bool = False
    endpoint: str | None = None
    model_name: str | None = None
    literal_mode: bool = False


class StoryboardRenderRequest(BaseModel):
    beats: list[dict[str, Any]]
    model: str = "auto"
    image_path: str | None = None
    style_preset: str | None = None
    want_audio: bool = False
    fast_draft: bool = False
    num_frames: int = 65
    loras: list[dict[str, Any]] = []
    auto_captions: bool = True
    add_sfx: bool = True
    transition: TransitionType = "crossfade"
    transition_duration: float = 0.3


class DirectorPullRequest(BaseModel):
    model_tag: str = "dolphin-llama3:8b"
    endpoint: str | None = None


class SmoothFpsRequest(BaseModel):
    target_fps: float = 32.0
    prefer_rife: bool = True


class CloneVoiceRequest(BaseModel):
    text: str
    cast_id: str | None = None
    ref_audio_path: str | None = None
    ref_text: str = ""
    speed: float = 1.0
    add_to_timeline: bool = True
    start_sec: float = 0.0
    volume: float = 1.15
    duck_main_audio: bool = True


class AddAudioOverlayRequest(BaseModel):
    sfx_id: str | None = None
    audio_path: str | None = None
    start_sec: float = 0.0
    volume: float = 1.0
    duck_main_audio: bool = False
    label: str | None = None


class UpdateAudioOverlayRequest(BaseModel):
    start_sec: float | None = None
    volume: float | None = None
    duck_main_audio: bool | None = None
    label: str | None = None


class MemeLayoutRequest(BaseModel):
    template: MemeTemplateType | None = None
    top_text: str | None = None
    bottom_text: str | None = None
    banner_label: str | None = None


class DirectorExpandRequest(BaseModel):
    idea: str
    mode: str = "image"
    has_friend_photo: bool = False
    has_second_photo: bool = False
    has_end_frame: bool = False
    model_id: str | None = None
    style_preset: str | None = None
    camera_preset: str | None = None
    endpoint: str | None = None
    model_name: str | None = None
    literal_mode: bool = False


# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------
@app.get("/api/health")
async def api_health() -> dict[str, str]:
    return {"service": "clipforge", "status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    html = index_file.read_text(encoding="utf-8")
    meta_tag = f'<meta name="clipforge-token" content="{SESSION_TOKEN}" />'
    if "<!--CLIPFORGE_TOKEN_META-->" in html:
        html = html.replace("<!--CLIPFORGE_TOKEN_META-->", meta_tag, 1)
    else:
        html = html.replace("</head>", f"  {meta_tag}\n</head>", 1)
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "media-src 'self'; "
                "connect-src 'self' ws://127.0.0.1:* ws://localhost:*"
            ),
        },
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    host_hdr = ws.headers.get("host", "")
    origin_hdr = ws.headers.get("origin", "")
    token = ws.query_params.get("token")
    client_host = ws.client.host if ws.client else None

    if (
        not _is_loopback_host_header(host_hdr, client_host)
        or (origin_hdr and not _is_allowed_origin(origin_hdr, host_hdr))
        or not _valid_token(token)
    ):
        await ws.close(code=1008)
        return

    await ws_manager.connect(ws)
    try:
        summary = await asyncio.to_thread(engine.get_summary_dict)
        await ws.send_json({"type": "state_updated", "data": summary})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


@app.get("/api/state")
async def api_get_state() -> dict[str, Any]:
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/project/configure")
async def api_configure_project(req: ConfigureRequest) -> dict[str, Any]:
    await asyncio.to_thread(
        engine.configure_project,
        req.name,
        req.width,
        req.height,
        req.fps,
        None,
        req.reset,
    )
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/project/undo")
async def api_undo() -> dict[str, Any]:
    await asyncio.to_thread(engine.undo)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/project/redo")
async def api_redo() -> dict[str, Any]:
    await asyncio.to_thread(engine.redo)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/media/import")
async def api_import_media(req: ImportPathsRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(engine.import_media, req.paths)
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/media/upload")
async def api_upload_media(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    uploads_dir = (engine.workspace_dir / "uploads").resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    try:
        for f in files:
            safe_name, _ext = _sanitize_upload_filename(f.filename)
            dest = (uploads_dir / safe_name).resolve()
            # Defense-in-depth containment check
            dest.relative_to(uploads_dir)

            total_bytes = 0
            with open(dest, "wb") as out_fh:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_BYTES:
                        raise ValueError("Uploaded file exceeds 2 GiB limit.")
                    out_fh.write(chunk)
            saved_paths.append(dest)

        await asyncio.to_thread(engine.import_media, [str(p) for p in saved_paths])
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        for p in saved_paths:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/media/{media_id}")
async def api_remove_media(media_id: str) -> dict[str, Any]:
    await asyncio.to_thread(engine.remove_media, media_id)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/media/{media_id}/analyze")
async def api_analyze_media(media_id: str, req: AnalyzeRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.analyze_clip,
            media_id,
            req.detect_silence,
            req.detect_scenes,
            req.transcribe,
            req.model_size,
            req.language,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/media/{media_id}/stream")
async def api_stream_media(media_id: str) -> FileResponse:
    state = await asyncio.to_thread(engine.get_state)
    media = state.get_media(media_id)
    if not media or not Path(media.path).exists():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(media.path, filename=media.filename)


@app.get("/api/media/{media_id}/thumbnail")
async def api_media_thumbnail(media_id: str) -> FileResponse:
    state = await asyncio.to_thread(engine.get_state)
    media = state.get_media(media_id)
    if not media or not media.thumbnail_path or not Path(media.thumbnail_path).exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(media.thumbnail_path, media_type="image/jpeg")


@app.post("/api/timeline/clip")
async def api_add_clip(req: AddClipRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.add_timeline_clip,
            req.media_id,
            req.in_sec,
            req.out_sec,
            req.position_index,
            req.transition,
            req.transition_duration,
            req.speed,
            req.volume,
            req.label,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.patch("/api/timeline/clip/{clip_id}")
async def api_update_clip(clip_id: str, req: UpdateClipRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.update_timeline_clip,
            clip_id,
            req.in_sec,
            req.out_sec,
            req.transition,
            req.transition_duration,
            req.speed,
            req.volume,
            req.muted,
            req.label,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/timeline/clip/{clip_id}/end-frame")
async def api_clip_end_frame(clip_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(engine.extract_clip_end_frame, clip_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/timeline/clip/{clip_id}/smooth-fps")
async def api_clip_smooth_fps(clip_id: str, req: SmoothFpsRequest) -> dict[str, Any]:
    try:
        res = await asyncio.to_thread(engine.smooth_clip_fps, clip_id, req.target_fps, req.prefer_rife)
        return {"smooth": res, "state": await asyncio.to_thread(engine.get_summary_dict)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# -------------------------------------------------------------------------
# Cast / Friend Profiles & Offline Voice Cloning (F5-TTS)
# -------------------------------------------------------------------------
@app.get("/api/cast")
async def api_list_cast() -> dict[str, Any]:
    return {"cast": await asyncio.to_thread(get_cast_manager().list_members)}


@app.post("/api/cast")
async def api_create_cast(
    name: str = Form(...),
    photo: UploadFile = File(...),
    voice: UploadFile | None = File(None),
    voice_ref_text: str = Form(""),
) -> dict[str, Any]:
    try:
        p_bytes = await photo.read()
        if len(p_bytes) > 40 * 1024 * 1024:
            raise ValueError("Photo exceeds 40 MB limit.")
        v_bytes = None
        v_name = None
        if voice is not None and voice.filename:
            v_bytes = await voice.read()
            if len(v_bytes) > 80 * 1024 * 1024:
                raise ValueError("Voice clip exceeds 80 MB limit.")
            v_name = voice.filename
        member = await asyncio.to_thread(
            get_cast_manager().save_member,
            name=name,
            photo_bytes=p_bytes,
            photo_filename=photo.filename,
            voice_bytes=v_bytes,
            voice_filename=v_name,
            voice_ref_text=voice_ref_text,
        )
        return {"member": member, "cast": await asyncio.to_thread(get_cast_manager().list_members)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/cast/{cast_id}/voice")
async def api_attach_cast_voice(
    cast_id: str,
    voice: UploadFile = File(...),
    voice_ref_text: str = Form(""),
) -> dict[str, Any]:
    try:
        v_bytes = await voice.read()
        if len(v_bytes) > 80 * 1024 * 1024:
            raise ValueError("Voice clip exceeds 80 MB limit.")
        member = await asyncio.to_thread(
            get_cast_manager().attach_voice,
            cast_id,
            v_bytes,
            voice.filename or "voice.wav",
            voice_ref_text,
        )
        return {"member": member, "cast": await asyncio.to_thread(get_cast_manager().list_members)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/cast/{cast_id}/photo")
async def api_add_cast_extra_photo(
    cast_id: str,
    photo: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        p_bytes = await photo.read()
        if len(p_bytes) > 50 * 1024 * 1024:
            raise ValueError("Photo exceeds 50 MB limit.")
        member = await asyncio.to_thread(
            get_cast_manager().add_extra_photo,
            cast_id,
            p_bytes,
            photo.filename,
        )
        return {"member": member, "cast": await asyncio.to_thread(get_cast_manager().list_members)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/cast/{cast_id}/photo/{index}")
async def api_get_cast_extra_photo(cast_id: str, index: int) -> FileResponse:
    m = await asyncio.to_thread(get_cast_manager().get_member, cast_id)
    extras = (m or {}).get("extra_photos") or []
    if index < 0 or index >= len(extras) or not Path(extras[index]).exists():
        raise HTTPException(status_code=404, detail="Extra cast photo not found.")
    return FileResponse(extras[index])


@app.delete("/api/cast/{cast_id}/photo/{index}")
async def api_delete_cast_extra_photo(cast_id: str, index: int) -> dict[str, Any]:
    try:
        member = await asyncio.to_thread(get_cast_manager().remove_extra_photo, cast_id, index)
        return {"member": member, "cast": await asyncio.to_thread(get_cast_manager().list_members)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/cast/{cast_id}/photo")
async def api_get_cast_photo(cast_id: str) -> FileResponse:
    m = await asyncio.to_thread(get_cast_manager().get_member, cast_id)
    if not m or not m.get("photo_path") or not Path(m["photo_path"]).exists():
        raise HTTPException(status_code=404, detail="Cast photo not found.")
    return FileResponse(m["photo_path"])


@app.get("/api/cast/{cast_id}/voice")
async def api_get_cast_voice(cast_id: str) -> FileResponse:
    m = await asyncio.to_thread(get_cast_manager().get_member, cast_id)
    if not m or not m.get("voice_path") or not Path(m["voice_path"]).exists():
        raise HTTPException(status_code=404, detail="Cast voice sample not found.")
    return FileResponse(m["voice_path"], media_type="audio/wav")


@app.delete("/api/cast/{cast_id}")
async def api_delete_cast(cast_id: str) -> dict[str, Any]:
    deleted = await asyncio.to_thread(get_cast_manager().delete_member, cast_id)
    return {"deleted": deleted, "cast": await asyncio.to_thread(get_cast_manager().list_members)}


@app.get("/api/voice/status")
async def api_voice_status() -> dict[str, Any]:
    return await asyncio.to_thread(_cached_voice_status)


@app.get("/api/voice/file/{filename}")
async def api_get_cloned_voice_file(filename: str) -> FileResponse:
    target = _resolve_safe_dir_file(engine.workspace_dir / "cloned_voices", filename, {".wav", ".mp3"})
    return FileResponse(str(target), media_type="audio/wav", filename=target.name)


@app.post("/api/voice/clone")
async def api_clone_voice(req: CloneVoiceRequest) -> dict[str, Any]:
    clean_text = (req.text or "").strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Dialogue text cannot be empty.")

    ref_audio = req.ref_audio_path
    ref_text = req.ref_text
    speaker_label = "Cloned Voice"
    if req.cast_id:
        member = await asyncio.to_thread(get_cast_manager().get_member, req.cast_id)
        if not member:
            raise HTTPException(status_code=404, detail="Cast member not found.")
        if not member.get("voice_path"):
            raise HTTPException(status_code=400, detail=f"Attach a 5-12s voice sample to '{member['name']}' first.")
        ref_audio = member["voice_path"]
        ref_text = ref_text or member.get("voice_ref_text", "")
        speaker_label = f"🎙 {member['name']}: {clean_text[:28]}"

    if not ref_audio:
        raise HTTPException(status_code=400, detail="Select a Cast member with voice audio or provide ref_audio_path.")

    job = job_manager.create(kind="voice", model="f5_tts", prompt=clean_text)

    async def _run_voice_job() -> None:
        gpu_label = detect_gpu_info().get("short_name") or "local GPU"
        job_manager.update(job.id, status="running", progress_pct=20, message=f"Cloning voice on {gpu_label} (F5-TTS)...")
        try:
            out_dir = engine.workspace_dir / "cloned_voices"
            res = await asyncio.to_thread(
                clone_voice_offline,
                text=clean_text,
                ref_audio_path=ref_audio,
                output_dir=out_dir,
                ref_text=ref_text,
                speed=req.speed,
            )
            overlay_id = None
            if req.add_to_timeline:
                ov = await asyncio.to_thread(
                    engine.add_audio_overlay,
                    None,
                    res["audio_path"],
                    req.start_sec,
                    req.volume,
                    req.duck_main_audio,
                    speaker_label,
                )
                overlay_id = ov.id
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=f"Cloned {res['duration_sec']}s voice in {res['generation_time_sec']}s",
                result={**res, "audio_url": f"/api/voice/file/{res['filename']}", "overlay_id": overlay_id},
            )
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_voice_job())
    return {"job_id": job.id, "status": "queued", "jobs": job_manager.list_jobs()}


@app.post("/api/voice/speak")
async def api_speak_text(req: SpeakTextRequest) -> dict[str, Any]:
    """Generate offline speech/voiceover using either a friend's cloned voice (F5-TTS) or instant built-in offline voices."""
    clean_text = (req.text or "").strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Speech text cannot be empty.")

    member = None
    if req.cast_id:
        member = await asyncio.to_thread(get_cast_manager().get_member, req.cast_id)
        if not member:
            raise HTTPException(status_code=404, detail="Cast member not found.")

    use_clone = bool(member and member.get("voice_path"))
    speaker_name = member["name"] if member else (req.voice_preset or "Narrator")
    job_model = "f5_tts" if use_clone else "offline_tts"
    job = job_manager.create(kind="audio", model=job_model, prompt=f"🎙 {speaker_name}: {clean_text[:60]}")

    async def _run_speak_job() -> None:
        out_dir = engine.workspace_dir / "generated_audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            if use_clone and member:
                job_manager.update(job.id, status="running", progress_pct=25, message=f"Cloning {member['name']}'s voice (F5-TTS)...")
                res = await asyncio.to_thread(
                    clone_voice_offline,
                    text=clean_text,
                    ref_audio_path=member["voice_path"],
                    output_dir=out_dir,
                    ref_text=member.get("voice_ref_text", ""),
                    speed=req.speed,
                )
            else:
                job_manager.update(job.id, status="running", progress_pct=35, message="Synthesizing offline voiceover...")
                res = await asyncio.to_thread(
                    synthesize_speech_offline,
                    text=clean_text,
                    output_dir=out_dir,
                    voice_preset=req.voice_preset,
                    speed=req.speed,
                )

            out_file = Path(res["audio_path"])
            clean_title = (req.title or "").strip() or f"{speaker_name}: {clean_text[:32]}"
            write_asset_metadata(
                out_file,
                {
                    "kind": "audio",
                    "subtype": "speech",
                    "model": res.get("engine", job_model),
                    "title": clean_title,
                    "text": clean_text,
                    "speaker": speaker_name,
                    "voice_preset": req.voice_preset,
                    "speed": req.speed,
                    "duration_sec": res.get("duration_sec", 0.0),
                    "generation_time_sec": res.get("generation_time_sec", 0.0),
                },
            )
            overlay_id = None
            if req.add_to_timeline:
                ov = await asyncio.to_thread(
                    engine.add_audio_overlay,
                    None,
                    str(out_file),
                    req.start_sec,
                    req.volume,
                    req.duck_main_audio,
                    f"🎙 {clean_title[:28]}",
                )
                overlay_id = ov.id
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=f"Speech ready ({res['duration_sec']}s)",
                result={
                    **res,
                    "title": clean_title,
                    "audio_url": f"/api/generate/audio/{out_file.name}",
                    "overlay_id": overlay_id,
                },
            )
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_speak_job())
    return {"job_id": job.id, "status": "queued", "jobs": job_manager.list_jobs()}


@app.post("/api/voice/talk-video")
async def api_talking_friend_video(req: TalkVideoRequest) -> dict[str, Any]:
    """1-click offline pipeline: clone friend's voice (or built-in offline TTS) -> animate lip-synced talking video."""
    clean_text = (req.text or "").strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Dialogue text cannot be empty.")
    member = await asyncio.to_thread(get_cast_manager().get_member, req.cast_id)
    if not member:
        raise HTTPException(status_code=404, detail="Cast member not found.")

    has_cloned_voice = bool(member.get("voice_path") and Path(member["voice_path"]).exists())
    job = job_manager.create(kind="video", model="talk_sync", prompt=f"🎙 {member['name']}: {clean_text}")

    async def _run_talk_job() -> None:
        gpu_label = detect_gpu_info().get("short_name") or "local GPU"
        if has_cloned_voice:
            job_manager.update(job.id, status="running", progress_pct=10, message=f"Step 1/2: Cloning {member['name']}'s voice on {gpu_label}...")
        else:
            job_manager.update(job.id, status="running", progress_pct=10, message=f"Step 1/2: Synthesizing offline voice for {member['name']}...")
        try:
            if has_cloned_voice:
                voice_res = await asyncio.to_thread(
                    clone_voice_offline,
                    text=clean_text,
                    ref_audio_path=member["voice_path"],
                    output_dir=engine.workspace_dir / "cloned_voices",
                    ref_text=member.get("voice_ref_text", ""),
                    speed=req.speed,
                )
            else:
                voice_res = await asyncio.to_thread(
                    synthesize_speech_offline,
                    text=clean_text,
                    output_dir=engine.workspace_dir / "cloned_voices",
                    voice_preset=req.voice_preset,
                    speed=req.speed,
                )
            wav_path = Path(voice_res["audio_path"])
            dur_sec = max(1.5, float(voice_res.get("duration_sec") or 3.5))

            avail = await asyncio.to_thread(get_model_availability)
            s2v_ready = bool(avail.get("wan22_s2v", {}).get("ready"))
            talk_prompt = (req.prompt or "").strip() or (
                f"Natural expressive talking head shot of this person speaking directly to camera, "
                f"realistic natural lip sync, subtle head nods, authentic lighting"
            )

            def _prog(msg: str, pct: int | None = None) -> None:
                p = 35 + int(((pct or 0) / 100.0) * 60)
                job_manager.update(job.id, progress_pct=min(96, p), message=f"Step 2/2: {msg}")

            def _prev(durl: str) -> None:
                job_manager.update(job.id, preview_data_url=durl)

            def _pid(pid: str) -> None:
                job_manager.update(job.id, prompt_id=pid)

            gen_dir = engine.workspace_dir / "generated"
            if s2v_ready:
                frames = max(25, min(121, int(round(dur_sec * 16.0)) + 5))
                vid_res = await asyncio.to_thread(
                    generate_video_via_comfyui,
                    prompt=talk_prompt,
                    output_dir=gen_dir,
                    model="wan22_s2v",
                    image_path=member["photo_path"],
                    audio_path=str(wav_path),
                    style_preset=req.style_preset,
                    match_photo_aspect=True,
                    num_frames=frames,
                    on_progress=_prog,
                    on_preview=_prev,
                    on_prompt_id=_pid,
                    cancel_event=job.cancel_event,
                )
                final_video_path = Path(vid_res["video_path"])
                engine_used = "wan22_s2v_lipsync"
            else:
                # Smart fallback: animate with Wan 2.2 I2V / 5B and mux exact cloned F5-TTS voice cleanly!
                fallback_model = "wan22_i2v" if avail.get("wan22_i2v", {}).get("ready") else "wan22_5b"
                fps_fb = 16 if fallback_model == "wan22_i2v" else 24
                frames_fb = max(41, min(113, int(round(dur_sec * fps_fb)) + 5))
                vid_res = await asyncio.to_thread(
                    generate_video_via_comfyui,
                    prompt=talk_prompt,
                    output_dir=gen_dir,
                    model=fallback_model,  # type: ignore[arg-type]
                    image_path=member["photo_path"],
                    style_preset=req.style_preset,
                    match_photo_aspect=True,
                    num_frames=frames_fb,
                    on_progress=_prog,
                    on_preview=_prev,
                    on_prompt_id=_pid,
                    cancel_event=job.cancel_event,
                )
                mux_out = gen_dir / f"talk_{member['name'].lower()[:12]}_{uuid.uuid4().hex[:6]}.mp4"
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-hide_banner",
                        "-i", vid_res["video_path"],
                        "-i", str(wav_path),
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart",
                        str(mux_out),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                final_video_path = mux_out
                engine_used = f"{fallback_model}+f5tts_mux"

            imported = await asyncio.to_thread(engine.import_media, [str(final_video_path)])
            media_item = imported[0]
            if req.add_to_timeline:
                cur_tl = (await asyncio.to_thread(engine.get_state)).timeline
                await asyncio.to_thread(
                    engine.add_timeline_clip,
                    media_item.id,
                    0.0,
                    None,
                    None,
                    "crossfade" if cur_tl else "cut",
                    0.35 if cur_tl else 0.0,
                    1.0,
                    1.0,
                    f"🎙 {member['name']}: {clean_text[:22]}",
                )
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=f"Talking clip ready ({engine_used})",
                result={
                    "video_path": str(final_video_path.resolve()),
                    "filename": final_video_path.name,
                    "audio_path": str(wav_path),
                    "engine": engine_used,
                    "media_id": media_item.id,
                },
            )
        except GenerationCanceledError:
            job_manager.update(job.id, status="canceled", message="Canceled by user")
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_talk_job())
    return {"job_id": job.id, "status": "queued", "jobs": job_manager.list_jobs()}


@app.get("/api/sfx/catalog")
async def api_sfx_catalog() -> dict[str, Any]:
    return {"sfx": list_builtin_sfx()}


@app.get("/api/sfx/preview/{sfx_id}")
async def api_sfx_preview(sfx_id: str) -> FileResponse:
    try:
        wav_path, _spec = await asyncio.to_thread(ensure_builtin_sfx_file, sfx_id, engine.sfx_dir)
        return FileResponse(str(wav_path), media_type="audio/wav", filename=wav_path.name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/audio-overlays")
async def api_add_audio_overlay(req: AddAudioOverlayRequest) -> dict[str, Any]:
    try:
        ov = await asyncio.to_thread(
            engine.add_audio_overlay,
            req.sfx_id,
            req.audio_path,
            req.start_sec,
            req.volume,
            req.duck_main_audio,
            req.label,
        )
        return {"overlay": ov.model_dump(), "state": await asyncio.to_thread(engine.get_summary_dict)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.patch("/api/audio-overlays/{overlay_id}")
async def api_update_audio_overlay(overlay_id: str, req: UpdateAudioOverlayRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.update_audio_overlay,
            overlay_id,
            req.start_sec,
            req.volume,
            req.duck_main_audio,
            req.label,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/audio-overlays/{overlay_id}")
async def api_remove_audio_overlay(overlay_id: str) -> dict[str, Any]:
    await asyncio.to_thread(engine.remove_audio_overlay, overlay_id)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/meme-layout")
async def api_set_meme_layout(req: MemeLayoutRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.set_meme_layout,
            req.template,
            req.top_text,
            req.bottom_text,
            req.banner_label,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/director/status")
async def api_director_status(endpoint: str | None = None) -> dict[str, Any]:
    if endpoint:
        return await asyncio.to_thread(discover_local_llm, endpoint)
    return await asyncio.to_thread(_cached_director_status, True)


@app.post("/api/director/pull")
async def api_director_pull(req: DirectorPullRequest) -> dict[str, Any]:
    try:
        st = await asyncio.to_thread(ollama_pull_manager.start_pull, req.model_tag, req.endpoint)
        return {"pull": st}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/director/storyboard")
async def api_director_storyboard(req: StoryboardPlanRequest) -> dict[str, Any]:
    try:
        has_p1 = req.has_friend_photo
        if "@" in (req.concept or ""):
            _, m_img1, _, matched = await asyncio.to_thread(
                get_cast_manager().resolve_prompt_mentions,
                req.concept,
                "__attached__" if has_p1 else None,
                None,
            )
            if matched:
                has_p1 = bool(m_img1)
        return await asyncio.to_thread(
            plan_storyboard_beats_local,
            req.concept,
            req.num_beats,
            req.style_preset,
            has_p1,
            req.endpoint,
            req.model_name,
            req.literal_mode,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/director/expand")
async def api_director_expand(req: DirectorExpandRequest) -> dict[str, Any]:
    try:
        # Detect @FriendName cast mentions so the LLM director knows reference photo(s) will be attached
        has_p1 = req.has_friend_photo
        has_p2 = req.has_second_photo
        if "@" in (req.idea or ""):
            _, m_img1, m_img2, matched = await asyncio.to_thread(
                get_cast_manager().resolve_prompt_mentions,
                req.idea,
                "__attached__" if has_p1 else None,
                "__attached__" if has_p2 else None,
            )
            if matched:
                has_p1 = bool(m_img1)
                has_p2 = bool(m_img2)

        eff_model_id = req.model_id
        if eff_model_id == "auto":
            eff_model_id = await asyncio.to_thread(resolve_auto_model, req.mode, has_p1, has_p2)

        return await asyncio.to_thread(
            expand_meme_prompt_local,
            req.idea,
            req.mode,
            has_p1,
            req.endpoint,
            req.model_name,
            eff_model_id,
            req.style_preset,
            req.camera_preset,
            has_p2,
            req.has_end_frame,
            req.literal_mode,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/timeline/clip/{clip_id}/split")
async def api_split_clip(clip_id: str, req: SplitClipRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.split_timeline_clip,
            clip_id,
            req.split_at_source_sec,
            req.split_at_timeline_sec,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/timeline/clip/{clip_id}")
async def api_delete_clip(clip_id: str) -> dict[str, Any]:
    await asyncio.to_thread(engine.remove_timeline_clip, clip_id)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/timeline/reorder")
async def api_reorder_clips(req: ReorderRequest) -> dict[str, Any]:
    await asyncio.to_thread(engine.reorder_timeline_clips, req.clip_ids)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/timeline/clear")
async def api_clear_timeline() -> dict[str, Any]:
    await asyncio.to_thread(engine.clear_timeline)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/timeline/smart-stitch")
async def api_smart_stitch(req: SmartStitchRequest) -> dict[str, Any]:
    try:
        res = await asyncio.to_thread(
            engine.smart_stitch,
            req.media_ids,
            req.order_by,
            req.trim_silence,
            req.split_long_silences,
            req.min_silence_sec,
            req.noise_db,
            req.padding_sec,
            req.transition,
            req.transition_duration,
            req.auto_subtitle,
            req.whisper_model,
        )
        return {"stitch_report": res, "state": await asyncio.to_thread(engine.get_summary_dict)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/subtitles/auto")
async def api_auto_subtitles(req: AutoSubtitleRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.auto_subtitle_timeline,
            req.model_size,
            req.language,
            req.style_preset,
            req.max_words_per_caption,
            req.force_retranscribe,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/subtitles/style")
async def api_set_subtitle_style(req: SubtitleStyleRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(engine.set_subtitle_style, **req.model_dump(exclude_none=True))
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/subtitles/entry")
async def api_upsert_subtitle(req: UpsertSubtitleRequest) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            engine.upsert_subtitle,
            req.start_sec,
            req.end_sec,
            req.text,
            req.subtitle_id,
        )
        return await asyncio.to_thread(engine.get_summary_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/subtitles/entry/{subtitle_id}")
async def api_remove_subtitle(subtitle_id: str) -> dict[str, Any]:
    await asyncio.to_thread(engine.remove_subtitle, subtitle_id)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/subtitles/clear")
async def api_clear_subtitles() -> dict[str, Any]:
    await asyncio.to_thread(engine.clear_subtitles)
    return await asyncio.to_thread(engine.get_summary_dict)


@app.post("/api/render")
async def api_render(req: RenderRequest) -> dict[str, Any]:
    try:
        safe_out = _resolve_safe_render_path(req.output_path)
        res = await asyncio.to_thread(
            engine.render_video,
            safe_out,
            req.burn_subtitles,
            req.quality,
            req.normalize_audio,
            req.use_hw_accel,
        )
        return {"render": res, "state": await asyncio.to_thread(engine.get_summary_dict)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/render/download")
async def api_download_last_render() -> FileResponse:
    state = await asyncio.to_thread(engine.get_state)
    if not state.last_render_path or not Path(state.last_render_path).exists():
        raise HTTPException(status_code=404, detail="No rendered video available yet.")
    p = Path(state.last_render_path)
    return FileResponse(str(p), filename=p.name, media_type="video/mp4")


# -------------------------------------------------------------------------
# Offline AI Video & Image Generation (ComfyUI + Resumable Model Manager)
# -------------------------------------------------------------------------
def _sanitize_ref_image_filename(raw_filename: str | None) -> str:
    candidate = (raw_filename or "").strip()
    base = PurePosixPath(PureWindowsPath(candidate).name).name
    if not base or base in (".", ".."):
        raise ValueError("Invalid reference image filename.")
    ext = Path(base).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image extension '{ext}'. Allowed: {sorted(IMAGE_EXTENSIONS)}")
    stem = _SAFE_STEM_RE.sub("_", Path(base).stem).strip("._-") or "ref"
    return f"{stem[:48]}_{uuid.uuid4().hex[:8]}{ext}"


def _resolve_safe_dir_file(root_dir: Path, filename: str, allowed_exts: set[str]) -> Path:
    """Strictly contain filename reads inside `root_dir` with zero traversal."""
    clean = (filename or "").strip()
    base = PurePosixPath(PureWindowsPath(clean).name).name
    if not base or base != clean or base in (".", "..") or "/" in clean or "\\" in clean:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if Path(base).suffix.lower() not in allowed_exts:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    root_resolved = root_dir.resolve()
    target = (root_resolved / base).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path outside allowed directory.") from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return target


def _list_image_gallery(limit: int = 36) -> list[dict[str, Any]]:
    gal_dir = engine.workspace_dir / "generated_images"
    if not gal_dir.exists():
        return []
    files = [p for p in gal_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "filename": p.name,
            "image_path": str(p.resolve()),
            "url": f"/api/generate/image/{p.name}",
            "size_bytes": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "meta": read_asset_metadata(p),
        }
        for p in files[:limit]
    ]


def _list_ref_images(limit: int = 16) -> list[dict[str, Any]]:
    refs_dir = engine.workspace_dir / "ref_images"
    if not refs_dir.exists():
        return []
    files = [p for p in refs_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "filename": p.name,
            "image_path": str(p.resolve()),
            "url": f"/api/generate/ref/{p.name}",
            "mtime": p.stat().st_mtime,
        }
        for p in files[:limit]
    ]


def _list_video_gallery(limit: int = 36) -> list[dict[str, Any]]:
    vid_dir = engine.workspace_dir / "generated"
    if not vid_dir.exists():
        return []
    files = [p for p in vid_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "kind": "video",
            "filename": p.name,
            "video_path": str(p.resolve()),
            "url": f"/api/generate/video/{p.name}",
            "size_bytes": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "meta": read_asset_metadata(p),
        }
        for p in files[:limit]
    ]


def _list_audio_gallery(limit: int = 36) -> list[dict[str, Any]]:
    aud_dir = engine.workspace_dir / "generated_audio"
    if not aud_dir.exists():
        return []
    files = [p for p in aud_dir.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "kind": "audio",
            "filename": p.name,
            "audio_path": str(p.resolve()),
            "url": f"/api/generate/audio/{p.name}",
            "size_bytes": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "meta": read_asset_metadata(p),
        }
        for p in files[:limit]
    ]


def _lora_triggers_file() -> Path:
    return engine.workspace_dir / "lora_triggers.json"


@app.get("/api/loras")
async def api_list_loras() -> dict[str, Any]:
    return {"loras": await asyncio.to_thread(list_available_loras, COMFYUI_DIR, _lora_triggers_file())}


@app.get("/api/checkpoints")
async def api_list_checkpoints() -> dict[str, Any]:
    return {"checkpoints": await asyncio.to_thread(list_custom_checkpoints, COMFYUI_DIR)}


@app.post("/api/starter-pack/{pack_id}/download")
async def api_download_starter_pack(pack_id: str) -> dict[str, Any]:
    packs = await asyncio.to_thread(get_starter_packs, COMFYUI_DIR)
    pack = next((p for p in packs if p["id"] == pack_id), None)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Unknown starter pack '{pack_id}'.")
    avail = await asyncio.to_thread(get_model_availability)
    started: list[str] = []
    for mid in pack["model_ids"]:
        if mid in MODEL_SPECS and not avail.get(mid, {}).get("ready"):
            await asyncio.to_thread(download_manager.start_download, mid)
            started.append(mid)
    return {
        "pack_id": pack_id,
        "started_models": started,
        "starter_packs": await asyncio.to_thread(get_starter_packs, COMFYUI_DIR),
        "models": await asyncio.to_thread(get_model_availability),
    }


@app.get("/api/civitai/status")
async def api_civitai_status() -> dict[str, Any]:
    key_st = await asyncio.to_thread(get_civitai_key_status, engine.workspace_dir)
    return {
        **key_st,
        "downloads": civitai_download_manager.list_downloads(),
        "curated": CURATED_CIVITAI_PICKS,
    }


@app.post("/api/civitai/api-key")
async def api_save_civitai_key(req: CivitaiApiKeyRequest) -> dict[str, Any]:
    return await asyncio.to_thread(save_civitai_api_key, engine.workspace_dir, req.api_key)


@app.get("/api/civitai/search")
async def api_civitai_search(
    q: str = "",
    model_type: str | None = None,
    base_model: str | None = None,
    sort: str = "Most Downloaded",
    limit: int = 16,
    nsfw: bool = True,
) -> dict[str, Any]:
    try:
        key = await asyncio.to_thread(load_civitai_api_key, engine.workspace_dir)
        items = await asyncio.to_thread(
            search_civitai_models, q, model_type, base_model, sort, limit, nsfw, key
        )
        return {"items": items, "curated": CURATED_CIVITAI_PICKS}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CivitAI search failed: {e}") from e


@app.post("/api/civitai/inspect")
async def api_civitai_inspect(req: CivitaiInspectRequest) -> dict[str, Any]:
    try:
        key = await asyncio.to_thread(load_civitai_api_key, engine.workspace_dir)
        item = await asyncio.to_thread(inspect_civitai_url, req.url_or_id, key)
        return {"item": item}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/civitai/install")
async def api_civitai_install(req: CivitaiInstallRequest) -> dict[str, Any]:
    try:
        key = await asyncio.to_thread(load_civitai_api_key, engine.workspace_dir)
        dl = await asyncio.to_thread(
            civitai_download_manager.start_install,
            version_id=req.version_id,
            url_or_id=req.url_or_id,
            download_url=req.download_url,
            filename=req.filename,
            name=req.name,
            model_type=req.model_type,
            base_model=req.base_model,
            target_subdir=req.target_subdir,
            trained_words=req.trained_words,
            size_mb=req.size_mb,
            api_key=key,
            triggers_file=_lora_triggers_file(),
        )
        return {"download": dl, "downloads": civitai_download_manager.list_downloads()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/civitai/cancel/{download_id}")
async def api_civitai_cancel(download_id: str) -> dict[str, Any]:
    ok = await asyncio.to_thread(civitai_download_manager.cancel, download_id)
    return {"download_id": download_id, "canceled": ok, "downloads": civitai_download_manager.list_downloads()}


@app.post("/api/loras/trigger")
async def api_save_lora_trigger(req: LoraTriggerRequest) -> dict[str, Any]:
    await asyncio.to_thread(save_lora_trigger, _lora_triggers_file(), req.name, req.trigger)
    return {"loras": await asyncio.to_thread(list_available_loras, COMFYUI_DIR, _lora_triggers_file())}


@app.post("/api/loras/upload")
async def api_upload_lora(file: UploadFile = File(...)) -> dict[str, Any]:
    raw_name = (file.filename or "").strip()
    base = PurePosixPath(PureWindowsPath(raw_name).name).name
    ext = Path(base).suffix.lower()
    if not base or ext not in (".safetensors", ".pt"):
        raise HTTPException(status_code=400, detail="Only .safetensors or .pt LoRA files are supported.")
    safe_stem = _SAFE_STEM_RE.sub("_", Path(base).stem).strip("._-") or "custom_lora"
    loras_dir = (COMFYUI_DIR / "models" / "loras").resolve()
    loras_dir.mkdir(parents=True, exist_ok=True)
    dest = (loras_dir / f"{safe_stem[:80]}{ext}").resolve()
    try:
        dest.relative_to(loras_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid LoRA path.") from exc
    data = await file.read()
    if len(data) > 2 * 1024 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="LoRA exceeds 2 GiB safety cap.")
    dest.write_bytes(data)
    return {
        "filename": dest.name,
        "loras": await asyncio.to_thread(list_available_loras, COMFYUI_DIR, _lora_triggers_file()),
    }


@app.get("/api/generate/status")
async def api_generate_status() -> dict[str, Any]:
    running = await asyncio.to_thread(is_comfyui_reachable)
    models = await asyncio.to_thread(get_model_availability)
    gallery = await asyncio.to_thread(_list_image_gallery)
    videos = await asyncio.to_thread(_list_video_gallery)
    audio_tracks = await asyncio.to_thread(_list_audio_gallery)
    ref_images = await asyncio.to_thread(_list_ref_images)
    gpu = await asyncio.to_thread(detect_gpu_info)
    cast = await asyncio.to_thread(get_cast_manager().list_members)
    voice_st = await asyncio.to_thread(_cached_voice_status)
    director_st = await asyncio.to_thread(_cached_director_status, False)
    loras = await asyncio.to_thread(list_available_loras, COMFYUI_DIR, _lora_triggers_file())
    checkpoints = await asyncio.to_thread(list_custom_checkpoints, COMFYUI_DIR)
    starter_packs = await asyncio.to_thread(get_starter_packs, COMFYUI_DIR)
    civitai_key = await asyncio.to_thread(get_civitai_key_status, engine.workspace_dir)
    return {
        "comfyui_url": COMFYUI_URL,
        "comfyui_dir": str(COMFYUI_DIR),
        "comfyui_running": running,
        "gpu_name": gpu.get("short_name") or "Local GPU",
        "gpu_full_name": gpu.get("name") or "",
        "gpu_vram_mb": gpu.get("vram_mb") or 0,
        "has_nvidia": bool(gpu.get("has_nvidia")),
        "platform": sys.platform,
        "models": models,
        "jobs": job_manager.list_jobs(),
        "presets": PROMPT_PRESETS,
        "camera_presets": CAMERA_PRESETS,
        "gallery": gallery,
        "videos": videos,
        "audio_tracks": audio_tracks,
        "ref_images": ref_images,
        "cast": cast,
        "voice": voice_st,
        "director": director_st,
        "loras": loras,
        "checkpoints": checkpoints,
        "starter_packs": starter_packs,
        "civitai": {
            **civitai_key,
            "downloads": civitai_download_manager.list_downloads(),
            "curated": CURATED_CIVITAI_PICKS,
        },
    }


@app.post("/api/generate/jobs/{job_id}/cancel")
async def api_cancel_generation_job(job_id: str) -> dict[str, Any]:
    canceled = await asyncio.to_thread(job_manager.cancel, job_id)
    return {"job_id": job_id, "canceled": canceled, "jobs": job_manager.list_jobs()}


@app.post("/api/generate/image/{filename}/polish")
async def api_polish_generated_image(
    filename: str,
    req: PolishImageRequest | None = None,
) -> dict[str, Any]:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated_images", filename, IMAGE_EXTENSIONS)
    scale = req.scale if req else 2
    prefer_ai = req.prefer_ai if req else True
    try:
        res = await asyncio.to_thread(
            polish_image_hd,
            target,
            engine.workspace_dir / "generated_images",
            scale,
            prefer_ai,
        )
        return {
            **res,
            "url": f"/api/generate/image/{res['filename']}",
            "gallery": await asyncio.to_thread(_list_image_gallery),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/generate/image/{filename}/detail-faces")
async def api_detail_faces_image(filename: str, req: FaceDetailRequest | None = None) -> dict[str, Any]:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated_images", filename, IMAGE_EXTENSIONS)
    body = req or FaceDetailRequest()
    ref_face: str | None = None
    if body.cast_id:
        m = await asyncio.to_thread(get_cast_manager().get_member, body.cast_id)
        if m and m.get("photo_path"):
            ref_face = m["photo_path"]

    job = job_manager.create(kind="image", model="face_detailer", prompt=f"Fix Faces: {filename}")

    async def _run_face_job() -> None:
        job_manager.update(job.id, status="running", progress_pct=5, message="Detecting faces...")
        try:
            def _prog(msg: str, pct: int | None = None) -> None:
                upd: dict[str, Any] = {"message": msg}
                if pct is not None:
                    upd["progress_pct"] = pct
                job_manager.update(job.id, **upd)

            res = await asyncio.to_thread(
                detail_faces_in_image,
                target,
                engine.workspace_dir / "generated_images",
                body.prompt,
                ref_face,
                body.denoise,
                body.model,
                COMFYUI_URL,
                COMFYUI_DIR,
                _prog,
            )
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=f"Refined {res['faces_refined']} face(s) ({res['filename']})",
                result={**res, "preview_url": f"/api/generate/image/{res['filename']}"},
            )
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_face_job())
    return {"job_id": job.id, "status": "queued", "jobs": job_manager.list_jobs()}


@app.post("/api/generate/image/{filename}/swap-faces")
async def api_swap_faces_image(filename: str, req: FaceSwapRequest) -> dict[str, Any]:
    """1-click pure-ONNX Face Lock: swap 1-2 real friend faces onto any generated image."""
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated_images", filename, IMAGE_EXTENSIONS)
    face_paths: list[str] = []
    cm = get_cast_manager()
    for cid in (req.cast_ids or [])[:2]:
        m = await asyncio.to_thread(cm.get_member, cid)
        if m and m.get("photo_path") and Path(m["photo_path"]).exists():
            face_paths.append(m["photo_path"])
    for fp in (req.face_paths or [])[:2]:
        if fp and Path(fp).exists() and len(face_paths) < 2:
            face_paths.append(fp)
    if not face_paths:
        raise HTTPException(status_code=400, detail="Select 1 or 2 friends (or face photos) to lock onto this image.")

    try:
        res = await asyncio.to_thread(
            swap_faces_in_image,
            target,
            face_paths,
            engine.workspace_dir / "generated_images",
            COMFYUI_DIR,
        )
        orig_meta = read_asset_metadata(target) or {}
        write_asset_metadata(
            Path(res["image_path"]),
            {
                **orig_meta,
                "parent_image": target.name,
                "face_swapped": True,
                "faces_swapped": res["faces_swapped"],
            },
        )
        return {
            **res,
            "url": f"/api/generate/image/{res['filename']}",
            "gallery": await asyncio.to_thread(_list_image_gallery),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/generate/audio/{filename}")
async def api_get_generated_audio(filename: str) -> FileResponse:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated_audio", filename, AUDIO_EXTENSIONS)
    ext = target.suffix.lower()
    mt = "audio/mpeg" if ext == ".mp3" else ("audio/wav" if ext == ".wav" else "audio/flac")
    return FileResponse(str(target), media_type=mt, filename=target.name)


@app.delete("/api/generate/audio/{filename}")
async def api_delete_generated_audio(filename: str) -> dict[str, Any]:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated_audio", filename, AUDIO_EXTENSIONS)
    target.unlink(missing_ok=True)
    target.with_suffix(target.suffix + ".meta.json").unlink(missing_ok=True)
    return {"deleted": filename, "audio_tracks": await asyncio.to_thread(_list_audio_gallery)}


@app.post("/api/music/plan")
async def api_plan_song(req: PlanSongRequest) -> dict[str, Any]:
    """Turn a rough 1-line song idea into ready-to-edit title, style tags, BPM, and structured lyrics (Suno-style)."""
    if not (req.idea or "").strip() and not (req.custom_style or "").strip() and not (req.custom_lyrics or "").strip():
        raise HTTPException(status_code=400, detail="Enter a rough song idea first.")
    return await asyncio.to_thread(
        plan_song_from_idea,
        idea=req.idea,
        instrumental=req.instrumental,
        explicit=req.explicit,
        variations=req.variations,
        duration_sec=req.duration_sec,
        custom_style=req.custom_style,
        custom_lyrics=req.custom_lyrics,
        custom_bpm=req.custom_bpm,
    )


@app.post("/api/generate/music")
async def api_generate_music(req: GenerateMusicRequest) -> dict[str, Any]:
    """Suno-style offline music generator: pass EITHER a rough 1-line `idea` OR custom `tags`/`lyrics` and get 1-4 distinct full songs."""
    idea_clean = (req.idea or "").strip()
    tags_clean = (req.tags or "").strip()
    lyrics_clean = (req.lyrics or "").strip()
    if not idea_clean and not tags_clean and not lyrics_clean:
        raise HTTPException(status_code=400, detail="Describe a song idea, style, or lyrics first.")

    avail = await asyncio.to_thread(get_model_availability)
    if not avail.get("ace_step_music_xl", {}).get("ready") and not avail.get("ace_step_music", {}).get("ready"):
        miss = avail.get("ace_step_music", {}).get("missing_gb", 10.0)
        raise HTTPException(
            status_code=400,
            detail=f"Offline Music Engine needs {miss} GB downloaded first (click Download Offline Music Engine).",
        )

    num_takes = max(1, min(4, int(req.variations or 1)))
    display_label = (req.title or "").strip() or (idea_clean or tags_clean or lyrics_clean)[:50]
    job = job_manager.create(kind="audio", model="ace_step_music", prompt=f"🎵 {display_label}")

    async def _run_music_job() -> None:
        job_manager.update(
            job.id,
            status="running",
            progress_pct=4,
            message=f"Writing lyrics & planning {num_takes} song take(s)...",
        )
        try:
            plan = await asyncio.to_thread(
                plan_song_from_idea,
                idea=idea_clean,
                instrumental=req.instrumental,
                explicit=req.explicit,
                variations=num_takes,
                duration_sec=req.duration_sec,
                custom_style=tags_clean,
                custom_lyrics=lyrics_clean,
                custom_bpm=req.bpm,
            )
            takes = plan.get("takes") or []
            out_dir = engine.workspace_dir / "generated_audio"
            created_tracks: list[dict[str, Any]] = []

            for idx, tk in enumerate(takes):
                if job.cancel_event.is_set():
                    raise GenerationCanceledError("Canceled by user.")
                take_title = (
                    (f"{req.title.strip()} (Take {idx + 1})" if len(takes) > 1 else req.title.strip())
                    if req.title.strip()
                    else tk["title"]
                )
                take_seed = (req.seed + idx) if req.seed >= 0 else -1

                def _prog(msg: str, pct: int | None = None, i_take: int = idx, total_t: int = len(takes)) -> None:
                    local_p = (pct if pct is not None else 50) / 100.0
                    overall = min(98, max(8, int(((i_take + local_p) / max(1, total_t)) * 92) + 6))
                    prefix = f"Song {i_take + 1}/{total_t}: " if total_t > 1 else ""
                    job_manager.update(job.id, progress_pct=overall, message=f"{prefix}{msg}")

                def _pid(pid: str) -> None:
                    job_manager.update(job.id, prompt_id=pid)

                res = await asyncio.to_thread(
                    generate_music_via_comfyui,
                    tags=tk["tags"],
                    output_dir=out_dir,
                    lyrics=tk["lyrics"],
                    title=take_title,
                    instrumental=req.instrumental,
                    strict_lyrics=req.strict_lyrics,
                    quality=req.quality,
                    master_audio=req.master_audio,
                    duration_sec=req.duration_sec,
                    bpm=int(tk["bpm"]),
                    keyscale=req.keyscale.strip() or tk.get("keyscale", "C major"),
                    language=req.language,
                    steps=req.steps,
                    cfg=req.cfg,
                    seed=take_seed,
                    base_url=COMFYUI_URL,
                    comfy_dir=COMFYUI_DIR,
                    auto_start=True,
                    on_progress=_prog,
                    on_prompt_id=_pid,
                    cancel_event=job.cancel_event,
                )
                created_tracks.append({**res, "audio_url": f"/api/generate/audio/{res['filename']}"})

            first = created_tracks[-1]
            overlay_id = None
            if req.add_to_timeline and created_tracks:
                ov = await asyncio.to_thread(
                    engine.add_audio_overlay,
                    None,
                    created_tracks[0]["audio_path"],
                    0.0,
                    req.volume,
                    False,
                    f"🎵 {created_tracks[0]['title'][:28]}",
                )
                overlay_id = ov.id

            done_msg = (
                f"Created {len(created_tracks)} song versions!"
                if len(created_tracks) > 1
                else f"Song ready ({first['duration_sec']}s in {first['generation_time_sec']}s)"
            )
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=done_msg,
                result={
                    **first,
                    "tracks": created_tracks,
                    "variations": len(created_tracks),
                    "planner_source": plan.get("source"),
                    "overlay_id": overlay_id,
                },
            )
        except GenerationCanceledError:
            job_manager.update(job.id, status="canceled", message="Canceled by user")
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_music_job())
    return {"job_id": job.id, "model": "ace_step_music", "variations": num_takes, "status": "queued", "jobs": job_manager.list_jobs()}


@app.get("/api/generate/video/{filename}")
async def api_get_generated_video(filename: str) -> FileResponse:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated", filename, VIDEO_EXTENSIONS)
    return FileResponse(str(target), media_type="video/mp4", filename=target.name)


@app.delete("/api/generate/video/{filename}")
async def api_delete_generated_video(filename: str) -> dict[str, Any]:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated", filename, VIDEO_EXTENSIONS)
    target.unlink(missing_ok=True)
    target.with_suffix(target.suffix + ".meta.json").unlink(missing_ok=True)
    return {"deleted": filename, "videos": await asyncio.to_thread(_list_video_gallery)}


@app.post("/api/generate/video/{filename}/end-frame")
async def api_extract_generated_video_end_frame(filename: str) -> dict[str, Any]:
    """Extract the exact last frame of any generated video directly into workspace/ref_images for 1-click Continue Video."""
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated", filename, VIDEO_EXTENSIONS)
    refs_dir = (engine.workspace_dir / "ref_images").resolve()
    refs_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"cont_{target.stem[:32]}_{uuid.uuid4().hex[:6]}.png"
    out_path = (refs_dir / out_name).resolve()

    def _extract() -> None:
        res = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-sseof", "-0.15", "-i", str(target),
                "-update", "1", "-frames:v", "1",
                str(out_path),
            ],
            capture_output=True, text=True, check=False,
        )
        if res.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 128:
            # Fallback to first frame for ultra-short videos
            res2 = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(target), "-frames:v", "1", str(out_path),
                ],
                capture_output=True, text=True, check=False,
            )
            if res2.returncode != 0 or not out_path.exists():
                raise RuntimeError(f"Could not extract end frame: {(res.stderr or res2.stderr or '')[-300:]}")

    try:
        await asyncio.to_thread(_extract)
        return {
            "image_path": str(out_path),
            "filename": out_name,
            "parent_video": target.name,
            "preview_url": f"/api/generate/ref/{out_name}",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/generate/video/{filename}/smooth-fps")
async def api_smooth_generated_video(filename: str, req: SmoothFpsRequest | None = None) -> dict[str, Any]:
    """1-click 32fps GPU RIFE v4.26 smooth motion directly on a generated video (no Pro timeline required)."""
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated", filename, VIDEO_EXTENSIONS)
    body = req or SmoothFpsRequest()
    orig_meta = read_asset_metadata(target) or {}
    out_path = target.with_name(f"{target.stem[:42]}_32fps_{uuid.uuid4().hex[:4]}.mp4")

    def _do_smooth() -> dict[str, Any]:
        avail = get_model_availability()
        src_fps = float(orig_meta.get("fps") or 16.0)
        if body.prefer_rife and avail.get("rife_vfi", {}).get("ready"):
            r = interpolate_video_rife_via_comfyui(
                target, out_path, source_fps=src_fps, target_fps=body.target_fps,
                base_url=COMFYUI_URL, comfy_dir=COMFYUI_DIR,
            )
            eng_used = r["engine"]
            eff_fps = r["target_fps"]
        else:
            tfps = max(24.0, min(60.0, float(body.target_fps)))
            res = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(target),
                    "-vf", f"minterpolate=fps={tfps:.0f}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "copy", "-movflags", "+faststart", str(out_path),
                ],
                capture_output=True, text=True, check=False,
            )
            if res.returncode != 0 or not out_path.exists():
                raise RuntimeError(f"Smooth motion failed: {(res.stderr or '')[-400:]}")
            eng_used = "ffmpeg_minterpolate"
            eff_fps = tfps

        from .generator import write_asset_metadata
        write_asset_metadata(
            out_path,
            {
                **orig_meta,
                "fps": eff_fps,
                "smoothed_from": target.name,
                "smooth_engine": eng_used,
            },
        )
        return {"filename": out_path.name, "video_path": str(out_path.resolve()), "engine": eng_used, "fps": eff_fps}

    try:
        res = await asyncio.to_thread(_do_smooth)
        return {**res, "videos": await asyncio.to_thread(_list_video_gallery)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/generate/video/stitch")
async def api_stitch_generated_videos(req: StitchVaultRequest) -> dict[str, Any]:
    """Seamlessly combine a continuation chain of generated videos into one continuous MP4 in 1 click."""
    names = [n for n in (req.filenames or []) if isinstance(n, str) and n.strip()]
    if len(names) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 video clips to combine.")
    gen_dir = engine.workspace_dir / "generated"
    targets = [_resolve_safe_dir_file(gen_dir, n, VIDEO_EXTENSIONS) for n in names[:12]]
    out_path = (gen_dir / f"combined_{uuid.uuid4().hex[:8]}.mp4").resolve()

    def _stitch() -> dict[str, Any]:
        from .generator import write_asset_metadata
        from .media import probe_media_file

        infos = [probe_media_file(str(t)) for t in targets]
        ref_w = max(256, int(infos[0].width or 480))
        ref_h = max(256, int(infos[0].height or 768))
        ref_w -= ref_w % 2
        ref_h -= ref_h % 2
        ref_fps = max(16.0, float(infos[0].fps or 24.0))

        inp_args: list[str] = []
        v_filters: list[str] = []
        concat_inputs: list[str] = []
        for idx, (t, info) in enumerate(zip(targets, infos)):
            inp_args.extend(["-i", str(t)])
            dur = max(0.2, float(info.duration_sec or 3.0))
            v_filters.append(
                f"[{idx}:v]fps={ref_fps:.2f},scale={ref_w}:{ref_h}:force_original_aspect_ratio=decrease,"
                f"pad={ref_w}:{ref_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p[v{idx}]"
            )
            if info.has_audio:
                v_filters.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo[a{idx}]")
            else:
                v_filters.append(f"anullsrc=r=44100:cl=stereo:d={dur:.3f}[a{idx}]")
            concat_inputs.append(f"[v{idx}][a{idx}]")

        fg = ";".join(v_filters) + f";{''.join(concat_inputs)}concat=n={len(targets)}:v=1:a=1[outv][outa]"
        res = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                *inp_args,
                "-filter_complex", fg,
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                str(out_path),
            ],
            capture_output=True, text=True, check=False,
        )
        if res.returncode != 0 or not out_path.exists():
            raise RuntimeError(f"Combine failed: {(res.stderr or '')[-500:]}")

        out_info = probe_media_file(str(out_path))
        write_asset_metadata(
            out_path,
            {
                "kind": "video",
                "model": "combined_scene",
                "raw_prompt": f"Combined {len(targets)}-part scene",
                "prompt": f"Combined {len(targets)}-part scene",
                "width": ref_w,
                "height": ref_h,
                "fps": ref_fps,
                "duration_sec": round(float(out_info.duration_sec or sum(i.duration_sec for i in infos)), 2),
                "stitched_from": [t.name for t in targets],
            },
        )
        return {
            "filename": out_path.name,
            "video_path": str(out_path),
            "duration_sec": round(float(out_info.duration_sec or 0.0), 2),
            "parts": len(targets),
        }

    try:
        res = await asyncio.to_thread(_stitch)
        return {**res, "videos": await asyncio.to_thread(_list_video_gallery)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/generate/start-comfyui")
async def api_start_comfyui() -> dict[str, Any]:
    try:
        res = await asyncio.to_thread(ensure_comfyui_running)
        return {**res, "models": await asyncio.to_thread(get_model_availability)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/generate/models/{model_id}/download")
async def api_download_model(model_id: str) -> dict[str, Any]:
    if model_id not in MODEL_SPECS:
        raise HTTPException(status_code=404, detail=f"Unknown model '{model_id}'.")
    try:
        dl = await asyncio.to_thread(download_manager.start_download, model_id)
        return {
            "model_id": model_id,
            "download": dl,
            "models": await asyncio.to_thread(get_model_availability),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/generate/models/{model_id}/cancel")
async def api_cancel_model_download(model_id: str) -> dict[str, Any]:
    if model_id not in MODEL_SPECS:
        raise HTTPException(status_code=404, detail=f"Unknown model '{model_id}'.")
    canceled = await asyncio.to_thread(download_manager.cancel_download, model_id)
    return {
        "model_id": model_id,
        "canceled": canceled,
        "models": await asyncio.to_thread(get_model_availability),
    }


@app.post("/api/generate/upload-ref")
async def api_upload_ref_image(file: UploadFile = File(...)) -> dict[str, Any]:
    refs_dir = (engine.workspace_dir / "ref_images").resolve()
    refs_dir.mkdir(parents=True, exist_ok=True)
    try:
        safe_name = _sanitize_ref_image_filename(file.filename)
        dest = (refs_dir / safe_name).resolve()
        dest.relative_to(refs_dir)
        data = await file.read()
        if len(data) > 50 * 1024 * 1024:
            raise ValueError("Reference image exceeds 50 MB limit.")
        dest.write_bytes(data)
        return {
            "filename": safe_name,
            "image_path": str(dest),
            "preview_url": f"/api/generate/ref/{safe_name}",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/generate/ref/{filename}")
async def api_get_ref_image(filename: str) -> FileResponse:
    target = _resolve_safe_dir_file(engine.workspace_dir / "ref_images", filename, IMAGE_EXTENSIONS)
    return FileResponse(str(target), filename=target.name)


@app.get("/api/generate/image/{filename}")
async def api_get_generated_image(filename: str) -> FileResponse:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated_images", filename, IMAGE_EXTENSIONS)
    return FileResponse(str(target), filename=target.name)


@app.delete("/api/generate/image/{filename}")
async def api_delete_generated_image(filename: str) -> dict[str, Any]:
    target = _resolve_safe_dir_file(engine.workspace_dir / "generated_images", filename, IMAGE_EXTENSIONS)
    target.unlink(missing_ok=True)
    target.with_suffix(target.suffix + ".meta.json").unlink(missing_ok=True)
    return {"deleted": filename, "gallery": await asyncio.to_thread(_list_image_gallery)}


@app.post("/api/generate/image")
async def api_generate_image(req: GenerateImageRequest) -> dict[str, Any]:
    prompt_raw = (req.prompt or "").strip()
    if not prompt_raw:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    # Decode optional canvas mask_data_url into a temporary PNG inside workspace/ref_images
    resolved_mask_path = req.mask_path
    if req.mask_data_url and not resolved_mask_path:
        raw_durl = req.mask_data_url.strip()
        if not raw_durl.startswith("data:image/png;base64,"):
            raise HTTPException(status_code=400, detail="mask_data_url must be a PNG data URL.")
        b64_part = raw_durl.split(",", 1)[1]
        if len(b64_part) > 32 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Inpaint mask exceeds size limit.")
        mask_bytes = base64.b64decode(b64_part)
        refs_dir = (engine.workspace_dir / "ref_images").resolve()
        refs_dir.mkdir(parents=True, exist_ok=True)
        mask_file = refs_dir / f"_mask_{uuid.uuid4().hex[:8]}.png"
        mask_file.write_bytes(mask_bytes)
        resolved_mask_path = str(mask_file)

    # Auto-resolve @Friend cast mentions and attach their saved reference photo(s)
    prompt_clean, img1, img2, _matched_cast = await asyncio.to_thread(
        get_cast_manager().resolve_prompt_mentions, prompt_raw, req.image_path, req.image_path_2
    )

    chosen_model = req.model
    if chosen_model == "auto":
        chosen_model = await asyncio.to_thread(
            resolve_auto_model, "image", bool(img1), bool(img2), False, False, req.intent
        )

    spec = MODEL_SPECS.get(chosen_model)
    if not spec or spec["kind"] != "image":
        raise HTTPException(status_code=400, detail=f"Invalid image model '{chosen_model}'.")
    if spec["requires_image"] and not img1:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} requires a friend/reference photo (or type @FriendName).",
        )

    avail = await asyncio.to_thread(get_model_availability)
    if not avail[chosen_model]["ready"]:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} needs {avail[chosen_model]['missing_gb']} GB downloaded first (click Download in Model Manager).",
        )

    job = job_manager.create(kind="image", model=chosen_model, prompt=prompt_raw)

    async def _run_image_job() -> None:
        job_manager.update(job.id, status="running", progress_pct=3, message="Starting offline image generation...")
        try:
            out_dir = engine.workspace_dir / "generated_images"

            def _progress(msg: str, pct: int | None = None) -> None:
                upd: dict[str, Any] = {"message": msg}
                if pct is not None:
                    upd["progress_pct"] = pct
                job_manager.update(job.id, **upd)

            def _preview(data_url: str) -> None:
                job_manager.update(job.id, preview_data_url=data_url)

            def _on_pid(pid: str) -> None:
                job_manager.update(job.id, prompt_id=pid)

            eff_prompt = prompt_clean
            eff_neg = req.negative_prompt
            if req.auto_enhance:
                _progress(f"Smart-tuning prompt for {chosen_model}...", 4)
                try:
                    enh = await asyncio.to_thread(
                        expand_meme_prompt_local,
                        idea=prompt_clean,
                        mode="image",
                        has_friend_photo=bool(img1),
                        has_second_photo=bool(img2),
                        model_id=chosen_model,
                        style_preset=req.style_preset,
                    )
                    if enh.get("prompt"):
                        eff_prompt = str(enh["prompt"])
                    if not (eff_neg or "").strip() and enh.get("negative_prompt"):
                        eff_neg = str(enh["negative_prompt"])
                except Exception:
                    pass

            res = await asyncio.to_thread(
                generate_image_via_comfyui,
                prompt=eff_prompt,
                output_dir=out_dir,
                model=chosen_model,  # type: ignore[arg-type]
                image_path=img1,
                image_path_2=img2,
                pose_image_path=req.pose_image_path,
                mask_path=resolved_mask_path,
                negative_prompt=eff_neg,
                style_preset=req.style_preset,
                width=req.width,
                height=req.height,
                match_photo_aspect=req.match_photo_aspect,
                steps=req.steps,
                cfg=req.cfg,
                denoise=req.denoise,
                seed=req.seed,
                batch_size=req.batch_size,
                loras=req.loras,
                checkpoint_override=req.checkpoint_override,
                parent_image=req.parent_image,
                base_url=COMFYUI_URL,
                comfy_dir=COMFYUI_DIR,
                auto_start=True,
                timeout_sec=600.0,
                on_progress=_progress,
                on_preview=_preview,
                on_prompt_id=_on_pid,
                cancel_event=job.cancel_event,
            )

            if req.auto_face_swap and (img1 or img2) and avail.get("face_swap", {}).get("ready"):
                _progress("Locking real friend face(s) onto scene...", 92)
                face_srcs = [p for p in (img1, img2) if p and Path(p).exists()]
                if face_srcs:
                    for item in res.get("images", []):
                        try:
                            ip = Path(item["image_path"])
                            await asyncio.to_thread(
                                swap_faces_in_image,
                                ip,
                                face_srcs,
                                out_dir,
                                COMFYUI_DIR,
                                ip,
                            )
                            orig_m = read_asset_metadata(ip) or {}
                            write_asset_metadata(ip, {**orig_m, "face_swapped": True})
                        except Exception:
                            pass

            if req.auto_polish and int(res.get("batch_size", 1)) == 1:
                _progress("Running 2× AI UltraSharp HD Polish...", 95)
                try:
                    pol = await asyncio.to_thread(polish_image_hd, Path(res["image_path"]), out_dir, 2, True)
                    res["image_path"] = pol["image_path"]
                    res["filename"] = pol["filename"]
                    res["width"] = pol["width"]
                    res["height"] = pol["height"]
                    res["hd_engine"] = pol["engine"]
                except Exception:
                    pass

            media_id = None
            if req.add_to_timeline:
                _progress("Adding image to timeline...", 98)
                imported = await asyncio.to_thread(engine.import_media, [res["image_path"]])
                media_item = imported[0]
                media_id = media_item.id
                cur_tl = (await asyncio.to_thread(engine.get_state)).timeline
                use_trans: TransitionType = req.transition if cur_tl else "cut"
                await asyncio.to_thread(
                    engine.add_timeline_clip,
                    media_item.id,
                    0.0,
                    None,
                    None,
                    use_trans,
                    req.transition_duration if cur_tl else 0.0,
                    1.0,
                    1.0,
                    f"{chosen_model}: {prompt_raw[:28]}",
                )

            cnt = int(res.get("batch_size", 1))
            done_msg = (
                f"Done: {cnt} images in {res['generation_time_sec']}s"
                if cnt > 1
                else f"Done in {res['generation_time_sec']}s ({res['filename']})"
            )
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=done_msg,
                result={
                    **res,
                    "preview_url": f"/api/generate/image/{res['filename']}",
                    "media_id": media_id,
                },
            )
        except GenerationCanceledError:
            job_manager.update(job.id, status="canceled", message="Canceled by user")
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_image_job())
    return {"job_id": job.id, "model": chosen_model, "status": "queued", "jobs": job_manager.list_jobs()}


@app.post("/api/generate/video")
async def api_generate_video(req: GenerateVideoRequest) -> dict[str, Any]:
    prompt_raw = (req.prompt or "").strip()
    if not prompt_raw:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    prompt_clean, img1, _img2, _matched_cast = await asyncio.to_thread(
        get_cast_manager().resolve_prompt_mentions, prompt_raw, req.image_path, None
    )

    chosen_model = req.model
    if chosen_model == "auto":
        chosen_model = await asyncio.to_thread(
            resolve_auto_model, "video", bool(img1), False, req.want_audio, req.fast_draft, req.intent
        )

    spec = MODEL_SPECS.get(chosen_model)
    if not spec or spec["kind"] != "video":
        raise HTTPException(status_code=400, detail=f"Invalid video model '{chosen_model}'.")
    if spec["requires_image"] and not img1:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} requires a friend photo / start frame (or type @FriendName).",
        )

    avail = await asyncio.to_thread(get_model_availability)
    if not avail[chosen_model]["ready"]:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} needs {avail[chosen_model]['missing_gb']} GB downloaded first (click Download in Model Manager).",
        )

    job = job_manager.create(kind="video", model=chosen_model, prompt=prompt_raw)

    async def _run_job() -> None:
        job_manager.update(job.id, status="running", progress_pct=3, message="Starting offline video generation...")
        try:
            gen_dir = engine.workspace_dir / "generated"

            def _progress(msg: str, pct: int | None = None) -> None:
                upd: dict[str, Any] = {"message": msg}
                if pct is not None:
                    upd["progress_pct"] = pct
                job_manager.update(job.id, **upd)

            def _preview(data_url: str) -> None:
                job_manager.update(job.id, preview_data_url=data_url)

            def _on_pid(pid: str) -> None:
                job_manager.update(job.id, prompt_id=pid)

            eff_prompt = prompt_clean
            eff_neg = req.negative_prompt
            if req.auto_enhance:
                _progress(f"Smart-tuning motion prompt for {chosen_model}...", 4)
                try:
                    enh = await asyncio.to_thread(
                        expand_meme_prompt_local,
                        idea=prompt_clean,
                        mode="video",
                        has_friend_photo=bool(img1),
                        has_end_frame=bool(req.end_image_path),
                        model_id=chosen_model,
                        style_preset=req.style_preset,
                        camera_preset=req.camera_preset,
                    )
                    if enh.get("prompt"):
                        eff_prompt = str(enh["prompt"])
                    if enh.get("negative_prompt") and eff_neg == DEFAULT_NEGATIVE_PROMPT:
                        eff_neg = str(enh["negative_prompt"])
                except Exception:
                    pass

            res = await asyncio.to_thread(
                generate_video_via_comfyui,
                prompt=eff_prompt,
                output_dir=gen_dir,
                model=chosen_model,  # type: ignore[arg-type]
                image_path=img1,
                end_image_path=req.end_image_path,
                audio_path=req.audio_path,
                negative_prompt=eff_neg,
                style_preset=req.style_preset,
                camera_preset=req.camera_preset,
                width=req.width,
                height=req.height,
                match_photo_aspect=req.match_photo_aspect,
                num_frames=req.num_frames,
                fps=req.fps,
                steps=req.steps,
                cfg=req.cfg,
                seed=req.seed,
                loras=req.loras,
                parent_video=req.parent_video,
                base_url=COMFYUI_URL,
                comfy_dir=COMFYUI_DIR,
                auto_start=True,
                timeout_sec=1800.0,
                on_progress=_progress,
                on_preview=_preview,
                on_prompt_id=_on_pid,
                cancel_event=job.cancel_event,
            )

            if req.auto_smooth_fps and chosen_model != "ltx23" and avail.get("rife_vfi", {}).get("ready"):
                _progress("Smoothing video to 32fps via GPU RIFE v4.26...", 94)
                try:
                    src_vid = Path(res["video_path"])
                    smooth_out = src_vid.with_name(f"{src_vid.stem}_32fps.mp4")
                    rife_res = await asyncio.to_thread(
                        interpolate_video_rife_via_comfyui,
                        src_vid,
                        smooth_out,
                        float(req.fps or MODEL_SPECS[chosen_model].get("default_fps") or 16.0),
                        32.0,
                        COMFYUI_URL,
                        COMFYUI_DIR,
                    )
                    res["video_path"] = rife_res["output_path"]
                    res["filename"] = Path(rife_res["output_path"]).name
                    res["rife_smoothed"] = True
                except Exception:
                    pass
            _progress("Importing clip into ClipForge...", 98)
            imported = await asyncio.to_thread(engine.import_media, [res["video_path"]])
            media_item = imported[0]
            if req.add_to_timeline:
                cur_tl = (await asyncio.to_thread(engine.get_state)).timeline
                use_trans: TransitionType = req.transition if cur_tl else "cut"
                await asyncio.to_thread(
                    engine.add_timeline_clip,
                    media_item.id,
                    0.0,
                    None,
                    None,
                    use_trans,
                    req.transition_duration if cur_tl else 0.0,
                    1.0,
                    1.0,
                    f"{chosen_model}: {prompt_raw[:28]}",
                )
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=f"Done in {res['generation_time_sec']}s ({media_item.filename})",
                result={**res, "media_id": media_item.id},
            )
        except GenerationCanceledError:
            job_manager.update(job.id, status="canceled", message="Canceled by user")
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_job())
    return {"job_id": job.id, "model": chosen_model, "status": "queued", "jobs": job_manager.list_jobs()}


@app.post("/api/generate/storyboard")
async def api_generate_storyboard(req: StoryboardRenderRequest) -> dict[str, Any]:
    """Render 2-4 sequential storyboard beats automatically chaining each beat's final frame -> next beat's start frame."""
    beats = [b for b in (req.beats or []) if isinstance(b, dict) and str(b.get("prompt") or "").strip()]
    if not beats:
        raise HTTPException(status_code=400, detail="Storyboard requires at least 1 beat with a prompt.")
    beats = beats[:4]

    job = job_manager.create(kind="video", model="storyboard", prompt=f"🎞 {len(beats)}-beat scene: {str(beats[0]['prompt'])[:32]}")

    async def _run_storyboard() -> None:
        job_manager.update(job.id, status="running", progress_pct=2, message=f"Starting {len(beats)}-beat chained scene...")
        try:
            gen_dir = engine.workspace_dir / "generated"
            cur_img = req.image_path
            rendered_clips: list[dict[str, Any]] = []
            cursor_sec = (await asyncio.to_thread(engine.get_state)).total_timeline_duration()

            for idx, beat in enumerate(beats):
                if job.cancel_event.is_set():
                    raise GenerationCanceledError("Canceled by user.")
                b_prompt_raw = str(beat.get("prompt") or "").strip()
                b_cam = str(beat.get("camera_preset") or "none").strip()
                b_caption = str(beat.get("caption") or "").strip()
                b_sfx = str(beat.get("sfx_id") or "").strip()

                b_prompt, img1, _, _ = await asyncio.to_thread(
                    get_cast_manager().resolve_prompt_mentions, b_prompt_raw, cur_img, None
                )
                chosen_model = req.model
                if chosen_model == "auto":
                    chosen_model = await asyncio.to_thread(
                        resolve_auto_model, "video", bool(img1), False, req.want_audio, req.fast_draft
                    )

                def _beat_prog(msg: str, pct: int | None = None, b_idx: int = idx) -> None:
                    local_p = pct if pct is not None else 50
                    overall = min(98, max(3, int(((b_idx + local_p / 100.0) / len(beats)) * 100)))
                    job_manager.update(job.id, progress_pct=overall, message=f"Beat {b_idx + 1}/{len(beats)} ({chosen_model}): {msg}")

                def _prev(durl: str) -> None:
                    job_manager.update(job.id, preview_data_url=durl)

                def _pid(pid: str) -> None:
                    job_manager.update(job.id, prompt_id=pid)

                res = await asyncio.to_thread(
                    generate_video_via_comfyui,
                    prompt=b_prompt,
                    output_dir=gen_dir,
                    model=chosen_model,  # type: ignore[arg-type]
                    image_path=img1,
                    style_preset=req.style_preset,
                    camera_preset=b_cam,
                    match_photo_aspect=True,
                    num_frames=req.num_frames,
                    loras=req.loras,
                    on_progress=_beat_prog,
                    on_preview=_prev,
                    on_prompt_id=_pid,
                    cancel_event=job.cancel_event,
                )
                imported = await asyncio.to_thread(engine.import_media, [res["video_path"]])
                media_item = imported[0]
                cur_tl = (await asyncio.to_thread(engine.get_state)).timeline
                clip = await asyncio.to_thread(
                    engine.add_timeline_clip,
                    media_item.id,
                    0.0,
                    None,
                    None,
                    req.transition if cur_tl else "cut",
                    req.transition_duration if cur_tl else 0.0,
                    1.0,
                    1.0,
                    f"Beat {idx + 1}: {b_prompt_raw[:22]}",
                )
                clip_dur = max(0.5, clip.effective_duration)
                if req.auto_captions and b_caption:
                    await asyncio.to_thread(
                        engine.upsert_subtitle,
                        cursor_sec + 0.1,
                        cursor_sec + max(0.8, clip_dur - 0.15),
                        b_caption,
                    )
                if req.add_sfx and b_sfx:
                    try:
                        await asyncio.to_thread(engine.add_audio_overlay, b_sfx, None, cursor_sec, 1.0, True, None)
                    except Exception:
                        pass

                cursor_sec = (await asyncio.to_thread(engine.get_state)).total_timeline_duration()
                rendered_clips.append({"beat": idx + 1, "clip_id": clip.id, "video_path": res["video_path"], "model": chosen_model})

                # Chain exact final frame -> next beat's start frame!
                if idx + 1 < len(beats):
                    ef = await asyncio.to_thread(engine.extract_clip_end_frame, clip.id)
                    cur_img = ef["image_path"]

            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=f"Chained {len(rendered_clips)}-beat scene added to timeline!",
                result={"beats": rendered_clips},
            )
        except GenerationCanceledError:
            job_manager.update(job.id, status="canceled", message="Canceled by user")
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_storyboard())
    return {"job_id": job.id, "status": "queued", "jobs": job_manager.list_jobs()}


def main() -> None:
    parser = argparse.ArgumentParser(description="ClipForge Web Editor Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
