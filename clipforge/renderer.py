"""FFmpeg multi-clip filtergraph compiler, xfade stitcher, and ASS subtitle burner."""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import MemeLayoutConfig, ProjectState, ensure_even_dimension, sanitize_hex_color
from .platform_utils import resolve_ffmpeg_fontfile as _resolve_ffmpeg_fontfile
from .subtitles import write_subtitle_file


@lru_cache(maxsize=1)
def _ffmpeg_filter_script_flag() -> str:
    """Use '-/filter_complex' on FFmpeg 7+ (required on FFmpeg 8/9) and '-filter_complex_script' on FFmpeg 4-6."""
    try:
        res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        first_line = (res.stdout or res.stderr or "").splitlines()[0] if (res.stdout or res.stderr) else ""
        if "version N-" in first_line:
            return "-/filter_complex"
        m = re.search(r"ffmpeg version\s+(?:n)?(\d+)\.", first_line, flags=re.IGNORECASE)
        if m and int(m.group(1)) < 7:
            return "-filter_complex_script"
    except Exception:
        pass
    return "-/filter_complex"


def _append_meme_layout_filters(
    layout: MemeLayoutConfig,
    in_label: str,
    w: int,
    h: int,
    bg_ffmpeg: str,
    out_dir: Path,
    run_nonce: str,
    filter_parts: list[str],
    temp_files: list[Path],
) -> str:
    """Apply injection-safe native meme layout templates using external UTF-8 textfile= files."""
    if not layout or layout.template == "none":
        return in_label

    short_edge = min(w, h)
    cur = in_label

    def _write_wrapped_txt(tag: str, raw: str, max_chars: int, uppercase: bool = False) -> Path | None:
        clean = (raw or "").strip()
        if not clean:
            return None
        if uppercase:
            clean = clean.upper()
        wrapped = "\n".join(textwrap.wrap(clean, width=max_chars) or [clean])
        tf = out_dir / f"_cf_ml_{tag}_{run_nonce}.txt"
        tf.write_text(wrapped, encoding="utf-8")
        temp_files.append(tf)
        return tf

    if layout.template in ("pov_top_bar", "pov_dark_bar"):
        is_dark = layout.template == "pov_dark_bar"
        bar_bg = "0x0F0F14" if is_dark else "0xFFFFFF"
        txt_col = "0xF4F4F6" if is_dark else "0x09090B"
        bar_h = max(64, (int(h * 0.19) // 2) * 2)
        vid_h = max(64, h - bar_h)
        f_arial = _resolve_ffmpeg_fontfile("arialbd.ttf")
        font_opt = f"fontfile='{f_arial}':" if f_arial else ""
        # Place scaled video below crisp top caption bar
        filter_parts.append(
            f"[{cur}]scale={w}:{vid_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{vid_h}:(ow-iw)/2:(oh-ih)/2:color={bg_ffmpeg},"
            f"pad={w}:{h}:0:{bar_h}:color={bar_bg}[vml_bar]"
        )
        cur = "vml_bar"
        tf_top = _write_wrapped_txt("top", layout.top_text, max_chars=max(18, int(w / (short_edge * 0.044))))
        if tf_top is not None:
            fs = max(20, int(short_edge * 0.056))
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_top.name}:reload=0:"
                f"fontcolor={txt_col}:fontsize={fs}:line_spacing=6:"
                f"x=(w-text_w)/2:y=({bar_h}-text_h)/2[vml_done]"
            )
            cur = "vml_done"

    elif layout.template == "demotivational":
        f_bold = _resolve_ffmpeg_fontfile("arialbd.ttf")
        font_opt = f"fontfile='{f_bold}':" if f_bold else ""
        inner_w = max(64, (int(w * 0.80) // 2) * 2)
        inner_h = max(64, (int(h * 0.66) // 2) * 2)
        pad_x = (w - inner_w) // 2
        pad_top = max(24, (int(h * 0.08) // 2) * 2)
        filter_parts.append(
            f"[{cur}]scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={inner_w}:{inner_h}:(ow-iw)/2:(oh-ih)/2:color=0x000000,"
            f"pad={w}:{h}:{pad_x}:{pad_top}:color=0x000000,"
            f"drawbox=x={pad_x - 4}:y={pad_top - 4}:w={inner_w + 8}:h={inner_h + 8}:color=0xFFFFFF:t=3[vml_demot]"
        )
        cur = "vml_demot"
        title_y = pad_top + inner_h + max(16, int(h * 0.032))
        fs_title = max(22, int(short_edge * 0.068))
        tf_top = _write_wrapped_txt("top", layout.top_text, max_chars=24, uppercase=True)
        if tf_top is not None:
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_top.name}:reload=0:"
                f"fontcolor=0xFFFFFF:fontsize={fs_title}:"
                f"x=(w-text_w)/2:y={title_y}[vml_demot_t]"
            )
            cur = "vml_demot_t"
        tf_bot = _write_wrapped_txt("bot", layout.bottom_text, max_chars=44, uppercase=False)
        if tf_bot is not None:
            fs_sub = max(14, int(short_edge * 0.034))
            sub_y = title_y + fs_title + max(10, int(h * 0.018))
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_bot.name}:reload=0:"
                f"fontcolor=0xD4D4D8:fontsize={fs_sub}:"
                f"x=(w-text_w)/2:y={sub_y}[vml_demot_b]"
            )
            cur = "vml_demot_b"

    elif layout.template == "bodycam_hud":
        f_mono = _resolve_ffmpeg_fontfile("consolab.ttf") or _resolve_ffmpeg_fontfile("arialbd.ttf")
        font_opt = f"fontfile='{f_mono}':" if f_mono else ""
        fs_hud = max(14, int(short_edge * 0.032))
        hud_w = max(210, int(w * 0.42))
        hud_h = max(62, int(fs_hud * 3.4))
        hud_x = w - hud_w - max(12, int(w * 0.03))
        hud_y = max(12, int(h * 0.03))
        filter_parts.append(
            f"[{cur}]drawbox=x={hud_x}:y={hud_y}:w={hud_w}:h={hud_h}:color=0x000000@0.58:t=fill,"
            f"drawbox=x={hud_x + 12}:y={hud_y + 13}:w=10:h=10:color=0xEF4444@1.0:t=fill[vml_bc_box]"
        )
        cur = "vml_bc_box"
        line1 = (layout.banner_label or "AXON BODY 4  REC").upper()
        line2 = (layout.top_text or "2026-11-23  02:14:09 -0500").upper()
        line3 = (layout.bottom_text or "UNIT 406  X6039A8B").upper()
        hud_txt = f"  {line1}\n{line2}\n{line3}"
        tf_hud = out_dir / f"_cf_ml_hud_{run_nonce}.txt"
        tf_hud.write_text(hud_txt, encoding="utf-8")
        temp_files.append(tf_hud)
        filter_parts.append(
            f"[{cur}]drawtext={font_opt}textfile={tf_hud.name}:reload=0:"
            f"fontcolor=0xF4F4F6:fontsize={fs_hud}:line_spacing=4:"
            f"x={hud_x + 16}:y={hud_y + 10}[vml_bc_done]"
        )
        cur = "vml_bc_done"

    elif layout.template == "impact_top_bottom":
        f_impact = _resolve_ffmpeg_fontfile("impact.ttf")
        font_opt = f"fontfile='{f_impact}':" if f_impact else ""
        fs = max(24, int(short_edge * 0.088))
        bw = max(2, int(fs * 0.09))
        pad_y = max(18, int(h * 0.04))
        max_chars = max(14, int(w / (fs * 0.56)))

        tf_top = _write_wrapped_txt("top", layout.top_text, max_chars=max_chars, uppercase=True)
        if tf_top is not None:
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_top.name}:reload=0:"
                f"fontcolor=white:bordercolor=black:borderw={bw}:fontsize={fs}:line_spacing=4:"
                f"x=(w-text_w)/2:y={pad_y}[vml_top]"
            )
            cur = "vml_top"

        tf_bot = _write_wrapped_txt("bot", layout.bottom_text, max_chars=max_chars, uppercase=True)
        if tf_bot is not None:
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_bot.name}:reload=0:"
                f"fontcolor=white:bordercolor=black:borderw={bw}:fontsize={fs}:line_spacing=4:"
                f"x=(w-text_w)/2:y=h-text_h-{pad_y}[vml_bot]"
            )
            cur = "vml_bot"

    elif layout.template == "breaking_news":
        f_bold = _resolve_ffmpeg_fontfile("arialbd.ttf")
        font_opt = f"fontfile='{f_bold}':" if f_bold else ""
        box_h = max(56, int(h * 0.105))
        sub_h = max(32, int(h * 0.052))
        y_main = h - box_h - sub_h - max(14, int(h * 0.03))
        y_sub = y_main + box_h
        tag_w = max(150, int(w * 0.28))

        # Red breaking pill + white headline bar + dark ticker sub-bar
        filter_parts.append(
            f"[{cur}]drawbox=x=0:y={y_main}:w={w}:h={box_h}:color=0xFFFFFF@0.96:t=fill,"
            f"drawbox=x=0:y={y_main}:w={tag_w}:h={box_h}:color=0xDC2626@1.0:t=fill,"
            f"drawbox=x=0:y={y_sub}:w={w}:h={sub_h}:color=0x09090B@0.92:t=fill[vml_bn_box]"
        )
        cur = "vml_bn_box"

        tf_lbl = _write_wrapped_txt("lbl", layout.banner_label or "BREAKING NEWS", max_chars=18, uppercase=True)
        if tf_lbl is not None:
            fs_lbl = max(14, int(box_h * 0.34))
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_lbl.name}:reload=0:"
                f"fontcolor=white:fontsize={fs_lbl}:"
                f"x=({tag_w}-text_w)/2:y={y_main}+({box_h}-text_h)/2[vml_bn_lbl]"
            )
            cur = "vml_bn_lbl"

        tf_top = _write_wrapped_txt("top", layout.top_text, max_chars=max(20, int((w - tag_w) / (box_h * 0.26))), uppercase=True)
        if tf_top is not None:
            fs_hl = max(16, int(box_h * 0.42))
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_top.name}:reload=0:"
                f"fontcolor=0x09090B:fontsize={fs_hl}:"
                f"x={tag_w}+16:y={y_main}+({box_h}-text_h)/2[vml_bn_hl]"
            )
            cur = "vml_bn_hl"

        tf_bot = _write_wrapped_txt("bot", layout.bottom_text, max_chars=64, uppercase=False)
        if tf_bot is not None:
            fs_sub = max(12, int(sub_h * 0.52))
            filter_parts.append(
                f"[{cur}]drawtext={font_opt}textfile={tf_bot.name}:reload=0:"
                f"fontcolor=0xFACC15:fontsize={fs_sub}:"
                f"x=18:y={y_sub}+({sub_h}-text_h)/2[vml_bn_sub]"
            )
            cur = "vml_bn_sub"

    return cur


def build_atempo_chain(speed: float) -> str:
    """Build chained atempo filters for arbitrary speed in [0.1, 16.0]."""
    spd = max(0.1, min(16.0, float(speed)))
    if abs(spd - 1.0) < 1e-3:
        return ""
    filters: list[str] = []
    rem = spd
    while rem < 0.5:
        filters.append("atempo=0.5")
        rem /= 0.5
    while rem > 2.0:
        filters.append("atempo=2.0")
        rem /= 2.0
    if abs(rem - 1.0) >= 1e-3:
        filters.append(f"atempo={rem:.4f}")
    return ("," + ",".join(filters)) if filters else ""


def render_project_to_mp4(
    project: ProjectState,
    output_path: str | Path,
    burn_subtitles: bool = True,
    quality: str = "balanced",
    normalize_audio: bool = True,
    use_hw_accel: bool = True,
) -> dict[str, Any]:
    """Compile the timeline schedule into an FFmpeg filtergraph and render an MP4."""
    schedule = project.compute_timeline_schedule()
    if not schedule:
        raise ValueError("Timeline is empty — add clips before rendering.")

    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    run_nonce = uuid.uuid4().hex[:10]
    srt_path = out_file.with_suffix(".srt")
    ass_path = out_file.with_suffix(".ass")
    temp_ass_path: Path | None = None
    temp_fg_path: Path | None = None
    extra_temp_files: list[Path] = []
    has_subs = len(project.subtitles) > 0

    w = ensure_even_dimension(project.width)
    h = ensure_even_dimension(project.height)
    fps = max(1.0, min(120.0, float(project.fps)))
    bg_hex = sanitize_hex_color(project.bg_color, "#000000")
    bg_ffmpeg = "0x" + bg_hex.lstrip("#")

    input_args: list[str] = []
    filter_parts: list[str] = []

    try:
        if has_subs:
            write_subtitle_file(project, srt_path, fmt="srt")
            write_subtitle_file(project, ass_path, fmt="ass")
            if burn_subtitles:
                # Strictly alphanumeric temp ASS filename eliminates filtergraph quote/metacharacter injection
                temp_ass_path = out_file.parent / f"_cf_subs_{run_nonce}.ass"
                shutil.copyfile(ass_path, temp_ass_path)

        for idx, item in enumerate(schedule):
            clip = item.clip
            media = project.get_media(clip.media_id)
            if not media:
                raise ValueError(f"Media ID '{clip.media_id}' referenced by clip '{clip.id}' not found.")

            in_s = max(0.0, clip.in_sec)
            out_s = max(in_s + 0.04, clip.out_sec)
            src_dur = out_s - in_s
            spd = max(0.1, min(16.0, clip.speed))
            eff_dur = item.effective_duration_sec

            # Static image clips (generated memes/title cards) loop smoothly at project FPS
            if media.is_image:
                fine_in = 0.0
                fine_out = eff_dur
                input_args.extend(["-loop", "1", "-framerate", f"{fps:.3f}", "-t", f"{eff_dur + 0.5:.4f}", "-i", media.path])
            # Fast input-side coarse seek avoids decoding minutes of dead footage from t=0
            elif in_s > 2.5:
                coarse_ss = max(0.0, in_s - 1.5)
                fine_in = in_s - coarse_ss
                fine_out = out_s - coarse_ss
                coarse_t = (out_s - coarse_ss) + 1.0
                input_args.extend(["-ss", f"{coarse_ss:.4f}", "-t", f"{coarse_t:.4f}", "-i", media.path])
            else:
                fine_in = in_s
                fine_out = out_s
                coarse_t = out_s + 1.0
                input_args.extend(["-t", f"{coarse_t:.4f}", "-i", media.path])

            # Video normalization: exact eff_dur clamp + tpad clone guarantees video length matches schedule
            if media.is_image:
                v_chain = (
                    f"[{idx}:v]fps={fps:.3f},"
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={bg_ffmpeg},"
                    f"setsar=1,format=yuv420p,"
                    f"trim=duration={eff_dur:.6f},setpts=PTS-STARTPTS,settb=AVTB[v{idx}]"
                )
            elif media.has_video:
                v_chain = (
                    f"[{idx}:v]trim=start={fine_in:.4f}:end={fine_out:.4f},"
                    f"setpts=(PTS-STARTPTS)/{spd:.6f},"
                    f"fps={fps:.3f},"
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={bg_ffmpeg},"
                    f"setsar=1,format=yuv420p,"
                    f"tpad=stop_mode=clone:stop_duration=0.5,"
                    f"trim=duration={eff_dur:.6f},setpts=PTS-STARTPTS,settb=AVTB[v{idx}]"
                )
            else:
                # Synthesize solid canvas for audio-only tracks
                v_chain = (
                    f"color=c={bg_ffmpeg}:s={w}x{h}:r={fps:.3f}:d={eff_dur:.6f},"
                    f"setsar=1,format=yuv420p,settb=AVTB[v{idx}]"
                )
            filter_parts.append(v_chain)

            # Audio normalization: apad + atrim to exact eff_dur eliminates A/V desync across acrossfade/atempo
            if media.has_audio and not clip.muted and clip.volume > 0.0:
                atempo_str = build_atempo_chain(spd)
                vol_str = f",volume={clip.volume:.3f}" if abs(clip.volume - 1.0) >= 1e-3 else ""
                a_chain = (
                    f"[{idx}:a]atrim=start={fine_in:.4f}:end={fine_out:.4f},"
                    f"asetpts=PTS-STARTPTS{atempo_str}{vol_str},"
                    f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"apad=whole_dur={eff_dur:.6f},atrim=duration={eff_dur:.6f},asetpts=PTS-STARTPTS[a{idx}]"
                )
            else:
                a_chain = (
                    f"aevalsrc=0:c=stereo:s=44100:d={eff_dur:.6f},"
                    f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"atrim=duration={eff_dur:.6f},asetpts=PTS-STARTPTS[a{idx}]"
                )
            filter_parts.append(a_chain)

        # Stitch clips sequentially via concat (hard cuts) or xfade + acrossfade (transitions)
        curr_v = "v0"
        curr_a = "a0"
        for idx in range(1, len(schedule)):
            item = schedule[idx]
            next_v = f"v{idx}"
            next_a = f"a{idx}"
            out_v = f"vx{idx}"
            out_a = f"ax{idx}"

            if item.applied_transition and item.applied_transition_duration > 0.0:
                trans = item.applied_transition
                tdur = item.applied_transition_duration
                toff = item.xfade_offset_sec
                filter_parts.append(
                    f"[{curr_v}][{next_v}]xfade=transition={trans}:duration={tdur:.4f}:offset={toff:.4f}[{out_v}]"
                )
                filter_parts.append(
                    f"[{curr_a}][{next_a}]acrossfade=d={tdur:.4f}:c1=tri:c2=tri[{out_a}]"
                )
            else:
                filter_parts.append(f"[{curr_v}][{next_v}]concat=n=2:v=1:a=0[{out_v}]")
                filter_parts.append(f"[{curr_a}][{next_a}]concat=n=2:v=0:a=1[{out_a}]")
            curr_v = out_v
            curr_a = out_a

        # Mix dedicated SFX / BGM Audio Overlay track with optional sidechain auto-ducking
        valid_overlays = [
            ov for ov in (project.audio_overlays or []) if Path(ov.path).exists() and ov.volume > 0.0
        ]
        if valid_overlays:
            total_dur = max(0.1, project.total_duration_sec)
            ov_labels: list[str] = []
            duck_labels: list[str] = []
            for k, ov in enumerate(valid_overlays):
                ov_input_idx = len(schedule) + k
                input_args.extend(["-i", ov.path])
                delay_ms = max(0, int(round(ov.start_sec * 1000.0)))
                lbl = f"ov{k}"
                filter_parts.append(
                    f"[{ov_input_idx}:a]"
                    f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"volume={ov.volume:.3f},"
                    f"adelay={delay_ms}|{delay_ms},"
                    f"apad=whole_dur={total_dur:.6f},atrim=duration={total_dur:.6f},"
                    f"asetpts=PTS-STARTPTS[{lbl}]"
                )
                ov_labels.append(lbl)
                if ov.duck_main_audio:
                    duck_labels.append(lbl)

            main_a_for_mix = curr_a
            mix_inputs: list[str] = []
            if duck_labels:
                if len(duck_labels) == 1:
                    filter_parts.append(f"[{duck_labels[0]}]asplit=2[duck_sc][duck_mix]")
                else:
                    d_in = "".join(f"[{dl}]" for dl in duck_labels)
                    filter_parts.append(
                        f"{d_in}amix=inputs={len(duck_labels)}:duration=first:normalize=0,asplit=2[duck_sc][duck_mix]"
                    )
                filter_parts.append(
                    f"[{curr_a}][duck_sc]sidechaincompress=threshold=0.04:ratio=5:attack=15:release=260[main_ducked]"
                )
                main_a_for_mix = "main_ducked"
                mix_inputs.append("[main_ducked]")
                mix_inputs.append("[duck_mix]")
                for lbl in ov_labels:
                    if lbl not in duck_labels:
                        mix_inputs.append(f"[{lbl}]")
            else:
                mix_inputs.append(f"[{main_a_for_mix}]")
                for lbl in ov_labels:
                    mix_inputs.append(f"[{lbl}]")

            filter_parts.append(
                f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:normalize=0,"
                f"alimiter=limit=0.96[amixed]"
            )
            curr_a = "amixed"

        # Apply native Meme Layout template (POV bar, Impact top/bottom, Breaking News)
        curr_v = _append_meme_layout_filters(
            layout=project.meme_layout,
            in_label=curr_v,
            w=w,
            h=h,
            bg_ffmpeg=bg_ffmpeg,
            out_dir=out_file.parent,
            run_nonce=run_nonce,
            filter_parts=filter_parts,
            temp_files=extra_temp_files,
        )

        if burn_subtitles and temp_ass_path is not None:
            # Safe alphanumeric filename in cwd=out_file.parent -> zero filtergraph injection risk
            filter_parts.append(f"[{curr_v}]ass=filename={temp_ass_path.name}[vfinal]")
            curr_v = "vfinal"

        if normalize_audio:
            filter_parts.append(f"[{curr_a}]dynaudnorm=f=150:g=15[afinal]")
            curr_a = "afinal"

        filter_complex = ";\n".join(filter_parts)
        # Write filtergraph to file and pass via FFmpeg 7+/9+ '-/filter_complex' to avoid Windows 32KB cmdline limit
        temp_fg_path = out_file.parent / f"_cf_fg_{run_nonce}.txt"
        temp_fg_path.write_text(filter_complex, encoding="utf-8")

        t0 = time.perf_counter()
        encoder_used = "libx264"

        def _build_cmd(use_nvenc: bool) -> list[str]:
            if use_nvenc:
                cq = "19" if quality == "high" else ("26" if quality == "draft" else "23")
                preset = "p5" if quality == "high" else ("p2" if quality == "draft" else "p4")
                v_enc = ["-c:v", "h264_nvenc", "-preset", preset, "-rc", "vbr", "-cq", cq, "-b:v", "0"]
            else:
                crf = "18" if quality == "high" else ("25" if quality == "draft" else "21")
                preset = "medium" if quality == "high" else ("ultrafast" if quality == "draft" else "veryfast")
                v_enc = ["-c:v", "libx264", "-preset", preset, "-crf", crf]

            return [
                "ffmpeg",
                "-y",
                "-hide_banner",
                *input_args,
                _ffmpeg_filter_script_flag(),
                temp_fg_path.name,
                "-map",
                f"[{curr_v}]",
                "-map",
                f"[{curr_a}]",
                *v_enc,
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(out_file),
            ]

        res = None
        if use_hw_accel:
            cmd_nvenc = _build_cmd(use_nvenc=True)
            res = subprocess.run(
                cmd_nvenc,
                cwd=str(out_file.parent),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                encoder_used = "h264_nvenc"
            else:
                res = None

        if res is None:
            cmd_cpu = _build_cmd(use_nvenc=False)
            res = subprocess.run(
                cmd_cpu,
                cwd=str(out_file.parent),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0 or not out_file.exists() or out_file.stat().st_size == 0:
                raise RuntimeError(
                    f"FFmpeg render failed (exit {res.returncode}):\n{(res.stderr or '')[-1500:]}"
                )

        elapsed = round(time.perf_counter() - t0, 2)
        return {
            "output_path": str(out_file),
            "file_size_bytes": out_file.stat().st_size,
            "duration_sec": project.total_duration_sec,
            "clips_rendered": len(schedule),
            "subtitles_burned": bool(burn_subtitles and has_subs),
            "srt_path": str(srt_path) if has_subs else None,
            "ass_path": str(ass_path) if has_subs else None,
            "encoder": encoder_used,
            "render_time_sec": elapsed,
        }
    finally:
        for tmp_f in (temp_ass_path, temp_fg_path, *extra_temp_files):
            if tmp_f is not None:
                try:
                    tmp_f.unlink(missing_ok=True)
                except Exception:
                    pass
