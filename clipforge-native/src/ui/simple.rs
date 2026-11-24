use crate::api::{ApiCommand, RefSlot, ToastKind};
use crate::app::{ClipForgeApp, RefAttachment, SimpleIntent, StudioMode, UiMode};
use crate::models::GalleryImage;
use crate::theme::*;
use egui::{Align, Color32, CornerRadius, Frame, Image, Layout, Margin, Pos2, Rect, RichText, Sense, Stroke, Vec2};
use serde_json::json;

pub fn render_simple_workspace(app: &mut ClipForgeApp, ctx: &egui::Context) {
    // Left Creator Panel (Intent Cards + Clean Prompt + Smart Controls)
    egui::SidePanel::left("simple_creator_panel")
        .resizable(true)
        .default_width(430.0)
        .min_width(360.0)
        .max_width(540.0)
        .frame(
            Frame::new()
                .fill(BG_PANEL)
                .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
                .inner_margin(Margin::same(12)),
        )
        .show(ctx, |ui| {
            egui::ScrollArea::vertical()
                .id_salt("simple_left_scroll")
                .auto_shrink([false, false])
                .show(ui, |ui| {
                    render_starter_pack_banner(app, ui);
                    render_intent_cards(app, ui);
                    ui.add_space(8.0);
                    if app.simple_intent == SimpleIntent::Talk {
                        render_simple_talk_card(app, ui);
                    } else {
                        render_simple_create_card(app, ui);
                    }
                    render_simple_active_job(app, ui);
                });
        });

    // Right Main Result Canvas + 1-Click Fix / Steer Chips + Recent Creations Strip
    egui::CentralPanel::default()
        .frame(Frame::new().fill(BG_ROOT).inner_margin(Margin::same(14)))
        .show(ctx, |ui| {
            render_simple_result_canvas(app, ui, ctx);
        });
}

fn render_starter_pack_banner(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    let any_img_ready = app
        .gen_status
        .models
        .values()
        .any(|m| m.kind == "image" && m.ready);
    if any_img_ready || app.gen_status.models.is_empty() {
        return;
    }
    let rec_pack = app
        .gen_status
        .starter_packs
        .iter()
        .find(|p| p.recommended)
        .or_else(|| app.gen_status.starter_packs.first())
        .cloned();

    Frame::new()
        .fill(Color32::from_rgb(24, 34, 58))
        .stroke(Stroke::new(1.2_f32, ACCENT_BLUE))
        .corner_radius(CornerRadius::same(10))
        .inner_margin(Margin::same(10))
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new("🚀 First-Run Setup").size(13.0).strong().color(Color32::WHITE));
                let gpu = if app.gen_status.gpu_name.is_empty() {
                    "Local GPU".to_string()
                } else if app.gen_status.gpu_vram_mb > 0 {
                    format!("{} ({:.0} GB)", app.gen_status.gpu_name, app.gen_status.gpu_vram_mb as f64 / 1024.0)
                } else {
                    app.gen_status.gpu_name.clone()
                };
                badge(ui, &gpu, ACCENT_GREEN);
            });
            if let Some(pack) = rec_pack {
                ui.label(RichText::new(&pack.title).size(12.0).strong());
                ui.label(RichText::new(&pack.description).size(11.0).color(TEXT_MUTED));
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    if pack.downloading {
                        badge(ui, "⬇ Downloading Starter Pack...", ACCENT_AMBER);
                    } else if ui
                        .add(primary_button(&format!("⬇ Install Recommended ({:.1} GB)", pack.missing_gb)))
                        .clicked()
                    {
                        app.api.send(ApiCommand::DownloadStarterPack(pack.id.clone()));
                    }
                    if ui.button("🌐 Browse CivitAI").clicked() {
                        app.show_civitai_modal = true;
                    }
                });
            }
        });
    ui.add_space(8.0);
}

fn render_intent_cards(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    ui.horizontal(|ui| {
        ui.label(RichText::new("What do you want to create?").size(13.5).strong().color(Color32::WHITE));
        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
            if !app.gen_status.comfyui_running {
                let starting = app.busy_flags.contains("start_comfy");
                if ui
                    .add_enabled(!starting, egui::Button::new(if starting { "Starting..." } else { "▶ Start Engine" }))
                    .clicked()
                {
                    app.busy_flags.insert("start_comfy".into());
                    app.api.send(ApiCommand::StartComfyUi);
                }
            } else {
                badge(ui, "● GPU Ready", ACCENT_GREEN);
            }
        });
    });
    ui.add_space(6.0);

    let intents = [
        (SimpleIntent::Photo, "📷 Realistic Photo", "Candid photos, memes & text"),
        (SimpleIntent::Friend, "👥 Friend in Scene", "Put @Friends into any photo"),
        (SimpleIntent::Anime, "🎨 Anime / 2.5D Art", "Illustrious XL + auto tags"),
        (SimpleIntent::Animate, "🎬 Animate Photo", "Turn any image into video"),
        (SimpleIntent::AudioVideo, "🔊 Video + Sound", "Video with synced audio/SFX"),
        (SimpleIntent::Talk, "🗣 Talking Friend", "Clone voice + lip-sync video"),
    ];

    let card_w = ((ui.available_width() - 8.0) / 2.0).max(150.0);
    egui::Grid::new("simple_intent_grid")
        .num_columns(2)
        .spacing([8.0, 8.0])
        .show(ui, |ui| {
            for (idx, (intent, title, sub)) in intents.iter().enumerate() {
                let active = app.simple_intent == *intent;
                let fill = if active {
                    Color32::from_rgb(30, 58, 112)
                } else {
                    BG_CARD
                };
                let stroke = if active {
                    Stroke::new(1.5_f32, ACCENT_BLUE)
                } else {
                    Stroke::new(1.0_f32, BORDER_SUBTLE)
                };
                let frame_resp = Frame::new()
                    .fill(fill)
                    .stroke(stroke)
                    .corner_radius(CornerRadius::same(9))
                    .inner_margin(Margin::symmetric(10, 8))
                    .show(ui, |ui| {
                        ui.set_width(card_w - 20.0);
                        ui.label(
                            RichText::new(*title)
                                .size(12.5)
                                .strong()
                                .color(if active { Color32::WHITE } else { TEXT_PRIMARY }),
                        );
                        ui.label(RichText::new(*sub).size(10.5).color(TEXT_MUTED));
                    });
                let click_resp = ui.interact(
                    frame_resp.response.rect,
                    ui.id().with(("intent_card", idx)),
                    Sense::click(),
                );
                if click_resp.clicked() {
                    app.simple_intent = *intent;
                    app.checkpoint_override.clear();
                    if intent.is_video() {
                        app.set_studio_mode(StudioMode::Video, true, Some("auto".into()));
                        app.want_audio = *intent == SimpleIntent::AudioVideo;
                    } else {
                        app.set_studio_mode(StudioMode::Image, true, Some("auto".into()));
                    }
                }
                if idx % 2 == 1 {
                    ui.end_row();
                }
            }
        });
}

fn render_simple_talk_card(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    card_frame().show(ui, |ui| {
        ui.horizontal(|ui| {
            ui.label(RichText::new("🗣 Make a Friend Talk").size(13.0).strong());
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if ui.small_button("+ Add Friend & Voice").clicked() {
                    app.show_cast_modal = true;
                }
            });
        });
        ui.label(
            RichText::new("Clones your friend's saved voice offline (F5-TTS) and animates their face speaking it.")
                .size(11.0)
                .color(TEXT_MUTED),
        );
        ui.add_space(6.0);

        let voice_cast: Vec<_> = app.gen_status.cast.iter().filter(|c| c.has_voice).cloned().collect();
        if voice_cast.is_empty() {
            ui.label(
                RichText::new("No friends have a voice clip yet — click '+ Add Friend & Voice' with a face photo and 5-12s voice clip.")
                    .size(11.5)
                    .color(ACCENT_AMBER),
            );
            if ui.add(primary_button("👥 Open Friends / Cast Book")).clicked() {
                app.show_cast_modal = true;
            }
            return;
        }

        let sel_name = voice_cast
            .iter()
            .find(|c| c.id == app.voice_cast_id)
            .map(|c| c.name.as_str())
            .unwrap_or("Pick a friend");
        egui::ComboBox::from_id_salt("simple_talk_cast_cb")
            .selected_text(format!("🎙 {sel_name}"))
            .width(ui.available_width() - 4.0)
            .show_ui(ui, |ui| {
                for c in &voice_cast {
                    ui.selectable_value(&mut app.voice_cast_id, c.id.clone(), format!("{} ({})", c.name, c.handle));
                }
            });

        ui.add_space(6.0);
        ui.label(RichText::new("What should they say?").size(11.5).strong());
        ui.add(
            egui::TextEdit::multiline(&mut app.voice_text)
                .desired_rows(3)
                .desired_width(f32::INFINITY)
                .hint_text("e.g. Bro I literally told you the server wasn't gonna crash this time..."),
        );

        ui.add_space(4.0);
        ui.horizontal(|ui| {
            ui.label(RichText::new("Voice Speed:").size(11.0).color(TEXT_MUTED));
            ui.add(egui::Slider::new(&mut app.voice_speed, 0.75..=1.35).step_by(0.05));
        });

        ui.add_space(6.0);
        if ui
            .add(primary_button("🗣 Create Talking Video").min_size(Vec2::new(ui.available_width(), 38.0)))
            .clicked()
        {
            let txt = app.voice_text.trim().to_string();
            if txt.is_empty() || app.voice_cast_id.is_empty() {
                app.push_toast("Pick a friend with voice and type dialogue first.", ToastKind::Warning);
            } else {
                app.api.send(ApiCommand::TalkSyncVideo(json!({
                    "cast_id": app.voice_cast_id,
                    "text": txt,
                    "prompt": app.prompt_input.trim(),
                    "style_preset": app.preset_id,
                    "speed": app.voice_speed,
                    "add_to_timeline": true,
                })));
            }
        }
    });
}

fn render_simple_create_card(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    let is_video = app.simple_intent.is_video();
    let mode = if is_video { StudioMode::Video } else { StudioMode::Image };
    let eff_model_id = app.resolve_auto_model_for_intent(mode, Some(app.simple_intent.as_api_intent()));
    let eff_model = app.gen_status.models.get(&eff_model_id).cloned();

    // Optional Photo & @Friend Strip (prominent for Friend / Animate / AudioVideo)
    let needs_photo_row = matches!(
        app.simple_intent,
        SimpleIntent::Friend | SimpleIntent::Animate | SimpleIntent::AudioVideo
    );
    if needs_photo_row || app.ref1.is_some() {
        card_frame().show(ui, |ui| {
            ui.horizontal(|ui| {
                let lbl = match app.simple_intent {
                    SimpleIntent::Friend => "Friend Photo(s) — or click @Name",
                    SimpleIntent::Animate => "Photo to Animate",
                    _ => "Optional Start Photo",
                };
                ui.label(RichText::new(lbl).size(11.5).strong().color(TEXT_MUTED));
                ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                    if ui.small_button("+ Add Friend").clicked() {
                        app.show_cast_modal = true;
                    }
                });
            });

            // Quick @Friend chips
            let cast = app.gen_status.cast.clone();
            if !cast.is_empty() {
                ui.horizontal_wrapped(|ui| {
                    for m in &cast {
                        let on = app.ref1.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false)
                            || app.ref2.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false);
                        let btn = egui::Button::new(
                            RichText::new(&m.handle)
                                .size(11.5)
                                .color(if on { Color32::WHITE } else { TEXT_PRIMARY }),
                        )
                        .fill(if on { ACCENT_BLUE } else { BG_ELEVATED });
                        if ui.add(btn).clicked() {
                            let att = RefAttachment {
                                path: m.photo_path.clone(),
                                filename: format!("{} ({})", m.name, m.handle),
                            };
                            if app.ref1.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false) {
                                app.ref1 = None;
                            } else if app.ref2.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false) {
                                app.ref2 = None;
                            } else if app.ref1.is_none() || is_video {
                                app.ref1 = Some(att);
                            } else {
                                app.ref2 = Some(att);
                            }
                        }
                    }
                });
            }

            ui.add_space(4.0);
            ui.horizontal(|ui| {
                if let Some(r1) = app.ref1.clone() {
                    if let Some(tex) = app.api.get_or_load_image(&format!("sr1_{}", r1.filename), &r1.path, 96).cloned() {
                        ui.add(Image::new(&tex).fit_to_exact_size(Vec2::splat(32.0)).corner_radius(CornerRadius::same(4)));
                    }
                    ui.label(RichText::new(&r1.filename).size(11.5).strong());
                    if ui.small_button("✕").clicked() {
                        app.ref1 = None;
                    }
                } else if ui.button("📷 Pick Photo...").clicked() {
                    if let Some(p) = rfd::FileDialog::new()
                        .add_filter("Images", &["png", "jpg", "jpeg", "webp", "bmp"])
                        .pick_file()
                    {
                        app.api.send(ApiCommand::UploadRef { slot: RefSlot::Ref1, path: p });
                    }
                }

                if app.simple_intent == SimpleIntent::Friend && app.ref1.is_some() {
                    if let Some(r2) = app.ref2.clone() {
                        ui.label(RichText::new(format!("+ {}", r2.filename)).size(11.0).color(ACCENT_BLUE));
                        if ui.small_button("✕").clicked() {
                            app.ref2 = None;
                        }
                    } else if ui.small_button("+ 2nd Friend").clicked() {
                        if let Some(p) = rfd::FileDialog::new()
                            .add_filter("Images", &["png", "jpg", "jpeg", "webp", "bmp"])
                            .pick_file()
                        {
                            app.api.send(ApiCommand::UploadRef { slot: RefSlot::Ref2, path: p });
                        }
                    }
                }
            });
        });
        ui.add_space(8.0);
    }

    // Main Prompt + Clean Options Card
    card_frame().show(ui, |ui| {
        ui.label(RichText::new("Describe what you want").size(12.5).strong());
        let hint = match app.simple_intent {
            SimpleIntent::Photo => "e.g. Candid late-night photo of a stray cat sitting on a neon-lit gas pump...",
            SimpleIntent::Friend => "e.g. @Jake holding a giant trophy outside a Waffle House at 2AM, harsh camera flash...",
            SimpleIntent::Anime => "e.g. Cyberpunk swordsman standing on a rainy neon rooftop at midnight, dramatic glow...",
            SimpleIntent::Animate => "e.g. He slowly turns to camera with a stunned expression while sparks fly behind him...",
            SimpleIntent::AudioVideo => "e.g. Dramatic breaking news studio anchor shouting with loud sirens and mic rustling...",
            SimpleIntent::Talk => "",
        };
        ui.add(
            egui::TextEdit::multiline(&mut app.prompt_input)
                .desired_rows(4)
                .desired_width(f32::INFINITY)
                .hint_text(hint),
        );

        ui.add_space(6.0);

        // Quick 1-click Visual Look pills
        ui.label(RichText::new("Visual Look").size(11.0).strong().color(TEXT_MUTED));
        let quick_presets = [
            ("none", "Natural"),
            ("raw_iphone", "iPhone Flash"),
            ("disposable_35mm", "90s 35mm"),
            ("bodycam", "Bodycam"),
            ("ring_doorbell", "Doorbell"),
            ("cinema_35mm", "Cinematic"),
            ("anime_90s", "90s Anime"),
        ];
        ui.horizontal_wrapped(|ui| {
            for (pid, lbl) in quick_presets {
                let on = app.preset_id == pid;
                let btn = egui::Button::new(
                    RichText::new(lbl)
                        .size(11.0)
                        .color(if on { Color32::WHITE } else { TEXT_MUTED }),
                )
                .fill(if on { ACCENT_BLUE } else { BG_ELEVATED })
                .corner_radius(CornerRadius::same(12));
                if ui.add(btn).clicked() {
                    app.preset_id = pid.to_string();
                }
            }
        });

        ui.add_space(6.0);

        // Community CivitAI Checkpoint Override (only when compatible custom checkpoints are installed)
        if !is_video {
            let matching_ckpts: Vec<_> = app
                .gen_status
                .checkpoints
                .iter()
                .filter(|c| !c.is_builtin && c.compatible_models.iter().any(|m| m == &eff_model_id))
                .cloned()
                .collect();
            if !matching_ckpts.is_empty() {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("CivitAI Look:").size(11.0).color(TEXT_MUTED));
                    let sel_txt = if app.checkpoint_override.is_empty() {
                        "Default Engine".to_string()
                    } else {
                        app.checkpoint_override.clone()
                    };
                    egui::ComboBox::from_id_salt("simple_ckpt_override")
                        .selected_text(sel_txt)
                        .width((ui.available_width() - 80.0).max(120.0))
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut app.checkpoint_override, String::new(), "Default Engine");
                            for ck in &matching_ckpts {
                                ui.selectable_value(
                                    &mut app.checkpoint_override,
                                    ck.name.clone(),
                                    format!("{} ({:.1} GB)", ck.filename, ck.size_gb),
                                );
                            }
                        });
                });
                ui.add_space(4.0);
            }
        }

        // Clean Quality Checkboxes (Zero jargon!)
        ui.horizontal_wrapped(|ui| {
            ui.checkbox(&mut app.simple_auto_enhance, "✨ Smart Prompt")
                .on_hover_text("Automatically optimizes your plain-English description for the chosen AI engine (e.g. Danbooru tags for Illustrious XL). Zero censorship.");
            if !is_video {
                ui.checkbox(&mut app.simple_four_grid, "🎲 4-Pick Grid")
                    .on_hover_text("Generate 4 different variations at once so you can pick your favorite");
                ui.checkbox(&mut app.simple_auto_hd, "✨ Auto 2× HD")
                    .on_hover_text("Automatically upscale the finished image 2× with GPU 4x-UltraSharp");
            } else {
                ui.checkbox(&mut app.simple_auto_hd, "🎞 Smooth 32fps (RIFE)")
                    .on_hover_text("Automatically interpolate generated video to silky 32fps via GPU RIFE v4.26");
            }
        });

        ui.add_space(6.0);

        // Resolved Engine Pill + Direct Download CTA if missing
        let is_ready = eff_model.as_ref().map(|m| m.ready).unwrap_or(false);
        ui.horizontal(|ui| {
            let eng_name = eff_model
                .as_ref()
                .map(|m| m.display_name.as_str())
                .unwrap_or(&eff_model_id);
            ui.label(RichText::new("Engine:").size(10.5).color(TEXT_MUTED));
            badge(
                ui,
                eng_name,
                if is_ready { ACCENT_GREEN } else { ACCENT_AMBER },
            );
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if ui.small_button("🌐 CivitAI").on_hover_text("Browse & install community checkpoints & LoRAs").clicked() {
                    app.show_civitai_modal = true;
                }
            });
        });

        ui.add_space(8.0);

        if let Some(m) = &eff_model {
            if !m.ready {
                let is_dl = m.download.as_ref().map(|d| d.status == "downloading").unwrap_or(false);
                if let Some(d) = m.download.as_ref().filter(|d| d.status == "downloading") {
                    ui.label(
                        RichText::new(format!("⬇ {} ({:.1}% · {:.1} MB/s)", d.current_file, d.pct, d.speed_mbps))
                            .size(11.0)
                            .color(ACCENT_AMBER),
                    );
                    ui.add(egui::ProgressBar::new((d.pct as f32 / 100.0).clamp(0.0, 1.0)).show_percentage());
                } else if !is_dl {
                    if ui
                        .add(
                            primary_button(&format!("⬇ Install {} ({:.1} GB)", m.display_name, m.missing_gb))
                                .min_size(Vec2::new(ui.available_width(), 38.0)),
                        )
                        .clicked()
                    {
                        app.api.send(ApiCommand::DownloadModel(m.id.clone()));
                    }
                }
                return;
            }
        }

        let create_lbl = if is_video {
            "🎬 Create Video"
        } else if app.simple_four_grid {
            "✨ Create 4 Variations"
        } else {
            "✨ Create"
        };
        if ui
            .add_enabled(
                is_ready,
                primary_button(create_lbl).min_size(Vec2::new(ui.available_width(), 40.0)),
            )
            .clicked()
        {
            submit_simple_creation(app, is_video);
        }
    });
}

fn submit_simple_creation(app: &mut ClipForgeApp, is_video: bool) {
    let prompt = app.prompt_input.trim().to_string();
    if prompt.is_empty() {
        app.push_toast("Describe what you want to create first.", ToastKind::Warning);
        return;
    }
    let intent = app.simple_intent.as_api_intent();
    let loras = app.active_loras_json();

    if is_video {
        let body = json!({
            "prompt": prompt,
            "model": "auto",
            "intent": intent,
            "image_path": app.ref1.as_ref().map(|r| r.path.clone()),
            "style_preset": app.preset_id,
            "match_photo_aspect": true,
            "want_audio": app.simple_intent == SimpleIntent::AudioVideo,
            "auto_enhance": app.simple_auto_enhance,
            "auto_smooth_fps": app.simple_auto_hd,
            "loras": loras,
            "add_to_timeline": true,
        });
        app.api.send(ApiCommand::GenerateVideo(body));
    } else {
        let mut body = json!({
            "prompt": prompt,
            "model": "auto",
            "intent": intent,
            "image_path": app.ref1.as_ref().map(|r| r.path.clone()),
            "image_path_2": app.ref2.as_ref().map(|r| r.path.clone()),
            "style_preset": app.preset_id,
            "match_photo_aspect": true,
            "auto_enhance": app.simple_auto_enhance,
            "auto_polish": app.simple_auto_hd && !app.simple_four_grid,
            "batch_size": if app.simple_four_grid { 4 } else { 1 },
            "loras": loras,
            "add_to_timeline": false,
        });
        if !app.checkpoint_override.trim().is_empty() {
            body["checkpoint_override"] = json!(app.checkpoint_override.trim());
        }
        app.api.send(ApiCommand::GenerateImage(body));
    }
}

fn render_simple_active_job(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    let active = app
        .gen_status
        .jobs
        .iter()
        .find(|j| j.status == "running" || j.status == "queued")
        .cloned();
    if let Some(j) = active {
        ui.add_space(8.0);
        card_frame().show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new(format!("⚡ Generating ({})...", j.model)).strong().size(12.0));
                ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                    if ui.small_button("✕ Stop").clicked() {
                        app.api.send(ApiCommand::CancelJob(j.id.clone()));
                    }
                });
            });
            ui.add(egui::ProgressBar::new((j.progress_pct as f32 / 100.0).clamp(0.03, 1.0)).show_percentage());
            if !j.message.is_empty() {
                ui.label(RichText::new(&j.message).size(10.5).color(TEXT_MUTED));
            }
        });
    }
}

fn render_simple_result_canvas(app: &mut ClipForgeApp, ui: &mut egui::Ui, ctx: &egui::Context) {
    let active_job = app
        .gen_status
        .jobs
        .iter()
        .find(|j| j.status == "running" || j.status == "queued")
        .cloned();

    let selected_item: Option<GalleryImage> = app
        .simple_selected_image
        .as_deref()
        .and_then(|fnm| app.gen_status.gallery.iter().find(|g| g.filename == fnm).cloned())
        .or_else(|| app.gen_status.gallery.first().cloned());

    let strip_h = 84.0;
    let chips_h = 46.0;
    let stage_h = (ui.available_height() - strip_h - chips_h - 24.0).max(240.0);

    // 1. Main Large Preview Stage
    let (stage_rect, _) = ui.allocate_exact_size(Vec2::new(ui.available_width(), stage_h), Sense::hover());
    let painter = ui.painter_at(stage_rect);
    painter.rect_filled(stage_rect, 10.0, BG_PANEL);
    painter.rect_stroke(stage_rect, 10.0, Stroke::new(1.0_f32, BORDER_SUBTLE), egui::StrokeKind::Inside);

    if let Some(j) = active_job.as_ref().filter(|j| j.preview_data_url.is_some()) {
        if let Some(durl) = &j.preview_data_url {
            if let Some(tex) = app.api.get_live_preview_texture(ctx, &j.id, durl).cloned() {
                let tsz = tex.size_vec2();
                let sc = ((stage_rect.width() - 24.0) / tsz.x.max(1.0))
                    .min((stage_rect.height() - 42.0) / tsz.y.max(1.0));
                let r = Rect::from_center_size(stage_rect.center(), tsz * sc);
                painter.image(tex.id(), r, Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)), Color32::WHITE);
                painter.text(
                    Pos2::new(stage_rect.center().x, stage_rect.bottom() - 16.0),
                    egui::Align2::CENTER_CENTER,
                    format!("Live GPU Preview · {}% · {}", j.progress_pct, j.message),
                    egui::FontId::proportional(12.0),
                    ACCENT_BLUE,
                );
            }
        }
    } else if let Some(item) = &selected_item {
        let key = format!("simple_full_{}", item.filename);
        if let Some(tex) = app.api.get_or_load_image(&key, &item.image_path, 1536).cloned() {
            let tsz = tex.size_vec2();
            let sc = ((stage_rect.width() - 24.0) / tsz.x.max(1.0))
                .min((stage_rect.height() - 28.0) / tsz.y.max(1.0));
            let r = Rect::from_center_size(stage_rect.center(), tsz * sc);
            painter.image(tex.id(), r, Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)), Color32::WHITE);
            let click_resp = ui.interact(r, ui.id().with("simple_stage_click"), Sense::click());
            if click_resp.clicked() {
                app.open_lightbox(item.clone());
            }
        } else {
            painter.text(
                stage_rect.center(),
                egui::Align2::CENTER_CENTER,
                "Loading result...",
                egui::FontId::proportional(14.0),
                TEXT_MUTED,
            );
        }
    } else {
        painter.text(
            Pos2::new(stage_rect.center().x, stage_rect.center().y - 12.0),
            egui::Align2::CENTER_CENTER,
            "✨ Your creations appear here",
            egui::FontId::proportional(18.0),
            TEXT_PRIMARY,
        );
        painter.text(
            Pos2::new(stage_rect.center().x, stage_rect.center().y + 14.0),
            egui::Align2::CENTER_CENTER,
            "Pick a card on the left, describe what you want in plain English, and click Create.",
            egui::FontId::proportional(12.5),
            TEXT_MUTED,
        );
    }

    ui.add_space(8.0);

    // 2. 1-Click "Fix / Steer This Result" Chip Bar
    Frame::new()
        .fill(BG_PANEL)
        .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
        .corner_radius(CornerRadius::same(8))
        .inner_margin(Margin::symmetric(10, 6))
        .show(ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                if let Some(item) = &selected_item {
                    ui.label(RichText::new("Fix / Steer:").size(11.5).strong().color(TEXT_MUTED));

                    if ui.button("👤 Fix Face").on_hover_text("Auto-detect & sharpen every face at 512×512").clicked() {
                        app.api.send(ApiCommand::DetailFaces { filename: item.filename.clone() });
                    }

                    if ui.button("🎲 4 Similar").on_hover_text("Generate 4 close variations keeping this composition").clicked() {
                        let p = item
                            .meta
                            .as_ref()
                            .and_then(|m| m.raw_prompt.clone().or_else(|| m.prompt.clone()))
                            .unwrap_or_else(|| app.prompt_input.clone());
                        let body = json!({
                            "prompt": if p.trim().is_empty() { "refined natural variation" } else { p.trim() },
                            "model": "auto",
                            "image_path": item.image_path,
                            "parent_image": item.filename,
                            "match_photo_aspect": true,
                            "denoise": 0.55,
                            "batch_size": 4,
                            "seed": -1,
                            "add_to_timeline": false,
                        });
                        app.api.send(ApiCommand::GenerateImage(body));
                    }

                    if ui.button("🎯 Follow Prompt Closer").on_hover_text("Re-run with Smart Prompt enhancement and stronger guidance").clicked() {
                        let m = item.meta.as_ref();
                        let p = m
                            .and_then(|x| x.raw_prompt.clone().or_else(|| x.prompt.clone()))
                            .unwrap_or_else(|| app.prompt_input.clone());
                        let model_id = m.and_then(|x| x.model.clone()).unwrap_or_else(|| "auto".into());
                        let next_steps = m.and_then(|x| x.steps).map(|s| s + 4);
                        let next_cfg = match model_id.as_str() {
                            "illustrious_xl" => Some(6.8),
                            "chroma_hd" => Some(5.0),
                            _ => None,
                        };
                        let mut body = json!({
                            "prompt": if p.trim().is_empty() { app.prompt_input.trim() } else { p.trim() },
                            "model": model_id,
                            "image_path": m.and_then(|x| x.image_path.clone()),
                            "image_path_2": m.and_then(|x| x.image_path_2.clone()),
                            "style_preset": m.and_then(|x| x.style_preset.clone()),
                            "checkpoint_override": m.and_then(|x| x.checkpoint_override.clone()),
                            "match_photo_aspect": true,
                            "auto_enhance": true,
                            "seed": -1,
                            "batch_size": 1,
                            "add_to_timeline": false,
                        });
                        if let Some(st) = next_steps {
                            body["steps"] = json!(st);
                        }
                        if let Some(c) = next_cfg {
                            body["cfg"] = json!(c);
                        }
                        app.api.send(ApiCommand::GenerateImage(body));
                    }

                    let polishing = app.busy_flags.contains("polish");
                    if ui
                        .add_enabled(!polishing, egui::Button::new("✨ 2× Sharper"))
                        .on_hover_text("GPU 4x-UltraSharp neural 2× HD polish")
                        .clicked()
                    {
                        app.busy_flags.insert("polish".into());
                        app.api.send(ApiCommand::PolishImage {
                            filename: item.filename.clone(),
                            scale: 2,
                        });
                    }

                    if ui.button("🖌 Fix Spot").on_hover_text("Paint over any spot to replace just that region").clicked() {
                        app.open_lightbox(item.clone());
                        app.lightbox.mask_mode = true;
                    }

                    if ui.add(primary_button("🎬 Bring to Life")).clicked() {
                        app.simple_intent = SimpleIntent::Animate;
                        app.set_studio_mode(StudioMode::Video, true, Some("auto".into()));
                        app.ref1 = Some(RefAttachment {
                            path: item.image_path.clone(),
                            filename: item.filename.clone(),
                        });
                        app.push_toast("Loaded image into Animate Photo — describe the motion and click Create Video!", ToastKind::Success);
                    }

                    if ui.button("🎞 Edit in Pro NLE").clicked() {
                        app.add_path_to_timeline(item.image_path.clone());
                        app.ui_mode = UiMode::Pro;
                    }
                } else {
                    ui.label(
                        RichText::new("1-click Fix Face · 4 Similar · Follow Prompt Closer · 2× Sharper · Mask Inpaint unlock as soon as you generate.")
                            .size(11.0)
                            .color(TEXT_MUTED),
                    );
                }
            });
        });

    ui.add_space(8.0);

    // 3. Recent Creations Filmstrip (Images + Recent Videos shortcut)
    Frame::new()
        .fill(BG_PANEL)
        .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
        .corner_radius(CornerRadius::same(8))
        .inner_margin(Margin::symmetric(8, 6))
        .show(ui, |ui| {
            ui.set_min_height(66.0);
            egui::ScrollArea::horizontal()
                .id_salt("simple_filmstrip_scroll")
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        let gallery = app.gen_status.gallery.clone();
                        for g in gallery.iter().take(18) {
                            let is_sel = selected_item
                                .as_ref()
                                .map(|s| s.filename == g.filename)
                                .unwrap_or(false);
                            let key = format!("gal_{}", g.filename);
                            let tex = app.api.get_or_load_image(&key, &g.image_path, 160).cloned();
                            Frame::new()
                                .fill(BG_ELEVATED)
                                .stroke(Stroke::new(
                                    if is_sel { 2.0_f32 } else { 1.0_f32 },
                                    if is_sel { ACCENT_BLUE } else { BORDER_SUBTLE },
                                ))
                                .corner_radius(CornerRadius::same(6))
                                .inner_margin(Margin::same(2))
                                .show(ui, |ui| {
                                    if let Some(t) = tex {
                                        let r = ui
                                            .add(
                                                Image::new(&t)
                                                    .fit_to_exact_size(Vec2::splat(56.0))
                                                    .corner_radius(CornerRadius::same(4))
                                                    .sense(Sense::click()),
                                            )
                                            .on_hover_text(&g.filename);
                                        if r.clicked() {
                                            app.simple_selected_image = Some(g.filename.clone());
                                        }
                                    } else if ui.small_button(&g.filename[..g.filename.len().min(8)]).clicked() {
                                        app.simple_selected_image = Some(g.filename.clone());
                                    }
                                });
                        }
                        if !app.gen_status.videos.is_empty() {
                            ui.separator();
                            let vcnt = app.gen_status.videos.len();
                            if ui
                                .button(format!("🎬 {vcnt} Videos → Open Pro Player"))
                                .clicked()
                            {
                                app.ui_mode = UiMode::Pro;
                            }
                        }
                    });
                });
        });
}
