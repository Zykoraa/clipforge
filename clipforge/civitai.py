"""CivitAI Live Browser, URL Inspector, Curated Community Picks, and Resumable Model/LoRA Installer."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from .generator import COMFYUI_DIR, save_lora_trigger

CIVITAI_API_BASE = "https://civitai.com/api/v1"
_ALLOWED_CIVITAI_HOSTS = {"civitai.com", "www.civitai.com"}
_ALLOWED_MODEL_EXTS = {".safetensors", ".gguf", ".ckpt", ".pt", ".pth"}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Verified popular community models & LoRAs on CivitAI tailored to ClipForge's native architectures
CURATED_CIVITAI_PICKS: list[dict[str, Any]] = [
    {
        "model_id": 573152,
        "name": "LUSTIFY! (SDXL Uncensored Photo)",
        "model_type": "Checkpoint",
        "base_model": "SDXL 1.0",
        "target_subdir": "checkpoints",
        "family": "illustrious",
        "suggested_model": "lustify_sdxl",
        "badge": "UNCENSORED PHOTO",
        "tagline": "#1 raw candid uncensored photorealism checkpoint — authentic phone lighting & real skin texture.",
    },
    {
        "model_id": 575395,
        "name": "Big Lust v1.6 (SDXL Uncensored)",
        "model_type": "Checkpoint",
        "base_model": "SDXL 1.0",
        "target_subdir": "checkpoints",
        "family": "illustrious",
        "suggested_model": "lustify_sdxl",
        "badge": "UNCENSORED REAL",
        "tagline": "Ultra-realistic uncensored SDXL merge with sharp faces, dramatic lighting, and zero content scrubbing.",
    },
    {
        "model_id": 372465,
        "name": "Pony Realism (Uncensored Poses)",
        "model_type": "Checkpoint",
        "base_model": "Pony",
        "target_subdir": "checkpoints",
        "family": "illustrious",
        "suggested_model": "pony_realism",
        "badge": "UNCENSORED POSES",
        "tagline": "Handles wild multi-person poses, chaotic meme scenes, and unfiltered realism with zero refusal.",
    },
    {
        "model_id": 2299142,
        "name": "Smooth Mix Wan 2.2 14B GGUF",
        "model_type": "Checkpoint",
        "base_model": "Wan Video 2.2",
        "target_subdir": "diffusion_models",
        "family": "wan",
        "suggested_model": "wan22_smoothmix_i2v",
        "badge": "UNCENSORED VIDEO",
        "tagline": "Most-downloaded uncensored Wan 2.2 I2V 14B model — fluid skin motion and natural physics out of the box.",
    },
    {
        "model_id": 2472759,
        "name": "Wan 2.2 Remix 14B GGUF",
        "model_type": "Checkpoint",
        "base_model": "Wan Video 2.2",
        "target_subdir": "diffusion_models",
        "family": "wan",
        "suggested_model": "wan22_remix_i2v",
        "badge": "UNCENSORED VIDEO",
        "tagline": "Community favorite unfiltered Wan 2.2 I2V fine-tune with crisp prompt adherence and zero LoRAs needed.",
    },
    {
        "model_id": 1981116,
        "name": "DaSiWa WAN 2.2 I2V 14B",
        "model_type": "Checkpoint",
        "base_model": "Wan Video 2.2",
        "target_subdir": "diffusion_models",
        "family": "wan",
        "suggested_model": "wan22_i2v",
        "badge": "HIGH-ACTION VIDEO",
        "tagline": "High-action uncensored Wan 2.2 14B I2V checkpoint built for dynamic movement & expressive reactions.",
    },
    {
        "model_id": 2237711,
        "name": "Zenith Z-Image Turbo",
        "model_type": "Checkpoint",
        "base_model": "ZImageTurbo",
        "target_subdir": "diffusion_models",
        "family": "z_image",
        "suggested_model": "z_image_turbo",
        "badge": "TOP REALISM ZiT",
        "tagline": "Community #1 Z-Image-Turbo fine-tune for candid photorealism, lighting, and skin texture.",
    },
    {
        "model_id": 2221503,
        "name": "Stable Yogi Z-Image Turbo",
        "model_type": "Checkpoint",
        "base_model": "ZImageTurbo",
        "target_subdir": "diffusion_models",
        "family": "z_image",
        "suggested_model": "z_image_turbo",
        "badge": "NATURAL SKIN ZiT",
        "tagline": "Natural unposed photography fine-tune for Z-Image-Turbo with crisp eyes and lighting.",
    },
    {
        "model_id": 2218365,
        "name": "CyberRealistic ZiT",
        "model_type": "Checkpoint",
        "base_model": "ZImageTurbo",
        "target_subdir": "diffusion_models",
        "family": "z_image",
        "suggested_model": "z_image_turbo",
        "badge": "PORTRAIT ZiT",
        "tagline": "Crisp studio & candid portrait realism tuned specifically on Z-Image-Turbo.",
    },
    {
        "model_id": 974693,
        "name": "Realism Illustrious by Stable Yogi",
        "model_type": "Checkpoint",
        "base_model": "Illustrious",
        "target_subdir": "checkpoints",
        "family": "illustrious",
        "suggested_model": "illustrious_xl",
        "badge": "SEMI-REAL / 2.5D",
        "tagline": "Top-rated Illustrious XL checkpoint for semi-realistic / 2.5D characters & clean anatomy.",
    },
    {
        "model_id": 1277670,
        "name": "JANKU Illustrious",
        "model_type": "Checkpoint",
        "base_model": "Illustrious",
        "target_subdir": "checkpoints",
        "family": "illustrious",
        "suggested_model": "illustrious_xl",
        "badge": "TOP ANIME",
        "tagline": "Vibrant anime & stylized illustration powerhouse with strong Danbooru tag obedience.",
    },
    {
        "model_id": 897413,
        "name": "Big Love (Krea 2 / Illustrious)",
        "model_type": "Checkpoint",
        "base_model": "Krea 2",
        "target_subdir": "diffusion_models",
        "family": "krea2",
        "suggested_model": "krea2_turbo",
        "badge": "EDITORIAL REALISM",
        "tagline": "Rich editorial photography checkpoint with expressive lighting and skin micro-detail.",
    },
    {
        "model_id": 2731187,
        "name": "Moody Krea 2 Mix",
        "model_type": "Checkpoint",
        "base_model": "Krea 2",
        "target_subdir": "diffusion_models",
        "family": "krea2",
        "suggested_model": "krea2_turbo",
        "badge": "CINEMATIC KREA2",
        "tagline": "Atmospheric 35mm filmic Krea 2 Turbo fine-tune for dramatic low-light scenes.",
    },
    {
        "model_id": 1330309,
        "name": "Chroma1-HD",
        "model_type": "Checkpoint",
        "base_model": "Chroma",
        "target_subdir": "diffusion_models",
        "family": "chroma",
        "suggested_model": "chroma_hd",
        "badge": "UNCENSORED OPEN",
        "tagline": "Unfiltered Apache-2.0 Flux-family checkpoint with full negative-prompt obedience.",
    },
    {
        "model_id": 2086389,
        "name": "UnCanny Chroma",
        "model_type": "Checkpoint",
        "base_model": "Chroma",
        "target_subdir": "diffusion_models",
        "family": "chroma",
        "suggested_model": "chroma_hd",
        "badge": "REALISM CHROMA",
        "tagline": "Photorealistic community fine-tune of Chroma1-HD with authentic candid grain.",
    },
    {
        "model_id": 2088956,
        "name": "Famegrid Realism LoRA",
        "model_type": "LORA",
        "base_model": "ZImageTurbo",
        "target_subdir": "loras",
        "family": "z_image",
        "suggested_model": "z_image_turbo",
        "badge": "LORA · REALISM",
        "tagline": "Adds raw smartphone lighting & natural skin imperfections to Z-Image-Turbo / Krea 2.",
    },
    {
        "model_id": 2462105,
        "name": "UltraReal Klein 9B LoRA",
        "model_type": "LORA",
        "base_model": "Flux.2 Klein 9B",
        "target_subdir": "loras",
        "family": "flux",
        "suggested_model": "flux2_klein_9b",
        "badge": "LORA · FLUX.2",
        "tagline": "Candid photo realism booster for FLUX.2 [klein] 9B edits & portraits.",
    },
    {
        "model_id": 1822984,
        "name": "Instagirl Wan 2.2 LoRA",
        "model_type": "LORA",
        "base_model": "Wan Video 2.2",
        "target_subdir": "loras",
        "family": "wan",
        "suggested_model": "wan22_i2v",
        "badge": "LORA · WAN 2.2",
        "tagline": "Natural handheld smartphone motion & photorealism booster for Wan 2.2 videos.",
    },
    {
        "model_id": 1385506,
        "name": "Detailz-Wan LoRA",
        "model_type": "LORA",
        "base_model": "Wan Video 2.2",
        "target_subdir": "loras",
        "family": "wan",
        "suggested_model": "wan22_i2v",
        "badge": "LORA · DETAIL",
        "tagline": "Sharpens fine texture, hair, and facial detail on Wan 2.2 I2V/T2V clips.",
    },
    {
        "model_id": 2535622,
        "name": "LTX 2.3 Enhancers LoRA",
        "model_type": "LORA",
        "base_model": "LTXV 2.3",
        "target_subdir": "loras",
        "family": "ltx",
        "suggested_model": "ltx23",
        "badge": "LORA · LTX 2.3",
        "tagline": "Improves motion stability and crisp detail on LTX-2.3 audio+video clips.",
    },
]


# ---------------------------------------------------------------------------
# Local Secret Store (gitignored workspace/secrets.json — never exposed back)
# ---------------------------------------------------------------------------
def _secrets_file(workspace_dir: Path) -> Path:
    return workspace_dir / "secrets.json"


def load_civitai_api_key(workspace_dir: Path | None = None) -> str:
    if workspace_dir is not None:
        sf = _secrets_file(workspace_dir)
        if sf.exists():
            try:
                data = json.loads(sf.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    val = str(data.get("civitai_api_key") or "").strip()
                    if val:
                        return val
            except Exception:
                pass
    return os.environ.get("CIVITAI_API_KEY", "").strip()


def get_civitai_key_status(workspace_dir: Path) -> dict[str, Any]:
    sf = _secrets_file(workspace_dir)
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(data, dict) and str(data.get("civitai_api_key") or "").strip():
                return {"has_api_key": True, "source": "saved"}
        except Exception:
            pass
    if os.environ.get("CIVITAI_API_KEY", "").strip():
        return {"has_api_key": True, "source": "env"}
    return {"has_api_key": False, "source": "none"}


def save_civitai_api_key(workspace_dir: Path, api_key: str) -> dict[str, Any]:
    sf = _secrets_file(workspace_dir)
    sf.parent.mkdir(parents=True, exist_ok=True)
    cur: dict[str, Any] = {}
    if sf.exists():
        try:
            raw = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cur = raw
        except Exception:
            cur = {}
    clean = (api_key or "").strip()
    if clean:
        cur["civitai_api_key"] = clean[:256]
    else:
        cur.pop("civitai_api_key", None)
    sf.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    try:
        os.chmod(sf, 0o600)
    except Exception:
        pass
    return get_civitai_key_status(workspace_dir)


# ---------------------------------------------------------------------------
# URL Parsing & Target Folder Classification
# ---------------------------------------------------------------------------
def parse_civitai_reference(url_or_id: str) -> tuple[int | None, int | None]:
    """Parse a CivitAI URL or numeric ID into (model_id, version_id) with strict hostname validation."""
    raw = (url_or_id or "").strip()
    if not raw:
        raise ValueError("Provide a CivitAI URL or model ID.")
    if raw.isdigit():
        return int(raw), None

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("CivitAI URL must start with https://civitai.com/...")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_CIVITAI_HOSTS:
        raise ValueError(f"Unsupported host '{host}'. Only civitai.com URLs are allowed.")

    qs = parse_qs(parsed.query)
    version_id: int | None = None
    for qk in ("modelVersionId", "versionId"):
        vals = qs.get(qk)
        if vals and vals[0].isdigit():
            version_id = int(vals[0])
            break

    m_dl = re.search(r"/api/download/models/(\d+)", parsed.path)
    if m_dl:
        return None, int(m_dl.group(1))

    m_ver = re.search(r"/model-versions/(\d+)", parsed.path)
    if m_ver:
        return None, int(m_ver.group(1))

    m_mod = re.search(r"/models/(\d+)", parsed.path)
    if m_mod:
        return int(m_mod.group(1)), version_id

    raise ValueError("Could not find a CivitAI model ID or modelVersionId in that URL.")


def classify_civitai_target(
    model_type: str,
    base_model: str,
    filename: str = "",
) -> tuple[str, str, str]:
    """Return (comfy_models_subdir, family_tag, suggested_clipforge_model_id)."""
    mtype = (model_type or "").strip().lower()
    base = f"{base_model or ''} {filename or ''}".lower()

    if any(k in base for k in ("zimage", "z-image", "z_image", "zit", "lumina")):
        family, suggested = "z_image", "z_image_turbo"
    elif "krea" in base:
        family, suggested = "krea2", "krea2_turbo"
    elif "chroma" in base:
        family, suggested = "chroma", "chroma_hd"
    elif any(k in base for k in ("illustrious", "noobai", "pony", "sdxl", "sd 1.5")):
        family, suggested = "illustrious", "illustrious_xl"
    elif "klein" in base or "flux" in base:
        family, suggested = "flux", "flux2_klein_9b"
    elif "qwen" in base:
        family, suggested = "qwen", "qwen_edit_2511"
    elif "wan" in base:
        family, suggested = "wan", "wan22_i2v"
    elif "ltx" in base:
        family, suggested = "ltx", "ltx23"
    else:
        family, suggested = "universal", "z_image_turbo"

    if mtype in ("lora", "locon", "dora"):
        return "loras", family, suggested
    if mtype == "vae":
        return "vae", family, suggested
    if mtype == "textualinversion":
        return "embeddings", family, suggested
    if mtype == "upscaler":
        return "upscale_models", "universal", "upscale_ultrasharp"

    # Checkpoint routing: Illustrious/SDXL/Pony live in models/checkpoints;
    # Flow-matching UNETs (Z-Image, Krea 2, Chroma, Flux, Qwen, Wan, LTX) live in models/diffusion_models
    if family == "illustrious":
        return "checkpoints", family, suggested
    if family in ("z_image", "krea2", "chroma", "flux", "qwen", "wan", "ltx"):
        return "diffusion_models", family, suggested
    return "checkpoints", family, "illustrious_xl"


def _pick_primary_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not files:
        return None
    # Prefer primary .safetensors or .gguf Model file
    def _rank(f: dict[str, Any]) -> tuple[int, int, int]:
        name = str(f.get("name") or "").lower()
        ext_ok = 0 if name.endswith((".safetensors", ".gguf")) else (1 if name.endswith((".ckpt", ".pt", ".pth")) else 2)
        is_primary = 0 if f.get("primary") else 1
        is_model = 0 if str(f.get("type") or "").lower() == "model" else 1
        return (ext_ok, is_primary, is_model)

    ranked = sorted(files, key=_rank)
    best = ranked[0]
    name = str(best.get("name") or "").lower()
    if not any(name.endswith(e) for e in _ALLOWED_MODEL_EXTS):
        return None
    return best


def _extract_preview_url(version: dict[str, Any]) -> str:
    imgs = version.get("images") or []
    for im in imgs:
        if isinstance(im, dict) and im.get("url"):
            u = str(im["url"])
            if u.startswith(("https://", "http://")):
                return u
    return ""


def _normalize_model_version(
    model_obj: dict[str, Any],
    version_obj: dict[str, Any],
) -> dict[str, Any] | None:
    primary = _pick_primary_file(version_obj.get("files") or [])
    if not primary:
        return None
    mtype = str(model_obj.get("type") or "Checkpoint")
    base_model = str(version_obj.get("baseModel") or "")
    filename = str(primary.get("name") or "")
    subdir, family, suggested = classify_civitai_target(mtype, base_model, filename)
    size_kb = float(primary.get("sizeKB") or 0.0)
    stats = model_obj.get("stats") or {}
    trained_words = [str(w).strip() for w in (version_obj.get("trainedWords") or []) if str(w).strip()]
    mid = int(model_obj.get("id") or version_obj.get("modelId") or 0)
    vid = int(version_obj.get("id") or 0)
    dl_url = str(primary.get("downloadUrl") or f"https://civitai.com/api/download/models/{vid}")

    return {
        "model_id": mid,
        "version_id": vid,
        "name": str(model_obj.get("name") or filename),
        "version_name": str(version_obj.get("name") or ""),
        "creator": str((model_obj.get("creator") or {}).get("username") or ""),
        "model_type": mtype,
        "base_model": base_model,
        "downloads": int(stats.get("downloadCount") or (version_obj.get("stats") or {}).get("downloadCount") or 0),
        "thumbs_up": int(stats.get("thumbsUpCount") or 0),
        "filename": filename,
        "size_mb": round(size_kb / 1024.0, 1),
        "download_url": dl_url,
        "trained_words": trained_words[:8],
        "preview_url": _extract_preview_url(version_obj),
        "target_subdir": subdir,
        "family": family,
        "suggested_model": suggested,
        "web_url": f"https://civitai.com/models/{mid}?modelVersionId={vid}" if mid else "",
        "nsfw": bool(model_obj.get("nsfw")),
    }


def _civitai_headers(api_key: str = "") -> dict[str, str]:
    hdrs = {"User-Agent": "ClipForge/1.0"}
    if api_key:
        hdrs["Authorization"] = f"Bearer {api_key}"
    return hdrs


# ---------------------------------------------------------------------------
# Live CivitAI Search & URL Inspection
# ---------------------------------------------------------------------------
def search_civitai_models(
    query: str = "",
    model_type: str | None = None,
    base_model: str | None = None,
    sort: str = "Most Downloaded",
    limit: int = 16,
    nsfw: bool = True,
    api_key: str = "",
) -> list[dict[str, Any]]:
    """Query the live CivitAI REST API for checkpoints/LoRAs and return normalized install-ready cards."""
    params: dict[str, Any] = {
        "limit": max(1, min(30, int(limit))),
        "sort": sort if sort in ("Most Downloaded", "Highest Rated", "Newest") else "Most Downloaded",
        "nsfw": "true" if nsfw else "false",
    }
    clean_q = (query or "").strip()
    if clean_q:
        params["query"] = clean_q
    if model_type and model_type.lower() not in ("all", "any"):
        params["types"] = "LORA" if model_type.lower() == "lora" else "Checkpoint"
    if base_model and base_model.lower() not in ("all", "any"):
        params["baseModels"] = base_model

    resp = httpx.get(
        f"{CIVITAI_API_BASE}/models",
        params=params,
        headers=_civitai_headers(api_key),
        follow_redirects=True,
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    items: list[dict[str, Any]] = []
    for m in data.get("items") or []:
        versions = m.get("modelVersions") or []
        if not versions:
            continue
        norm = _normalize_model_version(m, versions[0])
        if norm is not None:
            items.append(norm)
    return items


def inspect_civitai_url(url_or_id: str, api_key: str = "") -> dict[str, Any]:
    """Inspect any civitai.com model URL or ID and return install-ready version metadata + selectable versions."""
    model_id, version_id = parse_civitai_reference(url_or_id)
    hdrs = _civitai_headers(api_key)

    if version_id is not None and model_id is None:
        r_ver = httpx.get(f"{CIVITAI_API_BASE}/model-versions/{version_id}", headers=hdrs, follow_redirects=True, timeout=20.0)
        r_ver.raise_for_status()
        ver_data = r_ver.json()
        model_id = int(ver_data.get("modelId") or 0) or None

    if model_id is None:
        raise ValueError("Unable to resolve CivitAI model ID.")

    r_mod = httpx.get(f"{CIVITAI_API_BASE}/models/{model_id}", headers=hdrs, follow_redirects=True, timeout=20.0)
    r_mod.raise_for_status()
    mod_data = r_mod.json()
    versions = mod_data.get("modelVersions") or []
    if not versions:
        raise ValueError("This CivitAI model has no downloadable versions.")

    chosen_ver = versions[0]
    if version_id is not None:
        for v in versions:
            if int(v.get("id") or 0) == version_id:
                chosen_ver = v
                break

    norm = _normalize_model_version(mod_data, chosen_ver)
    if norm is None:
        raise ValueError("No supported .safetensors / .gguf / .ckpt file found on this CivitAI version.")

    alt_versions: list[dict[str, Any]] = []
    for v in versions[:8]:
        nv = _normalize_model_version(mod_data, v)
        if nv is not None:
            alt_versions.append(
                {
                    "version_id": nv["version_id"],
                    "version_name": nv["version_name"],
                    "base_model": nv["base_model"],
                    "filename": nv["filename"],
                    "size_mb": nv["size_mb"],
                    "target_subdir": nv["target_subdir"],
                }
            )
    norm["versions"] = alt_versions
    return norm


# ---------------------------------------------------------------------------
# Resumable Background Downloader -> ComfyUI/models/<subdir>/ + Auto-Triggers
# ---------------------------------------------------------------------------
def _sanitize_model_filename(raw_name: str, fallback_stem: str = "civitai_model") -> str:
    base = PurePosixPath(PureWindowsPath((raw_name or "").strip()).name).name
    ext = Path(base).suffix.lower()
    if ext not in _ALLOWED_MODEL_EXTS:
        raise ValueError(f"Unsupported model extension '{ext or '(none)'}'. Allowed: {sorted(_ALLOWED_MODEL_EXTS)}")
    stem = _SAFE_NAME_RE.sub("_", Path(base).stem).strip("._-") or fallback_stem
    return f"{stem[:96]}{ext}"


def _validate_civitai_download_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Invalid download URL scheme.")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_CIVITAI_HOSTS and not host.endswith(".civitai.com"):
        raise ValueError(f"Download URL must point to civitai.com (got '{host}').")
    return url.strip()


@dataclass
class CivitaiDownloadState:
    download_id: str
    name: str
    filename: str
    target_subdir: str
    model_type: str
    base_model: str
    status: str = "downloading"  # downloading | completed | failed | canceled
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_mbps: float = 0.0
    error: str | None = None
    dest_path: str = ""
    trained_words: list[str] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)


class CivitaiDownloadManager:
    """Streams CivitAI checkpoints & LoRAs directly into ComfyUI/models/ with HTTP Range resume & auto-triggers."""

    def __init__(self, comfy_dir: Path = COMFYUI_DIR) -> None:
        self.comfy_dir = comfy_dir
        self._lock = threading.Lock()
        self._states: dict[str, CivitaiDownloadState] = {}

    def list_downloads(self) -> list[dict[str, Any]]:
        with self._lock:
            out: list[dict[str, Any]] = []
            for st in self._states.values():
                pct = round((st.downloaded_bytes / st.total_bytes) * 100.0, 1) if st.total_bytes > 0 else 0.0
                out.append(
                    {
                        "download_id": st.download_id,
                        "name": st.name,
                        "filename": st.filename,
                        "target_subdir": st.target_subdir,
                        "model_type": st.model_type,
                        "base_model": st.base_model,
                        "status": st.status,
                        "downloaded_mb": round(st.downloaded_bytes / (1024 * 1024), 1),
                        "total_mb": round(st.total_bytes / (1024 * 1024), 1),
                        "pct": min(100.0, pct),
                        "speed_mbps": round(st.speed_mbps, 1),
                        "error": st.error,
                        "dest_path": st.dest_path,
                        "trained_words": st.trained_words,
                    }
                )
            return out

    def cancel(self, download_id: str) -> bool:
        with self._lock:
            st = self._states.get(download_id)
            if st and st.status == "downloading":
                st.cancel_event.set()
                st.status = "canceled"
                return True
            return False

    def start_install(
        self,
        *,
        version_id: int | None = None,
        url_or_id: str | None = None,
        download_url: str | None = None,
        filename: str | None = None,
        name: str | None = None,
        model_type: str | None = None,
        base_model: str | None = None,
        target_subdir: str | None = None,
        trained_words: list[str] | None = None,
        size_mb: float = 0.0,
        api_key: str = "",
        triggers_file: Path | None = None,
    ) -> dict[str, Any]:
        # If caller supplied a URL/model_id/version_id without full file metadata, resolve via CivitAI API
        resolved: dict[str, Any] | None = None
        if url_or_id and (not download_url or not filename):
            resolved = inspect_civitai_url(url_or_id, api_key=api_key)
        elif version_id and (not download_url or not filename):
            resolved = inspect_civitai_url(f"https://civitai.com/api/download/models/{int(version_id)}", api_key=api_key)

        if resolved is not None:
            version_id = resolved["version_id"]
            download_url = resolved["download_url"]
            filename = resolved["filename"]
            name = name or resolved["name"]
            model_type = model_type or resolved["model_type"]
            base_model = base_model or resolved["base_model"]
            target_subdir = target_subdir or resolved["target_subdir"]
            trained_words = trained_words if trained_words is not None else resolved["trained_words"]
            size_mb = size_mb or float(resolved.get("size_mb") or 0.0)

        if not download_url or not filename:
            raise ValueError("Missing download_url or filename for CivitAI install.")

        safe_url = _validate_civitai_download_url(download_url)
        safe_fn = _sanitize_model_filename(filename)
        subdir = target_subdir or classify_civitai_target(model_type or "Checkpoint", base_model or "", safe_fn)[0]
        if subdir not in ("loras", "checkpoints", "diffusion_models", "vae", "embeddings", "upscale_models"):
            raise ValueError(f"Unsupported target folder '{subdir}'.")

        target_root = (self.comfy_dir / "models" / subdir).resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        dest = (target_root / safe_fn).resolve()
        dest.relative_to(target_root)

        dl_id = f"civitai_{version_id or safe_fn}"
        with self._lock:
            existing = self._states.get(dl_id)
            if existing and existing.status == "downloading":
                return next(d for d in self.list_downloads() if d["download_id"] == dl_id)
            st = CivitaiDownloadState(
                download_id=dl_id,
                name=name or safe_fn,
                filename=safe_fn,
                target_subdir=subdir,
                model_type=model_type or "Checkpoint",
                base_model=base_model or "",
                status="downloading",
                total_bytes=int(size_mb * 1024 * 1024),
                dest_path=str(dest),
                trained_words=list(trained_words or []),
            )
            self._states[dl_id] = st

        t = threading.Thread(
            target=self._worker,
            args=(st, safe_url, dest, api_key, triggers_file),
            daemon=True,
        )
        t.start()
        return next(d for d in self.list_downloads() if d["download_id"] == dl_id)

    def _worker(
        self,
        st: CivitaiDownloadState,
        url: str,
        dest: Path,
        api_key: str,
        triggers_file: Path | None,
    ) -> None:
        try:
            if dest.exists() and dest.stat().st_size > 1024 * 1024:
                with self._lock:
                    st.downloaded_bytes = dest.stat().st_size
                    st.total_bytes = dest.stat().st_size
                    st.status = "completed"
                self._register_triggers(st, triggers_file)
                return

            part = dest.with_name(dest.name + ".part")
            resume_pos = part.stat().st_size if part.exists() else 0
            headers = _civitai_headers(api_key)
            if resume_pos > 0:
                headers["Range"] = f"bytes={resume_pos}-"

            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=90.0)) as client:
                with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code in (401, 403):
                        raise RuntimeError(
                            "CivitAI requires a free API key to download this model. "
                            "Paste your CivitAI API key in the CivitAI Browser settings."
                        )
                    if resp.status_code == 416 and part.exists() and part.stat().st_size > 1024 * 1024:
                        part.replace(dest)
                    else:
                        if resp.status_code not in (200, 206):
                            raise RuntimeError(f"CivitAI returned HTTP {resp.status_code} for {st.filename}")

                        mode = "ab" if resp.status_code == 206 and resume_pos > 0 else "wb"
                        if mode == "wb":
                            resume_pos = 0
                        cl = int(resp.headers.get("content-length") or 0)
                        if cl > 0:
                            with self._lock:
                                st.total_bytes = resume_pos + cl

                        t_last = time.perf_counter()
                        bytes_since = 0
                        written = resume_pos
                        with open(part, mode) as fh:
                            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                                if st.cancel_event.is_set():
                                    with self._lock:
                                        st.status = "canceled"
                                    return
                                fh.write(chunk)
                                n = len(chunk)
                                written += n
                                bytes_since += n
                                now = time.perf_counter()
                                dt = now - t_last
                                if dt >= 0.4:
                                    spd = (bytes_since / (1024 * 1024)) / dt
                                    with self._lock:
                                        st.downloaded_bytes = written
                                        st.speed_mbps = spd
                                    t_last = now
                                    bytes_since = 0
                        part.replace(dest)

            self._register_triggers(st, triggers_file)
            final_sz = dest.stat().st_size if dest.exists() else st.downloaded_bytes
            with self._lock:
                st.downloaded_bytes = final_sz
                st.total_bytes = max(st.total_bytes, final_sz)
                st.speed_mbps = 0.0
                st.status = "completed"
        except Exception as exc:
            with self._lock:
                if not st.cancel_event.is_set():
                    st.status = "failed"
                    st.error = str(exc)

    def _register_triggers(self, st: CivitaiDownloadState, triggers_file: Path | None) -> None:
        if triggers_file and st.target_subdir == "loras" and st.trained_words:
            try:
                save_lora_trigger(triggers_file, st.filename, ", ".join(st.trained_words[:6]))
            except Exception:
                pass


civitai_download_manager = CivitaiDownloadManager()
