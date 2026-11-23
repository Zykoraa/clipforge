# ClipForge — AI-Controllable Video Editor, Offline Media Studio & MCP Server

ClipForge is a local-first Non-Linear Video Editor (NLE) with a live WebSocket-synced **MCP Server (32 tools)** and integrated **offline ComfyUI Image & Video Generation** (zero cloud filters, zero API fees).

---

## Core Capabilities

- **Live MCP + Visual NLE Sync (`clipforge/engine.py`, `clipforge/web_server.py`)**
  - Process-safe `FileLock` persistence (`workspace/project.json`) with cross-process 40-step Undo/Redo and monotonic versioning so AI agent edits stream instantaneously to the browser UI.
  - Hardened localhost server: per-process cryptographic session token (`X-ClipForge-Token`), strict loopback `Host`/`Origin` validation, strict CSP, and jailed upload/render paths.
- **Zero-Flash Dual-Video Canvas Compositor (`clipforge/static/app.js`)**
  - Hardware audio/video master-clock sync, idle-slot pre-warming for seamless cuts/crossfades, zero-black-flash frame holding, and native static meme image preview.
  - Multi-track timeline (`VIDEO / AUDIO`, `SUBTITLES`, `SFX / BGM`) with audio waveforms, drag-to-trim handles, drag-to-reorder, razor split (`S`), and `⏭ Continue Shot` final-frame extraction.
- **Offline AI Image & Video Studio (`clipforge/generator.py`)**
  - Direct local ComfyUI client with WebSocket live step progress and built-in resumable HTTP `Range` Model Manager:
    - **Video**: `Wan 2.2 TI2V 5B`, `Wan 2.2 I2V 14B` (incl. `WanFirstLastFrameToVideo` Start→End morph), `LTX-2.3 22B` (synchronized native audio/SFX).
    - **Image / Photo Editing**: `FLUX.2 [klein] 4B` (4-step T2I + photo edit), `Z-Image-Turbo` (8-step candid realism + crisp meme text), `Qwen-Image-Edit 2509` (1–2 photo compositor).
  - **4-Seed Contact Sheet** batching, **24 categorized AI style presets**, **8 video camera motion presets**, and a local LLM prompt enhancer (`clipforge/director.py` — LM Studio / Ollama OpenAI-compatible).
- **FFmpeg Filtergraph Compiler (`clipforge/renderer.py`, `clipforge/subtitles.py`, `clipforge/sfx.py`)**
  - `xfade` + `acrossfade` transitions, `apad`/`tpad` A/V sync lock, static image `-loop 1` support, NVIDIA NVENC (`h264_nvenc`) with `libx264` fallback.
  - `faster-whisper` word-level karaoke subtitles (**10 presets**: `hormozi`, `mrbeast`, `tiktok_clean`, `meme_impact`, `gaming_rgb`, `news_ticker`, `whisper_red`, `cinema`, `minimal`, `neon_box`).
  - **7 injection-safe native Meme Layout Templates** (`pov_top_bar`, `pov_dark_bar`, `impact_top_bottom`, `breaking_news`, `demotivational`, `bodycam_hud`).
  - **12 built-in synthesized Meme SFX** (`vine_boom`, `bass_drop`, `airhorn`, `record_scratch`, `dramatic_hit`, `alert_siren`, `whoosh`, `pop_click`, `fbi_knock`, `sad_trombone`, `censor_beep`, `glitch_zap`) with FFmpeg `sidechaincompress` auto-ducking.

---

## Quick Start

### Prerequisites
- Python 3.10+, [uv](https://docs.astral.sh/uv/) (recommended), and `ffmpeg` / `ffprobe` on `PATH`.
- Optional: local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (`CLIPFORGE_COMFYUI_DIR`, `CLIPFORGE_COMFYUI_URL`, defaults to `http://127.0.0.1:8188`).

### Install & Run
```powershell
uv sync
uv run python main.py --port 8765
```
Open **http://127.0.0.1:8765**.

### Build Standalone Windows Executable
```powershell
uv pip install pyinstaller
uv run python build_exe.py
# Output: dist/ClipForge/ClipForge.exe (supports Web UI default & `--mcp` stdio mode)
```

### MCP Server Configuration
```json
{
  "mcpServers": {
    "clipforge": {
      "command": "<path-to-clipforge>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "clipforge.mcp_server"],
      "env": {
        "CLIPFORGE_WORKSPACE": "<path-to-clipforge>\\workspace"
      }
    }
  }
}
```

### Run Tests
```powershell
uv run pytest -v tests/test_clipforge_e2e.py
```
