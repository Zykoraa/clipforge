use egui::{Color32, CornerRadius, Margin, Stroke, Style, Visuals};

pub const BG_ROOT: Color32 = Color32::from_rgb(10, 12, 18);
pub const BG_PANEL: Color32 = Color32::from_rgb(16, 19, 28);
pub const BG_CARD: Color32 = Color32::from_rgb(23, 28, 41);
pub const BG_ELEVATED: Color32 = Color32::from_rgb(31, 38, 56);
pub const BORDER_SUBTLE: Color32 = Color32::from_rgb(44, 53, 76);
pub const TEXT_PRIMARY: Color32 = Color32::from_rgb(236, 240, 248);
pub const TEXT_MUTED: Color32 = Color32::from_rgb(148, 163, 184);
pub const ACCENT_BLUE: Color32 = Color32::from_rgb(59, 130, 246);
pub const ACCENT_PURPLE: Color32 = Color32::from_rgb(139, 92, 246);
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
    visuals.window_corner_radius = CornerRadius::same(10);

    visuals.selection.bg_fill = Color32::from_rgba_unmultiplied(59, 130, 246, 90);
    visuals.selection.stroke = Stroke::new(1.0_f32, ACCENT_BLUE);

    visuals.widgets.noninteractive.bg_fill = BG_CARD;
    visuals.widgets.noninteractive.weak_bg_fill = BG_PANEL;
    visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0_f32, BORDER_SUBTLE);
    visuals.widgets.noninteractive.fg_stroke = Stroke::new(1.0_f32, TEXT_PRIMARY);
    visuals.widgets.noninteractive.corner_radius = CornerRadius::same(6);

    visuals.widgets.inactive.bg_fill = BG_ELEVATED;
    visuals.widgets.inactive.weak_bg_fill = BG_CARD;
    visuals.widgets.inactive.bg_stroke = Stroke::new(1.0_f32, BORDER_SUBTLE);
    visuals.widgets.inactive.fg_stroke = Stroke::new(1.0_f32, TEXT_PRIMARY);
    visuals.widgets.inactive.corner_radius = CornerRadius::same(6);

    visuals.widgets.hovered.bg_fill = Color32::from_rgb(42, 52, 76);
    visuals.widgets.hovered.weak_bg_fill = BG_ELEVATED;
    visuals.widgets.hovered.bg_stroke = Stroke::new(1.0_f32, ACCENT_BLUE);
    visuals.widgets.hovered.fg_stroke = Stroke::new(1.5_f32, Color32::WHITE);
    visuals.widgets.hovered.corner_radius = CornerRadius::same(6);

    visuals.widgets.active.bg_fill = ACCENT_BLUE;
    visuals.widgets.active.weak_bg_fill = Color32::from_rgb(37, 99, 235);
    visuals.widgets.active.bg_stroke = Stroke::new(1.0_f32, Color32::WHITE);
    visuals.widgets.active.fg_stroke = Stroke::new(1.5_f32, Color32::WHITE);
    visuals.widgets.active.corner_radius = CornerRadius::same(6);

    visuals.widgets.open.bg_fill = BG_ELEVATED;
    visuals.widgets.open.weak_bg_fill = BG_CARD;
    visuals.widgets.open.bg_stroke = Stroke::new(1.0_f32, ACCENT_BLUE);
    visuals.widgets.open.corner_radius = CornerRadius::same(6);

    style.visuals = visuals;
    style.spacing.item_spacing = egui::vec2(6.0, 6.0);
    style.spacing.button_padding = egui::vec2(8.0, 4.5);
    style.spacing.window_margin = Margin::same(12);
    ctx.set_style(style);
}

pub fn card_frame() -> egui::Frame {
    egui::Frame::new()
        .fill(BG_CARD)
        .stroke(Stroke::new(1.0_f32, BORDER_SUBTLE))
        .corner_radius(CornerRadius::same(8))
        .inner_margin(Margin::same(10))
}

pub fn badge(ui: &mut egui::Ui, text: &str, color: Color32) {
    let bg = Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 36);
    egui::Frame::new()
        .fill(bg)
        .stroke(Stroke::new(1.0_f32, Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 120)))
        .corner_radius(CornerRadius::same(5))
        .inner_margin(Margin::symmetric(6, 2))
        .show(ui, |ui| {
            ui.label(egui::RichText::new(text).size(10.5).strong().color(color));
        });
}

pub fn primary_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(egui::RichText::new(text).strong().color(Color32::WHITE))
        .fill(ACCENT_BLUE)
        .corner_radius(CornerRadius::same(6))
}

pub fn danger_button(text: &str) -> egui::Button<'_> {
    egui::Button::new(egui::RichText::new(text).strong().color(Color32::WHITE))
        .fill(Color32::from_rgb(185, 28, 28))
        .corner_radius(CornerRadius::same(6))
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
