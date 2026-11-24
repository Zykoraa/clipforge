"""Media probing, silence detection, scene detection, thumbnails, waveforms, and Whisper STT."""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np

from .models import MediaItem, TimeInterval, TranscriptSegment, WordToken, new_id

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS

_WHISPER_CACHE: dict[str, Any] = {}
_WHISPER_LOCK = threading.Lock()
_CUDA_AVAILABLE_CACHED: bool | None = None

_SILENCE_EVENT_RE = re.compile(
    r"silence_(start|end):\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)"
)


def _iter_nvidia_wheel_lib_dirs(subdir_name: str) -> list[Path]:
    """Discover pip/uv-installed nvidia-cublas-cu12 / nvidia-cudnn-cu12 library directories."""
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    for sp in sys.path:
        if sp:
            p = Path(sp)
            if p.is_dir():
                roots.append(p)

    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for pkg in ("cublas", "cudnn"):
            cand = root / "nvidia" / pkg / subdir_name
            if cand.is_dir():
                resolved = cand.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(resolved)
    return found


def _cuda_runtime_available() -> bool:
    """Verify both CUDA GPU presence and required cuBLAS/cuDNN runtime libraries before loading on GPU."""
    global _CUDA_AVAILABLE_CACHED
    if _CUDA_AVAILABLE_CACHED is not None:
        return _CUDA_AVAILABLE_CACHED
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() <= 0:
            _CUDA_AVAILABLE_CACHED = False
            return False

        if sys.platform == "win32":
            for lib_dir in _iter_nvidia_wheel_lib_dirs("bin"):
                try:
                    os.add_dll_directory(str(lib_dir))
                except Exception:
                    pass
            ctypes.WinDLL("cublas64_12.dll")
            ctypes.WinDLL("cublasLt64_12.dll")
            _CUDA_AVAILABLE_CACHED = True
        elif sys.platform.startswith("linux"):
            # Preload cuBLAS 12 (and cuDNN 9 if installed) with RTLD_GLOBAL so ctranslate2's dlopen succeeds
            # even when libraries come from pip/uv nvidia-*-cu12 wheels instead of system LD_LIBRARY_PATH.
            wheel_dirs = _iter_nvidia_wheel_lib_dirs("lib")
            rtld_global = getattr(ctypes, "RTLD_GLOBAL", 0)

            def _load_linux_lib(soname: str) -> bool:
                for d in wheel_dirs:
                    cand = d / soname
                    if cand.exists():
                        try:
                            ctypes.CDLL(str(cand), mode=rtld_global)
                            return True
                        except OSError:
                            pass
                try:
                    ctypes.CDLL(soname, mode=rtld_global)
                    return True
                except OSError:
                    return False

            # Load cublasLt before cublas so symbol dependencies resolve cleanly
            lt_ok = _load_linux_lib("libcublasLt.so.12")
            blas_ok = _load_linux_lib("libcublas.so.12")
            # Optional cuDNN preload if present (beneficial for conv layers / future ctranslate2 builds)
            _load_linux_lib("libcudnn_ops.so.9")
            _load_linux_lib("libcudnn_cnn.so.9")
            _load_linux_lib("libcudnn.so.9")
            _CUDA_AVAILABLE_CACHED = bool(lt_ok and blas_ok)
        else:
            _CUDA_AVAILABLE_CACHED = False
    except Exception:
        _CUDA_AVAILABLE_CACHED = False
    return _CUDA_AVAILABLE_CACHED


def probe_media_file(file_path: str | Path, assets_dir: Path | None = None) -> MediaItem:
    """Inspect a video/audio file using ffprobe and optionally generate thumbnail & waveform peaks."""
    p = Path(file_path).resolve()
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Media file not found: {p}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(p),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 or not res.stdout.strip():
        raise ValueError(f"File is not a readable media container: {p.name}")

    info = json.loads(res.stdout)
    streams = info.get("streams", [])
    fmt = info.get("format", {})

    # Ignore attached cover-art picture streams on MP3/M4A files
    video_stream = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and int((s.get("disposition") or {}).get("attached_pic", 0)) == 0
        ),
        None,
    )
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video_stream is None and audio_stream is None:
        raise ValueError(f"No video or audio streams found in: {p.name}")

    fmt_name = str(fmt.get("format_name") or "").lower()
    is_image = (
        p.suffix.lower() in IMAGE_EXTENSIONS
        or (
            audio_stream is None
            and any(tag in fmt_name for tag in ("image2", "png_pipe", "jpeg_pipe", "webp_pipe", "bmp_pipe"))
        )
    )

    if is_image:
        duration = 3.0
    else:
        duration = float(fmt.get("duration") or 0.0)
        if duration <= 0.0 and video_stream and video_stream.get("duration"):
            duration = float(video_stream["duration"])
        if duration <= 0.0 and audio_stream and audio_stream.get("duration"):
            duration = float(audio_stream["duration"])
        duration = max(0.1, round(duration, 3))

    has_video = video_stream is not None
    has_audio = audio_stream is not None and not is_image
    width = int(video_stream.get("width", 1920)) if video_stream else 1920
    height = int(video_stream.get("height", 1080)) if video_stream else 1080
    video_codec = video_stream.get("codec_name", "h264") if video_stream else "none"
    audio_codec = audio_stream.get("codec_name") if has_audio else None

    fps = 30.0
    if video_stream and not is_image:
        r_frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "30/1"
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/", 1)
            if float(den) > 0:
                fps = round(float(num) / float(den), 3)
        elif float(r_frame_rate) > 0:
            fps = round(float(r_frame_rate), 3)
    if fps <= 1.0 or fps > 240.0:
        fps = 30.0

    item = MediaItem(
        id=new_id("media"),
        path=str(p),
        filename=p.name,
        duration_sec=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=video_codec,
        audio_codec=audio_codec,
        has_video=has_video,
        has_audio=has_audio,
        is_image=is_image,
        file_size_bytes=p.stat().st_size,
    )

    if assets_dir:
        assets_dir.mkdir(parents=True, exist_ok=True)
        if has_video:
            thumb_path = assets_dir / f"{item.id}_thumb.jpg"
            try:
                extract_frame(p, 0.0 if is_image else min(0.5, duration * 0.25), thumb_path, width=320)
                if thumb_path.exists():
                    item.thumbnail_path = str(thumb_path)
            except Exception:
                pass

        if has_audio:
            try:
                item.waveform_peaks = extract_waveform_peaks(p, duration_sec=duration, num_buckets=80)
            except Exception:
                item.waveform_peaks = []

    return item


def extract_frame(
    video_path: str | Path,
    timestamp_sec: float,
    output_jpg: str | Path,
    width: int = 640,
) -> Path:
    """Extract a single JPEG frame from a video at timestamp_sec."""
    out = Path(output_jpg)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(0.0, timestamp_sec):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-q:v",
        "3",
        str(out),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out


def extract_waveform_peaks(
    video_path: str | Path,
    duration_sec: float = 0.0,
    num_buckets: int = 80,
) -> list[float]:
    """Stream mono 4kHz 16-bit PCM via ffmpeg in bounded O(1) memory and compute normalized amplitude peaks."""
    sample_rate = 4000
    cmd = [
        "ffmpeg",
        "-v",
        "quiet",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None

    # Compute fine-grained block peaks in fixed 32KB (~4s of 4kHz s16le) chunks
    block_size = max(16, int((duration_sec * sample_rate) / max(1, num_buckets * 4))) if duration_sec > 0 else 200
    fine_peaks: list[float] = []
    remainder = b""
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buf = remainder + chunk
            usable = (len(buf) // 2) * 2
            remainder = buf[usable:]
            if usable == 0:
                continue
            arr = np.frombuffer(buf[:usable], dtype="<i2")
            n = len(arr)
            if n == 0:
                continue
            # Vectorized max-abs per block
            full_blocks = n // block_size
            if full_blocks > 0:
                reshaped = arr[: full_blocks * block_size].reshape(full_blocks, block_size)
                # Convert to int32 before abs to avoid -32768 int16 overflow
                blk_max = np.abs(reshaped.astype(np.int32)).max(axis=1) / 32768.0
                fine_peaks.extend(blk_max.tolist())
            tail = arr[full_blocks * block_size :]
            if len(tail) > 0:
                fine_peaks.append(float(np.abs(tail.astype(np.int32)).max()) / 32768.0)
    finally:
        proc.stdout.close()
        proc.wait()

    if not fine_peaks:
        return [0.05] * num_buckets

    arr_peaks = np.asarray(fine_peaks, dtype=np.float32)
    indices = np.linspace(0, len(arr_peaks), num_buckets + 1, dtype=int)
    peaks: list[float] = []
    for i in range(num_buckets):
        lo, hi = int(indices[i]), max(int(indices[i]) + 1, int(indices[i + 1]))
        val = float(arr_peaks[lo:hi].max()) if lo < len(arr_peaks) else 0.05
        peaks.append(round(max(0.03, min(1.0, val)), 3))
    return peaks


def detect_silence_and_active_segments(
    video_path: str | Path,
    duration_sec: float,
    noise_db: float = -35.0,
    min_silence_sec: float = 0.4,
    padding_sec: float = 0.12,
) -> tuple[list[TimeInterval], list[TimeInterval]]:
    """Run FFmpeg silencedetect to identify silent intervals and complementary active intervals."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-vn",
        "-i",
        str(video_path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_sec}",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stderr = res.stderr or ""

    # State-machine pairing handles negative timestamps, scientific notation (e.g. 1.2e-05), and EOF-open silences
    silent_intervals: list[TimeInterval] = []
    open_start: float | None = None
    for m in _SILENCE_EVENT_RE.finditer(stderr):
        kind = m.group(1)
        ts = float(m.group(2))
        if kind == "start":
            open_start = max(0.0, min(duration_sec, ts))
        elif kind == "end":
            s_val = open_start if open_start is not None else 0.0
            e_val = max(s_val, min(duration_sec, ts))
            open_start = None
            if e_val - s_val >= 0.05:
                silent_intervals.append(
                    TimeInterval(
                        start_sec=round(s_val, 3),
                        end_sec=round(e_val, 3),
                        duration_sec=round(e_val - s_val, 3),
                        label="silence",
                    )
                )

    if open_start is not None and duration_sec - open_start >= 0.05:
        silent_intervals.append(
            TimeInterval(
                start_sec=round(open_start, 3),
                end_sec=round(duration_sec, 3),
                duration_sec=round(duration_sec - open_start, 3),
                label="silence",
            )
        )

    # Derive active (non-silent) intervals with breathing padding
    active_intervals: list[TimeInterval] = []
    cursor = 0.0
    for sil in silent_intervals:
        if sil.start_sec - cursor >= 0.15:
            act_start = max(0.0, cursor - (padding_sec if cursor > 0 else 0.0))
            act_end = min(duration_sec, sil.start_sec + padding_sec)
            active_intervals.append(
                TimeInterval(
                    start_sec=round(act_start, 3),
                    end_sec=round(act_end, 3),
                    duration_sec=round(act_end - act_start, 3),
                    label="active",
                )
            )
        cursor = max(cursor, sil.end_sec)

    if duration_sec - cursor >= 0.15:
        act_start = max(0.0, cursor - (padding_sec if cursor > 0 else 0.0))
        act_end = duration_sec
        active_intervals.append(
            TimeInterval(
                start_sec=round(act_start, 3),
                end_sec=round(act_end, 3),
                duration_sec=round(act_end - act_start, 3),
                label="active",
            )
        )

    # Merge any overlapping padded active intervals
    merged_active: list[TimeInterval] = []
    for act in active_intervals:
        if merged_active and act.start_sec <= merged_active[-1].end_sec + 0.05:
            prev = merged_active[-1]
            new_end = max(prev.end_sec, act.end_sec)
            merged_active[-1] = TimeInterval(
                start_sec=prev.start_sec,
                end_sec=round(new_end, 3),
                duration_sec=round(new_end - prev.start_sec, 3),
                label="active",
            )
        else:
            merged_active.append(act)

    if not merged_active:
        merged_active = [
            TimeInterval(
                start_sec=0.0,
                end_sec=round(duration_sec, 3),
                duration_sec=round(duration_sec, 3),
                label="active",
            )
        ]

    return silent_intervals, merged_active


def detect_scene_changes(
    video_path: str | Path,
    threshold: float = 12.0,
) -> list[float]:
    """Run FFmpeg scdet filter to find visual scene cut timestamps."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-an",
        "-i",
        str(video_path),
        "-vf",
        f"scale=320:-2,scdet=threshold={threshold}:sc_pass=1",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stderr = res.stderr or ""
    cuts = [
        round(float(m.group(1)), 3)
        for m in re.finditer(r"lavfi\.scd\.time:\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)", stderr)
    ]
    return sorted(set(c for c in cuts if c > 0.1))


def transcribe_media_file(
    video_path: str | Path,
    model_size: str = "base",
    language: str | None = None,
) -> list[TranscriptSegment]:
    """Transcribe speech with word-level timestamps using faster-whisper (thread-safe GPU/CPU selection)."""
    from faster_whisper import WhisperModel

    use_cuda = _cuda_runtime_available()

    with _WHISPER_LOCK:
        cache_key = f"{model_size}:{'cuda' if use_cuda else 'cpu'}"
        model = _WHISPER_CACHE.get(cache_key)
        if model is None:
            if use_cuda:
                try:
                    model = WhisperModel(model_size, device="cuda", compute_type="float16")
                except Exception:
                    use_cuda = False
                    cache_key = f"{model_size}:cpu"
                    model = _WHISPER_CACHE.get(cache_key) or WhisperModel(
                        model_size, device="cpu", compute_type="int8"
                    )
            else:
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
            _WHISPER_CACHE[cache_key] = model

        try:
            segments_iter, _info = model.transcribe(
                str(video_path),
                language=language,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 350},
            )
            segments_list = list(segments_iter)
        except RuntimeError as exc:
            # Only retry on CPU if this was actually a CUDA/cuDNN runtime failure
            err_lower = str(exc).lower()
            if use_cuda and any(k in err_lower for k in ("cuda", "cublas", "cudnn", "gpu")):
                global _CUDA_AVAILABLE_CACHED
                _CUDA_AVAILABLE_CACHED = False
                cpu_key = f"{model_size}:cpu"
                model = _WHISPER_CACHE.get(cpu_key) or WhisperModel(
                    model_size, device="cpu", compute_type="int8"
                )
                _WHISPER_CACHE[cpu_key] = model
                segments_iter, _info = model.transcribe(
                    str(video_path),
                    language=language,
                    word_timestamps=True,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 350},
                )
                segments_list = list(segments_iter)
            else:
                raise

    results: list[TranscriptSegment] = []
    for seg in segments_list:
        txt = (seg.text or "").strip()
        if not txt:
            continue
        words: list[WordToken] = []
        if seg.words:
            for w in seg.words:
                w_txt = (w.word or "").strip()
                if not w_txt:
                    continue
                words.append(
                    WordToken(
                        word=w_txt,
                        start_sec=round(float(w.start), 3),
                        end_sec=round(float(w.end), 3),
                        probability=round(float(getattr(w, "probability", 1.0)), 3),
                    )
                )
        results.append(
            TranscriptSegment(
                id=new_id("seg"),
                start_sec=round(float(seg.start), 3),
                end_sec=round(float(seg.end), 3),
                text=txt,
                words=words,
            )
        )
    return results
