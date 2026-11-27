use egui::{Color32, CornerRadius, Margin, Pos2, Rect, RichText, Sense, Stroke, Style, Vec2, Visuals};

pub const BG_ROOT: Color32 = Color32::from_rgb(8, 10, 16);
pub const BG_PANEL: Color32 = Color32::from_rgb(15, 19, 30);
pub const BG_CARD: Color32 = Color32::from_rgb(22, 28, 43);
pub const BG_ELEVATED: Color32 = Color32::from_rgb(31, 39, 59);
pub const BORDER_SUBTLE: Color32 = Color32::from_rgb(38, 48, 70);
pub const TEXT_PRIMARY: Color32 = Color32::from_rgb(240, 244, 250);
pub const TEXT_MUTED: Color32 = Color32::from_rgb(148, 163, 184);
pub const ACCENT_BLUE: Color32 = Color32::from_rgb(59, 130, 246);
pub const ACCENT_INDIGO: Color32 = Color32::from_rgb(99, 102, 241);
pub const ACCENT_PURPLE: Color32 = Color32::from_rgb(139, 92, 246);
pub const ACCENT_CYAN: Color32 = Color32::from_rgb(6, 182, 212);
pub const ACCENT_GREEN: Color32 = Color32::from_rgb(16, 185, 129);
pub const ACCENT_AMBER: Color32 = Color32::from_rgb(245, 158, 11);
pub const ACCENT_RED: Color32 = Color32::from_rgb(239, 68, 68);

pub fn apply_studio_theme(ctx: &egui::Context) {
    let mut style = Style::default();
    let mut visuals = Visuals::dark();

    visuals.dark_mode = true;
    visuals.panel_fill = BG_PANEL;
    visuals.window_fill = BG_PANEL;
    visuals.extreme_bg_color = BG_ROOT;
    visuals.faint_bg_color = BG_CARD;
    visuals.code_bg_color = BG_ROOT;
    visuals.window_stroke = Stroke::new(1.0_f32, BORDER_SUBTLE);
    visuals.window_corner_radius = CornerRadius::same(12);

    visuals.selection.bg_fill = Color32::from_rgba_unmultiplied(59, 130, 246, 95);
    visuals.selection.stroke = Stroke::new(1.0_f32, ACCENT_BLUE);

    visuals.widgets.noninteractive.bg_fill = BG_CARD;
    visuals.widgets.noninteractive.weak_bg_fill = BG_PANEL;
    visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0_f32, BORDER_SUBTLE);
    visuals.widgets.noninteractive.fg_stroke = Stroke::new(1.0_f32, TEXT_PRIMARY);
    visuals.widgets.noninteractive.corner_radius = CornerRadius::same(8);

    visuals.widgets.inactive.bg_fill = BG_ELEVATED;
    visuals.widgets.inactive.weak_bg_fill = BG_CARD;
    visuals.widgets.inactive.bg_stroke = Stroke::new(1.0_f32, BORDER_SUBTLE);
    visuals.widgets.inactive.fg_stroke = Stroke::new(1.0_f32, TEXT_PRIMARY);
    visuals.widgets.inactive.corner_radius = CornerRadius::same(8);

    visuals.widgets.hovered.bg_fill = Color32::from_rgb(42, 53, 79);
    visuals.widgets.hovered.weak_bg_fill = BG_ELEVATED;
    visuals.widgets.hovered.bg_stroke = Stroke::new(1.0_f32, ACCENT_BLUE);
    visuals.widgets.hovered.fg_stroke = Stroke::new(1.5_f32, Color32::WHITE);
    visuals.widgets.hovered.corner_radius = CornerRadius::same(8);

    visuals.widgets.active.bg_fill = ACCENT_BLUE;
    visuals.widgets.active.weak_bg_fill = Color32::from_rgb(37, 99, 235);
    visuals.widgets.active.bg_stroke = Stroke::new(1.0_f32, Color32::WHITE);
    visuals.widgets.active.fg_stroke = Stroke::new(1.5_f32, Color32::WHITE);
    visuals.widgets.active.corner_radius = CornerRadius::same(8);

    visuals.widgets.open.bg_fill = BG_ELEVATED;
    visuals.widgets.open.weak_bg_fill = BG_CARD;
    visuals.widgets.open.bg_stroke = Stroke::new(1.0_f32, ACCENT_BLUE);
    visuals.widgets.open.corner_radius = CornerRadius::same(8);

    style.visuals = visuals;
    style.spacing.item_spacing = egui::vec2(7.0, 7.0);
    style.spacing.button_padding = egui::vec2(10.0, 5.5);
    style.spacing.window_margin = Margin::same(14);
    ctx.set_style(style);
}

pub fn lerp_color(a: Color32, b: Color32, t: f32) -> Color32 {
    let k = t.clamp(0.0, 1.0);
    let mix = |x: u8, y: u8| -> u8 { ((x as f32) + ((y as f32) - (x as f32)) * k).round().clamp(0.0, 255.0) as u8 };
    Color32::from_rgba_unmultiplied(mix(a.r(), b.r()), mix(a.g(), b.g()), mix(a.b(), b.b()), mix(a.a(), b.a()))
}

pub fn card_frame() -> egui::Frame {
    egui::Frame::new()
        .fill(BG_CARD)
        .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
        .corner_radius(CornerRadius::same(11))
        .inner_margin(Margin::same(12))
}

pub fn card_frame_soft() -> egui::Frame {
    egui::Frame::new()
        .fill(Color32::from_rgb(17, 22, 34))
        .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
        .corner_radius(CornerRadius::same(10))
        .inner_margin(Margin::symmetric(10, 8))
}

pub fn badge(ui: &mut egui::Ui, text: &str, color: Color32) {
    let bg = Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 34);
    egui::Frame::new()
        .fill(bg)
        .stroke(Stroke::new(1.0_f32, Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 115)))
        .corner_radius(CornerRadius::same(10))
        .inner_margin(Margin::symmetric(8, 2))
        .show(ui, |ui| {
            ui.label(RichText::new(text).size(10.5).strong().color(color));
        });
}

/// Animated gently pulsing live status pill (uses 60fps breathing opacity when active).
pub fn pulsing_status_pill(ui: &mut egui::Ui, text: &str, color: Color32, pulse: bool) {
    let bg = Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 28);
    egui::Frame::new()
        .fill(bg)
        .stroke(Stroke::new(1.0_f32, Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 110)))
        .corner_radius(CornerRadius::same(12))
        .inner_margin(Margin::symmetric(8, 3))
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.spacing_mut().item_spacing.x = 5.0;
                let (dot_r, _) = ui.allocate_exact_size(Vec2::splat(8.0), Sense::hover());
                let alpha = if pulse {
                    let t = ui.ctx().input(|i| i.time);
                    ui.ctx().request_repaint_after(std::time::Duration::from_millis(50));
                    (0.50 + 0.50 * (t * 3.2).sin() as f32).clamp(0.35, 1.0)
                } else {
                    1.0
                };
                if pulse {
                    let halo = Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), (70.0 * alpha) as u8);
                    ui.painter().circle_filled(dot_r.center(), 4.8, halo);
                }
                let core = Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), (255.0 * alpha) as u8);
                ui.painter().circle_filled(dot_r.center(), 3.0, core);
                ui.label(RichText::new(text).size(10.5).strong().color(color));
            });
        });
}

/// Smooth GPU-animated sliding segmented control (pill indicator slides effortlessly between tabs).
pub fn animated_segmented_bar(
    ui: &mut egui::Ui,
    id_salt: &str,
    items: &[&str],
    active_idx: usize,
    accent: Color32,
) -> Option<usize> {
    if items.is_empty() {
        return None;
    }
    let count = items.len();
    let active = active_idx.min(count - 1);
    let total_w = ui.available_width().max((count as f32) * 70.0);
    let height = 34.0;
    let (rect, _) = ui.allocate_exact_size(Vec2::new(total_w, height), Sense::hover());
    let painter = ui.painter_at(rect);

    painter.rect_filled(rect, 11.0, BG_ROOT);
    painter.rect_stroke(rect, 11.0, Stroke::new(1.0_f32, BORDER_SUBTLE), egui::StrokeKind::Inside);

    let inner = rect.shrink(3.0);
    let seg_w = inner.width() / (count as f32);
    let target_x = inner.left() + seg_w * (active as f32);
    let anim_x = ui
        .ctx()
        .animate_value_with_time(ui.id().with(("seg_slide", id_salt)), target_x, 0.18);

    let pill_rect = Rect::from_min_size(Pos2::new(anim_x, inner.top()), Vec2::new(seg_w, inner.height()));
    let glow = Color32::from_rgba_unmultiplied(accent.r(), accent.g(), accent.b(), 55);
    painter.rect_filled(pill_rect.expand(1.5), 9.0, glow);
    painter.rect_filled(pill_rect, 8.0, accent);

    let mut clicked_idx: Option<usize> = None;
    for (idx, label) in items.iter().enumerate() {
        let item_rect = Rect::from_min_size(
            Pos2::new(inner.left() + seg_w * (idx as f32), inner.top()),
            Vec2::new(seg_w, inner.height()),
        );
        let resp = ui.interact(item_rect, ui.id().with(("seg_btn", id_salt, idx)), Sense::click());
        let is_act = idx == active;
        let hover_t = ui
            .ctx()
            .animate_bool_with_time(ui.id().with(("seg_hov", id_salt, idx)), resp.hovered(), 0.14);
        if !is_act && hover_t > 0.01 {
            painter.rect_filled(
                item_rect.shrink(1.0),
                8.0,
                Color32::from_rgba_unmultiplied(255, 255, 255, (14.0 * hover_t) as u8),
            );
        }
        let txt_col = if is_act {
            Color32::WHITE
        } else {
            lerp_color(TEXT_MUTED, Color32::WHITE, hover_t * 0.75)
        };
        painter.text(
            item_rect.center(),
            egui::Align2::CENTER_CENTER,
            *label,
            egui::FontId::proportional(12.0),
            txt_col,
        );
        if resp.clicked() {
            clicked_idx = Some(idx);
        }
    }
    clicked_idx
}

/// Smooth hover-lifted CTA button with subtle glow & animated tint.
pub fn animated_cta_button(
    ui: &mut egui::Ui,
    id_salt: &str,
    text: &str,
    accent: Color32,
    enabled: bool,
    height: f32,
) -> egui::Response {
    let w = ui.available_width().max(120.0);
    let (rect, resp) = ui.allocate_exact_size(Vec2::new(w, height), if enabled { Sense::click() } else { Sense::hover() });
    let painter = ui.painter_at(rect);

    let hover_t = ui
        .ctx()
        .animate_bool_with_time(ui.id().with(("cta_hov", id_salt)), enabled && resp.hovered(), 0.16);
    let press_t = ui
        .ctx()
        .animate_bool_with_time(ui.id().with(("cta_prs", id_salt)), enabled && resp.is_pointer_button_down_on(), 0.08);

    let draw_rect = rect.translate(Vec2::new(0.0, press_t * 1.2 - hover_t * 0.8));
    if enabled && hover_t > 0.02 {
        let halo = Color32::from_rgba_unmultiplied(accent.r(), accent.g(), accent.b(), (65.0 * hover_t) as u8);
        painter.rect_filled(draw_rect.expand(2.5), 12.0, halo);
    }

    let bright = lerp_color(accent, Color32::WHITE, 0.14);
    let fill = if !enabled {
        BG_ELEVATED
    } else {
        lerp_color(accent, bright, hover_t * 0.85)
    };
    painter.rect_filled(draw_rect, 10.0, fill);
    if enabled {
        let top_sheen = Rect::from_min_max(draw_rect.min, Pos2::new(draw_rect.right(), draw_rect.top() + draw_rect.height() * 0.45));
        painter.rect_filled(top_sheen, 10.0, Color32::from_rgba_unmultiplied(255, 255, 255, (18.0 + 14.0 * hover_t) as u8));
    }
    painter.rect_stroke(
        draw_rect,
        10.0,
        Stroke::new(1.0_f32, Color32::from_rgba_unmultiplied(255, 255, 255, if enabled { 45 } else { 18 })),
        egui::StrokeKind::Inside,
    );
    painter.text(
        draw_rect.center(),
        egui::Align2::CENTER_CENTER,
        text,
        egui::FontId::proportional(13.5),
        if enabled { Color32::WHITE } else { TEXT_MUTED },
    );
    resp
}

/// Smoothly interpolated progress bar with subtle animated shimmer sweep.
pub fn animated_progress_bar(ui: &mut egui::Ui, id_salt: &str, pct_0_1: f32, label: &str, accent: Color32) {
    let target = pct_0_1.clamp(0.02, 1.0);
    let anim = ui
        .ctx()
        .animate_value_with_time(ui.id().with(("prog_val", id_salt)), target, 0.25);

    let w = ui.available_width().max(120.0);
    let (rect, _) = ui.allocate_exact_size(Vec2::new(w, 16.0), Sense::hover());
    let painter = ui.painter_at(rect);

    painter.rect_filled(rect, 8.0, BG_ROOT);
    painter.rect_stroke(rect, 8.0, Stroke::new(1.0_f32, BORDER_SUBTLE), egui::StrokeKind::Inside);

    let fill_w = (rect.width() * anim).max(12.0).min(rect.width());
    let fill_rect = Rect::from_min_size(rect.min, Vec2::new(fill_w, rect.height()));
    painter.rect_filled(fill_rect, 8.0, accent);

    // Subtle moving shimmer highlight inside active bar
    let t = ui.ctx().input(|i| i.time) as f32;
    ui.ctx().request_repaint_after(std::time::Duration::from_millis(45));
    let phase = (t * 0.75) % 1.0;
    let shim_x = fill_rect.left() + phase * fill_w;
    let shim_w = (fill_w * 0.28).clamp(16.0, 56.0);
    let shim_rect = Rect::from_center_size(Pos2::new(shim_x, fill_rect.center().y), Vec2::new(shim_w, fill_rect.height()))
        .intersect(fill_rect);
    if shim_rect.width() > 2.0 {
        painter.rect_filled(shim_rect, 8.0, Color32::from_rgba_unmultiplied(255, 255, 255, 38));
    }

    if !label.is_empty() {
        painter.text(
            rect.center(),
            egui::Align2::CENTER_CENTER,
            label,
            egui::FontId::proportional(10.5),
            Color32::WHITE,
        );
    }
}

pub fn primary_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(RichText::new(text).strong().color(Color32::WHITE))
        .fill(ACCENT_BLUE)
        .corner_radius(CornerRadius::same(8))
}

pub fn danger_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(RichText::new(text).strong().color(Color32::WHITE))
        .fill(Color32::from_rgb(185, 28, 28))
        .corner_radius(CornerRadius::same(8))
}

pub fn parse_hex_color(hex: &str, fallback: Color32) -> Color32 {
    let clean = hex.trim().trim_start_matches('#');
    if clean.len() == 6 {
        if let (Ok(r), Ok(g), Ok(b)) = (
            u8::from_str_radix(&clean[0..2], 16),
            u8::from_str_radix(&clean[2..4], 16),
            u8::from_str_radix(&clean[4..6], 16),
        ) {
            return Color32::from_rgb(r, g, b);
        }
    }
    fallback
}

pub fn format_hex_color(c: Color32) -> String {
    format!("#{:02X}{:02X}{:02X}", c.r(), c.g(), c.b())
}

pub fn format_time(sec: f64) -> String {
    let s = sec.max(0.0);
    let mins = (s / 60.0).floor() as u64;
    let rem = s % 60.0;
    format!("{:02}:{:05.2}", mins, rem)
}
