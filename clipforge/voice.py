"""Cross-platform Offline Speech & Friend Voice Cloning Engine (F5-TTS + Built-In Offline TTS)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .generator import COMFYUI_DIR, COMFYUI_PYTHON
from .media import probe_media_file
from .platform_utils import clean_pyinstaller_env, resolve_comfyui_python

BUILTIN_TTS_VOICES: list[dict[str, str]] = [
    {"id": "auto", "label": "Default Narrator", "hint": "male"},
    {"id": "male_deep", "label": "Male Narrator (Deep)", "hint": "male"},
    {"id": "female_clear", "label": "Female Narrator (Clear)", "hint": "female"},
    {"id": "hype_fast", "label": "Fast Meme Announcer", "hint": "male"},
    {"id": "dramatic_slow", "label": "Dramatic Documentary", "hint": "male"},
]


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


def list_builtin_voices() -> list[dict[str, str]]:
    """Return built-in instant offline voice presets (work with zero model download)."""
    return list(BUILTIN_TTS_VOICES)


def get_voice_cloner_status() -> dict[str, Any]:
    """Check whether F5-TTS voice cloning is ready in the local ComfyUI Python environment."""
    builtin_ok = sys.platform in ("win32", "darwin") or bool(shutil.which("espeak-ng") or shutil.which("espeak"))
    py_exe = _resolve_voice_python()
    worker_script = _resolve_voice_worker_script()
    if py_exe is None or worker_script is None:
        return {
            "ready": False,
            "builtin_tts_ready": builtin_ok,
            "builtin_voices": list_builtin_voices(),
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
            "builtin_tts_ready": builtin_ok,
            "builtin_voices": list_builtin_voices(),
            "engine": "f5-tts",
            "reason": None if ok else f"f5-tts not installed in {py_exe.parent.parent}",
        }
    except Exception as exc:
        return {
            "ready": False,
            "builtin_tts_ready": builtin_ok,
            "builtin_voices": list_builtin_voices(),
            "engine": "f5-tts",
            "reason": str(exc),
        }


def synthesize_speech_offline(
    text: str,
    output_dir: Path,
    voice_preset: str = "auto",
    speed: float = 1.0,
) -> dict[str, Any]:
    """Instant zero-download offline TTS using native OS speech engine (Windows SAPI / macOS say / Linux espeak-ng)."""
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("Speech text cannot be empty.")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    raw_wav = (output_dir / f"_tts_raw_{run_id}.wav").resolve()
    out_wav = (output_dir / f"speech_{run_id}.wav").resolve()

    preset = (voice_preset or "auto").strip().lower()
    eff_speed = max(0.6, min(1.75, float(speed)))
    if preset == "hype_fast" and abs(eff_speed - 1.0) < 0.05:
        eff_speed = 1.22
    elif preset == "dramatic_slow" and abs(eff_speed - 1.0) < 0.05:
        eff_speed = 0.86

    want_female = preset == "female_clear"
    t0 = time.perf_counter()

    try:
        if sys.platform == "win32":
            # Native Windows SAPI System.Speech.Synthesis (completely offline, instant, clean WAV)
            # Rate is -10..+10 (0 = 1.0x)
            sapi_rate = max(-6, min(6, int(round((eff_speed - 1.0) * 8.0))))
            gender_hint = "Female" if want_female else "Male"
            txt_file = (output_dir / f"_tts_txt_{run_id}.txt").resolve()
            txt_file.write_text(clean_text, encoding="utf-8")
            try:
                ps_script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$voices = $s.GetInstalledVoices() | Where-Object { $_.Enabled }; "
                    f"$picked = $voices | Where-Object {{ $_.VoiceInfo.Gender -eq '{gender_hint}' }} | Select-Object -First 1; "
                    "if ($picked) { $s.SelectVoice($picked.VoiceInfo.Name) }; "
                    f"$s.Rate = {sapi_rate}; "
                    f"$s.SetOutputToWaveFile('{str(raw_wav).replace(chr(39), chr(39)*2)}'); "
                    f"$t = [System.IO.File]::ReadAllText('{str(txt_file).replace(chr(39), chr(39)*2)}', [System.Text.Encoding]::UTF8); "
                    "$s.Speak($t); "
                    "$s.Dispose();"
                )
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if res.returncode != 0 or not raw_wav.exists() or raw_wav.stat().st_size < 256:
                    raise RuntimeError(f"Windows offline TTS failed: {(res.stderr or res.stdout or '')[-400:]}")
            finally:
                txt_file.unlink(missing_ok=True)
            engine_name = "windows_sapi"
        elif sys.platform == "darwin" and shutil.which("say"):
            tmp_aiff = (output_dir / f"_tts_raw_{run_id}.aiff").resolve()
            wpm = max(110, min(280, int(round(175 * eff_speed))))
            voice_name = "Samantha" if want_female else "Alex"
            try:
                res = subprocess.run(
                    ["say", "-v", voice_name, "-r", str(wpm), "-o", str(tmp_aiff), clean_text],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if res.returncode != 0 or not tmp_aiff.exists():
                    subprocess.run(["say", "-r", str(wpm), "-o", str(tmp_aiff), clean_text], check=True, timeout=60)
                subprocess.run(
                    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_aiff), str(raw_wav)],
                    check=True,
                    timeout=30,
                )
            finally:
                tmp_aiff.unlink(missing_ok=True)
            engine_name = "macos_say"
        else:
            espeak_bin = shutil.which("espeak-ng") or shutil.which("espeak")
            if not espeak_bin:
                raise RuntimeError("No offline TTS engine found (install `espeak-ng` or attach a friend voice clip for F5-TTS).")
            wpm = max(100, min(280, int(round(165 * eff_speed))))
            v_arg = "en-us+f3" if want_female else "en-us+m3"
            res = subprocess.run(
                [espeak_bin, "-v", v_arg, "-s", str(wpm), "-w", str(raw_wav), clean_text],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode != 0 or not raw_wav.exists():
                raise RuntimeError(f"espeak offline TTS failed: {(res.stderr or '')[-400:]}")
            engine_name = "espeak_ng"

        # Normalize to clean 24kHz mono WAV with subtle pitch polish for deep/dramatic presets
        af_chain = "highpass=f=70,dynaudnorm=f=150:g=9"
        if preset == "male_deep" or preset == "dramatic_slow":
            af_chain = "asetrate=24000*0.92,aresample=24000,atempo=1.087," + af_chain

        ff = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(raw_wav),
                "-ar", "24000", "-ac", "1",
                "-af", af_chain,
                "-c:a", "pcm_s16le",
                str(out_wav),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if ff.returncode != 0 or not out_wav.exists() or out_wav.stat().st_size < 256:
            raw_wav.replace(out_wav)

        elapsed = round(time.perf_counter() - t0, 2)
        probed = probe_media_file(out_wav, assets_dir=None)
        return {
            "audio_path": str(out_wav),
            "filename": out_wav.name,
            "text": clean_text,
            "voice_preset": preset,
            "duration_sec": round(float(probed.duration_sec or 1.5), 2),
            "generation_time_sec": elapsed,
            "engine": engine_name,
        }
    finally:
        raw_wav.unlink(missing_ok=True)


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
