use crate::api::{ApiCommand, RefSlot, ToastKind};
use crate::app::{ActiveLora, ClipForgeApp, RefAttachment, StudioMode, VaultFilter};
use crate::theme::*;
use egui::{Color32, CornerRadius, Image, RichText, Sense, Vec2};
use serde_json::json;

pub fn render_studio_tab(app: &mut ClipForgeApp, ui: &mut egui::Ui, ctx: &egui::Context) {
    // 1. ComfyUI Engine Header Bar
    card_frame().show(ui, |ui| {
        ui.horizontal(|ui| {
            let online = app.gen_status.comfyui_running;
            let gpu = if app.gen_status.gpu_name.is_empty() {
                "Local GPU"
            } else {
                &app.gen_status.gpu_name
            };
            if online {
                badge(ui, &format!("● ComfyUI · {gpu}"), ACCENT_GREEN);
            } else {
                badge(ui, "○ ComfyUI Offline", ACCENT_AMBER);
                let starting = app.busy_flags.contains("start_comfy");
                if ui
                    .add_enabled(!starting, egui::Button::new(if starting { "Starting..." } else { "Start" }))
                    .clicked()
                {
                    app.busy_flags.insert("start_comfy".into());
                    app.api.send(ApiCommand::StartComfyUi);
                }
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.small_button("Models").clicked() {
                    app.show_models_modal = true;
                }
            });
        });
    });

    ui.add_space(6.0);

    // 2. Mode Switcher (Image | Video | Scene Storyboard)
    ui.horizontal(|ui| {
        let w = (ui.available_width() - 12.0) / 3.0;
        let img_act = app.studio_mode == StudioMode::Image;
        if ui
            .add_sized(
                [w, 28.0],
                egui::Button::new(RichText::new("🖼 Image").strong().color(if img_act { Color32::WHITE } else { TEXT_MUTED }))
                    .fill(if img_act { ACCENT_BLUE } else { BG_CARD }),
            )
            .clicked()
        {
            app.set_studio_mode(StudioMode::Image, true, None);
        }
        let vid_act = app.studio_mode == StudioMode::Video;
        if ui
            .add_sized(
                [w, 28.0],
                egui::Button::new(RichText::new("🎬 Video").strong().color(if vid_act { Color32::WHITE } else { TEXT_MUTED }))
                    .fill(if vid_act { ACCENT_BLUE } else { BG_CARD }),
            )
            .clicked()
        {
            app.set_studio_mode(StudioMode::Video, true, None);
        }
        if ui
            .add_sized(
                [w, 28.0],
                egui::Button::new(RichText::new("🎞 Scene").strong().color(Color32::from_rgb(196, 181, 253)))
                    .fill(Color32::from_rgb(46, 26, 82)),
            )
            .on_hover_text("Auto Multi-Beat Storyboard / Scene Chainer")
            .clicked()
        {
            if app.sb_concept.trim().is_empty() && !app.prompt_input.trim().is_empty() {
                app.sb_concept = app.prompt_input.trim().to_string();
            }
            app.show_storyboard_modal = true;
        }
    });

    ui.add_space(6.0);

    // 3. Saved Cast / Friends Strip
    card_frame().show(ui, |ui| {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Friends / Cast (@Name)").size(11.5).strong().color(TEXT_MUTED));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.small_button("+ Add Friend").clicked() {
                    app.show_cast_modal = true;
                }
            });
        });
        let cast_list = app.gen_status.cast.clone();
        if cast_list.is_empty() {
            ui.label(RichText::new("Save friends with faces + voices for 1-click @Name reuse.").size(11.0).color(TEXT_MUTED));
        } else {
            ui.horizontal_wrapped(|ui| {
                for m in &cast_list {
                    let attached = app.ref1.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false)
                        || app.ref2.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false);
                    let lbl = format!("{}{}", m.handle, if m.has_voice { " 🎙" } else { "" });
                    let btn = egui::Button::new(
                        RichText::new(lbl)
                            .size(11.5)
                            .color(if attached { Color32::WHITE } else { TEXT_PRIMARY }),
                    )
                    .fill(if attached { ACCENT_BLUE } else { BG_ELEVATED });
                    if ui.add(btn).clicked() {
                        let att = RefAttachment {
                            path: m.photo_path.clone(),
                            filename: format!("{} ({})", m.name, m.handle),
                        };
                        if app.ref1.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false) {
                            app.ref1 = None;
                        } else if app.ref2.as_ref().map(|r| r.path == m.photo_path).unwrap_or(false) {
                            app.ref2 = None;
                        } else if app.ref1.is_none() {
                            app.ref1 = Some(att);
                        } else if app.studio_mode == StudioMode::Image {
                            app.ref2 = Some(att);
                        } else {
                            app.ref1 = Some(att);
                        }
                    }
                }
            });
        }
    });

    ui.add_space(6.0);

    // 4. Model Picker + Auto Options + Inline Download Banner
    let mode_kind = if app.studio_mode == StudioMode::Image { "image" } else { "video" };
    let effective_id = if app.selected_model == "auto" || app.selected_model.is_empty() {
        app.resolve_auto_model_preview()
    } else {
        app.selected_model.clone()
    };
    let active_model = app.gen_status.models.get(&effective_id).cloned();

    card_frame().show(ui, |ui| {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Model").size(11.5).strong().color(TEXT_MUTED));
            if let Some(m) = &active_model {
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    badge(
                        ui,
                        if app.selected_model == "auto" { "AUTO" } else { &m.badge },
                        if m.ready { ACCENT_GREEN } else { ACCENT_AMBER },
                    );
                });
            }
        });

        let auto_label = format!(
            "✨ Auto Recommended → {}",
            active_model
                .as_ref()
                .map(|m| m.display_name.as_str())
                .unwrap_or(&effective_id)
        );
        let cur_label = if app.selected_model == "auto" {
            auto_label.clone()
        } else {
            active_model
                .as_ref()
                .map(|m| format!("{} {}", if m.ready { "✓" } else { "⬇" }, m.display_name))
                .unwrap_or_else(|| app.selected_model.clone())
        };

        let mode_models: Vec<_> = app
            .gen_status
            .models
            .values()
            .filter(|m| m.kind == mode_kind && !m.requires_audio)
            .cloned()
            .collect();

        egui::ComboBox::from_id_salt("gen_model_combo")
            .selected_text(cur_label)
            .width(ui.available_width() - 4.0)
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut app.selected_model, "auto".into(), auto_label);
                for m in &mode_models {
                    let st_txt = if m.ready {
                        "Ready".to_string()
                    } else if let Some(d) = m.download.as_ref().filter(|d| d.status == "downloading") {
                        format!("{:.0}%", d.pct)
                    } else {
                        format!("{:.1} GB", m.missing_gb)
                    };
                    let lbl = format!("{} {} ({st_txt})", if m.ready { "✓" } else { "⬇" }, m.display_name);
                    ui.selectable_value(&mut app.selected_model, m.id.clone(), lbl);
                }
            });

        if app.studio_mode == StudioMode::Video && app.selected_model == "auto" {
            ui.horizontal(|ui| {
                ui.checkbox(&mut app.want_audio, "🔊 Native Audio/SFX");
                ui.checkbox(&mut app.fast_draft, "⚡ Fast Draft (5B)");
            });
        }

        // Community / CivitAI Checkpoint Selector (when matching checkpoints exist on disk)
        if app.studio_mode == StudioMode::Image {
            let matching_ckpts: Vec<_> = app
                .gen_status
                .checkpoints
                .iter()
                .filter(|c| !c.is_builtin && c.compatible_models.iter().any(|m| m == &effective_id))
                .cloned()
                .collect();
            if !matching_ckpts.is_empty() {
                ui.add_space(4.0);
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Checkpoint:").size(10.5).color(TEXT_MUTED));
                    let sel_ck = if app.checkpoint_override.is_empty() {
                        "Default Base Weights".to_string()
                    } else {
                        app.checkpoint_override.clone()
                    };
                    egui::ComboBox::from_id_salt("pro_ckpt_override")
                        .selected_text(RichText::new(sel_ck).size(11.0))
                        .width((ui.available_width() - 62.0).max(120.0))
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut app.checkpoint_override, String::new(), "Default Base Weights");
                            for ck in &matching_ckpts {
                                ui.selectable_value(
                                    &mut app.checkpoint_override,
                                    ck.name.clone(),
                                    format!("{} ({:.1} GB)", ck.filename, ck.size_gb),
                                );
                            }
                        });
                    if ui.small_button("🌐").on_hover_text("Install more checkpoints from CivitAI").clicked() {
                        app.show_civitai_modal = true;
                    }
                });
            }
        }

        if let Some(m) = &active_model {
            let best_hint = match m.id.as_str() {
                "z_image_turbo" => "Best for: Fast candid photos, visible text/signs & memes",
                "krea2_turbo" => "Best for: Studio editorial realism & crisp skin texture",
                "lustify_sdxl" => "Best for: Unfiltered raw photorealistic scenes & edgy comedy",
                "pony_realism" => "Best for: Unfiltered expressive poses & stylized realism",
                "chroma_hd" => "Best for: Uncensored Flux posters & vivid imaginative scenes",
                "illustrious_xl" => "Best for: Anime, manga & Danbooru illustration art",
                "flux2_klein_9b" | "flux2_klein" => "Best for: Putting a friend photo seamlessly into any scene",
                "qwen_edit_2511" | "qwen_edit" => "Best for: 2-friend scene blending & direct photo edits",
                "wan22_i2v" => "Best for: Smooth realistic 5s video from a start photo",
                "wan22_remix_i2v" | "wan22_smoothmix_i2v" => "Best for: Unfiltered bold physical action & motion",
                "ltx23" => "Best for: Video WITH synchronized dialogue & sound effects",
                "wan22_t2v" => "Best for: Text-only cinema & dynamic action clips",
                "wan22_5b" => "Best for: Fast rough draft previews (~25s)",
                _ => "",
            };
            if !best_hint.is_empty() {
                ui.label(RichText::new(best_hint).size(10.5).strong().color(Color32::from_rgb(165, 195, 255)));
            }
            if !m.description.is_empty() {
                ui.label(RichText::new(&m.description).size(10.5).color(TEXT_MUTED));
            }
            if !m.ready {
                ui.add_space(4.0);
                let is_dl = m.download.as_ref().map(|d| d.status == "downloading").unwrap_or(false);
                if let Some(d) = m.download.as_ref().filter(|d| d.status == "downloading") {
                    ui.label(
                        RichText::new(format!(
                            "⬇ {} ({:.2}/{:.2} GB · {:.1} MB/s)",
                            d.current_file, d.downloaded_gb, d.total_gb, d.speed_mbps
                        ))
                        .size(11.0)
                        .color(ACCENT_AMBER),
                    );
                    ui.add(egui::ProgressBar::new((d.pct as f32 / 100.0).clamp(0.0, 1.0)).show_percentage());
                    if ui.small_button("Pause Download").clicked() {
                        app.api.send(ApiCommand::CancelDownload(m.id.clone()));
                    }
                } else if !is_dl {
                    ui.horizontal(|ui| {
                        if ui
                            .add(primary_button(&format!("⬇ Download ({:.1} GB)", m.missing_gb)))
                            .clicked()
                        {
                            app.api.send(ApiCommand::DownloadModel(m.id.clone()));
                        }
                        if ui.button("All Models").clicked() {
                            app.show_models_modal = true;
                        }
                    });
                }
            }
        }
    });

    ui.add_space(6.0);

    // 5. Reference Photo Slots (Photo #1, Photo #2, Copy Pose/Framing, End Frame)
    card_frame().show(ui, |ui| {
        render_ref_slot_row(
            app,
            ui,
            if app.studio_mode == StudioMode::Image {
                "Friend Photo #1 (or type @Name)"
            } else {
                "Start Frame / Friend Photo"
            },
            RefSlot::Ref1,
        );

        let show_ref2 = app.studio_mode == StudioMode::Image
            && (app.ref1.is_some()
                || active_model.as_ref().map(|m| m.supports_second_image).unwrap_or(false));
        if show_ref2 {
            ui.add_space(4.0);
            render_ref_slot_row(app, ui, "Second Friend Photo #2 (2-Person Scene)", RefSlot::Ref2);
        }

        if app.studio_mode == StudioMode::Image {
            ui.add_space(4.0);
            render_ref_slot_row(app, ui, "Copy Pose / Framing Guide (Optional)", RefSlot::Pose);
        }

        let show_end = app.studio_mode == StudioMode::Video
            && active_model.as_ref().map(|m| m.supports_end_image).unwrap_or(false);
        if show_end {
            ui.add_space(4.0);
            render_ref_slot_row(app, ui, "End Frame Morph Target (Optional)", RefSlot::EndFrame);
        }

        // Recent Ref Thumbnails quick-attach strip
        let recent = app.gen_status.ref_images.clone();
        if !recent.is_empty() {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label(RichText::new("Recent:").size(10.5).color(TEXT_MUTED));
                for r in recent.iter().take(6) {
                    let key = format!("ref_{}", r.filename);
                    let tex = app.api.get_or_load_image(&key, &r.image_path, 96).cloned();
                    if let Some(t) = tex {
                        let resp = ui
                            .add(Image::new(&t).fit_to_exact_size(Vec2::splat(30.0)).sense(Sense::click()))
                            .on_hover_text(&r.filename);
                        if resp.clicked() {
                            app.ref1 = Some(RefAttachment {
                                path: r.image_path.clone(),
                                filename: r.filename.clone(),
                            });
                        }
                    } else if ui.small_button(&r.filename[..r.filename.len().min(8)]).clicked() {
                        app.ref1 = Some(RefAttachment {
                            path: r.image_path.clone(),
                            filename: r.filename.clone(),
                        });
                    }
                }
            });
        }
    });

    ui.add_space(6.0);

    // 6. Style Presets + Video Camera Motion
    card_frame().show(ui, |ui| {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Style Preset").size(11.5).strong().color(TEXT_MUTED));
            for (cid, lbl) in [("all", "All"), ("real", "Real"), ("viral", "Viral"), ("cinema", "Cinema")] {
                let act = app.preset_cat == cid;
                if ui
                    .selectable_label(act, RichText::new(lbl).size(10.5))
                    .clicked()
                {
                    app.preset_cat = cid.to_string();
                }
            }
        });
        ui.horizontal_wrapped(|ui| {
            let presets: Vec<_> = app.gen_status.presets.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
            for (pid, meta) in presets {
                if app.preset_cat != "all" && pid != "none" && meta.category != app.preset_cat {
                    continue;
                }
                let act = app.preset_id == pid;
                let btn = egui::Button::new(
                    RichText::new(&meta.label)
                        .size(10.5)
                        .color(if act { Color32::WHITE } else { TEXT_MUTED }),
                )
                .fill(if act { ACCENT_BLUE } else { BG_ELEVATED })
                .corner_radius(CornerRadius::same(12));
                if ui.add(btn).on_hover_text(&meta.suffix).clicked() {
                    app.preset_id = pid;
                }
            }
        });

        if app.studio_mode == StudioMode::Video && !app.gen_status.camera_presets.is_empty() {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label(RichText::new("Camera:").size(11.5).color(TEXT_MUTED));
                let cur_cam = app
                    .gen_status
                    .camera_presets
                    .get(&app.camera_preset)
                    .map(|c| c.label.as_str())
                    .unwrap_or("Auto Camera");
                egui::ComboBox::from_id_salt("cam_preset_combo")
                    .selected_text(cur_cam)
                    .width(ui.available_width() - 6.0)
                    .show_ui(ui, |ui| {
                        for (cid, meta) in &app.gen_status.camera_presets {
                            ui.selectable_value(&mut app.camera_preset, cid.clone(), &meta.label);
                        }
                    });
            });
        }
    });

    ui.add_space(6.0);

    // 7. Refusal-Proof Director LLM Bar + Prompt / Negative Prompt
    card_frame().show(ui, |ui| {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Prompt").size(12.0).strong());
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let expanding = app.busy_flags.contains("expand");
                if ui
                    .add_enabled(
                        !expanding,
                        egui::Button::new(if expanding { "Thinking..." } else { "✨ Enhance" }),
                    )
                    .clicked()
                {
                    let cur = app.prompt_input.trim().to_string();
                    if cur.is_empty() {
                        app.push_toast("Type a rough idea first, then click ✨ Enhance.", ToastKind::Warning);
                    } else {
                        let idea = if !app.last_enhanced_prompt.is_empty()
                            && cur == app.last_enhanced_prompt
                            && !app.raw_idea.is_empty()
                        {
                            app.raw_idea.clone()
                        } else {
                            cur.clone()
                        };
                        app.raw_idea = idea.clone();
                        app.busy_flags.insert("expand".into());
                        app.api.send(ApiCommand::DirectorExpand(json!({
                            "idea": idea,
                            "mode": mode_kind,
                            "model_id": effective_id,
                            "model_name": if app.director_model.is_empty() { serde_json::Value::Null } else { json!(app.director_model) },
                            "literal_mode": app.director_literal,
                            "style_preset": app.preset_id,
                            "camera_preset": app.camera_preset,
                            "has_friend_photo": app.ref1.is_some(),
                            "has_second_photo": app.ref2.is_some(),
                            "has_end_frame": app.end_frame.is_some(),
                        })));
                    }
                }
                if !app.last_enhanced_prompt.is_empty() && !app.raw_idea.is_empty() {
                    if ui.small_button("↩ Raw").clicked() {
                        app.prompt_input = app.raw_idea.clone();
                        app.last_enhanced_prompt.clear();
                    }
                }
            });
        });

        // Director micro-bar: LLM selector + Literal toggle + 1-click Uncensored Ollama Pull
        ui.horizontal(|ui| {
            let dir = &app.gen_status.director;
            let auto_dir_lbl = if dir.available || dir.can_auto_start_lms {
                format!("Auto ({})", dir.recommended_model.as_deref().unwrap_or("Local LLM"))
            } else {
                "Built-in Literal".into()
            };
            let sel_dir_lbl = if app.director_model.is_empty() {
                auto_dir_lbl.clone()
            } else {
                app.director_model.clone()
            };
            egui::ComboBox::from_id_salt("director_llm_combo")
                .selected_text(RichText::new(sel_dir_lbl).size(10.5))
                .width(155.0)
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut app.director_model, String::new(), auto_dir_lbl);
                    for d in &dir.model_details {
                        let lbl = format!("{}{}", if d.uncensored { "🔓 " } else { "" }, d.id);
                        ui.selectable_value(&mut app.director_model, d.id.clone(), lbl);
                    }
                });

            ui.checkbox(&mut app.director_literal, RichText::new("Literal").size(10.5))
                .on_hover_text("Zero-sanitize literal prompt enhancer — never lets an LLM rewrite or refuse your prompt");

            let pulling = dir.pull.as_ref().map(|p| p.status == "pulling").unwrap_or(false);
            if dir.is_ollama && (!dir.has_uncensored || pulling) {
                let lbl = if pulling {
                    format!("⬇ {:.0}%", dir.pull.as_ref().map(|p| p.pct).unwrap_or(0.0))
                } else {
                    "⬇ Uncensored".into()
                };
                if ui.add_enabled(!pulling, egui::Button::new(RichText::new(lbl).size(10.5))).clicked() {
                    let tag = if dir.recommended_uncensored_pull.is_empty() {
                        "dolphin-llama3:8b".to_string()
                    } else {
                        dir.recommended_uncensored_pull.clone()
                    };
                    app.api.send(ApiCommand::DirectorPull { model_tag: tag });
                }
            }
        });

        let prompt_resp = ui.add(
            egui::TextEdit::multiline(&mut app.prompt_input)
                .desired_rows(3)
                .desired_width(f32::INFINITY)
                .hint_text(if app.studio_mode == StudioMode::Image {
                    "e.g. Candid flash photo of @Jake at 2AM arguing with a raccoon outside a gas station..."
                } else {
                    "e.g. Handheld camera shot of @Jake flipping burgers on a jet engine with sparks flying..."
                }),
        );
        if prompt_resp.changed() && app.prompt_input.trim() != app.last_enhanced_prompt {
            app.last_enhanced_prompt.clear();
        }

        ui.add(
            egui::TextEdit::singleline(&mut app.neg_prompt_input)
                .desired_width(f32::INFINITY)
                .hint_text("Negative prompt (auto-filled by ✨ Enhance)..."),
        );

        ui.add_space(4.0);

        // Resolution + Batch / Frames + Denoise
        ui.horizontal(|ui| {
            if app.studio_mode == StudioMode::Image {
                let res_opts = [
                    ("auto", "Auto Aspect"),
                    ("1024x1024", "1:1 (1024)"),
                    ("896x1152", "3:4 (896×1152)"),
                    ("1152x896", "4:3 (1152×896)"),
                    ("768x1344", "9:16 (768×1344)"),
                ];
                let lbl = res_opts.iter().find(|(v, _)| *v == app.image_res).map(|(_, l)| *l).unwrap_or(&app.image_res);
                egui::ComboBox::from_id_salt("img_res_cb")
                    .selected_text(lbl)
                    .width(135.0)
                    .show_ui(ui, |ui| {
                        for (v, l) in res_opts {
                            ui.selectable_value(&mut app.image_res, v.into(), l);
                        }
                    });
                ui.label(RichText::new("Batch:").size(11.0).color(TEXT_MUTED));
                for n in [1u32, 2, 4] {
                    if ui.selectable_label(app.batch_size == n, format!("{n}×")).clicked() {
                        app.batch_size = n;
                    }
                }
            } else {
                let res_opts = [
                    ("auto", "Auto Aspect"),
                    ("480x608", "4:5 Fast (480×608)"),
                    ("480x832", "9:16 Shorts (480×832)"),
                    ("832x480", "16:9 Wide (832×480)"),
                    ("512x512", "1:1 Square"),
                ];
                let lbl = res_opts.iter().find(|(v, _)| *v == app.video_res).map(|(_, l)| *l).unwrap_or(&app.video_res);
                egui::ComboBox::from_id_salt("vid_res_cb")
                    .selected_text(lbl)
                    .width(145.0)
                    .show_ui(ui, |ui| {
                        for (v, l) in res_opts {
                            ui.selectable_value(&mut app.video_res, v.into(), l);
                        }
                    });
                egui::ComboBox::from_id_salt("vid_frames_cb")
                    .selected_text(format!("{}f", app.num_frames))
                    .width(74.0)
                    .show_ui(ui, |ui| {
                        for (f, lbl) in [(49u32, "~2.5s (49f)"), (65, "~3.5s (65f)"), (73, "~3s (73f)"), (81, "~5s (81f)"), (97, "~4s (97f)")] {
                            ui.selectable_value(&mut app.num_frames, f, lbl);
                        }
                    });
            }
        });

        if app.studio_mode == StudioMode::Image && app.ref1.is_some() {
            ui.horizontal(|ui| {
                let tag = if app.denoise >= 0.99 { "Full" } else if app.denoise <= 0.45 { "Subtle" } else { "Vary" };
                ui.label(RichText::new(format!("Denoise ({tag}):")).size(11.0).color(TEXT_MUTED));
                ui.add(egui::Slider::new(&mut app.denoise, 0.25..=1.0).step_by(0.05));
            });
        }

        // Collapsible LoRA Stacker
        egui::CollapsingHeader::new(format!("🎛 LoRA Stacker ({} active)", app.active_loras.len()))
            .id_salt("lora_stacker_hdr")
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    if ui.small_button("+ Add .safetensors").clicked() {
                        if let Some(p) = rfd::FileDialog::new()
                            .add_filter("LoRA Weights", &["safetensors", "pt"])
                            .pick_file()
                        {
                            app.api.send(ApiCommand::UploadLora(p));
                        }
                    }
                    ui.label(RichText::new("Max 3 stacked").size(10.5).color(TEXT_MUTED));
                });
                let loras = app.gen_status.loras.clone();
                if loras.is_empty() {
                    ui.label(RichText::new("No LoRAs found in ComfyUI/models/loras/.").size(10.5).color(TEXT_MUTED));
                } else {
                    for l in &loras {
                        let mut is_on = app.active_loras.contains_key(&l.name);
                        ui.horizontal(|ui| {
                            if ui.checkbox(&mut is_on, RichText::new(&l.filename).size(11.0)).changed() {
                                if is_on {
                                    if app.active_loras.len() >= 3 {
                                        app.push_toast("Max 3 LoRAs stacked at once.", ToastKind::Warning);
                                    } else {
                                        app.active_loras.insert(
                                            l.name.clone(),
                                            ActiveLora {
                                                name: l.name.clone(),
                                                strength: 0.8,
                                                trigger: l.trigger.clone(),
                                            },
                                        );
                                    }
                                } else {
                                    app.active_loras.remove(&l.name);
                                }
                            }
                            badge(ui, &l.family, ACCENT_PURPLE);
                        });
                        if let Some(act) = app.active_loras.get_mut(&l.name) {
                            ui.horizontal(|ui| {
                                ui.add(egui::Slider::new(&mut act.strength, 0.1..=1.5).step_by(0.05).show_value(true));
                                let tr = ui.add(
                                    egui::TextEdit::singleline(&mut act.trigger)
                                        .desired_width(115.0)
                                        .hint_text("Trigger word..."),
                                );
                                if tr.lost_focus() && tr.changed() {
                                    app.api.send(ApiCommand::SaveLoraTrigger {
                                        name: act.name.clone(),
                                        trigger: act.trigger.clone(),
                                    });
                                }
                            });
                        }
                    }
                }
            });

        // Collapsible Advanced (Steps / CFG / Seed)
        egui::CollapsingHeader::new("⚙ Advanced (Steps / CFG / Seed)")
            .id_salt("adv_gen_hdr")
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Steps").size(11.0));
                    ui.add(egui::TextEdit::singleline(&mut app.steps_buf).desired_width(48.0).hint_text("Auto"));
                    ui.label(RichText::new("CFG").size(11.0));
                    ui.add(egui::TextEdit::singleline(&mut app.cfg_buf).desired_width(48.0).hint_text("Auto"));
                    ui.label(RichText::new("Seed").size(11.0));
                    ui.add(egui::TextEdit::singleline(&mut app.seed_buf).desired_width(82.0).hint_text("-1"));
                });
            });

        ui.checkbox(&mut app.auto_timeline, "Auto-add result to timeline");
        ui.add_space(4.0);

        let is_ready = active_model.as_ref().map(|m| m.ready).unwrap_or(false);
        let gen_btn_lbl = if !is_ready {
            "⬇ Download Model Weights First".to_string()
        } else if app.studio_mode == StudioMode::Image {
            if app.batch_size > 1 {
                format!("✨ Generate {} Meme Variations", app.batch_size)
            } else {
                "✨ Generate Image".to_string()
            }
        } else {
            "🎬 Generate Video".to_string()
        };

        if ui
            .add_enabled(is_ready, primary_button(&gen_btn_lbl).min_size(Vec2::new(ui.available_width(), 34.0)))
            .clicked()
        {
            submit_studio_generation(app);
        }
    });

    ui.add_space(6.0);

    // 8. Active / Recent GPU Jobs with Live Latent Previews & Instant Cancel
    let jobs = app.gen_status.jobs.clone();
    if !jobs.is_empty() {
        card_frame().show(ui, |ui| {
            ui.label(RichText::new("Live GPU Queue").size(11.5).strong().color(TEXT_MUTED));
            for j in jobs.iter().take(4) {
                ui.add_space(3.0);
                let col = match j.status.as_str() {
                    "completed" => ACCENT_GREEN,
                    "failed" => ACCENT_RED,
                    "canceled" => ACCENT_AMBER,
                    _ => ACCENT_BLUE,
                };
                ui.horizontal(|ui| {
                    let icon = match j.kind.as_str() {
                        "image" => "🖼",
                        "voice" => "🎙",
                        _ => "🎬",
                    };
                    let short_p: String = j.prompt.chars().take(24).collect();
                    ui.label(RichText::new(format!("{icon} {} · {short_p}", j.model)).size(11.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if j.status == "running" || j.status == "queued" {
                            if ui.small_button("✕ Stop").clicked() {
                                app.api.send(ApiCommand::CancelJob(j.id.clone()));
                            }
                        }
                        badge(ui, &j.status.to_uppercase(), col);
                    });
                });
                if j.status == "running" || j.status == "queued" {
                    ui.add(egui::ProgressBar::new((j.progress_pct as f32 / 100.0).clamp(0.03, 1.0)).show_percentage());
                    if let Some(prev_url) = &j.preview_data_url {
                        if let Some(tex) = app.api.get_live_preview_texture(ctx, &j.id, prev_url).cloned() {
                            ui.add(Image::new(&tex).max_width(ui.available_width().min(220.0)).corner_radius(CornerRadius::same(6)));
                        }
                    }
                }
                if !j.message.is_empty() {
                    ui.label(RichText::new(&j.message).size(10.5).color(TEXT_MUTED));
                }
            }
        });
        ui.add_space(6.0);
    }

    // 9. Unified Media Vault (Images + Videos + Live Search)
    let img_count = app.gen_status.gallery.len();
    let vid_count = app.gen_status.videos.len();
    if img_count + vid_count > 0 {
        card_frame().show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new(format!("Media Vault ({})", img_count + vid_count)).size(12.0).strong());
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    for (vf, lbl) in [
                        (VaultFilter::Videos, "Videos"),
                        (VaultFilter::Images, "Images"),
                        (VaultFilter::All, "All"),
                    ] {
                        if ui.selectable_label(app.vault_filter == vf, RichText::new(lbl).size(10.5)).clicked() {
                            app.vault_filter = vf;
                        }
                    }
                });
            });
            ui.add(
                egui::TextEdit::singleline(&mut app.vault_search)
                    .desired_width(f32::INFINITY)
                    .hint_text("Search prompt, @Friend, model, filename..."),
            );
            ui.add_space(4.0);

            let q = app.vault_search.trim().to_lowercase();

            if app.vault_filter != VaultFilter::Videos {
                let imgs = app.gen_status.gallery.clone();
                let filtered: Vec<_> = imgs
                    .into_iter()
                    .filter(|g| {
                        if q.is_empty() {
                            return true;
                        }
                        let hay = format!(
                            "{} {} {} {}",
                            g.filename,
                            g.meta.as_ref().and_then(|m| m.raw_prompt.as_deref()).unwrap_or(""),
                            g.meta.as_ref().and_then(|m| m.prompt.as_deref()).unwrap_or(""),
                            g.meta.as_ref().and_then(|m| m.model.as_deref()).unwrap_or("")
                        )
                        .to_lowercase();
                        hay.contains(&q)
                    })
                    .collect();

                let cols = 2usize;
                let card_w = ((ui.available_width() - 12.0) / cols as f32).max(115.0);
                egui::Grid::new("vault_img_grid")
                    .num_columns(cols)
                    .spacing([6.0, 6.0])
                    .show(ui, |ui| {
                        for (idx, item) in filtered.iter().enumerate() {
                            egui::Frame::new()
                                .fill(BG_ELEVATED)
                                .corner_radius(CornerRadius::same(6))
                                .inner_margin(egui::Margin::same(4))
                                .show(ui, |ui| {
                                    ui.set_width(card_w);
                                    let key = format!("gal_{}", item.filename);
                                    let tex = app.api.get_or_load_image(&key, &item.image_path, 320).cloned();
                                    if let Some(t) = tex {
                                        let resp = ui
                                            .add(
                                                Image::new(&t)
                                                    .fit_to_exact_size(Vec2::new(card_w - 8.0, 108.0))
                                                    .corner_radius(CornerRadius::same(4))
                                                    .sense(Sense::click()),
                                            )
                                            .on_hover_text("Click to open Lightbox (Mask Inpaint / A/B Compare / Fix Faces / HD)");
                                        if resp.clicked() {
                                            app.open_lightbox(item.clone());
                                        }
                                    } else {
                                        if ui.button(&item.filename[..item.filename.len().min(16)]).clicked() {
                                            app.open_lightbox(item.clone());
                                        }
                                    }
                                    ui.horizontal(|ui| {
                                        if ui.small_button("🎬").on_hover_text("Animate into Video").clicked() {
                                            app.animate_image_in_video(item.image_path.clone(), item.filename.clone());
                                        }
                                        if ui.small_button("🔍").on_hover_text("Open Lightbox").clicked() {
                                            app.open_lightbox(item.clone());
                                        }
                                        if ui.small_button("+").on_hover_text("Import to Media Bin").clicked() {
                                            app.add_path_to_timeline(item.image_path.clone());
                                        }
                                        if ui.small_button("✕").on_hover_text("Delete").clicked() {
                                            app.api.send(ApiCommand::DeleteGalleryImage(item.filename.clone()));
                                        }
                                    });
                                });
                            if (idx + 1) % cols == 0 {
                                ui.end_row();
                            }
                        }
                    });
            }

            if app.vault_filter != VaultFilter::Images {
                let vids = app.gen_status.videos.clone();
                let filtered: Vec<_> = vids
                    .into_iter()
                    .filter(|v| {
                        if q.is_empty() {
                            return true;
                        }
                        let hay = format!(
                            "{} {} {}",
                            v.filename,
                            v.meta.as_ref().and_then(|m| m.raw_prompt.as_deref()).unwrap_or(""),
                            v.meta.as_ref().and_then(|m| m.model.as_deref()).unwrap_or("")
                        )
                        .to_lowercase();
                        hay.contains(&q)
                    })
                    .collect();

                if !filtered.is_empty() {
                    ui.add_space(6.0);
                    ui.label(RichText::new("Generated Videos").size(11.0).strong().color(TEXT_MUTED));
                    for v in filtered.iter().take(12) {
                        egui::Frame::new()
                            .fill(BG_ELEVATED)
                            .corner_radius(CornerRadius::same(6))
                            .inner_margin(egui::Margin::same(6))
                            .show(ui, |ui| {
                                ui.horizontal(|ui| {
                                    ui.label(RichText::new(format!("🎬 {}", v.filename)).size(11.0));
                                });
                                ui.horizontal(|ui| {
                                    if ui.small_button("♻ Remix").clicked() {
                                        app.remix_vault_video(v);
                                    }
                                    if ui.small_button("+ Import").clicked() {
                                        app.add_path_to_timeline(v.video_path.clone());
                                    }
                                    if ui.small_button("✕").clicked() {
                                        app.api.send(ApiCommand::DeleteVaultVideo(v.filename.clone()));
                                    }
                                });
                            });
                    }
                }
            }
        });
    }
}

fn render_ref_slot_row(app: &mut ClipForgeApp, ui: &mut egui::Ui, label: &str, slot: RefSlot) {
    let cur = match slot {
        RefSlot::Ref1 => app.ref1.clone(),
        RefSlot::Ref2 => app.ref2.clone(),
        RefSlot::Pose => app.pose_ref.clone(),
        RefSlot::EndFrame => app.end_frame.clone(),
    };
    ui.horizontal(|ui| {
        if let Some(att) = &cur {
            let key = format!("slot_{}_{}", slot_key(slot), att.filename);
            if let Some(tex) = app.api.get_or_load_image(&key, &att.path, 96).cloned() {
                ui.add(Image::new(&tex).fit_to_exact_size(Vec2::splat(30.0)).corner_radius(CornerRadius::same(4)));
            }
            ui.vertical(|ui| {
                ui.label(RichText::new(label).size(10.0).color(TEXT_MUTED));
                ui.label(RichText::new(&att.filename).size(11.5).strong());
            });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.small_button("✕").clicked() {
                    match slot {
                        RefSlot::Ref1 => app.ref1 = None,
                        RefSlot::Ref2 => app.ref2 = None,
                        RefSlot::Pose => app.pose_ref = None,
                        RefSlot::EndFrame => app.end_frame = None,
                    }
                }
            });
        } else {
            if ui
                .button(format!("📷 Pick {label}"))
                .on_hover_text("Opens native OS file picker (or drag-and-drop an image anywhere on ClipForge)")
                .clicked()
            {
                if let Some(p) = rfd::FileDialog::new()
                    .add_filter("Images", &["png", "jpg", "jpeg", "webp", "bmp"])
                    .pick_file()
                {
                    app.api.send(ApiCommand::UploadRef { slot, path: p });
                }
            }
        }
    });
}

fn slot_key(slot: RefSlot) -> &'static str {
    match slot {
        RefSlot::Ref1 => "r1",
        RefSlot::Ref2 => "r2",
        RefSlot::Pose => "pose",
        RefSlot::EndFrame => "end",
    }
}

fn submit_studio_generation(app: &mut ClipForgeApp) {
    let prompt = app.prompt_input.trim().to_string();
    if prompt.is_empty() {
        app.push_toast("Enter a prompt first.", ToastKind::Warning);
        return;
    }
    let seed = app.seed_buf.trim().parse::<i64>().unwrap_or(-1);
    let steps: Option<u32> = app.steps_buf.trim().parse().ok();
    let cfg: Option<f64> = app.cfg_buf.trim().parse().ok();
    let loras = app.active_loras_json();

    if app.studio_mode == StudioMode::Image {
        let match_aspect = app.image_res == "auto";
        let (w, h) = parse_res_pair(&app.image_res);
        let mut body = json!({
            "prompt": prompt,
            "model": app.selected_model,
            "image_path": app.ref1.as_ref().map(|r| r.path.clone()),
            "image_path_2": app.ref2.as_ref().map(|r| r.path.clone()),
            "pose_image_path": app.pose_ref.as_ref().map(|r| r.path.clone()),
            "style_preset": app.preset_id,
            "width": w,
            "height": h,
            "match_photo_aspect": match_aspect,
            "steps": steps,
            "cfg": cfg,
            "denoise": app.denoise,
            "seed": seed,
            "batch_size": app.batch_size,
            "loras": loras,
            "add_to_timeline": app.auto_timeline,
        });
        if !app.neg_prompt_input.trim().is_empty() {
            body["negative_prompt"] = json!(app.neg_prompt_input.trim());
        }
        if !app.checkpoint_override.trim().is_empty() {
            body["checkpoint_override"] = json!(app.checkpoint_override.trim());
        }
        app.api.send(ApiCommand::GenerateImage(body));
    } else {
        let match_aspect = app.video_res == "auto";
        let (w, h) = parse_res_pair(&app.video_res);
        let mut body = json!({
            "prompt": prompt,
            "model": app.selected_model,
            "image_path": app.ref1.as_ref().map(|r| r.path.clone()),
            "end_image_path": app.end_frame.as_ref().map(|r| r.path.clone()),
            "style_preset": app.preset_id,
            "camera_preset": app.camera_preset,
            "width": w,
            "height": h,
            "match_photo_aspect": match_aspect,
            "want_audio": app.want_audio,
            "fast_draft": app.fast_draft,
            "num_frames": app.num_frames,
            "steps": steps,
            "cfg": cfg,
            "seed": seed,
            "loras": loras,
            "add_to_timeline": app.auto_timeline,
        });
        if !app.neg_prompt_input.trim().is_empty() {
            body["negative_prompt"] = json!(app.neg_prompt_input.trim());
        }
        app.api.send(ApiCommand::GenerateVideo(body));
    }
}

fn parse_res_pair(s: &str) -> (Option<u32>, Option<u32>) {
    if s == "auto" {
        return (None, None);
    }
    if let Some((w, h)) = s.split_once('x') {
        if let (Ok(wi), Ok(hi)) = (w.parse::<u32>(), h.parse::<u32>()) {
            return (Some(wi), Some(hi));
        }
    }
    (None, None)
}
