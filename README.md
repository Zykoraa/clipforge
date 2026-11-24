# ClipForge — AI-Controllable Video Editor, Offline Media Studio & MCP Server

ClipForge is a cross-platform (Windows & Linux) local-first Non-Linear Video Editor (NLE) with a live WebSocket-synced **MCP Server (43 tools)** and integrated **offline ComfyUI Image & Video Generation** (zero cloud filters, zero API fees).

---

## Core Capabilities

- **Live MCP + Visual NLE Sync (`clipforge/engine.py`, `clipforge/web_server.py`)**
  - Process-safe `FileLock` persistence (`workspace/project.json`) with cross-process 40-step Undo/Redo and monotonic versioning so AI agent edits stream instantaneously to the browser UI.
  - Hardened localhost server: per-process cryptographic session token (`X-ClipForge-Token`), strict loopback `Host`/`Origin` validation, strict CSP, and jailed upload/render paths.
- **Zero-Flash Dual-Video Canvas Compositor (`clipforge/static/app.js`)**
  - Hardware audio/video master-clock sync, idle-slot pre-warming for seamless cuts/crossfades, zero-black-flash frame holding, and native static meme image preview.
  - Multi-track timeline (`VIDEO / AUDIO`, `SUBTITLES`, `SFX / BGM`) with audio waveforms, drag-to-trim handles, drag-to-reorder, razor split (`S`), and `⏭ Continue Shot` final-frame extraction.
- **Offline AI Image & Video Studio (`clipforge/generator.py`, `clipforge/cast.py`, `clipforge/voice.py`)**
  - Direct local ComfyUI client with WebSocket live step progress, **mid-render latent previews + instant GPU Cancel/Interrupt**, automatic **VRAM headroom (`--reserve-vram`) & model-switch `/free` unload**, and built-in resumable HTTP `Range` Model Manager:
    - **Video**: `Wan 2.2 TI2V 5B`, `Wan 2.2 I2V 14B` (incl. `WanFirstLastFrameToVideo` Start→End morph), `Wan 2.2 T2V 14B` (4-step Lightx2v), `Wan 2.2 S2V 14B` (audio-driven lip-sync), `LTX-2.3 22B` (synchronized native audio/SFX).
    - **Image / Photo Editing**: `FLUX.2 [klein] 4B` & `9B` (4-step T2I + photo edit), `Z-Image-Turbo` (8-step candid realism + crisp meme text), `Qwen-Image-Edit 2509` & `2511` (4-step Lightning 1–3 photo compositor).
    - **Neural Utilities**: `4x-UltraSharp` GPU upscaler (2× / 4× HD) and `RIFE v4.26` GPU frame interpolation (`Smooth 32fps`), with automatic FFmpeg fallbacks.
  - **Zero-Refusal Studio & Iteration**:
    - **Refusal-Proof Local LLM Director** (`clipforge/director.py` — Ollama / LM Studio model picker with `🔓` uncensored flags, auto-retry on refusal, **Literal zero-sanitize toggle**, and 1-click Ollama uncensored model pull).
    - **Lightbox Follow-Up Edit & Canvas Mask-Brush Inpainting** (pixel-locked `DifferentialDiffusion` + `SetLatentNoiseMask` + `ImageCompositeMasked`, clickable version history chain, **A/B Split-Curtain Compare**, **Vary Slightly** denoise slider, and automatic **Face Detailer** via `clipforge/face_worker.py`).
    - **Copy Pose / Framing Reference Slot**, auto-discovered **LoRA Stacker** (up to 3 stacked `.safetensors` with strength sliders, persisted trigger words, and drag-and-drop upload), and searchable **Unified Media Vault** (images + hover-play videos + 1-click Remix).
    - **Multi-Angle Cast Book** (up to 4 photos per friend + voice clip + `@Name` auto-attach), **1-Click `🗣 Talk-Sync Video`** (`F5-TTS` voice clone → `Wan 2.2 S2V` / `I2V` + audio mux), and **Auto Multi-Beat Storyboard / Scene Chainer** (plans 2–4 beats and automatically chains final frames onto the timeline with captions + SFX).
  - **✨ Auto Best Model Router**, **Aspect-Ratio Photo Matching**, **4-Seed Contact Sheet** batching, **24 categorized AI style presets**, and **8 video camera motion presets**.
- **FFmpeg Filtergraph Compiler (`clipforge/renderer.py`, `clipforge/subtitles.py`, `clipforge/sfx.py`)**
  - `xfade` + `acrossfade` transitions, `apad`/`tpad` A/V sync lock, static image `-loop 1` support, NVIDIA NVENC (`h264_nvenc`) with `libx264` fallback.
  - `faster-whisper` word-level karaoke subtitles (**10 presets**: `hormozi`, `mrbeast`, `tiktok_clean`, `meme_impact`, `gaming_rgb`, `news_ticker`, `whisper_red`, `cinema`, `minimal`, `neon_box`).
  - **7 injection-safe native Meme Layout Templates** (`pov_top_bar`, `pov_dark_bar`, `impact_top_bottom`, `breaking_news`, `demotivational`, `bodycam_hud`).
  - **12 built-in synthesized Meme SFX** (`vine_boom`, `bass_drop`, `airhorn`, `record_scratch`, `dramatic_hit`, `alert_siren`, `whoosh`, `pop_click`, `fbi_knock`, `sad_trombone`, `censor_beep`, `glitch_zap`) with FFmpeg `sidechaincompress` auto-ducking.

---

## Quick Start

### Prerequisites
- Python 3.10+, [uv](https://docs.astral.sh/uv/) (recommended), and `ffmpeg` / `ffprobe` on `PATH`.
- On Linux: `fontconfig` and standard sans/mono fonts (e.g. Liberation / Noto / DejaVu).
- Optional: local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (`CLIPFORGE_COMFYUI_DIR`, `CLIPFORGE_COMFYUI_URL`, defaults to `http://127.0.0.1:8188`).
  - Auto-detected on Linux at `~/CreationTools/ComfyUI` or `~/ComfyUI`, and on Windows at `E:\ComfyUI` or `C:\ComfyUI`.
  - Automatically uses existing FP8/BF16 safetensors weights via native `UNETLoader` when present (`Wan 2.2 I2V 14B`, `Z-Image-Turbo`, shared `qwen_3_4b`), or GGUF weights via `ComfyUI-GGUF` (`UnetLoaderGGUF`).

### Install & Run (Linux / macOS)
```bash
uv sync
# Optional: enable CUDA 12 libraries for GPU-accelerated faster-whisper on NVIDIA GPUs
uv sync --extra cuda

./start_editor.sh
# Or directly:
uv run python main.py --port 8765
```

### Install & Run (Windows)
```powershell
uv sync
.\start_editor.bat
# Or directly:
uv run python main.py --port 8765
```

Open **http://127.0.0.1:8765**.

---

## Standalone Native Builds (Windows & Linux)

### 1. True Native Rust GPU Desktop App (`clipforge-native/`, zero web browser / zero WebView)
Built with **`eframe` / `egui` + `wgpu`** (DirectX 12 on Windows, Vulkan on Linux), native `rfd` OS file pickers & drag-and-drop, native FFmpeg + `rodio` video/audio playback, live `tungstenite` WebSocket MCP sync, and automatic headless backend management (Win32 Job Object `KILL_ON_JOB_CLOSE` / clean SIGTERM teardown):

```bash
cd clipforge-native
cargo build --release
# Windows output: target/release/ClipForgeNative.exe
# Linux output:   target/release/ClipForgeNative
```

### 2. Standalone Headless Backend / Web UI Executable (`build_exe.py`)
`build_exe.py` builds a native standalone bundle for whichever OS you run it on (PyInstaller compiles native executables per platform, and `.github/workflows/build-release.yml` builds both Windows and Linux release archives automatically on `v*` tags):

```bash
# Install PyInstaller extra and build native bundle (+ optional release archive)
uv sync --extra build
uv run python build_exe.py --archive

# Linux output:   dist/ClipForge/ClipForge      (+ dist/ClipForge-linux-x86_64.tar.gz)
# Windows output: dist/ClipForge/ClipForge.exe  (+ dist/ClipForge-windows-x86_64.zip)
```

Both binaries default to launching the Web UI and accept `--mcp` for stdio MCP mode.

---

## MCP Server Configuration

### Linux / macOS
```json
{
  "mcpServers": {
    "clipforge": {
      "command": "<path-to-clipforge>/.venv/bin/python",
      "args": ["-m", "clipforge.mcp_server"],
      "env": {
        "CLIPFORGE_WORKSPACE": "<path-to-clipforge>/workspace"
      }
    }
  }
}
```

### Windows
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

---

## Run Tests
```bash
uv run pytest -v tests/test_clipforge_e2e.py
```
