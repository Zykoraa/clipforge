"""Hardened FastAPI + WebSocket server for the ClipForge Visual Timeline Editor with live MCP sync."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import re
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .director import discover_local_llm, expand_meme_prompt_local
from .engine import ProjectEngine
from .generator import (
    CAMERA_PRESETS,
    COMFYUI_DIR,
    COMFYUI_URL,
    DEFAULT_NEGATIVE_PROMPT,
    ImageModelId,
    MODEL_SPECS,
    PROMPT_PRESETS,
    VideoModelId,
    download_manager,
    ensure_comfyui_running,
    generate_image_via_comfyui,
    generate_video_via_comfyui,
    get_model_availability,
    is_comfyui_reachable,
    job_manager,
)
from .media import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS
from .models import MemeTemplateType, TransitionType
from .sfx import ensure_builtin_sfx_file, list_builtin_sfx


def _resolve_static_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        cand = meipass / "clipforge" / "static"
        if cand.exists():
            return cand
    return Path(__file__).parent / "static"


STATIC_DIR = _resolve_static_dir()
engine = ProjectEngine()

# Cryptographic per-process CSRF/session token (injected into same-origin index.html only)
SESSION_TOKEN = secrets.token_urlsafe(32)
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
    model: VideoModelId = "wan22_5b"
    image_path: str | None = None
    end_image_path: str | None = None
    width: int | None = None
    height: int | None = None
    num_frames: int | None = None
    fps: int | None = None
    steps: int | None = None
    cfg: float | None = None
    seed: int = -1
    add_to_timeline: bool = True
    transition: TransitionType = "crossfade"
    transition_duration: float = 0.35


class GenerateImageRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    style_preset: str | None = None
    model: ImageModelId = "flux2_klein"
    image_path: str | None = None
    image_path_2: str | None = None
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    cfg: float | None = None
    seed: int = -1
    batch_size: int = 1
    add_to_timeline: bool = False
    transition: TransitionType = "crossfade"
    transition_duration: float = 0.35


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
    endpoint: str | None = None
    model_name: str | None = None


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
    return await asyncio.to_thread(discover_local_llm, endpoint)


@app.post("/api/director/expand")
async def api_director_expand(req: DirectorExpandRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            expand_meme_prompt_local,
            req.idea,
            req.mode,
            req.has_friend_photo,
            req.endpoint,
            req.model_name,
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


@app.get("/api/generate/status")
async def api_generate_status() -> dict[str, Any]:
    running = await asyncio.to_thread(is_comfyui_reachable)
    models = await asyncio.to_thread(get_model_availability)
    gallery = await asyncio.to_thread(_list_image_gallery)
    ref_images = await asyncio.to_thread(_list_ref_images)
    return {
        "comfyui_url": COMFYUI_URL,
        "comfyui_dir": str(COMFYUI_DIR),
        "comfyui_running": running,
        "models": models,
        "jobs": job_manager.list_jobs(),
        "presets": PROMPT_PRESETS,
        "camera_presets": CAMERA_PRESETS,
        "gallery": gallery,
        "ref_images": ref_images,
    }


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
    return {"deleted": filename, "gallery": await asyncio.to_thread(_list_image_gallery)}


@app.post("/api/generate/image")
async def api_generate_image(req: GenerateImageRequest) -> dict[str, Any]:
    prompt_clean = (req.prompt or "").strip()
    if not prompt_clean:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    spec = MODEL_SPECS.get(req.model)
    if not spec or spec["kind"] != "image":
        raise HTTPException(status_code=400, detail=f"Invalid image model '{req.model}'.")
    if spec["requires_image"] and not req.image_path:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} requires a friend/reference photo.",
        )

    avail = await asyncio.to_thread(get_model_availability)
    if not avail[req.model]["ready"]:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} needs {avail[req.model]['missing_gb']} GB downloaded first (click Download in Model Manager).",
        )

    job = job_manager.create(kind="image", model=req.model, prompt=prompt_clean)

    async def _run_image_job() -> None:
        job_manager.update(job.id, status="running", progress_pct=3, message="Starting offline image generation...")
        try:
            out_dir = engine.workspace_dir / "generated_images"

            def _progress(msg: str, pct: int | None = None) -> None:
                upd: dict[str, Any] = {"message": msg}
                if pct is not None:
                    upd["progress_pct"] = pct
                job_manager.update(job.id, **upd)

            res = await asyncio.to_thread(
                generate_image_via_comfyui,
                prompt=prompt_clean,
                output_dir=out_dir,
                model=req.model,
                image_path=req.image_path,
                image_path_2=req.image_path_2,
                negative_prompt=req.negative_prompt,
                style_preset=req.style_preset,
                width=req.width,
                height=req.height,
                steps=req.steps,
                cfg=req.cfg,
                seed=req.seed,
                batch_size=req.batch_size,
                base_url=COMFYUI_URL,
                comfy_dir=COMFYUI_DIR,
                auto_start=True,
                timeout_sec=600.0,
                on_progress=_progress,
            )

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
                    f"{req.model}: {prompt_clean[:28]}",
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
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_image_job())
    return {"job_id": job.id, "status": "queued", "jobs": job_manager.list_jobs()}


@app.post("/api/generate/video")
async def api_generate_video(req: GenerateVideoRequest) -> dict[str, Any]:
    prompt_clean = (req.prompt or "").strip()
    if not prompt_clean:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    spec = MODEL_SPECS.get(req.model)
    if not spec or spec["kind"] != "video":
        raise HTTPException(status_code=400, detail=f"Invalid video model '{req.model}'.")
    if spec["requires_image"] and not req.image_path:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} requires a friend photo / start frame.",
        )

    avail = await asyncio.to_thread(get_model_availability)
    if not avail[req.model]["ready"]:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['display_name']} needs {avail[req.model]['missing_gb']} GB downloaded first (click Download in Model Manager).",
        )

    job = job_manager.create(kind="video", model=req.model, prompt=prompt_clean)

    async def _run_job() -> None:
        job_manager.update(job.id, status="running", progress_pct=3, message="Starting offline video generation...")
        try:
            gen_dir = engine.workspace_dir / "generated"

            def _progress(msg: str, pct: int | None = None) -> None:
                upd: dict[str, Any] = {"message": msg}
                if pct is not None:
                    upd["progress_pct"] = pct
                job_manager.update(job.id, **upd)

            res = await asyncio.to_thread(
                generate_video_via_comfyui,
                prompt=prompt_clean,
                output_dir=gen_dir,
                model=req.model,
                image_path=req.image_path,
                end_image_path=req.end_image_path,
                negative_prompt=req.negative_prompt,
                style_preset=req.style_preset,
                camera_preset=req.camera_preset,
                width=req.width,
                height=req.height,
                num_frames=req.num_frames,
                fps=req.fps,
                steps=req.steps,
                cfg=req.cfg,
                seed=req.seed,
                base_url=COMFYUI_URL,
                comfy_dir=COMFYUI_DIR,
                auto_start=True,
                timeout_sec=1800.0,
                on_progress=_progress,
            )
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
                    f"{req.model}: {prompt_clean[:28]}",
                )
            job_manager.update(
                job.id,
                status="completed",
                progress_pct=100,
                message=f"Done in {res['generation_time_sec']}s ({media_item.filename})",
                result={**res, "media_id": media_item.id},
            )
        except Exception as exc:
            job_manager.update(job.id, status="failed", message=str(exc), error=str(exc))

    asyncio.create_task(_run_job())
    return {"job_id": job.id, "status": "queued", "jobs": job_manager.list_jobs()}


def main() -> None:
    parser = argparse.ArgumentParser(description="ClipForge Web Editor Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
