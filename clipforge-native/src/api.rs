use crate::models::*;
use base64::Engine as _;
use egui::{ColorImage, Context, TextureHandle, TextureOptions};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RefSlot {
    Ref1,
    Ref2,
    Pose,
    EndFrame,
}

#[derive(Debug, Clone)]
pub enum ApiCommand {
    RefreshState,
    RefreshGenStatus,
    LoadSfxCatalog,
    ConfigureProject(Value),
    Undo,
    Redo,
    ClearTimeline,
    ImportPaths(Vec<String>),
    RemoveMedia(String),
    AnalyzeMedia { media_id: String, model_size: String },
    AddClip(Value),
    UpdateClip { clip_id: String, body: Value },
    SplitClip { clip_id: String, timeline_sec: f64 },
    RemoveClip(String),
    ReorderClips(Vec<String>),
    ExtractEndFrame(String),
    SmoothClipFps { clip_id: String, target_fps: f64, prefer_rife: bool },
    SmartStitch(Value),
    AutoSubtitle(Value),
    SetSubtitleStyle(Value),
    UpsertSubtitle(Value),
    RemoveSubtitle(String),
    SetMemeLayout(Value),
    AddAudioOverlay(Value),
    UpdateAudioOverlay { overlay_id: String, body: Value },
    RemoveAudioOverlay(String),
    PreviewSfx { sfx_id: String, volume: f32 },
    StartComfyUi,
    DownloadModel(String),
    CancelDownload(String),
    DownloadStarterPack(String),
    SearchCivitai {
        query: String,
        model_type: String,
        base_model: String,
        sort: String,
    },
    InspectCivitai(String),
    InstallCivitai(Value),
    CancelCivitai(String),
    SaveCivitaiKey(String),
    CancelJob(String),
    UploadRef { slot: RefSlot, path: PathBuf },
    GenerateImage(Value),
    GenerateVideo(Value),
    PlanSong(Value),
    GenerateMusic(Value),
    SpeakText(Value),
    DeleteAudioTrack(String),
    PolishImage { filename: String, scale: u32 },
    DetailFaces { filename: String },
    SwapFaces { filename: String, body: Value },
    DeleteGalleryImage(String),
    DeleteVaultVideo(String),
    ExtractVaultEndFrame { filename: String },
    SmoothVaultVideo { filename: String },
    StitchVaultVideos { filenames: Vec<String> },
    DirectorExpand(Value),
    DirectorPull { model_tag: String },
    DirectorStoryboard(Value),
    RenderStoryboard(Value),
    SaveLoraTrigger { name: String, trigger: String },
    UploadLora(PathBuf),
    CreateCast {
        name: String,
        photo_path: PathBuf,
        voice_path: Option<PathBuf>,
        voice_ref_text: String,
    },
    AddCastAngle { cast_id: String, photo_path: PathBuf },
    DeleteCastAngle { cast_id: String, index: usize },
    DeleteCast(String),
    CloneVoice(Value),
    TalkSyncVideo(Value),
    RenderVideo(Value),
    LoadImageKey { key: String, path: PathBuf, max_dim: u32 },
}

#[derive(Debug)]
pub enum ApiEvent {
    StateUpdated(ProjectSummary),
    GenStatusUpdated(GeneratorStatus),
    SfxCatalogLoaded(Vec<SfxItem>),
    WsConnected(bool),
    Toast { message: String, kind: ToastKind },
    Log(String),
    RefUploaded { slot: RefSlot, path: String, filename: String },
    EndFrameExtracted { path: String, filename: String },
    VaultEndFrameExtracted { path: String, filename: String, parent_video: String },
    VaultVideoCreated { filename: String },
    DirectorExpanded(DirectorExpandResponse),
    StoryboardPlanned { beats: Vec<StoryboardBeat>, source: String },
    SongPlanned { title: String, tags: String, lyrics: String, bpm: u32 },
    RenderCompleted(RenderReport),
    StitchCompleted(StitchReport),
    ImagePolished { filename: String, engine: String, width: u32, height: u32 },
    CivitaiSearchResults(Vec<CivitaiModelItem>),
    CivitaiInspected(CivitaiModelItem),
    ImageDecoded { key: String, image: ColorImage },
    ActionDone(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToastKind {
    Info,
    Success,
    Warning,
    Error,
}

pub struct ApiBridge {
    cmd_tx: Sender<ApiCommand>,
    pub ev_rx: Receiver<ApiEvent>,
    img_tx: Sender<(String, PathBuf, u32)>,
    pending_images: HashSet<String>,
    pub textures: HashMap<String, TextureHandle>,
    pub preview_textures: HashMap<String, (String, TextureHandle)>,
}

impl ApiBridge {
    pub fn spawn(base_url: String, ws_url: String, token: String, ctx: Context) -> Self {
        let (cmd_tx, cmd_rx) = mpsc::channel::<ApiCommand>();
        let (ev_tx, ev_rx) = mpsc::channel::<ApiEvent>();
        let (img_tx, img_rx) = mpsc::channel::<(String, PathBuf, u32)>();

        // 1. Live WebSocket sync worker (streams MCP edits instantaneously into native UI)
        {
            let ws_full = format!("{ws_url}?token={}", urlencoding::encode(&token));
            let ev_tx = ev_tx.clone();
            let ctx = ctx.clone();
            std::thread::spawn(move || loop {
                match tungstenite::connect(&ws_full) {
                    Ok((mut socket, _)) => {
                        let _ = ev_tx.send(ApiEvent::WsConnected(true));
                        let _ = ev_tx.send(ApiEvent::Log("Connected to ClipForge Live MCP Sync.".into()));
                        ctx.request_repaint();
                        while let Ok(msg) = socket.read() {
                            if let tungstenite::Message::Text(txt) = msg {
                                if let Ok(v) = serde_json::from_str::<Value>(&txt) {
                                    if v.get("type").and_then(|x| x.as_str()) == Some("state_updated") {
                                        if let Some(d) = v.get("data") {
                                            if let Ok(sum) = serde_json::from_value::<ProjectSummary>(d.clone()) {
                                                let _ = ev_tx.send(ApiEvent::StateUpdated(sum));
                                                ctx.request_repaint();
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        let _ = ev_tx.send(ApiEvent::WsConnected(false));
                        ctx.request_repaint();
                    }
                    Err(_) => {
                        let _ = ev_tx.send(ApiEvent::WsConnected(false));
                    }
                }
                std::thread::sleep(Duration::from_millis(1500));
            });
        }

        // 2. Local image decode worker pool (fast disk thumbnail / gallery / cast decoding off UI thread)
        {
            let ev_tx = ev_tx.clone();
            let ctx = ctx.clone();
            std::thread::spawn(move || {
                while let Ok((key, path, max_dim)) = img_rx.recv() {
                    if let Some(ci) = decode_image_file(&path, max_dim) {
                        let _ = ev_tx.send(ApiEvent::ImageDecoded { key, image: ci });
                        ctx.request_repaint();
                    }
                }
            });
        }

        // 3. HTTP Command Dispatcher (spawns short-lived threads for slow ops so UI never blocks!)
        {
            let base_url = Arc::new(base_url);
            let token = Arc::new(token);
            let ev_tx = ev_tx.clone();
            let ctx = ctx.clone();
            std::thread::spawn(move || {
                while let Ok(cmd) = cmd_rx.recv() {
                    let base_url = Arc::clone(&base_url);
                    let token = Arc::clone(&token);
                    let ev_tx = ev_tx.clone();
                    let ctx = ctx.clone();
                    std::thread::spawn(move || {
                        execute_command(&base_url, &token, cmd, &ev_tx);
                        ctx.request_repaint();
                    });
                }
            });
        }

        Self {
            cmd_tx,
            ev_rx,
            img_tx,
            pending_images: HashSet::new(),
            textures: HashMap::new(),
            preview_textures: HashMap::new(),
        }
    }

    pub fn send(&self, cmd: ApiCommand) {
        let _ = self.cmd_tx.send(cmd);
    }

    pub fn get_or_load_image(
        &mut self,
        key: &str,
        path: &str,
        max_dim: u32,
    ) -> Option<&TextureHandle> {
        if self.textures.contains_key(key) {
            return self.textures.get(key);
        }
        if !path.is_empty() && !self.pending_images.contains(key) {
            self.pending_images.insert(key.to_string());
            let _ = self.img_tx.send((key.to_string(), PathBuf::from(path), max_dim));
        }
        None
    }

    pub fn store_decoded_image(&mut self, ctx: &Context, key: String, image: ColorImage) {
        self.pending_images.remove(&key);
        let tex = ctx.load_texture(&key, image, TextureOptions::LINEAR);
        self.textures.insert(key, tex);
    }

    pub fn invalidate_image_key(&mut self, key: &str) {
        self.textures.remove(key);
        self.pending_images.remove(key);
    }

    /// Decode a base64 `data:image/...;base64,...` live latent preview from ComfyUI WebSocket into a GPU texture.
    pub fn get_live_preview_texture(
        &mut self,
        ctx: &Context,
        job_id: &str,
        data_url: &str,
    ) -> Option<&TextureHandle> {
        let needs_decode = match self.preview_textures.get(job_id) {
            Some((prev_url, _)) => prev_url != data_url,
            None => true,
        };
        if needs_decode {
            if let Some((_, b64)) = data_url.split_once(',') {
                if let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(b64.trim()) {
                    if let Ok(dyn_img) = image::load_from_memory(&bytes) {
                        let rgba = dyn_img.to_rgba8();
                        let size = [rgba.width() as usize, rgba.height() as usize];
                        let ci = ColorImage::from_rgba_unmultiplied(size, rgba.as_raw());
                        let tex = ctx.load_texture(
                            format!("live_prev_{job_id}"),
                            ci,
                            TextureOptions::LINEAR,
                        );
                        self.preview_textures
                            .insert(job_id.to_string(), (data_url.to_string(), tex));
                    }
                }
            }
        }
        self.preview_textures.get(job_id).map(|(_, t)| t)
    }
}

fn decode_image_file(path: &Path, max_dim: u32) -> Option<ColorImage> {
    if !path.exists() {
        return None;
    }
    let img = image::open(path).ok()?;
    let resized = if max_dim > 0 && (img.width() > max_dim || img.height() > max_dim) {
        img.thumbnail(max_dim, max_dim)
    } else {
        img
    };
    let rgba = resized.to_rgba8();
    let size = [rgba.width() as usize, rgba.height() as usize];
    Some(ColorImage::from_rgba_unmultiplied(size, rgba.as_raw()))
}

fn make_client(timeout_sec: u64) -> reqwest::blocking::Client {
    reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(timeout_sec))
        .build()
        .unwrap_or_else(|_| reqwest::blocking::Client::new())
}

fn api_error(resp: reqwest::blocking::Response) -> String {
    let status = resp.status();
    if let Ok(v) = resp.json::<Value>() {
        if let Some(d) = v.get("detail").and_then(|x| x.as_str()) {
            return d.to_string();
        }
    }
    format!("HTTP {status}")
}

fn emit_err(tx: &Sender<ApiEvent>, msg: String) {
    let _ = tx.send(ApiEvent::Toast {
        message: msg.clone(),
        kind: ToastKind::Error,
    });
    let _ = tx.send(ApiEvent::Log(format!("Error: {msg}")));
}

fn emit_ok(tx: &Sender<ApiEvent>, msg: impl Into<String>) {
    let m = msg.into();
    let _ = tx.send(ApiEvent::Toast {
        message: m.clone(),
        kind: ToastKind::Success,
    });
    let _ = tx.send(ApiEvent::Log(m));
}

fn post_json_val(
    base: &str,
    tok: &str,
    path: &str,
    body: &Value,
    timeout_sec: u64,
) -> Result<Value, String> {
    let client = make_client(timeout_sec);
    let resp = client
        .post(format!("{base}{path}"))
        .header("X-ClipForge-Token", tok)
        .json(body)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(api_error(resp));
    }
    resp.json::<Value>().map_err(|e| e.to_string())
}

fn patch_json_val(base: &str, tok: &str, path: &str, body: &Value) -> Result<Value, String> {
    let client = make_client(60);
    let resp = client
        .patch(format!("{base}{path}"))
        .header("X-ClipForge-Token", tok)
        .json(body)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(api_error(resp));
    }
    resp.json::<Value>().map_err(|e| e.to_string())
}

fn get_json_val(base: &str, tok: &str, path: &str, timeout_sec: u64) -> Result<Value, String> {
    let client = make_client(timeout_sec);
    let resp = client
        .get(format!("{base}{path}"))
        .header("X-ClipForge-Token", tok)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(api_error(resp));
    }
    resp.json::<Value>().map_err(|e| e.to_string())
}

fn delete_json_val(base: &str, tok: &str, path: &str) -> Result<Value, String> {
    let client = make_client(60);
    let resp = client
        .delete(format!("{base}{path}"))
        .header("X-ClipForge-Token", tok)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(api_error(resp));
    }
    resp.json::<Value>().map_err(|e| e.to_string())
}

fn push_summary(tx: &Sender<ApiEvent>, v: Value) {
    if let Ok(sum) = serde_json::from_value::<ProjectSummary>(v) {
        let _ = tx.send(ApiEvent::StateUpdated(sum));
    }
}

fn execute_command(base: &str, tok: &str, cmd: ApiCommand, tx: &Sender<ApiEvent>) {
    match cmd {
        ApiCommand::RefreshState => {
            if let Ok(v) = get_json_val(base, tok, "/api/state", 15) {
                push_summary(tx, v);
            }
        }
        ApiCommand::RefreshGenStatus => {
            if let Ok(v) = get_json_val(base, tok, "/api/generate/status", 20) {
                if let Ok(st) = serde_json::from_value::<GeneratorStatus>(v) {
                    let _ = tx.send(ApiEvent::GenStatusUpdated(st));
                }
            }
        }
        ApiCommand::LoadSfxCatalog => {
            if let Ok(v) = get_json_val(base, tok, "/api/sfx/catalog", 15) {
                if let Some(arr) = v.get("sfx") {
                    if let Ok(items) = serde_json::from_value::<Vec<SfxItem>>(arr.clone()) {
                        let _ = tx.send(ApiEvent::SfxCatalogLoaded(items));
                    }
                }
            }
        }
        ApiCommand::ConfigureProject(body) => match post_json_val(base, tok, "/api/project/configure", &body, 30) {
            Ok(v) => push_summary(tx, v),
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::Undo => match post_json_val(base, tok, "/api/project/undo", &json!({}), 30) {
            Ok(v) => {
                push_summary(tx, v);
                let _ = tx.send(ApiEvent::Log("Undid last action.".into()));
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::Redo => match post_json_val(base, tok, "/api/project/redo", &json!({}), 30) {
            Ok(v) => {
                push_summary(tx, v);
                let _ = tx.send(ApiEvent::Log("Redid action.".into()));
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::ClearTimeline => match post_json_val(base, tok, "/api/timeline/clear", &json!({}), 30) {
            Ok(v) => {
                push_summary(tx, v);
                let _ = tx.send(ApiEvent::Log("Cleared timeline.".into()));
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::ImportPaths(paths) => {
            let count = paths.len();
            match post_json_val(base, tok, "/api/media/import", &json!({ "paths": paths }), 120) {
                Ok(v) => {
                    push_summary(tx, v);
                    emit_ok(tx, format!("Imported {count} media file(s)."));
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::RemoveMedia(id) => {
            let p = format!("/api/media/{}", urlencoding::encode(&id));
            match delete_json_val(base, tok, &p) {
                Ok(v) => push_summary(tx, v),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::AnalyzeMedia { media_id, model_size } => {
            let p = format!("/api/media/{}/analyze", urlencoding::encode(&media_id));
            let body = json!({
                "detect_silence": true,
                "detect_scenes": true,
                "transcribe": true,
                "model_size": model_size,
            });
            match post_json_val(base, tok, &p, &body, 600) {
                Ok(v) => {
                    push_summary(tx, v);
                    emit_ok(tx, "Analyzed & transcribed media clip.");
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("analyze".into()));
        }
        ApiCommand::AddClip(body) => match post_json_val(base, tok, "/api/timeline/clip", &body, 30) {
            Ok(v) => {
                push_summary(tx, v);
                let _ = tx.send(ApiEvent::Log("Added clip to timeline.".into()));
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::UpdateClip { clip_id, body } => {
            let p = format!("/api/timeline/clip/{}", urlencoding::encode(&clip_id));
            match patch_json_val(base, tok, &p, &body) {
                Ok(v) => push_summary(tx, v),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::SplitClip { clip_id, timeline_sec } => {
            let p = format!("/api/timeline/clip/{}/split", urlencoding::encode(&clip_id));
            match post_json_val(base, tok, &p, &json!({ "split_at_timeline_sec": timeline_sec }), 30) {
                Ok(v) => {
                    push_summary(tx, v);
                    let _ = tx.send(ApiEvent::Log(format!("Split clip at {timeline_sec:.2}s.")));
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::RemoveClip(clip_id) => {
            let p = format!("/api/timeline/clip/{}", urlencoding::encode(&clip_id));
            match delete_json_val(base, tok, &p) {
                Ok(v) => push_summary(tx, v),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::ReorderClips(ids) => {
            match post_json_val(base, tok, "/api/timeline/reorder", &json!({ "clip_ids": ids }), 30) {
                Ok(v) => push_summary(tx, v),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::ExtractEndFrame(clip_id) => {
            let p = format!("/api/timeline/clip/{}/end-frame", urlencoding::encode(&clip_id));
            match post_json_val(base, tok, &p, &json!({}), 60) {
                Ok(v) => {
                    let path = v.get("image_path").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let filename = v.get("filename").and_then(|x| x.as_str()).unwrap_or("end_frame.png").to_string();
                    if !path.is_empty() {
                        let _ = tx.send(ApiEvent::EndFrameExtracted { path, filename });
                    }
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::SmoothClipFps { clip_id, target_fps, prefer_rife } => {
            let p = format!("/api/timeline/clip/{}/smooth-fps", urlencoding::encode(&clip_id));
            match post_json_val(base, tok, &p, &json!({ "target_fps": target_fps, "prefer_rife": prefer_rife }), 360) {
                Ok(v) => {
                    if let Some(st) = v.get("state") {
                        push_summary(tx, st.clone());
                    }
                    let eng = v.get("smooth").and_then(|s| s.get("engine")).and_then(|x| x.as_str()).unwrap_or("32fps");
                    emit_ok(tx, format!("Smoothed clip to {target_fps:.0}fps via {eng}!"));
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("smooth".into()));
        }
        ApiCommand::SmartStitch(body) => {
            match post_json_val(base, tok, "/api/timeline/smart-stitch", &body, 600) {
                Ok(v) => {
                    if let Some(st) = v.get("state") {
                        push_summary(tx, st.clone());
                    }
                    if let Some(rep) = v.get("stitch_report") {
                        if let Ok(r) = serde_json::from_value::<StitchReport>(rep.clone()) {
                            let _ = tx.send(ApiEvent::StitchCompleted(r));
                        }
                    }
                    emit_ok(tx, "Smart Stitch complete!");
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("stitch".into()));
        }
        ApiCommand::AutoSubtitle(body) => {
            match post_json_val(base, tok, "/api/subtitles/auto", &body, 600) {
                Ok(v) => {
                    push_summary(tx, v);
                    emit_ok(tx, "Generated word-synced Whisper captions!");
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("autosub".into()));
        }
        ApiCommand::SetSubtitleStyle(body) => match post_json_val(base, tok, "/api/subtitles/style", &body, 30) {
            Ok(v) => push_summary(tx, v),
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::UpsertSubtitle(body) => match post_json_val(base, tok, "/api/subtitles/entry", &body, 30) {
            Ok(v) => push_summary(tx, v),
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::RemoveSubtitle(id) => {
            let p = format!("/api/subtitles/entry/{}", urlencoding::encode(&id));
            match delete_json_val(base, tok, &p) {
                Ok(v) => push_summary(tx, v),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::SetMemeLayout(body) => match post_json_val(base, tok, "/api/meme-layout", &body, 30) {
            Ok(v) => {
                push_summary(tx, v);
                emit_ok(tx, "Applied meme layout overlay.");
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::AddAudioOverlay(body) => match post_json_val(base, tok, "/api/audio-overlays", &body, 60) {
            Ok(v) => {
                if let Some(st) = v.get("state") {
                    push_summary(tx, st.clone());
                }
                emit_ok(tx, "Dropped SFX overlay on timeline.");
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::UpdateAudioOverlay { overlay_id, body } => {
            let p = format!("/api/audio-overlays/{}", urlencoding::encode(&overlay_id));
            match patch_json_val(base, tok, &p, &body) {
                Ok(v) => {
                    push_summary(tx, v);
                    emit_ok(tx, "Updated SFX overlay.");
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::RemoveAudioOverlay(id) => {
            let p = format!("/api/audio-overlays/{}", urlencoding::encode(&id));
            match delete_json_val(base, tok, &p) {
                Ok(v) => push_summary(tx, v),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::PreviewSfx { sfx_id, volume } => {
            let client = make_client(15);
            let url = format!("{base}/api/sfx/preview/{}", urlencoding::encode(&sfx_id));
            if let Ok(resp) = client.get(&url).header("X-ClipForge-Token", tok).send() {
                if let Ok(bytes) = resp.bytes() {
                    let cursor = std::io::Cursor::new(bytes.to_vec());
                    if let Ok((_stream, handle)) = rodio::OutputStream::try_default() {
                        if let Ok(sink) = rodio::Sink::try_new(&handle) {
                            sink.set_volume(volume.clamp(0.05, 1.5));
                            if let Ok(src) = rodio::Decoder::new_wav(cursor) {
                                sink.append(src);
                                sink.sleep_until_end();
                            }
                        }
                    }
                }
            }
        }
        ApiCommand::StartComfyUi => {
            match post_json_val(base, tok, "/api/generate/start-comfyui", &json!({}), 90) {
                Ok(_) => {
                    emit_ok(tx, "Local ComfyUI engine is online (127.0.0.1:8188).");
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("start_comfy".into()));
        }
        ApiCommand::DownloadModel(model_id) => {
            let p = format!("/api/generate/models/{}/download", urlencoding::encode(&model_id));
            match post_json_val(base, tok, &p, &json!({}), 30) {
                Ok(_) => {
                    emit_ok(tx, format!("Started resumable download for {model_id}."));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::CancelDownload(model_id) => {
            let p = format!("/api/generate/models/{}/cancel", urlencoding::encode(&model_id));
            match post_json_val(base, tok, &p, &json!({}), 30) {
                Ok(_) => {
                    let _ = tx.send(ApiEvent::Toast {
                        message: format!("Paused download for {model_id} (.part saved)."),
                        kind: ToastKind::Warning,
                    });
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::DownloadStarterPack(pack_id) => {
            let p = format!("/api/starter-pack/{}/download", urlencoding::encode(&pack_id));
            match post_json_val(base, tok, &p, &json!({}), 30) {
                Ok(_) => {
                    emit_ok(tx, format!("Downloading starter pack '{pack_id}' in background..."));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::SearchCivitai { query, model_type, base_model, sort } => {
            let mut qs = vec![
                format!("q={}", urlencoding::encode(&query)),
                format!("sort={}", urlencoding::encode(&sort)),
                "limit=18".to_string(),
            ];
            if !model_type.is_empty() && model_type != "All" {
                qs.push(format!("model_type={}", urlencoding::encode(&model_type)));
            }
            if !base_model.is_empty() && base_model != "All" {
                qs.push(format!("base_model={}", urlencoding::encode(&base_model)));
            }
            let path = format!("/api/civitai/search?{}", qs.join("&"));
            match get_json_val(base, tok, &path, 30) {
                Ok(v) => {
                    let items: Vec<CivitaiModelItem> = v
                        .get("items")
                        .and_then(|arr| serde_json::from_value(arr.clone()).ok())
                        .unwrap_or_default();
                    let _ = tx.send(ApiEvent::CivitaiSearchResults(items));
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("civitai_search".into()));
        }
        ApiCommand::InspectCivitai(url_or_id) => {
            match post_json_val(base, tok, "/api/civitai/inspect", &json!({ "url_or_id": url_or_id }), 30) {
                Ok(v) => {
                    if let Some(it) = v.get("item") {
                        if let Ok(parsed) = serde_json::from_value::<CivitaiModelItem>(it.clone()) {
                            emit_ok(tx, format!("Loaded CivitAI: {} ({})", parsed.name, parsed.base_model));
                            let _ = tx.send(ApiEvent::CivitaiInspected(parsed));
                        }
                    }
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("civitai_inspect".into()));
        }
        ApiCommand::InstallCivitai(body) => {
            match post_json_val(base, tok, "/api/civitai/install", &body, 30) {
                Ok(v) => {
                    let fname = v
                        .get("download")
                        .and_then(|d| d.get("filename"))
                        .and_then(|x| x.as_str())
                        .unwrap_or("model");
                    let sub = v
                        .get("download")
                        .and_then(|d| d.get("target_subdir"))
                        .and_then(|x| x.as_str())
                        .unwrap_or("models");
                    emit_ok(tx, format!("Installing {fname} → ComfyUI/models/{sub}/"));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::CancelCivitai(dl_id) => {
            let p = format!("/api/civitai/cancel/{}", urlencoding::encode(&dl_id));
            match post_json_val(base, tok, &p, &json!({}), 20) {
                Ok(_) => {
                    let _ = tx.send(ApiEvent::Toast {
                        message: "Paused CivitAI download (.part saved).".into(),
                        kind: ToastKind::Warning,
                    });
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::SaveCivitaiKey(key) => {
            match post_json_val(base, tok, "/api/civitai/api-key", &json!({ "api_key": key }), 15) {
                Ok(v) => {
                    let has = v.get("has_api_key").and_then(|x| x.as_bool()).unwrap_or(false);
                    emit_ok(
                        tx,
                        if has {
                            "Saved CivitAI API key locally (workspace/secrets.json)."
                        } else {
                            "Cleared saved CivitAI API key."
                        },
                    );
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::CancelJob(job_id) => {
            let p = format!("/api/generate/jobs/{}/cancel", urlencoding::encode(&job_id));
            match post_json_val(base, tok, &p, &json!({}), 30) {
                Ok(_) => {
                    let _ = tx.send(ApiEvent::Toast {
                        message: format!("Canceled GPU job {job_id}."),
                        kind: ToastKind::Warning,
                    });
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::UploadRef { slot, path } => {
            let client = make_client(60);
            let form = match reqwest::blocking::multipart::Form::new().file("file", &path) {
                Ok(f) => f,
                Err(e) => {
                    emit_err(tx, format!("Failed to read {}: {e}", path.display()));
                    return;
                }
            };
            let resp = client
                .post(format!("{base}/api/generate/upload-ref"))
                .header("X-ClipForge-Token", tok)
                .multipart(form)
                .send();
            match resp {
                Ok(r) if r.status().is_success() => {
                    if let Ok(v) = r.json::<Value>() {
                        let p = v.get("image_path").and_then(|x| x.as_str()).unwrap_or("").to_string();
                        let f = v.get("filename").and_then(|x| x.as_str()).unwrap_or("ref.png").to_string();
                        let _ = tx.send(ApiEvent::RefUploaded { slot, path: p, filename: f });
                        execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                    }
                }
                Ok(r) => emit_err(tx, api_error(r)),
                Err(e) => emit_err(tx, e.to_string()),
            }
        }
        ApiCommand::GenerateImage(body) => {
            match post_json_val(base, tok, "/api/generate/image", &body, 60) {
                Ok(v) => {
                    let model = v.get("model").and_then(|x| x.as_str()).unwrap_or("image");
                    let jid = v.get("job_id").and_then(|x| x.as_str()).unwrap_or("");
                    emit_ok(tx, format!("Queued {model} image job ({jid})."));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("generate".into()));
        }
        ApiCommand::GenerateVideo(body) => {
            match post_json_val(base, tok, "/api/generate/video", &body, 60) {
                Ok(v) => {
                    let model = v.get("model").and_then(|x| x.as_str()).unwrap_or("video");
                    let jid = v.get("job_id").and_then(|x| x.as_str()).unwrap_or("");
                    emit_ok(tx, format!("Queued {model} video job ({jid})."));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("generate".into()));
        }
        ApiCommand::PlanSong(body) => {
            match post_json_val(base, tok, "/api/music/plan", &body, 45) {
                Ok(v) => {
                    let title = v.get("title").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let first = v.get("takes").and_then(|t| t.as_array()).and_then(|a| a.first());
                    let tags = first.and_then(|f| f.get("tags")).and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let lyrics = first.and_then(|f| f.get("lyrics")).and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let bpm = first.and_then(|f| f.get("bpm")).and_then(|x| x.as_u64()).unwrap_or(120) as u32;
                    let _ = tx.send(ApiEvent::SongPlanned { title, tags, lyrics, bpm });
                    emit_ok(tx, "Wrote lyrics & style — tweak anything or click Create!");
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("plan_song".into()));
        }
        ApiCommand::GenerateMusic(body) => {
            match post_json_val(base, tok, "/api/generate/music", &body, 60) {
                Ok(v) => {
                    let vars = v.get("variations").and_then(|x| x.as_u64()).unwrap_or(1);
                    let msg = if vars > 1 {
                        format!("Composing {vars} different song versions offline...")
                    } else {
                        "Composing song offline...".into()
                    };
                    emit_ok(tx, msg);
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("generate".into()));
        }
        ApiCommand::SpeakText(body) => {
            match post_json_val(base, tok, "/api/voice/speak", &body, 60) {
                Ok(v) => {
                    let jid = v.get("job_id").and_then(|x| x.as_str()).unwrap_or("");
                    emit_ok(tx, format!("Generating offline speech ({jid})..."));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("generate".into()));
        }
        ApiCommand::DeleteAudioTrack(filename) => {
            let p = format!("/api/generate/audio/{}", urlencoding::encode(&filename));
            match delete_json_val(base, tok, &p) {
                Ok(_) => execute_command(base, tok, ApiCommand::RefreshGenStatus, tx),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::SwapFaces { filename, body } => {
            let p = format!("/api/generate/image/{}/swap-faces", urlencoding::encode(&filename));
            match post_json_val(base, tok, &p, &body, 120) {
                Ok(v) => {
                    let fn_out = v.get("filename").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let cnt = v.get("faces_swapped").and_then(|x| x.as_u64()).unwrap_or(1);
                    if !fn_out.is_empty() {
                        let _ = tx.send(ApiEvent::ImagePolished {
                            filename: fn_out.clone(),
                            engine: "Face Lock".into(),
                            width: 0,
                            height: 0,
                        });
                    }
                    emit_ok(tx, format!("Locked {cnt} friend face(s) onto photo!"));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("face_swap".into()));
        }
        ApiCommand::PolishImage { filename, scale } => {
            let p = format!("/api/generate/image/{}/polish", urlencoding::encode(&filename));
            match post_json_val(base, tok, &p, &json!({ "scale": scale, "prefer_ai": true }), 240) {
                Ok(v) => {
                    let fn_out = v.get("filename").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let eng = v.get("engine").and_then(|x| x.as_str()).unwrap_or("HD").to_string();
                    let w = v.get("width").and_then(|x| x.as_u64()).unwrap_or(0) as u32;
                    let h = v.get("height").and_then(|x| x.as_u64()).unwrap_or(0) as u32;
                    let _ = tx.send(ApiEvent::ImagePolished {
                        filename: fn_out.clone(),
                        engine: eng.clone(),
                        width: w,
                        height: h,
                    });
                    emit_ok(tx, format!("Saved {scale}× HD ({eng}): {fn_out} ({w}×{h})"));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("polish".into()));
        }
        ApiCommand::DetailFaces { filename } => {
            let p = format!("/api/generate/image/{}/detail-faces", urlencoding::encode(&filename));
            match post_json_val(base, tok, &p, &json!({ "denoise": 0.38, "model": "auto" }), 60) {
                Ok(v) => {
                    let jid = v.get("job_id").and_then(|x| x.as_str()).unwrap_or("");
                    emit_ok(tx, format!("Queued Face Detailer job ({jid}) for {filename}."));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::DeleteGalleryImage(filename) => {
            let p = format!("/api/generate/image/{}", urlencoding::encode(&filename));
            match delete_json_val(base, tok, &p) {
                Ok(_) => execute_command(base, tok, ApiCommand::RefreshGenStatus, tx),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::DeleteVaultVideo(filename) => {
            let p = format!("/api/generate/video/{}", urlencoding::encode(&filename));
            match delete_json_val(base, tok, &p) {
                Ok(_) => execute_command(base, tok, ApiCommand::RefreshGenStatus, tx),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::ExtractVaultEndFrame { filename } => {
            let p = format!("/api/generate/video/{}/end-frame", urlencoding::encode(&filename));
            match post_json_val(base, tok, &p, &json!({}), 60) {
                Ok(v) => {
                    let path = v.get("image_path").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let fname = v.get("filename").and_then(|x| x.as_str()).unwrap_or("last_frame.png").to_string();
                    let parent = v.get("parent_video").and_then(|x| x.as_str()).unwrap_or(&filename).to_string();
                    if !path.is_empty() {
                        let _ = tx.send(ApiEvent::VaultEndFrameExtracted {
                            path,
                            filename: fname,
                            parent_video: parent,
                        });
                    }
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("continue_vid".into()));
        }
        ApiCommand::SmoothVaultVideo { filename } => {
            let p = format!("/api/generate/video/{}/smooth-fps", urlencoding::encode(&filename));
            match post_json_val(base, tok, &p, &json!({ "target_fps": 32.0, "prefer_rife": true }), 360) {
                Ok(v) => {
                    let out_fn = v.get("filename").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    emit_ok(tx, "Smoothed video motion! Ready to play.");
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                    if !out_fn.is_empty() {
                        let _ = tx.send(ApiEvent::VaultVideoCreated { filename: out_fn });
                    }
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("smooth_vid".into()));
        }
        ApiCommand::StitchVaultVideos { filenames } => {
            match post_json_val(base, tok, "/api/generate/video/stitch", &json!({ "filenames": filenames }), 300) {
                Ok(v) => {
                    let out_fn = v.get("filename").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    let parts = v.get("parts").and_then(|x| x.as_u64()).unwrap_or(2);
                    emit_ok(tx, format!("Combined {parts} clips into one continuous video!"));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                    if !out_fn.is_empty() {
                        let _ = tx.send(ApiEvent::VaultVideoCreated { filename: out_fn });
                    }
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("stitch_vid".into()));
        }
        ApiCommand::DirectorExpand(body) => {
            match post_json_val(base, tok, "/api/director/expand", &body, 120) {
                Ok(v) => {
                    if let Ok(r) = serde_json::from_value::<DirectorExpandResponse>(v) {
                        let bypass = if r.refusal_bypassed { " (refusal bypassed!)" } else { "" };
                        let msg = if let Some(mname) = r.source.strip_prefix("local_llm:") {
                            let short = mname.split('/').last().unwrap_or(mname);
                            let short_lbl = if short.len() > 36 { &short[..36] } else { short };
                            format!("✨ Rewrote prompt using local AI ({short_lbl}){bypass}")
                        } else {
                            format!("Expanded prompt via {}{bypass}", r.source)
                        };
                        emit_ok(tx, msg);
                        let _ = tx.send(ApiEvent::DirectorExpanded(r));
                        execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                    }
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("expand".into()));
        }
        ApiCommand::DirectorPull { model_tag } => {
            match post_json_val(base, tok, "/api/director/pull", &json!({ "model_tag": model_tag }), 30) {
                Ok(_) => {
                    emit_ok(tx, format!("Pulling uncensored Ollama model {model_tag}..."));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::DirectorStoryboard(body) => {
            match post_json_val(base, tok, "/api/director/storyboard", &body, 120) {
                Ok(v) => {
                    let beats: Vec<StoryboardBeat> = v
                        .get("beats")
                        .and_then(|b| serde_json::from_value(b.clone()).ok())
                        .unwrap_or_default();
                    let source = v.get("source").and_then(|s| s.as_str()).unwrap_or("director").to_string();
                    emit_ok(tx, format!("Planned {} chained beats via {source}.", beats.len()));
                    let _ = tx.send(ApiEvent::StoryboardPlanned { beats, source });
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("plan_sb".into()));
        }
        ApiCommand::RenderStoryboard(body) => {
            match post_json_val(base, tok, "/api/generate/storyboard", &body, 60) {
                Ok(v) => {
                    let jid = v.get("job_id").and_then(|x| x.as_str()).unwrap_or("");
                    emit_ok(tx, format!("Queued multi-beat chained storyboard ({jid})!"));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::SaveLoraTrigger { name, trigger } => {
            let _ = post_json_val(base, tok, "/api/loras/trigger", &json!({ "name": name, "trigger": trigger }), 15);
        }
        ApiCommand::UploadLora(path) => {
            let client = make_client(180);
            let form = match reqwest::blocking::multipart::Form::new().file("file", &path) {
                Ok(f) => f,
                Err(e) => {
                    emit_err(tx, format!("Could not read LoRA file: {e}"));
                    return;
                }
            };
            match client
                .post(format!("{base}/api/loras/upload"))
                .header("X-ClipForge-Token", tok)
                .multipart(form)
                .send()
            {
                Ok(r) if r.status().is_success() => {
                    emit_ok(tx, format!("Installed LoRA: {}", path.file_name().unwrap_or_default().to_string_lossy()));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Ok(r) => emit_err(tx, api_error(r)),
                Err(e) => emit_err(tx, e.to_string()),
            }
        }
        ApiCommand::CreateCast { name, photo_path, voice_path, voice_ref_text } => {
            let client = make_client(90);
            let mut form = reqwest::blocking::multipart::Form::new()
                .text("name", name.clone())
                .text("voice_ref_text", voice_ref_text);
            form = match form.file("photo", &photo_path) {
                Ok(f) => f,
                Err(e) => {
                    emit_err(tx, format!("Cannot read photo: {e}"));
                    return;
                }
            };
            if let Some(vp) = voice_path {
                form = match form.file("voice", &vp) {
                    Ok(f) => f,
                    Err(e) => {
                        emit_err(tx, format!("Cannot read voice clip: {e}"));
                        return;
                    }
                };
            }
            match client
                .post(format!("{base}/api/cast"))
                .header("X-ClipForge-Token", tok)
                .multipart(form)
                .send()
            {
                Ok(r) if r.status().is_success() => {
                    emit_ok(tx, format!("Saved friend profile \"{name}\"!"));
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Ok(r) => emit_err(tx, api_error(r)),
                Err(e) => emit_err(tx, e.to_string()),
            }
            let _ = tx.send(ApiEvent::ActionDone("save_cast".into()));
        }
        ApiCommand::AddCastAngle { cast_id, photo_path } => {
            let client = make_client(60);
            let form = match reqwest::blocking::multipart::Form::new().file("photo", &photo_path) {
                Ok(f) => f,
                Err(e) => {
                    emit_err(tx, format!("Cannot read angle photo: {e}"));
                    return;
                }
            };
            let url = format!("{base}/api/cast/{}/photo", urlencoding::encode(&cast_id));
            match client.post(url).header("X-ClipForge-Token", tok).multipart(form).send() {
                Ok(r) if r.status().is_success() => {
                    emit_ok(tx, "Added extra angle photo to Cast profile!");
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Ok(r) => emit_err(tx, api_error(r)),
                Err(e) => emit_err(tx, e.to_string()),
            }
        }
        ApiCommand::DeleteCastAngle { cast_id, index } => {
            let p = format!("/api/cast/{}/photo/{index}", urlencoding::encode(&cast_id));
            match delete_json_val(base, tok, &p) {
                Ok(_) => execute_command(base, tok, ApiCommand::RefreshGenStatus, tx),
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::DeleteCast(cast_id) => {
            let p = format!("/api/cast/{}", urlencoding::encode(&cast_id));
            match delete_json_val(base, tok, &p) {
                Ok(_) => {
                    emit_ok(tx, "Removed friend from Cast Book.");
                    execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
                }
                Err(e) => emit_err(tx, e),
            }
        }
        ApiCommand::CloneVoice(body) => match post_json_val(base, tok, "/api/voice/clone", &body, 60) {
            Ok(v) => {
                let jid = v.get("job_id").and_then(|x| x.as_str()).unwrap_or("");
                emit_ok(tx, format!("Queued offline F5-TTS voice clone ({jid})."));
                execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::TalkSyncVideo(body) => match post_json_val(base, tok, "/api/voice/talk-video", &body, 60) {
            Ok(v) => {
                let jid = v.get("job_id").and_then(|x| x.as_str()).unwrap_or("");
                emit_ok(tx, format!("Queued Talk-Sync talking friend video ({jid})!"));
                execute_command(base, tok, ApiCommand::RefreshGenStatus, tx);
            }
            Err(e) => emit_err(tx, e),
        },
        ApiCommand::RenderVideo(body) => {
            match post_json_val(base, tok, "/api/render", &body, 1800) {
                Ok(v) => {
                    if let Some(st) = v.get("state") {
                        push_summary(tx, st.clone());
                    }
                    if let Some(rep) = v.get("render") {
                        if let Ok(r) = serde_json::from_value::<RenderReport>(rep.clone()) {
                            emit_ok(tx, format!("Rendered MP4 ({} in {:.1}s) -> {}", r.encoder, r.render_time_sec, r.output_path));
                            let _ = tx.send(ApiEvent::RenderCompleted(r));
                        }
                    }
                }
                Err(e) => emit_err(tx, e),
            }
            let _ = tx.send(ApiEvent::ActionDone("render".into()));
        }
        ApiCommand::LoadImageKey { key, path, max_dim } => {
            if let Some(ci) = decode_image_file(&path, max_dim) {
                let _ = tx.send(ApiEvent::ImageDecoded { key, image: ci });
            }
        }
    }
}
