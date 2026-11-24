"""Comprehensive E2E & Security Regression Tests for ClipForge."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipforge import mcp_server, web_server
from clipforge.engine import ProjectEngine
from clipforge.media import probe_media_file
from clipforge.models import SubtitleEntry, TranscriptSegment, WordToken
from clipforge.subtitles import generate_ass


def _generate_synthetic_clip(
    out_path: Path,
    color: str,
    total_dur: float = 3.0,
    lead_silence: float = 0.6,
    trail_silence: float = 0.6,
    freq: int = 440,
) -> Path:
    tone_start = lead_silence
    tone_end = total_dur - trail_silence
    expr = f"if(between(t,{tone_start},{tone_end}),0.4*sin(2*PI*{freq}*t),0)"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=640x360:r=30:d={total_dur}",
        "-f",
        "lavfi",
        "-i",
        f"aevalsrc='{expr}':s=44100:c=stereo:d={total_dur}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


def _probe_stream_durations(video_path: Path) -> dict[str, float]:
    res = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    out: dict[str, float] = {}
    for s in json.loads(res.stdout).get("streams", []):
        if "duration" in s and s.get("codec_type") in ("video", "audio"):
            out[s["codec_type"]] = float(s["duration"])
    return out


def test_full_smart_stitch_subtitle_and_render(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    eng = ProjectEngine(workspace_dir=workspace)
    monkeypatch.setattr(mcp_server, "_engine", eng)

    c1 = _generate_synthetic_clip(tmp_path / "clip1_intro.mp4", "navy", total_dur=3.0, lead_silence=0.6, trail_silence=0.6, freq=440)
    c2 = _generate_synthetic_clip(tmp_path / "clip2_middle.mp4", "darkgreen", total_dur=3.2, lead_silence=0.5, trail_silence=0.7, freq=554)
    c3 = _generate_synthetic_clip(tmp_path / "clip3_outro.mp4", "maroon", total_dur=2.8, lead_silence=0.5, trail_silence=0.5, freq=659)

    imp_res = mcp_server.import_media([str(c1), str(c2), str(c3)])
    assert imp_res["imported_count"] == 3

    # MED-05: odd dimensions auto-snapped to even
    cfg = mcp_server.configure_project(name="E2E Stitched Video", width=641, height=361, fps=30.0)
    assert cfg["project"]["width"] == 640
    assert cfg["project"]["height"] == 360

    stitch_res = mcp_server.smart_stitch(
        trim_silence=True,
        split_long_silences=False,
        min_silence_sec=0.35,
        noise_db=-35.0,
        padding_sec=0.05,
        transition="crossfade",
        transition_duration=0.3,
        auto_subtitle=False,
    )
    assert stitch_res["clips_count"] == 3
    assert stitch_res["saved_dead_air_sec"] > 2.0
    assert 3.5 < stitch_res["stitched_duration_sec"] < 6.8

    mcp_server.set_subtitle_style(
        preset="hormozi",
        primary_color="#FFFFFF",
        highlight_color="#00FF66",
        word_highlight=True,
    )
    mcp_server.upsert_subtitle(start_sec=0.1, end_sec=1.8, text="AI smart stitched clip one")
    mcp_server.upsert_subtitle(start_sec=1.9, end_sec=3.8, text="BOOM!")  # SUB-01 single-word pop

    ass_res = mcp_server.export_subtitles(fmt="ass")
    ass_text = Path(ass_res["subtitle_file"]).read_text(encoding="utf-8")
    assert r"\fscx108\fscy108}BOOM!" in ass_text

    # SEC-03: apostrophe + filtergraph metacharacters in output filename must not crash or inject
    tricky_out = tmp_path / "user's_cut_[1];render.mp4"
    render_res = mcp_server.render_video(
        output_path=str(tricky_out),
        burn_subtitles=True,
        quality="draft",
        normalize_audio=True,
        use_hw_accel=True,
    )
    assert tricky_out.exists()
    assert render_res["subtitles_burned"] is True

    probed = probe_media_file(tricky_out)
    assert probed.width == 640
    assert probed.height == 360
    assert probed.has_audio is True
    assert abs(probed.duration_sec - stitch_res["stitched_duration_sec"]) < 0.25


def test_av_sync_mismatched_streams_and_audio_only_clip(tmp_path: Path) -> None:
    """MED-01 + MED-02: Verify zero A/V desync on short-audio clips, speed changes, and audio-only files."""
    eng = ProjectEngine(workspace_dir=tmp_path / "ws_sync")
    eng.configure_project(width=320, height=240, fps=30.0)

    # Clip 1: 2.0s video, 1.5s audio (500ms audio shortfall)
    c1 = tmp_path / "short_audio.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=2.0",
            "-f", "lavfi", "-i", "aevalsrc=0.3*sin(440*2*PI*t):s=44100:c=stereo:d=1.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(c1),
        ],
        capture_output=True,
        check=True,
    )

    # Clip 2: Audio-only WAV file (MED-02)
    a_only = tmp_path / "narration.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "lavfi", "-i", "aevalsrc=0.3*sin(660*2*PI*t):s=44100:c=stereo:d=1.6",
            str(a_only),
        ],
        capture_output=True,
        check=True,
    )

    items = eng.import_media([str(c1), str(a_only)])
    assert items[0].has_video is True
    assert items[1].has_video is False
    assert items[1].has_audio is True

    eng.add_timeline_clip(items[0].id, speed=1.25, transition="cut")
    eng.add_timeline_clip(items[1].id, transition="crossfade", transition_duration=0.4)

    out_mp4 = tmp_path / "synced_audio_only.mp4"
    res = eng.render_video(output_path=str(out_mp4), burn_subtitles=False, quality="draft", use_hw_accel=False)
    durs = _probe_stream_durations(out_mp4)
    assert "video" in durs and "audio" in durs
    # Previously drifted by 500ms; now locked within 80ms
    assert abs(durs["video"] - durs["audio"]) < 0.08
    assert abs(durs["video"] - res["duration_sec"]) < 0.12


def test_subtitle_ass_hardening_and_portrait_scaling(tmp_path: Path) -> None:
    """SEC-05 + SUB-01 + SUB-02 + SUB-03 + SUB-04."""
    eng = ProjectEngine(workspace_dir=tmp_path / "ws_sub")
    eng.configure_project(name="Line1\n[Events]\nInjected", width=1080, height=1920, fps=30.0)
    eng.set_subtitle_style(preset="hormozi", font_name="Arial,999\nFakeStyle")

    st = eng.get_state()
    assert "\n" not in st.name
    assert "," not in st.subtitle_style.font_name and "\n" not in st.subtitle_style.font_name

    # Ultra-fast words 10ms apart must produce non-overlapping ASS centisecond slices
    st.subtitles = [
        SubtitleEntry(
            start_sec=0.0,
            end_sec=1.0,
            text=r"fast\Nwords {test}",
            words=[
                WordToken(word=r"fast\N", start_sec=0.0, end_sec=0.01),
                WordToken(word="words", start_sec=0.01, end_sec=0.02),
                WordToken(word="{test}", start_sec=0.5, end_sec=1.0),
            ],
        )
    ]
    ass = generate_ass(st)
    # Portrait 1080x1920 short-edge scale = 1080/1080 = 1.0 -> font size 64 (NOT 114!)
    assert ",64," in ass
    # No raw double-backslash escape and no unescaped control '\N' from user text
    assert r"\\N" not in ass
    assert "\\\u200bN" in ass

    # Verify all Dialogue lines have strictly non-overlapping timestamps
    dialogue_times: list[tuple[str, str]] = re.findall(r"Dialogue: 0,([^,]+),([^,]+),", ass)
    assert len(dialogue_times) >= 2
    for i in range(len(dialogue_times) - 1):
        assert dialogue_times[i][1] <= dialogue_times[i + 1][0]

    # Empty subtitle rejected
    with pytest.raises(ValueError):
        eng.upsert_subtitle(start_sec=0.0, end_sec=1.0, text="   ")


def test_cross_process_undo_redo_and_monotonic_version(tmp_path: Path) -> None:
    """ARCH-01: Undo across separate ProjectEngine instances restores state AND strictly bumps version."""
    ws = tmp_path / "ws_undo"
    c1 = _generate_synthetic_clip(tmp_path / "u.mp4", "teal", total_dur=2.0, lead_silence=0.1, trail_silence=0.1)

    mcp_eng = ProjectEngine(workspace_dir=ws)
    web_eng = ProjectEngine(workspace_dir=ws)

    items = mcp_eng.import_media([str(c1)])
    mcp_eng.add_timeline_clip(items[0].id)
    v_after_add = web_eng.get_state().version
    assert len(web_eng.get_state().timeline) == 1

    # Undo from the SECOND process (Web UI) undoes MCP's edit and strictly increments version
    restored = web_eng.undo()
    assert len(restored.timeline) == 0
    assert restored.version > v_after_add

    # Redo from MCP restores clip and strictly increments version again
    redone = mcp_eng.redo()
    assert len(redone.timeline) == 1
    assert redone.version > restored.version


def test_web_security_hardening_and_api(tmp_path: Path, monkeypatch) -> None:
    """SEC-01 + SEC-02: Verify token auth, Origin/Host checks, upload traversal block, and render path jail."""
    ws = tmp_path / "ws_sec"
    eng = ProjectEngine(workspace_dir=ws)
    monkeypatch.setattr(web_server, "engine", eng)
    monkeypatch.setattr(mcp_server, "_engine", eng)

    client = TestClient(web_server.app)

    # 1. Missing token rejected on /api/state (401)
    assert client.get("/api/state").status_code == 401

    # 2. Health endpoint remains accessible
    assert client.get("/api/health").json() == {"service": "clipforge", "status": "ok"}

    # 3. Extract legitimate token from same-origin index HTML
    idx_resp = client.get("/")
    assert idx_resp.status_code == 200
    m = re.search(r'<meta name="clipforge-token" content="([^"]+)"', idx_resp.text)
    assert m is not None
    token = m.group(1)
    auth_hdrs = {"X-ClipForge-Token": token}

    # 4. Cross-origin request blocked even WITH token (403)
    r_cors = client.get("/api/state", headers={**auth_hdrs, "Origin": "https://evil.attacker"})
    assert r_cors.status_code == 403
    assert "access-control-allow-origin" not in {k.lower() for k in r_cors.headers}

    # 5. DNS rebinding Host header blocked (403)
    r_host = client.get("/api/state", headers={**auth_hdrs, "Host": "rebind.evil.com:8765"})
    assert r_host.status_code == 403

    # 6. Upload path traversal & non-media file blocked (SEC-01)
    pwn_target = tmp_path / "pwn.bat"
    r_trav = client.post(
        "/api/media/upload",
        headers=auth_hdrs,
        files={"files": (str(pwn_target), b"@echo pwned", "application/octet-stream")},
    )
    assert r_trav.status_code == 400
    assert not pwn_target.exists()

    # Fake .mp4 with non-media bytes rejected and cleaned up from uploads dir
    r_fake = client.post(
        "/api/media/upload",
        headers=auth_hdrs,
        files={"files": ("../../fake.mp4", b"not a real video", "video/mp4")},
    )
    assert r_fake.status_code == 400
    uploads_dir = ws / "uploads"
    assert not list(uploads_dir.glob("*.mp4"))

    # 7. Valid media upload & Web API EDL/split/undo workflow succeeds
    c1 = _generate_synthetic_clip(tmp_path / "good.mp4", "purple", total_dur=2.5, lead_silence=0.2, trail_silence=0.2)
    r_up = client.post(
        "/api/media/upload",
        headers=auth_hdrs,
        files={"files": ("good.mp4", c1.read_bytes(), "video/mp4")},
    )
    assert r_up.status_code == 200
    media_id = r_up.json()["project"]["media_bin"][0]["id"]

    # 8. HTTP render path jail blocks escaping workspace/renders (SEC-02)
    client.post("/api/timeline/clip", headers=auth_hdrs, json={"media_id": media_id})
    escape_path = tmp_path / "escaped.mp4"
    r_esc = client.post("/api/render", headers=auth_hdrs, json={"output_path": str(escape_path)})
    assert r_esc.status_code == 400
    assert not escape_path.exists()

    # 9. WebSocket rejects missing/bad token and cross-origin CSWSH, accepts valid token
    with pytest.raises(Exception):
        with client.websocket_connect("/ws"):
            pass
    with client.websocket_connect(f"/ws?token={token}") as ws_conn:
        msg = ws_conn.receive_json()
        assert msg["type"] == "state_updated"


def test_static_image_timeline_render(tmp_path: Path) -> None:
    """Verify static meme PNGs import cleanly (is_image=True, 3.0s) and crossfade-render with video & captions."""
    eng = ProjectEngine(workspace_dir=tmp_path / "ws_img")
    eng.configure_project(width=640, height=360, fps=30.0)

    meme_png = tmp_path / "meme_still.png"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "lavfi", "-i", "color=c=orange:s=512x512:d=1",
            "-frames:v", "1", str(meme_png),
        ],
        capture_output=True,
        check=True,
    )
    vid = _generate_synthetic_clip(tmp_path / "clip.mp4", "navy", total_dur=2.2, lead_silence=0.1, trail_silence=0.1)

    items = eng.import_media([str(meme_png), str(vid)])
    assert items[0].is_image is True
    assert items[0].has_video is True
    assert items[0].has_audio is False
    assert items[0].duration_sec == 3.0

    eng.add_timeline_clip(items[0].id, in_sec=0.0, out_sec=2.0, transition="cut")
    eng.add_timeline_clip(items[1].id, transition="crossfade", transition_duration=0.4)
    eng.upsert_subtitle(start_sec=0.2, end_sec=1.8, text="STATIC MEME INTRO")

    out_mp4 = tmp_path / "meme_stitched.mp4"
    res = eng.render_video(output_path=str(out_mp4), burn_subtitles=True, quality="draft", use_hw_accel=False)
    assert out_mp4.exists()
    durs = _probe_stream_durations(out_mp4)
    assert "video" in durs and "audio" in durs
    assert abs(durs["video"] - durs["audio"]) < 0.12
    assert abs(durs["video"] - res["duration_sec"]) < 0.15


def test_offline_generator_workflows_and_ref_upload_security(tmp_path: Path, monkeypatch) -> None:
    """Verify all 6 ComfyUI workflows (Video + Image), Model Manager endpoints, and ref/gallery path jails."""
    from clipforge.generator import (
        apply_prompt_preset,
        build_flux2_klein_workflow,
        build_ltx23_workflow,
        build_qwen_edit_workflow,
        build_wan22_5b_workflow,
        build_wan22_i2v_workflow,
        build_z_image_turbo_workflow,
    )

    assert "CCTV" in apply_prompt_preset("my friend", "cctv")

    wf_i2v = build_wan22_i2v_workflow("funny meme", image_filename="friend.jpg", width=480, height=832, num_frames=81)
    assert wf_i2v["1"]["class_type"] == "UnetLoaderGGUF"
    assert wf_i2v["12"]["class_type"] == "WanImageToVideo"
    assert wf_i2v["17"]["class_type"] == "SaveVideo"

    wf_5b = build_wan22_5b_workflow("funny meme", width=480, height=608, num_frames=73)
    assert wf_5b["8"]["class_type"] == "Wan22ImageToVideoLatent"
    assert "start_image" not in wf_5b["8"]["inputs"]

    wf_ltx = build_ltx23_workflow("funny meme with loud bass drop", image_filename="friend.jpg", width=480, height=832, num_frames=97)
    assert wf_ltx["2"]["class_type"] == "DualCLIPLoader"
    assert wf_ltx["12"]["class_type"] == "LTXVConcatAVLatent"
    assert wf_ltx["20"]["class_type"] == "LTXVAudioVAEDecode"
    assert wf_ltx["21"]["inputs"]["audio"] == ["20", 0]

    # Image workflows
    wf_fk_t2i = build_flux2_klein_workflow("candid meme photo")
    assert wf_fk_t2i["6"]["class_type"] == "EmptyFlux2LatentImage"
    assert "9" not in wf_fk_t2i

    wf_fk_edit = build_flux2_klein_workflow("put this guy on mars", image_filename="friend.png")
    assert wf_fk_edit["9"]["class_type"] == "ReferenceLatent"
    assert wf_fk_edit["10"]["inputs"]["positive"] == ["9", 0]

    wf_zit = build_z_image_turbo_workflow("viral meme text")
    assert wf_zit["3"]["inputs"]["type"] == "lumina2"
    assert wf_zit["2"]["class_type"] == "ModelSamplingAuraFlow"

    wf_qw = build_qwen_edit_workflow("both friends at a diner", image_filename="f1.png", image_filename_2="f2.png")
    assert wf_qw["6"]["class_type"] == "TextEncodeQwenImageEditPlus"
    assert wf_qw["6"]["inputs"]["image2"] == ["5b", 0]

    # Verify ref-image upload, preview serving, gallery traversal blocks, and model endpoints
    ws = tmp_path / "ws_gen"
    eng = ProjectEngine(workspace_dir=ws)
    monkeypatch.setattr(web_server, "engine", eng)
    client = TestClient(web_server.app)
    token = re.search(r'<meta name="clipforge-token" content="([^"]+)"', client.get("/").text).group(1)
    hdrs = {"X-ClipForge-Token": token}

    r_bad = client.post(
        "/api/generate/upload-ref",
        headers=hdrs,
        files={"file": ("../../evil.bat", b"@echo pwn", "application/octet-stream")},
    )
    assert r_bad.status_code == 400

    # Valid PNG ref upload returns preview_url and serves safely
    r_ok = client.post(
        "/api/generate/upload-ref",
        headers=hdrs,
        files={"file": ("friend.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
    )
    assert r_ok.status_code == 200
    preview_url = r_ok.json()["preview_url"]
    assert client.get(preview_url, headers=hdrs).status_code == 200

    # Path traversal against image/ref read endpoints rejected
    assert client.get("/api/generate/image/..%5Cproject.json", headers=hdrs).status_code in (400, 404)
    assert client.get("/api/generate/ref/..%5Cproject.json", headers=hdrs).status_code in (400, 404)
    assert client.post("/api/generate/models/not_a_real_model/download", headers=hdrs).status_code == 404

    r_status = client.get("/api/generate/status", headers=hdrs)
    assert r_status.status_code == 200
    status_json = r_status.json()
    assert set(status_json["models"].keys()) == {
        "wan22_i2v",
        "wan22_t2v",
        "wan22_s2v",
        "wan22_5b",
        "ltx23",
        "flux2_klein",
        "flux2_klein_9b",
        "z_image_turbo",
        "krea2_turbo",
        "chroma_hd",
        "illustrious_xl",
        "qwen_edit",
        "qwen_edit_2511",
        "upscale_ultrasharp",
        "rife_vfi",
    }
    assert "raw_iphone" in status_json["presets"]
    assert len(status_json["presets"]) >= 20
    assert "crash_zoom" in status_json["camera_presets"]
    assert len(status_json["ref_images"]) == 1

    # Verify WanFirstLastFrameToVideo morph graph when end_image_filename is supplied
    wf_morph = build_wan22_i2v_workflow("morph meme", image_filename="f1.png", end_image_filename="f2.png")
    assert wf_morph["12"]["class_type"] == "WanFirstLastFrameToVideo"
    assert wf_morph["12"]["inputs"]["end_image"] == ["11b", 0]


def test_sfx_auto_duck_meme_layout_continue_shot_and_director(tmp_path: Path, monkeypatch) -> None:
    """Verify SFX synthesis + sidechain auto-ducking + POV/Breaking News meme layouts + Continue Shot + Director."""
    eng = ProjectEngine(workspace_dir=tmp_path / "ws_pro")
    monkeypatch.setattr(web_server, "engine", eng)
    eng.configure_project(width=640, height=360, fps=30.0)

    vid = _generate_synthetic_clip(tmp_path / "base.mp4", "darkblue", total_dur=2.6, lead_silence=0.1, trail_silence=0.1)
    items = eng.import_media([str(vid)])
    clip = eng.add_timeline_clip(items[0].id)

    # 1. Continue Shot extracts final frame cleanly into workspace/ref_images
    end_frame = eng.extract_clip_end_frame(clip.id)
    assert Path(end_frame["image_path"]).exists()
    assert end_frame["preview_url"].startswith("/api/generate/ref/")

    # 2. Built-in SFX synthesis + auto-ducking audio overlay
    ov = eng.add_audio_overlay(sfx_id="vine_boom", start_sec=0.5, volume=1.2, duck_main_audio=True)
    assert Path(ov.path).exists()

    # 3. Native Meme Layout templates (injection-safe textfile= with quotes/colons/semicolons)
    eng.set_meme_layout(
        template="pov_top_bar",
        top_text="POV: he said 'trust me: bro; it works'",
    )
    out_pov = tmp_path / "pov_ducked.mp4"
    res = eng.render_video(output_path=str(out_pov), burn_subtitles=False, quality="draft", use_hw_accel=False)
    assert out_pov.exists() and res["file_size_bytes"] > 10000

    eng.set_meme_layout(
        template="breaking_news",
        banner_label="LIVE ALERT",
        top_text="LOCAL MAN REFUSES TO DEBUG",
        bottom_text="Sources confirm he just rebooted it",
    )
    out_bn = tmp_path / "breaking_news.mp4"
    res_bn = eng.render_video(output_path=str(out_bn), burn_subtitles=False, quality="draft", use_hw_accel=False)
    assert out_bn.exists() and res_bn["file_size_bytes"] > 10000

    eng.set_meme_layout(
        template="bodycam_hud",
        banner_label="AXON BODY 4 REC",
        top_text="2026-11-23 02:14:09",
        bottom_text="UNIT 406",
    )
    out_bc = tmp_path / "bodycam.mp4"
    res_bc = eng.render_video(output_path=str(out_bc), burn_subtitles=False, quality="draft", use_hw_accel=False)
    assert out_bc.exists() and res_bc["file_size_bytes"] > 10000

    # 4. Web API routes for SFX catalog, meme layout, continue shot, and director prompt expander
    client = TestClient(web_server.app)
    token = re.search(r'<meta name="clipforge-token" content="([^"]+)"', client.get("/").text).group(1)
    hdrs = {"X-ClipForge-Token": token}

    r_cat = client.get("/api/sfx/catalog", headers=hdrs)
    assert r_cat.status_code == 200 and len(r_cat.json()["sfx"]) >= 12

    r_dir = client.post(
        "/api/director/expand",
        headers=hdrs,
        json={
            "idea": "arguing with a raccoon at 2am",
            "mode": "video",
            "model_id": "ltx23",
            "style_preset": "ring_doorbell",
            "has_friend_photo": True,
        },
    )
    assert r_dir.status_code == 200
    dir_data = r_dir.json()
    assert dir_data.get("prompt") and len(dir_data["prompt"]) > 20
    assert dir_data.get("negative_prompt") and len(dir_data["negative_prompt"]) > 10
    assert dir_data.get("recommended_sfx") in {s["id"] for s in r_cat.json()["sfx"]}


def test_cross_platform_helpers_fonts_and_env(tmp_path: Path, monkeypatch) -> None:
    """Verify cross-platform ComfyUI discovery, PyInstaller env cleanup, font resolution, and status metadata."""
    import os
    import sys

    from clipforge.platform_utils import (
        clean_pyinstaller_env,
        detached_popen_kwargs,
        resolve_ass_font_name,
        resolve_comfyui_python,
        resolve_default_comfyui_dir,
        resolve_ffmpeg_fontfile,
    )

    # 1. Detached subprocess kwargs are OS-valid
    dk = detached_popen_kwargs()
    if sys.platform == "win32":
        assert "creationflags" in dk
    else:
        assert dk.get("start_new_session") is True

    # 2. PyInstaller _MEIPASS cleanup strips bundled dirs from PATH and restores LD_LIBRARY_PATH
    fake_mp = str((tmp_path / "meipass").resolve())
    monkeypatch.setattr(sys, "_MEIPASS", fake_mp, raising=False)
    cleaned = clean_pyinstaller_env(
        {
            "PATH": f"{fake_mp}{os.pathsep}/usr/bin",
            "LD_LIBRARY_PATH": f"{fake_mp}:/opt/cuda/lib64",
            "LD_LIBRARY_PATH_ORIG": "/opt/cuda/lib64",
            "_MEIPASS2": fake_mp,
        }
    )
    assert "_MEIPASS2" not in cleaned
    assert fake_mp not in cleaned.get("PATH", "")
    assert cleaned.get("LD_LIBRARY_PATH") == "/opt/cuda/lib64"
    assert "LD_LIBRARY_PATH_ORIG" not in cleaned

    # 3. ComfyUI dir honors CLIPFORGE_COMFYUI_DIR and locates OS-native venv python
    fake_comfy = tmp_path / "ComfyUI"
    py_rel = Path(".venv/Scripts/python.exe") if sys.platform == "win32" else Path(".venv/bin/python")
    py_path = fake_comfy / py_rel
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLIPFORGE_COMFYUI_DIR", str(fake_comfy))
    assert resolve_default_comfyui_dir() == fake_comfy
    assert resolve_comfyui_python(fake_comfy) == py_path

    # 4. FFmpeg drawtext font resolution returns an existing font file on Linux/Windows
    ff_bold = resolve_ffmpeg_fontfile("arialbd.ttf")
    assert ff_bold != ""
    ff_mono = resolve_ffmpeg_fontfile("consolab.ttf")
    assert ff_mono != ""

    # 5. libass font resolution never resolves Impact to an icon font (e.g. FontAwesome)
    impact_fam, _force_bold = resolve_ass_font_name("Impact")
    assert "fontawesome" not in impact_fam.lower()
    assert "emoji" not in impact_fam.lower()

    # 6. Safetensors / FP8 / BF16 auto-detection satisfies model availability & switches to UNETLoader
    from clipforge.generator import (
        build_flux2_klein_workflow,
        build_qwen_edit_workflow,
        build_wan22_i2v_workflow,
        build_wan22_t2v_workflow,
        build_z_image_turbo_workflow,
        get_model_availability,
    )

    st_comfy = tmp_path / "comfy_st"
    for rel in (
        "models/diffusion_models/z_image_turbo_bf16.safetensors",
        "models/text_encoders/qwen_3_4b.safetensors",
        "models/vae/ae.safetensors",
        "models/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "models/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "models/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        "models/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
        "models/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
        "models/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
        "models/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
        "models/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
        "models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "models/vae/wan_2.1_vae.safetensors",
    ):
        fp = st_comfy / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(b"\x00" * (1024 * 1024 + 16))

    avail_st = get_model_availability(st_comfy)
    assert avail_st["z_image_turbo"]["ready"] is True
    assert avail_st["z_image_turbo"]["variant"] == "safetensors"
    assert avail_st["wan22_i2v"]["ready"] is True
    assert avail_st["wan22_i2v"]["variant"] == "safetensors"
    assert avail_st["wan22_t2v"]["ready"] is True
    assert avail_st["wan22_t2v"]["variant"] == "safetensors"

    wf_zit_st = build_z_image_turbo_workflow(
        "test",
        unet_name="z_image_turbo_bf16.safetensors",
        clip_name="qwen_3_4b.safetensors",
    )
    assert wf_zit_st["1"]["class_type"] == "UNETLoader"
    assert wf_zit_st["1"]["inputs"]["weight_dtype"] == "default"
    assert wf_zit_st["3"]["inputs"]["clip_name"] == "qwen_3_4b.safetensors"

    wf_wan_st = build_wan22_i2v_workflow(
        "test",
        image_filename="f.png",
        high_unet="wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        low_unet="wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        high_lora="wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        low_lora="wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    )
    assert wf_wan_st["1"]["class_type"] == "UNETLoader"
    assert wf_wan_st["2"]["class_type"] == "UNETLoader"
    assert wf_wan_st["3"]["inputs"]["lora_name"] == "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"

    wf_t2v_st = build_wan22_t2v_workflow(
        "test t2v",
        high_unet="wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
        low_unet="wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
        high_lora="wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
        low_lora="wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
    )
    assert wf_t2v_st["1"]["class_type"] == "UNETLoader"
    assert wf_t2v_st["11"]["class_type"] == "EmptyHunyuanLatentVideo"
    assert wf_t2v_st["16"]["class_type"] == "SaveVideo"

    wf_fk9 = build_flux2_klein_workflow(
        "test 9b",
        image_filename="friend.png",
        unet_name="flux-2-klein-9b-Q5_K_M.gguf",
        clip_name="qwen_3_8b_fp8mixed.safetensors",
    )
    assert wf_fk9["1"]["class_type"] == "UnetLoaderGGUF"
    assert wf_fk9["2"]["inputs"]["clip_name"] == "qwen_3_8b_fp8mixed.safetensors"
    assert wf_fk9["9"]["class_type"] == "ReferenceLatent"

    wf_qw2511 = build_qwen_edit_workflow(
        "test 2511",
        image_filename="f1.png",
        image_filename_2="f2.png",
        steps=4,
        cfg=1.0,
        unet_name="qwen-image-edit-2511-Q4_K_M.gguf",
        lora_name="Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
    )
    assert wf_qw2511["1b"]["class_type"] == "LoraLoaderModelOnly"
    assert wf_qw2511["2"]["inputs"]["model"] == ["1b", 0]
    assert wf_qw2511["9"]["inputs"]["steps"] == 4

    # 7. Concise ComfyUI error formatting extracts node/exception cleanly
    from clipforge.generator import _format_comfyui_error

    formatted = _format_comfyui_error(
        [
            ["execution_start", {"prompt_id": "abc"}],
            [
                "execution_error",
                {
                    "node_id": "17",
                    "node_type": "SamplerCustomAdvanced",
                    "exception_type": "torch.OutOfMemoryError",
                    "exception_message": "Allocation on device 0 would exceed allowed memory.\nCurrently allocated: 11.90 GiB",
                },
            ],
        ]
    )
    assert "SamplerCustomAdvanced (node 17)" in formatted
    assert "torch.OutOfMemoryError" in formatted



def test_cast_mentions_auto_router_aspect_match_hd_polish_and_qwen_lightning(tmp_path: Path, monkeypatch) -> None:
    """Verify Cast Book (@Name mentions), Auto Router, Aspect-Safe Dims, Qwen 4-step Lightning LoRA, HD Polish, and Smooth FPS."""
    from clipforge.cast import CastManager
    from clipforge.generator import (
        build_qwen_edit_workflow,
        compute_aspect_matched_dims,
        polish_image_hd,
        read_asset_metadata,
        read_image_dimensions,
    )

    ws = tmp_path / "ws_cast"
    eng = ProjectEngine(workspace_dir=ws)
    monkeypatch.setattr(web_server, "engine", eng)

    # Create a real portrait PNG (540x960) and a landscape PNG (800x450)
    p1 = tmp_path / "jake.png"
    p2 = tmp_path / "mike.png"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", "color=c=teal:s=540x960:d=1", "-frames:v", "1", str(p1)], capture_output=True, check=True)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", "color=c=crimson:s=800x450:d=1", "-frames:v", "1", str(p2)], capture_output=True, check=True)

    # 1. Zero-dependency PNG dimension reader + aspect-matched dimensions
    assert read_image_dimensions(p1) == (540, 960)
    w_img, h_img = compute_aspect_matched_dims(p1, kind="image", dim_step=16)
    assert h_img > w_img and w_img % 16 == 0 and h_img % 16 == 0
    w_vid, h_vid = compute_aspect_matched_dims(p2, kind="video", dim_step=32)
    assert w_vid > h_vid and w_vid % 32 == 0 and h_vid % 32 == 0

    # 2. Cast Manager + @Name auto-resolution
    cm = CastManager(ws)
    m1 = cm.save_member("Jake", photo_path=str(p1))
    m2 = cm.save_member("Mike", photo_path=str(p2))
    assert m1["handle"] == "@Jake" and m2["handle"] == "@Mike"

    resolved, img1, img2, matched = cm.resolve_prompt_mentions("@Jake and @Mike arguing over pizza")
    assert len(matched) == 2
    assert img1 == m1["photo_path"] and img2 == m2["photo_path"]
    assert "image 1" in resolved and "image 2" in resolved

    # 3. Qwen 4-step Lightning LoRA workflow graph
    wf_q = build_qwen_edit_workflow("test", image_filename="a.png", steps=4, cfg=1.0, use_lightning_lora=True)
    assert wf_q["1b"]["class_type"] == "LoraLoaderModelOnly"
    assert wf_q["2"]["inputs"]["model"] == ["1b", 0]
    assert wf_q["9"]["inputs"]["steps"] == 4

    # 4. 1-click 2x HD Polish (offline FFmpeg fast path in unit test; GPU 4x-UltraSharp tested live)
    polished = polish_image_hd(p1, ws / "generated_images", scale=2, prefer_ai=False)
    assert polished["width"] == 1080 and polished["height"] == 1920
    assert read_asset_metadata(Path(polished["image_path"]))["hd_scale"] == 2

    # 5. Smooth 32fps interpolation on a 16fps clip (offline FFmpeg fast path in unit test; GPU RIFE tested live)
    vid16 = tmp_path / "choppy16.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", "color=c=navy:s=320x240:r=16:d=1.0",
         "-f", "lavfi", "-i", "aevalsrc=0.2*sin(440*2*PI*t):s=44100:c=stereo:d=1.0",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(vid16)],
        capture_output=True, check=True,
    )
    imp = eng.import_media([str(vid16)])
    clip = eng.add_timeline_clip(imp[0].id)
    sm = eng.smooth_clip_fps(clip.id, target_fps=32.0, prefer_rife=False)
    assert Path(sm["output_path"]).exists()
    assert round(sm["media"]["fps"]) == 32

    # 6. Cast + Cancel Job + Polish HTTP endpoints + Director auto/@mention resolution
    client = TestClient(web_server.app)
    token = re.search(r'<meta name="clipforge-token" content="([^"]+)"', client.get("/").text).group(1)
    hdrs = {"X-ClipForge-Token": token}
    r_cast = client.post(
        "/api/cast",
        headers=hdrs,
        data={"name": "Alex"},
        files={"photo": ("alex.png", p1.read_bytes(), "image/png")},
    )
    assert r_cast.status_code == 200
    cid = r_cast.json()["member"]["id"]
    assert client.get(f"/api/cast/{cid}/photo", headers=hdrs).status_code == 200
    assert client.post("/api/generate/jobs/nonexistent/cancel", headers=hdrs).status_code == 200

    r_dir_auto = client.post(
        "/api/director/expand",
        headers=hdrs,
        json={"idea": "@Alex ordering 40 nuggets at 3am", "mode": "image", "model_id": "auto"},
    )
    assert r_dir_auto.status_code == 200
    assert r_dir_auto.json().get("prompt") and r_dir_auto.json().get("negative_prompt")

    # 7. Optional 2509 Lightning LoRA doesn't block readiness on Linux/minimal installs; 9-model auto router prefers HQ models when installed
    from clipforge.generator import get_model_availability, resolve_auto_model

    fake_comfy = tmp_path / "comfy_auto"
    for rel in (
        "models/diffusion_models/Qwen-Image-Edit-2509-Q4_K_M.gguf",
        "models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
        "models/vae/qwen_image_vae.safetensors",
        "models/diffusion_models/qwen-image-edit-2511-Q4_K_M.gguf",
        "models/loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
        "models/diffusion_models/flux-2-klein-9b-Q5_K_M.gguf",
        "models/text_encoders/qwen_3_8b_fp8mixed.safetensors",
        "models/vae/flux2-vae.safetensors",
    ):
        fp = fake_comfy / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(b"\x00" * (1024 * 1024 + 16))

    av = get_model_availability(fake_comfy)
    assert av["qwen_edit"]["ready"] is True
    assert av["qwen_edit"]["defaults"]["steps"] == 20
    assert av["qwen_edit_2511"]["ready"] is True
    assert av["qwen_edit_2511"]["defaults"]["steps"] == 4
    assert resolve_auto_model("image", True, False, comfy_dir=fake_comfy) == "flux2_klein_9b"
    assert resolve_auto_model("image", True, True, comfy_dir=fake_comfy) == "qwen_edit_2511"


def test_tier123_director_refusal_loras_inpaint_pose_vault_angles_and_storyboard(tmp_path: Path, monkeypatch) -> None:
    """Verify Tier 1-3 upgrades: refusal bypass + literal mode, LoRA stacker, inpaint/pose/denoise/RIFE/UltraSharp/S2V graphs, multi-angle cast, and storyboard planning."""
    from clipforge.cast import CastManager
    from clipforge.director import _looks_like_refusal, expand_meme_prompt_local, plan_storyboard_beats_local
    from clipforge.generator import (
        build_flux2_klein_workflow,
        build_qwen_edit_workflow,
        build_rife_interpolate_workflow,
        build_ultrasharp_upscale_workflow,
        build_wan22_s2v_workflow,
        build_z_image_turbo_workflow,
        list_available_loras,
        save_lora_trigger,
    )

    # 1. Refusal detector + Literal Zero-Sanitize Director + Storyboard Beat Planner
    assert _looks_like_refusal("I'm sorry, I cannot assist with generating that image.") is True
    assert _looks_like_refusal("As an AI language model, this violates safety policy.") is True
    assert _looks_like_refusal("Candid 35mm flash photo of a guy slipping on nacho cheese at 2AM") is False

    lit = expand_meme_prompt_local("wild raccoon heist at waffle house", mode="image", literal_mode=True)
    assert lit["source"] == "literal_enhancer"
    assert "wild raccoon heist at waffle house" in lit["prompt"]

    sb = plan_storyboard_beats_local("he accidentally launches his grill into orbit", num_beats=3, literal_mode=True)
    assert len(sb["beats"]) == 3
    assert all(b.get("prompt") for b in sb["beats"])

    # 2. LoRA auto-discovery + trigger persistence + workflow injection
    from clipforge.generator import _apply_lora_triggers

    fake_comfy = tmp_path / "comfy_t123"
    loras_dir = fake_comfy / "models" / "loras"
    loras_dir.mkdir(parents=True, exist_ok=True)
    (loras_dir / "flux2_vintage_film.safetensors").write_bytes(b"\x00" * 4096)
    (loras_dir / "wan22_action_cam.safetensors").write_bytes(b"\x00" * 4096)

    ws = tmp_path / "ws_t123"
    triggers_file = ws / "lora_triggers.json"
    save_lora_trigger(triggers_file, "flux2_vintage_film.safetensors", "vintfilm")
    found_loras = list_available_loras(fake_comfy, triggers_file)
    names = {x["name"]: x for x in found_loras}
    assert "flux2_vintage_film.safetensors" in names
    assert names["flux2_vintage_film.safetensors"]["family"] == "flux"
    assert names["flux2_vintage_film.safetensors"]["trigger"] == "vintfilm"

    # 3. Upgraded ComfyUI workflow graphs: Denoise, Mask Inpaint, Pose Ref, LoRA Stacker, UltraSharp, RIFE 4.9, Wan S2V
    user_lora = [{"name": "flux2_vintage_film.safetensors", "strength": 0.75, "trigger": "vintfilm"}]
    assert "vintfilm" in _apply_lora_triggers("wearing sunglasses", user_lora)
    wf_fk_adv = build_flux2_klein_workflow(
        _apply_lora_triggers("wearing sunglasses", user_lora),
        image_filename="base.png",
        pose_image_filename="pose.png",
        mask_filename="mask.png",
        denoise=0.6,
        loras=user_lora,
    )
    assert wf_fk_adv["ulora_0"]["class_type"] == "LoraLoaderModelOnly"
    assert wf_fk_adv["1d"]["class_type"] == "DifferentialDiffusion"
    assert wf_fk_adv["9p"]["class_type"] == "ReferenceLatent"
    assert wf_fk_adv["13b"]["class_type"] == "SplitSigmasDenoise"
    assert wf_fk_adv["m5"]["class_type"] == "SetLatentNoiseMask"
    assert wf_fk_adv["15b"]["class_type"] == "ImageCompositeMasked"
    assert "vintfilm" in wf_fk_adv["4"]["inputs"]["text"]

    wf_qw_adv = build_qwen_edit_workflow(
        "change jacket to red leather",
        image_filename="base.png",
        image_filename_2="friend2.png",
        image_filename_3="pose.png",
        mask_filename="mask.png",
        denoise=0.85,
        loras=user_lora,
    )
    assert wf_qw_adv["6"]["inputs"]["image3"] == ["5c", 0]
    assert wf_qw_adv["m5"]["class_type"] == "SetLatentNoiseMask"
    assert wf_qw_adv["10b"]["class_type"] == "ImageCompositeMasked"
    assert wf_qw_adv["9"]["inputs"]["denoise"] == pytest.approx(0.85)

    wf_zit_inp = build_z_image_turbo_workflow(
        "neon cyberpunk visor",
        image_filename="base.png",
        mask_filename="mask.png",
        denoise=0.72,
    )
    assert wf_zit_inp["m5"]["class_type"] == "SetLatentNoiseMask"
    assert wf_zit_inp["9b"]["class_type"] == "ImageCompositeMasked"
    assert wf_zit_inp["8"]["inputs"]["denoise"] == pytest.approx(0.72)

    wf_us = build_ultrasharp_upscale_workflow("photo.png", target_width=1024, target_height=1024)
    assert wf_us["2"]["class_type"] == "UpscaleModelLoader"
    assert wf_us["3"]["class_type"] == "ImageUpscaleWithModel"
    assert wf_us["4"]["class_type"] == "ImageScale"

    wf_rife = build_rife_interpolate_workflow("clip.mp4", multiplier=2, output_fps=32.0)
    assert wf_rife["1"]["class_type"] == "LoadVideo"
    assert wf_rife["3"]["class_type"] == "FrameInterpolationModelLoader"
    assert wf_rife["4"]["class_type"] == "FrameInterpolate"
    assert wf_rife["6"]["class_type"] == "SaveVideo"

    wf_s2v = build_wan22_s2v_workflow("talking meme", image_filename="face.png", audio_filename="voice.wav", loras=user_lora)
    assert wf_s2v["8"]["class_type"] == "AudioEncoderLoader"
    assert wf_s2v["11"]["class_type"] == "WanSoundImageToVideo"
    assert wf_s2v["15"]["class_type"] == "SaveVideo"
    assert wf_s2v["ulora_0"]["class_type"] == "LoraLoaderModelOnly"

    # 4. Multi-angle Cast Profiles + automatic 2nd-angle attachment for single-friend mentions
    p1 = tmp_path / "ang1.png"
    p2 = tmp_path / "ang2.png"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", "color=c=blue:s=256x256:d=1", "-frames:v", "1", str(p1)], capture_output=True, check=True)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", "color=c=green:s=256x256:d=1", "-frames:v", "1", str(p2)], capture_output=True, check=True)

    cm = CastManager(ws)
    m = cm.save_member("Sam", photo_path=str(p1))
    m_ang = cm.add_extra_photo(m["id"], photo_path=str(p2))
    assert m_ang["photo_count"] == 2
    assert len(m_ang["extra_photo_urls"]) == 1

    _, out_i1, out_i2, matched = cm.resolve_prompt_mentions("@Sam skateboarding on a volcano")
    assert len(matched) == 1
    assert out_i1 == m_ang["photo_path"]
    assert out_i2 == m_ang["extra_photos"][0]

    # 5. New HTTP endpoints & security jails
    from clipforge import generator as gen_mod

    eng = ProjectEngine(workspace_dir=ws)
    monkeypatch.setattr(web_server, "engine", eng)
    monkeypatch.setattr(web_server, "COMFYUI_DIR", fake_comfy)
    monkeypatch.setattr(gen_mod, "COMFYUI_DIR", fake_comfy)
    client = TestClient(web_server.app)
    token = re.search(r'<meta name="clipforge-token" content="([^"]+)"', client.get("/").text).group(1)
    hdrs = {"X-ClipForge-Token": token}

    r_loras = client.get("/api/loras", headers=hdrs)
    assert r_loras.status_code == 200
    assert any(x["name"] == "flux2_vintage_film.safetensors" for x in r_loras.json()["loras"])

    r_trig = client.post("/api/loras/trigger", headers=hdrs, json={"name": "wan22_action_cam.safetensors", "trigger": "gopro_pov"})
    assert r_trig.status_code == 200

    r_sb = client.post("/api/director/storyboard", headers=hdrs, json={"concept": "pizza delivery on mars", "num_beats": 2, "literal_mode": True})
    assert r_sb.status_code == 200 and len(r_sb.json()["beats"]) == 2

    # Multi-angle Cast HTTP endpoints
    r_c_ang = client.post(
        f"/api/cast/{m['id']}/photo",
        headers=hdrs,
        files={"photo": ("angle3.png", p2.read_bytes(), "image/png")},
    )
    assert r_c_ang.status_code == 200 and r_c_ang.json()["member"]["photo_count"] == 3
    assert client.get(f"/api/cast/{m['id']}/photo/0", headers=hdrs).status_code == 200
    assert client.delete(f"/api/cast/{m['id']}/photo/0", headers=hdrs).status_code == 200

    # Video Vault path traversal block & status fields
    assert client.get("/api/generate/video/..%5Cproject.json", headers=hdrs).status_code in (400, 404)
    st = client.get("/api/generate/status", headers=hdrs).json()
    assert "videos" in st and "loras" in st and "director" in st
    assert st["models"]["wan22_s2v"]["requires_audio"] is True
    assert st["models"]["upscale_ultrasharp"]["kind"] == "utility"
    assert st["models"]["rife_vfi"]["kind"] == "utility"

    # Regression: _extract_saved_output_info must skip LoadVideo 'input' previews and pick SaveVideo 'output'
    from clipforge.generator import _extract_saved_output_info

    picked = _extract_saved_output_info(
        {
            "outputs": {
                "1": {"images": [{"filename": "cf_rife_in.mp4", "subfolder": "", "type": "input"}]},
                "6": {"images": [{"filename": "rife_out_00001_.mp4", "subfolder": "clipforge", "type": "output"}]},
            }
        },
        extensions=(".mp4",),
    )
    assert picked is not None and picked["filename"] == "rife_out_00001_.mp4" and picked["type"] == "output"


def test_civitai_new_architectures_starter_packs_and_checkpoints(tmp_path: Path, monkeypatch) -> None:
    """Verify Krea 2 Turbo, Chroma1-HD, Illustrious XL workflows, checkpoint discovery, Starter Packs & CivitAI module."""
    from clipforge import civitai as civ_mod
    from clipforge import generator as gen_mod
    from clipforge.director import expand_meme_prompt_local
    from clipforge.generator import (
        build_chroma_workflow,
        build_illustrious_xl_workflow,
        build_krea2_workflow,
        build_z_image_turbo_workflow,
        get_model_availability,
        get_starter_packs,
        list_custom_checkpoints,
        resolve_auto_model,
    )

    user_lora = [{"name": "style_boost.safetensors", "strength": 0.75, "trigger": "cinematic_vibe"}]

    # 1. Krea 2 Turbo workflow (T2I + ReferenceLatent + Mask Inpaint + CheckpointLoader override)
    wf_krea = build_krea2_workflow(
        "candid film photo",
        image_filename="ref.png",
        mask_filename="mask.png",
        denoise=0.82,
        loras=user_lora,
    )
    assert wf_krea["2"]["class_type"] == "CLIPLoader"
    assert wf_krea["2"]["inputs"]["type"] == "krea2"
    assert wf_krea["7r"]["class_type"] == "ReferenceLatent"
    assert wf_krea["1d"]["class_type"] == "DifferentialDiffusion"
    assert wf_krea["9b"]["class_type"] == "ImageCompositeMasked"
    assert wf_krea["ulora_0"]["class_type"] == "LoraLoaderModelOnly"

    wf_krea_ckpt = build_krea2_workflow("portrait", unet_name="big_love_krea2.safetensors", use_checkpoint_loader=True)
    assert wf_krea_ckpt["1"]["class_type"] == "CheckpointLoaderSimple"

    # 2. Chroma1-HD workflow (AuraFlow shift=1.0 + t5xxl chroma + inpaint)
    wf_chroma = build_chroma_workflow(
        "raw street photo",
        image_filename="orig.png",
        mask_filename="mask.png",
        denoise=0.78,
        loras=user_lora,
    )
    assert wf_chroma["2"]["class_type"] == "ModelSamplingAuraFlow"
    assert wf_chroma["2"]["inputs"]["shift"] == 1.0
    assert wf_chroma["3"]["inputs"]["type"] == "chroma"
    assert wf_chroma["2d"]["class_type"] == "DifferentialDiffusion"
    assert wf_chroma["9b"]["class_type"] == "ImageCompositeMasked"

    # 3. Illustrious XL workflow (CheckpointLoaderSimple + CLIP skip -2 + full LoraLoader model+clip + inpaint)
    wf_ill = build_illustrious_xl_workflow(
        "masterpiece, 1girl, neon rooftop",
        image_filename="orig.png",
        mask_filename="mask.png",
        denoise=0.75,
        ckpt_name="janku_illustrious.safetensors",
        loras=user_lora,
    )
    assert wf_ill["1"]["class_type"] == "CheckpointLoaderSimple"
    assert wf_ill["2"]["class_type"] == "CLIPSetLastLayer"
    assert wf_ill["2"]["inputs"]["stop_at_clip_layer"] == -2
    assert wf_ill["ulora_0"]["class_type"] == "LoraLoader"
    assert wf_ill["3"]["inputs"]["clip"] == ["ulora_0", 1]
    assert wf_ill["1d"]["class_type"] == "DifferentialDiffusion"
    assert wf_ill["7b"]["class_type"] == "ImageCompositeMasked"

    # 4. Z-Image-Turbo checkpoint-folder override mode
    wf_zit_ck = build_z_image_turbo_workflow("photo", unet_name="zenith_zit.safetensors", use_checkpoint_loader=True)
    assert wf_zit_ck["1"]["class_type"] == "CheckpointLoaderSimple"

    # 5. Director Danbooru tag formatting for Illustrious XL (zero-refusal offline fallback)
    enh_ill = expand_meme_prompt_local("cyberpunk samurai on a rainy rooftop", mode="image", model_id="illustrious_xl", literal_mode=True)
    assert "masterpiece" in enh_ill["prompt"].lower()
    assert "bad anatomy" in enh_ill["negative_prompt"].lower()

    # 6. Community checkpoint auto-discovery + illustrious_xl scan_dir readiness + intent routing + starter packs
    fake_comfy = tmp_path / "comfy_civ"
    ckpt_dir = fake_comfy / "models" / "checkpoints"
    diff_dir = fake_comfy / "models" / "diffusion_models"
    ckpt_dir.mkdir(parents=True)
    diff_dir.mkdir(parents=True)

    # Create sparse 105MB files so size filters match real weights without writing 105MB to disk
    for fp in (ckpt_dir / "Realism_Illustrious_v5.safetensors", diff_dir / "Zenith_ZiT_v2.safetensors"):
        with open(fp, "wb") as fh:
            fh.seek(110 * 1024 * 1024)
            fh.write(b"\0")

    ckpts = list_custom_checkpoints(fake_comfy)
    assert len(ckpts) == 2
    by_name = {c["filename"]: c for c in ckpts}
    assert by_name["Realism_Illustrious_v5.safetensors"]["family"] == "illustrious"
    assert "illustrious_xl" in by_name["Realism_Illustrious_v5.safetensors"]["compatible_models"]
    assert by_name["Zenith_ZiT_v2.safetensors"]["family"] == "z_image"
    assert "z_image_turbo" in by_name["Zenith_ZiT_v2.safetensors"]["compatible_models"]

    # Installing ANY CivitAI Illustrious checkpoint immediately marks illustrious_xl ready!
    avail = get_model_availability(fake_comfy)
    assert avail["illustrious_xl"]["ready"] is True
    assert resolve_auto_model("image", intent="anime", comfy_dir=fake_comfy) == "illustrious_xl"

    packs = get_starter_packs(fake_comfy)
    assert {p["id"] for p in packs} == {"fast_8gb", "hq_16gb", "anime_civitai"}
    assert any(p["recommended"] for p in packs)

    # 7. CivitAI URL parser, SSRF validation, folder routing, and secret store
    assert civ_mod.parse_civitai_reference("https://civitai.com/models/2237711/zenith?modelVersionId=2554321") == (2237711, 2554321)
    assert civ_mod.parse_civitai_reference("https://civitai.com/api/download/models/998877") == (None, 998877)
    assert civ_mod.parse_civitai_reference("974693") == (974693, None)
    with pytest.raises(ValueError):
        civ_mod.parse_civitai_reference("https://evil.example.com/models/123")

    assert civ_mod.classify_civitai_target("LORA", "ZImageTurbo", "famegrid.safetensors")[0] == "loras"
    assert civ_mod.classify_civitai_target("Checkpoint", "Illustrious", "janku.safetensors")[0] == "checkpoints"
    assert civ_mod.classify_civitai_target("Checkpoint", "ZImageTurbo", "zenith.safetensors")[0] == "diffusion_models"
    assert civ_mod.classify_civitai_target("Checkpoint", "Krea 2", "biglove.safetensors")[0] == "diffusion_models"
    assert civ_mod.classify_civitai_target("Checkpoint", "Chroma", "chroma.safetensors")[0] == "diffusion_models"

    # 8. HTTP endpoints for checkpoints, starter packs, and CivitAI API key (never echoes secret!)
    ws = tmp_path / "ws_civ"
    eng = ProjectEngine(workspace_dir=ws)
    monkeypatch.setattr(web_server, "engine", eng)
    monkeypatch.setattr(web_server, "COMFYUI_DIR", fake_comfy)
    monkeypatch.setattr(gen_mod, "COMFYUI_DIR", fake_comfy)
    client = TestClient(web_server.app)
    token = re.search(r'<meta name="clipforge-token" content="([^"]+)"', client.get("/").text).group(1)
    hdrs = {"X-ClipForge-Token": token}

    r_ck = client.get("/api/checkpoints", headers=hdrs)
    assert r_ck.status_code == 200 and len(r_ck.json()["checkpoints"]) == 2

    r_key = client.post("/api/civitai/api-key", headers=hdrs, json={"api_key": "test_dummy_token_value"})
    assert r_key.status_code == 200
    assert r_key.json()["has_api_key"] is True
    assert "test_dummy_token_value" not in r_key.text

    r_st = client.get("/api/generate/status", headers=hdrs).json()
    assert r_st["civitai"]["has_api_key"] is True
    assert len(r_st["civitai"]["curated"]) >= 10
    assert len(r_st["starter_packs"]) == 3
    assert len(r_st["checkpoints"]) == 2

    # 9. Simple Mode direct video Continue (end-frame) + Stitch Chain endpoints
    gen_dir = ws / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    v1 = _generate_synthetic_clip(gen_dir / "part1.mp4", "crimson", total_dur=1.4, lead_silence=0.1, trail_silence=0.1)
    v2 = _generate_synthetic_clip(gen_dir / "part2.mp4", "teal", total_dur=1.4, lead_silence=0.1, trail_silence=0.1)

    r_ef = client.post(f"/api/generate/video/{v1.name}/end-frame", headers=hdrs)
    assert r_ef.status_code == 200
    ef_json = r_ef.json()
    assert ef_json["parent_video"] == v1.name
    assert Path(ef_json["image_path"]).exists()

    r_stch = client.post("/api/generate/video/stitch", headers=hdrs, json={"filenames": [v1.name, v2.name]})
    assert r_stch.status_code == 200
    stch_json = r_stch.json()
    assert stch_json["parts"] == 2
    assert Path(stch_json["video_path"]).exists()
    assert stch_json["duration_sec"] >= 2.5




