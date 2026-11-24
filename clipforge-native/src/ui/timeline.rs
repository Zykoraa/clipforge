use crate::api::ApiCommand;
use crate::app::{ClipForgeApp, SelectedEntity};
use crate::theme::*;
use egui::{Align2, Color32, FontId, Pos2, Rect, RichText, Sense, Stroke, Vec2};
use serde_json::json;

const HEADER_W: f32 = 96.0;
const RULER_H: f32 = 24.0;
const VIDEO_LANE_H: f32 = 64.0;
const SUB_LANE_H: f32 = 34.0;
const SFX_LANE_H: f32 = 30.0;

pub fn render_timeline_panel(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    // Timeline header bar
    ui.horizontal(|ui| {
        ui.label(RichText::new("TIMELINE").strong().size(12.0).color(TEXT_MUTED));
        let stats = format!(
            "{} clips · {} captions · {} SFX · {}",
            app.summary.project.timeline.len(),
            app.summary.project.subtitles.len(),
            app.summary.project.audio_overlays.len(),
            format_time(app.summary.total_duration_sec)
        );
        badge(ui, &stats, ACCENT_BLUE);

        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            ui.add(egui::Slider::new(&mut app.px_per_sec, 28.0..=220.0).text("Zoom"));
        });
    });

    ui.add_space(4.0);

    let max_dur = (app.summary.total_duration_sec + 4.0).max(16.0);
    let total_w = (HEADER_W + (max_dur as f32) * app.px_per_sec).max(ui.available_width());
    let total_h = RULER_H + VIDEO_LANE_H + SUB_LANE_H + SFX_LANE_H + 10.0;

    egui::ScrollArea::horizontal()
        .id_salt("timeline_hscroll")
        .auto_shrink([false, false])
        .show(ui, |ui| {
            let (full_rect, _resp) = ui.allocate_exact_size(Vec2::new(total_w, total_h), Sense::hover());
            let painter = ui.painter_at(full_rect);

            let ruler_rect = Rect::from_min_size(full_rect.min, Vec2::new(total_w, RULER_H));
            let vid_rect = Rect::from_min_size(
                Pos2::new(full_rect.left(), ruler_rect.bottom() + 2.0),
                Vec2::new(total_w, VIDEO_LANE_H),
            );
            let sub_rect = Rect::from_min_size(
                Pos2::new(full_rect.left(), vid_rect.bottom() + 2.0),
                Vec2::new(total_w, SUB_LANE_H),
            );
            let sfx_rect = Rect::from_min_size(
                Pos2::new(full_rect.left(), sub_rect.bottom() + 2.0),
                Vec2::new(total_w, SFX_LANE_H),
            );

            // Lane backgrounds & track headers
            painter.rect_filled(ruler_rect, 2.0, BG_ROOT);
            for (r, title, accent) in [
                (vid_rect, "VIDEO / AUD", ACCENT_BLUE),
                (sub_rect, "SUBTITLES", ACCENT_GREEN),
                (sfx_rect, "SFX / BGM", ACCENT_AMBER),
            ] {
                painter.rect_filled(r, 3.0, Color32::from_rgb(13, 16, 24));
                let hdr = Rect::from_min_size(r.min, Vec2::new(HEADER_W, r.height()));
                painter.rect_filled(hdr, 2.0, BG_CARD);
                painter.rect_stroke(hdr, 2.0, Stroke::new(1.0_f32, BORDER_SUBTLE), egui::StrokeKind::Inside);
                painter.text(
                    hdr.center(),
                    Align2::CENTER_CENTER,
                    title,
                    FontId::proportional(10.5),
                    accent,
                );
            }

            // Ruler ticks & click/drag scrubbing
            let step_sec = if app.px_per_sec >= 120.0 {
                0.5
            } else if app.px_per_sec >= 55.0 {
                1.0
            } else {
                2.0
            };
            let mut t = 0.0_f64;
            while t <= max_dur {
                let x = full_rect.left() + HEADER_W + (t as f32) * app.px_per_sec;
                painter.line_segment(
                    [Pos2::new(x, ruler_rect.top() + 10.0), Pos2::new(x, ruler_rect.bottom())],
                    Stroke::new(1.0_f32, BORDER_SUBTLE),
                );
                let label = if step_sec < 1.0 {
                    format!("{t:.1}s")
                } else {
                    format!("{t:.0}s")
                };
                painter.text(
                    Pos2::new(x + 3.0, ruler_rect.top() + 3.0),
                    Align2::LEFT_TOP,
                    label,
                    FontId::monospace(10.0),
                    TEXT_MUTED,
                );
                t += step_sec;
            }

            let ruler_scrub_rect = Rect::from_min_max(
                Pos2::new(full_rect.left() + HEADER_W, ruler_rect.top()),
                ruler_rect.max,
            );
            let scrub_resp = ui.interact(ruler_scrub_rect, egui::Id::new("tl_ruler_scrub"), Sense::click_and_drag());
            if scrub_resp.clicked() || scrub_resp.dragged() {
                if let Some(pos) = scrub_resp.interact_pointer_pos() {
                    let sec = ((pos.x - (full_rect.left() + HEADER_W)).max(0.0) / app.px_per_sec) as f64;
                    app.player.seek_to(sec, app.summary.total_duration_sec);
                }
            }

            // Draw VIDEO/AUDIO clips + waveforms + interactive trim handles
            let schedule_clone = app.summary.schedule.clone();
            let media_bin = app.summary.project.media_bin.clone();
            for s in &schedule_clone {
                let media = media_bin.iter().find(|m| m.id == s.media_id);
                let left_x = full_rect.left() + HEADER_W + (s.timeline_start_sec as f32) * app.px_per_sec;
                let width = (((s.timeline_end_sec - s.timeline_start_sec) as f32) * app.px_per_sec).max(22.0);
                let clip_rect = Rect::from_min_size(
                    Pos2::new(left_x, vid_rect.top() + 4.0),
                    Vec2::new(width, VIDEO_LANE_H - 8.0),
                );
                let is_sel = app.selected == Some(SelectedEntity::Clip(s.clip_id.clone()));

                let fill = if is_sel {
                    Color32::from_rgb(34, 62, 114)
                } else {
                    Color32::from_rgb(24, 38, 66)
                };
                let stroke_col = if is_sel { Color32::WHITE } else { ACCENT_BLUE };
                painter.rect_filled(clip_rect, 5.0, fill);
                painter.rect_stroke(clip_rect, 5.0, Stroke::new(if is_sel { 1.8_f32 } else { 1.0_f32 }, stroke_col), egui::StrokeKind::Inside);

                // Audio waveform bars inside bottom half of clip
                if let Some(m) = media {
                    if !m.waveform_peaks.is_empty() && m.duration_sec > 0.05 {
                        let peaks = &m.waveform_peaks;
                        let s_ratio = (s.in_sec / m.duration_sec).clamp(0.0, 1.0);
                        let e_ratio = (s.out_sec / m.duration_sec).clamp(s_ratio + 0.01, 1.0);
                        let s_idx = (s_ratio * peaks.len() as f64).floor() as usize;
                        let e_idx = ((e_ratio * peaks.len() as f64).ceil() as usize).clamp(s_idx + 1, peaks.len());
                        let slice = &peaks[s_idx.min(peaks.len().saturating_sub(1))..e_idx];
                        let wf_h = 22.0_f32;
                        let bar_w = (clip_rect.width() / (slice.len().max(1) as f32)).max(2.0);
                        let mut bx = clip_rect.left() + 4.0;
                        for &p in slice {
                            if bx >= clip_rect.right() - 4.0 {
                                break;
                            }
                            let bh = (p.clamp(0.0, 1.0) * wf_h).max(2.0);
                            let br = Rect::from_min_max(
                                Pos2::new(bx, clip_rect.bottom() - bh - 2.0),
                                Pos2::new((bx + bar_w - 1.0).min(clip_rect.right() - 4.0), clip_rect.bottom() - 2.0),
                            );
                            painter.rect_filled(br, 1.0, Color32::from_rgba_unmultiplied(96, 165, 250, 140));
                            bx += bar_w;
                        }
                    }
                }

                // Clip title & range
                let title = if s.label.is_empty() {
                    media.map(|m| m.filename.as_str()).unwrap_or("Clip")
                } else {
                    &s.label
                };
                painter.text(
                    Pos2::new(clip_rect.left() + 8.0, clip_rect.top() + 5.0),
                    Align2::LEFT_TOP,
                    title,
                    FontId::proportional(11.5),
                    Color32::WHITE,
                );
                let meta_txt = format!("{:.1}s–{:.1}s{}", s.in_sec, s.out_sec, if (s.speed - 1.0).abs() > 0.01 { format!(" ({:.2}x)", s.speed) } else { String::new() });
                painter.text(
                    Pos2::new(clip_rect.left() + 8.0, clip_rect.top() + 20.0),
                    Align2::LEFT_TOP,
                    meta_txt,
                    FontId::monospace(9.5),
                    TEXT_MUTED,
                );

                // Left & Right drag-to-trim handles
                let handle_w = 7.0;
                let left_h = Rect::from_min_size(clip_rect.min, Vec2::new(handle_w, clip_rect.height()));
                let right_h = Rect::from_min_size(
                    Pos2::new(clip_rect.right() - handle_w, clip_rect.top()),
                    Vec2::new(handle_w, clip_rect.height()),
                );
                let l_resp = ui.interact(left_h, egui::Id::new(("trim_l", &s.clip_id)), Sense::drag());
                let r_resp = ui.interact(right_h, egui::Id::new(("trim_r", &s.clip_id)), Sense::drag());
                if l_resp.hovered() || r_resp.hovered() {
                    ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
                }

                let max_media_dur = media.map(|m| m.duration_sec).unwrap_or(s.out_sec + 30.0);
                if l_resp.dragged() {
                    let dx = l_resp.drag_delta().x;
                    let dsec = (dx / app.px_per_sec) as f64 * s.speed;
                    let entry = app
                        .timeline_drag_trim
                        .get_or_insert_with(|| (s.clip_id.clone(), true, s.in_sec, s.in_sec));
                    entry.3 = (entry.3 + dsec).clamp(0.0, (s.out_sec - 0.1).max(0.0));
                } else if l_resp.drag_stopped() {
                    if let Some((cid, true, orig, cur)) = app.timeline_drag_trim.take() {
                        if (cur - orig).abs() > 0.02 {
                            app.api.send(ApiCommand::UpdateClip {
                                clip_id: cid,
                                body: json!({ "in_sec": (cur * 100.0).round() / 100.0 }),
                            });
                        }
                    }
                }

                if r_resp.dragged() {
                    let dx = r_resp.drag_delta().x;
                    let dsec = (dx / app.px_per_sec) as f64 * s.speed;
                    let entry = app
                        .timeline_drag_trim
                        .get_or_insert_with(|| (s.clip_id.clone(), false, s.out_sec, s.out_sec));
                    entry.3 = (entry.3 + dsec).clamp(s.in_sec + 0.1, max_media_dur);
                } else if r_resp.drag_stopped() {
                    if let Some((cid, false, orig, cur)) = app.timeline_drag_trim.take() {
                        if (cur - orig).abs() > 0.02 {
                            app.api.send(ApiCommand::UpdateClip {
                                clip_id: cid,
                                body: json!({ "out_sec": (cur * 100.0).round() / 100.0 }),
                            });
                        }
                    }
                }

                // Body click selects clip
                let body_rect = clip_rect.shrink2(Vec2::new(handle_w, 0.0));
                let c_resp = ui.interact(body_rect, egui::Id::new(("tl_clip", &s.clip_id)), Sense::click());
                if c_resp.clicked() {
                    app.selected = Some(SelectedEntity::Clip(s.clip_id.clone()));
                    app.clip_draft = None;
                    app.sync_inspector_drafts();
                }
            }

            // Draw SUBTITLES blocks
            let subs = app.summary.project.subtitles.clone();
            for sub in &subs {
                let lx = full_rect.left() + HEADER_W + (sub.start_sec as f32) * app.px_per_sec;
                let w = (((sub.end_sec - sub.start_sec) as f32) * app.px_per_sec).max(18.0);
                let sr = Rect::from_min_size(Pos2::new(lx, sub_rect.top() + 4.0), Vec2::new(w, SUB_LANE_H - 8.0));
                let is_sel = app.selected == Some(SelectedEntity::Subtitle(sub.id.clone()));
                painter.rect_filled(
                    sr,
                    4.0,
                    if is_sel { Color32::from_rgb(16, 110, 78) } else { Color32::from_rgb(18, 64, 52) },
                );
                painter.rect_stroke(sr, 4.0, Stroke::new(1.0_f32, if is_sel { Color32::WHITE } else { ACCENT_GREEN }), egui::StrokeKind::Inside);
                painter.text(
                    Pos2::new(sr.left() + 5.0, sr.center().y),
                    Align2::LEFT_CENTER,
                    &sub.text,
                    FontId::proportional(11.0),
                    Color32::WHITE,
                );
                let r = ui.interact(sr, egui::Id::new(("tl_sub", &sub.id)), Sense::click());
                if r.clicked() {
                    app.selected = Some(SelectedEntity::Subtitle(sub.id.clone()));
                    app.sub_draft = None;
                    app.sync_inspector_drafts();
                    app.player.seek_to(sub.start_sec + 0.02, app.summary.total_duration_sec);
                }
            }

            // Draw SFX / BGM overlay blocks
            let overlays = app.summary.project.audio_overlays.clone();
            for ov in &overlays {
                let lx = full_rect.left() + HEADER_W + (ov.start_sec as f32) * app.px_per_sec;
                let w = (((ov.duration_sec.max(0.8)) as f32) * app.px_per_sec).max(24.0);
                let or = Rect::from_min_size(Pos2::new(lx, sfx_rect.top() + 4.0), Vec2::new(w, SFX_LANE_H - 8.0));
                let is_sel = app.selected == Some(SelectedEntity::Sfx(ov.id.clone()));
                painter.rect_filled(
                    or,
                    4.0,
                    if is_sel { Color32::from_rgb(146, 84, 14) } else { Color32::from_rgb(76, 48, 16) },
                );
                painter.rect_stroke(or, 4.0, Stroke::new(1.0_f32, if is_sel { Color32::WHITE } else { ACCENT_AMBER }), egui::StrokeKind::Inside);
                painter.text(
                    Pos2::new(or.left() + 5.0, or.center().y),
                    Align2::LEFT_CENTER,
                    &ov.label,
                    FontId::proportional(10.5),
                    Color32::WHITE,
                );
                let r = ui.interact(or, egui::Id::new(("tl_sfx", &ov.id)), Sense::click());
                if r.clicked() {
                    app.selected = Some(SelectedEntity::Sfx(ov.id.clone()));
                    app.sfx_draft = None;
                    app.sync_inspector_drafts();
                    app.player.seek_to(ov.start_sec, app.summary.total_duration_sec);
                }
            }

            // Red vertical playhead line across all tracks
            let ph_x = full_rect.left() + HEADER_W + (app.player.playhead_sec as f32) * app.px_per_sec;
            painter.line_segment(
                [Pos2::new(ph_x, ruler_rect.top()), Pos2::new(ph_x, sfx_rect.bottom())],
                Stroke::new(2.0_f32, ACCENT_RED),
            );
            painter.circle_filled(Pos2::new(ph_x, ruler_rect.top() + 5.0), 4.5, ACCENT_RED);
        });
}
