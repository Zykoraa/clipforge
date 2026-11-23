"""Subtitle projection, caption chunking, and SRT / ASS (with word-highlight) export."""

from __future__ import annotations

from pathlib import Path

from .models import (
    ProjectState,
    SubtitleEntry,
    SubtitleStyle,
    WordToken,
    new_id,
    sanitize_font_name,
    sanitize_single_line,
)


def hex_to_ass_color(hex_color: str, opacity: float = 1.0) -> str:
    """Convert '#RRGGBB' + opacity (1.0=opaque, 0.0=transparent) to ASS '&HAABBGGRR'."""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or not all(c in "0123456789abcdefABCDEF" for c in h):
        h = "FFFFFF"
    r, g, b = h[0:2].upper(), h[2:4].upper(), h[4:6].upper()
    alpha = int(round((1.0 - max(0.0, min(1.0, opacity))) * 255))
    return f"&H{alpha:02X}{b}{g}{r}"


def format_srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_ass_timestamp_cs(total_cs: int) -> str:
    total_cs = max(0, int(total_cs))
    cs = total_cs % 100
    total_sec = total_cs // 100
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def format_ass_timestamp(seconds: float) -> str:
    return format_ass_timestamp_cs(int(round(max(0.0, seconds) * 100)))


def escape_ass_text(text: str) -> str:
    """Escape text safely for libass without producing invalid '\\\\' escapes or override injection."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # Insert zero-width space after literal backslashes so '\N', '\n', '\h' are never interpreted as ASS controls
    escaped = (
        normalized.replace("\\", "\\\u200b")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )
    return escaped


def project_timeline_subtitles(
    project: ProjectState,
    max_words_per_caption: int | None = None,
    pause_threshold_sec: float = 0.45,
) -> list[SubtitleEntry]:
    """Project per-media cached word/segment transcripts onto the current timeline schedule.

    Automatically accounts for clip in_sec, out_sec, speed, and xfade transition overlaps.
    """
    max_words = max_words_per_caption or project.subtitle_style.max_words_per_caption
    max_words = max(1, min(20, max_words))
    schedule = project.compute_timeline_schedule()
    entries: list[SubtitleEntry] = []

    for item in schedule:
        clip = item.clip
        if clip.muted or clip.volume <= 0.0:
            continue
        media = project.get_media(clip.media_id)
        if not media or not media.transcript:
            continue

        spd = max(0.1, clip.speed)
        in_s, out_s = clip.in_sec, clip.out_sec
        tl_start = item.timeline_start_sec

        projected_words: list[WordToken] = []
        for seg in media.transcript:
            if seg.end_sec <= in_s or seg.start_sec >= out_s:
                continue

            if seg.words:
                for w in seg.words:
                    if w.end_sec <= in_s or w.start_sec >= out_s:
                        continue
                    w_start = max(in_s, w.start_sec)
                    w_end = min(out_s, w.end_sec)
                    if w_end - w_start < 0.02:
                        continue
                    tl_w_start = round(tl_start + (w_start - in_s) / spd, 3)
                    tl_w_end = round(tl_start + (w_end - in_s) / spd, 3)
                    if tl_w_end <= tl_w_start:
                        tl_w_end = round(tl_w_start + 0.08, 3)
                    clean_word = w.word.strip()
                    if clean_word:
                        projected_words.append(
                            WordToken(
                                word=clean_word,
                                start_sec=tl_w_start,
                                end_sec=tl_w_end,
                                probability=w.probability,
                            )
                        )
            else:
                s_start = max(in_s, seg.start_sec)
                s_end = min(out_s, seg.end_sec)
                raw_words = [tok for tok in seg.text.strip().split() if tok]
                if not raw_words or s_end <= s_start:
                    continue
                tl_seg_start = tl_start + (s_start - in_s) / spd
                tl_seg_end = tl_start + (s_end - in_s) / spd
                step = (tl_seg_end - tl_seg_start) / len(raw_words)
                for i, tok in enumerate(raw_words):
                    projected_words.append(
                        WordToken(
                            word=tok,
                            start_sec=round(tl_seg_start + i * step, 3),
                            end_sec=round(tl_seg_start + (i + 1) * step, 3),
                        )
                    )

        current_chunk: list[WordToken] = []
        for w in projected_words:
            if current_chunk:
                gap = w.start_sec - current_chunk[-1].end_sec
                prev_word = current_chunk[-1].word
                ends_sentence = prev_word.endswith((".", "!", "?", ":", ";"))
                ends_clause = prev_word.endswith(",") and len(current_chunk) >= max(2, max_words - 1)
                if (
                    len(current_chunk) >= max_words
                    or gap >= pause_threshold_sec
                    or ends_sentence
                    or ends_clause
                ):
                    entries.append(_chunk_to_entry(current_chunk, clip.id))
                    current_chunk = []
            current_chunk.append(w)

        if current_chunk:
            entries.append(_chunk_to_entry(current_chunk, clip.id))

    # Clamp consecutive subtitle blocks AND their nested word tokens so nothing overlaps
    entries.sort(key=lambda e: e.start_sec)
    for i in range(len(entries) - 1):
        if entries[i].end_sec > entries[i + 1].start_sec:
            clamped_end = round(max(entries[i].start_sec + 0.05, entries[i + 1].start_sec - 0.01), 3)
            entries[i].end_sec = clamped_end
            for w in entries[i].words:
                if w.start_sec > clamped_end:
                    w.start_sec = clamped_end
                if w.end_sec > clamped_end:
                    w.end_sec = clamped_end

    return entries


def _chunk_to_entry(words: list[WordToken], clip_id: str) -> SubtitleEntry:
    text = " ".join(w.word for w in words)
    return SubtitleEntry(
        id=new_id("sub"),
        start_sec=words[0].start_sec,
        end_sec=max(words[-1].end_sec, round(words[0].start_sec + 0.25, 3)),
        text=text,
        words=words,
        clip_id=clip_id,
    )


def generate_srt(subtitles: list[SubtitleEntry], style: SubtitleStyle | None = None) -> str:
    lines: list[str] = []
    upper = style.uppercase if style else False
    for idx, sub in enumerate(sorted(subtitles, key=lambda s: s.start_sec), start=1):
        txt = sub.text.strip()
        if not txt:
            continue
        if upper:
            txt = txt.upper()
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(sub.start_sec)} --> {format_srt_timestamp(sub.end_sec)}")
        lines.append(txt)
        lines.append("")
    return "\n".join(lines)


def generate_ass(project: ProjectState) -> str:
    """Generate a complete Advanced SubStation Alpha (.ass) file with non-overlapping word-by-word highlight."""
    st = project.subtitle_style
    play_res_x = project.width
    play_res_y = project.height

    # Scale typography against short edge (min(W, H) / 1080) so landscape 16:9 and portrait 9:16 stay balanced
    short_edge_scale = min(play_res_x, play_res_y) / 1080.0
    height_scale = play_res_y / 1080.0

    font_size = max(16, int(round(st.font_size * short_edge_scale)))
    margin_v = int(round(st.margin_v * height_scale))
    margin_lr = max(24, int(round(play_res_x * 0.045)))
    outline_w = round(st.outline_width * short_edge_scale, 2)
    shadow_d = round(st.shadow_depth * short_edge_scale, 2)

    pri_ass = hex_to_ass_color(st.primary_color, 1.0)
    hi_ass = hex_to_ass_color(st.highlight_color, 1.0)
    out_ass = hex_to_ass_color(st.outline_color, 1.0)
    back_ass = hex_to_ass_color(st.back_color, st.back_opacity)

    border_style = 3 if st.back_opacity > 0.05 else 1
    bold_flag = -1 if st.bold else 0
    italic_flag = -1 if st.italic else 0
    safe_title = sanitize_single_line(project.name)
    safe_font = sanitize_font_name(st.font_name)
    safe_align = st.alignment if 1 <= st.alignment <= 9 else 2

    header = f"""[Script Info]
Title: {safe_title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{safe_font},{font_size},{pri_ass},{hi_ass},{out_ass},{back_ass},{bold_flag},{italic_flag},0,0,100,100,0,0,{border_style},{outline_w},{shadow_d},{safe_align},{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    sorted_subs = sorted(project.subtitles, key=lambda s: s.start_sec)
    global_cursor_cs = 0

    for sub in sorted_subs:
        raw_text = sub.text.strip()
        if not raw_text or sub.end_sec <= sub.start_sec:
            continue

        sub_start_cs = max(global_cursor_cs, int(round(max(0.0, sub.start_sec) * 100)))
        sub_end_cs = int(round(max(0.0, sub.end_sec) * 100))
        if sub_end_cs <= sub_start_cs:
            continue

        if st.word_highlight and sub.words and len(sub.words) >= 1:
            words = sub.words
            n_words = len(words)
            cursor_cs = sub_start_cs

            for idx, w in enumerate(words):
                s_cs = sub_start_cs if idx == 0 else max(cursor_cs, int(round(w.start_sec * 100)))
                if idx == n_words - 1:
                    e_cs = sub_end_cs
                else:
                    next_start_cs = int(round(words[idx + 1].start_sec * 100))
                    e_cs = min(sub_end_cs, next_start_cs)

                if e_cs <= s_cs:
                    continue

                rendered_tokens: list[str] = []
                for j, tok in enumerate(words):
                    tok_str = tok.word.upper() if st.uppercase else tok.word
                    esc = escape_ass_text(tok_str)
                    if j == idx:
                        rendered_tokens.append(
                            f"{{\\1c{hi_ass}\\fscx108\\fscy108}}{esc}{{\\1c{pri_ass}\\fscx100\\fscy100}}"
                        )
                    else:
                        rendered_tokens.append(esc)

                line_text = " ".join(rendered_tokens)
                events.append(
                    f"Dialogue: 0,{format_ass_timestamp_cs(s_cs)},{format_ass_timestamp_cs(e_cs)},Default,,0,0,0,,{line_text}"
                )
                cursor_cs = e_cs
            global_cursor_cs = max(global_cursor_cs, cursor_cs)
        else:
            disp = raw_text.upper() if st.uppercase else raw_text
            esc = escape_ass_text(disp)
            events.append(
                f"Dialogue: 0,{format_ass_timestamp_cs(sub_start_cs)},{format_ass_timestamp_cs(sub_end_cs)},Default,,0,0,0,,{esc}"
            )
            global_cursor_cs = max(global_cursor_cs, sub_end_cs)

    return header + "\n".join(events) + "\n"


def write_subtitle_file(project: ProjectState, output_path: str | Path, fmt: str = "ass") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt.lower() == "srt":
        out.write_text(generate_srt(project.subtitles, project.subtitle_style), encoding="utf-8")
    else:
        out.write_text(generate_ass(project), encoding="utf-8")
    return out
