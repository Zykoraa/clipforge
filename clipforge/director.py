"""Offline Local LLM Meme Director (LM Studio / Ollama OpenAI-Compatible Client)."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

DEFAULT_DIRECTOR_ENDPOINTS = [
    os.environ.get("CLIPFORGE_LLM_URL", "").strip(),
    "http://127.0.0.1:1234/v1",  # LM Studio default
    "http://127.0.0.1:11434/v1",  # Ollama OpenAI-compatible default
]


def discover_local_llm(endpoint: str | None = None) -> dict[str, Any]:
    """Probe local OpenAI-compatible LLM endpoints (LM Studio / Ollama) on loopback."""
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
                models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
                return {"available": True, "endpoint": base, "models": models}
        except Exception:
            continue
    return {"available": False, "endpoint": candidates[0] if candidates else "http://127.0.0.1:1234/v1", "models": []}


def expand_meme_prompt_local(
    idea: str,
    mode: str = "image",
    has_friend_photo: bool = False,
    endpoint: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Use a local uncensored LLM (or smart deterministic template fallback) to craft punchy visual prompts."""
    clean_idea = (idea or "").strip()
    if not clean_idea:
        raise ValueError("Idea cannot be empty.")

    disc = discover_local_llm(endpoint=endpoint)
    if disc["available"] and disc["models"]:
        use_model = model_name if model_name and model_name in disc["models"] else disc["models"][0]
        target_desc = (
            "an offline photorealistic image / meme generator (FLUX.2 / Z-Image-Turbo)"
            if mode == "image"
            else "an offline image-to-video / text-to-video generator (Wan 2.2 / LTX-2.3)"
        )
        subj_note = (
            "A reference photo of the user's friend is attached — preserve their face/identity naturally as 'this person'."
            if has_friend_photo
            else "No reference photo is attached."
        )
        sys_msg = (
            f"You are an expert comedic visual director writing concise, ultra-vivid prompts for {target_desc}. "
            f"{subj_note} Return strict JSON with keys: "
            '`{"prompt": "...", "meme_top_text": "...", "recommended_sfx": "vine_boom|bass_drop|airhorn|record_scratch|dramatic_hit|alert_siren|whoosh|pop_click"}`. '
            "Keep `prompt` under 65 words, concrete lighting, camera movement/lens, authentic candid realism, zero buzzword fluff."
        )
        try:
            resp = httpx.post(
                f"{disc['endpoint']}/chat/completions",
                json={
                    "model": use_model,
                    "messages": [
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": f"Meme concept: {clean_idea}"},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 260,
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Extract JSON block if wrapped in markdown fences
                if "```" in content:
                    parts = content.split("```")
                    for p in parts:
                        p_s = p.strip()
                        if p_s.startswith("json"):
                            p_s = p_s[4:].strip()
                        if p_s.startswith("{"):
                            content = p_s
                            break
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("prompt"):
                    return {
                        "source": f"local_llm:{use_model}",
                        "endpoint": disc["endpoint"],
                        "prompt": str(parsed["prompt"]).strip(),
                        "meme_top_text": str(parsed.get("meme_top_text") or "").strip(),
                        "recommended_sfx": str(parsed.get("recommended_sfx") or "vine_boom").strip(),
                    }
        except Exception:
            pass

    # Deterministic cinematic prompt enhancer when no local LLM is running
    subj = "the exact person from the reference photo" if has_friend_photo else "a hilariously deadpan subject"
    if mode == "video":
        expanded = (
            f"Handheld raw smartphone footage of {subj}, {clean_idea}, "
            "natural candid ambient lighting, subtle camera shake, crisp facial expressions, "
            "realistic motion physics, authentic viral internet clip aesthetic"
        )
    else:
        expanded = (
            f"Candid raw iPhone photograph of {subj}, {clean_idea}, "
            "harsh natural flash lighting, authentic candid framing, sharp realistic skin texture, "
            "zero AI gloss, viral reaction meme timing"
        )
    return {
        "source": "builtin_enhancer",
        "endpoint": disc["endpoint"],
        "prompt": expanded,
        "meme_top_text": f"POV: {clean_idea[:64]}",
        "recommended_sfx": "vine_boom",
    }
