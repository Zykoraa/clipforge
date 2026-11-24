use crate::api::{ApiCommand, RefSlot, ToastKind};
use crate::app::{ActiveLora, ClipForgeApp, RefAttachment, SimpleAsset, SimpleIntent, StudioMode, UiMode};
use crate::models::{GalleryImage, VaultVideo};
use crate::theme::*;
use egui::{Align, Color32, CornerRadius, Frame, Image, Layout, Margin, Pos2, Rect, RichText, Sense, Stroke, Vec2};
use serde_json::json;

pub fn render_simple_workspace(app: &mut ClipForgeApp, ctx: &egui::Context) {
    // Left Creator Panel (Plain English, zero jargon)
    egui::SidePanel::left("simple_creator_panel")
        .resizable(true)
        .default_width(425.0)
        .min_width(355.0)
        .max_width(530.0)
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

    // Right Main Result Stage (Displays BOTH Photos AND Playable Videos + Continue Video + Fix Chips)
    egui::CentralPanel::default()
        .frame(Frame::new().fill(BG_ROOT).inner_margin(Margin::same(14)))
        .show(ctx, |ui| {
            render_simple_result_canvas(app, ui, ctx);
        });
}

fn friendly_file_label(raw: &str) -> String {
    let base = raw.rsplit(['/', '\\']).next().unwrap_or(raw);
    let stem = base
        .strip_suffix(".safetensors")
        .or_else(|| base.strip_suffix(".gguf"))
        .or_else(|| base.strip_suffix(".ckpt"))
        .or_else(|| base.strip_suffix(".pt"))
        .unwrap_or(base);
    stem.replace('_', " ").replace('-', " ")
}

fn reveal_in_os(path: &str) {
    if path.is_empty() {
        return;
    }
    #[cfg(windows)]
    {
        let _ = std::process::Command::new("explorer")
            .arg(format!("/select,{path}"))
            .spawn();
    }
    #[cfg(not(windows))]
    {
        if let Some(parent) = std::path::Path::new(path).parent() {
            let _ = std::process::Command::new("xdg-open").arg(parent).spawn();
        }
    }
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
            ui.label(RichText::new("🚀 Quick Setup (One-Time Download)").size(13.0).strong().color(Color32::WHITE));
            if let Some(pack) = rec_pack {
                ui.label(
                    RichText::new("Download the recommended pack for your graphics card so you can generate photos & videos offline.")
                        .size(11.0)
                        .color(TEXT_MUTED),
                );
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    if pack.downloading {
                        badge(ui, "⬇ Downloading Pack...", ACCENT_AMBER);
                    } else if ui
                        .add(primary_button(&format!("⬇ Install Recommended ({:.1} GB)", pack.missing_gb)))
                        .clicked()
                    {
                        app.api.send(ApiCommand::DownloadStarterPack(pack.id.clone()));
                    }
                    if ui.button("✨ Get Styles").clicked() {
                        app.show_civitai_modal = true;
                    }
                });
            }
        });
    ui.add_space(8.0);
}

fn render_intent_cards(app: &mut ClipForgeApp, ui: &mut egui::Ui) {
    ui.horizontal(|ui| {
        ui.label(RichText::new("What do you want to make?").size(13.5).strong().color(Color32::WHITE));
        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
            if !app.gen_status.comfyui_running {
                let starting = app.busy_flags.contains("start_comfy");
                if ui
                    .add_enabled(!starting, egui::Button::new(if starting { "Starting..." } else { "▶ Start AI" }))
                    .clicked()
                {
                    app.busy_flags.insert("start_comfy".into());
                    app.api.send(ApiCommand::StartComfyUi);
                }
            } else {
                badge(ui, "● Ready", ACCENT_GREEN);
            }
        });
    });
    ui.add_space(6.0);

    let intents = [
        (SimpleIntent::Photo, "📷 Photo", "Realistic images & text"),
        (SimpleIntent::Friend, "👥 Friend in Scene", "Put a friend into any photo"),
        (SimpleIntent::Anime, "🎨 Anime / Art", "Illustration & stylized art"),
        (SimpleIntent::Animate, "🎬 Animate Photo", "Turn any photo into video"),
        (SimpleIntent::AudioVideo, "🔊 Video + Sound", "Video with matching audio"),
        (SimpleIntent::Talk, "🗣 Talking Friend", "Clone voice & lip-sync"),
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
                    if !intent.is_video() {
                        app.continue_parent_video = None;
                    }
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
            RichText::new("Clones your friend's saved voice offline and animates their face speaking your line.")
                .size(11.0)
                .color(TEXT_MUTED),
        );
        ui.add_space(6.0);

        let voice_cast: Vec<_> = app.gen_status.cast.iter().filter(|c| c.has_voice).cloned().collect();
        if voice_cast.is_empty() {
            ui.label(
                RichText::new("Add a friend with a face photo and a short 5–12s voice clip first.")
                    .size(11.5)
                    .color(ACCENT_AMBER),
            );
            if ui.add(primary_button("👥 Add a Friend")).clicked() {
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
                .hint_text("Type the exact line you want them to speak..."),
        );

        ui.add_space(4.0);
        ui.horizontal(|ui| {
            ui.label(RichText::new("Voice Speed:").size(11.0).color(TEXT_MUTED));
            ui.add(egui::Slider::new(&mut app.voice_speed, 0.75..=1.35).step_by(0.05));
        });

        ui.add_space(6.0);
        if ui
            .add(primary_button("🗣 Create Talking Video").min_size(Vec2::new(ui.available_width(), 40.0)))
            .clicked()
        {
            let txt = app.voice_text.trim().to_string();
            if txt.is_empty() || app.voice_cast_id.is_empty() {
                app.push_toast("Pick a friend and type what they should say first.", ToastKind::Warning);
            } else {
                app.api.send(ApiCommand::TalkSyncVideo(json!({
                    "cast_id": app.voice_cast_id,
                    "text": txt,
                    "prompt": app.prompt_input.trim(),
                    "style_preset": app.preset_id,
                    "speed": app.voice_speed,
                    "add_to_timeline": false,
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

    // Clear visual banner when continuing from a previous video clip!
    if let Some(parent_v) = app.continue_parent_video.clone() {
        Frame::new()
            .fill(Color32::from_rgb(24, 48, 86))
            .stroke(Stroke::new(1.2_f32, ACCENT_BLUE))
            .corner_radius(CornerRadius::same(8))
            .inner_margin(Margin::symmetric(10, 7))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(
                        RichText::new("🔗 Continuing from your last video")
                            .size(12.0)
                            .strong()
                            .color(Color32::WHITE),
                    );
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        if ui.small_button("✕ Start Fresh").clicked() {
                            app.continue_parent_video = None;
                            app.ref1 = None;
                        }
                    });
                });
                ui.label(
                    RichText::new(format!("Using the exact ending frame of {parent_v} — describe what happens next!"))
                        .size(10.5)
                        .color(TEXT_MUTED),
                );
            });
        ui.add_space(6.0);
    }

    // Photo & Saved Friends picker
    let needs_photo_row = matches!(
        app.simple_intent,
        SimpleIntent::Friend | SimpleIntent::Animate | SimpleIntent::AudioVideo
    );
    if needs_photo_row || app.ref1.is_some() {
        card_frame().show(ui, |ui| {
            ui.horizontal(|ui| {
                let lbl = if app.continue_parent_video.is_some() {
                    "Starting Frame (End of Previous Video)"
                } else {
                    match app.simple_intent {
                        SimpleIntent::Friend => "Friend Photo(s)",
                        SimpleIntent::Animate => "Photo to Animate",
                        _ => "Optional Starting Photo",
                    }
                };
                ui.label(RichText::new(lbl).size(11.5).strong().color(TEXT_MUTED));
                ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                    if ui.small_button("+ Add Friend").clicked() {
                        app.show_cast_modal = true;
                    }
                });
            });

            let cast = app.gen_status.cast.clone();
            if !cast.is_empty() && app.continue_parent_video.is_none() {
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
                        ui.add(Image::new(&tex).fit_to_exact_size(Vec2::splat(36.0)).corner_radius(CornerRadius::same(4)));
                    }
                    ui.label(RichText::new(&r1.filename).size(11.5).strong());
                    if ui.small_button("✕").clicked() {
                        app.ref1 = None;
                        app.continue_parent_video = None;
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

    // Main Prompt + Clean Options Card (zero AI jargon!)
    card_frame().show(ui, |ui| {
        let prompt_heading = if app.continue_parent_video.is_some() {
            "What happens next?"
        } else {
            "Describe what you want"
        };
        ui.label(RichText::new(prompt_heading).size(12.5).strong());
        let hint = if app.continue_parent_video.is_some() {
            "e.g. He suddenly turns around laughing while the lights flicker and sparks fly..."
        } else {
            match app.simple_intent {
                SimpleIntent::Photo => "e.g. Candid late-night photo of a stray cat sitting on a neon-lit gas pump...",
                SimpleIntent::Friend => "e.g. @Jake holding a giant trophy outside a Waffle House at 2AM, camera flash...",
                SimpleIntent::Anime => "e.g. Cyberpunk swordsman standing on a rainy neon rooftop at midnight...",
                SimpleIntent::Animate => "e.g. He slowly turns to the camera with a stunned expression while sparks fly...",
                SimpleIntent::AudioVideo => "e.g. Breaking news anchor shouting dramatically with loud sirens in the background...",
                SimpleIntent::Talk => "",
            }
        };
        ui.add(
            egui::TextEdit::multiline(&mut app.prompt_input)
                .desired_rows(4)
                .desired_width(f32::INFINITY)
                .hint_text(hint),
        );

        ui.add_space(6.0);

        // Quick Camera / Visual Vibe chips
        ui.label(RichText::new("Camera Vibe").size(11.0).strong().color(TEXT_MUTED));
        let quick_presets = [
            ("none", "Natural"),
            ("raw_iphone", "iPhone Flash"),
            ("disposable_35mm", "90s Film"),
            ("bodycam", "Bodycam"),
            ("ring_doorbell", "Doorbell"),
            ("cinema_35mm", "Movie"),
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

        // Installed Community Art Styles (only shown if user downloaded custom Full Styles — zero jargon!)
        if !is_video {
            let custom_styles: Vec<_> = app
                .gen_status
                .checkpoints
                .iter()
                .filter(|c| !c.is_builtin && c.compatible_models.iter().any(|m| m == &eff_model_id))
                .cloned()
                .collect();
            if !custom_styles.is_empty() {
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Art Style:").size(11.0).color(TEXT_MUTED));
                    let sel_txt = if app.checkpoint_override.is_empty() {
                        "Default Look".to_string()
                    } else {
                        friendly_file_label(&app.checkpoint_override)
                    };
                    egui::ComboBox::from_id_salt("simple_style_override")
                        .selected_text(sel_txt)
                        .width((ui.available_width() - 80.0).max(120.0))
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut app.checkpoint_override, String::new(), "Default Look");
                            for ck in &custom_styles {
                                ui.selectable_value(
                                    &mut app.checkpoint_override,
                                    ck.name.clone(),
                                    friendly_file_label(&ck.filename),
                                );
                            }
                        });
                });
            }
        }

        // Installed Style Boosters (only user-installed non-builtin add-ons, as simple toggle pills!)
        let user_boosters: Vec<_> = app
            .gen_status
            .loras
            .iter()
            .filter(|l| !l.is_builtin)
            .cloned()
            .collect();
        if !user_boosters.is_empty() {
            ui.add_space(6.0);
            ui.label(RichText::new("Style Boosters").size(11.0).strong().color(TEXT_MUTED));
            ui.horizontal_wrapped(|ui| {
                for l in &user_boosters {
                    let is_on = app.active_loras.contains_key(&l.name);
                    let lbl = friendly_file_label(&l.filename);
                    let btn = egui::Button::new(
                        RichText::new(if is_on { format!("✓ {lbl}") } else { lbl })
                            .size(10.5)
                            .color(if is_on { Color32::WHITE } else { TEXT_MUTED }),
                    )
                    .fill(if is_on { ACCENT_PURPLE } else { BG_ELEVATED })
                    .corner_radius(CornerRadius::same(12));
                    if ui.add(btn).clicked() {
                        if is_on {
                            app.active_loras.remove(&l.name);
                        } else if app.active_loras.len() < 3 {
                            app.active_loras.insert(
                                l.name.clone(),
                                ActiveLora {
                                    name: l.name.clone(),
                                    strength: 0.8,
                                    trigger: l.trigger.clone(),
                                },
                            );
                        } else {
                            app.push_toast("You can enable up to 3 Style Boosters at once.", ToastKind::Warning);
                        }
                    }
                }
            });
        }

        ui.add_space(6.0);

        // Plain-English quality switches
        ui.horizontal_wrapped(|ui| {
            ui.checkbox(&mut app.simple_auto_enhance, "✨ Auto-improve prompt")
                .on_hover_text("Expands short ideas into rich visual detail automatically — never censors.");
            if !is_video {
                ui.checkbox(&mut app.simple_four_grid, "🎲 Make 4 options")
                    .on_hover_text("Creates 4 different versions at once so you can pick the best one.");
                ui.checkbox(&mut app.simple_auto_hd, "✨ Extra sharp HD")
                    .on_hover_text("Automatically sharpens and doubles resolution when finished.");
            } else {
                ui.checkbox(&mut app.simple_auto_hd, "✨ Extra smooth motion")
                    .on_hover_text("Automatically doubles framerate for silky-smooth video motion.");
            }
        });

        ui.add_space(8.0);

        // If the needed generator isn't downloaded yet, offer a clean 1-click download button right here
        let is_ready = eff_model.as_ref().map(|m| m.ready).unwrap_or(false);
        if let Some(m) = &eff_model {
            if !m.ready {
                let is_dl = m.download.as_ref().map(|d| d.status == "downloading").unwrap_or(false);
                if let Some(d) = m.download.as_ref().filter(|d| d.status == "downloading") {
                    ui.label(
                        RichText::new(format!("⬇ Downloading ({:.0}% · {:.1} MB/s)...", d.pct, d.speed_mbps))
                            .size(11.0)
                            .color(ACCENT_AMBER),
                    );
                    ui.add(egui::ProgressBar::new((d.pct as f32 / 100.0).clamp(0.0, 1.0)).show_percentage());
                } else if !is_dl {
                    let friendly_kind = match app.simple_intent {
                        SimpleIntent::Photo => "Photo Creator",
                        SimpleIntent::Friend => "Friend Photo Editor",
                        SimpleIntent::Anime => "Anime & Art Style",
                        SimpleIntent::Animate => "Video Animator",
                        SimpleIntent::AudioVideo => "Video + Sound Creator",
                        SimpleIntent::Talk => "Talking Video Creator",
                    };
                    if ui
                        .add(
                            primary_button(&format!("⬇ Download {friendly_kind} ({:.1} GB)", m.missing_gb))
                                .min_size(Vec2::new(ui.available_width(), 40.0)),
                        )
                        .clicked()
                    {
                        app.api.send(ApiCommand::DownloadModel(m.id.clone()));
                    }
                }
                return;
            }
        }

        let create_lbl = if app.continue_parent_video.is_some() {
            "🎬 Create Next Part (+5s)"
        } else if is_video {
            "🎬 Create Video"
        } else if app.simple_four_grid {
            "✨ Create 4 Options"
        } else {
            "✨ Create"
        };
        if ui
            .add_enabled(
                is_ready,
                primary_button(create_lbl).min_size(Vec2::new(ui.available_width(), 42.0)),
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
        app.push_toast("Type a quick description of what you want first.", ToastKind::Warning);
        return;
    }
    let intent = app.simple_intent.as_api_intent();
    let loras = app.active_loras_json();

    if is_video {
        let mut body = json!({
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
            "add_to_timeline": false,
        });
        if let Some(pv) = app.continue_parent_video.take() {
            body["parent_video"] = json!(pv);
        }
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
                let kind_lbl = if j.kind == "video" { "Creating video..." } else { "Creating image..." };
                ui.label(RichText::new(format!("⚡ {kind_lbl}")).strong().size(12.0));
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

/// Trace `parent_video` chain backwards so Continue Video Part 1 -> Part 2 -> Part 3 can combine in 1 click!
fn build_video_chain(videos: &[VaultVideo], current: &VaultVideo) -> Vec<String> {
    let mut chain: Vec<String> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut cur = Some(current.clone());
    while let Some(v) = cur {
        if !seen.insert(v.filename.clone()) {
            break;
        }
        chain.insert(0, v.filename.clone());
        let parent = v.meta.as_ref().and_then(|m| m.parent_video.clone());
        cur = parent.and_then(|pf| videos.iter().find(|x| x.filename == pf).cloned());
    }
    chain
}

enum ResolvedSimpleItem {
    Image(GalleryImage),
    Video(VaultVideo),
}

fn resolve_selected_item(app: &ClipForgeApp) -> Option<ResolvedSimpleItem> {
    match &app.simple_selected {
        Some(SimpleAsset::Image(fnm)) => app
            .gen_status
            .gallery
            .iter()
            .find(|g| &g.filename == fnm)
            .cloned()
            .map(ResolvedSimpleItem::Image),
        Some(SimpleAsset::Video(fnm)) => app
            .gen_status
            .videos
            .iter()
            .find(|v| &v.filename == fnm)
            .cloned()
            .map(ResolvedSimpleItem::Video),
        None => None,
    }
    .or_else(|| {
        let g = app.gen_status.gallery.first();
        let v = app.gen_status.videos.first();
        match (g, v) {
            (Some(img), Some(vid)) => {
                if vid.mtime > img.mtime {
                    Some(ResolvedSimpleItem::Video(vid.clone()))
                } else {
                    Some(ResolvedSimpleItem::Image(img.clone()))
                }
            }
            (Some(img), None) => Some(ResolvedSimpleItem::Image(img.clone())),
            (None, Some(vid)) => Some(ResolvedSimpleItem::Video(vid.clone())),
            (None, None) => None,
        }
    })
}

fn render_simple_result_canvas(app: &mut ClipForgeApp, ui: &mut egui::Ui, ctx: &egui::Context) {
    let active_job = app
        .gen_status
        .jobs
        .iter()
        .find(|j| j.status == "running" || j.status == "queued")
        .cloned();

    let selected = resolve_selected_item(app);
    let is_video_selected = matches!(selected, Some(ResolvedSimpleItem::Video(_)));

    let strip_h = 84.0;
    let transport_h = if is_video_selected { 38.0 } else { 0.0 };
    let chips_h = 46.0;
    let stage_h = (ui.available_height() - strip_h - chips_h - transport_h - 28.0).max(220.0);

    // 1. Main Large Preview Stage (Live Progress OR Photo OR Native GPU Video Player!)
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
                    format!("Live Preview · {}%", j.progress_pct),
                    egui::FontId::proportional(12.0),
                    ACCENT_BLUE,
                );
            }
        }
    } else if let Some(ResolvedSimpleItem::Video(vid)) = &selected {
        let drawn = app.player.paint_single_frame(&painter, stage_rect);
        if !drawn {
            painter.text(
                stage_rect.center(),
                egui::Align2::CENTER_CENTER,
                "Loading video...",
                egui::FontId::proportional(14.0),
                TEXT_MUTED,
            );
        }
        // Click video viewport to toggle play/pause
        let click_r = ui.interact(stage_rect, ui.id().with("simple_vid_click"), Sense::click());
        if click_r.clicked() {
            let dur = app.player.single_video_dur.max(0.5);
            app.player.toggle_play(dur);
        }
        // Subtle badge showing it's a playable video
        let _ = vid;
    } else if let Some(ResolvedSimpleItem::Image(item)) = &selected {
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
                "Loading photo...",
                egui::FontId::proportional(14.0),
                TEXT_MUTED,
            );
        }
    } else {
        painter.text(
            Pos2::new(stage_rect.center().x, stage_rect.center().y - 12.0),
            egui::Align2::CENTER_CENTER,
            "✨ Your photos & videos appear here",
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

    // 1b. Native Video Play/Pause & Scrub Bar (right under video inside Simple Mode!)
    if let Some(ResolvedSimpleItem::Video(_)) = &selected {
        ui.add_space(4.0);
        Frame::new()
            .fill(BG_PANEL)
            .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
            .corner_radius(CornerRadius::same(8))
            .inner_margin(Margin::symmetric(10, 4))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    let dur = app.player.single_video_dur.max(0.5);
                    let play_lbl = if app.player.is_playing { "⏸ Pause" } else { "▶ Play" };
                    if ui.add(primary_button(play_lbl)).clicked() {
                        app.player.toggle_play(dur);
                    }
                    let mut t = app.player.playhead_sec;
                    let slider = ui.add(
                        egui::Slider::new(&mut t, 0.0..=dur)
                            .show_value(false)
                            .trailing_fill(true),
                    );
                    if slider.changed() {
                        app.player.seek_to(t, dur);
                    }
                    ui.label(
                        RichText::new(format!("{} / {}", format_time(app.player.playhead_sec), format_time(dur)))
                            .monospace()
                            .size(11.5)
                            .color(TEXT_MUTED),
                    );
                });
            });
    }

    ui.add_space(6.0);

    // 2. Context-Aware 1-Click Action Bar (Video Continue / Combine / Smooth OR Photo Fix Chips!)
    Frame::new()
        .fill(BG_PANEL)
        .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
        .corner_radius(CornerRadius::same(8))
        .inner_margin(Margin::symmetric(10, 6))
        .show(ui, |ui| {
            ui.horizontal_wrapped(|ui| match &selected {
                Some(ResolvedSimpleItem::Video(vid)) => {
                    let continuing = app.busy_flags.contains("continue_vid");
                    if ui
                        .add_enabled(!continuing, primary_button(if continuing { "Preparing..." } else { "⏭ Continue Video (+5s)" }))
                        .on_hover_text("Grabs the exact last frame so you can generate the next 5 seconds seamlessly right here!")
                        .clicked()
                    {
                        app.busy_flags.insert("continue_vid".into());
                        app.api.send(ApiCommand::ExtractVaultEndFrame { filename: vid.filename.clone() });
                    }

                    // If this clip is part of a Continue chain (2+ clips), offer 1-click Combine right here!
                    let chain = build_video_chain(&app.gen_status.videos, vid);
                    if chain.len() >= 2 {
                        let stitching = app.busy_flags.contains("stitch_vid");
                        if ui
                            .add_enabled(
                                !stitching,
                                egui::Button::new(
                                    RichText::new(if stitching {
                                        "Combining...".into()
                                    } else {
                                        format!("🔗 Combine All {} Parts", chain.len())
                                    })
                                    .strong()
                                    .color(Color32::WHITE),
                                )
                                .fill(ACCENT_GREEN),
                            )
                            .on_hover_text("Joins every continued part into one single continuous video file")
                            .clicked()
                        {
                            app.busy_flags.insert("stitch_vid".into());
                            app.api.send(ApiCommand::StitchVaultVideos { filenames: chain });
                        }
                    }

                    let smoothing = app.busy_flags.contains("smooth_vid");
                    if ui
                        .add_enabled(!smoothing, egui::Button::new(if smoothing { "Smoothing..." } else { "✨ Smoother Motion" }))
                        .on_hover_text("Doubles framerate for smoother, less choppy video")
                        .clicked()
                    {
                        app.busy_flags.insert("smooth_vid".into());
                        app.api.send(ApiCommand::SmoothVaultVideo { filename: vid.filename.clone() });
                    }

                    if ui.button("📂 Show File").on_hover_text("Open folder containing this MP4 file").clicked() {
                        reveal_in_os(&vid.video_path);
                    }

                    if ui.button("🎛 Edit in Pro").on_hover_text("Add captions, sound effects, or trim in Pro Editor").clicked() {
                        app.add_path_to_timeline(vid.video_path.clone());
                        app.player.stop_playback();
                        app.ui_mode = UiMode::Pro;
                    }
                }
                Some(ResolvedSimpleItem::Image(item)) => {
                    if ui.add(primary_button("🎬 Turn into Video")).clicked() {
                        app.simple_intent = SimpleIntent::Animate;
                        app.continue_parent_video = None;
                        app.set_studio_mode(StudioMode::Video, true, Some("auto".into()));
                        app.ref1 = Some(RefAttachment {
                            path: item.image_path.clone(),
                            filename: item.filename.clone(),
                        });
                        app.push_toast("Photo loaded! Describe the motion and click Create Video.", ToastKind::Success);
                    }

                    if ui.button("👤 Fix Face").on_hover_text("Detects and sharpens faces automatically").clicked() {
                        app.api.send(ApiCommand::DetailFaces { filename: item.filename.clone() });
                    }

                    if ui.button("🎲 4 Similar").on_hover_text("Generate 4 close variations keeping this layout").clicked() {
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

                    if ui.button("🎯 Match Prompt Better").on_hover_text("Re-runs with stronger prompt adherence").clicked() {
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
                        .add_enabled(!polishing, egui::Button::new("✨ Sharper HD"))
                        .on_hover_text("Doubles image sharpness and resolution")
                        .clicked()
                    {
                        app.busy_flags.insert("polish".into());
                        app.api.send(ApiCommand::PolishImage {
                            filename: item.filename.clone(),
                            scale: 2,
                        });
                    }

                    if ui.button("🖌 Edit a Spot").on_hover_text("Brush over any part of the photo to change just that area").clicked() {
                        app.open_lightbox(item.clone());
                        app.lightbox.mask_mode = true;
                    }

                    if ui.button("📂 Show File").on_hover_text("Open folder containing this image").clicked() {
                        reveal_in_os(&item.image_path);
                    }
                }
                None => {
                    ui.label(
                        RichText::new("Once you create a photo or video, 1-click buttons appear here (Continue Video, Fix Face, 4 Similar, Sharper HD, Show File).")
                            .size(11.0)
                            .color(TEXT_MUTED),
                    );
                }
            });
        });

    ui.add_space(8.0);

    // 3. Unified Chronological Recent Creations Filmstrip (BOTH Photos AND Videos together!)
    enum StripEntry {
        Img(GalleryImage),
        Vid(VaultVideo),
    }
    impl StripEntry {
        fn mtime(&self) -> f64 {
            match self {
                StripEntry::Img(g) => g.mtime,
                StripEntry::Vid(v) => v.mtime,
            }
        }
    }
    let mut entries: Vec<StripEntry> = Vec::new();
    for g in app.gen_status.gallery.iter().take(20) {
        entries.push(StripEntry::Img(g.clone()));
    }
    for v in app.gen_status.videos.iter().take(20) {
        entries.push(StripEntry::Vid(v.clone()));
    }
    entries.sort_by(|a, b| b.mtime().partial_cmp(&a.mtime()).unwrap_or(std::cmp::Ordering::Equal));
    entries.truncate(24);

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
                        for entry in &entries {
                            match entry {
                                StripEntry::Img(g) => {
                                    let is_sel = matches!(&selected, Some(ResolvedSimpleItem::Image(s)) if s.filename == g.filename);
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
                                                    .on_hover_text("Photo — click to view");
                                                if r.clicked() {
                                                    app.player.stop_playback();
                                                    app.simple_selected = Some(SimpleAsset::Image(g.filename.clone()));
                                                }
                                            } else if ui.small_button("📷").clicked() {
                                                app.player.stop_playback();
                                                app.simple_selected = Some(SimpleAsset::Image(g.filename.clone()));
                                            }
                                        });
                                }
                                StripEntry::Vid(v) => {
                                    let is_sel = matches!(&selected, Some(ResolvedSimpleItem::Video(s)) if s.filename == v.filename);
                                    let snippet: String = v
                                        .meta
                                        .as_ref()
                                        .and_then(|m| m.raw_prompt.as_deref())
                                        .unwrap_or(&v.filename)
                                        .chars()
                                        .take(14)
                                        .collect();
                                    let is_part = v.meta.as_ref().and_then(|m| m.parent_video.as_ref()).is_some();
                                    let badge_txt = if is_part { "🔗 Video" } else { "🎬 Video" };
                                    let fr = Frame::new()
                                        .fill(if is_sel { Color32::from_rgb(30, 58, 112) } else { BG_ELEVATED })
                                        .stroke(Stroke::new(
                                            if is_sel { 2.0_f32 } else { 1.0_f32 },
                                            if is_sel { ACCENT_BLUE } else { BORDER_SUBTLE },
                                        ))
                                        .corner_radius(CornerRadius::same(6))
                                        .inner_margin(Margin::symmetric(8, 6))
                                        .show(ui, |ui| {
                                            ui.set_min_size(Vec2::new(82.0, 48.0));
                                            ui.label(RichText::new(badge_txt).size(11.0).strong().color(Color32::WHITE));
                                            ui.label(RichText::new(snippet).size(10.0).color(TEXT_MUTED));
                                        });
                                    let click = ui.interact(
                                        fr.response.rect,
                                        ui.id().with(("vid_tile", &v.filename)),
                                        Sense::click(),
                                    );
                                    if click.clicked() {
                                        app.simple_selected = Some(SimpleAsset::Video(v.filename.clone()));
                                    }
                                }
                            }
                        }
                    });
                });
        });
}
