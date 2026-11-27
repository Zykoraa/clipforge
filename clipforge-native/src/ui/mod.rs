pub mod modals;
pub mod panels;
pub mod simple;
pub mod studio;
pub mod timeline;

use crate::api::{ApiCommand, ToastKind};
use crate::app::{ClipForgeApp, LeftTab, SelectedEntity, UiMode};
use crate::player::active_clip_at;
use crate::theme::*;
use egui::{Align, Color32, CornerRadius, Frame, Layout, Margin, RichText, Stroke};
use serde_json::json;

pub fn render_main_layout(app: &mut ClipForgeApp, ctx: &egui::Context) {
    // 1. Top Command Bar
    egui::TopBottomPanel::top("top_bar")
        .exact_height(46.0)
        .frame(
            Frame::new()
                .fill(BG_PANEL)
                .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
                .inner_margin(Margin::symmetric(12, 6)),
        )
        .show(ctx, |ui| {
            ui.horizontal_centered(|ui| {
                ui.label(RichText::new("⚡ CLIPFORGE").size(15.5).strong().color(Color32::WHITE));

                ui.separator();

                // Simple vs. Pro Editor animated pill switcher
                let mode_idx = if app.ui_mode == UiMode::Simple { 0 } else { 1 };
                ui.allocate_ui(egui::vec2(215.0, 34.0), |ui| {
                    if let Some(picked) = animated_segmented_bar(
                        ui,
                        "top_ui_mode",
                        &["✨ Simple", "🎛 Pro Editor"],
                        mode_idx,
                        ACCENT_BLUE,
                    ) {
                        let next_mode = if picked == 0 { UiMode::Simple } else { UiMode::Pro };
                        if next_mode == UiMode::Pro && app.ui_mode == UiMode::Simple {
                            app.player.stop_playback();
                        }
                        app.ui_mode = next_mode;
                    }
                });

                if app.ui_mode == UiMode::Pro {
                    ui.separator();

                    let name_resp = ui.add(
                        egui::TextEdit::singleline(&mut app.project_name_buf)
                            .desired_width(155.0)
                            .hint_text("Project name"),
                    );
                    if name_resp.lost_focus() && name_resp.changed() {
                        app.api.send(ApiCommand::ConfigureProject(json!({
                            "name": app.project_name_buf
                        })));
                    }

                    let aspect_options = [
                        ("1080x1920", "9:16 Vertical (1080×1920)"),
                        ("1920x1080", "16:9 Landscape (1920×1080)"),
                        ("1080x1080", "1:1 Square (1080×1080)"),
                        ("1280x720", "16:9 Fast HD (1280×720)"),
                    ];
                    let prev_aspect = app.aspect_buf.clone();
                    egui::ComboBox::from_id_salt("aspect_select")
                        .selected_text(
                            aspect_options
                                .iter()
                                .find(|(v, _)| *v == app.aspect_buf)
                                .map(|(_, l)| *l)
                                .unwrap_or(&app.aspect_buf),
                        )
                        .width(160.0)
                        .show_ui(ui, |ui| {
                            for (val, lbl) in aspect_options {
                                ui.selectable_value(&mut app.aspect_buf, val.to_string(), lbl);
                            }
                        });
                    if app.aspect_buf != prev_aspect {
                        if let Some((w, h)) = app.aspect_buf.split_once('x') {
                            if let (Ok(wi), Ok(hi)) = (w.parse::<u32>(), h.parse::<u32>()) {
                                app.api.send(ApiCommand::ConfigureProject(json!({
                                    "width": wi,
                                    "height": hi
                                })));
                            }
                        }
                    }

                    ui.separator();

                    if app.ws_connected {
                        badge(
                            ui,
                            &format!("● MCP v{}", app.summary.project.version),
                            ACCENT_GREEN,
                        );
                    } else {
                        badge(ui, "○ SYNC", ACCENT_AMBER);
                    }
                }

                // Right-aligned actions
                ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                    if app.ui_mode == UiMode::Pro {
                        if ui.add(primary_button("🎬 Render MP4")).clicked() {
                            app.show_render_modal = true;
                        }
                        if ui.button("Clear").on_hover_text("Clear timeline").clicked() {
                            app.api.send(ApiCommand::ClearTimeline);
                        }
                        if ui.button("↪").on_hover_text("Redo (Ctrl+Y)").clicked() {
                            app.api.send(ApiCommand::Redo);
                        }
                        if ui.button("↩").on_hover_text("Undo (Ctrl+Z)").clicked() {
                            app.api.send(ApiCommand::Undo);
                        }
                        ui.separator();
                    }

                    let civ_active = app
                        .gen_status
                        .civitai
                        .downloads
                        .iter()
                        .find(|d| d.status == "downloading");
                    let civ_lbl = if let Some(d) = civ_active {
                        format!("⬇ Style ({:.0}%)", d.pct)
                    } else {
                        "✨ Get Styles".to_string()
                    };
                    if ui
                        .button(civ_lbl)
                        .on_hover_text("Install new art styles & visual boosters from the community library (CivitAI)")
                        .clicked()
                    {
                        app.show_civitai_modal = true;
                        app.api.send(ApiCommand::RefreshGenStatus);
                    }

                    let ready_cnt = app.gen_status.models.values().filter(|m| m.ready).count();
                    let total_cnt = app.gen_status.models.len();
                    let dl_active = app.gen_status.models.values().find_map(|m| {
                        m.download.as_ref().filter(|d| d.status == "downloading")
                    });
                    let models_lbl = if let Some(d) = dl_active {
                        format!("⬇ Downloading ({:.0}%)", d.pct)
                    } else if app.ui_mode == UiMode::Simple {
                        "⬇ Setup & Packs".to_string()
                    } else {
                        format!("🧠 Engines {ready_cnt}/{total_cnt}")
                    };
                    if ui.button(models_lbl).clicked() {
                        app.show_models_modal = true;
                        app.api.send(ApiCommand::RefreshGenStatus);
                    }

                    let cast_lbl = format!("👥 Friends ({})", app.gen_status.cast.len());
                    if ui.button(cast_lbl).clicked() {
                        app.show_cast_modal = true;
                    }
                });
            });
        });

    if app.ui_mode == UiMode::Simple {
        simple::render_simple_workspace(app, ctx);
    } else {
    // 2. Bottom Multi-Track Timeline Panel
    egui::TopBottomPanel::bottom("timeline_panel")
        .resizable(true)
        .default_height(215.0)
        .min_height(155.0)
        .max_height(360.0)
        .frame(
            Frame::new()
                .fill(BG_PANEL)
                .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
                .inner_margin(Margin::same(8)),
        )
        .show(ctx, |ui| {
            timeline::render_timeline_panel(app, ui);
        });

    // 3. Left Tool Dock (AI Studio / Media / Subs+Voice / Meme+SFX)
    egui::SidePanel::left("left_dock")
        .resizable(true)
        .default_width(370.0)
        .min_width(310.0)
        .max_width(540.0)
        .frame(
            Frame::new()
                .fill(BG_PANEL)
                .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
                .inner_margin(Margin::same(8)),
        )
        .show(ctx, |ui| {
            ui.horizontal(|ui| {
                for (tab, label) in [
                    (LeftTab::Studio, "✨ AI Studio"),
                    (LeftTab::Media, "📁 Media"),
                    (LeftTab::Subs, "💬 Subs & Voice"),
                    (LeftTab::Meme, "😂 Meme & SFX"),
                ] {
                    let active = app.left_tab == tab;
                    let btn = egui::Button::new(
                        RichText::new(label)
                            .strong()
                            .size(12.0)
                            .color(if active { Color32::WHITE } else { TEXT_MUTED }),
                    )
                    .fill(if active { ACCENT_BLUE } else { BG_CARD })
                    .corner_radius(CornerRadius::same(6));
                    if ui.add(btn).clicked() {
                        app.left_tab = tab;
                    }
                }
            });
            ui.add_space(6.0);
            egui::ScrollArea::vertical()
                .id_salt("left_dock_scroll")
                .auto_shrink([false, false])
                .show(ui, |ui| match app.left_tab {
                    LeftTab::Studio => studio::render_studio_tab(app, ui, ctx),
                    LeftTab::Media => panels::render_media_tab(app, ui),
                    LeftTab::Subs => panels::render_subs_tab(app, ui),
                    LeftTab::Meme => panels::render_meme_tab(app, ui),
                });
        });

    // 4. Right Inspector & Live Activity Log
    egui::SidePanel::right("right_inspector")
        .resizable(true)
        .default_width(280.0)
        .min_width(235.0)
        .max_width(380.0)
        .frame(
            Frame::new()
                .fill(BG_PANEL)
                .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
                .inner_margin(Margin::same(8)),
        )
        .show(ctx, |ui| {
            panels::render_inspector_panel(app, ui);
        });

    // 5. Center GPU Video Preview Viewport + Transport Controls
    egui::CentralPanel::default()
        .frame(Frame::new().fill(BG_ROOT).inner_margin(Margin::same(8)))
        .show(ctx, |ui| {
            let total_h = ui.available_height();
            let transport_h = 44.0;
            let viewport_h = (total_h - transport_h - 6.0).max(160.0);

            ui.allocate_ui_with_layout(
                egui::vec2(ui.available_width(), viewport_h),
                Layout::top_down(Align::Center),
                |ui| {
                    app.player.paint_viewport(ui, &app.summary);
                },
            );

            ui.add_space(4.0);
            Frame::new()
                .fill(BG_PANEL)
                .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
                .corner_radius(CornerRadius::same(8))
                .inner_margin(Margin::symmetric(10, 6))
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        if ui.button("⏮").on_hover_text("Seek start").clicked() {
                            app.player.seek_to(0.0, app.summary.total_duration_sec);
                        }
                        if ui.button("⏪").on_hover_text("-0.1s").clicked() {
                            app.player.seek_to(
                                app.player.playhead_sec - 0.1,
                                app.summary.total_duration_sec,
                            );
                        }
                        let play_lbl = if app.player.is_playing { "⏸ Pause" } else { "▶ Play" };
                        if ui.add(primary_button(play_lbl)).on_hover_text("Space").clicked() {
                            app.player.toggle_play(app.summary.total_duration_sec);
                        }
                        if ui.button("⏩").on_hover_text("+0.1s").clicked() {
                            app.player.seek_to(
                                app.player.playhead_sec + 0.1,
                                app.summary.total_duration_sec,
                            );
                        }

                        ui.add_space(6.0);
                        ui.label(
                            RichText::new(format!(
                                "{} / {}",
                                format_time(app.player.playhead_sec),
                                format_time(app.summary.total_duration_sec)
                            ))
                            .monospace()
                            .strong()
                            .color(TEXT_PRIMARY),
                        );

                        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                            if ui
                                .add(danger_button("🗑 Delete"))
                                .on_hover_text("Delete selected clip/caption/SFX (Del)")
                                .clicked()
                            {
                                if let Some(sel) = app.selected.take() {
                                    match sel {
                                        SelectedEntity::Clip(id) => app.api.send(ApiCommand::RemoveClip(id)),
                                        SelectedEntity::Subtitle(id) => app.api.send(ApiCommand::RemoveSubtitle(id)),
                                        SelectedEntity::Sfx(id) => app.api.send(ApiCommand::RemoveAudioOverlay(id)),
                                    }
                                }
                            }
                            if ui.button("✂ Split (S)").clicked() {
                                if let Some(cid) = match &app.selected {
                                    Some(SelectedEntity::Clip(id)) => Some(id.clone()),
                                    _ => active_clip_at(&app.summary.schedule, app.player.playhead_sec)
                                        .map(|c| c.clip_id.clone()),
                                } {
                                    app.api.send(ApiCommand::SplitClip {
                                        clip_id: cid,
                                        timeline_sec: app.player.playhead_sec,
                                    });
                                }
                            }
                            if ui
                                .button("⏭ Continue Shot")
                                .on_hover_text("Extract final frame into AI Video start slot")
                                .clicked()
                            {
                                app.continue_from_clip(None);
                            }
                        });
                    });
                });
        });
    } // end Pro NLE mode

    // 6. Modals
    modals::render_all_modals(app, ctx);

    // 7. Animated Floating Toast Notifications (smooth slide-in + fade-out overlay)
    if !app.toasts.is_empty() {
        let mut needs_toast_anim = false;
        for (idx, t) in app.toasts.iter().enumerate() {
            let age = t.created.elapsed().as_secs_f32();
            let in_t = (age / 0.22).clamp(0.0, 1.0);
            let out_t = if age > 3.6 {
                ((4.0 - age) / 0.40).clamp(0.0, 1.0)
            } else {
                1.0
            };
            if in_t < 1.0 || out_t < 1.0 {
                needs_toast_anim = true;
            }
            let ease = 1.0 - (1.0 - in_t).powi(3);
            let slide_x = (1.0 - ease) * 34.0;
            let alpha_u8 = (out_t * ease * 246.0).round().clamp(0.0, 255.0) as u8;
            let border_a = (out_t * ease * 230.0).round().clamp(0.0, 255.0) as u8;
            let text_a = (out_t * ease * 255.0).round().clamp(0.0, 255.0) as u8;
            let y_off = -16.0 - (idx as f32) * 46.0;

            egui::Area::new(egui::Id::new(("toast_overlay_item", idx, t.message.len())))
                .anchor(egui::Align2::RIGHT_BOTTOM, egui::vec2(-16.0 + slide_x, y_off))
                .interactable(false)
                .show(ctx, |ui| {
                    let accent = match t.kind {
                        ToastKind::Success => ACCENT_GREEN,
                        ToastKind::Warning => ACCENT_AMBER,
                        ToastKind::Error => ACCENT_RED,
                        ToastKind::Info => ACCENT_BLUE,
                    };
                    Frame::new()
                        .fill(Color32::from_rgba_unmultiplied(15, 20, 32, alpha_u8))
                        .stroke(Stroke::new(
                            1.2_f32,
                            Color32::from_rgba_unmultiplied(accent.r(), accent.g(), accent.b(), border_a),
                        ))
                        .corner_radius(CornerRadius::same(10))
                        .inner_margin(Margin::symmetric(12, 8))
                        .show(ui, |ui| {
                            ui.set_max_width(370.0);
                            ui.label(
                                RichText::new(&t.message)
                                    .color(Color32::from_rgba_unmultiplied(
                                        TEXT_PRIMARY.r(),
                                        TEXT_PRIMARY.g(),
                                        TEXT_PRIMARY.b(),
                                        text_a,
                                    ))
                                    .size(12.5),
                            );
                        });
                });
        }
        if needs_toast_anim {
            ctx.request_repaint_after(std::time::Duration::from_millis(16));
        }
    }
}
