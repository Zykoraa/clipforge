"""Offline F5-TTS GPU Voice Cloning Worker (runs inside ComfyUI's venv with caches in ComfyUI dir)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref-audio", required=True)
    parser.add_argument("--ref-text", default="")
    parser.add_argument("--gen-text", required=True)
    parser.add_argument("--out-wav", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()

    from f5_tts.api import F5TTS

    tts = F5TTS(model="F5TTS_v1_Base")
    wav, sr, _spec = tts.infer(
        ref_file=args.ref_audio,
        ref_text=args.ref_text,
        gen_text=args.gen_text,
        file_wave=args.out_wav,
        speed=args.speed,
        remove_silence=True,
    )
    out_p = Path(args.out_wav)
    if not out_p.exists() or out_p.stat().st_size < 1024:
        import soundfile as sf

        sf.write(str(out_p), wav, sr)

    print(
        "RESULT_JSON:"
        + json.dumps({"out_wav": str(out_p), "sample_rate": int(sr), "ref_text": args.ref_text}),
        flush=True,
    )


if __name__ == "__main__":
    main()
