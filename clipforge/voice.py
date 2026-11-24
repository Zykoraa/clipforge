"""Cross-platform Offline Friend Voice Cloning Client (runs F5-TTS inside the local ComfyUI venv)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .generator import COMFYUI_DIR, COMFYUI_PYTHON
from .media import probe_media_file
from .platform_utils import clean_pyinstaller_env, resolve_comfyui_python


def _resolve_voice_worker_script() -> Path | None:
    """Locate bundled voice_worker.py across source runs, PyInstaller bundles, and ComfyUI dir."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "clipforge" / "voice_worker.py")
    candidates.append(Path(__file__).resolve().parent / "voice_worker.py")
    candidates.append(COMFYUI_DIR / "voice_worker.py")
    for cand in candidates:
        if cand.exists() and cand.is_file():
            return cand
    return None


def _resolve_voice_python() -> Path | None:
    py = resolve_comfyui_python(COMFYUI_DIR)
    if py is not None and py.exists():
        return py
    if COMFYUI_PYTHON.exists():
        return COMFYUI_PYTHON
    return None


def _clean_child_env() -> dict[str, str]:
    clean = clean_pyinstaller_env()
    tmp_dir = COMFYUI_DIR / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    clean["HF_HOME"] = str(COMFYUI_DIR / ".hf-cache")
    clean["TMP"] = str(tmp_dir)
    clean["TEMP"] = str(tmp_dir)
    clean["TMPDIR"] = str(tmp_dir)
    clean["PYTHONUTF8"] = "1"
    return clean


def get_voice_cloner_status() -> dict[str, Any]:
    """Check whether F5-TTS voice cloning is ready in the local ComfyUI Python environment."""
    py_exe = _resolve_voice_python()
    worker_script = _resolve_voice_worker_script()
    if py_exe is None or worker_script is None:
        return {
            "ready": False,
            "engine": "f5-tts",
            "reason": f"ComfyUI Python venv or voice_worker.py not found (COMFYUI_DIR={COMFYUI_DIR}).",
        }
    try:
        res = subprocess.run(
            [str(py_exe), "-c", "import f5_tts; print('OK')"],
            capture_output=True,
            text=True,
            timeout=10,
            env=_clean_child_env(),
        )
        ok = res.returncode == 0 and "OK" in (res.stdout or "")
        return {
            "ready": ok,
            "engine": "f5-tts",
            "reason": None if ok else f"f5-tts not installed in {py_exe.parent.parent}",
        }
    except Exception as exc:
        return {"ready": False, "engine": "f5-tts", "reason": str(exc)}


def clone_voice_offline(
    text: str,
    ref_audio_path: str | Path,
    output_dir: Path,
    ref_text: str = "",
    speed: float = 1.0,
    timeout_sec: float = 300.0,
) -> dict[str, Any]:
    """Synthesize custom speech in a friend's cloned voice completely offline on the local GPU."""
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("Dialogue text cannot be empty.")

    ref_src = Path(ref_audio_path).expanduser().resolve()
    if not ref_src.exists() or not ref_src.is_file():
        raise FileNotFoundError(f"Reference voice audio not found: {ref_src}")

    py_exe = _resolve_voice_python()
    worker_script = _resolve_voice_worker_script()
    if py_exe is None or worker_script is None:
        raise RuntimeError(f"Offline voice cloner runtime not found (COMFYUI_DIR={COMFYUI_DIR}).")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    out_wav = (output_dir / f"voice_{run_id}.wav").resolve()
    tmp_ref_wav = (output_dir / f"_ref_{run_id}.wav").resolve()

    # Normalize reference clip to clean <=12s 24kHz mono WAV
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(ref_src),
            "-vn",
            "-t",
            "12.0",
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(tmp_ref_wav),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    t0 = time.perf_counter()
    try:
        cmd = [
            str(py_exe),
            str(worker_script),
            "--ref-audio",
            str(tmp_ref_wav),
            "--ref-text",
            (ref_text or "").strip(),
            "--gen-text",
            clean_text,
            "--out-wav",
            str(out_wav),
            "--speed",
            f"{max(0.5, min(1.8, float(speed))):.2f}",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=_clean_child_env(),
        )
        if res.returncode != 0 or not out_wav.exists():
            raise RuntimeError(f"Voice cloning failed: {(res.stderr or res.stdout or '')[-900:]}")

        elapsed = round(time.perf_counter() - t0, 2)
        probed = probe_media_file(out_wav, assets_dir=None)
        worker_meta: dict[str, Any] = {}
        for ln in reversed((res.stdout or "").splitlines()):
            if ln.startswith("RESULT_JSON:"):
                try:
                    worker_meta = json.loads(ln[len("RESULT_JSON:") :])
                except Exception:
                    pass
                break

        return {
            "audio_path": str(out_wav),
            "filename": out_wav.name,
            "text": clean_text,
            "duration_sec": probed.duration_sec,
            "generation_time_sec": elapsed,
            "engine": "f5-tts",
            "detected_ref_text": worker_meta.get("ref_text", ref_text),
        }
    finally:
        tmp_ref_wav.unlink(missing_ok=True)
