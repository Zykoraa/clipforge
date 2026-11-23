"""Offline AI Video & Image Generation Engine (ComfyUI Client + Live WS Progress + Resumable Model Downloader)."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import httpx

COMFYUI_DIR = Path(os.environ.get("CLIPFORGE_COMFYUI_DIR", r"E:\ComfyUI"))
COMFYUI_URL = os.environ.get("CLIPFORGE_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
COMFYUI_PYTHON = COMFYUI_DIR / ".venv" / "Scripts" / "python.exe"

VideoModelId = Literal["wan22_5b", "wan22_i2v", "ltx23"]
ImageModelId = Literal["flux2_klein", "z_image_turbo", "qwen_edit"]
GeneratorModelId = Literal["wan22_5b", "wan22_i2v", "ltx23", "flux2_klein", "z_image_turbo", "qwen_edit"]

PROMPT_PRESETS: dict[str, dict[str, str]] = {
    "none": {"label": "Raw Prompt", "category": "all", "suffix": ""},
    # --- Candid & Hyper-Realism ---
    "raw_iphone": {
        "label": "iPhone Flash",
        "category": "candid",
        "suffix": "candid smartphone photo taken with harsh direct camera flash, slightly imperfect handheld framing, realistic natural skin texture, authentic everyday lighting, zero AI gloss",
    },
    "paparazzi": {
        "label": "3AM Paparazzi",
        "category": "candid",
        "suffix": "ambush 3AM tabloid paparazzi photo, harsh off-camera flash glare, grainy high-ISO telephoto lens, caught off guard outside a club, raw candid photojournalism",
    },
    "disposable_35mm": {
        "label": "90s Disposable",
        "category": "candid",
        "suffix": "1998 disposable 35mm film camera snapshot, warm direct flash falloff, heavy Kodak film grain, slightly soft vintage lens, nostalgic candid house party lighting",
    },
    "mugshot": {
        "label": "Booking Mugshot",
        "category": "candid",
        "suffix": "authentic county jail booking mugshot photograph, flat harsh overhead fluorescent lighting, height measurement lines on concrete wall behind subject, unsmiling deadpan expression",
    },
    "nightclub_flash": {
        "label": "Club Flash",
        "category": "candid",
        "suffix": "chaotic late-night club flash photography, harsh direct flash freezing subject against motion-blurred neon strobe lights and crowded dancefloor, raw candid energy",
    },
    "grocery_fluorescent": {
        "label": "2AM Walmart",
        "category": "candid",
        "suffix": "unhinged 2AM superstore aisle candid phone photo, buzzing green-white overhead fluorescent tubes, shiny linoleum floor reflections, hyper-real mundane chaos",
    },
    # --- Found Footage & Security ---
    "bodycam": {
        "label": "Police Bodycam",
        "category": "footage",
        "suffix": "raw chest-mounted police bodycam footage, wide-angle fisheye lens distortion, harsh flashlight and flashing red-blue cruiser lights at night, realistic low-light digital video noise",
    },
    "cctv": {
        "label": "2AM CCTV Cam",
        "category": "footage",
        "suffix": "grainy 2:14 AM overhead convenience store CCTV security camera footage, subtle fisheye distortion, green-tinted fluorescent lighting, authentic surveillance video still",
    },
    "ring_doorbell": {
        "label": "Ring Doorbell",
        "category": "footage",
        "suffix": "160-degree fisheye smart doorbell porch camera footage at night, infrared night-vision monochrome glow, bizarre close-up visitor staring directly into lens",
    },
    "dashcam": {
        "label": "Car Dashcam",
        "category": "footage",
        "suffix": "wide-angle windshield dashboard camera footage, subtle glass reflections and road glare, authentic compressed action dashcam realism",
    },
    "vhs_2003": {
        "label": "2003 Camcorder",
        "category": "footage",
        "suffix": "2003 handheld MiniDV camcorder home video footage, subtle VHS color bleed, blown-out highlights, slight interlaced motion blur, authentic early-2000s realism",
    },
    "trail_cam": {
        "label": "Night Trail Cam",
        "category": "footage",
        "suffix": "infrared wildlife trail camera photo in dark woods at midnight, stark monochrome night-vision flash, high contrast, eerie cryptid sighting aesthetic",
    },
    # --- Viral Memes & Broadcast ---
    "meme_reaction": {
        "label": "Viral Reaction",
        "category": "meme",
        "suffix": "expressive deadpan viral internet meme photo, natural candid lighting, hilarious exaggerated comedic timing, crystal clear subject focus",
    },
    "cursed_zoom": {
        "label": "0.5x Wide Selfie",
        "category": "meme",
        "suffix": "chaotic ultra-wide 0.5x smartphone lens extreme close-up distortion, comedic exaggerated perspective, harsh candid lighting, unhinged friend-group meme energy",
    },
    "breaking_news": {
        "label": "Breaking News",
        "category": "meme",
        "suffix": "live cable TV breaking news remote field broadcast camera feed, crisp broadcast camera lighting, authentic television journalism framing",
    },
    "podcast": {
        "label": "Viral Podcast",
        "category": "meme",
        "suffix": "viral YouTube podcast studio camera shot, Shure SM7B microphone in foreground, moody neon accent lighting, shallow depth of field, realistic 4K cinema camera",
    },
    "courtroom_sketch": {
        "label": "Courtroom Trial",
        "category": "meme",
        "suffix": "dramatic televised courtroom trial camera feed, telephoto press lens, wooden witness stand and microphone, dead-serious high-stakes legal drama lighting",
    },
    "national_geo": {
        "label": "Nature Doc",
        "category": "meme",
        "suffix": "prestigious wildlife documentary telephoto shot, crisp golden-hour rim light, shallow bokeh background, ultra-serious National Geographic framing",
    },
    # --- Cinema & Stylized ---
    "movie_poster": {
        "label": "Action Cinema",
        "category": "cinema",
        "suffix": "epic blockbuster cinema photography, dramatic rim lighting, atmospheric smoke, anamorphic lens flare, ultra detailed photorealistic film still",
    },
    "cyberpunk_noir": {
        "label": "Neon Noir",
        "category": "cinema",
        "suffix": "rain-soaked cyberpunk neo-noir cinematography, wet asphalt neon magenta and cyan reflections, moody volumetric fog, 35mm anamorphic lens",
    },
    "gta_loading": {
        "label": "GTA Loading Art",
        "category": "cinema",
        "suffix": "iconic Grand Theft Auto loading screen illustration style, bold ink outlines, vibrant sunset cel-shaded highlights, palm trees and dramatic comic-realism shading",
    },
    "ps2_cutscene": {
        "label": "2002 PS2 Game",
        "category": "cinema",
        "suffix": "early 2000s PlayStation 2 video game cutscene aesthetic, slightly low-poly nostalgic 3D rendering, glossy specular highlights, retro CRT video game charm",
    },
    "anime_sakuga": {
        "label": "Anime Sakuga",
        "category": "cinema",
        "suffix": "high-budget Japanese anime action keyframe, dramatic speed lines, bold cel-shaded lighting, intense impact-frame energy, crisp anime cinematography",
    },
}

CAMERA_PRESETS: dict[str, dict[str, str]] = {
    "none": {"label": "Auto Camera", "suffix": ""},
    "handheld_chaos": {
        "label": "Handheld Panic",
        "suffix": "frantic shaky handheld smartphone camera chasing the chaotic action with natural camera bounce",
    },
    "crash_zoom": {
        "label": "Crash Zoom",
        "suffix": "sudden rapid comedic crash-zoom straight onto the subject's shocked face",
    },
    "fpv_chase": {
        "label": "FPV Drone Chase",
        "suffix": "high-speed dynamic FPV drone tracking shot swooping and banking closely around the subject",
    },
    "slow_mo": {
        "label": "Epic Slow-Mo",
        "suffix": "dramatic 120fps ultra slow-motion cinematography with flying particles and smooth motion",
    },
    "whip_pan": {
        "label": "Whip Pan",
        "suffix": "snappy kinetic whip-pan camera sweep across the scene for comedic timing",
    },
    "orbit_360": {
        "label": "360° Hero Orbit",
        "suffix": "smooth dramatic 360-degree circular gimbal orbit sweeping around the subject",
    },
    "static_deadpan": {
        "label": "Static Deadpan",
        "suffix": "completely locked-off tripod static camera shot holding awkward deadpan comedic framing",
    },
}

DEFAULT_NEGATIVE_PROMPT = (
    "blurry, static, low quality, worst quality, watermark, deformed face, "
    "extra limbs, jittering, artifacts, overexposed, neon oversaturation, plastic skin"
)

# Exact verified HuggingFace model catalog (Video + Image, all stored cleanly on E:\ComfyUI\models\)
MODEL_SPECS: dict[str, dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # VIDEO MODELS
    # -------------------------------------------------------------------------
    "wan22_5b": {
        "kind": "video",
        "display_name": "Wan 2.2 TI2V 5B (Fast)",
        "badge": "FAST T2V + I2V",
        "description": "Fast single-model Wan 2.2 supporting both Text-to-Video and Image-to-Video on 8GB VRAM.",
        "requires_image": False,
        "supports_image": True,
        "supports_second_image": False,
        "supports_audio": False,
        "default_width": 480,
        "default_height": 608,
        "default_fps": 24,
        "default_steps": 20,
        "default_cfg": 3.8,
        "default_frames": 73,
        "frame_step": 4,
        "dim_step": 32,
        "files": [
            {
                "repo_id": "QuantStack/Wan2.2-TI2V-5B-GGUF",
                "remote_path": "Wan2.2-TI2V-5B-Q4_K_M.gguf",
                "local_rel": "models/diffusion_models/Wan2.2-TI2V-5B-Q4_K_M.gguf",
                "size_gb": 3.20,
            },
            {
                "repo_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                "remote_path": "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "local_rel": "models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "size_gb": 6.27,
            },
            {
                "repo_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                "remote_path": "split_files/vae/wan2.2_vae.safetensors",
                "local_rel": "models/vae/wan2.2_vae.safetensors",
                "size_gb": 1.31,
            },
        ],
    },
    "wan22_i2v": {
        "kind": "video",
        "display_name": "Wan 2.2 I2V 14B (Best Likeness)",
        "badge": "HQ PHOTO -> VIDEO",
        "description": "Dual-expert 14B Q4_K_M + 4-step Lightx2v LoRAs. Best face consistency & physics for friend memes.",
        "requires_image": True,
        "supports_image": True,
        "supports_end_image": True,
        "supports_second_image": False,
        "supports_audio": False,
        "default_width": 480,
        "default_height": 832,
        "default_fps": 16,
        "default_steps": 6,
        "default_cfg": 1.0,
        "default_frames": 81,
        "frame_step": 4,
        "dim_step": 16,
        "files": [
            {
                "repo_id": "QuantStack/Wan2.2-I2V-A14B-GGUF",
                "remote_path": "HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf",
                "local_rel": "models/diffusion_models/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf",
                "size_gb": 8.99,
            },
            {
                "repo_id": "QuantStack/Wan2.2-I2V-A14B-GGUF",
                "remote_path": "LowNoise/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
                "local_rel": "models/diffusion_models/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
                "size_gb": 8.99,
            },
            {
                "repo_id": "lightx2v/Wan2.2-Distill-Loras",
                "remote_path": "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors",
                "local_rel": "models/loras/wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors",
                "size_gb": 0.59,
            },
            {
                "repo_id": "lightx2v/Wan2.2-Distill-Loras",
                "remote_path": "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors",
                "local_rel": "models/loras/wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors",
                "size_gb": 0.69,
            },
            {
                "repo_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                "remote_path": "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "local_rel": "models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "size_gb": 6.27,
            },
            {
                "repo_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                "remote_path": "split_files/vae/wan_2.1_vae.safetensors",
                "local_rel": "models/vae/wan_2.1_vae.safetensors",
                "size_gb": 0.24,
            },
        ],
    },
    "ltx23": {
        "kind": "video",
        "display_name": "LTX-2.3 22B (Native Audio + Video)",
        "badge": "FAST + AUDIO/SFX",
        "description": "8-step distilled Text-to-Video & Image-to-Video with synchronized native audio/SFX/dialogue.",
        "requires_image": False,
        "supports_image": True,
        "supports_second_image": False,
        "supports_audio": True,
        "default_width": 480,
        "default_height": 832,
        "default_fps": 24,
        "default_steps": 8,
        "default_cfg": 1.0,
        "default_frames": 97,
        "frame_step": 8,
        "dim_step": 32,
        "files": [
            {
                "repo_id": "unsloth/LTX-2.3-GGUF",
                "remote_path": "distilled-1.1/ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf",
                "local_rel": "models/diffusion_models/ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf",
                "size_gb": 13.22,
            },
            {
                "repo_id": "Comfy-Org/ltx-2",
                "remote_path": "split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors",
                "local_rel": "models/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors",
                "size_gb": 12.30,
            },
            {
                "repo_id": "unsloth/LTX-2.3-GGUF",
                "remote_path": "text_encoders/ltx-2.3-22b-distilled_embeddings_connectors.safetensors",
                "local_rel": "models/text_encoders/ltx-2.3-22b-distilled_embeddings_connectors.safetensors",
                "size_gb": 2.15,
            },
            {
                "repo_id": "unsloth/LTX-2.3-GGUF",
                "remote_path": "vae/ltx-2.3-22b-distilled_video_vae.safetensors",
                "local_rel": "models/vae/ltx-2.3-22b-distilled_video_vae.safetensors",
                "size_gb": 1.35,
            },
            {
                "repo_id": "unsloth/LTX-2.3-GGUF",
                "remote_path": "vae/ltx-2.3-22b-distilled_audio_vae.safetensors",
                "local_rel": "models/vae/ltx-2.3-22b-distilled_audio_vae.safetensors",
                "size_gb": 0.34,
            },
        ],
    },
    # -------------------------------------------------------------------------
    # IMAGE & FRIEND-PHOTO EDITING MODELS
    # -------------------------------------------------------------------------
    "flux2_klein": {
        "kind": "image",
        "display_name": "FLUX.2 [klein] 4B (Fast Edit + Memes)",
        "badge": "4-STEP T2I + EDIT",
        "description": "Ultra-fast ~4s photorealistic image gen & friend-photo editing. Drop a photo to place friends into any scene.",
        "requires_image": False,
        "supports_image": True,
        "supports_second_image": False,
        "supports_audio": False,
        "default_width": 1024,
        "default_height": 1024,
        "default_steps": 4,
        "default_cfg": 1.0,
        "dim_step": 16,
        "files": [
            {
                "repo_id": "unsloth/FLUX.2-klein-4B-GGUF",
                "remote_path": "flux-2-klein-4b-Q4_K_M.gguf",
                "local_rel": "models/diffusion_models/flux-2-klein-4b-Q4_K_M.gguf",
                "size_gb": 2.43,
            },
            {
                "repo_id": "Comfy-Org/z_image_turbo",
                "remote_path": "split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors",
                "local_rel": "models/text_encoders/qwen_3_4b_fp8_mixed.safetensors",
                "size_gb": 5.25,
            },
            {
                "repo_id": "Comfy-Org/flux2-klein",
                "remote_path": "split_files/vae/flux2-vae.safetensors",
                "local_rel": "models/vae/flux2-vae.safetensors",
                "size_gb": 0.31,
            },
        ],
    },
    "z_image_turbo": {
        "kind": "image",
        "display_name": "Z-Image-Turbo (Realism & Meme Text)",
        "badge": "8-STEP REALISM",
        "description": "Best ultra-fast photorealistic candid photography & crisp embedded meme text. Shares encoder with FLUX.2-klein (+3.9GB).",
        "requires_image": False,
        "supports_image": False,
        "supports_second_image": False,
        "supports_audio": False,
        "default_width": 1024,
        "default_height": 1024,
        "default_steps": 8,
        "default_cfg": 1.0,
        "dim_step": 16,
        "files": [
            {
                "repo_id": "unsloth/Z-Image-Turbo-GGUF",
                "remote_path": "z-image-turbo-Q4_K_M.gguf",
                "local_rel": "models/diffusion_models/z-image-turbo-Q4_K_M.gguf",
                "size_gb": 3.59,
            },
            {
                "repo_id": "Comfy-Org/z_image_turbo",
                "remote_path": "split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors",
                "local_rel": "models/text_encoders/qwen_3_4b_fp8_mixed.safetensors",
                "size_gb": 5.25,
            },
            {
                "repo_id": "Comfy-Org/z_image_turbo",
                "remote_path": "split_files/vae/ae.safetensors",
                "local_rel": "models/vae/ae.safetensors",
                "size_gb": 0.31,
            },
        ],
    },
    "qwen_edit": {
        "kind": "image",
        "display_name": "Qwen-Image-Edit 2509 (Multi-Photo)",
        "badge": "PRO PHOTO COMPOSITOR",
        "description": "Instruction-based friend-photo compositor supporting 1–2 friend photos simultaneously with unmatched identity lock.",
        "requires_image": True,
        "supports_image": True,
        "supports_second_image": True,
        "supports_audio": False,
        "default_width": 1024,
        "default_height": 1024,
        "default_steps": 20,
        "default_cfg": 2.5,
        "dim_step": 16,
        "files": [
            {
                "repo_id": "QuantStack/Qwen-Image-Edit-2509-GGUF",
                "remote_path": "Qwen-Image-Edit-2509-Q4_K_M.gguf",
                "local_rel": "models/diffusion_models/Qwen-Image-Edit-2509-Q4_K_M.gguf",
                "size_gb": 12.17,
            },
            {
                "repo_id": "Comfy-Org/Qwen-Image_ComfyUI",
                "remote_path": "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "local_rel": "models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "size_gb": 8.74,
            },
            {
                "repo_id": "Comfy-Org/Qwen-Image_ComfyUI",
                "remote_path": "split_files/vae/qwen_image_vae.safetensors",
                "local_rel": "models/vae/qwen_image_vae.safetensors",
                "size_gb": 0.24,
            },
        ],
    },
}


def apply_prompt_preset(
    prompt: str,
    preset_id: str | None,
    camera_preset: str | None = None,
) -> str:
    parts: list[str] = []
    clean = (prompt or "").strip()
    if clean:
        parts.append(clean)
    if preset_id and preset_id != "none" and preset_id in PROMPT_PRESETS:
        s = PROMPT_PRESETS[preset_id]["suffix"].strip()
        if s:
            parts.append(s)
    if camera_preset and camera_preset != "none" and camera_preset in CAMERA_PRESETS:
        c = CAMERA_PRESETS[camera_preset]["suffix"].strip()
        if c:
            parts.append(c)
    return ", ".join(parts)


def snap_dim(val: int, step: int, minimum: int = 256, maximum: int = 1536) -> int:
    clamped = max(minimum, min(maximum, int(val)))
    return max(minimum, (clamped // step) * step)


def snap_frames(num_frames: int, step: int, minimum: int = 17, maximum: int = 161) -> int:
    clamped = max(minimum, min(maximum, int(num_frames)))
    k = max(1, round((clamped - 1) / step))
    return k * step + 1


# ---------------------------------------------------------------------------
# Resumable In-Process Model Download Manager (Direct HTTP Range -> E:\ComfyUI)
# ---------------------------------------------------------------------------
@dataclass
class DownloadState:
    model_id: str
    status: str = "idle"  # idle | downloading | completed | failed | canceled
    current_file: str = ""
    file_index: int = 0
    total_files: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_mbps: float = 0.0
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


class ModelDownloadManager:
    """Streams HuggingFace model files with HTTP Range resume & exact live progress onto E:\\ComfyUI."""

    def __init__(self, comfy_dir: Path = COMFYUI_DIR) -> None:
        self.comfy_dir = comfy_dir
        self._lock = threading.Lock()
        self._states: dict[str, DownloadState] = {}
        self._file_locks: dict[str, threading.Lock] = {}

    def _get_file_lock(self, local_rel: str) -> threading.Lock:
        with self._lock:
            if local_rel not in self._file_locks:
                self._file_locks[local_rel] = threading.Lock()
            return self._file_locks[local_rel]

    def get_state_dict(self, model_id: str) -> dict[str, Any] | None:
        with self._lock:
            st = self._states.get(model_id)
            if not st:
                return None
            pct = round((st.downloaded_bytes / st.total_bytes) * 100, 1) if st.total_bytes > 0 else 0.0
            return {
                "status": st.status,
                "current_file": st.current_file,
                "file_index": st.file_index,
                "total_files": st.total_files,
                "downloaded_gb": round(st.downloaded_bytes / (1024**3), 2),
                "total_gb": round(st.total_bytes / (1024**3), 2),
                "pct": min(100.0, pct),
                "speed_mbps": round(st.speed_mbps, 1),
                "error": st.error,
            }

    def cancel_download(self, model_id: str) -> bool:
        with self._lock:
            st = self._states.get(model_id)
            if st and st.status == "downloading":
                st.cancel_event.set()
                st.status = "canceled"
                return True
            return False

    def start_download(self, model_id: str) -> dict[str, Any]:
        if model_id not in MODEL_SPECS:
            raise ValueError(f"Unknown model '{model_id}'. Valid: {sorted(MODEL_SPECS.keys())}")

        with self._lock:
            existing = self._states.get(model_id)
            if existing and existing.status == "downloading":
                return self.get_state_dict(model_id) or {}
            spec = MODEL_SPECS[model_id]
            est_total = int(sum(f["size_gb"] for f in spec["files"]) * (1024**3))
            st = DownloadState(
                model_id=model_id,
                status="downloading",
                total_files=len(spec["files"]),
                total_bytes=est_total,
            )
            self._states[model_id] = st

        t = threading.Thread(target=self._worker, args=(model_id, st), daemon=True)
        t.start()
        return self.get_state_dict(model_id) or {}

    def _worker(self, model_id: str, st: DownloadState) -> None:
        spec = MODEL_SPECS[model_id]
        files = spec["files"]
        hf_token = os.environ.get("HF_TOKEN")
        base_headers = {"User-Agent": "ClipForge/1.0"}
        if hf_token:
            base_headers["Authorization"] = f"Bearer {hf_token}"

        try:
            # Resolve exact sizes upfront where possible
            exact_sizes: list[int] = []
            for f in files:
                dest = self.comfy_dir / f["local_rel"]
                if dest.exists() and dest.stat().st_size > 1024 * 1024:
                    exact_sizes.append(dest.stat().st_size)
                else:
                    url = f"https://huggingface.co/{f['repo_id']}/resolve/main/{f['remote_path']}"
                    try:
                        r = httpx.head(url, headers=base_headers, follow_redirects=True, timeout=15.0)
                        sz = int(r.headers.get("content-length") or 0)
                        exact_sizes.append(sz if sz > 0 else int(f["size_gb"] * (1024**3)))
                    except Exception:
                        exact_sizes.append(int(f["size_gb"] * (1024**3)))

            with self._lock:
                st.total_bytes = sum(exact_sizes)

            completed_bytes = 0
            for idx, f in enumerate(files):
                if st.cancel_event.is_set():
                    with self._lock:
                        st.status = "canceled"
                    return

                dest = self.comfy_dir / f["local_rel"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                file_lock = self._get_file_lock(f["local_rel"])

                with file_lock:
                    if dest.exists() and dest.stat().st_size > 1024 * 1024:
                        completed_bytes += dest.stat().st_size
                        with self._lock:
                            st.file_index = idx + 1
                            st.current_file = dest.name
                            st.downloaded_bytes = completed_bytes
                        continue

                    part = dest.with_name(dest.name + ".part")
                    resume_pos = part.stat().st_size if part.exists() else 0
                    url = f"https://huggingface.co/{f['repo_id']}/resolve/main/{f['remote_path']}"
                    headers = dict(base_headers)
                    if resume_pos > 0:
                        headers["Range"] = f"bytes={resume_pos}-"

                    with self._lock:
                        st.file_index = idx + 1
                        st.current_file = dest.name
                        st.downloaded_bytes = completed_bytes + resume_pos

                    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=60.0)) as client:
                        with client.stream("GET", url, headers=headers) as resp:
                            if resp.status_code == 416 and part.exists() and part.stat().st_size >= exact_sizes[idx]:
                                part.replace(dest)
                                completed_bytes += dest.stat().st_size
                                continue
                            if resp.status_code not in (200, 206):
                                raise RuntimeError(f"HTTP {resp.status_code} downloading {dest.name}")

                            mode = "ab" if resp.status_code == 206 and resume_pos > 0 else "wb"
                            if mode == "wb":
                                resume_pos = 0

                            t_last = time.perf_counter()
                            bytes_since = 0
                            written_file = resume_pos
                            with open(part, mode) as fh:
                                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                                    if st.cancel_event.is_set():
                                        with self._lock:
                                            st.status = "canceled"
                                        return
                                    fh.write(chunk)
                                    n = len(chunk)
                                    written_file += n
                                    bytes_since += n
                                    now = time.perf_counter()
                                    dt = now - t_last
                                    if dt >= 0.4:
                                        spd = (bytes_since / (1024 * 1024)) / dt
                                        with self._lock:
                                            st.downloaded_bytes = completed_bytes + written_file
                                            st.speed_mbps = spd
                                        t_last = now
                                        bytes_since = 0

                    part.replace(dest)
                    completed_bytes += dest.stat().st_size
                    with self._lock:
                        st.downloaded_bytes = completed_bytes

            with self._lock:
                st.status = "completed"
                st.downloaded_bytes = st.total_bytes
                st.speed_mbps = 0.0
                st.current_file = ""
        except Exception as exc:
            with self._lock:
                if not st.cancel_event.is_set():
                    st.status = "failed"
                    st.error = str(exc)


download_manager = ModelDownloadManager()


def get_model_availability(comfy_dir: Path = COMFYUI_DIR) -> dict[str, dict[str, Any]]:
    """Inspect all video & image model bundles on E:\\ComfyUI plus any active download progress."""
    report: dict[str, dict[str, Any]] = {}
    for model_id, spec in MODEL_SPECS.items():
        present: list[str] = []
        missing: list[dict[str, Any]] = []
        total_gb = 0.0
        for f in spec["files"]:
            total_gb += f["size_gb"]
            fp = comfy_dir / f["local_rel"]
            if fp.exists() and fp.stat().st_size > 1024 * 1024:
                present.append(f["local_rel"])
            else:
                part = fp.with_name(fp.name + ".part")
                partial_gb = round(part.stat().st_size / (1024**3), 2) if part.exists() else 0.0
                missing.append({"file": f["local_rel"], "size_gb": f["size_gb"], "partial_gb": partial_gb})

        dl_state = download_manager.get_state_dict(model_id)
        report[model_id] = {
            "id": model_id,
            "kind": spec["kind"],
            "display_name": spec["display_name"],
            "badge": spec["badge"],
            "description": spec["description"],
            "ready": len(missing) == 0,
            "requires_image": spec["requires_image"],
            "supports_image": spec["supports_image"],
            "supports_end_image": spec.get("supports_end_image", False),
            "supports_second_image": spec["supports_second_image"],
            "supports_audio": spec["supports_audio"],
            "defaults": {
                "width": spec["default_width"],
                "height": spec["default_height"],
                "steps": spec["default_steps"],
                "cfg": spec["default_cfg"],
                "frames": spec.get("default_frames"),
                "fps": spec.get("default_fps"),
            },
            "present_count": len(present),
            "total_files": len(spec["files"]),
            "total_gb": round(total_gb, 2),
            "missing_files": missing,
            "missing_gb": round(sum(m["size_gb"] for m in missing), 2),
            "download": dl_state,
        }
    return report


def is_comfyui_reachable(base_url: str = COMFYUI_URL) -> bool:
    try:
        r = httpx.get(f"{base_url}/system_stats", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def ensure_comfyui_running(
    comfy_dir: Path = COMFYUI_DIR,
    base_url: str = COMFYUI_URL,
    wait_sec: float = 45.0,
) -> dict[str, Any]:
    """Start headless ComfyUI on 127.0.0.1:8188 (--lowvram) if not already listening."""
    if is_comfyui_reachable(base_url):
        return {"running": True, "url": base_url, "started_now": False}

    py_exe = comfy_dir / ".venv" / "Scripts" / "python.exe"
    main_py = comfy_dir / "main.py"
    if not py_exe.exists() or not main_py.exists():
        raise RuntimeError(f"ComfyUI installation not found at {comfy_dir}")

    log_path = comfy_dir / "comfyui_server.log"
    # Strip PyInstaller _MEIPASS / _internal entries from PATH so ComfyUI never loads DLLs from ClipForge\_internal
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("_MEIPASS")}
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and "PATH" in clean_env:
        mp_norm = str(Path(meipass).resolve()).lower()
        clean_env["PATH"] = os.pathsep.join(
            p for p in clean_env["PATH"].split(os.pathsep) if p and not p.lower().startswith(mp_norm)
        )
    env = {
        **clean_env,
        "HF_HOME": str(comfy_dir / ".hf-cache"),
        "TMP": str(comfy_dir / ".tmp"),
        "TEMP": str(comfy_dir / ".tmp"),
        "PYTHONUTF8": "1",
    }
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    with open(log_path, "ab") as log_fh:
        subprocess.Popen(
            [
                str(py_exe),
                str(main_py),
                "--listen",
                "127.0.0.1",
                "--port",
                "8188",
                "--lowvram",
                "--disable-auto-launch",
            ],
            cwd=str(comfy_dir),
            stdout=log_fh,
            stderr=log_fh,
            creationflags=creationflags,
            env=env,
        )

    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        if is_comfyui_reachable(base_url):
            return {"running": True, "url": base_url, "started_now": True}
        time.sleep(1.0)

    raise RuntimeError(
        f"ComfyUI failed to become reachable at {base_url} within {wait_sec}s. Check {log_path}"
    )


# ---------------------------------------------------------------------------
# Verified ComfyUI Video Workflow Builders
# ---------------------------------------------------------------------------
def build_wan22_i2v_workflow(
    prompt: str,
    image_filename: str,
    end_image_filename: str | None = None,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    width: int = 480,
    height: int = 832,
    num_frames: int = 81,
    fps: int = 16,
    steps: int = 6,
    cfg: float = 1.0,
    seed: int = -1,
    filename_prefix: str = "clipforge/wan22_i2v",
) -> dict[str, Any]:
    w = snap_dim(width, 16)
    h = snap_dim(height, 16)
    length = snap_frames(num_frames, 4)
    total_steps = max(4, min(30, int(steps)))
    split_step = max(2, total_steps // 2)
    actual_seed = random.randint(1, 2**50) if seed < 0 else int(seed)

    cond_inputs: dict[str, Any] = {
        "positive": ["9", 0],
        "negative": ["10", 0],
        "vae": ["8", 0],
        "width": w,
        "height": h,
        "length": length,
        "batch_size": 1,
        "start_image": ["11", 0],
    }
    cond_class = "WanImageToVideo"
    if end_image_filename:
        cond_class = "WanFirstLastFrameToVideo"
        cond_inputs["end_image"] = ["11b", 0]

    graph: dict[str, Any] = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"}},
        "3": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors",
                "strength_model": 1.0,
            },
        },
        "4": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["2", 0],
                "lora_name": "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors",
                "strength_model": 1.0,
            },
        },
        "5": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["3", 0], "shift": 5.0}},
        "6": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["4", 0], "shift": 5.0}},
        "7": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"},
        },
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["7", 0], "text": prompt}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["7", 0], "text": negative_prompt}},
        "11": {"class_type": "LoadImage", "inputs": {"image": image_filename}},
        "12": {"class_type": cond_class, "inputs": cond_inputs},
        "13": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["5", 0],
                "add_noise": "enable",
                "noise_seed": actual_seed,
                "steps": total_steps,
                "cfg": float(cfg),
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["12", 0],
                "negative": ["12", 1],
                "latent_image": ["12", 2],
                "start_at_step": 0,
                "end_at_step": split_step,
                "return_with_leftover_noise": "enable",
            },
        },
        "14": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["6", 0],
                "add_noise": "disable",
                "noise_seed": 0,
                "steps": total_steps,
                "cfg": float(cfg),
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["12", 0],
                "negative": ["12", 1],
                "latent_image": ["13", 0],
                "start_at_step": split_step,
                "end_at_step": total_steps,
                "return_with_leftover_noise": "disable",
            },
        },
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["8", 0]}},
        "16": {"class_type": "CreateVideo", "inputs": {"images": ["15", 0], "fps": float(fps)}},
        "17": {"class_type": "SaveVideo", "inputs": {"video": ["16", 0], "filename_prefix": filename_prefix, "format": "mp4"}},
    }
    if end_image_filename:
        graph["11b"] = {"class_type": "LoadImage", "inputs": {"image": end_image_filename}}
    return graph


def build_wan22_5b_workflow(
    prompt: str,
    image_filename: str | None = None,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    width: int = 480,
    height: int = 608,
    num_frames: int = 73,
    fps: int = 24,
    steps: int = 20,
    cfg: float = 3.8,
    seed: int = -1,
    filename_prefix: str = "clipforge/wan22_5b",
) -> dict[str, Any]:
    w = snap_dim(width, 32)
    h = snap_dim(height, 32)
    length = snap_frames(num_frames, 4)
    actual_seed = random.randint(1, 2**50) if seed < 0 else int(seed)

    latent_inputs: dict[str, Any] = {
        "vae": ["4", 0],
        "width": w,
        "height": h,
        "length": length,
        "batch_size": 1,
    }
    graph: dict[str, Any] = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-TI2V-5B-Q4_K_M.gguf"}},
        "2": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"},
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": negative_prompt}},
        "8": {"class_type": "Wan22ImageToVideoLatent", "inputs": latent_inputs},
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "seed": actual_seed,
                "steps": max(8, min(40, int(steps))),
                "cfg": float(cfg),
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["8", 0],
                "denoise": 1.0,
            },
        },
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["4", 0]}},
        "11": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "fps": float(fps)}},
        "12": {"class_type": "SaveVideo", "inputs": {"video": ["11", 0], "filename_prefix": filename_prefix, "format": "mp4"}},
    }
    if image_filename:
        graph["7"] = {"class_type": "LoadImage", "inputs": {"image": image_filename}}
        latent_inputs["start_image"] = ["7", 0]
    return graph


def build_ltx23_workflow(
    prompt: str,
    image_filename: str | None = None,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    width: int = 480,
    height: int = 832,
    num_frames: int = 97,
    fps: int = 24,
    steps: int = 8,
    cfg: float = 1.0,
    seed: int = -1,
    image_strength: float = 0.95,
    filename_prefix: str = "clipforge/ltx23",
) -> dict[str, Any]:
    w = snap_dim(width, 32)
    h = snap_dim(height, 32)
    length = snap_frames(num_frames, 8)
    actual_seed = random.randint(1, 2**50) if seed < 0 else int(seed)
    use_distilled_sigmas = int(steps) == 8

    graph: dict[str, Any] = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf"}},
        "2": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "gemma_3_12B_it_fp8_scaled.safetensors",
                "clip_name2": "ltx-2.3-22b-distilled_embeddings_connectors.safetensors",
                "type": "ltxv",
                "device": "default",
            },
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ltx-2.3-22b-distilled_video_vae.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "ltx-2.3-22b-distilled_audio_vae.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative_prompt}},
        "7": {
            "class_type": "LTXVConditioning",
            "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": float(fps)},
        },
        "8": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": w, "height": h, "length": length, "batch_size": 1}},
        "9": {
            "class_type": "LTXVEmptyLatentAudio",
            "inputs": {"frames_number": length, "frame_rate": float(fps), "batch_size": 1, "audio_vae": ["4", 0]},
        },
        "12": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["8", 0], "audio_latent": ["9", 0]}},
        "13": {
            "class_type": "CFGGuider",
            "inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["7", 1], "cfg": float(cfg)},
        },
        "14": {"class_type": "RandomNoise", "inputs": {"noise_seed": actual_seed}},
        "15": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "16": (
            {
                "class_type": "ManualSigmas",
                "inputs": {"sigmas": "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"},
            }
            if use_distilled_sigmas
            else {
                "class_type": "LTXVScheduler",
                "inputs": {
                    "steps": max(4, min(30, int(steps))),
                    "max_shift": 2.05,
                    "base_shift": 0.95,
                    "stretch": True,
                    "terminal": 0.1,
                    "latent": ["8", 0],
                },
            }
        ),
        "17": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {"noise": ["14", 0], "guider": ["13", 0], "sampler": ["15", 0], "sigmas": ["16", 0], "latent_image": ["12", 0]},
        },
        "18": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["17", 0]}},
        "19": {"class_type": "VAEDecode", "inputs": {"samples": ["18", 0], "vae": ["3", 0]}},
        "20": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["18", 1], "audio_vae": ["4", 0]}},
        "21": {"class_type": "CreateVideo", "inputs": {"images": ["19", 0], "fps": float(fps), "audio": ["20", 0]}},
        "22": {"class_type": "SaveVideo", "inputs": {"video": ["21", 0], "filename_prefix": filename_prefix, "format": "mp4"}},
    }
    if image_filename:
        graph["10"] = {"class_type": "LoadImage", "inputs": {"image": image_filename}}
        graph["10b"] = {"class_type": "LTXVPreprocess", "inputs": {"image": ["10", 0], "img_compression": 35}}
        graph["11"] = {
            "class_type": "LTXVImgToVideoInplace",
            "inputs": {
                "vae": ["3", 0],
                "image": ["10b", 0],
                "latent": ["8", 0],
                "strength": max(0.1, min(1.0, float(image_strength))),
                "bypass": False,
            },
        }
        graph["12"]["inputs"]["video_latent"] = ["11", 0]
    return graph


# ---------------------------------------------------------------------------
# Verified ComfyUI Image & Friend-Photo Editing Workflow Builders
# ---------------------------------------------------------------------------
def build_flux2_klein_workflow(
    prompt: str,
    image_filename: str | None = None,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 4,
    cfg: float = 1.0,
    seed: int = -1,
    filename_prefix: str = "clipforge/flux2_klein",
) -> dict[str, Any]:
    """FLUX.2 [klein] 4B Q4_K_M: 4-step ultra-fast T2I + Reference-Image Friend Photo Editing."""
    w = snap_dim(width, 16, minimum=512, maximum=1536)
    h = snap_dim(height, 16, minimum=512, maximum=1536)
    actual_seed = random.randint(1, 2**50) if seed < 0 else int(seed)

    graph: dict[str, Any] = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-2-klein-4b-Q4_K_M.gguf"}},
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_4b_fp8_mixed.safetensors", "type": "flux2", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative_prompt}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "10": {
            "class_type": "CFGGuider",
            "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": float(cfg)},
        },
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": actual_seed}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "13": {"class_type": "Flux2Scheduler", "inputs": {"steps": max(4, min(20, int(steps))), "width": w, "height": h}},
        "14": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {"noise": ["11", 0], "guider": ["10", 0], "sampler": ["12", 0], "sigmas": ["13", 0], "latent_image": ["6", 0]},
        },
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["3", 0]}},
        "16": {"class_type": "SaveImage", "inputs": {"images": ["15", 0], "filename_prefix": filename_prefix}},
    }

    if image_filename:
        graph["7"] = {"class_type": "LoadImage", "inputs": {"image": image_filename}}
        graph["8"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["3", 0]}}
        graph["9"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["4", 0], "latent": ["8", 0]}}
        graph["9b"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["5", 0], "latent": ["8", 0]}}
        graph["10"]["inputs"]["positive"] = ["9", 0]
        graph["10"]["inputs"]["negative"] = ["9b", 0]

    return graph


def build_z_image_turbo_workflow(
    prompt: str,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    width: int = 1024,
    height: int = 1024,
    steps: int = 8,
    cfg: float = 1.0,
    seed: int = -1,
    filename_prefix: str = "clipforge/z_image_turbo",
) -> dict[str, Any]:
    """Z-Image-Turbo Q4_K_M: 8-step hyper-real candid photography & crisp embedded meme text."""
    w = snap_dim(width, 16, minimum=512, maximum=1536)
    h = snap_dim(height, 16, minimum=512, maximum=1536)
    actual_seed = random.randint(1, 2**50) if seed < 0 else int(seed)

    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "z-image-turbo-Q4_K_M.gguf"}},
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_4b_fp8_mixed.safetensors", "type": "lumina2", "device": "default"},
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": negative_prompt}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "seed": actual_seed,
                "steps": max(4, min(20, int(steps))),
                "cfg": float(cfg),
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
                "denoise": 1.0,
            },
        },
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["4", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": filename_prefix}},
    }


def build_qwen_edit_workflow(
    prompt: str,
    image_filename: str,
    image_filename_2: str | None = None,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 2.5,
    seed: int = -1,
    filename_prefix: str = "clipforge/qwen_edit",
) -> dict[str, Any]:
    """Qwen-Image-Edit 2509 Q4_K_M: Heavyweight instruction-based 1-2 friend photo compositor."""
    w = snap_dim(width, 16, minimum=512, maximum=1536)
    h = snap_dim(height, 16, minimum=512, maximum=1536)
    actual_seed = random.randint(1, 2**50) if seed < 0 else int(seed)

    pos_inputs: dict[str, Any] = {"clip": ["3", 0], "prompt": prompt, "vae": ["4", 0], "image1": ["5", 0]}
    neg_inputs: dict[str, Any] = {"clip": ["3", 0], "prompt": negative_prompt, "vae": ["4", 0], "image1": ["5", 0]}

    graph: dict[str, Any] = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Qwen-Image-Edit-2509-Q4_K_M.gguf"}},
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"},
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_filename}},
        "6": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": pos_inputs},
        "7": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": neg_inputs},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "seed": actual_seed,
                "steps": max(8, min(40, int(steps))),
                "cfg": float(cfg),
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["8", 0],
                "denoise": 1.0,
            },
        },
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["4", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": filename_prefix}},
    }
    if image_filename_2:
        graph["5b"] = {"class_type": "LoadImage", "inputs": {"image": image_filename_2}}
        pos_inputs["image2"] = ["5b", 0]
        neg_inputs["image2"] = ["5b", 0]
    return graph


# ---------------------------------------------------------------------------
# ComfyUI Execution Client with Live WebSocket Step Progress
# ---------------------------------------------------------------------------
def _upload_image_to_comfyui(image_path: str | Path, base_url: str = COMFYUI_URL) -> str:
    p = Path(image_path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Reference image not found: {p}")

    ext = p.suffix.lower() or ".png"
    safe_name = f"cf_ref_{uuid.uuid4().hex[:8]}{ext}"
    with open(p, "rb") as fh:
        resp = httpx.post(
            f"{base_url}/upload/image",
            files={"image": (safe_name, fh, "application/octet-stream")},
            data={"overwrite": "true"},
            timeout=60.0,
        )
    resp.raise_for_status()
    return resp.json()["name"]


def _extract_saved_output_info(history_entry: dict[str, Any], extensions: tuple[str, ...]) -> dict[str, str] | None:
    outputs = history_entry.get("outputs") or {}
    for _node_id, node_out in outputs.items():
        for key in ("videos", "images", "gifs"):
            items = node_out.get(key)
            if isinstance(items, list) and items:
                for it in items:
                    fn = it.get("filename", "")
                    if fn.lower().endswith(extensions):
                        return {
                            "filename": fn,
                            "subfolder": it.get("subfolder", ""),
                            "type": it.get("type", "output"),
                        }
    return None


def _execute_comfyui_workflow(
    workflow: dict[str, Any],
    base_url: str,
    timeout_sec: float,
    extensions: tuple[str, ...],
    on_progress: Callable[[str, int | None], None] | None = None,
) -> tuple[str, dict[str, str], float]:
    """Queue workflow, stream live step progress over ComfyUI WebSocket, and return saved artifact info."""
    client_id = f"clipforge_{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()

    # Optional background WS listener for exact sampling step percentages
    ws_stop = threading.Event()
    step_info = {"pct": 5, "label": "Queued on RTX 4060..."}

    def _ws_listener() -> None:
        try:
            from websockets.sync.client import connect as ws_connect

            ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={client_id}"
            with ws_connect(ws_url, open_timeout=5.0, close_timeout=2.0) as ws:
                while not ws_stop.is_set():
                    try:
                        raw = ws.recv(timeout=1.0)
                    except TimeoutError:
                        continue
                    if not isinstance(raw, str):
                        continue
                    msg = json.loads(raw)
                    mtype = msg.get("type")
                    data = msg.get("data") or {}
                    if mtype == "progress":
                        val = int(data.get("value", 0))
                        mx = max(1, int(data.get("max", 1)))
                        pct = min(98, max(5, int(round((val / mx) * 100))))
                        step_info["pct"] = pct
                        step_info["label"] = f"Sampling step {val}/{mx} ({pct}%)"
                        if on_progress:
                            on_progress(step_info["label"], pct)
                    elif mtype == "executing":
                        node_id = data.get("node")
                        if node_id and node_id in workflow:
                            ct = workflow[node_id]["class_type"]
                            step_info["label"] = f"Running {ct}..."
                            if on_progress:
                                on_progress(step_info["label"], step_info["pct"])
        except Exception:
            pass

    ws_thread = threading.Thread(target=_ws_listener, daemon=True)
    ws_thread.start()

    try:
        resp = httpx.post(
            f"{base_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            timeout=30.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"ComfyUI rejected workflow ({resp.status_code}): {resp.text[:1200]}")

        prompt_id = resp.json()["prompt_id"]
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            hist_resp = httpx.get(f"{base_url}/history/{prompt_id}", timeout=15.0)
            if hist_resp.status_code == 200:
                hist = hist_resp.json()
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        raise RuntimeError(f"ComfyUI execution failed: {json.dumps(msgs)[:1200]}")

                    out_info = _extract_saved_output_info(entry, extensions=extensions)
                    if out_info:
                        elapsed = round(time.perf_counter() - t0, 2)
                        return prompt_id, out_info, elapsed
            if on_progress:
                elapsed_s = int(time.perf_counter() - t0)
                on_progress(f"{step_info['label']} · {elapsed_s}s", step_info["pct"])
            time.sleep(1.5)

        raise TimeoutError(f"ComfyUI generation timed out after {timeout_sec}s (prompt_id={prompt_id}).")
    finally:
        ws_stop.set()


def generate_video_via_comfyui(
    prompt: str,
    output_dir: Path,
    model: VideoModelId = "wan22_5b",
    image_path: str | None = None,
    end_image_path: str | None = None,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    style_preset: str | None = None,
    camera_preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    num_frames: int | None = None,
    fps: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    seed: int = -1,
    base_url: str = COMFYUI_URL,
    comfy_dir: Path = COMFYUI_DIR,
    auto_start: bool = True,
    timeout_sec: float = 1800.0,
    on_progress: Callable[[str, int | None], None] | None = None,
) -> dict[str, Any]:
    """Queue a Wan 2.2 or LTX-2.3 video workflow on local ComfyUI and save the rendered MP4."""
    if model not in MODEL_SPECS or MODEL_SPECS[model]["kind"] != "video":
        raise ValueError(f"Unknown video model '{model}'. Valid: wan22_5b, wan22_i2v, ltx23")

    spec = MODEL_SPECS[model]
    if spec["requires_image"] and not image_path:
        raise ValueError(f"Model '{spec['display_name']}' requires a reference photo (`image_path`).")

    avail = get_model_availability(comfy_dir)
    if not avail[model]["ready"]:
        ready_vids = [k for k, v in avail.items() if v["kind"] == "video" and v["ready"]]
        hint = f" Ready right now: {', '.join(ready_vids)}." if ready_vids else ""
        raise RuntimeError(
            f"'{spec['display_name']}' needs {avail[model]['missing_gb']} GB downloaded first "
            f"(open Model Manager to download).{hint}"
        )

    if auto_start:
        if on_progress:
            on_progress("Checking local ComfyUI engine...", 2)
        ensure_comfyui_running(comfy_dir=comfy_dir, base_url=base_url)
    elif not is_comfyui_reachable(base_url):
        raise RuntimeError(f"ComfyUI is not running at {base_url}")

    uploaded_img_name: str | None = None
    uploaded_end_name: str | None = None
    if image_path:
        if on_progress:
            on_progress("Uploading start frame image...", 4)
        uploaded_img_name = _upload_image_to_comfyui(image_path, base_url=base_url)
    if end_image_path and spec.get("supports_end_image"):
        if on_progress:
            on_progress("Uploading end frame image...", 6)
        uploaded_end_name = _upload_image_to_comfyui(end_image_path, base_url=base_url)

    full_prompt = apply_prompt_preset(prompt, style_preset, camera_preset)
    use_w = width or spec["default_width"]
    use_h = height or spec["default_height"]
    use_frames = num_frames or spec["default_frames"]
    use_fps = fps or spec["default_fps"]
    use_steps = steps or spec["default_steps"]
    use_cfg = cfg if cfg is not None else spec["default_cfg"]
    run_id = uuid.uuid4().hex[:8]

    if model == "wan22_i2v":
        assert uploaded_img_name is not None
        workflow = build_wan22_i2v_workflow(
            prompt=full_prompt,
            image_filename=uploaded_img_name,
            end_image_filename=uploaded_end_name,
            negative_prompt=negative_prompt,
            width=use_w,
            height=use_h,
            num_frames=use_frames,
            fps=use_fps,
            steps=use_steps,
            cfg=use_cfg,
            seed=seed,
            filename_prefix=f"clipforge/wan22_i2v_{run_id}",
        )
    elif model == "wan22_5b":
        workflow = build_wan22_5b_workflow(
            prompt=full_prompt,
            image_filename=uploaded_img_name,
            negative_prompt=negative_prompt,
            width=use_w,
            height=use_h,
            num_frames=use_frames,
            fps=use_fps,
            steps=use_steps,
            cfg=use_cfg,
            seed=seed,
            filename_prefix=f"clipforge/wan22_5b_{run_id}",
        )
    else:
        workflow = build_ltx23_workflow(
            prompt=full_prompt,
            image_filename=uploaded_img_name,
            negative_prompt=negative_prompt,
            width=use_w,
            height=use_h,
            num_frames=use_frames,
            fps=use_fps,
            steps=use_steps,
            cfg=use_cfg,
            seed=seed,
            filename_prefix=f"clipforge/ltx23_{run_id}",
        )

    prompt_id, vid_info, elapsed = _execute_comfyui_workflow(
        workflow=workflow,
        base_url=base_url,
        timeout_sec=timeout_sec,
        extensions=(".mp4", ".webm", ".mkv", ".mov"),
        on_progress=on_progress,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"{model}_{run_id}.mp4"
    view_resp = httpx.get(f"{base_url}/view", params=vid_info, timeout=120.0)
    view_resp.raise_for_status()
    dest.write_bytes(view_resp.content)

    return {
        "video_path": str(dest.resolve()),
        "filename": dest.name,
        "model": model,
        "prompt": full_prompt,
        "prompt_id": prompt_id,
        "generation_time_sec": elapsed,
        "file_size_bytes": dest.stat().st_size,
    }


def generate_image_via_comfyui(
    prompt: str,
    output_dir: Path,
    model: ImageModelId = "flux2_klein",
    image_path: str | None = None,
    image_path_2: str | None = None,
    negative_prompt: str = "",
    style_preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    seed: int = -1,
    batch_size: int = 1,
    base_url: str = COMFYUI_URL,
    comfy_dir: Path = COMFYUI_DIR,
    auto_start: bool = True,
    timeout_sec: float = 600.0,
    on_progress: Callable[[str, int | None], None] | None = None,
) -> dict[str, Any]:
    """Queue 1-4 FLUX.2-klein, Z-Image-Turbo, or Qwen-Image-Edit runs (4-seed meme contact sheet)."""
    if model not in MODEL_SPECS or MODEL_SPECS[model]["kind"] != "image":
        raise ValueError(f"Unknown image model '{model}'. Valid: flux2_klein, z_image_turbo, qwen_edit")

    spec = MODEL_SPECS[model]
    if spec["requires_image"] and not image_path:
        raise ValueError(f"Model '{spec['display_name']}' requires at least one reference photo (`image_path`).")

    avail = get_model_availability(comfy_dir)
    if not avail[model]["ready"]:
        ready_imgs = [k for k, v in avail.items() if v["kind"] == "image" and v["ready"]]
        hint = f" Ready right now: {', '.join(ready_imgs)}." if ready_imgs else ""
        raise RuntimeError(
            f"'{spec['display_name']}' needs {avail[model]['missing_gb']} GB downloaded first "
            f"(click Download in Model Manager).{hint}"
        )

    if auto_start:
        if on_progress:
            on_progress("Checking local ComfyUI engine...", 2)
        ensure_comfyui_running(comfy_dir=comfy_dir, base_url=base_url)
    elif not is_comfyui_reachable(base_url):
        raise RuntimeError(f"ComfyUI is not running at {base_url}")

    up_img1: str | None = None
    up_img2: str | None = None
    if image_path and spec["supports_image"]:
        if on_progress:
            on_progress("Uploading friend photo #1...", 4)
        up_img1 = _upload_image_to_comfyui(image_path, base_url=base_url)
    if image_path_2 and spec["supports_second_image"]:
        if on_progress:
            on_progress("Uploading friend photo #2...", 6)
        up_img2 = _upload_image_to_comfyui(image_path_2, base_url=base_url)

    full_prompt = apply_prompt_preset(prompt, style_preset)
    use_w = width or spec["default_width"]
    use_h = height or spec["default_height"]
    use_steps = steps or spec["default_steps"]
    use_cfg = cfg if cfg is not None else spec["default_cfg"]
    count = max(1, min(4, int(batch_size)))
    base_seed = random.randint(1, 2**48) if seed < 0 else int(seed)

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_list: list[dict[str, Any]] = []
    total_elapsed = 0.0

    for i in range(count):
        cur_seed = base_seed + i if seed >= 0 else random.randint(1, 2**50)
        run_id = uuid.uuid4().hex[:8]

        if model == "flux2_klein":
            workflow = build_flux2_klein_workflow(
                prompt=full_prompt,
                image_filename=up_img1,
                negative_prompt=negative_prompt,
                width=use_w,
                height=use_h,
                steps=use_steps,
                cfg=use_cfg,
                seed=cur_seed,
                filename_prefix=f"clipforge/flux2_klein_{run_id}",
            )
        elif model == "z_image_turbo":
            workflow = build_z_image_turbo_workflow(
                prompt=full_prompt,
                negative_prompt=negative_prompt or DEFAULT_NEGATIVE_PROMPT,
                width=use_w,
                height=use_h,
                steps=use_steps,
                cfg=use_cfg,
                seed=cur_seed,
                filename_prefix=f"clipforge/z_image_{run_id}",
            )
        else:
            assert up_img1 is not None
            workflow = build_qwen_edit_workflow(
                prompt=full_prompt,
                image_filename=up_img1,
                image_filename_2=up_img2,
                negative_prompt=negative_prompt,
                width=use_w,
                height=use_h,
                steps=use_steps,
                cfg=use_cfg,
                seed=cur_seed,
                filename_prefix=f"clipforge/qwen_edit_{run_id}",
            )

        def _batch_prog(msg: str, pct: int | None) -> None:
            if not on_progress:
                return
            if count == 1:
                on_progress(msg, pct)
            else:
                local_p = pct if pct is not None else 50
                overall = min(98, max(5, int(((i + local_p / 100.0) / count) * 100)))
                on_progress(f"Seed {i + 1}/{count}: {msg}", overall)

        prompt_id, img_info, elapsed = _execute_comfyui_workflow(
            workflow=workflow,
            base_url=base_url,
            timeout_sec=timeout_sec,
            extensions=(".png", ".jpg", ".jpeg", ".webp"),
            on_progress=_batch_prog,
        )
        total_elapsed = round(total_elapsed + elapsed, 2)

        dest = output_dir / f"{model}_{run_id}.png"
        view_resp = httpx.get(f"{base_url}/view", params=img_info, timeout=60.0)
        view_resp.raise_for_status()
        dest.write_bytes(view_resp.content)

        generated_list.append(
            {
                "image_path": str(dest.resolve()),
                "filename": dest.name,
                "seed": cur_seed,
                "prompt_id": prompt_id,
                "generation_time_sec": elapsed,
                "file_size_bytes": dest.stat().st_size,
            }
        )

    first = generated_list[0]
    return {
        "image_path": first["image_path"],
        "filename": first["filename"],
        "images": generated_list,
        "batch_size": len(generated_list),
        "model": model,
        "prompt": full_prompt,
        "prompt_id": first["prompt_id"],
        "generation_time_sec": total_elapsed,
        "file_size_bytes": first["file_size_bytes"],
    }


# ---------------------------------------------------------------------------
# Background Job Registry for Non-Blocking Web UI Generation
# ---------------------------------------------------------------------------
@dataclass
class GenerationJob:
    id: str
    kind: str  # "video" | "image"
    model: str
    prompt: str
    status: str = "queued"  # queued | running | completed | failed
    message: str = "Queued"
    progress_pct: int = 0
    created_at: float = field(default_factory=time.time)
    result: dict[str, Any] | None = None
    error: str | None = None


class GenerationJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, GenerationJob] = {}

    def create(self, kind: str, model: str, prompt: str) -> GenerationJob:
        job = GenerationJob(id=f"gen_{uuid.uuid4().hex[:8]}", kind=kind, model=model, prompt=prompt)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > 30:
                oldest = next(iter(self._jobs))
                del self._jobs[oldest]
        return job

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": j.id,
                    "kind": j.kind,
                    "model": j.model,
                    "prompt": j.prompt,
                    "status": j.status,
                    "message": j.message,
                    "progress_pct": j.progress_pct,
                    "result": j.result,
                    "error": j.error,
                }
                for j in reversed(list(self._jobs.values()))
            ]


job_manager = GenerationJobManager()
