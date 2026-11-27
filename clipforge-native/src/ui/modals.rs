use crate::api::{ApiCommand, ToastKind};
use crate::app::{ClipForgeApp, MaskStroke};
use crate::models::{GalleryImage, StoryboardBeat};
use crate::theme::*;
use base64::Engine as _;
use egui::{Align, Color32, CornerRadius, Image, Pos2, Rect, RichText, Sense, Stroke, Vec2};
use serde_json::json;

pub fn render_all_modals(app: &mut ClipForgeApp, ctx: &egui::Context) {
    if app.lightbox.open {
        render_lightbox_modal(app, ctx);
    }
    if app.show_models_modal {
        render_models_modal(app, ctx);
    }
    if app.show_civitai_modal {
        render_civitai_modal(app, ctx);
    }
    if app.show_cast_modal {
        render_cast_modal(app, ctx);
    }
    if app.show_storyboard_modal {
        render_storyboard_modal(app, ctx);
    }
    if app.show_render_modal {
        render_render_modal(app, ctx);
    }
}

// ---------------------------------------------------------------------------
// 1. Image Lightbox (Version Chain + Canvas Mask Brush + A/B Split Compare + Follow-Up Edit)
// ---------------------------------------------------------------------------
fn render_lightbox_modal(app: &mut ClipForgeApp, ctx: &egui::Context) {
    let Some(item) = app.lightbox.item.clone() else {
        app.lightbox.open = false;
        return;
    };

    let mut open = app.lightbox.open;
    egui::Window::new(format!("🖼 {}", item.filename))
        .open(&mut open)
        .resizable(true)
        .collapsible(false)
        .default_size([860.0, 680.0])
        .anchor(egui::Align2::CENTER_CENTER, Vec2::ZERO)
        .show(ctx, |ui| {
            // Top meta + mode toggles
            ui.horizontal(|ui| {
                if let Some(m) = &item.meta {
                    let meta_str = format!(
                        "{} · seed {:?} · {}×{}",
                        m.model.as_deref().unwrap_or("image"),
                        m.seed.unwrap_or(-1),
                        m.width.unwrap_or(0),
                        m.height.unwrap_or(0)
                    );
                    ui.label(RichText::new(meta_str).size(11.0).color(TEXT_MUTED));
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let cmp_btn = egui::Button::new("⇄ A/B Compare")
                        .fill(if app.lightbox.compare_mode { ACCENT_BLUE } else { BG_ELEVATED });
                    if ui.add(cmp_btn).clicked() {
                        app.lightbox.compare_mode = !app.lightbox.compare_mode;
                        if app.lightbox.compare_mode {
                            app.lightbox.mask_mode = false;
                            if app.lightbox.compare_filename.is_empty() {
                                if let Some(pf) = item.meta.as_ref().and_then(|m| m.parent_image.clone()) {
                                    app.lightbox.compare_filename = pf;
                                } else if let Some(other) = app
                                    .gen_status
                                    .gallery
                                    .iter()
                                    .find(|g| g.filename != item.filename)
                                {
                                    app.lightbox.compare_filename = other.filename.clone();
                                }
                            }
                        }
                    }
                    let mask_btn = egui::Button::new("🖌 Mask Inpaint")
                        .fill(if app.lightbox.mask_mode { ACCENT_RED } else { BG_ELEVATED });
                    if ui.add(mask_btn).clicked() {
                        app.lightbox.mask_mode = !app.lightbox.mask_mode;
                        if app.lightbox.mask_mode {
                            app.lightbox.compare_mode = false;
                        }
                    }
                });
            });

            // Clickable Version History Chain
            let history = build_version_chain(&app.gen_status.gallery, &item);
            if history.len() > 1 {
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new("History:").size(10.5).color(TEXT_MUTED));
                    for (idx, node) in history.iter().enumerate() {
                        let tag = if idx == 0 {
                            "Original".to_string()
                        } else {
                            let kind = if node.meta.as_ref().and_then(|m| m.inpainted).unwrap_or(false) {
                                "Inpaint"
                            } else if node.meta.as_ref().and_then(|m| m.face_detailed).unwrap_or(false) {
                                "Faces"
                            } else if let Some(sc) = node.meta.as_ref().and_then(|m| m.hd_scale) {
                                if sc >= 4 { "4×HD" } else { "2×HD" }
                            } else {
                                "Edit"
                            };
                            format!("v{} ({kind})", idx + 1)
                        };
                        let act = node.filename == item.filename;
                        if ui.selectable_label(act, RichText::new(tag).size(11.0)).clicked() && !act {
                            app.open_lightbox(node.clone());
                            return;
                        }
                    }
                });
            }

            // Mask Brush Toolbar
            if app.lightbox.mask_mode {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Brush:").size(11.0));
                    ui.add(egui::Slider::new(&mut app.lightbox.mask_brush_size, 8.0..=96.0));
                    let er_btn = egui::Button::new("Eraser")
                        .fill(if app.lightbox.mask_eraser { ACCENT_AMBER } else { BG_ELEVATED });
                    if ui.add(er_btn).clicked() {
                        app.lightbox.mask_eraser = !app.lightbox.mask_eraser;
                    }
                    if ui.button("Undo").clicked() {
                        app.lightbox.mask_strokes.pop();
                    }
                    if ui.button("Clear").clicked() {
                        app.lightbox.mask_strokes.clear();
                    }
                    ui.label(
                        RichText::new("Paint over area to replace, then type edit below.")
                            .size(10.5)
                            .color(TEXT_MUTED),
                    );
                });
            }

            // A/B Compare Toolbar
            if app.lightbox.compare_mode {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Compare with:").size(11.0));
                    let others: Vec<_> = app
                        .gen_status
                        .gallery
                        .iter()
                        .filter(|g| g.filename != item.filename)
                        .cloned()
                        .collect();
                    egui::ComboBox::from_id_salt("ab_cmp_cb")
                        .selected_text(&app.lightbox.compare_filename)
                        .width(220.0)
                        .show_ui(ui, |ui| {
                            for o in &others {
                                ui.selectable_value(
                                    &mut app.lightbox.compare_filename,
                                    o.filename.clone(),
                                    &o.filename,
                                );
                            }
                        });
                    ui.label("Curtain:");
                    ui.add(egui::Slider::new(&mut app.lightbox.compare_split, 0.0..=1.0));
                });
            }

            ui.add_space(4.0);

            // Main Image Stage (GPU texture + Mask Brush Painter + A/B Split Curtain)
            let stage_h = (ui.available_height() - 92.0).max(240.0);
            let full_key = format!("full_{}", item.filename);
            let main_tex = app.api.get_or_load_image(&full_key, &item.image_path, 1536).cloned();

            let cmp_tex = if app.lightbox.compare_mode && !app.lightbox.compare_filename.is_empty() {
                app.gen_status
                    .gallery
                    .iter()
                    .find(|g| g.filename == app.lightbox.compare_filename)
                    .cloned()
                    .and_then(|o| {
                        let k = format!("full_{}", o.filename);
                        app.api.get_or_load_image(&k, &o.image_path, 1536).cloned()
                    })
            } else {
                None
            };

            let stage_size = Vec2::new(ui.available_width(), stage_h);
            let (stage_rect, _) = ui.allocate_exact_size(stage_size, Sense::hover());
            let painter = ui.painter_at(stage_rect);
            painter.rect_filled(stage_rect, 6.0, BG_ROOT);

            if let Some(tex) = main_tex {
                let tsz = tex.size_vec2();
                let sc = (stage_rect.width() / tsz.x.max(1.0)).min(stage_rect.height() / tsz.y.max(1.0));
                let img_rect = Rect::from_center_size(stage_rect.center(), tsz * sc);

                painter.image(
                    tex.id(),
                    img_rect,
                    Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)),
                    Color32::WHITE,
                );

                // A/B Split-Curtain Left Overlay
                if let Some(ctex) = cmp_tex {
                    let split = app.lightbox.compare_split.clamp(0.0, 1.0);
                    let cut_x = img_rect.left() + img_rect.width() * split;
                    let left_rect = Rect::from_min_max(img_rect.min, Pos2::new(cut_x, img_rect.bottom()));
                    painter.image(
                        ctex.id(),
                        left_rect,
                        Rect::from_min_max(Pos2::ZERO, Pos2::new(split, 1.0)),
                        Color32::WHITE,
                    );
                    painter.line_segment(
                        [Pos2::new(cut_x, img_rect.top()), Pos2::new(cut_x, img_rect.bottom())],
                        Stroke::new(2.0_f32, Color32::WHITE),
                    );
                }

                // Interactive Mask-Brush Overlay
                if app.lightbox.mask_mode {
                    let resp = ui.interact(img_rect, egui::Id::new("mask_brush_canvas"), Sense::drag());
                    if resp.drag_started() {
                        if let Some(pos) = resp.interact_pointer_pos() {
                            let nx = ((pos.x - img_rect.left()) / img_rect.width()).clamp(0.0, 1.0);
                            let ny = ((pos.y - img_rect.top()) / img_rect.height()).clamp(0.0, 1.0);
                            app.lightbox.mask_strokes.push(MaskStroke {
                                size_px: app.lightbox.mask_brush_size,
                                erase: app.lightbox.mask_eraser,
                                pts: vec![[nx, ny]],
                            });
                            app.lightbox.painting = true;
                        }
                    } else if resp.dragged() && app.lightbox.painting {
                        if let (Some(pos), Some(st)) = (resp.interact_pointer_pos(), app.lightbox.mask_strokes.last_mut()) {
                            let nx = ((pos.x - img_rect.left()) / img_rect.width()).clamp(0.0, 1.0);
                            let ny = ((pos.y - img_rect.top()) / img_rect.height()).clamp(0.0, 1.0);
                            st.pts.push([nx, ny]);
                        }
                    } else if resp.drag_stopped() {
                        app.lightbox.painting = false;
                    }

                    // Render painted mask strokes in red (or dark indicator for erase)
                    for st in &app.lightbox.mask_strokes {
                        let col = if st.erase {
                            Color32::from_rgba_unmultiplied(15, 20, 30, 150)
                        } else {
                            Color32::from_rgba_unmultiplied(239, 68, 68, 145)
                        };
                        let pts: Vec<Pos2> = st
                            .pts
                            .iter()
                            .map(|[nx, ny]| {
                                Pos2::new(
                                    img_rect.left() + nx * img_rect.width(),
                                    img_rect.top() + ny * img_rect.height(),
                                )
                            })
                            .collect();
                        if pts.len() == 1 {
                            painter.circle_filled(pts[0], st.size_px * 0.5, col);
                        } else if pts.len() >= 2 {
                            for w in pts.windows(2) {
                                painter.line_segment([w[0], w[1]], Stroke::new(st.size_px, col));
                                painter.circle_filled(w[1], st.size_px * 0.5, col);
                            }
                        }
                    }
                }
            } else {
                ui.centered_and_justified(|ui| {
                    ui.label("Loading full-resolution image...");
                });
            }

            ui.add_space(6.0);

            // 1-Line Iterative Follow-Up Edit / Inpaint Bar
            ui.horizontal(|ui| {
                let edit_resp = ui.add(
                    egui::TextEdit::singleline(&mut app.lightbox.followup_prompt)
                        .desired_width(ui.available_width() - 165.0)
                        .hint_text("Follow-up edit / inpaint (e.g. 'give him red sunglasses', 'fix hands')..."),
                );
                let has_mask = !app.lightbox.mask_strokes.is_empty();
                let btn_lbl = if has_mask { "🖌 Inpaint Area" } else { "✨ Apply Edit" };
                let submit = ui.add(primary_button(btn_lbl)).clicked()
                    || (edit_resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)));
                if submit {
                    submit_lightbox_followup(app, &item);
                }
            });

            ui.add_space(4.0);

            // Action Footer Bar
            ui.horizontal_wrapped(|ui| {
                if ui.add(primary_button("🎬 Animate")).clicked() {
                    app.animate_image_in_video(item.image_path.clone(), item.filename.clone());
                }
                if ui.button("🎲 Vary (0.55)").clicked() {
                    app.vary_gallery_image(&item);
                }
                if ui.button("👤 Fix Faces").clicked() {
                    app.api.send(ApiCommand::DetailFaces { filename: item.filename.clone() });
                    app.lightbox.open = false;
                }
                if ui.button("🖌 Edit").clicked() {
                    app.edit_image_in_studio(item.image_path.clone(), item.filename.clone());
                }
                let polishing = app.busy_flags.contains("polish");
                if ui.add_enabled(!polishing, egui::Button::new("✨ 2× HD")).clicked() {
                    app.busy_flags.insert("polish".into());
                    app.api.send(ApiCommand::PolishImage { filename: item.filename.clone(), scale: 2 });
                }
                if ui.add_enabled(!polishing, egui::Button::new("4× HD")).clicked() {
                    app.busy_flags.insert("polish".into());
                    app.api.send(ApiCommand::PolishImage { filename: item.filename.clone(), scale: 4 });
                }
                if ui.button("♻ Remix").clicked() {
                    app.remix_gallery_image(&item);
                }
                if ui.button("+ Import Bin").clicked() {
                    app.add_path_to_timeline(item.image_path.clone());
                    app.lightbox.open = false;
                }
            });
        });

    if !open {
        app.lightbox.open = false;
    }
}

fn build_version_chain(gallery: &[GalleryImage], current: &GalleryImage) -> Vec<GalleryImage> {
    let mut chain: Vec<GalleryImage> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut cur = Some(current.clone());
    while let Some(node) = cur {
        if !seen.insert(node.filename.clone()) {
            break;
        }
        let parent_fn = node.meta.as_ref().and_then(|m| m.parent_image.clone());
        chain.insert(0, node);
        cur = parent_fn.and_then(|pf| gallery.iter().find(|g| g.filename == pf).cloned());
    }
    for child in gallery.iter().filter(|g| {
        g.meta.as_ref().and_then(|m| m.parent_image.as_deref()) == Some(current.filename.as_str())
            && !seen.contains(&g.filename)
    }).take(3) {
        chain.push(child.clone());
    }
    chain
}

fn rasterize_mask_to_png_data_url(strokes: &[MaskStroke], img_path: &str) -> Option<String> {
    if strokes.is_empty() {
        return None;
    }
    let (w, h) = image::image_dimensions(img_path).unwrap_or((1024, 1024));
    let mut mask = image::GrayImage::from_pixel(w, h, image::Luma([0u8]));
    let scale = (w as f32) / 640.0;

    for st in strokes {
        let val = if st.erase { 0u8 } else { 255u8 };
        let radius = ((st.size_px * scale * 0.5).max(4.0)) as i32;
        let r2 = radius * radius;
        let mut draw_disc = |cx: i32, cy: i32| {
            let x0 = (cx - radius).max(0);
            let x1 = (cx + radius).min(w as i32 - 1);
            let y0 = (cy - radius).max(0);
            let y1 = (cy + radius).min(h as i32 - 1);
            for y in y0..=y1 {
                let dy = y - cy;
                for x in x0..=x1 {
                    let dx = x - cx;
                    if dx * dx + dy * dy <= r2 {
                        mask.put_pixel(x as u32, y as u32, image::Luma([val]));
                    }
                }
            }
        };

        for (i, [nx, ny]) in st.pts.iter().enumerate() {
            let x1 = (nx * w as f32).round() as i32;
            let y1 = (ny * h as f32).round() as i32;
            draw_disc(x1, y1);
            if i > 0 {
                let [px, py] = st.pts[i - 1];
                let x0 = (px * w as f32).round() as i32;
                let y0 = (py * h as f32).round() as i32;
                let steps = ((x1 - x0).abs().max((y1 - y0).abs()) / (radius / 2).max(1)).max(1);
                for s in 1..steps {
                    let t = s as f32 / steps as f32;
                    let ix = (x0 as f32 + (x1 - x0) as f32 * t).round() as i32;
                    let iy = (y0 as f32 + (y1 - y0) as f32 * t).round() as i32;
                    draw_disc(ix, iy);
                }
            }
        }
    }

    let mut png_bytes: Vec<u8> = Vec::new();
    let mut cursor = std::io::Cursor::new(&mut png_bytes);
    image::DynamicImage::ImageLuma8(mask)
        .write_to(&mut cursor, image::ImageFormat::Png)
        .ok()?;
    let b64 = base64::engine::general_purpose::STANDARD.encode(&png_bytes);
    Some(format!("data:image/png;base64,{b64}"))
}

fn submit_lightbox_followup(app: &mut ClipForgeApp, item: &GalleryImage) {
    let instr = app.lightbox.followup_prompt.trim().to_string();
    if instr.is_empty() {
        app.push_toast("Type what to change or inpaint first.", ToastKind::Warning);
        return;
    }
    let mask_url = rasterize_mask_to_png_data_url(&app.lightbox.mask_strokes, &item.image_path);
    let best_model = ["qwen_edit_2511", "qwen_edit", "flux2_klein_9b", "flux2_klein"]
        .into_iter()
        .find(|id| app.gen_status.models.get(*id).map(|m| m.ready).unwrap_or(false))
        .unwrap_or("flux2_klein");

    let payload = json!({
        "prompt": instr,
        "model": best_model,
        "image_path": item.image_path,
        "parent_image": item.filename,
        "match_photo_aspect": true,
        "denoise": if mask_url.is_some() { 0.88 } else { 1.0 },
        "mask_data_url": mask_url,
        "loras": app.active_loras_json(),
        "batch_size": 1,
        "add_to_timeline": false,
    });
    app.api.send(ApiCommand::GenerateImage(payload));
    app.lightbox.open = false;
}

fn plain_english_model_guide(id: &str) -> &'static str {
    match id {
        "z_image_turbo" => "Best for: Fast everyday candid photos, crisp visible signs/text & memes (~6s)",
        "krea2_turbo" => "Best for: High-end editorial & studio portrait skin detail (~8s)",
        "lustify_sdxl" => "Best for: Completely unfiltered, raw realistic photos & edgy humor",
        "pony_realism" => "Best for: Unfiltered bold expressive scenes, dynamic poses & stylized realism",
        "chroma_hd" => "Best for: Uncensored Flux art & surreal posters with strong prompt adherence",
        "illustrious_xl" => "Best for: Anime, manga, illustration & crisp 2.5D stylized artwork",
        "flux2_klein_9b" => "Best for: Highest-quality placing a friend's photo into a new scene",
        "flux2_klein" => "Best for: Lightweight faster scene edits keeping a friend's face",
        "qwen_edit_2511" => "Best for: Best 2-friend photo combiner & complex outfit/scene edits",
        "qwen_edit" => "Best for: Fast multi-photo scene edits for 1-2 friends",
        "wan22_i2v" => "Best for: Smooth, natural 5-second video motion from any still photo",
        "wan22_remix_i2v" => "Best for: Unfiltered expressive physical action from a still photo",
        "wan22_smoothmix_i2v" => "Best for: Unfiltered smooth cinematic motion & expressive transitions",
        "ltx23" => "Best for: Text/photo into video WITH synchronized sound effects & dialogue audio",
        "wan22_t2v" => "Best for: Full 5-second realistic video directly from text alone",
        "wan22_5b" => "Best for: Fast ~25s rough video drafts before committing a full render",
        "wan22_s2v" => "Best for: Lip-synced talking/singing friend video driven by speech or voice clip",
        "ace_step_music_xl" => "Best for: Pro Suno-grade 4B songs with sharpest vocals & lyrics",
        "ace_step_music" => "Best for: Fast full songs with vocals or instrumentals (lighter download)",
        "kokoro_tts" => "Best for: 12 studio-real neural human voices (replaces robotic OS voices)",
        "face_swap" => "Best for: 1-second automatic friend Face Lock on any generated or meme photo",
        "rife_vfi" => "Best for: Doubling video framerate cleanly to 32fps smooth motion",
        _ => "Best for: General offline local creation",
    }
}

// ---------------------------------------------------------------------------
// 2. Downloads & Starter Packs Modal (Guided Tabs + Plain-English Recommendations)
// ---------------------------------------------------------------------------
fn render_models_modal(app: &mut ClipForgeApp, ctx: &egui::Context) {
    let mut open = app.show_models_modal;
    let is_simple = app.ui_mode == crate::app::UiMode::Simple;
    let title = if is_simple {
        "📦 Packs & Offline AI Engines"
    } else {
        "🧠 Local Offline AI Engine Manager"
    };
    egui::Window::new(title)
        .open(&mut open)
        .resizable(true)
        .collapsible(false)
        .default_size([770.0, 610.0])
        .anchor(egui::Align2::CENTER_CENTER, Vec2::ZERO)
        .show(ctx, |ui| {
            ui.horizontal(|ui| {
                if !is_simple {
                    ui.label(RichText::new(format!("Storage: {}", app.gen_status.comfyui_dir)).size(11.0).color(TEXT_MUTED));
                } else {
                    ui.label(RichText::new("Everything runs 100% offline — pick Starter Packs first, or browse by studio category.").size(11.5).color(TEXT_MUTED));
                }
                ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| {
                    if ui.small_button("✨ Get Styles").clicked() {
                        app.show_models_modal = false;
                        app.show_civitai_modal = true;
                    }
                    if app.gen_status.comfyui_running {
                        pulsing_status_pill(ui, "AI Ready", ACCENT_GREEN, true);
                    } else if ui.small_button("▶ Start AI").clicked() {
                        app.api.send(ApiCommand::StartComfyUi);
                    }
                });
            });
            ui.add_space(6.0);

            if let Some(tab) = animated_segmented_bar(
                ui,
                "models_modal_tabs",
                &["🚀 Starter Packs", "🖼 Photos", "🎬 Video", "🎵 Music & Voice", "⚙ Utilities"],
                app.models_modal_tab,
                ACCENT_BLUE,
            ) {
                app.models_modal_tab = tab;
            }
            ui.add_space(6.0);

            let starter_packs = app.gen_status.starter_packs.clone();
            let models: Vec<_> = app.gen_status.models.values().cloned().collect();

            let render_model_cards = |app: &mut ClipForgeApp, ui: &mut egui::Ui, kinds: &[&str]| {
                for m in models.iter().filter(|x| kinds.contains(&x.kind.as_str())) {
                    card_frame().show(ui, |ui| {
                        ui.horizontal(|ui| {
                            ui.vertical(|ui| {
                                ui.set_max_width((ui.available_width() - 165.0).max(240.0));
                                ui.horizontal_wrapped(|ui| {
                                    ui.label(RichText::new(&m.display_name).strong().size(12.5).color(Color32::WHITE));
                                    badge(ui, &m.badge, if m.ready { ACCENT_GREEN } else { ACCENT_BLUE });
                                });
                                ui.label(
                                    RichText::new(plain_english_model_guide(&m.id))
                                        .size(11.0)
                                        .strong()
                                        .color(Color32::from_rgb(165, 195, 255)),
                                );
                                ui.label(RichText::new(&m.description).size(10.5).color(TEXT_MUTED));
                                let status_meta = if m.ready {
                                    format!("{}/{} files · {:.2} GB installed", m.total_files, m.total_files, m.total_gb)
                                } else {
                                    format!("{}/{} present · {:.2} GB remaining", m.present_count, m.total_files, m.missing_gb)
                                };
                                ui.label(RichText::new(status_meta).size(10.0).color(TEXT_MUTED));
                            });
                            ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| {
                                let is_dl = m.download.as_ref().map(|d| d.status == "downloading").unwrap_or(false);
                                if m.ready {
                                    if m.kind != "utility" && m.kind != "audio" && !is_simple {
                                        let use_lbl = if m.requires_audio { "Talk-Sync" } else { "Use" };
                                        if ui.button(use_lbl).clicked() {
                                            if m.requires_audio {
                                                app.left_tab = crate::app::LeftTab::Subs;
                                                app.show_models_modal = false;
                                            } else {
                                                let sm = if m.kind == "image" {
                                                    crate::app::StudioMode::Image
                                                } else {
                                                    crate::app::StudioMode::Video
                                                };
                                                app.set_studio_mode(sm, true, Some(m.id.clone()));
                                                app.left_tab = crate::app::LeftTab::Studio;
                                                app.show_models_modal = false;
                                            }
                                        }
                                    }
                                    badge(
                                        ui,
                                        if m.kind == "utility" { "✓ Auto-Active" } else { "✓ Ready" },
                                        ACCENT_GREEN,
                                    );
                                } else if is_dl {
                                    if ui.button("Pause").clicked() {
                                        app.api.send(ApiCommand::CancelDownload(m.id.clone()));
                                    }
                                } else {
                                    let partial = m.missing_files.iter().any(|f| f.partial_gb > 0.0);
                                    let lbl = if partial {
                                        format!("▶ Resume ({:.1} GB)", m.missing_gb)
                                    } else {
                                        format!("⬇ Download ({:.1} GB)", m.missing_gb)
                                    };
                                    if ui.add(primary_button(&lbl)).clicked() {
                                        app.api.send(ApiCommand::DownloadModel(m.id.clone()));
                                    }
                                }
                            });
                        });
                        if let Some(d) = m.download.as_ref().filter(|d| d.status == "downloading") {
                            ui.add_space(5.0);
                            let txt = format!(
                                "{} · {:.2}/{:.2} GB · {:.1} MB/s ({:.0}%)",
                                d.current_file, d.downloaded_gb, d.total_gb, d.speed_mbps, d.pct
                            );
                            animated_progress_bar(ui, &format!("mdl_{}", m.id), (d.pct as f32) / 100.0, &txt, ACCENT_BLUE);
                        }
                    });
                    ui.add_space(5.0);
                }
            };

            egui::ScrollArea::vertical().id_salt("models_modal_scroll").show(ui, |ui| match app.models_modal_tab {
                0 => {
                    for pack in &starter_packs {
                        card_frame().show(ui, |ui| {
                            ui.horizontal(|ui| {
                                ui.vertical(|ui| {
                                    ui.set_max_width((ui.available_width() - 155.0).max(240.0));
                                    ui.horizontal_wrapped(|ui| {
                                        ui.label(RichText::new(&pack.title).strong().size(12.5).color(Color32::WHITE));
                                        badge(
                                            ui,
                                            &pack.badge,
                                            if pack.recommended { ACCENT_BLUE } else { ACCENT_PURPLE },
                                        );
                                    });
                                    ui.label(RichText::new(&pack.description).size(11.0).color(TEXT_MUTED));
                                });
                                ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| {
                                    if pack.ready {
                                        badge(ui, "✓ Installed", ACCENT_GREEN);
                                    } else if pack.downloading {
                                        badge(ui, "⬇ Downloading...", ACCENT_AMBER);
                                    } else if ui
                                        .add(primary_button(&format!("⬇ Install ({:.1} GB)", pack.missing_gb)))
                                        .clicked()
                                    {
                                        app.api.send(ApiCommand::DownloadStarterPack(pack.id.clone()));
                                    }
                                });
                            });
                        });
                        ui.add_space(5.0);
                    }
                }
                1 => render_model_cards(app, ui, &["image"]),
                2 => render_model_cards(app, ui, &["video"]),
                3 => render_model_cards(app, ui, &["audio"]),
                _ => render_model_cards(app, ui, &["utility"]),
            });
        });
    if !open {
        app.show_models_modal = false;
    }
}

// ---------------------------------------------------------------------------
// 3. Cast / Friends Book Modal (Multi-Angle + Voice Sample)
// ---------------------------------------------------------------------------
fn render_cast_modal(app: &mut ClipForgeApp, ctx: &egui::Context) {
    let mut open = app.show_cast_modal;
    egui::Window::new("👥 Saved Cast / Friends Book (Multi-Angle + Voice)")
        .open(&mut open)
        .resizable(true)
        .collapsible(false)
        .default_size([620.0, 520.0])
        .anchor(egui::Align2::CENTER_CENTER, Vec2::ZERO)
        .show(ctx, |ui| {
            card_frame().show(ui, |ui| {
                ui.label(RichText::new("Add New Friend Profile").strong());
                ui.horizontal(|ui| {
                    ui.label("Name:");
                    ui.add(egui::TextEdit::singleline(&mut app.cast_name_buf).desired_width(180.0).hint_text("e.g. Jake"));
                    if ui.button("📷 Face Photo...").clicked() {
                        app.cast_photo_path = rfd::FileDialog::new()
                            .add_filter("Images", &["png", "jpg", "jpeg", "webp"])
                            .pick_file();
                    }
                    if ui.button("🎙 Voice Clip (opt)...").clicked() {
                        app.cast_voice_path = rfd::FileDialog::new()
                            .add_filter("Audio/Video", &["wav", "mp3", "m4a", "ogg", "mp4", "mov"])
                            .pick_file();
                    }
                });
                if let Some(p) = &app.cast_photo_path {
                    ui.label(RichText::new(format!("Photo: {}", p.file_name().unwrap_or_default().to_string_lossy())).size(10.5).color(ACCENT_GREEN));
                }
                if let Some(v) = &app.cast_voice_path {
                    ui.label(RichText::new(format!("Voice: {}", v.file_name().unwrap_or_default().to_string_lossy())).size(10.5).color(ACCENT_BLUE));
                    ui.add(
                        egui::TextEdit::singleline(&mut app.cast_voice_transcript)
                            .desired_width(f32::INFINITY)
                            .hint_text("Optional transcript of what they say in the voice clip..."),
                    );
                }
                let saving = app.busy_flags.contains("save_cast");
                if ui.add_enabled(!saving, primary_button("+ Save Friend Profile")).clicked() {
                    if app.cast_name_buf.trim().is_empty() || app.cast_photo_path.is_none() {
                        app.push_toast("Enter a name and choose a face photo.", ToastKind::Warning);
                    } else if let Some(photo_path) = app.cast_photo_path.take() {
                        app.busy_flags.insert("save_cast".into());
                        let name = app.cast_name_buf.trim().to_string();
                        app.cast_name_buf.clear();
                        let voice_path = app.cast_voice_path.take();
                        let transcript = std::mem::take(&mut app.cast_voice_transcript);
                        app.api.send(ApiCommand::CreateCast {
                            name,
                            photo_path,
                            voice_path,
                            voice_ref_text: transcript,
                        });
                    }
                }
            });

            ui.add_space(6.0);
            let cast_list = app.gen_status.cast.clone();
            egui::ScrollArea::vertical().show(ui, |ui| {
                for m in &cast_list {
                    card_frame().show(ui, |ui| {
                        ui.horizontal(|ui| {
                            let key = format!("cast_{}", m.id);
                            if let Some(t) = app.api.get_or_load_image(&key, &m.photo_path, 128).cloned() {
                                ui.add(Image::new(&t).fit_to_exact_size(Vec2::splat(52.0)).corner_radius(CornerRadius::same(6)));
                            }
                            ui.vertical(|ui| {
                                ui.label(RichText::new(format!("{} ({})", m.name, m.handle)).strong());
                                ui.label(
                                    RichText::new(format!(
                                        "{} angle(s) · {}",
                                        m.photo_count.max(1),
                                        if m.has_voice { "🎙 Voice Ready" } else { "No voice sample" }
                                    ))
                                    .size(10.5)
                                    .color(TEXT_MUTED),
                                );
                                ui.horizontal(|ui| {
                                    for (idx, ep) in m.extra_photos.iter().enumerate() {
                                        let ek = format!("cast_{}_e_{idx}", m.id);
                                        if let Some(et) = app.api.get_or_load_image(&ek, ep, 64).cloned() {
                                            ui.add(Image::new(&et).fit_to_exact_size(Vec2::splat(26.0)).corner_radius(CornerRadius::same(4)));
                                        }
                                        if ui.small_button("×").on_hover_text("Remove angle").clicked() {
                                            app.api.send(ApiCommand::DeleteCastAngle {
                                                cast_id: m.id.clone(),
                                                index: idx,
                                            });
                                        }
                                    }
                                    if m.extra_photos.len() < 3 {
                                        if ui.small_button("+ Angle").clicked() {
                                            if let Some(p) = rfd::FileDialog::new()
                                                .add_filter("Images", &["png", "jpg", "jpeg", "webp"])
                                                .pick_file()
                                            {
                                                app.api.send(ApiCommand::AddCastAngle {
                                                    cast_id: m.id.clone(),
                                                    photo_path: p,
                                                });
                                            }
                                        }
                                    }
                                });
                            });
                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                if ui.small_button("✕").clicked() {
                                    app.api.send(ApiCommand::DeleteCast(m.id.clone()));
                                }
                            });
                        });
                    });
                    ui.add_space(4.0);
                }
            });
        });
    if !open {
        app.show_cast_modal = false;
    }
}

// ---------------------------------------------------------------------------
// 4. Multi-Beat Storyboard / Scene Chainer Modal
// ---------------------------------------------------------------------------
fn render_storyboard_modal(app: &mut ClipForgeApp, ctx: &egui::Context) {
    let mut open = app.show_storyboard_modal;
    egui::Window::new("🎞 Auto Multi-Beat Storyboard / Scene Chainer")
        .open(&mut open)
        .resizable(true)
        .collapsible(false)
        .default_size([680.0, 540.0])
        .anchor(egui::Align2::CENTER_CENTER, Vec2::ZERO)
        .show(ctx, |ui| {
            ui.label(
                RichText::new("Write a 1-line idea — ClipForge plans 2–4 chained shots, extracts each final frame into the next beat, and builds the edited timeline with captions & SFX.")
                    .size(11.0)
                    .color(TEXT_MUTED),
            );
            ui.horizontal(|ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut app.sb_concept)
                        .desired_width(ui.available_width() - 185.0)
                        .hint_text("e.g. @Jake tries to grill indoors and accidentally launches the patio into orbit"),
                );
                egui::ComboBox::from_id_salt("sb_cnt_cb")
                    .selected_text(format!("{} beats", app.sb_beat_count))
                    .width(78.0)
                    .show_ui(ui, |ui| {
                        for n in [2usize, 3, 4] {
                            ui.selectable_value(&mut app.sb_beat_count, n, format!("{n} beats"));
                        }
                    });
                let planning = app.busy_flags.contains("plan_sb");
                if ui.add_enabled(!planning, primary_button(if planning { "..." } else { "✨ Auto-Plan" })).clicked() {
                    if app.sb_concept.trim().is_empty() {
                        app.push_toast("Enter a 1-line scene concept first.", ToastKind::Warning);
                    } else {
                        app.busy_flags.insert("plan_sb".into());
                        app.api.send(ApiCommand::DirectorStoryboard(json!({
                            "concept": app.sb_concept.trim(),
                            "num_beats": app.sb_beat_count,
                            "style_preset": app.preset_id,
                            "has_friend_photo": app.ref1.is_some(),
                            "model_name": if app.director_model.is_empty() { serde_json::Value::Null } else { json!(app.director_model) },
                            "literal_mode": app.director_literal,
                        })));
                    }
                }
            });

            ui.horizontal(|ui| {
                ui.checkbox(&mut app.sb_auto_captions, "Auto captions");
                ui.checkbox(&mut app.sb_add_sfx, "Auto SFX hits");
                ui.checkbox(&mut app.sb_want_audio, "Native audio (LTX-2.3)");
                ui.checkbox(&mut app.sb_fast_draft, "Fast draft");
            });

            ui.separator();

            let cams: Vec<(String, String)> = app
                .gen_status
                .camera_presets
                .iter()
                .map(|(k, v)| (k.clone(), v.label.clone()))
                .collect();

            let mut to_remove: Option<usize> = None;
            egui::ScrollArea::vertical().max_height(330.0).show(ui, |ui| {
                for (idx, beat) in app.sb_beats.iter_mut().enumerate() {
                    card_frame().show(ui, |ui| {
                        ui.horizontal(|ui| {
                            let hdr = if idx == 0 {
                                "Beat 1 (Opening Shot)".to_string()
                            } else {
                                format!("Beat {} (Chains from Beat {} Final Frame)", idx + 1, idx)
                            };
                            ui.label(RichText::new(hdr).strong().size(11.5));
                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                if ui.small_button("✕").clicked() {
                                    to_remove = Some(idx);
                                }
                            });
                        });
                        ui.add(egui::TextEdit::multiline(&mut beat.prompt).desired_rows(2).desired_width(f32::INFINITY));
                        ui.horizontal(|ui| {
                            egui::ComboBox::from_id_salt(("sb_cam", idx))
                                .selected_text(
                                    cams.iter().find(|(k, _)| k == &beat.camera_preset).map(|(_, l)| l.as_str()).unwrap_or("Auto Camera"),
                                )
                                .width(135.0)
                                .show_ui(ui, |ui| {
                                    for (k, l) in &cams {
                                        ui.selectable_value(&mut beat.camera_preset, k.clone(), l);
                                    }
                                });
                            ui.add(egui::TextEdit::singleline(&mut beat.caption).desired_width(180.0).hint_text("Caption..."));
                            ui.add(egui::TextEdit::singleline(&mut beat.sfx_id).desired_width(110.0).hint_text("SFX (e.g. vine_boom)"));
                        });
                    });
                    ui.add_space(4.0);
                }
            });
            if let Some(i) = to_remove {
                app.sb_beats.remove(i);
            }

            ui.add_space(6.0);
            ui.horizontal(|ui| {
                if ui.button("+ Add Beat").clicked() && app.sb_beats.len() < 4 {
                    app.sb_beats.push(StoryboardBeat::default());
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.add(primary_button("🚀 Render Chained Scene")).clicked() {
                        let valid: Vec<_> = app.sb_beats.iter().filter(|b| !b.prompt.trim().is_empty()).cloned().collect();
                        if valid.is_empty() {
                            app.push_toast("Plan or add at least 1 beat first.", ToastKind::Warning);
                        } else {
                            app.api.send(ApiCommand::RenderStoryboard(json!({
                                "beats": valid,
                                "model": "auto",
                                "image_path": app.ref1.as_ref().map(|r| r.path.clone()),
                                "style_preset": app.preset_id,
                                "want_audio": app.sb_want_audio,
                                "fast_draft": app.sb_fast_draft,
                                "num_frames": app.num_frames,
                                "loras": app.active_loras_json(),
                                "auto_captions": app.sb_auto_captions,
                                "add_sfx": app.sb_add_sfx,
                            })));
                            app.show_storyboard_modal = false;
                        }
                    }
                });
            });
        });
    if !open {
        app.show_storyboard_modal = false;
    }
}

// ---------------------------------------------------------------------------
// 5. Render Export MP4 Modal
// ---------------------------------------------------------------------------
fn render_render_modal(app: &mut ClipForgeApp, ctx: &egui::Context) {
    let mut open = app.show_render_modal;
    egui::Window::new("🎬 Render Final Video (FFmpeg)")
        .open(&mut open)
        .resizable(false)
        .collapsible(false)
        .default_size([460.0, 310.0])
        .anchor(egui::Align2::CENTER_CENTER, Vec2::ZERO)
        .show(ctx, |ui| {
            ui.label(RichText::new("Output Filename (inside workspace/renders/)").size(11.0).color(TEXT_MUTED));
            ui.add(
                egui::TextEdit::singleline(&mut app.render_output_path)
                    .desired_width(f32::INFINITY)
                    .hint_text("Leave blank for auto timestamped MP4"),
            );

            ui.horizontal(|ui| {
                ui.label("Quality:");
                egui::ComboBox::from_id_salt("render_q_cb")
                    .selected_text(&app.render_quality)
                    .show_ui(ui, |ui| {
                        for (q, lbl) in [
                            ("draft", "Draft (Fastest)"),
                            ("balanced", "Balanced (Recommended)"),
                            ("high", "High Quality (Archival)"),
                        ] {
                            ui.selectable_value(&mut app.render_quality, q.into(), lbl);
                        }
                    });
            });

            ui.checkbox(&mut app.render_burn_subs, "Burn word-synced karaoke subtitles into video");
            ui.checkbox(&mut app.render_norm_audio, "Loudness normalize audio (EBU R128)");
            let gpu_lbl = if app.gen_status.has_nvidia {
                format!("Use NVIDIA NVENC hardware encoding ({})", app.gen_status.gpu_name)
            } else {
                "Use hardware encoding when available (falls back to x264)".into()
            };
            ui.checkbox(&mut app.render_hw_accel, gpu_lbl);

            ui.add_space(6.0);
            let rendering = app.busy_flags.contains("render");
            if ui
                .add_enabled(
                    !rendering,
                    primary_button(if rendering { "⏳ Rendering with FFmpeg..." } else { "▶ Start Render" })
                        .min_size(Vec2::new(ui.available_width(), 32.0)),
                )
                .clicked()
            {
                app.busy_flags.insert("render".into());
                let out_val = if app.render_output_path.trim().is_empty() {
                    serde_json::Value::Null
                } else {
                    json!(app.render_output_path.trim())
                };
                app.api.send(ApiCommand::RenderVideo(json!({
                    "output_path": out_val,
                    "quality": app.render_quality,
                    "burn_subtitles": app.render_burn_subs,
                    "normalize_audio": app.render_norm_audio,
                    "use_hw_accel": app.render_hw_accel,
                })));
            }

            if let Some(r) = &app.last_render_report {
                ui.add_space(6.0);
                card_frame().show(ui, |ui| {
                    ui.label(
                        RichText::new(format!(
                            "✓ Complete in {:.1}s via {} · {:.2} MB",
                            r.render_time_sec,
                            r.encoder,
                            r.file_size_bytes as f64 / (1024.0 * 1024.0)
                        ))
                        .color(ACCENT_GREEN)
                        .strong(),
                    );
                    ui.label(RichText::new(&r.output_path).size(10.5).color(TEXT_MUTED));
                });
            }
        });
    if !open {
        app.show_render_modal = false;
    }
}

// ---------------------------------------------------------------------------
// 6. Get More Styles & Looks (Plain-English Community Library powered by CivitAI)
// ---------------------------------------------------------------------------
fn friendly_style_kind(model_type: &str) -> &'static str {
    if model_type.eq_ignore_ascii_case("lora") {
        "Style Booster"
    } else {
        "Full Style"
    }
}

fn friendly_family_label(family: &str, base_model: &str) -> String {
    match family {
        "z_image" | "krea2" | "chroma" | "flux" => "Photorealism".into(),
        "illustrious" => "Anime / Art".into(),
        "wan" | "ltx" => "Video".into(),
        "qwen" => "Friend Edit".into(),
        _ if !base_model.is_empty() => base_model.to_string(),
        _ => "General".into(),
    }
}

fn render_civitai_modal(app: &mut ClipForgeApp, ctx: &egui::Context) {
    let mut open = app.show_civitai_modal;
    egui::Window::new("✨ Get More Styles & Looks (Community Library)")
        .open(&mut open)
        .resizable(true)
        .collapsible(false)
        .default_size([800.0, 620.0])
        .anchor(egui::Align2::CENTER_CENTER, Vec2::ZERO)
        .show(ctx, |ui| {
            ui.label(
                RichText::new("Full Styles change the whole art look (Anime, Film, Photorealism). Style Boosters layer an extra vibe on top. Click Install — ClipForge sets everything up automatically.")
                    .size(11.0)
                    .color(TEXT_MUTED),
            );
            ui.add_space(4.0);

            // 1. Direct URL / ID Paste Bar
            card_frame().show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Paste a civitai.com link:").size(11.5).strong());
                    let inspecting = app.busy_flags.contains("civitai_inspect");
                    let url_resp = ui.add(
                        egui::TextEdit::singleline(&mut app.civitai_url_buf)
                            .desired_width((ui.available_width() - 105.0).max(180.0))
                            .hint_text("https://civitai.com/models/..."),
                    );
                    let trigger = ui
                        .add_enabled(!inspecting, primary_button(if inspecting { "Loading..." } else { "🔍 Preview" }))
                        .clicked()
                        || (url_resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)));
                    if trigger {
                        let raw = app.civitai_url_buf.trim().to_string();
                        if !raw.is_empty() {
                            app.busy_flags.insert("civitai_inspect".into());
                            app.api.send(ApiCommand::InspectCivitai(raw));
                        }
                    }
                });

                if let Some(item) = app.civitai_inspected.clone() {
                    ui.add_space(6.0);
                    egui::Frame::new()
                        .fill(Color32::from_rgb(22, 34, 56))
                        .stroke(Stroke::new(1.0_f32, ACCENT_BLUE))
                        .corner_radius(CornerRadius::same(8))
                        .inner_margin(egui::Margin::same(8))
                        .show(ui, |ui| {
                            ui.horizontal(|ui| {
                                ui.vertical(|ui| {
                                    ui.horizontal(|ui| {
                                        ui.label(RichText::new(&item.name).strong().size(13.0).color(Color32::WHITE));
                                        badge(ui, friendly_style_kind(&item.model_type), ACCENT_PURPLE);
                                        badge(ui, &friendly_family_label(&item.family, &item.base_model), ACCENT_BLUE);
                                    });
                                    ui.label(
                                        RichText::new(format!(
                                            "{:.1} MB · Auto-installs into your {} list",
                                            item.size_mb,
                                            if item.model_type.eq_ignore_ascii_case("lora") {
                                                "Style Boosters"
                                            } else {
                                                "Art Styles"
                                            }
                                        ))
                                        .size(11.0)
                                        .color(TEXT_MUTED),
                                    );
                                });
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                    if ui.add(primary_button("⬇ 1-Click Install")).clicked() {
                                        app.api.send(ApiCommand::InstallCivitai(json!({
                                            "version_id": item.version_id,
                                            "download_url": item.download_url,
                                            "filename": item.filename,
                                            "name": item.name,
                                            "model_type": item.model_type,
                                            "base_model": item.base_model,
                                            "target_subdir": item.target_subdir,
                                            "trained_words": item.trained_words,
                                            "size_mb": item.size_mb,
                                        })));
                                    }
                                    if ui.small_button("✕").clicked() {
                                        app.civitai_inspected = None;
                                    }
                                });
                            });
                        });
                }
            });

            ui.add_space(6.0);

            // 2. Live Search & Plain-English Filters
            ui.horizontal(|ui| {
                let searching = app.busy_flags.contains("civitai_search");
                let s_resp = ui.add(
                    egui::TextEdit::singleline(&mut app.civitai_search_buf)
                        .desired_width(220.0)
                        .hint_text("Search styles (e.g. realism, anime, 90s film)..."),
                );
                let type_display = match app.civitai_type_filter.as_str() {
                    "Checkpoint" => "Full Styles",
                    "LORA" => "Style Boosters",
                    _ => "All Types",
                };
                egui::ComboBox::from_id_salt("civ_type_cb")
                    .selected_text(type_display)
                    .width(112.0)
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut app.civitai_type_filter, "All".into(), "All Types");
                        ui.selectable_value(&mut app.civitai_type_filter, "Checkpoint".into(), "Full Styles");
                        ui.selectable_value(&mut app.civitai_type_filter, "LORA".into(), "Style Boosters");
                    });
                let base_display = match app.civitai_base_filter.as_str() {
                    "All" => "All Categories",
                    "ZImageTurbo" => "Photorealism (Fast)",
                    "Illustrious" => "Anime / Art",
                    "Krea 2" => "Editorial Realism",
                    "Chroma" => "Uncensored Art",
                    "Flux.2 Klein 9B" => "Friend Photo Edit",
                    "Wan Video 2.2" => "Video Motion",
                    "LTXV 2.3" => "Video + Sound",
                    other => other,
                };
                egui::ComboBox::from_id_salt("civ_base_cb")
                    .selected_text(base_display)
                    .width(140.0)
                    .show_ui(ui, |ui| {
                        for (val, lbl) in [
                            ("All", "All Categories"),
                            ("ZImageTurbo", "Photorealism (Fast)"),
                            ("Illustrious", "Anime / Art"),
                            ("Krea 2", "Editorial Realism"),
                            ("Chroma", "Uncensored Art"),
                            ("Flux.2 Klein 9B", "Friend Photo Edit"),
                            ("Wan Video 2.2", "Video Motion"),
                            ("LTXV 2.3", "Video + Sound"),
                        ] {
                            ui.selectable_value(&mut app.civitai_base_filter, val.into(), lbl);
                        }
                    });
                egui::ComboBox::from_id_salt("civ_sort_cb")
                    .selected_text(&app.civitai_sort)
                    .width(122.0)
                    .show_ui(ui, |ui| {
                        for s in ["Most Downloaded", "Highest Rated", "Newest"] {
                            ui.selectable_value(&mut app.civitai_sort, s.into(), s);
                        }
                    });
                let do_search = ui
                    .add_enabled(!searching, primary_button(if searching { "..." } else { "Search" }))
                    .clicked()
                    || (s_resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)));
                if do_search {
                    app.busy_flags.insert("civitai_search".into());
                    app.api.send(ApiCommand::SearchCivitai {
                        query: app.civitai_search_buf.trim().to_string(),
                        model_type: app.civitai_type_filter.clone(),
                        base_model: app.civitai_base_filter.clone(),
                        sort: app.civitai_sort.clone(),
                    });
                }
            });

            // Optional CivitAI API Key (for locked/18+ downloads)
            ui.add_space(4.0);
            let has_key = app.gen_status.civitai.has_api_key;
            egui::CollapsingHeader::new(if has_key {
                "🔑 CivitAI Account Key (✓ Saved — Locked Downloads Unlocked)"
            } else {
                "🔑 Optional CivitAI Key (only needed if a download says 'account required')"
            })
            .id_salt("civ_key_hdr")
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.add(
                        egui::TextEdit::singleline(&mut app.civitai_api_key_buf)
                            .password(true)
                            .desired_width(300.0)
                            .hint_text("Paste your free civitai.com API key..."),
                    );
                    if ui.button("Save Key").clicked() {
                        let k = app.civitai_api_key_buf.trim().to_string();
                        app.civitai_api_key_buf.clear();
                        app.api.send(ApiCommand::SaveCivitaiKey(k));
                    }
                    if has_key && ui.small_button("Clear Key").clicked() {
                        app.api.send(ApiCommand::SaveCivitaiKey(String::new()));
                    }
                });
            });

            ui.separator();

            // 3. Active Style Downloads
            let dls = app.gen_status.civitai.downloads.clone();
            if !dls.is_empty() {
                for d in &dls {
                    card_frame().show(ui, |ui| {
                        ui.horizontal(|ui| {
                            ui.label(RichText::new(&d.name).strong().size(11.5));
                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                if d.status == "downloading" {
                                    if ui.small_button("Pause").clicked() {
                                        app.api.send(ApiCommand::CancelCivitai(d.download_id.clone()));
                                    }
                                }
                                let col = match d.status.as_str() {
                                    "completed" => ACCENT_GREEN,
                                    "failed" => ACCENT_RED,
                                    "canceled" => ACCENT_AMBER,
                                    _ => ACCENT_BLUE,
                                };
                                let lbl = match d.status.as_str() {
                                    "completed" => "INSTALLED",
                                    "downloading" => "DOWNLOADING",
                                    "canceled" => "PAUSED",
                                    _ => "FAILED",
                                };
                                badge(ui, lbl, col);
                            });
                        });
                        if d.status == "downloading" {
                            ui.add(
                                egui::ProgressBar::new((d.pct as f32 / 100.0).clamp(0.0, 1.0)).text(format!(
                                    "{:.0}/{:.0} MB · {:.1} MB/s",
                                    d.downloaded_mb, d.total_mb, d.speed_mbps
                                )),
                            );
                        } else if let Some(err) = &d.error {
                            ui.label(RichText::new(err).size(10.5).color(ACCENT_RED));
                        }
                    });
                    ui.add_space(4.0);
                }
            }

            // 4. Scrollable Results OR Hand-Picked Popular Styles
            egui::ScrollArea::vertical().id_salt("civitai_list_scroll").show(ui, |ui| {
                let results = app.civitai_results.clone();
                if !results.is_empty() {
                    ui.horizontal(|ui| {
                        ui.label(RichText::new(format!("Search Results ({})", results.len())).strong().size(12.5));
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if ui.small_button("← Back to Top Picks").clicked() {
                                app.civitai_results.clear();
                            }
                        });
                    });
                    ui.add_space(4.0);
                    for item in &results {
                        card_frame().show(ui, |ui| {
                            ui.horizontal(|ui| {
                                ui.vertical(|ui| {
                                    ui.horizontal(|ui| {
                                        ui.label(RichText::new(&item.name).strong().size(12.5));
                                        badge(ui, friendly_style_kind(&item.model_type), ACCENT_PURPLE);
                                        badge(ui, &friendly_family_label(&item.family, &item.base_model), ACCENT_BLUE);
                                    });
                                    ui.label(
                                        RichText::new(format!(
                                            "{:.0} MB · {} downloads",
                                            item.size_mb, item.downloads
                                        ))
                                        .size(10.5)
                                        .color(TEXT_MUTED),
                                    );
                                });
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                    if ui.add(primary_button("⬇ Install")).clicked() {
                                        app.api.send(ApiCommand::InstallCivitai(json!({
                                            "version_id": item.version_id,
                                            "download_url": item.download_url,
                                            "filename": item.filename,
                                            "name": item.name,
                                            "model_type": item.model_type,
                                            "base_model": item.base_model,
                                            "target_subdir": item.target_subdir,
                                            "trained_words": item.trained_words,
                                            "size_mb": item.size_mb,
                                        })));
                                    }
                                });
                            });
                        });
                        ui.add_space(4.0);
                    }
                } else {
                    ui.label(RichText::new("⭐ Popular Hand-Picked Styles").strong().size(12.5));
                    ui.add_space(4.0);

                    let curated = app.gen_status.civitai.curated.clone();
                    for pick in &curated {
                        card_frame().show(ui, |ui| {
                            ui.horizontal(|ui| {
                                ui.vertical(|ui| {
                                    ui.horizontal(|ui| {
                                        ui.label(RichText::new(&pick.name).strong().size(12.5));
                                        badge(ui, friendly_style_kind(&pick.model_type), ACCENT_PURPLE);
                                        badge(ui, &friendly_family_label(&pick.family, &pick.base_model), ACCENT_BLUE);
                                    });
                                    ui.label(RichText::new(&pick.tagline).size(11.0).color(TEXT_MUTED));
                                });
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                    if ui.add(primary_button("⬇ Install")).clicked() {
                                        app.api.send(ApiCommand::InstallCivitai(json!({
                                            "url_or_id": pick.model_id.to_string(),
                                            "name": pick.name,
                                        })));
                                    }
                                });
                            });
                        });
                        ui.add_space(4.0);
                    }
                }
            });
        });
    if !open {
        app.show_civitai_modal = false;
    }
}
