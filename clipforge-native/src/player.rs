use crate::models::{MediaItem, MemeLayout, ProjectSummary, ScheduleItem, SubtitleEntry, SubtitleStyle};
use crate::theme::{parse_hex_color, BG_ROOT};
use egui::{Align2, Color32, ColorImage, Context, FontId, Pos2, Rect, Stroke, TextureHandle, TextureOptions, Vec2};
use std::collections::HashMap;
use std::io::Read;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[derive(Clone, PartialEq)]
struct ScrubKey {
    media_path: String,
    bucket_ms: i64,
    width: u32,
    height: u32,
}

struct ActiveStream {
    clip_id: String,
    stop_flag: Arc<AtomicBool>,
}

/// Native GPU Video Player & Compositor:
/// - Instant disk decode for static images
/// - Coalesced FFmpeg frame decoder for smooth zero-flash scrubbing
/// - Real-time FFmpeg RGBA pipe + native rodio WASAPI/ALSA audio playback
/// - Native GPU egui::Painter vector overlays for Karaoke Subtitles & Meme Layouts
pub struct NativeVideoPlayer {
    current_tex: Option<TextureHandle>,
    static_cache: HashMap<String, TextureHandle>,
    last_scrub_key: Option<ScrubKey>,
    scrub_req: Arc<Mutex<Option<(ScrubKey, f64)>>>,
    decoded_frame: Arc<Mutex<Option<ColorImage>>>,
    active_stream: Option<ActiveStream>,
    single_video_path: String,
    pub single_video_dur: f64,
    pub is_playing: bool,
    pub playhead_sec: f64,
    last_tick: Instant,
}

impl NativeVideoPlayer {
    pub fn new(ctx: Context) -> Self {
        let scrub_req: Arc<Mutex<Option<(ScrubKey, f64)>>> = Arc::new(Mutex::new(None));
        let decoded_frame: Arc<Mutex<Option<ColorImage>>> = Arc::new(Mutex::new(None));

        // Background coalescing single-frame scrub decoder
        {
            let scrub_req = Arc::clone(&scrub_req);
            let decoded_frame = Arc::clone(&decoded_frame);
            let ctx = ctx.clone();
            std::thread::spawn(move || loop {
                let job = { scrub_req.lock().ok().and_then(|mut g| g.take()) };
                if let Some((key, sec)) = job {
                    if let Some(ci) = decode_single_video_frame(&key.media_path, sec, key.width, key.height) {
                        if let Ok(mut out) = decoded_frame.lock() {
                            *out = Some(ci);
                        }
                        ctx.request_repaint();
                    }
                } else {
                    std::thread::sleep(Duration::from_millis(16));
                }
            });
        }

        Self {
            current_tex: None,
            static_cache: HashMap::new(),
            last_scrub_key: None,
            scrub_req,
            decoded_frame,
            active_stream: None,
            single_video_path: String::new(),
            single_video_dur: 0.0,
            is_playing: false,
            playhead_sec: 0.0,
            last_tick: Instant::now(),
        }
    }

    pub fn select_single_video(&mut self, path: &str, duration_sec: f64, autoplay: bool) {
        if self.single_video_path != path {
            self.stop_playback();
            self.single_video_path = path.to_string();
            self.single_video_dur = duration_sec.max(0.5);
            self.playhead_sec = 0.0;
            self.last_scrub_key = None;
            self.current_tex = None;
            if autoplay {
                self.is_playing = true;
                self.last_tick = Instant::now();
            }
        } else {
            self.single_video_dur = duration_sec.max(0.5);
        }
    }

    pub fn tick_single_video(
        &mut self,
        ctx: &Context,
        path: &str,
        width: u32,
        height: u32,
        duration_sec: f64,
    ) {
        let dur = duration_sec.max(0.5);
        if self.single_video_path != path {
            self.select_single_video(path, dur, true);
        } else {
            self.single_video_dur = dur;
        }

        let now = Instant::now();
        let dt = now.duration_since(self.last_tick).as_secs_f64().min(0.1);
        self.last_tick = now;

        if let Ok(mut g) = self.decoded_frame.lock() {
            if let Some(ci) = g.take() {
                match &mut self.current_tex {
                    Some(tex) => tex.set(ci, TextureOptions::LINEAR),
                    None => {
                        self.current_tex =
                            Some(ctx.load_texture("video_viewport", ci, TextureOptions::LINEAR));
                    }
                }
            }
        }

        if self.is_playing {
            self.playhead_sec += dt;
            if self.playhead_sec >= dur {
                self.playhead_sec = dur;
                self.stop_playback();
            } else {
                ctx.request_repaint();
            }
        }

        let (pw, ph) = preview_dims(width.max(320), height.max(320));
        let source_sec = self.playhead_sec.clamp(0.0, dur);

        if self.is_playing {
            let clip_key = format!("single::{path}");
            let need_new = match &self.active_stream {
                Some(st) => st.clip_id != clip_key || st.stop_flag.load(Ordering::Relaxed),
                None => true,
            };
            if need_new {
                if let Some(st) = self.active_stream.take() {
                    st.stop_flag.store(true, Ordering::SeqCst);
                }
                let stop_flag = Arc::new(AtomicBool::new(false));
                let media = MediaItem {
                    id: clip_key.clone(),
                    path: path.to_string(),
                    has_video: true,
                    has_audio: true,
                    duration_sec: dur,
                    width: pw,
                    height: ph,
                    ..Default::default()
                };
                let clip = ScheduleItem {
                    clip_id: clip_key.clone(),
                    in_sec: 0.0,
                    out_sec: dur,
                    speed: 1.0,
                    volume: 1.0,
                    muted: false,
                    ..Default::default()
                };
                spawn_playback_stream(
                    media,
                    clip,
                    source_sec,
                    pw,
                    ph,
                    Arc::clone(&stop_flag),
                    Arc::clone(&self.decoded_frame),
                    ctx.clone(),
                );
                self.active_stream = Some(ActiveStream {
                    clip_id: clip_key,
                    stop_flag,
                });
            }
        } else {
            let bucket_ms = (source_sec * 25.0).round() as i64 * 40;
            let key = ScrubKey {
                media_path: path.to_string(),
                bucket_ms,
                width: pw,
                height: ph,
            };
            if self.last_scrub_key.as_ref() != Some(&key) {
                self.last_scrub_key = Some(key.clone());
                if let Ok(mut g) = self.scrub_req.lock() {
                    *g = Some((key, source_sec));
                }
            }
        }
    }

    pub fn paint_single_frame(&self, painter: &egui::Painter, rect: Rect) -> bool {
        if let Some(tex) = &self.current_tex {
            let tsz = tex.size_vec2();
            if tsz.x > 0.0 && tsz.y > 0.0 {
                let sc = ((rect.width() - 24.0).max(80.0) / tsz.x)
                    .min((rect.height() - 24.0).max(80.0) / tsz.y);
                let draw_rect = Rect::from_center_size(rect.center(), tsz * sc);
                painter.image(
                    tex.id(),
                    draw_rect,
                    Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)),
                    Color32::WHITE,
                );
                return true;
            }
        }
        false
    }

    pub fn stop_playback(&mut self) {
        self.is_playing = false;
        if let Some(st) = self.active_stream.take() {
            st.stop_flag.store(true, Ordering::SeqCst);
        }
    }

    pub fn seek_to(&mut self, sec: f64, total_dur: f64) {
        let was_playing = self.is_playing;
        self.stop_playback();
        self.playhead_sec = sec.clamp(0.0, total_dur.max(0.0));
        self.last_scrub_key = None;
        if was_playing && total_dur > 0.0 {
            self.is_playing = true;
            self.last_tick = Instant::now();
        }
    }

    pub fn toggle_play(&mut self, total_dur: f64) {
        if total_dur <= 0.0 {
            self.stop_playback();
            return;
        }
        if self.is_playing {
            self.stop_playback();
        } else {
            if self.playhead_sec >= total_dur - 0.05 {
                self.playhead_sec = 0.0;
            }
            self.is_playing = true;
            self.last_tick = Instant::now();
        }
    }

    pub fn tick(&mut self, ctx: &Context, summary: &ProjectSummary) {
        let now = Instant::now();
        let dt = now.duration_since(self.last_tick).as_secs_f64().min(0.1);
        self.last_tick = now;

        // Upload any newly decoded frame from background thread onto the GPU wgpu texture
        if let Ok(mut g) = self.decoded_frame.lock() {
            if let Some(ci) = g.take() {
                match &mut self.current_tex {
                    Some(tex) => tex.set(ci, TextureOptions::LINEAR),
                    None => {
                        self.current_tex =
                            Some(ctx.load_texture("video_viewport", ci, TextureOptions::LINEAR));
                    }
                }
            }
        }

        if self.is_playing {
            self.playhead_sec += dt;
            if self.playhead_sec >= summary.total_duration_sec {
                self.playhead_sec = summary.total_duration_sec;
                self.stop_playback();
            } else {
                ctx.request_repaint();
            }
        }

        let active = active_clip_at(&summary.schedule, self.playhead_sec);
        let Some(clip) = active else {
            if self.active_stream.is_some() {
                self.stop_playback();
            }
            return;
        };
        let Some(media) = summary.project.media_bin.iter().find(|m| m.id == clip.media_id) else {
            return;
        };

        let (pw, ph) = preview_dims(summary.project.width, summary.project.height);
        let local_offset = (self.playhead_sec - clip.timeline_start_sec).max(0.0) * clip.speed.max(0.1);
        let source_sec = (clip.in_sec + local_offset).clamp(clip.in_sec, clip.out_sec);

        if media.is_image {
            if let Some(st) = self.active_stream.take() {
                st.stop_flag.store(true, Ordering::SeqCst);
            }
            if !self.static_cache.contains_key(&media.id) {
                if let Ok(img) = image::open(&media.path) {
                    let thumb = img.thumbnail(1080, 1080).to_rgba8();
                    let ci = ColorImage::from_rgba_unmultiplied(
                        [thumb.width() as usize, thumb.height() as usize],
                        thumb.as_raw(),
                    );
                    let tex = ctx.load_texture(format!("static_{}", media.id), ci, TextureOptions::LINEAR);
                    self.static_cache.insert(media.id.clone(), tex);
                }
            }
            return;
        }

        if !media.has_video {
            return;
        }

        if self.is_playing {
            let need_new = match &self.active_stream {
                Some(st) => st.clip_id != clip.clip_id || st.stop_flag.load(Ordering::Relaxed),
                None => true,
            };
            if need_new {
                if let Some(st) = self.active_stream.take() {
                    st.stop_flag.store(true, Ordering::SeqCst);
                }
                let stop_flag = Arc::new(AtomicBool::new(false));
                spawn_playback_stream(
                    media.clone(),
                    clip.clone(),
                    source_sec,
                    pw,
                    ph,
                    Arc::clone(&stop_flag),
                    Arc::clone(&self.decoded_frame),
                    ctx.clone(),
                );
                self.active_stream = Some(ActiveStream {
                    clip_id: clip.clip_id.clone(),
                    stop_flag,
                });
            }
        } else {
            // Paused scrubbing: coalesced 40ms-bucket single-frame FFmpeg decode
            let bucket_ms = (source_sec * 25.0).round() as i64 * 40;
            let key = ScrubKey {
                media_path: media.path.clone(),
                bucket_ms,
                width: pw,
                height: ph,
            };
            if self.last_scrub_key.as_ref() != Some(&key) {
                self.last_scrub_key = Some(key.clone());
                if let Ok(mut g) = self.scrub_req.lock() {
                    *g = Some((key, source_sec));
                }
            }
        }
    }

    pub fn paint_viewport(&self, ui: &mut egui::Ui, summary: &ProjectSummary) {
        let avail = ui.available_size();
        let proj_w = summary.project.width.max(16) as f32;
        let proj_h = summary.project.height.max(16) as f32;
        let aspect = proj_w / proj_h;

        let max_w = (avail.x - 16.0).max(160.0);
        let max_h = (avail.y - 12.0).max(120.0);
        let (disp_w, disp_h) = if max_w / max_h > aspect {
            (max_h * aspect, max_h)
        } else {
            (max_w, max_w / aspect)
        };

        let (outer_rect, _) = ui.allocate_exact_size(avail, egui::Sense::hover());
        let painter = ui.painter();
        painter.rect_filled(outer_rect, 6.0, BG_ROOT);

        let canvas_rect = Rect::from_center_size(outer_rect.center(), Vec2::new(disp_w, disp_h));
        let bg = parse_hex_color(&summary.project.bg_color, Color32::BLACK);
        painter.rect_filled(canvas_rect, 4.0, bg);
        painter.rect_stroke(
            canvas_rect,
            4.0,
            Stroke::new(1.0_f32, Color32::from_rgb(48, 58, 84)),
            egui::StrokeKind::Outside,
        );

        let active = active_clip_at(&summary.schedule, self.playhead_sec);
        let tex_to_draw: Option<&TextureHandle> = if let Some(clip) = active {
            if let Some(media) = summary.project.media_bin.iter().find(|m| m.id == clip.media_id) {
                if media.is_image {
                    self.static_cache.get(&media.id)
                } else {
                    self.current_tex.as_ref()
                }
            } else {
                self.current_tex.as_ref()
            }
        } else {
            None
        };

        if let Some(tex) = tex_to_draw {
            let tsz = tex.size_vec2();
            if tsz.x > 0.0 && tsz.y > 0.0 {
                let scale = (canvas_rect.width() / tsz.x).min(canvas_rect.height() / tsz.y);
                let draw_rect = Rect::from_center_size(canvas_rect.center(), tsz * scale);
                let mut tint = Color32::WHITE;
                // Smooth fadeblack / fadewhite transition visual feedback
                if let Some(clip) = active {
                    if let Some(ref tr) = clip.applied_transition {
                        let td = clip.applied_transition_duration;
                        if td > 0.0 && self.playhead_sec < clip.timeline_start_sec + td {
                            let p = ((self.playhead_sec - clip.timeline_start_sec) / td).clamp(0.0, 1.0) as f32;
                            if tr == "fadeblack" {
                                let v = (p * 255.0) as u8;
                                tint = Color32::from_rgb(v, v, v);
                            } else if tr == "crossfade" || tr == "dissolve" {
                                tint = Color32::from_rgba_unmultiplied(255, 255, 255, (p * 255.0) as u8);
                            }
                        }
                    }
                }
                painter.image(
                    tex.id(),
                    draw_rect,
                    Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)),
                    tint,
                );
            }
        } else if summary.schedule.is_empty() {
            painter.text(
                canvas_rect.center(),
                Align2::CENTER_CENTER,
                "Drop video/image clips or generate with AI Studio",
                FontId::proportional(14.0),
                Color32::from_rgb(120, 134, 160),
            );
        }

        // Native GPU Meme Layout Overlay
        paint_meme_layout(painter, canvas_rect, &summary.project.meme_layout);

        // Native GPU Word-Highlighted Karaoke Subtitles
        paint_subtitles(
            painter,
            canvas_rect,
            &summary.project.subtitles,
            &summary.project.subtitle_style,
            self.playhead_sec,
        );
    }
}

impl Drop for NativeVideoPlayer {
    fn drop(&mut self) {
        self.stop_playback();
    }
}

pub fn active_clip_at(schedule: &[ScheduleItem], t: f64) -> Option<&ScheduleItem> {
    if schedule.is_empty() {
        return None;
    }
    for (i, s) in schedule.iter().enumerate() {
        let is_last = i + 1 == schedule.len();
        if t >= s.timeline_start_sec && (t < s.timeline_end_sec || (is_last && t <= s.timeline_end_sec + 0.005)) {
            return Some(s);
        }
    }
    if t <= 0.0 {
        schedule.first()
    } else {
        schedule.last()
    }
}

fn preview_dims(proj_w: u32, proj_h: u32) -> (u32, u32) {
    let aspect = (proj_w.max(16) as f32) / (proj_h.max(16) as f32);
    let (w, h) = if aspect >= 1.0 {
        (640u32, ((640.0 / aspect).round() as u32).max(160))
    } else {
        (((640.0 * aspect).round() as u32).max(160), 640u32)
    };
    ((w / 2) * 2, (h / 2) * 2)
}

fn decode_single_video_frame(path: &str, sec: f64, w: u32, h: u32) -> Option<ColorImage> {
    let vf = format!(
        "scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
    );
    let mut cmd = Command::new("ffmpeg");
    cmd.args([
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        &format!("{sec:.3}"),
        "-i",
        path,
        "-frames:v",
        "1",
        "-vf",
        &vf,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-",
    ])
    .stdin(Stdio::null())
    .stdout(Stdio::piped())
    .stderr(Stdio::null());

    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000);

    let out = cmd.output().ok()?;
    let expected = (w as usize) * (h as usize) * 4;
    if out.stdout.len() < expected {
        return None;
    }
    Some(ColorImage::from_rgba_unmultiplied(
        [w as usize, h as usize],
        &out.stdout[..expected],
    ))
}

#[allow(clippy::too_many_arguments)]
fn spawn_playback_stream(
    media: MediaItem,
    clip: ScheduleItem,
    start_sec: f64,
    w: u32,
    h: u32,
    stop_flag: Arc<AtomicBool>,
    decoded_frame: Arc<Mutex<Option<ColorImage>>>,
    ctx: Context,
) {
    let fps = 24.0_f64;
    let speed = clip.speed.clamp(0.25, 4.0);
    let clip_remaining = ((clip.out_sec - start_sec).max(0.05)) / speed;

    // Audio stream thread (native WASAPI/ALSA via rodio)
    if media.has_audio && !clip.muted && clip.volume > 0.01 {
        let path_a = media.path.clone();
        let stop_a = Arc::clone(&stop_flag);
        let vol = clip.volume.clamp(0.0, 2.0) as f32;
        std::thread::spawn(move || {
            let mut cmd = Command::new("ffmpeg");
            cmd.args([
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                &format!("{start_sec:.3}"),
                "-t",
                &format!("{:.3}", (clip.out_sec - start_sec).max(0.05)),
                "-i",
                &path_a,
                "-vn",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-f",
                "wav",
                "-",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
            #[cfg(windows)]
            cmd.creation_flags(0x0800_0000);

            if let Ok(out) = cmd.output() {
                if stop_a.load(Ordering::Relaxed) || out.stdout.len() < 64 {
                    return;
                }
                if let Ok((_stream, handle)) = rodio::OutputStream::try_default() {
                    if let Ok(sink) = rodio::Sink::try_new(&handle) {
                        sink.set_volume(vol);
                        if let Ok(src) = rodio::Decoder::new_wav(std::io::Cursor::new(out.stdout)) {
                            sink.append(src);
                            while !sink.empty() && !stop_a.load(Ordering::Relaxed) {
                                std::thread::sleep(Duration::from_millis(25));
                            }
                            sink.stop();
                        }
                    }
                }
            }
        });
    }

    // Video RGBA pipe thread
    std::thread::spawn(move || {
        let vf = format!(
            "scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setpts=PTS/{speed:.3}"
        );
        let mut cmd = Command::new("ffmpeg");
        cmd.args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            &format!("{start_sec:.3}"),
            "-t",
            &format!("{:.3}", (clip.out_sec - start_sec).max(0.05)),
            "-i",
            &media.path,
            "-vf",
            &vf,
            "-r",
            &format!("{fps:.1}"),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
        #[cfg(windows)]
        cmd.creation_flags(0x0800_0000);

        let mut child: Child = match cmd.spawn() {
            Ok(c) => c,
            Err(_) => return,
        };
        let Some(mut stdout) = child.stdout.take() else {
            let _ = child.kill();
            let _ = child.wait();
            return;
        };

        let frame_bytes = (w as usize) * (h as usize) * 4;
        let mut buf = vec![0u8; frame_bytes];
        let frame_dt = Duration::from_secs_f64(1.0 / fps);
        let t0 = Instant::now();
        let mut frame_idx = 0u64;

        while !stop_flag.load(Ordering::Relaxed) {
            if t0.elapsed().as_secs_f64() > clip_remaining + 0.5 {
                break;
            }
            if stdout.read_exact(&mut buf).is_err() {
                break;
            }
            let ci = ColorImage::from_rgba_unmultiplied([w as usize, h as usize], &buf);
            if let Ok(mut g) = decoded_frame.lock() {
                *g = Some(ci);
            }
            ctx.request_repaint();
            frame_idx += 1;
            let target = frame_dt.mul_f64(frame_idx as f64);
            if let Some(sleep_d) = target.checked_sub(t0.elapsed()) {
                std::thread::sleep(sleep_d.min(Duration::from_millis(50)));
            }
        }
        let _ = child.kill();
        let _ = child.wait();
        stop_flag.store(true, Ordering::SeqCst);
    });
}

fn paint_outlined_text(
    painter: &egui::Painter,
    pos: Pos2,
    align: Align2,
    text: &str,
    font: FontId,
    fg: Color32,
    outline: Color32,
    outline_px: f32,
) {
    let r = outline_px.clamp(1.0, 4.0);
    for (dx, dy) in [(-r, -r), (r, -r), (-r, r), (r, r), (0.0, r), (0.0, -r), (r, 0.0), (-r, 0.0)] {
        painter.text(pos + Vec2::new(dx, dy), align, text, font.clone(), outline);
    }
    painter.text(pos, align, text, font, fg);
}

fn paint_subtitles(
    painter: &egui::Painter,
    rect: Rect,
    subs: &[SubtitleEntry],
    st: &SubtitleStyle,
    t: f64,
) {
    let Some(sub) = subs.iter().find(|s| t >= s.start_sec && t <= s.end_sec) else {
        return;
    };
    let short_edge = rect.width().min(rect.height());
    let scale = short_edge / 1080.0;
    let font_px = ((st.font_size as f32) * scale).clamp(13.0, 48.0);
    let outline_px = (st.outline_width * scale).clamp(1.2, 4.0);
    let margin_y = ((st.margin_v as f32) / 1080.0) * rect.height();

    let center_y = match st.alignment {
        8 => rect.top() + margin_y.max(font_px),
        5 => rect.center().y,
        _ => rect.bottom() - margin_y.max(font_px),
    };

    let pri = parse_hex_color(&st.primary_color, Color32::WHITE);
    let hi = parse_hex_color(&st.highlight_color, Color32::from_rgb(0, 255, 102));
    let out = parse_hex_color(&st.outline_color, Color32::BLACK);
    let font = FontId::proportional(font_px);

    let active_word_idx = if st.word_highlight && !sub.words.is_empty() {
        sub.words
            .iter()
            .position(|w| t >= w.start_sec && t <= w.end_sec)
            .or_else(|| sub.words.iter().rposition(|w| t >= w.start_sec))
    } else {
        None
    };

    let display_text = if st.uppercase {
        sub.text.to_uppercase()
    } else {
        sub.text.clone()
    };

    if st.back_opacity > 0.05 {
        let galley = painter.layout_no_wrap(display_text.clone(), font.clone(), pri);
        let bg_rect = Rect::from_center_size(
            Pos2::new(rect.center().x, center_y),
            galley.size() + Vec2::new(16.0, 8.0),
        );
        painter.rect_filled(
            bg_rect,
            6.0,
            Color32::from_rgba_unmultiplied(9, 9, 11, (st.back_opacity.clamp(0.0, 1.0) * 255.0) as u8),
        );
    }

    if let Some(hi_idx) = active_word_idx {
        // Measure each word to lay out centered horizontal karaoke row cleanly
        let words: Vec<String> = sub
            .words
            .iter()
            .map(|w| if st.uppercase { w.word.to_uppercase() } else { w.word.clone() })
            .collect();
        let space_w = painter.layout_no_wrap(" ".into(), font.clone(), pri).size().x;
        let widths: Vec<f32> = words
            .iter()
            .map(|w| painter.layout_no_wrap(w.clone(), font.clone(), pri).size().x)
            .collect();
        let total_w: f32 = widths.iter().sum::<f32>() + space_w * (words.len().saturating_sub(1) as f32);
        let mut x = rect.center().x - total_w * 0.5;
        for (idx, w) in words.iter().enumerate() {
            let color = if idx == hi_idx { hi } else { pri };
            let f = if idx == hi_idx {
                FontId::proportional(font_px * 1.08)
            } else {
                font.clone()
            };
            paint_outlined_text(
                painter,
                Pos2::new(x, center_y),
                Align2::LEFT_CENTER,
                w,
                f,
                color,
                out,
                outline_px,
            );
            x += widths[idx] + space_w;
        }
    } else {
        paint_outlined_text(
            painter,
            Pos2::new(rect.center().x, center_y),
            Align2::CENTER_CENTER,
            &display_text,
            font,
            pri,
            out,
            outline_px,
        );
    }
}

fn paint_meme_layout(painter: &egui::Painter, rect: Rect, ml: &MemeLayout) {
    let short_edge = rect.width().min(rect.height());
    match ml.template.as_str() {
        "pov_top_bar" | "pov_dark_bar" => {
            let bar_h = (rect.height() * 0.14).max(26.0);
            let bar = Rect::from_min_size(rect.min, Vec2::new(rect.width(), bar_h));
            let dark = ml.template == "pov_dark_bar";
            painter.rect_filled(bar, 0.0, if dark { Color32::from_rgb(15, 17, 23) } else { Color32::WHITE });
            painter.text(
                bar.center(),
                Align2::CENTER_CENTER,
                &ml.top_text,
                FontId::proportional((short_edge * 0.052).clamp(11.0, 26.0)),
                if dark { Color32::WHITE } else { Color32::BLACK },
            );
        }
        "impact_top_bottom" => {
            let f = FontId::proportional((short_edge * 0.082).clamp(14.0, 38.0));
            if !ml.top_text.is_empty() {
                paint_outlined_text(
                    painter,
                    Pos2::new(rect.center().x, rect.top() + rect.height() * 0.09),
                    Align2::CENTER_CENTER,
                    &ml.top_text.to_uppercase(),
                    f.clone(),
                    Color32::WHITE,
                    Color32::BLACK,
                    2.5,
                );
            }
            if !ml.bottom_text.is_empty() {
                paint_outlined_text(
                    painter,
                    Pos2::new(rect.center().x, rect.bottom() - rect.height() * 0.09),
                    Align2::CENTER_CENTER,
                    &ml.bottom_text.to_uppercase(),
                    f,
                    Color32::WHITE,
                    Color32::BLACK,
                    2.5,
                );
            }
        }
        "breaking_news" => {
            let h = (rect.height() * 0.15).max(36.0);
            let box_rect = Rect::from_min_max(
                Pos2::new(rect.left() + 8.0, rect.bottom() - h - 8.0),
                Pos2::new(rect.right() - 8.0, rect.bottom() - 8.0),
            );
            painter.rect_filled(box_rect, 4.0, Color32::from_rgba_unmultiplied(185, 28, 28, 235));
            let label = if ml.banner_label.is_empty() { "BREAKING NEWS" } else { &ml.banner_label };
            painter.text(
                Pos2::new(box_rect.left() + 8.0, box_rect.top() + 8.0),
                Align2::LEFT_TOP,
                label,
                FontId::proportional((short_edge * 0.032).clamp(9.0, 14.0)),
                Color32::from_rgb(254, 240, 138),
            );
            painter.text(
                Pos2::new(box_rect.left() + 8.0, box_rect.center().y + 4.0),
                Align2::LEFT_CENTER,
                &ml.top_text,
                FontId::proportional((short_edge * 0.042).clamp(11.0, 18.0)),
                Color32::WHITE,
            );
        }
        "bodycam_hud" => {
            let hud_pos = Pos2::new(rect.right() - 10.0, rect.top() + 10.0);
            let f = FontId::monospace((short_edge * 0.032).clamp(9.0, 15.0));
            let l1 = if ml.banner_label.is_empty() { "● AXON BODY 4 REC" } else { &ml.banner_label };
            let l2 = if ml.top_text.is_empty() { "2026-11-24 02:14:09" } else { &ml.top_text };
            let l3 = if ml.bottom_text.is_empty() { "UNIT 406 X6039A8B" } else { &ml.bottom_text };
            painter.text(hud_pos, Align2::RIGHT_TOP, format!("{l1}\n{l2}\n{l3}"), f, Color32::from_rgb(241, 245, 249));
        }
        "demotivational" => {
            let inner = rect.shrink2(Vec2::new(rect.width() * 0.12, rect.height() * 0.14));
            painter.rect_stroke(inner, 0.0, Stroke::new(1.5_f32, Color32::WHITE), egui::StrokeKind::Outside);
            painter.text(
                Pos2::new(rect.center().x, rect.bottom() - rect.height() * 0.085),
                Align2::CENTER_CENTER,
                &ml.top_text.to_uppercase(),
                FontId::proportional((short_edge * 0.06).clamp(12.0, 24.0)),
                Color32::WHITE,
            );
            painter.text(
                Pos2::new(rect.center().x, rect.bottom() - rect.height() * 0.035),
                Align2::CENTER_CENTER,
                &ml.bottom_text,
                FontId::proportional((short_edge * 0.032).clamp(9.0, 14.0)),
                Color32::from_rgb(203, 213, 225),
            );
        }
        _ => {}
    }
}
