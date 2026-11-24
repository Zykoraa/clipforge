"""Offline Local LLM Prompt Director (Ollama / LM Studio) — model-aware positive + negative prompt expander."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import urlparse

import httpx

from .generator import CAMERA_PRESETS, DEFAULT_NEGATIVE_PROMPT, MODEL_SPECS, PROMPT_PRESETS
from .sfx import BUILTIN_SFX

DEFAULT_DIRECTOR_ENDPOINTS = [
    os.environ.get("CLIPFORGE_LLM_URL", "").strip(),
    "http://127.0.0.1:1234/v1",  # LM Studio default
    "http://127.0.0.1:11434/v1",  # Ollama OpenAI-compatible default
]

VALID_SFX_IDS = tuple(BUILTIN_SFX.keys())

_STYLIZED_PRESETS = {"gta_loading", "ps2_cutscene", "anime_sakuga"}
_NON_CHAT_MARKERS = (
    "qwen-image",
    "qwen_image",
    "embed",
    "nomic",
    "bge-",
    "mxbai",
    "whisper",
    "rerank",
    "flux",
    "sdxl",
    "wan2",
    "ltx",
)
_UNCENSORED_MARKERS = ("uncensored", "abliterated", "heretic", "defiant", "dolphin", "lexi", "uncnr")
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def _query_free_vram_mb() -> int | None:
    """Return currently free GPU VRAM in MiB via nvidia-smi (fast, non-fatal)."""
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        return None
    try:
        res = subprocess.run(
            [nvsmi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return int(float(res.stdout.strip().splitlines()[0].strip()))
    except Exception:
        pass
    return None


def _ollama_origin(base_v1: str) -> str | None:
    """Return Ollama root URL (e.g. http://127.0.0.1:11434) if endpoint looks like Ollama, else None."""
    parsed = urlparse(base_v1)
    root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if not root:
        return None
    if parsed.port == 11434:
        return root
    try:
        r = httpx.get(f"{root}/api/tags", timeout=1.0)
        if r.status_code == 200 and "models" in r.json():
            return root
    except Exception:
        pass
    return None


def _is_chat_model(model_id: str, family: str = "") -> bool:
    low = f"{model_id} {family}".lower()
    return not any(bad in low for bad in _NON_CHAT_MARKERS)


def _score_llm_candidate(model_id: str, size_bytes: int = 0, family: str = "", caps: list[str] | None = None) -> int:
    """Score candidate local LLMs for fast, zero-refusal prompt expansion without fighting ComfyUI for VRAM."""
    if not _is_chat_model(model_id, family):
        return -10_000

    low = model_id.lower()
    fam = (family or "").lower()
    score = 0

    if any(k in low for k in _UNCENSORED_MARKERS):
        score += 45

    size_gb = size_bytes / (1024**3) if size_bytes > 0 else 0.0
    if 0.5 < size_gb <= 6.5:
        score += 35
    elif 6.5 < size_gb <= 9.5:
        score += 20
    elif size_gb > 10.5:
        score -= 30
    else:
        # Size unknown (OpenAI-compat endpoint): infer from parameter tag
        if any(tag in low for tag in ("3b", "4b", "e4b", "7b", "8b", "9b")):
            score += 25
        elif any(tag in low for tag in ("27b", "32b", "70b")):
            score -= 25

    # Gemma 4 E4B & Llama 3 8B are fast on both GPU and CPU fallback, with crisp instruction following
    if "gemma-4" in low or "gemma4" in fam or "e4b" in low:
        score += 22
    elif "llama-3" in low or "llama3" in low:
        score += 14
    elif "qwen2.5" in low or "qwen3-" in low:
        score += 10
    elif "qwen3.5" in low or "qwen35" in fam:
        # Hybrid architecture can be slow on CPU when ComfyUI holds VRAM
        score += 4

    # Deprioritize mandatory heavy chain-of-thought reasoning models (slow + often censored)
    if "deepseek-r1" in low or "qwq" in low:
        score -= 45

    if caps and "thinking" not in caps:
        score += 6

    return score


def _fetch_ollama_model_meta(ollama_root: str) -> dict[str, dict[str, Any]]:
    try:
        r = httpx.get(f"{ollama_root}/api/tags", timeout=1.5)
        if r.status_code == 200:
            meta: dict[str, dict[str, Any]] = {}
            for m in r.json().get("models") or []:
                name = m.get("name") or m.get("model")
                if not name:
                    continue
                det = m.get("details") or {}
                meta[name] = {
                    "size_bytes": int(m.get("size") or 0),
                    "family": str(det.get("family") or ""),
                    "capabilities": list(m.get("capabilities") or []),
                }
            return meta
    except Exception:
        pass
    return {}


def discover_local_llm(endpoint: str | None = None) -> dict[str, Any]:
    """Probe local OpenAI-compatible / Ollama LLM endpoints on loopback and rank best chat models."""
    candidates = [endpoint.strip().rstrip("/")] if endpoint and endpoint.strip() else []
    for ep in DEFAULT_DIRECTOR_ENDPOINTS:
        clean = ep.rstrip("/")
        if clean and clean not in candidates:
            candidates.append(clean)

    for base in candidates:
        try:
            r = httpx.get(f"{base}/models", timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                raw_models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
                ollama_root = _ollama_origin(base)
                ollama_meta = _fetch_ollama_model_meta(ollama_root) if ollama_root else {}

                chat_models = [
                    mid
                    for mid in raw_models
                    if _is_chat_model(mid, ollama_meta.get(mid, {}).get("family", ""))
                ]
                chat_models.sort(
                    key=lambda mid: _score_llm_candidate(
                        mid,
                        size_bytes=ollama_meta.get(mid, {}).get("size_bytes", 0),
                        family=ollama_meta.get(mid, {}).get("family", ""),
                        caps=ollama_meta.get(mid, {}).get("capabilities"),
                    ),
                    reverse=True,
                )
                return {
                    "available": True,
                    "endpoint": base,
                    "ollama_root": ollama_root,
                    "models": chat_models or raw_models,
                    "recommended_model": chat_models[0] if chat_models else (raw_models[0] if raw_models else None),
                    "model_meta": ollama_meta,
                }
        except Exception:
            continue
    return {
        "available": False,
        "endpoint": candidates[0] if candidates else "http://127.0.0.1:1234/v1",
        "ollama_root": None,
        "models": [],
        "recommended_model": None,
        "model_meta": {},
    }


def _describe_target_for_llm(
    mode: str,
    model_id: str | None,
    style_preset: str | None,
    camera_preset: str | None,
    has_friend_photo: bool,
    has_second_photo: bool,
    has_end_frame: bool,
) -> tuple[str, str]:
    """Build model-specific positive & negative guidance for the LLM prompt director."""
    mid = (model_id or "").strip().lower()
    spec = MODEL_SPECS.get(mid) or {}
    model_label = spec.get("display_name") or ("local video generator" if mode == "video" else "local image generator")

    rules: list[str] = [f"Target generator: {model_label} ({mode})."]

    if mid == "ltx23":
        rules.append(
            "LTX-2.3 generates SYNCHRONIZED AUDIO AND VIDEO together (~4s). "
            "Write ONE continuous chronological shot describing physical motion, facial expressions, lighting, camera feel, "
            "AND weave explicit concrete sound effects, ambient noise, and exact voice/screaming/dialogue audio naturally into the same prose paragraph "
            "(e.g. mic quality, crashing impacts, shouting tone). Do NOT use headings, bullet points, or markdown asterisks."
        )
    elif mid == "wan22_i2v":
        if has_end_frame:
            rules.append(
                "Wan 2.2 First-to-Last Frame Morph: describe the smooth, physically believable motion, facial transition, and camera movement "
                "bridging from the attached start image into the attached end image."
            )
        else:
            rules.append(
                "Wan 2.2 Image-to-Video: the attached start image already defines the subject's appearance and initial framing. "
                "Focus heavily on concrete motion, facial expression shifts, physical action beats, environmental reactions, and camera movement over 4-5 seconds."
            )
    elif mid in ("wan22_t2v", "wan22_5b") or mode == "video":
        rules.append(
            "Text-to-Video: describe the subject, environment, lighting, camera movement, and continuous physical action clearly in one vivid paragraph."
        )
    elif mid in ("qwen_edit", "qwen_edit_2511"):
        if has_second_photo:
            rules.append(
                "Qwen-Image-Edit Multi-Photo Compositor: write a clear, direct editing instruction combining the exact person from image 1 "
                "and the exact person from image 2 into the same scene. Preserve both faces/identities faithfully while describing their poses, "
                "expressions, interaction, outfits, lighting match, and camera framing."
            )
        else:
            rules.append(
                "Qwen-Image-Edit: write a clear, direct photo-editing instruction keeping the exact person and facial identity from the reference photo, "
                "changing only what the user wants (setting, pose, expression, outfit, lighting, camera framing) with seamless natural lighting."
            )
    elif mid in ("flux2_klein", "flux2_klein_9b"):
        if has_friend_photo:
            rules.append(
                "FLUX.2 Reference Edit: write a vivid natural-language scene instruction placing the exact person from the reference photo "
                "into the requested scenario, preserving their exact face/likeness while specifying pose, expression, lighting, lens, and candid environment details."
            )
        else:
            rules.append(
                "FLUX.2 Text-to-Image: write a vivid natural-language photograph/scene description with concrete lighting, framing, lens, and expressions. "
                "Avoid tag-soup buzzwords like '8k, masterpiece, trending on artstation'."
            )
    elif mid == "z_image_turbo":
        rules.append(
            "Z-Image-Turbo: excels at candid hyper-real photography and crisp visible text. If the user's idea implies visible text/signs/shirts/overlays, "
            "put the exact words inside double quotes."
        )

    if has_friend_photo and mid not in ("qwen_edit", "qwen_edit_2511"):
        rules.append(
            "A reference photo of the subject is attached — refer to them naturally as 'the person' / 'this person from the reference photo' "
            "and NEVER invent a conflicting age, hair color, or facial traits that might override their real face."
        )

    preset_info = PROMPT_PRESETS.get(style_preset or "")
    if style_preset and style_preset != "none" and preset_info:
        rules.append(
            f"Style preset ALREADY selected by user: '{preset_info['label']}' ({preset_info['suffix']}). "
            "Write in complete harmony with this exact visual style — do NOT contradict it (e.g. do not say 'iPhone photo' if preset is GTA/Anime/Bodycam/Doorbell) "
            "and do not repeat the preset's exact suffix verbatim."
        )
    else:
        rules.append(
            "No style preset is locked: infer the most fitting visual style directly from the user's rough idea "
            "(e.g. doorbell cam -> night-vision fisheye porch cam; bodycam -> chest-mounted police cam; otherwise authentic candid realism)."
        )

    cam_info = CAMERA_PRESETS.get(camera_preset or "")
    if mode == "video" and camera_preset and camera_preset != "none" and cam_info:
        rules.append(f"Camera motion preset ALREADY selected: '{cam_info['label']}' ({cam_info['suffix']}). Match this camera feel.")

    is_stylized = (style_preset or "") in _STYLIZED_PRESETS
    if is_stylized:
        neg_guide = (
            "Write `negative_prompt` as 12-22 concise comma-separated quality/style flaws to avoid "
            "(include photorealistic/blurry/deformed anatomy/watermark/bad framing, matching the stylized look). No prose prefixes like 'Avoid:'."
        )
    else:
        extra_neg = (
            "static frame, frozen subject, morphing face, garbled audio, silent clip"
            if mid == "ltx23"
            else ("static frame, frozen subject, morphing face, jittering" if mode == "video" else "plastic skin, airbrushed AI gloss, cartoon, 3d render")
        )
        neg_guide = (
            f"Write `negative_prompt` as 12-25 concise comma-separated artifacts/flaws to avoid "
            f"(e.g. blurry, deformed face, extra limbs, watermark, {extra_neg}, plus anything contradicting the user's mood/scene). "
            "Output ONLY comma-separated terms — never start with 'Avoid' or full sentences."
        )

    return " ".join(rules), neg_guide


def _clean_prompt_text(raw: str) -> str:
    txt = _THINK_BLOCK_RE.sub("", str(raw or "")).strip()
    # Strip markdown bold/italic wrappers such as **Synchronized Audio:** or *Audio:*
    txt = re.sub(r"\*{1,2}([^*]+?)\*{1,2}", r"\1", txt)
    txt = re.sub(r"\s+", " ", txt).strip(" \"'")
    return txt


def _clean_negative_text(raw: str) -> str:
    txt = _THINK_BLOCK_RE.sub("", str(raw or "")).strip()
    txt = re.sub(r"^(?:avoid(?:\s+any)?(?:\s+artifacts)?(?:\s+such\s+as)?|do\s+not\s+include|negative\s+prompt)\s*:?\s*", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\s+", " ", txt).strip(" .\"'")
    return txt


def _extract_json_obj(raw_content: str) -> dict[str, Any] | None:
    cleaned = _THINK_BLOCK_RE.sub("", raw_content or "").strip()
    if "```" in cleaned:
        for part in cleaned.split("```"):
            p_s = part.strip()
            if p_s.lower().startswith("json"):
                p_s = p_s[4:].strip()
            if p_s.startswith("{"):
                cleaned = p_s
                break
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _default_negative_for(mode: str, model_id: str | None, style_preset: str | None) -> str:
    mid = (model_id or "").lower()
    if (style_preset or "") in _STYLIZED_PRESETS:
        return (
            "blurry, low quality, worst quality, deformed face, extra limbs, watermark, "
            "text artifacts, bad anatomy, muddy colors, cropped head"
        )
    if mid == "ltx23":
        return (
            "blurry, static frame, frozen subject, low quality, worst quality, watermark, "
            "deformed face, extra limbs, jittering, plastic skin, garbled audio, robotic voice, out of sync audio"
        )
    if mode == "video":
        return (
            "blurry, static image, frozen subject, low quality, worst quality, watermark, "
            "deformed face, morphing face, extra limbs, jittering, plastic skin, overexposed"
        )
    return (
        "blurry, low quality, worst quality, watermark, deformed face, extra fingers, extra limbs, "
        "plastic skin, airbrushed AI gloss, cartoon, 3d render, oversaturated"
    )


def _pick_sfx(raw_sfx: str | None, idea_lower: str) -> str:
    cand = (raw_sfx or "").strip().lower()
    if cand in BUILTIN_SFX:
        return cand
    if any(w in idea_lower for w in ("cop", "police", "arrest", "bodycam", "siren", "news", "breaking")):
        return "alert_siren"
    if any(w in idea_lower for w in ("door", "porch", "knock", "fbi", "raid")):
        return "fbi_knock"
    if any(w in idea_lower for w in ("fail", "cry", "sad", "fell", "embarrass")):
        return "sad_trombone"
    if any(w in idea_lower for w in ("scream", "smash", "angry", "rage", "punch", "explode")):
        return "bass_drop"
    return "vine_boom"


def expand_meme_prompt_local(
    idea: str,
    mode: str = "image",
    has_friend_photo: bool = False,
    endpoint: str | None = None,
    model_name: str | None = None,
    model_id: str | None = None,
    style_preset: str | None = None,
    camera_preset: str | None = None,
    has_second_photo: bool = False,
    has_end_frame: bool = False,
) -> dict[str, Any]:
    """Expand a rough 1-line idea into tailored positive + negative prompts using a local uncensored LLM."""
    clean_idea = (idea or "").strip()
    if not clean_idea:
        raise ValueError("Idea cannot be empty.")

    disc = discover_local_llm(endpoint=endpoint)
    env_model = os.environ.get("CLIPFORGE_LLM_MODEL", "").strip()
    if disc["available"] and disc["models"]:
        if model_name and model_name in disc["models"]:
            use_model = model_name
        elif env_model and env_model in disc["models"]:
            use_model = env_model
        else:
            use_model = disc.get("recommended_model") or disc["models"][0]

        target_guide, neg_guide = _describe_target_for_llm(
            mode=mode,
            model_id=model_id,
            style_preset=style_preset,
            camera_preset=camera_preset,
            has_friend_photo=has_friend_photo,
            has_second_photo=has_second_photo,
            has_end_frame=has_end_frame,
        )
        sfx_list = ", ".join(VALID_SFX_IDS)
        sys_msg = (
            "You are an expert prompt engineer for local offline AI video and image generators. "
            "Turn the user's rough, casual idea into an immediately usable, concrete, vivid generation prompt and matching negative prompt. "
            "Preserve ALL of the user's exact intent, humor, chaos, and tone faithfully without censoring, lecturing, or sanitizing. "
            f"{target_guide} {neg_guide} "
            "Return ONLY a valid JSON object with keys: `prompt` (60-105 words of plain descriptive prose, no markdown), "
            "`negative_prompt` (comma-separated flaws to avoid), `meme_top_text` (short punchy caption <= 50 chars), "
            f"and `recommended_sfx` (pick exactly ONE id from: {sfx_list})."
        )
        user_msg = f"Rough user idea: {clean_idea}"

        parsed: dict[str, Any] | None = None
        ollama_root = disc.get("ollama_root")
        try:
            if ollama_root:
                # Native Ollama /api/chat: disables thinking tokens, enforces JSON, limits KV-cache context,
                # unloads immediately (keep_alive=0) so ComfyUI never loses VRAM, and auto-runs on CPU if GPU is busy.
                meta = (disc.get("model_meta") or {}).get(use_model) or {}
                model_mb = int((meta.get("size_bytes") or 0) / (1024 * 1024))
                free_vram_mb = _query_free_vram_mb()
                options: dict[str, Any] = {
                    "temperature": 0.72,
                    "num_predict": 420,
                    "num_ctx": 2048,
                }
                if free_vram_mb is not None and model_mb > 0 and free_vram_mb < (model_mb + 2500):
                    options["num_gpu"] = 0

                resp = httpx.post(
                    f"{ollama_root}/api/chat",
                    json={
                        "model": use_model,
                        "think": False,
                        "stream": False,
                        "keep_alive": 0,
                        "format": "json",
                        "options": options,
                        "messages": [
                            {"role": "system", "content": sys_msg},
                            {"role": "user", "content": user_msg},
                        ],
                    },
                    timeout=35.0,
                )
                if resp.status_code == 200:
                    content = (resp.json().get("message") or {}).get("content") or ""
                    parsed = _extract_json_obj(content)
            else:
                resp = httpx.post(
                    f"{disc['endpoint']}/chat/completions",
                    json={
                        "model": use_model,
                        "messages": [
                            {"role": "system", "content": sys_msg},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.72,
                        "max_tokens": 420,
                    },
                    timeout=35.0,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    parsed = _extract_json_obj(content)
        except Exception:
            parsed = None

        if parsed and _clean_prompt_text(str(parsed.get("prompt") or "")):
            pos = _clean_prompt_text(str(parsed["prompt"]))
            neg = _clean_negative_text(str(parsed.get("negative_prompt") or "")) or _default_negative_for(
                mode, model_id, style_preset
            )
            top_txt = _clean_prompt_text(str(parsed.get("meme_top_text") or ""))[:72]
            sfx = _pick_sfx(str(parsed.get("recommended_sfx") or ""), clean_idea.lower())
            return {
                "source": f"local_llm:{use_model}",
                "endpoint": disc["endpoint"],
                "prompt": pos,
                "negative_prompt": neg,
                "meme_top_text": top_txt or f"POV: {clean_idea[:60]}",
                "recommended_sfx": sfx,
            }

    # Smart model-aware & style-aware deterministic fallback when no local LLM is reachable
    mid = (model_id or "").lower()
    is_stylized = (style_preset or "") in _STYLIZED_PRESETS
    if has_friend_photo and has_second_photo:
        subj = "the exact two people from reference image 1 and image 2 together"
    elif has_friend_photo:
        subj = "the exact person from the reference photo"
    else:
        subj = "the subject"

    if mid == "ltx23":
        expanded = (
            f"Continuous raw footage of {subj}, {clean_idea}, expressive natural facial reactions, "
            "realistic physical momentum and ambient lighting, accompanied by matching live microphone audio, "
            "natural voice acoustics, and crisp environmental sound effects"
        )
    elif mode == "video":
        expanded = (
            f"Dynamic continuous motion of {subj}, {clean_idea}, natural expressive facial reactions, "
            "realistic physics and fluid camera movement, authentic lighting"
        )
    elif mid in ("qwen_edit", "qwen_edit_2511") and has_friend_photo:
        expanded = (
            f"Keep the exact facial identity of {subj}, {clean_idea}, "
            "seamless natural scene lighting, realistic shadows, authentic candid framing"
        )
    elif is_stylized:
        expanded = f"Dynamic stylized scene featuring {subj}, {clean_idea}, bold dramatic composition and expressive timing"
    else:
        expanded = (
            f"Candid raw photograph of {subj}, {clean_idea}, "
            "natural unposed lighting, sharp realistic skin texture, authentic framing, zero AI gloss"
        )

    return {
        "source": "builtin_enhancer",
        "endpoint": disc["endpoint"],
        "prompt": expanded,
        "negative_prompt": _default_negative_for(mode, model_id, style_preset) or DEFAULT_NEGATIVE_PROMPT,
        "meme_top_text": f"POV: {clean_idea[:64]}",
        "recommended_sfx": _pick_sfx(None, clean_idea.lower()),
    }
