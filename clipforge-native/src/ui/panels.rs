use crate::api::{ApiCommand, ToastKind};
use crate::app::{ClipForgeApp, SelectedEntity};
use crate::theme::*;
use egui::{Color32, CornerRadius, Image, RichText, Vec2};
use serde_json::json;

pub fn render_media_tab(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    // 1. Native Import Bar
    card_frame().show(ui, |ui| {
        ui.label(RichText::new("Import Media (Native Disk Access)").size(12.0).strong());
        ui.horizontal(|ui| {
            if ui
                .add(primary_button("📂 Open Files..."))
                .on_hover_text("Zero-copy native file import (video, audio, images)")
                .clicked()
            {
                if let Some(files) = rfd::FileDialog::new()
                    .add_filter(
                        "Media",
                        &["mp4", "mov", "mkv", "webm", "avi", "wav", "mp3", "m4a", "png", "jpg", "jpeg", "webp"],
                    )
                    .pick_files()
                {
                    let paths: Vec<String> = files
                        .into_iter()
                        .map(|p| p.to_string_lossy().to_string())
                        .collect();
                    app.api.send(ApiCommand::ImportPaths(paths));
                }
            }
            if ui.button("📁 Folder...").clicked() {
                if let Some(dir) = rfd::FileDialog::new().pick_folder() {
                    app.api.send(ApiCommand::ImportPaths(vec![dir.to_string_lossy().to_string()]));
                }
            }
        });
        ui.horizontal(|ui| {
            ui.add(
                egui::TextEdit::singleline(&mut app.import_path_buf)
                    .desired_width(ui.available_width() - 68.0)
                    .hint_text("Or paste path..."),
            );
            if ui.button("Import").clicked() && !app.import_path_buf.trim().is_empty() {
                let p = app.import_path_buf.trim().to_string();
                app.import_path_buf.clear();
                app.api.send(ApiCommand::ImportPaths(vec![p]));
            }
        });
    });

    ui.add_space(6.0);

    // 2. Smart Stitch Card
    card_frame().show(ui, |ui| {
        ui.label(RichText::new("⚡ AI Smart Stitch").size(12.0).strong());
        ui.horizontal(|ui| {
            ui.label(RichText::new("Transition:").size(11.0).color(TEXT_MUTED));
            egui::ComboBox::from_id_salt("stitch_tr_cb")
                .selected_text(&app.stitch_transition)
                .width(110.0)
                .show_ui(ui, |ui| {
                    for t in ["crossfade", "cut", "fadeblack", "wipeleft", "dissolve"] {
                        ui.selectable_value(&mut app.stitch_transition, t.into(), t);
                    }
                });
            ui.add(egui::DragValue::new(&mut app.stitch_trans_dur).speed(0.05).range(0.0..=1.5).suffix("s"));
        });
        ui.checkbox(&mut app.stitch_trim_silence, "Trim lead/trail dead air");
        ui.checkbox(&mut app.stitch_split_silence, "Jump-cut internal pauses");
        ui.checkbox(&mut app.stitch_auto_sub, "Auto-generate Whisper captions");
        let busy = app.busy_flags.contains("stitch");
        if ui
            .add_enabled(!busy, primary_button(if busy { "⚡ Stitching..." } else { "⚡ Run Smart Stitch" }))
            .clicked()
        {
            app.busy_flags.insert("stitch".into());
            app.api.send(ApiCommand::SmartStitch(json!({
                "order_by": app.stitch_order,
                "transition": app.stitch_transition,
                "transition_duration": app.stitch_trans_dur,
                "trim_silence": app.stitch_trim_silence,
                "split_long_silences": app.stitch_split_silence,
                "min_silence_sec": app.stitch_min_silence,
                "noise_db": app.stitch_noise_db,
                "auto_subtitle": app.stitch_auto_sub,
                "whisper_model": app.whisper_model,
            })));
        }
        if let Some(r) = &app.last_stitch_report {
            ui.label(
                RichText::new(format!(
                    "Stitched {} clips ({:.1}s) · Saved {:.1}s dead air · {} captions",
                    r.clips_count, r.stitched_duration_sec, r.saved_dead_air_sec, r.subtitles_count
                ))
                .size(10.5)
                .color(ACCENT_GREEN),
            );
        }
    });

    ui.add_space(6.0);

    // 3. Media Bin List
    let bin = app.summary.project.media_bin.clone();
    if bin.is_empty() {
        ui.label(RichText::new("Media Bin is empty — drop files anywhere or click Open Files.").color(TEXT_MUTED));
    } else {
        for m in &bin {
            card_frame().show(ui, |ui| {
                ui.horizontal(|ui| {
                    let thumb_src = m
                        .thumbnail_path
                        .as_deref()
                        .unwrap_or(if m.is_image { &m.path } else { "" });
                    if !thumb_src.is_empty() {
                        let key = format!("mthumb_{}", m.id);
                        if let Some(t) = app.api.get_or_load_image(&key, thumb_src, 128).cloned() {
                            ui.add(Image::new(&t).fit_to_exact_size(Vec2::new(62.0, 44.0)).corner_radius(CornerRadius::same(4)));
                        }
                    }
                    ui.vertical(|ui| {
                        ui.label(RichText::new(&m.filename).size(11.5).strong());
                        let meta_str = if m.is_image {
                            format!("{:.1}s · IMAGE · {}×{}", m.duration_sec, m.width, m.height)
                        } else if !m.has_video {
                            format!("{:.1}s · AUDIO ONLY", m.duration_sec)
                        } else {
                            format!("{:.1}s · {}×{} · {:.0}fps", m.duration_sec, m.width, m.height, m.fps)
                        };
                        ui.label(RichText::new(meta_str).size(10.0).color(TEXT_MUTED));
                        ui.horizontal(|ui| {
                            if ui.small_button("+ Timeline").clicked() {
                                let has_tl = !app.summary.project.timeline.is_empty();
                                app.api.send(ApiCommand::AddClip(json!({
                                    "media_id": m.id,
                                    "transition": if has_tl { "crossfade" } else { "cut" },
                                    "transition_duration": if has_tl { 0.35 } else { 0.0 },
                                })));
                            }
                            if m.is_image {
                                if ui.small_button("🎬 Animate").clicked() {
                                    app.animate_image_in_video(m.path.clone(), m.filename.clone());
                                }
                            } else {
                                let busy = app.busy_flags.contains("analyze");
                                if ui.add_enabled(!busy, egui::Button::new("Analyze").small()).clicked() {
                                    app.busy_flags.insert("analyze".into());
                                    app.api.send(ApiCommand::AnalyzeMedia {
                                        media_id: m.id.clone(),
                                        model_size: app.whisper_model.clone(),
                                    });
                                }
                            }
                            if ui.small_button("✕").clicked() {
                                app.api.send(ApiCommand::RemoveMedia(m.id.clone()));
                            }
                        });
                    });
                });
            });
            ui.add_space(4.0);
        }
    }
}

pub fn render_subs_tab(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    // 1. Offline F5-TTS Friend Voice Cloner + 1-Click Talk-Sync Video
    card_frame().show(ui, |ui| {
        ui.horizontal(|ui| {
            ui.label(RichText::new("🎙 Offline Voice Cloner & Lip-Sync").size(12.0).strong());
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                badge(
                    ui,
                    if app.gen_status.voice.ready { "F5-TTS Ready" } else { "Offline" },
                    if app.gen_status.voice.ready { ACCENT_GREEN } else { TEXT_MUTED },
                );
            });
        });

        let voice_cast: Vec<_> = app.gen_status.cast.iter().filter(|c| c.has_voice).cloned().collect();
        ui.horizontal(|ui| {
            let sel_name = voice_cast
                .iter()
                .find(|c| c.id == app.voice_cast_id)
                .map(|c| format!("🎙 {} ({})", c.name, c.handle))
                .unwrap_or_else(|| "Select friend with voice...".into());
            egui::ComboBox::from_id_salt("voice_cast_cb")
                .selected_text(sel_name)
                .width(ui.available_width() - 62.0)
                .show_ui(ui, |ui| {
                    for c in &voice_cast {
                        ui.selectable_value(
                            &mut app.voice_cast_id,
                            c.id.clone(),
                            format!("🎙 {} ({})", c.name, c.handle),
                        );
                    }
                });
            if ui.small_button("+ Cast").clicked() {
                app.show_cast_modal = true;
            }
        });

        ui.add(
            egui::TextEdit::multiline(&mut app.voice_text)
                .desired_rows(2)
                .desired_width(f32::INFINITY)
                .hint_text("Type dialogue for your friend's cloned voice..."),
        );

        ui.horizontal(|ui| {
            ui.label(RichText::new("Speed").size(11.0));
            ui.add(egui::DragValue::new(&mut app.voice_speed).speed(0.05).range(0.6..=1.5));
            ui.checkbox(&mut app.voice_auto_timeline, "Auto-add to timeline");
        });

        ui.horizontal(|ui| {
            if ui.add(primary_button("🎙 Clone Voice")).clicked() {
                if app.voice_cast_id.is_empty() || app.voice_text.trim().is_empty() {
                    app.push_toast("Pick a saved friend with voice and type dialogue.", ToastKind::Warning);
                } else {
                    app.api.send(ApiCommand::CloneVoice(json!({
                        "cast_id": app.voice_cast_id,
                        "text": app.voice_text.trim(),
                        "speed": app.voice_speed,
                        "add_to_timeline": app.voice_auto_timeline,
                        "start_sec": app.player.playhead_sec,
                        "duck_main_audio": true,
                    })));
                }
            }
            if ui
                .button("🗣 Talk-Sync Video")
                .on_hover_text("1-click F5-TTS voice clone -> Wan 2.2 S2V lip-sync / I2V talking video!")
                .clicked()
            {
                if app.voice_cast_id.is_empty() || app.voice_text.trim().is_empty() {
                    app.push_toast("Pick a saved friend with voice and type dialogue.", ToastKind::Warning);
                } else {
                    app.api.send(ApiCommand::TalkSyncVideo(json!({
                        "cast_id": app.voice_cast_id,
                        "text": app.voice_text.trim(),
                        "style_preset": app.preset_id,
                        "speed": app.voice_speed,
                        "add_to_timeline": app.voice_auto_timeline,
                    })));
                }
            }
        });
    });

    ui.add_space(6.0);

    // 2. Whisper Auto-Subtitle + 10 Presets & Colors
    card_frame().show(ui, |ui| {
        ui.label(RichText::new("💬 Auto-Subtitles (Whisper Karaoke)").size(12.0).strong());
        ui.horizontal(|ui| {
            ui.label(RichText::new("Whisper:").size(11.0).color(TEXT_MUTED));
            egui::ComboBox::from_id_salt("whisper_cb")
                .selected_text(&app.whisper_model)
                .width(100.0)
                .show_ui(ui, |ui| {
                    for m in ["tiny", "base", "small", "medium"] {
                        ui.selectable_value(&mut app.whisper_model, m.into(), m);
                    }
                });
            let busy = app.busy_flags.contains("autosub");
            if ui
                .add_enabled(!busy, primary_button(if busy { "Transcribing..." } else { "💬 Auto-Sub" }))
                .clicked()
            {
                app.busy_flags.insert("autosub".into());
                app.api.send(ApiCommand::AutoSubtitle(json!({
                    "model_size": app.whisper_model,
                    "style_preset": app.sub_style_draft.preset,
                    "max_words_per_caption": app.sub_style_draft.max_words_per_caption,
                })));
            }
        });

        ui.add_space(4.0);
        let prev_preset = app.sub_style_draft.preset.clone();
        egui::ComboBox::from_id_salt("sub_preset_cb")
            .selected_text(format!("Preset: {}", app.sub_style_draft.preset))
            .width(ui.available_width() - 4.0)
            .show_ui(ui, |ui| {
                for p in [
                    "hormozi", "mrbeast", "tiktok_clean", "meme_impact", "gaming_rgb",
                    "news_ticker", "whisper_red", "cinema", "minimal", "neon_box",
                ] {
                    ui.selectable_value(&mut app.sub_style_draft.preset, p.into(), p);
                }
            });
        if app.sub_style_draft.preset != prev_preset {
            app.api.send(ApiCommand::SetSubtitleStyle(json!({
                "preset": app.sub_style_draft.preset
            })));
        }

        let mut style_changed = false;
        ui.horizontal(|ui| {
            let mut pri = parse_hex_color(&app.sub_style_draft.primary_color, Color32::WHITE);
            let mut hi = parse_hex_color(&app.sub_style_draft.highlight_color, ACCENT_GREEN);
            let mut out = parse_hex_color(&app.sub_style_draft.outline_color, Color32::BLACK);
            ui.label("Text");
            if ui.color_edit_button_srgba(&mut pri).changed() {
                app.sub_style_draft.primary_color = format_hex_color(pri);
                style_changed = true;
            }
            ui.label("Pop");
            if ui.color_edit_button_srgba(&mut hi).changed() {
                app.sub_style_draft.highlight_color = format_hex_color(hi);
                style_changed = true;
            }
            ui.label("Out");
            if ui.color_edit_button_srgba(&mut out).changed() {
                app.sub_style_draft.outline_color = format_hex_color(out);
                style_changed = true;
            }
        });

        ui.horizontal(|ui| {
            ui.label("Size");
            if ui.add(egui::DragValue::new(&mut app.sub_style_draft.font_size).range(20..=140)).changed() {
                style_changed = true;
            }
            ui.label("Margin");
            if ui.add(egui::DragValue::new(&mut app.sub_style_draft.margin_v).range(10..=500)).changed() {
                style_changed = true;
            }
        });
        ui.horizontal(|ui| {
            if ui.checkbox(&mut app.sub_style_draft.word_highlight, "Word Pop").changed() {
                style_changed = true;
            }
            if ui.checkbox(&mut app.sub_style_draft.uppercase, "UPPERCASE").changed() {
                style_changed = true;
            }
        });
        if style_changed {
            app.api.send(ApiCommand::SetSubtitleStyle(json!({
                "primary_color": app.sub_style_draft.primary_color,
                "highlight_color": app.sub_style_draft.highlight_color,
                "outline_color": app.sub_style_draft.outline_color,
                "font_size": app.sub_style_draft.font_size,
                "margin_v": app.sub_style_draft.margin_v,
                "word_highlight": app.sub_style_draft.word_highlight,
                "uppercase": app.sub_style_draft.uppercase,
            })));
        }

        if ui.button("+ Add Manual Caption at Playhead").clicked() {
            let s = app.player.playhead_sec;
            app.api.send(ApiCommand::UpsertSubtitle(json!({
                "start_sec": (s * 100.0).round() / 100.0,
                "end_sec": ((s + 2.0) * 100.0).round() / 100.0,
                "text": "New caption text",
            })));
        }
    });
}

pub fn render_meme_tab(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    // 1. 7 Native Meme Layout Templates
    card_frame().show(ui, |ui| {
        ui.label(RichText::new("😂 Native Meme Layout Templates").size(12.0).strong());
        egui::ComboBox::from_id_salt("meme_tpl_cb")
            .selected_text(&app.meme_layout_draft.template)
            .width(ui.available_width() - 4.0)
            .show_ui(ui, |ui| {
                for (t, lbl) in [
                    ("none", "None (Clean Video)"),
                    ("pov_top_bar", "POV White Top Header"),
                    ("pov_dark_bar", "POV Dark Top Header"),
                    ("impact_top_bottom", "Classic IMPACT Top / Bottom"),
                    ("breaking_news", "Breaking News Chyron + Ticker"),
                    ("bodycam_hud", "AXON Bodycam Timestamp HUD"),
                    ("demotivational", "Demotivational Poster Frame"),
                ] {
                    ui.selectable_value(&mut app.meme_layout_draft.template, t.into(), lbl);
                }
            });

        let tpl = app.meme_layout_draft.template.as_str();
        if tpl == "breaking_news" || tpl == "bodycam_hud" {
            ui.add(
                egui::TextEdit::singleline(&mut app.meme_layout_draft.banner_label)
                    .desired_width(f32::INFINITY)
                    .hint_text("Banner / HUD header"),
            );
        }
        if tpl != "none" {
            ui.add(
                egui::TextEdit::singleline(&mut app.meme_layout_draft.top_text)
                    .desired_width(f32::INFINITY)
                    .hint_text("Top text / Headline"),
            );
        }
        if !matches!(tpl, "none" | "pov_top_bar" | "pov_dark_bar") {
            ui.add(
                egui::TextEdit::singleline(&mut app.meme_layout_draft.bottom_text)
                    .desired_width(f32::INFINITY)
                    .hint_text("Bottom text / Ticker / Unit"),
            );
        }

        if ui.add(primary_button("Apply Meme Layout")).clicked() {
            app.api.send(ApiCommand::SetMemeLayout(json!({
                "template": app.meme_layout_draft.template,
                "top_text": app.meme_layout_draft.top_text,
                "bottom_text": app.meme_layout_draft.bottom_text,
                "banner_label": app.meme_layout_draft.banner_label,
            })));
        }
    });

    ui.add_space(6.0);

    // 2. 12 Built-in Synthesized Meme SFX Soundboard (with instant native rodio preview!)
    card_frame().show(ui, |ui| {
        ui.label(RichText::new("🔊 Meme SFX Soundboard (Drops at Playhead)").size(12.0).strong());
        ui.horizontal(|ui| {
            ui.label(RichText::new("Vol:").size(11.0));
            ui.add(egui::Slider::new(&mut app.sfx_volume, 0.2..=2.0).step_by(0.1));
        });
        ui.checkbox(&mut app.sfx_duck, "Auto-duck main audio (sidechain)");
        ui.add_space(4.0);

        let catalog = app.sfx_catalog.clone();
        let cols = 2usize;
        let btn_w = ((ui.available_width() - 8.0) / cols as f32).max(115.0);
        egui::Grid::new("sfx_grid")
            .num_columns(cols)
            .spacing([5.0, 5.0])
            .show(ui, |ui| {
                for (i, s) in catalog.iter().enumerate() {
                    let lbl = format!("{} {}", s.emoji, s.label);
                    if ui
                        .add_sized([btn_w, 28.0], egui::Button::new(RichText::new(lbl).size(11.0)))
                        .on_hover_text(format!("{} ({:.1}s)", s.description, s.duration_sec))
                        .clicked()
                    {
                        app.api.send(ApiCommand::PreviewSfx {
                            sfx_id: s.id.clone(),
                            volume: app.sfx_volume,
                        });
                        app.api.send(ApiCommand::AddAudioOverlay(json!({
                            "sfx_id": s.id,
                            "start_sec": (app.player.playhead_sec * 100.0).round() / 100.0,
                            "volume": app.sfx_volume,
                            "duck_main_audio": app.sfx_duck,
                        })));
                    }
                    if (i + 1) % cols == 0 {
                        ui.end_row();
                    }
                }
            });
    });
}

pub fn render_inspector_panel(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    ui.label(RichText::new("INSPECTOR").strong().size(12.0).color(TEXT_MUTED));
    ui.add_space(4.0);

    app.sync_inspector_drafts();

    match &app.selected.clone() {
        Some(SelectedEntity::Clip(cid)) => {
            if let Some(mut d) = app.clip_draft.clone() {
                card_frame().show(ui, |ui| {
                    ui.label(RichText::new("Clip Properties").size(12.5).strong());
                    ui.label(RichText::new("Label").size(10.5).color(TEXT_MUTED));
                    ui.add(egui::TextEdit::singleline(&mut d.label).desired_width(f32::INFINITY));

                    ui.horizontal(|ui| {
                        ui.label("In (s)");
                        ui.add(egui::DragValue::new(&mut d.in_sec).speed(0.05).range(0.0..=3600.0));
                        ui.label("Out (s)");
                        ui.add(egui::DragValue::new(&mut d.out_sec).speed(0.05).range(0.1..=3600.0));
                    });
                    ui.horizontal(|ui| {
                        ui.label("Speed");
                        ui.add(egui::DragValue::new(&mut d.speed).speed(0.05).range(0.25..=4.0).suffix("x"));
                        ui.label("Vol");
                        ui.add(egui::DragValue::new(&mut d.volume).speed(0.05).range(0.0..=3.0));
                    });
                    ui.horizontal(|ui| {
                        ui.label("Trans:");
                        egui::ComboBox::from_id_salt("insp_tr_cb")
                            .selected_text(&d.transition)
                            .width(105.0)
                            .show_ui(ui, |ui| {
                                for t in [
                                    "cut", "crossfade", "fadeblack", "fadewhite", "wipeleft", "wiperight",
                                    "slideup", "slidedown", "circleopen", "circleclose", "dissolve", "pixelize",
                                ] {
                                    ui.selectable_value(&mut d.transition, t.into(), t);
                                }
                            });
                        ui.add(egui::DragValue::new(&mut d.transition_duration).speed(0.05).range(0.0..=2.5).suffix("s"));
                    });
                    ui.checkbox(&mut d.muted, "Mute clip audio");

                    if ui.add(primary_button("Apply Clip Changes")).clicked() {
                        app.api.send(ApiCommand::UpdateClip {
                            clip_id: cid.clone(),
                            body: json!({
                                "label": d.label,
                                "in_sec": d.in_sec,
                                "out_sec": d.out_sec,
                                "speed": d.speed,
                                "volume": d.volume,
                                "transition": d.transition,
                                "transition_duration": d.transition_duration,
                                "muted": d.muted,
                            }),
                        });
                    }

                    ui.add_space(4.0);
                    ui.horizontal(|ui| {
                        if ui.button("◀ Move").clicked() {
                            reorder_clip(app, cid, -1);
                        }
                        if ui.button("Move ▶").clicked() {
                            reorder_clip(app, cid, 1);
                        }
                    });
                    ui.horizontal(|ui| {
                        if ui.button("⏭ Continue").clicked() {
                            app.continue_from_clip(Some(cid.clone()));
                        }
                        let smoothing = app.busy_flags.contains("smooth");
                        if ui
                            .add_enabled(
                                !smoothing,
                                egui::Button::new(if smoothing { "⏳ RIFE..." } else { "⚡ Smooth 32fps" }),
                            )
                            .on_hover_text("GPU RIFE v4.26 optical-flow interpolation")
                            .clicked()
                        {
                            app.busy_flags.insert("smooth".into());
                            app.api.send(ApiCommand::SmoothClipFps {
                                clip_id: cid.clone(),
                                target_fps: 32.0,
                                prefer_rife: true,
                            });
                        }
                    });
                });
                app.clip_draft = Some(d);
            }
        }
        Some(SelectedEntity::Subtitle(sid)) => {
            if let Some(mut d) = app.sub_draft.clone() {
                card_frame().show(ui, |ui| {
                    ui.label(RichText::new("Subtitle Caption").size(12.5).strong());
                    ui.horizontal(|ui| {
                        ui.label("Start");
                        ui.add(egui::DragValue::new(&mut d.start_sec).speed(0.05).range(0.0..=3600.0));
                        ui.label("End");
                        ui.add(egui::DragValue::new(&mut d.end_sec).speed(0.05).range(0.1..=3600.0));
                    });
                    ui.add(egui::TextEdit::multiline(&mut d.text).desired_rows(3).desired_width(f32::INFINITY));
                    if ui.add(primary_button("Save Caption")).clicked() {
                        app.api.send(ApiCommand::UpsertSubtitle(json!({
                            "subtitle_id": sid,
                            "start_sec": d.start_sec,
                            "end_sec": d.end_sec,
                            "text": d.text,
                        })));
                    }
                });
                app.sub_draft = Some(d);
            }
        }
        Some(SelectedEntity::Sfx(oid)) => {
            if let Some(mut d) = app.sfx_draft.clone() {
                card_frame().show(ui, |ui| {
                    ui.label(RichText::new("SFX / BGM Overlay").size(12.5).strong());
                    ui.add(egui::TextEdit::singleline(&mut d.label).desired_width(f32::INFINITY));
                    ui.horizontal(|ui| {
                        ui.label("Start");
                        ui.add(egui::DragValue::new(&mut d.start_sec).speed(0.05).range(0.0..=3600.0));
                        ui.label("Vol");
                        ui.add(egui::DragValue::new(&mut d.volume).speed(0.05).range(0.0..=3.0));
                    });
                    ui.checkbox(&mut d.duck_main_audio, "Auto-duck main audio");
                    if ui.add(primary_button("Apply SFX Changes")).clicked() {
                        app.api.send(ApiCommand::UpdateAudioOverlay {
                            overlay_id: oid.clone(),
                            body: json!({
                                "label": d.label,
                                "start_sec": d.start_sec,
                                "volume": d.volume,
                                "duck_main_audio": d.duck_main_audio,
                            }),
                        });
                    }
                });
                app.sfx_draft = Some(d);
            }
        }
        None => {
            card_frame().show(ui, |ui| {
                ui.label(
                    RichText::new("Select a clip, subtitle, or SFX block on the timeline to inspect & edit.")
                        .size(11.5)
                        .color(TEXT_MUTED),
                );
            });
        }
    }

    ui.add_space(10.0);
    ui.separator();
    ui.label(RichText::new("ACTIVITY & MCP FEED").strong().size(11.0).color(TEXT_MUTED));
    ui.add_space(4.0);
    egui::ScrollArea::vertical()
        .id_salt("activity_log_scroll")
        .auto_shrink([false, false])
        .show(ui, |ui| {
            for entry in &app.logs {
                ui.label(RichText::new(entry).size(10.5).color(TEXT_MUTED));
            }
        });
}

fn reorder_clip(app: &mut ClipForgeApp, clip_id: &str, delta: isize) {
    let mut ids: Vec<String> = app.summary.schedule.iter().map(|s| s.clip_id.clone()).collect();
    if let Some(pos) = ids.iter().position(|id| id == clip_id) {
        let new_pos = (pos as isize + delta).clamp(0, ids.len().saturating_sub(1) as isize) as usize;
        if new_pos != pos {
            let item = ids.remove(pos);
            ids.insert(new_pos, item);
            app.api.send(ApiCommand::ReorderClips(ids));
        }
    }
}
