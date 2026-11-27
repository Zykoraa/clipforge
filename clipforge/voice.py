"""Cross-platform Offline Speech & Friend Voice Cloning Engine (Kokoro-82M Neural Studio Voices + F5-TTS Cloning)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .generator import COMFYUI_DIR, COMFYUI_PYTHON
from .media import probe_media_file
from .platform_utils import clean_pyinstaller_env, resolve_comfyui_python

# Studio-grade real human neural voices (Kokoro-82M v1.0 ONNX, 24kHz)
KOKORO_VOICES: list[dict[str, str]] = [
    {"id": "am_michael", "label": "Michael · Deep Studio Male (US)", "lang": "en-us", "gender": "male"},
    {"id": "af_heart", "label": "Heart · Warm Natural Female (US)", "lang": "en-us", "gender": "female"},
    {"id": "am_adam", "label": "Adam · Viral Narrator Male (US)", "lang": "en-us", "gender": "male"},
    {"id": "af_bella", "label": "Bella · Expressive Female (US)", "lang": "en-us", "gender": "female"},
    {"id": "am_fenrir", "label": "Fenrir · Gritty Dramatic Male (US)", "lang": "en-us", "gender": "male"},
    {"id": "am_onyx", "label": "Onyx · Smooth Low Male (US)", "lang": "en-us", "gender": "male"},
    {"id": "am_puck", "label": "Puck · Energetic Playful Male (US)", "lang": "en-us", "gender": "male"},
    {"id": "af_sky", "label": "Sky · Bright Young Female (US)", "lang": "en-us", "gender": "female"},
    {"id": "af_nicole", "label": "Nicole · Soft Intimate Female (US)", "lang": "en-us", "gender": "female"},
    {"id": "bm_george", "label": "George · British Documentary Male (UK)", "lang": "en-gb", "gender": "male"},
    {"id": "bf_emma", "label": "Emma · Natural British Female (UK)", "lang": "en-gb", "gender": "female"},
    {"id": "bm_lewis", "label": "Lewis · Smooth British Male (UK)", "lang": "en-gb", "gender": "male"},
]

_LEGACY_PRESET_MAP: dict[str, str] = {
    "auto": "am_michael",
    "male_deep": "am_michael",
    "female_clear": "af_heart",
    "hype_fast": "am_puck",
    "dramatic_slow": "am_fenrir",
}

SPEECH_ACOUSTIC_FX: dict[str, str] = {
    "studio": "highpass=f=65,loudnorm=I=-16:TP=-1.5:LRA=11",
    "cinematic": (
        "highpass=f=55,equalizer=f=110:t=q:w=1.2:g=3.5,"
        "equalizer=f=3200:t=q:w=1.4:g=2.0,aecho=0.8:0.88:45:0.18,"
        "loudnorm=I=-15:TP=-1.5:LRA=10"
    ),
    "vintage_radio": (
        "highpass=f=320,lowpass=f=3400,"
        "acompressor=threshold=-20dB:ratio=4:attack=5:release=60,"
        "equalizer=f=1400:t=q:w=1.5:g=4.0,loudnorm=I=-16:TP=-1.5:LRA=9"
    ),
    "intimate_whisper": (
        "highpass=f=80,equalizer=f=220:t=q:w=1.2:g=2.5,"
        "equalizer=f=6500:t=q:w=1.5:g=3.0,"
        "acompressor=threshold=-24dB:ratio=3:attack=8:release=120,"
        "loudnorm=I=-16:TP=-1.5:LRA=10"
    ),
    "hype_broadcast": (
        "highpass=f=75,equalizer=f=140:t=q:w=1.1:g=3.0,"
        "equalizer=f=4200:t=q:w=1.2:g=3.5,"
        "acompressor=threshold=-16dB:ratio=4.5:attack=4:release=50,"
        "loudnorm=I=-14:TP=-1.2:LRA=8"
    ),
    "spooky_hall": (
        "highpass=f=70,lowpass=f=7500,aecho=0.8:0.85:90|160:0.32|0.22,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    ),
}


def pick_kokoro_voice_for_style(
    speech_style: str = "",
    gender: str = "auto",
    requested_preset: str = "auto",
    take_idx: int = 0,
) -> tuple[str, float, str]:
    """Match a Kokoro-82M voice, natural cadence speed, and acoustic EQ chain to Suno-style delivery prompts."""
    low = (speech_style or "").lower()
    req = (requested_preset or "auto").strip().lower()
    g = (gender or "auto").strip().lower()

    if any(k in low for k in ("radio", "1920", "1940", "vintage", "old-time", "telephone", "walkie")):
        fx_key = "vintage_radio"
    elif any(k in low for k in ("trailer", "cinematic", "epic", "movie", "dramatic", "gravitas")):
        fx_key = "cinematic"
    elif any(k in low for k in ("whisper", "asmr", "intimate", "calm", "bedtime", "soothing", "soft", "meditat")):
        fx_key = "intimate_whisper"
    elif any(k in low for k in ("hype", "announcer", "commercial", "ad ", "ad,", "sports", "breaking", "urgent")):
        fx_key = "hype_broadcast"
    elif any(k in low for k in ("spooky", "horror", "creepy", "ghost", "haunted", "dark story", "chilling")):
        fx_key = "spooky_hall"
    else:
        fx_key = "studio"

    # Respect an explicit Kokoro voice ID if the user chose one directly
    if req and req not in ("auto", "default") and any(v["id"] == req for v in KOKORO_VOICES):
        chosen = req
    else:
        is_uk = any(k in low for k in ("british", "uk", "london", "bbc", "documentary", "transatlantic", "museum"))
        if g == "female":
            if is_uk:
                pool = ["bf_emma", "af_heart"]
            elif fx_key == "intimate_whisper":
                pool = ["af_nicole", "af_sky", "af_heart"]
            else:
                pool = ["af_heart", "af_bella", "af_sky", "bf_emma"]
        elif g == "male":
            if is_uk:
                pool = ["bm_george", "bm_lewis", "am_michael"]
            elif fx_key in ("cinematic", "spooky_hall"):
                pool = ["am_fenrir", "am_michael", "am_onyx"]
            elif fx_key == "hype_broadcast":
                pool = ["am_puck", "am_adam", "am_michael"]
            else:
                pool = ["am_michael", "am_adam", "am_onyx", "am_fenrir"]
        else:
            if is_uk:
                pool = ["bm_george", "bf_emma", "bm_lewis"]
            elif fx_key == "cinematic":
                pool = ["am_fenrir", "am_michael", "am_onyx"]
            elif fx_key == "intimate_whisper":
                pool = ["af_heart", "af_nicole", "bm_lewis"]
            elif fx_key == "hype_broadcast":
                pool = ["am_puck", "af_bella", "am_adam"]
            elif fx_key == "spooky_hall":
                pool = ["am_onyx", "af_nicole", "bm_george"]
            else:
                pool = ["am_michael", "af_heart", "am_adam", "af_bella"]
        chosen = pool[take_idx % len(pool)]

    if fx_key in ("cinematic", "spooky_hall") or any(k in low for k in ("slow", "dramatic", "pauses")):
        sug_speed = 0.90
    elif fx_key == "intimate_whisper" or any(k in low for k in ("calm", "meditat", "soothing", "bedtime")):
        sug_speed = 0.92
    elif fx_key == "hype_broadcast" or any(k in low for k in ("fast", "urgent", "hype", "excited")):
        sug_speed = 1.12
    else:
        sug_speed = 1.0

    return chosen, sug_speed, fx_key

_KOKORO_LOCK = threading.Lock()
_KOKORO_INSTANCE: Any = None
_KOKORO_DIR_KEY: str = ""


def _kokoro_paths(comfy_dir: Path = COMFYUI_DIR) -> tuple[Path, Path]:
    base = comfy_dir / "models" / "kokoro"
    return base / "kokoro-v1.0.onnx", base / "voices-v1.0.bin"


def is_kokoro_ready(comfy_dir: Path = COMFYUI_DIR) -> bool:
    onnx_p, voices_p = _kokoro_paths(comfy_dir)
    return (
        onnx_p.exists()
        and onnx_p.stat().st_size > 10 * 1024 * 1024
        and voices_p.exists()
        and voices_p.stat().st_size > 1 * 1024 * 1024
    )


def _get_kokoro(comfy_dir: Path = COMFYUI_DIR) -> Any:
    global _KOKORO_INSTANCE, _KOKORO_DIR_KEY
    onnx_p, voices_p = _kokoro_paths(comfy_dir)
    key = str(onnx_p.parent.resolve())
    with _KOKORO_LOCK:
        if _KOKORO_INSTANCE is not None and _KOKORO_DIR_KEY == key:
            return _KOKORO_INSTANCE
        from kokoro_onnx import Kokoro

        _KOKORO_INSTANCE = Kokoro(str(onnx_p), str(voices_p))
        _KOKORO_DIR_KEY = key
        return _KOKORO_INSTANCE


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
    """Return studio neural human voices (Kokoro-82M v1.0)."""
    return list(KOKORO_VOICES)


def get_voice_cloner_status(comfy_dir: Path = COMFYUI_DIR) -> dict[str, Any]:
    """Check whether F5-TTS voice cloning and Kokoro-82M neural human voices are ready."""
    kokoro_ok = is_kokoro_ready(comfy_dir)
    os_tts_ok = sys.platform in ("win32", "darwin") or bool(shutil.which("espeak-ng") or shutil.which("espeak"))
    py_exe = _resolve_voice_python()
    worker_script = _resolve_voice_worker_script()
    if py_exe is None or worker_script is None:
        return {
            "ready": False,
            "kokoro_ready": kokoro_ok,
            "builtin_tts_ready": kokoro_ok or os_tts_ok,
            "builtin_voices": list_builtin_voices(),
            "engine": "f5-tts",
            "reason": f"ComfyUI Python venv or voice_worker.py not found (COMFYUI_DIR={comfy_dir}).",
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
            "kokoro_ready": kokoro_ok,
            "builtin_tts_ready": kokoro_ok or os_tts_ok,
            "builtin_voices": list_builtin_voices(),
            "engine": "f5-tts",
            "reason": None if ok else f"f5-tts not installed in {py_exe.parent.parent}",
        }
    except Exception as exc:
        return {
            "ready": False,
            "kokoro_ready": kokoro_ok,
            "builtin_tts_ready": kokoro_ok or os_tts_ok,
            "builtin_voices": list_builtin_voices(),
            "engine": "f5-tts",
            "reason": str(exc),
        }


def _write_float32_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = np.clip(arr * 32767.0, -32768.0, 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())


def synthesize_speech_offline(
    text: str,
    output_dir: Path,
    voice_preset: str = "am_michael",
    speed: float = 1.0,
    comfy_dir: Path = COMFYUI_DIR,
    acoustic_fx: str = "studio",
) -> dict[str, Any]:
    """Synthesize realistic human speech completely offline using Kokoro-82M neural voices (with OS TTS fallback)."""
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("Speech text cannot be empty.")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    raw_wav = (output_dir / f"_tts_raw_{run_id}.wav").resolve()
    out_wav = (output_dir / f"speech_{run_id}.wav").resolve()

    preset_raw = (voice_preset or "am_michael").strip().lower()
    kokoro_voice = _LEGACY_PRESET_MAP.get(preset_raw, preset_raw)
    voice_meta = next((v for v in KOKORO_VOICES if v["id"] == kokoro_voice), KOKORO_VOICES[0])
    kokoro_voice = voice_meta["id"]

    eff_speed = max(0.65, min(1.65, float(speed)))
    if preset_raw == "hype_fast" and abs(eff_speed - 1.0) < 0.05:
        eff_speed = 1.18
    elif preset_raw == "dramatic_slow" and abs(eff_speed - 1.0) < 0.05:
        eff_speed = 0.88

    t0 = time.perf_counter()
    engine_name = ""

    try:
        # 1. Preferred: Real Neural Studio Human Voices (Kokoro-82M v1.0 ONNX, 24kHz)
        if is_kokoro_ready(comfy_dir):
            try:
                kokoro = _get_kokoro(comfy_dir)
                samples, sr = kokoro.create(
                    clean_text,
                    voice=kokoro_voice,
                    speed=eff_speed,
                    lang=voice_meta["lang"],
                )
                _write_float32_wav(raw_wav, samples, sr)
                engine_name = f"kokoro_82m:{kokoro_voice}"
            except Exception:
                engine_name = ""

        # 2. Fallback only if Kokoro weights aren't downloaded yet
        if not engine_name:
            want_female = voice_meta["gender"] == "female"
            if sys.platform == "win32":
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
                        raise RuntimeError(f"Offline TTS failed: {(res.stderr or res.stdout or '')[-400:]}")
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
                    raise RuntimeError("Download 'Real Neural Voices (Kokoro-82M)' (350 MB) first for studio human speech.")
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

        # Clean studio broadcast polish + delivery-matched acoustic EQ chain
        af_chain = SPEECH_ACOUSTIC_FX.get((acoustic_fx or "studio").strip().lower(), SPEECH_ACOUSTIC_FX["studio"])
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
            "voice_preset": kokoro_voice,
            "voice_label": voice_meta["label"],
            "duration_sec": round(float(probed.duration_sec or 1.5), 2),
            "generation_time_sec": elapsed,
            "engine": engine_name,
        }
    finally:
        raw_wav.unlink(missing_ok=True)


def synthesize_procedural_score(
    output_path: Path,
    duration_sec: float,
    mood_prompt: str = "",
    seed: int = -1,
) -> Path:
    """Fast (<0.3s) zero-dependency stereo harmonic ambient underscore tuned to mood keywords."""
    sr = 44100
    dur = max(3.0, float(duration_sec))
    n = int(round(sr * dur))
    t = np.linspace(0.0, dur, n, endpoint=False, dtype=np.float32)

    low = (mood_prompt or "").lower()
    if any(k in low for k in ("dramatic", "cinema", "epic", "trailer", "orchestr", "brass", "hero")):
        # D minor dramatic progression: Dm -> Bb -> Gm -> A
        chords = [(146.83, 220.00, 261.63), (116.54, 174.61, 233.08), (130.81, 196.00, 233.08), (110.00, 164.81, 220.00)]
        warmth_lpf = 0.35
        pulse_hz = 1.6
    elif any(k in low for k in ("dark", "suspense", "horror", "creepy", "crime", "mystery", "noir")):
        # E minor brooding tension drone
        chords = [(82.41, 123.47, 155.56), (82.41, 116.54, 155.56), (73.42, 110.00, 146.83), (82.41, 123.47, 146.83)]
        warmth_lpf = 0.20
        pulse_hz = 0.85
    elif any(k in low for k in ("sad", "piano", "rain", "melanchol", "heartbreak")):
        # A minor felt ballad: Am -> F -> C -> Em
        chords = [(110.00, 220.00, 261.63), (87.31, 174.61, 220.00), (130.81, 261.63, 329.63), (98.00, 196.00, 246.94)]
        warmth_lpf = 0.40
        pulse_hz = 0.65
    elif any(k in low for k in ("upbeat", "happy", "ad", "commercial", "fun", "funk", "pop", "synth")):
        # C major bright uplifting groove: C -> G -> Am -> F
        chords = [(130.81, 261.63, 329.63), (98.00, 196.00, 246.94), (110.00, 220.00, 261.63), (87.31, 174.61, 220.00)]
        warmth_lpf = 0.55
        pulse_hz = 2.0
    else:
        # Smooth lo-fi / midnight podcast Rhodes: Fmaj7 -> Em7 -> Dm7 -> Cmaj7
        chords = [(174.61, 220.00, 261.63), (164.81, 196.00, 246.94), (146.83, 174.61, 220.00), (130.81, 164.81, 246.94)]
        warmth_lpf = 0.45
        pulse_hz = 1.25

    chord_len = dur / max(1, len(chords) * 2)
    phase_idx = np.clip((t / max(0.5, chord_len)).astype(np.int32) % len(chords), 0, len(chords) - 1)
    # Soft boundary crossfade envelope per chord cell
    cell_pos = (t % max(0.5, chord_len)) / max(0.5, chord_len)
    cell_env = np.sin(np.pi * cell_pos) ** 0.35

    f_root = np.array([chords[i][0] for i in range(len(chords))], dtype=np.float32)[phase_idx]
    f_third = np.array([chords[i][1] for i in range(len(chords))], dtype=np.float32)[phase_idx]
    f_fifth = np.array([chords[i][2] for i in range(len(chords))], dtype=np.float32)[phase_idx]

    sub = 0.42 * np.sin(2.0 * np.pi * f_root * 0.5 * t)
    pad_l = (
        0.24 * np.sin(2.0 * np.pi * f_root * t)
        + 0.20 * np.sin(2.0 * np.pi * f_third * 1.002 * t)
        + 0.16 * np.sin(2.0 * np.pi * f_fifth * 0.998 * t)
        + warmth_lpf * 0.08 * np.sin(2.0 * np.pi * f_third * 2.0 * t)
    )
    pad_r = (
        0.24 * np.sin(2.0 * np.pi * f_root * 0.999 * t)
        + 0.20 * np.sin(2.0 * np.pi * f_third * 0.997 * t + 0.4)
        + 0.16 * np.sin(2.0 * np.pi * f_fifth * 1.003 * t + 0.7)
        + warmth_lpf * 0.08 * np.sin(2.0 * np.pi * f_fifth * 2.0 * t)
    )

    swell = 0.80 + 0.20 * np.sin(2.0 * np.pi * pulse_hz * t)
    fade_in = np.clip(t / min(0.8, dur * 0.2), 0.0, 1.0)
    fade_out = np.clip((dur - t) / min(1.5, dur * 0.25), 0.0, 1.0)
    master_env = cell_env * swell * fade_in * fade_out

    left = (sub + pad_l) * master_env
    right = (sub + pad_r) * master_env
    peak = float(max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-4))
    scale = 0.45 / peak
    stereo = np.stack([left * scale, right * scale], axis=1)
    pcm = np.clip(stereo * 32767.0, -32768.0, 32767.0).astype("<i2")

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return out


def mix_speech_with_background_music(
    speech_wav: Path,
    music_path: Path,
    output_path: Path,
    music_volume: float = 0.34,
    intro_sec: float = 0.85,
    outro_sec: float = 1.9,
) -> dict[str, Any]:
    """Blend spoken audio + background music with FFmpeg sidechain auto-ducking & -14 LUFS broadcast mastering."""
    sp = Path(speech_wav).resolve()
    mu = Path(music_path).resolve()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    sp_info = probe_media_file(sp, assets_dir=None)
    sp_dur = max(0.8, float(sp_info.duration_sec or 3.0))
    intro = max(0.0, float(intro_sec))
    outro = max(0.4, float(outro_sec))
    total_dur = intro + sp_dur + outro
    delay_ms = int(round(intro * 1000))
    mu_vol = max(0.06, min(0.95, float(music_volume)))
    fade_out_start = max(0.4, total_dur - min(1.5, outro))

    fc = (
        f"[0:a]aresample=44100,aformat=channel_layouts=stereo,"
        f"adelay={delay_ms}|{delay_ms},apad=whole_dur={total_dur:.3f},asplit=2[v_main][v_sc];"
        f"[1:a]aresample=44100,aformat=channel_layouts=stereo,"
        f"aloop=loop=-1:size=2000000000,atrim=0:{total_dur:.3f},"
        f"lowpass=f=11500,volume={mu_vol:.3f},"
        f"afade=t=in:st=0:d=0.60,afade=t=out:st={fade_out_start:.3f}:d={min(1.5, outro):.3f}[m_pre];"
        f"[m_pre][v_sc]sidechaincompress=threshold=0.025:ratio=5:attack=35:release=420:makeup=1[m_duck];"
        f"[v_main][m_duck]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
        f"loudnorm=I=-14:TP=-1.0:LRA=10[outa]"
    )
    codec_args = ["-c:a", "libmp3lame", "-b:a", "320k"] if out.suffix.lower() == ".mp3" else ["-c:a", "pcm_s16le"]
    res = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(sp),
            "-i", str(mu),
            "-filter_complex", fc,
            "-map", "[outa]",
            "-t", f"{total_dur:.3f}",
            *codec_args,
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0 or not out.exists() or out.stat().st_size < 512:
        raise RuntimeError(f"Background music mix failed: {(res.stderr or '')[-500:]}")

    probed = probe_media_file(out, assets_dir=None)
    return {
        "audio_path": str(out),
        "filename": out.name,
        "duration_sec": round(float(probed.duration_sec or total_dur), 2),
    }


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
