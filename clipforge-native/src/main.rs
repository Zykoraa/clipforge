#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api;
mod app;
mod backend;
mod models;
mod player;
mod theme;
mod ui;

use app::ClipForgeApp;
use backend::BackendHandle;

fn main() -> eframe::Result<()> {
    let backend = match BackendHandle::spawn_or_connect() {
        Ok(b) => b,
        Err(err) => {
            eprintln!("ClipForge startup failed: {err}");
            rfd::MessageDialog::new()
                .set_level(rfd::MessageLevel::Error)
                .set_title("ClipForge Startup Error")
                .set_description(&err)
                .show();
            return Ok(());
        }
    };

    let native_options = eframe::NativeOptions {
        renderer: eframe::Renderer::Wgpu,
        viewport: egui::ViewportBuilder::default()
            .with_title("ClipForge — Native GPU AI Video Editor & Media Studio")
            .with_inner_size([1540.0, 940.0])
            .with_min_inner_size([1100.0, 680.0])
            .with_drag_and_drop(true),
        ..Default::default()
    };

    eframe::run_native(
        "ClipForge",
        native_options,
        Box::new(move |cc| Ok(Box::new(ClipForgeApp::new(cc, backend)))),
    )
}
