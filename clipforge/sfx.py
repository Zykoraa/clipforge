"""Built-in Offline Meme SFX Synthesizer (FFmpeg DSP) + Soundboard Catalog."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

BUILTIN_SFX: dict[str, dict[str, Any]] = {
    "vine_boom": {
        "id": "vine_boom",
        "label": "Vine Boom",
        "emoji": "💥",
        "duration_sec": 1.35,
        "description": "Heavy sub-bass impact thud for deadpan meme zooms.",
        "expr": (
            "0.95*tanh(2.4*("
            "sin(2*PI*(68*t - 18*t*t))*exp(-3.0*t) + "
            "0.55*sin(2*PI*36*t)*exp(-2.2*t) + "
            "0.25*sin(2*PI*145*t)*exp(-14*t)"
            "))*min(1,t/0.008)"
        ),
    },
    "bass_drop": {
        "id": "bass_drop",
        "label": "Bass Drop",
        "emoji": "🔊",
        "duration_sec": 1.8,
        "description": "Distorted sub-drop sweep for viral reveal transitions.",
        "expr": (
            "0.9*tanh(3.2*("
            "sin(2*PI*(95*t*exp(-0.9*t) + 28*t))*exp(-1.5*t) + "
            "0.35*sin(2*PI*56*t)*exp(-2.0*t)"
            "))*min(1,t/0.01)"
        ),
    },
    "airhorn": {
        "id": "airhorn",
        "label": "MLG Airhorn",
        "emoji": "📯",
        "duration_sec": 1.25,
        "description": "Classic triple-blast meme airhorn.",
        "expr": (
            "0.75*tanh(2.0*("
            "sin(2*PI*392*t)+0.7*sin(2*PI*494*t)+0.6*sin(2*PI*587*t)+0.5*sin(2*PI*784*t)+0.35*sin(2*PI*1175*t)"
            "))*("
            "between(t,0.0,0.14)*exp(-4*(t)) + "
            "between(t,0.19,0.33)*exp(-4*(t-0.19)) + "
            "between(t,0.38,1.22)*exp(-1.4*(t-0.38))"
            ")"
        ),
    },
    "record_scratch": {
        "id": "record_scratch",
        "label": "Record Scratch",
        "emoji": "💿",
        "duration_sec": 0.55,
        "description": "Freeze-frame vinyl rip for 'yep, that's me' moments.",
        "expr": (
            "0.85*("
            "sin(2*PI*(650*t + 220*sin(2*PI*11*t))*exp(-1.8*t)) * 0.65 + "
            "0.35*sin(2*PI*(1400*t - 900*t*t))*exp(-3.5*t)"
            ")*exp(-2.8*t)*min(1,t/0.006)"
        ),
    },
    "dramatic_hit": {
        "id": "dramatic_hit",
        "label": "Dramatic Braam",
        "emoji": "🎬",
        "duration_sec": 1.9,
        "description": "Cinema trailer brass/sub stinger.",
        "expr": (
            "0.85*tanh(2.5*("
            "sin(2*PI*55*t) + 0.7*sin(2*PI*82.4*t) + 0.5*sin(2*PI*110.8*t) + 0.35*sin(2*PI*165*t)"
            "))*exp(-1.45*t)*min(1,t/0.02)"
        ),
    },
    "alert_siren": {
        "id": "alert_siren",
        "label": "Breaking Alert",
        "emoji": "🚨",
        "duration_sec": 1.4,
        "description": "Urgent breaking-news broadcast alert chime.",
        "expr": (
            "0.72*("
            "between(mod(t,0.35),0,0.17)*sin(2*PI*880*t) + "
            "between(mod(t,0.35),0.17,0.34)*sin(2*PI*660*t)"
            ")*exp(-0.5*t)*min(1,t/0.005)"
        ),
    },
    "whoosh": {
        "id": "whoosh",
        "label": "Transition Whoosh",
        "emoji": "💨",
        "duration_sec": 0.45,
        "description": "Snappy cinematic swoosh for rapid cuts & zooms.",
        "expr": (
            "0.85*(random(0)*2-1)*sin(PI*t/0.45)*sin(PI*t/0.45)"
        ),
        "post_filter": "bandpass=f=680:w=900",
    },
    "pop_click": {
        "id": "pop_click",
        "label": "Caption Pop",
        "emoji": "💬",
        "duration_sec": 0.14,
        "description": "Crisp bubble pop for text/image punch-ins.",
        "expr": "0.85*sin(2*PI*(380*t + 2600*t*t))*exp(-28*t)*min(1,t/0.003)",
    },
    "fbi_knock": {
        "id": "fbi_knock",
        "label": "FBI Door Knock",
        "emoji": "🚪",
        "duration_sec": 1.15,
        "description": "Loud triple heavy wood door slam.",
        "expr": (
            "0.95*tanh(2.5*("
            "between(t,0.0,0.22)*(sin(2*PI*92*t)+0.5*(random(0)*2-1)*exp(-35*t))*exp(-14*t) + "
            "between(t,0.28,0.52)*(sin(2*PI*88*(t-0.28))+0.5*(random(0)*2-1)*exp(-35*(t-0.28)))*exp(-14*(t-0.28)) + "
            "between(t,0.56,1.10)*(sin(2*PI*82*(t-0.56))+0.5*(random(0)*2-1)*exp(-30*(t-0.56)))*exp(-10*(t-0.56))"
            "))"
        ),
    },
    "sad_trombone": {
        "id": "sad_trombone",
        "label": "Sad Trombone",
        "emoji": "🎺",
        "duration_sec": 1.85,
        "description": "Classic comedic fail wah-wah-waaaah.",
        "expr": (
            "0.75*tanh(1.8*("
            "between(t,0.0,0.34)*(sin(2*PI*311*t)+0.5*sin(2*PI*622*t)+0.25*sin(2*PI*933*t))*exp(-2.0*t) + "
            "between(t,0.38,0.72)*(sin(2*PI*293.6*t)+0.5*sin(2*PI*587.2*t)+0.25*sin(2*PI*880.8*t))*exp(-2.0*(t-0.38)) + "
            "between(t,0.76,1.10)*(sin(2*PI*277.2*t)+0.5*sin(2*PI*554.4*t)+0.25*sin(2*PI*831.6*t))*exp(-2.0*(t-0.76)) + "
            "between(t,1.14,1.82)*(sin(2*PI*(261.6-24*(t-1.14)+4*sin(2*PI*6*t))*t)+0.5*sin(2*PI*(523.2-48*(t-1.14))*t))*exp(-1.5*(t-1.14))"
            "))"
        ),
    },
    "censor_beep": {
        "id": "censor_beep",
        "label": "TV Bleep",
        "emoji": "🤬",
        "duration_sec": 0.45,
        "description": "Sharp 1000 Hz broadcast censor bleep.",
        "expr": "0.65*sin(2*PI*1000*t)*min(1,t/0.005)*min(1,(0.45-t)/0.008)",
    },
    "glitch_zap": {
        "id": "glitch_zap",
        "label": "Glitch Stutter",
        "emoji": "⚡",
        "duration_sec": 0.50,
        "description": "Digital corruption zap for cursed edits.",
        "expr": (
            "0.82*tanh(3.0*("
            "sin(2*PI*(220 + 880*floor(mod(t*18,4)))*t)*between(mod(t*24,1),0,0.65) + "
            "0.35*(random(0)*2-1)*between(mod(t*14,1),0.4,0.8)"
            "))*exp(-2.2*t)"
        ),
    },
}


def list_builtin_sfx() -> list[dict[str, Any]]:
    return [
        {
            "id": s["id"],
            "label": s["label"],
            "emoji": s["emoji"],
            "duration_sec": s["duration_sec"],
            "description": s["description"],
        }
        for s in BUILTIN_SFX.values()
    ]


def ensure_builtin_sfx_file(sfx_id: str, sfx_dir: Path) -> tuple[Path, dict[str, Any]]:
    if sfx_id not in BUILTIN_SFX:
        raise ValueError(f"Unknown built-in SFX '{sfx_id}'. Valid: {sorted(BUILTIN_SFX.keys())}")
    spec = BUILTIN_SFX[sfx_id]
    sfx_dir.mkdir(parents=True, exist_ok=True)
    out_wav = (sfx_dir / f"{sfx_id}.wav").resolve()
    if out_wav.exists() and out_wav.stat().st_size > 1024:
        return out_wav, spec

    dur = float(spec["duration_sec"])
    af_chain = [f"aevalsrc='{spec['expr']}':s=44100:c=stereo:d={dur:.3f}"]
    if spec.get("post_filter"):
        af_chain.append(str(spec["post_filter"]))
    af_chain.append("alimiter=limit=0.95")

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        af_chain[0],
    ]
    if len(af_chain) > 1:
        cmd.extend(["-af", ",".join(af_chain[1:])])
    cmd.extend(["-ar", "44100", "-ac", "2", str(out_wav)])

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 or not out_wav.exists():
        raise RuntimeError(f"Failed to synthesize SFX '{sfx_id}': {(res.stderr or '')[-400:]}")
    return out_wav, spec
