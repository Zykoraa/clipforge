"""Cross-platform OS helpers for GPU detection, fonts, ComfyUI discovery, and detached subprocesses."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"

_GPU_INFO_CACHE: dict[str, Any] | None = None
_FFMPEG_FONT_CACHE: dict[str, str] = {}
_ASS_FONT_CACHE: dict[str, tuple[str, bool]] = {}

_ICON_FONT_MARKERS = (
    "fontawesome",
    "font awesome",
    "emoji",
    "symbol",
    "dingbat",
    "wingding",
    "webding",
    "shapes",
    "icomoon",
    "material icons",
    "codicon",
)

# Logical font key -> Linux candidate font files (checked in order before fc-match)
_LINUX_FONT_CANDIDATES: dict[str, list[str]] = {
    "impact.ttf": [
        "/usr/share/fonts/TTF/impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/impact.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Black.ttf",
        "/usr/share/fonts/noto/NotoSans-ExtraBold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "arialbd.ttf": [
        "/usr/share/fonts/TTF/arialbd.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "arial.ttf": [
        "/usr/share/fonts/TTF/arial.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "segoeuib.ttf": [
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "consolab.ttf": [
        "/usr/share/fonts/noto/NotoSansMono-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ],
}

_LINUX_FCMATCH_PATTERNS: dict[str, str] = {
    "impact.ttf": "sans-serif:weight=bold",
    "arialbd.ttf": "sans-serif:weight=bold",
    "arial.ttf": "sans-serif",
    "segoeuib.ttf": "sans-serif:weight=bold",
    "consolab.ttf": "monospace:weight=bold",
}

_MACOS_FONT_CANDIDATES: dict[str, list[str]] = {
    "impact.ttf": [
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/Library/Fonts/Impact.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    "arialbd.ttf": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    "arial.ttf": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    "segoeuib.ttf": [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    "consolab.ttf": [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    ],
}

# Known Windows-only font names -> (Linux fontconfig fallback queries, force_bold)
_WINDOWS_FONT_LINUX_FALLBACKS: dict[str, tuple[list[str], bool]] = {
    "impact": (["Liberation Sans", "Noto Sans", "DejaVu Sans", "sans-serif"], True),
    "arial black": (["Liberation Sans", "Noto Sans", "DejaVu Sans", "sans-serif"], True),
    "arial": (["Liberation Sans", "Noto Sans", "DejaVu Sans", "sans-serif"], False),
    "segoe ui": (["Noto Sans", "Liberation Sans", "DejaVu Sans", "sans-serif"], False),
    "segoe ui bold": (["Noto Sans", "Liberation Sans", "DejaVu Sans", "sans-serif"], True),
    "segoe ui semibold": (["Noto Sans", "Liberation Sans", "DejaVu Sans", "sans-serif"], True),
    "consolas": (["Noto Sans Mono", "Liberation Mono", "DejaVu Sans Mono", "monospace"], False),
}


def detect_gpu_info() -> dict[str, Any]:
    """Detect primary NVIDIA GPU name & VRAM via nvidia-smi (cached, fast fallback if unavailable)."""
    global _GPU_INFO_CACHE
    if _GPU_INFO_CACHE is not None:
        return dict(_GPU_INFO_CACHE)

    info: dict[str, Any] = {
        "has_nvidia": False,
        "name": "",
        "short_name": "Local GPU",
        "vram_mb": 0,
    }
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            res = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                first_line = res.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in first_line.split(",")]
                if parts and parts[0]:
                    full_name = parts[0]
                    short = full_name
                    for prefix in ("NVIDIA GeForce ", "NVIDIA ", "GeForce "):
                        if short.startswith(prefix):
                            short = short[len(prefix) :]
                            break
                    vram = 0
                    if len(parts) > 1:
                        try:
                            vram = int(float(parts[1]))
                        except ValueError:
                            vram = 0
                    info = {
                        "has_nvidia": True,
                        "name": full_name,
                        "short_name": short or full_name,
                        "vram_mb": vram,
                    }
        except Exception:
            pass

    _GPU_INFO_CACHE = info
    return dict(info)


def detached_popen_kwargs() -> dict[str, Any]:
    """Return OS-appropriate subprocess.Popen kwargs to launch a detached background daemon."""
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        return {"creationflags": creationflags}
    return {"start_new_session": True, "stdin": subprocess.DEVNULL}


def clean_pyinstaller_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Strip PyInstaller _MEIPASS paths from environment so child processes (e.g. ComfyUI) never load bundled libs."""
    src = os.environ if base_env is None else base_env
    clean_env = {k: v for k, v in src.items() if not k.startswith("_MEIPASS")}
    meipass = getattr(sys, "_MEIPASS", None)

    def _strip_path_var(var_name: str, mp_norm: str) -> None:
        raw = clean_env.get(var_name)
        if not raw:
            return
        kept: list[str] = []
        for entry in raw.split(os.pathsep):
            if not entry:
                continue
            cmp_entry = entry.lower() if IS_WINDOWS else entry
            if cmp_entry.startswith(mp_norm):
                continue
            kept.append(entry)
        if kept:
            clean_env[var_name] = os.pathsep.join(kept)
        else:
            clean_env.pop(var_name, None)

    if meipass:
        mp_str = str(Path(meipass).resolve())
        mp_norm = mp_str.lower() if IS_WINDOWS else mp_str
        _strip_path_var("PATH", mp_norm)
        _strip_path_var("PYTHONPATH", mp_norm)
        if clean_env.get("PYTHONHOME"):
            ph = clean_env["PYTHONHOME"]
            if (ph.lower() if IS_WINDOWS else ph).startswith(mp_norm):
                clean_env.pop("PYTHONHOME", None)

        # PyInstaller on Linux/macOS overrides LD_LIBRARY_PATH / DYLD_LIBRARY_PATH and saves *_ORIG
        for lib_var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            orig_key = f"{lib_var}_ORIG"
            if orig_key in clean_env:
                orig_val = clean_env.pop(orig_key)
                if orig_val:
                    clean_env[lib_var] = orig_val
                else:
                    clean_env.pop(lib_var, None)
            else:
                _strip_path_var(lib_var, mp_norm)

    return clean_env


def resolve_default_comfyui_dir() -> Path:
    """Resolve the local ComfyUI installation directory from env var or OS-native defaults."""
    env_dir = os.environ.get("CLIPFORGE_COMFYUI_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()

    home = Path.home()
    if IS_WINDOWS:
        candidates = [
            Path(r"E:\ComfyUI"),
            Path(r"C:\ComfyUI"),
            home / "ComfyUI",
        ]
        default_dir = Path(r"E:\ComfyUI")
    else:
        candidates = [
            home / "CreationTools" / "ComfyUI",
            home / "ComfyUI",
            home / "comfy" / "ComfyUI",
            Path("/opt/ComfyUI"),
            home / ".local" / "share" / "ComfyUI",
        ]
        default_dir = home / "ComfyUI"

    for cand in candidates:
        if (cand / "main.py").exists():
            return cand
    for cand in candidates:
        if cand.exists():
            return cand
    return default_dir


def resolve_comfyui_python(comfy_dir: Path) -> Path | None:
    """Locate the Python interpreter inside a ComfyUI installation across Windows and POSIX layouts."""
    if IS_WINDOWS:
        candidates = [
            comfy_dir / ".venv" / "Scripts" / "python.exe",
            comfy_dir / "venv" / "Scripts" / "python.exe",
            comfy_dir.parent / "python_embeded" / "python.exe",
            comfy_dir / "python_embeded" / "python.exe",
        ]
    else:
        candidates = [
            comfy_dir / ".venv" / "bin" / "python",
            comfy_dir / ".venv" / "bin" / "python3",
            comfy_dir / "venv" / "bin" / "python",
            comfy_dir / "venv" / "bin" / "python3",
        ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _is_icon_font(family: str, filepath: str) -> bool:
    combined = f"{family} {filepath}".lower()
    return any(marker in combined for marker in _ICON_FONT_MARKERS)


def _fc_match_query(pattern: str) -> tuple[str, str] | None:
    """Query fontconfig fc-match and return (family, file_path) if available."""
    fc_match = shutil.which("fc-match")
    if not fc_match:
        return None
    try:
        res = subprocess.run(
            [fc_match, "-f", "%{family}\n%{file}\n", pattern],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
            if len(lines) >= 2:
                # Fontconfig may return comma-separated family aliases
                fam = lines[0].split(",")[0].strip()
                fpath = lines[1]
                return fam, fpath
    except Exception:
        pass
    return None


def _escape_ffmpeg_fontfile(p: Path) -> str:
    return p.as_posix().replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def resolve_ffmpeg_fontfile(preferred: str) -> str:
    """Resolve an OS font file path escaped for FFmpeg drawtext fontfile='...'."""
    key = (preferred or "arialbd.ttf").strip().lower()
    if key in _FFMPEG_FONT_CACHE:
        return _FFMPEG_FONT_CACHE[key]

    resolved = ""
    if IS_WINDOWS:
        candidates = [
            Path("C:/Windows/Fonts") / preferred,
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
        ]
        for c in candidates:
            if c.exists():
                resolved = _escape_ffmpeg_fontfile(c)
                break
    elif IS_MACOS:
        candidates = [
            Path(p)
            for p in (
                _MACOS_FONT_CANDIDATES.get(key, [])
                + _MACOS_FONT_CANDIDATES["arialbd.ttf"]
            )
        ]
        for c in candidates:
            if c.exists():
                resolved = _escape_ffmpeg_fontfile(c)
                break
    else:
        candidates = [
            Path(p)
            for p in (
                _LINUX_FONT_CANDIDATES.get(key, [])
                + _LINUX_FONT_CANDIDATES["arialbd.ttf"]
            )
        ]
        for c in candidates:
            if c.exists():
                resolved = _escape_ffmpeg_fontfile(c)
                break
        if not resolved:
            pattern = _LINUX_FCMATCH_PATTERNS.get(key, "sans-serif:weight=bold")
            matched = _fc_match_query(pattern)
            if matched:
                fam, fpath = matched
                p = Path(fpath)
                if p.exists() and not _is_icon_font(fam, fpath):
                    resolved = _escape_ffmpeg_fontfile(p)

    _FFMPEG_FONT_CACHE[key] = resolved
    return resolved


def resolve_ass_font_name(font_name: str) -> tuple[str, bool]:
    """Resolve a libass Fontname safely on Linux so missing Windows fonts never map to icon fonts (e.g. FontAwesome).

    Returns (resolved_font_name, force_bold).
    """
    if IS_WINDOWS or not font_name:
        return font_name, False

    key = font_name.strip().lower()
    if key in _ASS_FONT_CACHE:
        return _ASS_FONT_CACHE[key]

    matched = _fc_match_query(font_name)
    if matched:
        matched_fam, matched_path = matched
        fam_lower = matched_fam.lower()
        # Exact/prefix family match on a non-icon font -> the font is genuinely installed
        if not _is_icon_font(matched_fam, matched_path) and (
            fam_lower == key or fam_lower.startswith(key) or key.startswith(fam_lower)
        ):
            res = (font_name, False)
            _ASS_FONT_CACHE[key] = res
            return res

        # If this is a known Windows-only font (or fontconfig matched an icon font like FontAwesome), pick a clean fallback
        if key in _WINDOWS_FONT_LINUX_FALLBACKS or _is_icon_font(matched_fam, matched_path):
            fallback_list, force_bold = _WINDOWS_FONT_LINUX_FALLBACKS.get(
                key, (["Liberation Sans", "Noto Sans", "DejaVu Sans", "sans-serif"], False)
            )
            for candidate in fallback_list:
                fb_match = _fc_match_query(candidate)
                if fb_match and not _is_icon_font(fb_match[0], fb_match[1]):
                    res = (fb_match[0], force_bold)
                    _ASS_FONT_CACHE[key] = res
                    return res

    res = (font_name, False)
    _ASS_FONT_CACHE[key] = res
    return res
